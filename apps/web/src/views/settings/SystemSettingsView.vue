<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  SETTINGS_TOOL_DEFINITIONS,
  settingsToolMismatchMessage,
  settingsToolNameMatches,
  type SettingsToolId,
} from '../../../../desktop_electron/src/shared/bridge'

import {
  getFeatureSettings, getSystemSettings, previewFeatureSettings, reloadSystemSettings,
  restoreFeatureSettings, saveFeatureSettings, saveSystemSettings,
} from '../../api/systemSettings'
import { isFeatureEnabled, loadWebFeatures } from '../../features'
import { t } from '../../i18n/runtime'
import { getPlatformAdapter } from '../../platform/runtime'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { applySystemAppearance } from '../../settings/appearance'
import { useConfirm } from '../../components/feedback/useConfirm'
import type { FeatureSetting, SystemSettingsSnapshot, SystemSettingsValues } from '../../types/systemSettings'
import SiteStoragePanel from './SiteStoragePanel.vue'
import NcExecutablePathField from '../../components/settings/NcExecutablePathField.vue'

const emptyValues: SystemSettingsValues = {
  theme: 'light', language: 'zh_CN', theme_color: '#0078D4', iperf_path: '', fping_path: '', ipop_path: '',
  terminal_type: 'securecrt', terminal_paths: { putty: '', securecrt: '', xshell: '' },
  securecrt_sessions_root: '', ssh_port: 22, telnet_port: 23, crt_encoding: 'UTF-8',
}
const { confirm } = useConfirm()
const route = useRoute()
const snapshot = ref<SystemSettingsSnapshot | null>(null)
const baseline = ref<SystemSettingsValues | null>(null)
const form = reactive<SystemSettingsValues>(cloneValues(emptyValues))
const features = ref<FeatureSetting[]>([])
const featureBaseline = ref('')
const featurePreview = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const featureError = ref('')
const featureConfigurationAllowed = ref(getPlatformAdapter().hostType !== 'electron')
const siteStorageFocused = ref(false)
const siteStoragePanel = ref<InstanceType<typeof SiteStoragePanel> | null>(null)
let siteStorageFocusTimer: ReturnType<typeof setTimeout> | undefined
const runtimeToolErrors = reactive<Partial<Record<SettingsToolId, string>>>({})
const dirty = computed(() => Boolean(baseline.value && JSON.stringify(form) !== JSON.stringify(baseline.value)))
const featuresDirty = computed(() => featureSwitchAvailable.value && JSON.stringify(features.value) !== featureBaseline.value)
const anyDirty = computed(() => dirty.value || featuresDirty.value)
const pathErrors = computed<Record<SettingsToolId, string>>(() => ({
  iperf3: toolPathError('iperf3', form.iperf_path),
  fping: toolPathError('fping', form.fping_path),
  ipop: toolPathError('ipop', form.ipop_path),
  securecrt: toolPathError('securecrt', form.terminal_paths.securecrt),
  xshell: toolPathError('xshell', form.terminal_paths.xshell),
  putty: toolPathError('putty', form.terminal_paths.putty),
}))
const hasBlockingPathError = computed(() => Object.values(pathErrors.value).some(Boolean))
const featureSwitchAvailable = computed(() => featureConfigurationAllowed.value && isFeatureEnabled('web.feature_switch'))
const featureColumns: NcTableColumn<FeatureSetting>[] = [
  { key: 'title', label: '功能', valueType: 'name', align: 'left', alignmentReason: 'description' },
  { key: 'feature_id', label: 'ID', valueType: 'description', alignmentReason: 'code' },
  { key: 'visible', label: '显示', valueType: 'status' },
  { key: 'enabled', label: '启用', valueType: 'status' },
  { key: 'client_package', label: '客户包', valueType: 'status' },
  { key: 'internal_only', label: '内部', valueType: 'status' },
]

onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  if (siteStorageFocusTimer) clearTimeout(siteStorageFocusTimer)
  if (dirty.value) restoreAppearance()
})
onBeforeRouteLeave(async () => {
  if (!anyDirty.value) return true
  try {
    if (!await confirm({ type: 'WARNING', title: '设置尚未保存', message: '放弃未保存的设置并离开？', confirmText: '放弃并离开' })) return false
    cancelChanges()
    return true
  } catch { return false }
})

