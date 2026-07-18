<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  getFeatureSettings, getSystemSettings, previewFeatureSettings, reloadSystemSettings,
  restoreFeatureSettings, saveFeatureSettings, saveSystemSettings,
} from '../../api/systemSettings'
import { isFeatureEnabled, loadWebFeatures } from '../../features'
import { t } from '../../i18n/runtime'
import { getPlatformAdapter } from '../../platform/runtime'
import { applySystemAppearance } from '../../settings/appearance'
import type { FeatureSetting, SystemSettingsSnapshot, SystemSettingsValues } from '../../types/systemSettings'

const emptyValues: SystemSettingsValues = {
  theme: 'light', language: 'zh_CN', theme_color: '#0078D4', iperf_path: '', fping_path: '', ipop_path: '',
  terminal_type: 'securecrt', terminal_paths: { putty: '', securecrt: '', xshell: '' },
  securecrt_sessions_root: '', ssh_port: 22, telnet_port: 23, crt_encoding: 'UTF-8',
}
const snapshot = ref<SystemSettingsSnapshot | null>(null)
const baseline = ref<SystemSettingsValues | null>(null)
const form = reactive<SystemSettingsValues>(cloneValues(emptyValues))
const features = ref<FeatureSetting[]>([])
const featureBaseline = ref('')
const featurePreview = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const dirty = computed(() => Boolean(baseline.value && JSON.stringify(form) !== JSON.stringify(baseline.value)))
const featuresDirty = computed(() => JSON.stringify(features.value) !== featureBaseline.value)
const anyDirty = computed(() => dirty.value || featuresDirty.value)
const featureSwitchAvailable = computed(() => isFeatureEnabled('web.feature_switch'))

onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => { window.removeEventListener('beforeunload', beforeUnload); if (dirty.value) restoreAppearance() })
onBeforeRouteLeave(async () => {
  if (!anyDirty.value) return true
  try {
    await ElMessageBox.confirm('放弃未保存的设置并离开？', '设置尚未保存', { type: 'warning', confirmButtonText: '放弃并离开', cancelButtonText: '留在此页' })
    cancelChanges()
    return true
  } catch { return false }
})

async function load(): Promise<void> {
  loading.value = true; error.value = ''
  try {
    acceptSnapshot(await getSystemSettings())
    await loadFeatureSettings()
  } catch (cause) { error.value = message(cause, '系统设置加载失败') }
  finally { loading.value = false }
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
    } else showError(cause, saveStage === 'feature_profile' ? '功能开关保存失败，系统设置未保存' : '系统设置保存失败')
  } finally { saving.value = false }
}

async function reload(): Promise<void> {
  loading.value = true; error.value = ''
  try { acceptSnapshot(await reloadSystemSettings()); await loadFeatureSettings(); ElMessage.success('已重载') }
  catch (cause) { restoreAppearance(); showError(cause, '重载失败') }
  finally { loading.value = false }
}

async function loadFeatureSettings(): Promise<void> {
  if (!featureSwitchAvailable.value) return
  const featureData = await getFeatureSettings()
  features.value = featureData.items
  featureBaseline.value = JSON.stringify(featureData.items)
  featurePreview.value = featureData.preview_active
}

function acceptSnapshot(value: SystemSettingsSnapshot): void {
  snapshot.value = value; baseline.value = cloneValues(value.values); Object.assign(form, cloneValues(value.values)); previewAppearance()
}
function resetDefaults(): void { if (snapshot.value) { Object.assign(form, cloneValues(snapshot.value.defaults)); previewAppearance() } }
function cancelChanges(): void { if (baseline.value) Object.assign(form, cloneValues(baseline.value)); previewAppearance(); if (featureBaseline.value) features.value = JSON.parse(featureBaseline.value) as FeatureSetting[] }
function previewAppearance(): void { applySystemAppearance(form) }
function restoreAppearance(): void { if (baseline.value) applySystemAppearance(baseline.value) }
function cloneValues(value: SystemSettingsValues): SystemSettingsValues { return { ...value, terminal_paths: { ...value.terminal_paths } } }
function beforeUnload(event: BeforeUnloadEvent): void { if (anyDirty.value) { event.preventDefault(); event.returnValue = '' } }

