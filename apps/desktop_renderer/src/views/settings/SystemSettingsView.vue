<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  clearFeatureRuntimeOverrides, exitFeatureSettingsPreview, getFeatureRuntimeStatus, getSystemSettings,
  reloadFeatureGate, reloadSystemSettings, saveSystemSettings, getRuntimeSelfCheck,
} from '../../api/systemSettings'
import { isFeatureEnabled, loadRendererFeatures } from '../../features'
import { t } from '../../i18n/runtime'
import { getPlatformAdapter, resolveWebSocketUrl } from '../../platform/runtime'
import { applySystemAppearance } from '../../settings/appearance'
import { useConfirm } from '../../components/feedback/useConfirm'
import type { FeatureRuntimeStatus, RuntimeSelfCheckItem, RuntimeSelfCheckSnapshot, SystemSettingsSnapshot, SystemSettingsValues } from '../../types/systemSettings'
import SiteStoragePanel from './SiteStoragePanel.vue'
import DatabaseUpgradePanel from '../../components/settings/DatabaseUpgradePanel.vue'

const emptyValues: SystemSettingsValues = {
  theme: 'light', language: 'zh_CN', theme_color: '#0078D4', iperf_path: '', fping_path: '', ipop_path: '',
  terminal_type: 'securecrt', terminal_paths: { putty: '', securecrt: '', xshell: '' },
  securecrt_sessions_root: '', ssh_port: 22, telnet_port: 23, crt_encoding: 'UTF-8',
}
const { confirm } = useConfirm()
const route = useRoute()
const router = useRouter()
const snapshot = ref<SystemSettingsSnapshot | null>(null)
const baseline = ref<SystemSettingsValues | null>(null)
const form = reactive<SystemSettingsValues>(cloneValues(emptyValues))
const featureRuntimeStatus = ref<FeatureRuntimeStatus | null>(null)
const featureActionLoading = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const siteStorageFocused = ref(false)
const siteStoragePanel = ref<InstanceType<typeof SiteStoragePanel> | null>(null)
const closeToTrayEnabled = ref(true)
const closeToTrayAvailable = ref(false)
const closeToTraySaving = ref(false)
const selfCheck = ref<RuntimeSelfCheckSnapshot | null>(null)
const selfCheckLoading = ref(false)
const selfCheckError = ref('')
const desktopHost = Boolean(window.netconsoleDesktop)
let siteStorageFocusTimer: ReturnType<typeof setTimeout> | undefined
let removeCloseToTrayListener: (() => void) | undefined
let traySiteSwitchInProgress = ''
const dirty = computed(() => Boolean(baseline.value && JSON.stringify(form) !== JSON.stringify(baseline.value)))
const anyDirty = computed(() => dirty.value)
const editionLabel = computed(() => {
  const edition = featureRuntimeStatus.value?.edition
  return edition === 'customer' ? '客户版' : edition === 'full' ? '完整版' : edition === 'engineer' ? '工程版' : '开发版'
})
const runtimeStateLabel = computed(() => {
  const state = featureRuntimeStatus.value?.state
  return state === 'session_preview' ? '当前会话预览' : state === 'customer_unlocked' ? '客户版临时解锁' : '正常'
})

onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  void load()
  void loadCloseToTrayState()
  void runSelfCheck()
  removeCloseToTrayListener = window.netconsoleDesktop?.onCloseToTrayChanged?.((state) => {
    closeToTrayEnabled.value = state.enabled
    closeToTrayAvailable.value = state.available
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  if (siteStorageFocusTimer) clearTimeout(siteStorageFocusTimer)
  if (dirty.value) restoreAppearance()
  removeCloseToTrayListener?.()
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
  loading.value = true; error.value = ''
  try {
    try { acceptSnapshot(await getSystemSettings()) }
    catch (cause) { error.value = message(cause, '系统设置加载失败') }
    await loadFeatureRuntimeStatus()
  } finally { loading.value = false }
}

async function loadCloseToTrayState(): Promise<void> {
  if (!window.netconsoleDesktop?.getCloseToTrayState) return
  try {
    const state = await window.netconsoleDesktop.getCloseToTrayState()
    closeToTrayEnabled.value = state.enabled
    closeToTrayAvailable.value = state.available
  } catch {
    closeToTrayAvailable.value = false
  }
}

async function updateCloseToTray(value: boolean): Promise<void> {
  if (!window.netconsoleDesktop?.setCloseToTrayEnabled || !closeToTrayAvailable.value) return
  closeToTraySaving.value = true
  try {
    const state = await window.netconsoleDesktop.setCloseToTrayEnabled(value)
    closeToTrayEnabled.value = state.enabled
    closeToTrayAvailable.value = state.available
    ElMessage.success(value ? '已启用关闭到通知区域' : '已关闭通知区域驻留')
  } catch {
    closeToTrayEnabled.value = !value
    ElMessage.error('通知区域设置保存失败')
  } finally {
    closeToTraySaving.value = false
  }
}

async function runSelfCheck(): Promise<void> {
  selfCheckLoading.value = true
  selfCheckError.value = ''
  try {
    const backend = await getRuntimeSelfCheck()
    const items = [...backend.items]
    items.push({
      check_id: 'electron_bridge',
      title: 'Electron Bridge',
      status: window.netconsoleDesktop ? 'normal' : 'warning',
      message: window.netconsoleDesktop ? 'Electron 安全桥可用。' : '当前页面未检测到 Electron Bridge。',
      suggestion: window.netconsoleDesktop ? '' : '请从 NetConsole.exe 打开系统设置。',
    })
    items.push({
      check_id: 'utf8_api_round_trip',
      title: 'UTF-8 API 往返',
      status: backend.unicode_sample === '宁波地铁1号线 · 中文设备 · 任务已完成' ? 'normal' : 'error',
      message: backend.unicode_sample === '宁波地铁1号线 · 中文设备 · 任务已完成' ? 'REST API 中文往返正常。' : 'REST API 中文往返异常。',
      suggestion: backend.unicode_sample === '宁波地铁1号线 · 中文设备 · 任务已完成' ? '' : '保留日志并联系维护人员。',
    })
    items.push(await checkTaskWebSocket())
    selfCheck.value = { ...backend, items, status: aggregateSelfCheckStatus(items) }
  } catch (cause) {
    selfCheckError.value = message(cause, '环境自检失败')
  } finally {
    selfCheckLoading.value = false
  }
}

function checkTaskWebSocket(): Promise<RuntimeSelfCheckItem> {
  return new Promise((resolve) => {
    let settled = false
    let socket: WebSocket | null = null
    const finish = (item: RuntimeSelfCheckItem) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      socket?.close()
      resolve(item)
    }
    const timer = window.setTimeout(() => finish({
      check_id: 'websocket_unicode_round_trip', title: 'WebSocket 中文往返', status: 'error',
      message: '任务 WebSocket 中文探针超时。', suggestion: '重启 Backend 后重试。',
    }), 3000)
    try {
      socket = new WebSocket(resolveWebSocketUrl('/ws/tasks'))
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as { type?: string; payload?: { unicode_probe?: string } }
          if (payload.type !== 'snapshot') return
          const normal = payload.payload?.unicode_probe === '宁波地铁1号线 · 任务已完成'
          finish({
            check_id: 'websocket_unicode_round_trip', title: 'WebSocket 中文往返', status: normal ? 'normal' : 'error',
            message: normal ? '任务 WebSocket 中文往返正常。' : '任务 WebSocket 中文探针不一致。',
            suggestion: normal ? '' : '重启 Backend 后重试。',
          })
        } catch {
          finish({
            check_id: 'websocket_unicode_round_trip', title: 'WebSocket 中文往返', status: 'error',
            message: '任务 WebSocket 返回无效数据。', suggestion: '重启 Backend 后重试。',
          })
        }
      }
      socket.onerror = () => finish({
        check_id: 'websocket_unicode_round_trip', title: 'WebSocket 中文往返', status: 'error',
        message: '任务 WebSocket 无法连接。', suggestion: '检查 Backend 状态后重试。',
      })
    } catch {
      finish({
        check_id: 'websocket_unicode_round_trip', title: 'WebSocket 中文往返', status: 'error',
        message: '任务 WebSocket 地址不可用。', suggestion: '请从 NetConsole.exe 打开系统设置。',
      })
    }
  })
}