async function load(): Promise<void> {
  loading.value = true; error.value = ''; featureError.value = ''
  try {
    await resolveFeatureConfigurationAvailability()
    try { acceptSnapshot(await getSystemSettings()) }
    catch (cause) { error.value = message(cause, '系统设置加载失败') }
    await loadFeatureSettingsSafely()
  } finally { loading.value = false }
}

async function save(): Promise<void> {
  if (!snapshot.value) return
  const settingsWereDirty = dirty.value
  const featuresWereDirty = featuresDirty.value
  if (featuresWereDirty && !(await confirmAction('保存功能开关会更新中央 customer profile，是否继续？'))) return
  saving.value = true; error.value = ''
  let featureSaved = false
  let saveStage: 'feature_profile' | 'feature_refresh' | 'settings' = featuresWereDirty ? 'feature_profile' : 'settings'
  try {
    if (featuresWereDirty) {
      const data = await saveFeatureSettings(features.value)
      features.value = data.items; featureBaseline.value = JSON.stringify(data.items)
      featurePreview.value = data.preview_active
      featureSaved = true
      saveStage = 'feature_refresh'
      await loadWebFeatures(true)
    }
    if (settingsWereDirty) {
      saveStage = 'settings'
      acceptSnapshot(await saveSystemSettings(cloneValues(form), snapshot.value.version))
    }
    ElMessage.success('设置已保存')
  } catch (cause) {
    restoreAppearance()
    if (featureSaved && saveStage === 'feature_refresh') {
      const pending = settingsWereDirty ? '，系统设置未保存' : ''
      error.value = `功能开关已保存，但 Gate/导航刷新失败${pending}：${message(cause, '未知错误')}`
      ElMessage.error(error.value)
    } else if (featureSaved) {
      error.value = `功能开关已保存，但系统设置保存失败：${message(cause, '未知错误')}`
      ElMessage.error(error.value)
    } else {
      assignToolError(cause)
      showError(cause, saveStage === 'feature_profile' ? '功能开关保存失败，系统设置未保存' : '系统设置保存失败')
    }
  } finally { saving.value = false }
}

async function reload(): Promise<void> {
  loading.value = true; error.value = ''; featureError.value = ''
  try {
    try { acceptSnapshot(await reloadSystemSettings()); ElMessage.success('系统设置已重载') }
    catch (cause) { restoreAppearance(); showError(cause, '重载失败') }
    await loadFeatureSettingsSafely()
  } finally { loading.value = false }
}

async function resolveFeatureConfigurationAvailability(): Promise<void> {
  const runtime = getPlatformAdapter()
  if (runtime.hostType !== 'electron') {
    featureConfigurationAllowed.value = true
    return
  }
  try {
    featureConfigurationAllowed.value = !(await runtime.getAppInfo()).isPackaged
  } catch {
    featureConfigurationAllowed.value = false
  }
  if (!featureConfigurationAllowed.value) resetFeatureConfigurationState()
}

async function loadFeatureSettingsSafely(): Promise<void> {
  featureError.value = ''
  try { await loadFeatureSettings() }
  catch (cause) { featureError.value = message(cause, '功能配置加载失败') }
}

async function loadFeatureSettings(): Promise<void> {
  if (!featureSwitchAvailable.value) {
    resetFeatureConfigurationState()
    return
  }
  const featureData = await getFeatureSettings()
  features.value = featureData.items
  featureBaseline.value = JSON.stringify(featureData.items)
  featurePreview.value = featureData.preview_active
}

function resetFeatureConfigurationState(): void {
  features.value = []
  featureBaseline.value = JSON.stringify([])
  featurePreview.value = false
  featureError.value = ''
}

function acceptSnapshot(value: SystemSettingsSnapshot): void {
  snapshot.value = value; baseline.value = cloneValues(value.values); Object.assign(form, cloneValues(value.values)); clearToolErrors(); previewAppearance()
}
function resetDefaults(): void { if (snapshot.value) { Object.assign(form, cloneValues(snapshot.value.defaults)); clearToolErrors(); previewAppearance() } }
function cancelChanges(): void { if (baseline.value) Object.assign(form, cloneValues(baseline.value)); clearToolErrors(); previewAppearance(); if (featureBaseline.value) features.value = JSON.parse(featureBaseline.value) as FeatureSetting[] }
function previewAppearance(): void { applySystemAppearance(form) }
function restoreAppearance(): void { if (baseline.value) applySystemAppearance(baseline.value) }
function cloneValues(value: SystemSettingsValues): SystemSettingsValues { return { ...value, terminal_paths: { ...value.terminal_paths } } }
function beforeUnload(event: BeforeUnloadEvent): void { if (anyDirty.value) { event.preventDefault(); event.returnValue = '' } }

