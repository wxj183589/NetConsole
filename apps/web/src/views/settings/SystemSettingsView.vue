<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import {
  exitFeatureSettingsPreview, getFeatureSettings, getSystemSettings, reloadSystemSettings,
  restoreFeatureSettings, saveFeatureSettings, saveSystemSettings, getRuntimeSelfCheck,
} from '../../api/systemSettings'
import { isFeatureEnabled, loadWebFeatures } from '../../features'
import { t } from '../../i18n/runtime'
import { getPlatformAdapter, resolveWebSocketUrl } from '../../platform/runtime'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { applySystemAppearance } from '../../settings/appearance'
import { useConfirm } from '../../components/feedback/useConfirm'
import type { FeatureSetting, FeatureSettingsSnapshot, RuntimeSelfCheckItem, RuntimeSelfCheckSnapshot, SystemSettingsSnapshot, SystemSettingsValues } from '../../types/systemSettings'
import SiteStoragePanel from './SiteStoragePanel.vue'

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
const features = ref<FeatureSetting[]>([])
const featureBaseline = ref('')
const featurePreview = ref(false)
const featureConfigurationName = ref('当前实例运行配置')
const featureScopeLabel = ref('全局')
const featureInheritedProfile = ref('full')
const featureSearch = ref('')
const featureGroupFilter = ref('all')
const featureModifiedOnly = ref(false)
const featurePreviewDrawer = ref(false)
const activeFeatureGroups = ref<string[]>([])
const linkedFeatureChanges = ref<Set<string>>(new Set())
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const featureError = ref('')
const featureConfigurationAllowed = ref(getPlatformAdapter().hostType !== 'electron')
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
const featuresDirty = computed(() => featureSwitchAvailable.value && JSON.stringify(features.value) !== featureBaseline.value)
const anyDirty = computed(() => dirty.value || featuresDirty.value)
const featureSwitchAvailable = computed(() => featureConfigurationAllowed.value && isFeatureEnabled('web.feature_switch'))
const featureColumns: NcTableColumn<FeatureSetting>[] = [
  { key: 'title', label: '功能', valueType: 'name', align: 'left', alignmentReason: 'description', fixed: 'left' },
  { key: 'feature_id', label: 'ID', valueType: 'description', alignmentReason: 'code', stretch: 'fill', maxWidth: 960 },
  { key: 'scope', label: '作用域', valueType: 'status' },
  { key: 'package_range', label: '发布范围', valueType: 'status' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'enabled', label: '运行状态', valueType: 'status', fixed: 'right' },
]
type FeatureMode = 'enabled_visible' | 'enabled_hidden' | 'disabled'
const baselineFeatures = computed<FeatureSetting[]>(() => featureBaseline.value ? JSON.parse(featureBaseline.value) as FeatureSetting[] : [])
const baselineFeatureById = computed(() => new Map(baselineFeatures.value.map((item) => [item.feature_id, item])))
const featureGroups = computed(() => {
  const search = featureSearch.value.trim().toLocaleLowerCase()
  const groups = new Map<string, { id: string; title: string; items: FeatureSetting[] }>()
  for (const item of features.value) {
    if (featureGroupFilter.value !== 'all' && item.group_id !== featureGroupFilter.value) continue
    if (search && !`${item.title} ${item.feature_id}`.toLocaleLowerCase().includes(search)) continue
    if (featureModifiedOnly.value && !isFeatureModified(item)) continue
    const group = groups.get(item.group_id) ?? { id: item.group_id, title: item.group_title, items: [] }
    group.items.push(item)
    groups.set(item.group_id, group)
  }
  return [...groups.values()]
})
const featureGroupOptions = computed(() => [...new Map(features.value.map((item) => [item.group_id, item.group_title])).entries()])
const featureChanges = computed(() => features.value.flatMap((item) => {
  const baselineItem = baselineFeatureById.value.get(item.feature_id)
  if (!baselineItem || (baselineItem.visible === item.visible && baselineItem.enabled === item.enabled)) return []
  return [{ item, before: featureMode(baselineItem), after: featureMode(item) }]
}))
const dependencyIssues = computed(() => features.value.flatMap((item) => item.enabled
  ? item.dependencies.filter((dependencyId) => !features.value.find((candidate) => candidate.feature_id === dependencyId)?.enabled).map((dependencyId) => ({ item, dependencyId }))
  : []))

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
  loading.value = true; error.value = ''; featureError.value = ''
  try {
    await resolveFeatureConfigurationAvailability()
    try { acceptSnapshot(await getSystemSettings()) }
    catch (cause) { error.value = message(cause, '系统设置加载失败') }
    await loadFeatureSettingsSafely()
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
  const settingsWereDirty = dirty.value
  const featuresWereDirty = featuresDirty.value
  if (featuresWereDirty && !(await confirmAction('保存并应用当前实例的全局功能配置？'))) return
  saving.value = true; error.value = ''
  let featureSaved = false
  let saveStage: 'feature_profile' | 'feature_refresh' | 'settings' = featuresWereDirty ? 'feature_profile' : 'settings'
  try {
    if (featuresWereDirty) {
      const data = await saveFeatureSettings(features.value)
      acceptFeatureSnapshot(data)
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
  acceptFeatureSnapshot(await getFeatureSettings())
}

function acceptFeatureSnapshot(data: FeatureSettingsSnapshot): void {
  features.value = data.items
  featureBaseline.value = JSON.stringify(data.items)
  featurePreview.value = data.preview_active
  featureConfigurationName.value = data.configuration_name
  featureScopeLabel.value = data.scope_label
  featureInheritedProfile.value = data.inherited_profile
  activeFeatureGroups.value = [...new Set(data.items.map((item) => item.group_id))]
  linkedFeatureChanges.value = new Set()
}

function resetFeatureConfigurationState(): void {
  features.value = []
  featureBaseline.value = JSON.stringify([])
  featurePreview.value = false
  featurePreviewDrawer.value = false
  linkedFeatureChanges.value = new Set()
  featureError.value = ''
}

function acceptSnapshot(value: SystemSettingsSnapshot): void {
  snapshot.value = value; baseline.value = cloneValues(value.values); Object.assign(form, cloneValues(value.values)); previewAppearance()
}
function resetDefaults(): void { if (snapshot.value) { Object.assign(form, cloneValues(snapshot.value.defaults)); previewAppearance() } }
function cancelChanges(): void { if (baseline.value) Object.assign(form, cloneValues(baseline.value)); previewAppearance(); undoFeatureChanges() }
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
function previewFeatures(): void {
  featurePreviewDrawer.value = true
}
async function restoreFeatures(): Promise<void> {
  if (!await confirmAction(`恢复继承配置 ${featureInheritedProfile.value} 的默认运行状态？`)) return
  try {
    acceptFeatureSnapshot(await restoreFeatureSettings()); await loadWebFeatures(true); ElMessage.success('已恢复默认功能配置')
  } catch (cause) { showError(cause, '功能开关恢复失败') }
}
async function exitFeaturePreview(): Promise<void> {
  try {
    acceptFeatureSnapshot(await exitFeatureSettingsPreview()); await loadWebFeatures(true); ElMessage.success('已退出会话预览')
  } catch (cause) { showError(cause, '退出功能预览失败') }
}
async function saveFeaturesOnly(): Promise<void> {
  if (!featuresDirty.value || dependencyIssues.value.length) return
  if (!await confirmAction('保存并立即应用当前实例的全局功能配置？')) return
  saving.value = true
  try {
    acceptFeatureSnapshot(await saveFeatureSettings(features.value))
    await loadWebFeatures(true)
    ElMessage.success('功能配置已保存并应用')
  } catch (cause) { showError(cause, '功能配置保存失败') }
  finally { saving.value = false }
}
function undoFeatureChanges(): void {
  if (featureBaseline.value) features.value = JSON.parse(featureBaseline.value) as FeatureSetting[]
  linkedFeatureChanges.value = new Set()
}
function featureMode(item: FeatureSetting): FeatureMode {
  if (!item.enabled) return 'disabled'
  return item.visible ? 'enabled_visible' : 'enabled_hidden'
}
function featureModeLabel(mode: FeatureMode): string {
  return mode === 'enabled_visible' ? '显示并启用' : mode === 'enabled_hidden' ? '隐藏入口' : '完全禁用'
}
async function updateFeatureMode(item: FeatureSetting, mode: FeatureMode): Promise<void> {
  if (item.locked) return
  const nextLinked = new Set(linkedFeatureChanges.value)
  if (mode === 'disabled') {
    const affected = enabledDependentsOf(item.feature_id)
    if (affected.length && !await confirmAction(`禁用“${item.title}”将同时禁用 ${affected.map((value) => value.title).join('、')}，是否继续？`)) return
    for (const dependent of affected) {
      dependent.enabled = false
      dependent.visible = false
      nextLinked.add(dependent.feature_id)
    }
    item.enabled = false
    item.visible = false
  } else {
    const dependencies = dependencyClosure(item).filter((dependency) => !dependency.enabled)
    if (dependencies.length && !await confirmAction(`启用“${item.title}”需要同时启用 ${dependencies.map((value) => value.title).join('、')}，是否继续？`)) return
    for (const dependency of dependencies) {
      dependency.enabled = true
      dependency.visible = true
      nextLinked.add(dependency.feature_id)
    }
    item.enabled = true
    item.visible = mode === 'enabled_visible'
  }
  linkedFeatureChanges.value = nextLinked
}
function dependencyClosure(item: FeatureSetting, seen = new Set<string>()): FeatureSetting[] {
  const result: FeatureSetting[] = []
  for (const featureId of item.dependencies) {
    if (seen.has(featureId)) continue
    seen.add(featureId)
    const dependency = features.value.find((candidate) => candidate.feature_id === featureId)
    if (!dependency) continue
    result.push(...dependencyClosure(dependency, seen), dependency)
  }
  return [...new Map(result.map((value) => [value.feature_id, value])).values()]
}
function enabledDependentsOf(featureId: string): FeatureSetting[] {
  const result: FeatureSetting[] = []
  const queue = [featureId]
  const seen = new Set(queue)
  while (queue.length) {
    const current = queue.shift()!
    for (const candidate of features.value) {
      if (!candidate.enabled || seen.has(candidate.feature_id) || !candidate.dependencies.includes(current)) continue
      seen.add(candidate.feature_id)
      result.push(candidate)
      queue.push(candidate.feature_id)
    }
  }
  return result
}
function isFeatureModified(item: FeatureSetting): boolean {
  const baselineItem = baselineFeatureById.value.get(item.feature_id)
  return item.overridden || Boolean(baselineItem && (baselineItem.visible !== item.visible || baselineItem.enabled !== item.enabled))
}
function groupEnabledSummary(items: FeatureSetting[]): string {
  return `已启用 ${items.filter((item) => item.enabled).length} / ${items.length}`
}
function packageRangeLabel(value: FeatureSetting['package_range']): string {
  return value === 'customer_internal' ? '客户包、内部包' : value === 'internal' ? '内部包' : value === 'internal_only' ? '仅内部' : '未包含'
}
function featureStatusLabel(status: FeatureSetting['status']): string {
  return status === 'DEVELOPMENT' ? '开发中' : status === 'HIDDEN' ? '已隐藏' : status === 'DISABLED' ? '不可用' : '正常'
}
function featureStatusTagType(status: FeatureSetting['status']): 'success' | 'warning' | 'info' | 'danger' {
  return status === 'ENABLED' ? 'success' : status === 'DEVELOPMENT' ? 'warning' : status === 'DISABLED' ? 'danger' : 'info'
}
async function copyFeatureId(featureId: string): Promise<void> {
  try { await navigator.clipboard.writeText(featureId); ElMessage.success('功能 ID 已复制') }
  catch { ElMessage.error('复制失败') }
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
    <el-alert v-if="featureSwitchAvailable && featureError" :title="featureError" type="warning" :closable="false" />

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

    <section v-if="featureSwitchAvailable" class="settings-band feature-settings-band">
      <div class="section-heading feature-heading">
        <div>
          <h2>{{ t('settings.features', '功能开关') }}</h2>
          <div class="feature-context">
            <span>当前配置：<strong>{{ featureConfigurationName }}</strong></span>
            <span>作用范围：<strong>{{ featureScopeLabel }}</strong></span>
            <span>继承配置：<strong>{{ featureInheritedProfile }}</strong></span>
          </div>
        </div>
        <div class="inline-actions">
          <el-tag v-if="featurePreview" type="warning">会话预览中</el-tag>
          <el-button v-if="featurePreview" data-testid="exit-feature-preview" @click="exitFeaturePreview">退出预览</el-button>
          <el-button data-testid="undo-feature-changes" :disabled="!featuresDirty" @click="undoFeatureChanges">撤销修改</el-button>
          <el-button data-testid="restore-features" @click="restoreFeatures">恢复默认</el-button>
          <el-button data-testid="preview-features" :disabled="!featuresDirty" @click="previewFeatures">预览变更</el-button>
          <el-button data-testid="save-features" type="primary" :loading="saving" :disabled="!featuresDirty || Boolean(dependencyIssues.length)" @click="saveFeaturesOnly">保存并应用</el-button>
        </div>
      </div>
      <el-alert v-if="featurePreview" title="正在预览功能配置，会话预览尚未写入运行时覆盖。" type="warning" :closable="false" />
      <el-alert v-if="dependencyIssues.length" :title="`存在 ${dependencyIssues.length} 项依赖异常，修复后才能保存。`" type="error" :closable="false" />
      <div class="feature-filters">
        <el-input v-model="featureSearch" data-testid="feature-search" clearable placeholder="搜索功能或 ID" />
        <el-select v-model="featureGroupFilter" data-testid="feature-group-filter">
          <el-option label="全部分类" value="all" />
          <el-option v-for="[id, title] in featureGroupOptions" :key="id" :label="title" :value="id" />
        </el-select>
        <el-switch v-model="featureModifiedOnly" data-testid="feature-modified-only" active-text="仅显示已修改" />
      </div>
      <el-empty v-if="!featureGroups.length" description="没有匹配的功能" />
      <el-collapse v-else v-model="activeFeatureGroups" class="feature-groups">
        <el-collapse-item v-for="group in featureGroups" :key="group.id" :name="group.id">
          <template #title>
            <span class="feature-group-title">{{ group.title }}</span>
            <el-tag size="small" type="info">{{ groupEnabledSummary(group.items) }}</el-tag>
          </template>
          <NcDataTable :data="group.items" :columns="featureColumns" :table-id="`system-feature-settings-${group.id}`" route-key="/system-settings" max-height="480" :row-key="(row: FeatureSetting) => row.feature_id">
            <template #cell-title="{ row }"><strong>{{ row.title }}</strong></template>
            <template #cell-feature_id="{ row }">
              <div class="feature-id-cell">
                <code>{{ row.feature_id }}</code>
                <el-tooltip content="复制功能 ID" placement="top"><el-button link :icon="CopyDocument" :aria-label="`复制 ${row.feature_id}`" @click="copyFeatureId(row.feature_id)" /></el-tooltip>
              </div>
            </template>
            <template #cell-scope><el-tag size="small" type="info">全局</el-tag></template>
            <template #cell-package_range="{ row }"><el-tag size="small" :type="row.package_range === 'not_included' ? 'info' : row.package_range === 'internal_only' ? 'warning' : 'success'">{{ packageRangeLabel(row.package_range) }}</el-tag></template>
            <template #cell-status="{ row }">
              <div class="feature-status-tags">
                <el-tag size="small" :type="featureStatusTagType(row.status)">{{ featureStatusLabel(row.status) }}</el-tag>
                <el-tag v-if="isFeatureModified(row)" size="small" type="warning">已修改</el-tag>
                <el-tooltip v-if="row.locked" :content="row.lock_reason" placement="top"><el-tag size="small" type="info">锁定</el-tag></el-tooltip>
                <el-tag v-if="dependencyIssues.some((issue) => issue.item.feature_id === row.feature_id)" size="small" type="danger">依赖异常</el-tag>
              </div>
            </template>
            <template #cell-enabled="{ row }">
              <el-select :model-value="featureMode(row)" :data-testid="`feature-mode-${row.feature_id}`" :disabled="row.locked || row.package_range === 'not_included'" @change="updateFeatureMode(row, $event as FeatureMode)">
                <el-option label="显示并启用" value="enabled_visible" />
                <el-option label="隐藏入口" value="enabled_hidden" />
                <el-option label="完全禁用" value="disabled" />
              </el-select>
            </template>
          </NcDataTable>
        </el-collapse-item>
      </el-collapse>
      <el-drawer v-model="featurePreviewDrawer" title="变更预览" size="480px">
        <div class="feature-preview-content">
          <section><h3>直接修改</h3><el-empty v-if="!featureChanges.length" description="无变更" :image-size="56" /><ul v-else><li v-for="change in featureChanges" :key="change.item.feature_id"><strong>{{ change.item.title }}</strong><span>{{ featureModeLabel(change.before) }} → {{ featureModeLabel(change.after) }}</span></li></ul></section>
          <section><h3>依赖联动</h3><p v-if="!linkedFeatureChanges.size">无</p><ul v-else><li v-for="featureId in linkedFeatureChanges" :key="featureId">{{ features.find((item) => item.feature_id === featureId)?.title }}</li></ul></section>
          <section><h3>导航变化</h3><p v-if="!featureChanges.some((change) => change.item.visible !== baselineFeatureById.get(change.item.feature_id)?.visible)">无</p><ul v-else><li v-for="change in featureChanges.filter((value) => value.item.visible !== baselineFeatureById.get(value.item.feature_id)?.visible)" :key="change.item.feature_id">{{ change.item.visible ? '显示' : '移除' }}“{{ change.item.title }}”入口</li></ul></section>
          <section><h3>任务影响</h3><p v-if="!featureChanges.some((change) => change.before !== 'disabled' && change.after === 'disabled')">无</p><ul v-else><li v-for="change in featureChanges.filter((value) => value.before !== 'disabled' && value.after === 'disabled')" :key="change.item.feature_id">禁止创建新的“{{ change.item.title }}”相关任务；历史任务保留可查。</li></ul></section>
          <section><h3>生效方式</h3><p>保存后立即刷新功能 Gate、导航与路由访问状态。</p></section>
        </div>
        <template #footer><el-button @click="featurePreviewDrawer = false">关闭</el-button><el-button type="primary" :disabled="!featuresDirty || Boolean(dependencyIssues.length)" @click="saveFeaturesOnly">保存并应用</el-button></template>
      </el-drawer>
    </section>
  </section>
</template>

<style scoped>
.settings-page{display:flex;flex-direction:column;gap:16px;max-width:1680px;margin:0 auto}.settings-toolbar,.settings-actions,.section-heading,.inline-actions,.color-control,.desktop-shell-setting{display:flex;align-items:center;gap:10px}.settings-toolbar,.section-heading,.desktop-shell-setting{justify-content:space-between}.settings-toolbar h1,.settings-band h2{margin:0}.settings-toolbar p,.desktop-shell-setting p{margin:6px 0 0;color:var(--nc-text-secondary)}.settings-actions,.inline-actions{flex-wrap:wrap;justify-content:flex-end}.settings-band{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.settings-band h2{margin-bottom:16px;font-size:17px}.settings-grid{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:0 18px}.settings-grid .wide{grid-column:span 2}.el-select,.el-input-number{width:100%}.color-swatch{width:24px;height:24px;border:1px solid var(--nc-border-strong);border-radius:4px}.site-facts{display:grid;grid-template-columns:1fr 2fr;gap:12px}.site-facts div{min-width:0}.site-facts dt{color:var(--nc-text-secondary);font-size:12px}.site-facts dd{margin:5px 0;overflow-wrap:anywhere;font-family:Consolas,monospace}.self-check-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.self-check-grid article{padding:12px;border:1px solid var(--el-border-color-light);border-radius:6px}.self-check-grid article>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.self-check-grid p{margin:8px 0 0}.self-check-grid small{display:block;margin-top:6px;color:var(--nc-text-secondary)}.section-heading h2{margin-bottom:0}
.feature-settings-band{width:100%;min-width:0}.feature-heading{align-items:flex-start}.feature-context{display:flex;flex-wrap:wrap;gap:8px 20px;margin-top:8px;color:var(--nc-text-secondary);font-size:13px}.feature-context strong{color:var(--nc-text-primary);font-weight:600}.feature-filters{display:grid;grid-template-columns:minmax(260px,1fr) 220px auto;align-items:center;gap:12px;margin:16px 0}.feature-groups{border-top:1px solid var(--el-border-color-light)}.feature-group-title{margin-right:10px;font-weight:600}.feature-id-cell,.feature-status-tags{display:flex;align-items:center;gap:6px}.feature-id-cell{min-width:0;justify-content:flex-start}.feature-id-cell code{max-width:calc(100% - 32px);overflow:hidden;color:var(--nc-text-secondary);font-family:Consolas,"Courier New",monospace;text-overflow:ellipsis;white-space:nowrap}.feature-status-tags{flex-wrap:wrap;justify-content:center}.feature-preview-content{display:flex;flex-direction:column;gap:18px}.feature-preview-content section{padding-bottom:16px;border-bottom:1px solid var(--el-border-color-light)}.feature-preview-content h3{margin:0 0 10px;font-size:15px}.feature-preview-content p{margin:0;color:var(--nc-text-secondary)}.feature-preview-content ul{display:flex;flex-direction:column;gap:8px;margin:0;padding-left:20px}.feature-preview-content li span{display:block;margin-top:3px;color:var(--nc-text-secondary);font-size:13px}
@media(max-width:900px){.settings-toolbar,.section-heading,.desktop-shell-setting{align-items:flex-start;flex-direction:column}.settings-actions,.inline-actions{justify-content:flex-start}.settings-grid,.site-facts,.self-check-grid,.feature-filters{grid-template-columns:1fr}.settings-grid .wide{grid-column:auto}.feature-filters .el-switch{justify-self:start}}
</style>