function aggregateSelfCheckStatus(items: RuntimeSelfCheckItem[]): RuntimeSelfCheckSnapshot['status'] {
  if (items.some((item) => item.status === 'error')) return 'error'
  if (items.some((item) => item.status === 'warning')) return 'warning'
  return 'normal'
}

function selfCheckTagType(status: RuntimeSelfCheckItem['status']): 'success' | 'warning' | 'danger' {
  return status === 'normal' ? 'success' : status === 'warning' ? 'warning' : 'danger'
}

async function save(): Promise<void> {
  if (!snapshot.value) return
  saving.value = true; error.value = ''
  try {
    if (dirty.value) {
      acceptSnapshot(await saveSystemSettings(cloneValues(form), snapshot.value.version))
    }
    ElMessage.success('设置已保存')
  } catch (cause) {
    restoreAppearance()
    showError(cause, '系统设置保存失败')
  } finally { saving.value = false }
}

async function reload(): Promise<void> {
  loading.value = true; error.value = ''
  try {
    try { acceptSnapshot(await reloadSystemSettings()); ElMessage.success('系统设置已重载') }
    catch (cause) { restoreAppearance(); showError(cause, '重载失败') }
    await loadFeatureRuntimeStatus()
  } finally { loading.value = false }
}

async function loadFeatureRuntimeStatus(): Promise<void> {
  try {
    featureRuntimeStatus.value = await getFeatureRuntimeStatus()
  } catch (cause) {
    error.value = message(cause, '当前版本状态加载失败')
  }
}

async function openFeatureDelivery(): Promise<void> {
  await router.push('/feature-flags')
}

async function exitRuntimePreview(): Promise<void> {
  featureActionLoading.value = true
  try {
    await exitFeatureSettingsPreview('customer')
    await loadRendererFeatures(true)
    featureRuntimeStatus.value = await getFeatureRuntimeStatus()
    ElMessage.success('已退出会话预览')
  } catch (cause) {
    showError(cause, '退出会话预览失败')
  } finally {
    featureActionLoading.value = false
  }
}

async function clearRuntimeOverrides(): Promise<void> {
  if (!await confirmAction('清除历史运行时功能覆盖？模板文件和业务数据不会被修改。')) return
  featureActionLoading.value = true
  try {
    featureRuntimeStatus.value = await clearFeatureRuntimeOverrides()
    ElMessage.success('历史运行时覆盖已清除')
  } catch (cause) {
    showError(cause, '清除历史运行时覆盖失败')
  } finally {
    featureActionLoading.value = false
  }
}

async function reloadRuntimeGate(): Promise<void> {
  featureActionLoading.value = true
  try {
    featureRuntimeStatus.value = await reloadFeatureGate()
    ElMessage.success('Feature Gate 已重新加载')
  } catch (cause) {
    showError(cause, 'Feature Gate 重新加载失败')
  } finally {
    featureActionLoading.value = false
  }
}

function acceptSnapshot(value: SystemSettingsSnapshot): void {
  snapshot.value = value; baseline.value = cloneValues(value.values); Object.assign(form, cloneValues(value.values)); previewAppearance()
}
function resetDefaults(): void { if (snapshot.value) { Object.assign(form, cloneValues(snapshot.value.defaults)); previewAppearance() } }
function cancelChanges(): void { if (baseline.value) Object.assign(form, cloneValues(baseline.value)); previewAppearance() }
function previewAppearance(): void { applySystemAppearance(form) }
function restoreAppearance(): void { if (baseline.value) applySystemAppearance(baseline.value) }
function cloneValues(value: SystemSettingsValues): SystemSettingsValues { return { ...value, terminal_paths: { ...value.terminal_paths } } }
function beforeUnload(event: BeforeUnloadEvent): void { if (anyDirty.value) { event.preventDefault(); event.returnValue = '' } }