async function selectTool(toolId: 'iperf3' | 'fping' | 'ipop' | 'securecrt' | 'xshell' | 'putty', field?: 'iperf_path' | 'fping_path' | 'ipop_path'): Promise<void> {
  try {
    const result = await getPlatformAdapter().selectSettingsTool(toolId)
    if (result.cancelled || !result.path) return
    if (field) form[field] = result.path; else form.terminal_paths[form.terminal_type] = result.path
  } catch (cause) { showError(cause, '工具路径选择失败') }
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
    catch (cause) { restoreAppearance(); showError(cause, '保存当前设置失败，未启动 IPOP'); return }
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
  try { await ElMessageBox.confirm(text, '确认操作', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }); return true }
  catch { return false }
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
        <el-button data-testid="save" type="primary" :loading="saving" :disabled="!anyDirty" @click="save">{{ t('settings.save', '保存') }}</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />

    <section class="settings-band"><h2>{{ t('settings.appearance', '外观') }}</h2>
      <el-form class="settings-grid" label-position="top">
        <el-form-item label="主题"><el-select v-model="form.theme" data-testid="theme" @change="previewAppearance"><el-option label="浅色" value="light"/><el-option label="深色" value="dark"/><el-option label="跟随系统" value="auto"/></el-select></el-form-item>
        <el-form-item label="语言"><el-select v-model="form.language" data-testid="language" @change="previewAppearance"><el-option label="中文" value="zh_CN"/><el-option label="English" value="en_US"/></el-select></el-form-item>
        <el-form-item label="主题色"><div class="color-control"><span class="color-swatch" :style="{ background: form.theme_color }"></span><code>{{ form.theme_color }}</code><el-button data-testid="select-color" @click="selectColor">原生选择</el-button></div></el-form-item>
      </el-form>
    </section>

    <section class="settings-band"><h2>{{ t('settings.site', '当前局点') }}</h2>
      <dl class="site-facts"><div><dt>局点名称</dt><dd>{{ snapshot?.current_site_name }}</dd></div><div><dt>局点路径</dt><dd>{{ snapshot?.current_site_path }}</dd></div></dl>
      <div class="inline-actions"><el-button data-testid="open-current-site" @click="nativeAction('open_current_site')">打开局点目录</el-button></div>
    </section>

    <section class="settings-band"><h2>{{ t('settings.tools', '工具路径') }}</h2>
      <el-form label-position="top">
        <el-form-item label="iperf3.exe"><el-input v-model="form.iperf_path" readonly><template #append><el-button @click="selectTool('iperf3','iperf_path')">选择</el-button><el-button @click="form.iperf_path=''">清空</el-button></template></el-input></el-form-item>
        <el-form-item label="Fping_v3.exe"><el-input v-model="form.fping_path" readonly><template #append><el-button @click="selectTool('fping','fping_path')">选择</el-button><el-button @click="form.fping_path=''">清空</el-button></template></el-input></el-form-item>
        <el-form-item label="IPOP.EXE"><el-input v-model="form.ipop_path" readonly><template #append><el-button data-testid="select-ipop" @click="selectTool('ipop','ipop_path')">选择</el-button><el-button @click="form.ipop_path=''">清空</el-button><el-button data-testid="launch-ipop" @click="launchIpop">试启动</el-button></template></el-input></el-form-item>
      </el-form>
    </section>

    <section class="settings-band"><h2>{{ t('settings.terminal', '外部终端') }}</h2>
      <el-form class="settings-grid" label-position="top">
        <el-form-item label="终端类型"><el-select v-model="form.terminal_type" data-testid="terminal-type"><el-option label="SecureCRT" value="securecrt"/><el-option label="Xshell" value="xshell"/><el-option label="PuTTY" value="putty"/></el-select></el-form-item>
        <el-form-item class="wide" label="终端程序路径"><el-input v-model="form.terminal_paths[form.terminal_type]" readonly data-testid="terminal-path"><template #append><el-button @click="selectTool(form.terminal_type)">选择</el-button><el-button @click="form.terminal_paths[form.terminal_type]=''">清空</el-button></template></el-input></el-form-item>
        <el-form-item class="wide" label="SecureCRT 会话根目录"><el-input v-model="form.securecrt_sessions_root" readonly><template #append><el-button data-testid="select-sessions" @click="selectSessions">选择</el-button></template></el-input></el-form-item>
        <el-form-item label="默认 SSH 端口"><el-input-number v-model="form.ssh_port" :min="1" :max="65535"/></el-form-item>
        <el-form-item label="默认 Telnet 端口"><el-input-number v-model="form.telnet_port" :min="1" :max="65535"/></el-form-item>
        <el-form-item label="CRT 编码"><el-select v-model="form.crt_encoding"><el-option label="UTF-8" value="UTF-8"/><el-option label="GBK" value="GBK"/></el-select></el-form-item>
      </el-form>
    </section>

    <section v-if="featureSwitchAvailable" class="settings-band"><div class="section-heading"><h2>{{ t('settings.features', '功能开关') }}</h2><div><el-tag v-if="featurePreview" type="warning">客户配置预览中</el-tag><el-button data-testid="preview-features" @click="previewFeatures">影响预览</el-button><el-button data-testid="restore-features" @click="restoreFeatures">退出预览/恢复</el-button></div></div>
      <el-table :data="features" max-height="520"><el-table-column prop="title" label="功能" min-width="260"/><el-table-column prop="feature_id" label="ID" min-width="240"/><el-table-column label="显示" width="90"><template #default="{row}"><el-checkbox v-model="row.visible" :data-testid="`feature-visible-${row.feature_id}`"/></template></el-table-column><el-table-column label="启用" width="90"><template #default="{row}"><el-checkbox v-model="row.enabled"/></template></el-table-column><el-table-column label="客户包" width="100"><template #default="{row}"><el-checkbox v-model="row.client_package"/></template></el-table-column><el-table-column label="内部" width="90"><template #default="{row}"><el-checkbox v-model="row.internal_only"/></template></el-table-column></el-table>
    </section>
  </section>