async function focusSiteStorage(): Promise<void> {
  if (route.query.section !== 'site-storage') return
  await nextTick()
  const target = siteStoragePanel.value?.$el as HTMLElement | undefined
  if (!target) return
  target.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  siteStorageFocused.value = true
  if (siteStorageFocusTimer) clearTimeout(siteStorageFocusTimer)
  siteStorageFocusTimer = setTimeout(() => { siteStorageFocused.value = false }, 1600)
}

watch(
  () => [route.query.section, route.query.site_focus],
  () => { void focusSiteStorage() },
  { immediate: true },
)

async function selectTool(toolId: SettingsToolId, field?: 'iperf_path' | 'fping_path' | 'ipop_path'): Promise<void> {
  try {
    const result = await getPlatformAdapter().selectSettingsTool(toolId)
    if (result.cancelled || !result.path) return
    if (field) form[field] = result.path; else form.terminal_paths[form.terminal_type] = result.path
    clearToolError(toolId)
  } catch (cause) {
    runtimeToolErrors[toolId] = message(cause, '工具路径选择失败')
    showError(cause, '工具路径选择失败')
  }
}
function toolPathError(toolId: SettingsToolId, value: string): string {
  if (runtimeToolErrors[toolId]) return runtimeToolErrors[toolId] ?? ''
  return settingsToolNameMatches(toolId, value) ? '' : settingsToolMismatchMessage(toolId)
}
function toolPathSuccess(toolId: SettingsToolId, value: string): string {
  return value && !pathErrors.value[toolId] ? `已识别为 ${SETTINGS_TOOL_DEFINITIONS[toolId].displayName} 程序` : ''
}
function clearToolError(toolId: SettingsToolId): void { delete runtimeToolErrors[toolId]; error.value = '' }
function clearToolErrors(): void { for (const toolId of Object.keys(runtimeToolErrors) as SettingsToolId[]) delete runtimeToolErrors[toolId] }
function assignToolError(cause: unknown): void {
  const detail = message(cause, '')
  const normalized = detail.toLowerCase()
  for (const [toolId, definition] of Object.entries(SETTINGS_TOOL_DEFINITIONS) as [SettingsToolId, typeof SETTINGS_TOOL_DEFINITIONS[SettingsToolId]][]) {
    if (normalized.includes(toolId) || normalized.includes(definition.displayName.toLowerCase())) {
      runtimeToolErrors[toolId] = detail
      return
    }
  }
}
async function selectSessions(): Promise<void> {
  try {
    const result = await getPlatformAdapter().selectSettingsDirectory('securecrt_sessions_root')
    if (result.path) form.securecrt_sessions_root = result.path
  } catch (cause) { showError(cause, '会话目录选择失败') }
}
async function selectColor(): Promise<void> {
  try {
    const result = await getPlatformAdapter().selectSettingsColor()
    if (result.color) { form.theme_color = result.color; previewAppearance() }
  } catch (cause) { showError(cause, '主题色选择失败') }
}
async function nativeAction(action: 'open_settings_config' | 'open_current_site' | 'launch_ipop'): Promise<void> {
  try {
    const result = await getPlatformAdapter().executeSettingsAction(action)
    if (result.success) ElMessage.success('操作已完成')
    else showError(new Error(result.error || '操作失败'), '操作失败')
  } catch (cause) { showError(cause, '本机操作失败') }
}
async function launchIpop(): Promise<void> {
  if (!snapshot.value) return
  error.value = ''
  if (dirty.value) {
    saving.value = true
    try { acceptSnapshot(await saveSystemSettings(cloneValues(form), snapshot.value.version)) }
    catch (cause) { restoreAppearance(); assignToolError(cause); showError(cause, '保存当前设置失败，未启动 IPOP'); return }
    finally { saving.value = false }
  }
  await nativeAction('launch_ipop')
}