async function focusSiteStorage(): Promise<void> {
  if (route.query.section !== 'site-storage') return
  await siteStoragePanel.value?.reload?.()
  await nextTick()
  siteStoragePanel.value?.focus?.()
  siteStorageFocused.value = true
  if (siteStorageFocusTimer) clearTimeout(siteStorageFocusTimer)
  siteStorageFocusTimer = setTimeout(() => { siteStorageFocused.value = false }, 1600)
}

async function focusExternalTerminal(): Promise<void> {
  if (route.query.section !== 'external-terminal') return
  await router.replace({ path: '/tools', query: { section: 'external-terminal' } })
}

async function processTraySiteSwitch(): Promise<void> {
  const requestedSiteId = typeof route.query.tray_site_switch === 'string'
    ? route.query.tray_site_switch
    : ''
  if (!/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(requestedSiteId)) return
  if (traySiteSwitchInProgress === requestedSiteId) return
  traySiteSwitchInProgress = requestedSiteId
  try {
    await nextTick()
    await siteStoragePanel.value?.requestSwitch?.(requestedSiteId)
  } finally {
    if (route.query.tray_site_switch === requestedSiteId) {
      const query = { ...route.query }
      delete query.tray_site_switch
      await router.replace({ query })
    }
    traySiteSwitchInProgress = ''
  }
}

onActivated(() => { void focusSiteStorage() })

watch(
  () => [route.query.section, route.query.site_focus],
  () => {
    void focusSiteStorage()
    void focusExternalTerminal()
  },
  { immediate: true },
)

watch(
  () => route.query.tray_site_switch,
  () => { void processTraySiteSwitch() },
  { immediate: true },
)