</template>

<style scoped>
.settings-page{display:flex;flex-direction:column;gap:16px;max-width:1500px;margin:0 auto}.settings-toolbar,.settings-actions,.section-heading,.inline-actions,.color-control{display:flex;align-items:center;gap:10px}.settings-toolbar,.section-heading{justify-content:space-between}.settings-toolbar h1,.settings-band h2{margin:0}.settings-toolbar p{margin:6px 0 0;color:var(--nc-text-secondary)}.settings-actions,.inline-actions{flex-wrap:wrap;justify-content:flex-end}.settings-band{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.settings-band h2{margin-bottom:16px;font-size:17px}.settings-grid{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:0 18px}.settings-grid .wide{grid-column:span 2}.el-select,.el-input-number{width:100%}.color-swatch{width:24px;height:24px;border:1px solid var(--nc-border-strong);border-radius:4px}.site-facts{display:grid;grid-template-columns:1fr 2fr;gap:12px}.site-facts div{min-width:0}.site-facts dt{color:var(--nc-text-secondary);font-size:12px}.site-facts dd{margin:5px 0;overflow-wrap:anywhere;font-family:Consolas,monospace}.section-heading h2{margin-bottom:0}@media(max-width:900px){.settings-toolbar,.section-heading{align-items:flex-start;flex-direction:column}.settings-actions,.inline-actions{justify-content:flex-start}.settings-grid,.site-facts{grid-template-columns:1fr}.settings-grid .wide{grid-column:auto}}
</style>