async function previewFeatures(): Promise<void> {
  if (!await confirmAction('预览会立即影响本次会话导航，是否继续？')) return
  try {
    const data = await previewFeatureSettings(features.value); featurePreview.value = data.preview_active; await loadWebFeatures(true)
  } catch (cause) { showError(cause, '功能开关预览失败') }
}
async function restoreFeatures(): Promise<void> {
  if (!await confirmAction('退出预览并恢复默认 customer profile 表单？')) return
  try {
    const data = await restoreFeatureSettings(); features.value = data.items; featureBaseline.value = JSON.stringify(data.items); featurePreview.value = false; await loadWebFeatures(true)
  } catch (cause) { showError(cause, '功能开关恢复失败') }
}
async function confirmAction(text: string): Promise<boolean> {
  return confirm({ type: 'WARNING', title: '确认操作', message: text, confirmText: '确认操作' })
}
function showError(cause: unknown, fallback: string): void { error.value = message(cause, fallback); ElMessage.error(error.value) }
function message(cause: unknown, fallback: string): string { return cause instanceof Error && cause.message ? cause.message : fallback }
</script>

<template>
  <section class="settings-page" v-loading="loading">
    <header class="settings-toolbar">
      <div><h1>{{ t('settings.title', '系统设置') }}</h1></div>
      <div class="settings-actions">
        <el-tag v-if="anyDirty" type="warning">{{ t('settings.unsaved', '未保存修改') }}</el-tag>
        <el-button data-testid="defaults" @click="resetDefaults">{{ t('settings.defaults', '恢复表单默认值') }}</el-button>
        <el-button data-testid="cancel" :disabled="!anyDirty" @click="cancelChanges">{{ t('settings.cancel', '取消修改') }}</el-button>
        <el-button data-testid="reload" @click="reload">{{ t('settings.reload', '重载') }}</el-button>
        <el-button data-testid="open-settings-config" @click="nativeAction('open_settings_config')">打开配置目录</el-button>
        <el-button data-testid="save" type="primary" :loading="saving" :disabled="!anyDirty || hasBlockingPathError" @click="save">{{ t('settings.save', '保存') }}</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="featureSwitchAvailable && featureError" :title="featureError" type="warning" :closable="false" />

    <section class="settings-band"><h2>{{ t('settings.appearance', '外观') }}</h2>
      <el-form class="settings-grid" label-position="top">
        <el-form-item label="主题"><el-select v-model="form.theme" data-testid="theme" @change="previewAppearance"><el-option label="浅色" value="light"/><el-option label="深色" value="dark"/><el-option label="跟随系统" value="auto"/></el-select></el-form-item>
        <el-form-item label="语言"><el-select v-model="form.language" data-testid="language" @change="previewAppearance"><el-option label="中文" value="zh_CN"/><el-option label="English" value="en_US"/></el-select></el-form-item>
        <el-form-item label="主题色"><div class="color-control"><span class="color-swatch" :style="{ background: form.theme_color }"></span><code>{{ form.theme_color }}</code><el-button data-testid="select-color" @click="selectColor">原生选择</el-button></div></el-form-item>
      </el-form>
    </section>

    <SiteStoragePanel ref="siteStoragePanel" :focused="siteStorageFocused" />

    <section class="settings-band"><h2>{{ t('settings.tools', '工具路径') }}</h2>
      <el-form label-position="top">
        <el-form-item :label="SETTINGS_TOOL_DEFINITIONS.iperf3.fieldLabel"><NcExecutablePathField v-model="form.iperf_path" :error="pathErrors.iperf3" :success="toolPathSuccess('iperf3', form.iperf_path)" @select="selectTool('iperf3','iperf_path')" @clear="clearToolError('iperf3')" /></el-form-item>
        <el-form-item :label="SETTINGS_TOOL_DEFINITIONS.fping.fieldLabel"><NcExecutablePathField v-model="form.fping_path" :error="pathErrors.fping" :success="toolPathSuccess('fping', form.fping_path)" @select="selectTool('fping','fping_path')" @clear="clearToolError('fping')" /></el-form-item>
        <el-form-item :label="SETTINGS_TOOL_DEFINITIONS.ipop.fieldLabel"><NcExecutablePathField v-model="form.ipop_path" testable select-test-id="select-ipop" test-test-id="launch-ipop" :loading="saving" :error="pathErrors.ipop" :success="toolPathSuccess('ipop', form.ipop_path)" @select="selectTool('ipop','ipop_path')" @clear="clearToolError('ipop')" @test="launchIpop" /></el-form-item>
      </el-form>
    </section>

    <section class="settings-band"><h2>{{ t('settings.terminal', '外部终端') }}</h2>
      <el-form class="settings-grid" label-position="top">
        <el-form-item label="终端类型"><el-select v-model="form.terminal_type" data-testid="terminal-type"><el-option label="SecureCRT" value="securecrt"/><el-option label="Xshell" value="xshell"/><el-option label="PuTTY" value="putty"/></el-select></el-form-item>
        <el-form-item class="wide" :label="SETTINGS_TOOL_DEFINITIONS[form.terminal_type].fieldLabel"><NcExecutablePathField v-model="form.terminal_paths[form.terminal_type]" data-testid="terminal-path" select-test-id="select-terminal-tool" clear-test-id="clear-terminal-tool" :error="pathErrors[form.terminal_type]" :success="toolPathSuccess(form.terminal_type, form.terminal_paths[form.terminal_type])" @select="selectTool(form.terminal_type)" @clear="clearToolError(form.terminal_type)" /></el-form-item>
        <el-form-item class="wide" label="SecureCRT 会话根目录"><el-input v-model="form.securecrt_sessions_root" readonly><template #append><el-button data-testid="select-sessions" @click="selectSessions">选择</el-button></template></el-input></el-form-item>
        <el-form-item label="默认 SSH 端口"><el-input-number v-model="form.ssh_port" :min="1" :max="65535"/></el-form-item>
        <el-form-item label="默认 Telnet 端口"><el-input-number v-model="form.telnet_port" :min="1" :max="65535"/></el-form-item>
        <el-form-item label="CRT 编码"><el-select v-model="form.crt_encoding"><el-option label="UTF-8" value="UTF-8"/><el-option label="GBK" value="GBK"/></el-select></el-form-item>
      </el-form>
    </section>

    <section v-if="featureSwitchAvailable" class="settings-band"><div class="section-heading"><h2>{{ t('settings.features', '功能开关') }}</h2><div><el-tag v-if="featurePreview" type="warning">客户配置预览中</el-tag><el-button data-testid="preview-features" @click="previewFeatures">影响预览</el-button><el-button data-testid="restore-features" @click="restoreFeatures">退出预览/恢复</el-button></div></div>
      <NcDataTable :data="features" :columns="featureColumns" table-id="system-feature-settings" route-key="/system-settings" max-height="520">
        <template #cell-visible="{ row }"><el-checkbox v-model="row.visible" :data-testid="`feature-visible-${row.feature_id}`" /></template>
        <template #cell-enabled="{ row }"><el-checkbox v-model="row.enabled" /></template>
        <template #cell-client_package="{ row }"><el-checkbox v-model="row.client_package" /></template>
        <template #cell-internal_only="{ row }"><el-checkbox v-model="row.internal_only" /></template>
      </NcDataTable>
    </section>
  </section>