async function selectColor(): Promise<void> {
  try {
    const result = await getPlatformAdapter().selectSettingsColor()
    if (result.color) { form.theme_color = result.color; previewAppearance() }
  } catch (cause) { showError(cause, '主题色选择失败') }
}
async function nativeAction(action: 'open_settings_config' | 'open_current_site'): Promise<void> {
  try {
    const result = await getPlatformAdapter().executeSettingsAction(action)
    if (result.success) ElMessage.success('操作已完成')
    else showError(new Error(result.error || '操作失败'), '操作失败')
  } catch (cause) { showError(cause, '本机操作失败') }
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

    <section class="settings-band"><h2>桌面外壳</h2>
      <div class="desktop-shell-setting">
        <div>
          <strong>关闭主窗口后继续驻留通知区域</strong>
          <p>关闭窗口只暂停页面显示，Python Backend 和后台任务继续运行。</p>
        </div>
        <el-switch
          v-model="closeToTrayEnabled"
          data-testid="close-to-tray"
          :disabled="!closeToTrayAvailable || closeToTraySaving"
          :loading="closeToTraySaving"
          @change="updateCloseToTray"
        />
      </div>
      <el-alert
        v-if="desktopHost && !closeToTrayAvailable"
        title="系统托盘当前不可用，关闭主窗口将按正常退出处理。"
        type="warning"
        :closable="false"
      />
    </section>

    <section class="settings-band">
      <div class="section-heading">
        <h2>正式包环境自检</h2>
        <div class="inline-actions">
          <el-tag v-if="selfCheck" :type="selfCheckTagType(selfCheck.status)">{{ selfCheck.status === 'normal' ? '正常' : selfCheck.status === 'warning' ? '警告' : '错误' }}</el-tag>
          <el-button data-testid="runtime-self-check" :loading="selfCheckLoading" @click="runSelfCheck">重新检查</el-button>
        </div>
      </div>
      <el-alert v-if="selfCheckError" :title="selfCheckError" type="error" :closable="false" />
      <div v-if="selfCheck" class="self-check-grid">
        <article v-for="item in selfCheck.items" :key="item.check_id">
          <div><strong>{{ item.title }}</strong><el-tag :type="selfCheckTagType(item.status)" size="small">{{ item.status === 'normal' ? '正常' : item.status === 'warning' ? '警告' : '错误' }}</el-tag></div>
          <p>{{ item.message }}</p><small v-if="item.suggestion">{{ item.suggestion }}</small>
        </article>
      </div>
    </section>

    <SiteStoragePanel ref="siteStoragePanel" :focused="siteStorageFocused" :switch-blocked="saving || anyDirty" />

    <DatabaseUpgradePanel v-if="isFeatureEnabled('module.database_upgrade')" />

    <section class="settings-band feature-status-band">
      <div class="section-heading">
        <h2>当前版本状态</h2>
        <div class="inline-actions">
          <el-button
            v-if="featureRuntimeStatus?.configuration_available"
            data-testid="open-feature-delivery"
            @click="openFeatureDelivery"
          >打开版本与功能交付</el-button>
          <el-button
            v-if="featureRuntimeStatus?.preview_active"
            data-testid="exit-feature-preview"
            :loading="featureActionLoading"
            @click="exitRuntimePreview"
          >退出会话预览</el-button>
          <el-button
            data-testid="clear-runtime-overrides"
            :disabled="!featureRuntimeStatus?.local_override_count"
            :loading="featureActionLoading"
            @click="clearRuntimeOverrides"
          >清除历史运行时覆盖</el-button>
          <el-button
            data-testid="reload-feature-gate"
            :loading="featureActionLoading"
            @click="reloadRuntimeGate"
          >重新加载 Feature Gate</el-button>
        </div>
      </div>
      <dl class="version-facts">
        <div><dt>版本类型</dt><dd>{{ editionLabel }}</dd></div>
        <div><dt>基础模板</dt><dd>{{ featureRuntimeStatus?.base_profile || '--' }}</dd></div>
        <div><dt>当前状态</dt><dd><el-tag :type="featureRuntimeStatus?.state === 'normal' ? 'success' : 'warning'">{{ runtimeStateLabel }}</el-tag></dd></div>
        <div><dt>本地覆盖</dt><dd>{{ featureRuntimeStatus?.local_override_count ? `${featureRuntimeStatus.local_override_count} 项` : '无' }}</dd></div>
      </dl>
    </section>
  </section>
</template>

<style scoped>
.settings-page{display:flex;flex-direction:column;gap:16px;max-width:1680px;margin:0 auto}.settings-toolbar,.settings-actions,.section-heading,.inline-actions,.color-control,.desktop-shell-setting{display:flex;align-items:center;gap:10px}.settings-toolbar,.section-heading,.desktop-shell-setting{justify-content:space-between}.settings-toolbar h1,.settings-band h2{margin:0}.settings-toolbar p,.desktop-shell-setting p{margin:6px 0 0;color:var(--nc-text-secondary)}.settings-actions,.inline-actions{flex-wrap:wrap;justify-content:flex-end}.settings-band{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.settings-band h2{margin-bottom:16px;font-size:17px}.settings-grid{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:0 18px}.settings-grid .wide{grid-column:span 2}.el-select,.el-input-number{width:100%}.color-swatch{width:24px;height:24px;border:1px solid var(--nc-border-strong);border-radius:4px}.site-facts{display:grid;grid-template-columns:1fr 2fr;gap:12px}.site-facts div{min-width:0}.site-facts dt{color:var(--nc-text-secondary);font-size:12px}.site-facts dd{margin:5px 0;overflow-wrap:anywhere;font-family:Consolas,monospace}.self-check-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.self-check-grid article{padding:12px;border:1px solid var(--el-border-color-light);border-radius:6px}.self-check-grid article>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.self-check-grid p{margin:8px 0 0}.self-check-grid small{display:block;margin-top:6px;color:var(--nc-text-secondary)}.section-heading h2{margin-bottom:0}
.version-facts{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:14px;margin:18px 0 0}.version-facts div{min-width:0;padding-left:12px;border-left:3px solid var(--el-border-color)}.version-facts dt{color:var(--nc-text-secondary);font-size:12px}.version-facts dd{margin:6px 0 0;font-weight:600;overflow-wrap:anywhere}
@media(max-width:900px){.settings-toolbar,.section-heading,.desktop-shell-setting{align-items:flex-start;flex-direction:column}.settings-actions,.inline-actions{justify-content:flex-start}.settings-grid,.site-facts,.self-check-grid,.version-facts{grid-template-columns:1fr}.settings-grid .wide{grid-column:auto}}
</style>