</template>

<style scoped>
.settings-page{display:flex;flex-direction:column;gap:16px;max-width:1500px;margin:0 auto}.settings-toolbar,.settings-actions,.section-heading,.inline-actions,.color-control{display:flex;align-items:center;gap:10px}.settings-toolbar,.section-heading{justify-content:space-between}.settings-toolbar h1,.settings-band h2{margin:0}.settings-toolbar p{margin:6px 0 0;color:var(--nc-text-secondary)}.settings-actions,.inline-actions{flex-wrap:wrap;justify-content:flex-end}.settings-band{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.settings-band h2{margin-bottom:16px;font-size:17px}.settings-grid{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:0 18px}.settings-grid .wide{grid-column:span 2}.el-select,.el-input-number{width:100%}.color-swatch{width:24px;height:24px;border:1px solid var(--nc-border-strong);border-radius:4px}.site-facts{display:grid;grid-template-columns:1fr 2fr;gap:12px}.site-facts div{min-width:0}.site-facts dt{color:var(--nc-text-secondary);font-size:12px}.site-facts dd{margin:5px 0;overflow-wrap:anywhere;font-family:Consolas,monospace}.section-heading h2{margin-bottom:0}@media(max-width:900px){.settings-toolbar,.section-heading{align-items:flex-start;flex-direction:column}.settings-actions,.inline-actions{justify-content:flex-start}.settings-grid,.site-facts{grid-template-columns:1fr}.settings-grid .wide{grid-column:auto}}
</style>
