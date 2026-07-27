<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTracksideApTask,
  listTracksideSwitchAdapters,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
  startTracksideSwitchSample,
  tracksideSwitchSampleDownloadRequest,
} from '../../api/tracksideApBusiness'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import { t } from '../../i18n/runtime'
import { downloadBackendResource } from '../../platform/runtime'
import type {
  TracksideApBusinessPage,
  TracksideApBusinessRow,
  TracksideApTask,
  TracksideApUpdateRequest,
  TracksideSwitchAdapterCatalog,
  TracksideSwitchCapabilityStatus,
  TracksideSwitchDevice,
} from '../../types/tracksideApBusiness'
import { displayInterfaceName } from '../../utils/interfaceName'
import {
  isTracksideApBusinessArtifactTask,
  saveTracksideApBusinessArtifact,
  TRACKSIDE_AP_BUSINESS_EXPORT_ACTION,
} from './tracksideApBusinessArtifact'
import {
  displayBidirectionalLoss,
  displayLldpStatus,
  displayPowerThreshold,
  displaySwitchVendor,
  displayTracksideValue,
  tracksideOpticalPresentation,
} from './tracksideApBusinessDisplay'

const storageKey = 'netconsole.trackside-ap.last-task'
const autoSaveStorageKey = 'netconsole.trackside-ap-business.auto-saved-task-ids'
const router = useRouter()
const activeStates = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'QUEUED', 'CANCELLING'])
const sampleTaskAction = 'switch_vendor_sample_collect'
const businessTaskActions = new Set(['trackside_ap_optical_update', TRACKSIDE_AP_BUSINESS_EXPORT_ACTION, sampleTaskAction])
const autoSaveInFlight = new Set<string>()
const initialLoading = ref(false)
const refreshing = ref(false)
const taskSubmitting = ref(false)
const pendingScopeKey = ref('')
const error = ref('')
const taskNotice = ref('')
const taskNoticeType = ref<'success' | 'info' | 'warning' | 'error'>('info')
const page = ref<TracksideApBusinessPage | null>(null)
const task = ref<TracksideApTask | null>(null)
const adapterCatalog = ref<TracksideSwitchAdapterCatalog | null>(null)
const selectedSwitchUuid = ref('')
const selectedInterface = ref('')
const adapterLoading = ref(false)
const adapterError = ref('')
const adapterDetailsVisible = ref(false)
const sampleDownloading = ref(false)
const filters = reactive({ station: '', query: '', optical_anomaly_only: false, page: 1, page_size: 50 })
let pollTimer: number | undefined
let taskNoticeTimer: number | undefined
let loadGeneration = 0

const businessColumns: NcTableColumn<TracksideApBusinessRow>[] = [
  { key: 'site', label: '站点', valueType: 'name', fixed: 'left' },
  { key: 'device_name', label: '车站交换机', valueType: 'name', fixed: 'left' },
  { key: 'switch_vendor', label: '交换机厂商', valueType: 'name', displayValue: (row) => displaySwitchVendor(row.switch_vendor) },
  { key: 'interface_name', label: '接口', valueType: 'port', displayValue: (row) => displayTracksideValue(displayInterfaceName(row.interface_name)) },
  { key: 'lldp_match_status', label: 'LLDP 状态', valueType: 'status', displayValue: (row) => displayLldpStatus(row.lldp_match_status) },
  { key: 'link_status', label: '链路', valueType: 'status' },
  { key: 'port_type', label: '端口类型', valueType: 'status', width: 100 },
  { key: 'description', label: '描述', valueType: 'description', width: 90, maxWidth: 120, align: 'center', headerAlign: 'center', stretch: 'none', showOverflowTooltip: true },
  { key: 'pvid', label: 'PVID', valueType: 'number', displayValue: (row) => displayTracksideValue(row.pvid) },
  { key: 'vlan', label: 'VLAN', displayValue: (row) => displayTracksideValue(row.vlan) },
  { key: 'switch_rx_power', label: '本端 Rx (dBm)', valueType: 'number' },
  { key: 'switch_tx_power', label: '本端 Tx (dBm)', valueType: 'number' },
  { key: 'switch_rx_low_alarm', label: 'Rx 门限', displayValue: (row) => displayPowerThreshold(row.switch_rx_low_alarm, row.switch_rx_high_alarm) },
  { key: 'switch_tx_low_alarm', label: 'Tx 门限', displayValue: (row) => displayPowerThreshold(row.switch_tx_low_alarm, row.switch_tx_high_alarm) },
  { key: 'switch_optical_status', label: '模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac', stretch: 'priority' },
  { key: 'ap_name', label: '当前轨旁 AP', valueType: 'name' },
  { key: 'ap_rx_power', label: '对端 Rx (dBm)', valueType: 'number' },
  { key: 'ap_tx_power', label: '对端 Tx (dBm)', valueType: 'number' },
  { key: 'ap_optical_status', label: 'AP 模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'calculation_status', label: '双向光衰', width: 230, showOverflowTooltip: true, displayValue: (row) => displayBidirectionalLoss(row.calculation_status, row.forward_loss_db, row.reverse_loss_db) },
  { key: 'optical_severity', label: '综合', valueType: 'status', cellKind: 'tag' },
  { key: 'updated_at', label: '更新时间', valueType: 'datetime' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['更新站点', '更新 AP'] },
]
const updateTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === 'trackside_ap_optical_update')
const exportTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === TRACKSIDE_AP_BUSINESS_EXPORT_ACTION)
const sampleTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === sampleTaskAction)
const sampleArtifactAvailable = computed(() => (
  task.value?.action === sampleTaskAction
  && task.value.status === 'COMPLETED'
  && task.value.available
  && Boolean(task.value.artifact_id && task.value.artifact_name)
))
const selectedSwitch = computed<TracksideSwitchDevice | null>(() => (
  adapterCatalog.value?.items.find((item) => item.device_uuid === selectedSwitchUuid.value) || null
))
const sampleVendorSupported = computed(() => selectedSwitch.value?.adapter.vendor === 'ZTE')
const adapterFeatureEnabled = computed(() => (
  isFeatureEnabled('rail.zte_trackside_switch_adapter')
  && isFeatureEnabled('web.rail_task_control')
))
const updateFeatureEnabled = computed(() => isFeatureEnabled('web.rail_trackside_ap_business_update') && isFeatureEnabled('web.rail_task_control'))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function clearTaskNotice(): void {
  if (taskNoticeTimer !== undefined) window.clearTimeout(taskNoticeTimer)
  taskNoticeTimer = undefined
  taskNotice.value = ''
  taskNoticeType.value = 'info'
}
function setTaskNotice(message: string, type: 'success' | 'info' | 'warning' | 'error' = 'info', autoHideMs = 0): void {
  clearTaskNotice()
  taskNotice.value = message
  taskNoticeType.value = type
  if (autoHideMs > 0) taskNoticeTimer = window.setTimeout(clearTaskNotice, autoHideMs)
}
function rememberTask(value: TracksideApTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function isActiveTask(value: TracksideApTask | null): boolean { return Boolean(value && activeStates.has(value.status)) }
function cleanIdentity(value: string): string { return String(value || '').trim() }
function handleStationChange(): void { filters.page = 1; void loadRows() }
function singleApUpdatePayload(row: TracksideApBusinessRow): TracksideApUpdateRequest | null {
  const apUuid = cleanIdentity(row.ap_uuid)
  if (apUuid) return { ap_uuid: apUuid }
  const apMac = cleanIdentity(row.ap_mac)
  if (apMac) return { ap_mac: apMac }
  const apName = cleanIdentity(row.ap_name)
  if (apName) return { ap_name: apName }
  return null
}
function hasApIdentity(row: TracksideApBusinessRow): boolean { return singleApUpdatePayload(row) !== null }
function autoSavedTaskIds(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(autoSaveStorageKey) || '[]')
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}
function summaryCount(summary: Record<string, unknown>, key: string): number {
  const value = Number(summary[key] ?? 0)
  return Number.isFinite(value) ? Math.max(0, value) : 0
}
function updateReasonLabel(value: string): string {
  const labels: Record<string, string> = {
    connection_incomplete: t('trackside.result.reason.connection_incomplete', '连接信息不完整'),
    no_device_connection: t('trackside.result.reason.no_device_connection', '未配置设备连接'),
    vendor_not_supported: t('trackside.result.reason.vendor_not_supported', '厂商暂不支持光衰采集'),
    unsupported_vendor: t('trackside.result.reason.vendor_not_supported', '厂商暂不支持光衰采集'),
    fit_ap_resource_failed: t('trackside.result.reason.fit_ap_resource_failed', 'FIT-AP 资源刷新失败'),
    cancelled: t('trackside.result.reason.cancelled', '采集已取消'),
    device_collection_failed: t('trackside.result.reason.device_collection_failed', '交换机采集失败'),
    fit_ap_collection_failed: t('trackside.result.reason.fit_ap_collection_failed', 'AP 光衰采集失败'),
  }
  return labels[value] || value
}
function resultMessage(key: string, fallback: string, values: Record<string, number | string> = {}): string {
  return Object.entries(values).reduce(
    (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)),
    t(key, fallback),
  )
}
function primaryFailureReason(summary: Record<string, unknown>): string {
  for (const key of ['failure_reason_counts', 'skipped_reason_counts']) {
    const counts = summary[key]
    if (!counts || typeof counts !== 'object' || Array.isArray(counts)) continue
    const reason = Object.entries(counts as Record<string, unknown>)
      .filter(([code, count]) => code !== 'no_station_switches' && Number.isFinite(Number(count)) && Number(count) > 0)
      .sort((left, right) => Number(right[1]) - Number(left[1]))[0]?.[0]
    if (reason) return updateReasonLabel(reason)
  }
  return ''
}
function updateFinishedNotice(value: TracksideApTask): { message: string; type: 'success' | 'info' | 'warning' | 'error'; autoHideMs: number } {
  const summary = value.result_summary || {}
  const status = String(summary.status || value.status || '').toUpperCase()
  const successCount = summaryCount(summary, 'success_count')
  const failedCount = summaryCount(summary, 'failed_count')
  const actionableSkippedCount = summaryCount(summary, 'actionable_skipped_count')
  const ignoredSkippedCount = summaryCount(summary, 'ignored_skipped_count')
  if (value.status === 'FAILED' || status === 'FAILED') {
    const notExecuted = actionableSkippedCount
      ? resultMessage('trackside.result.notice.not_executed_suffix', '，{count} 个目标未执行', { count: actionableSkippedCount })
      : ''
    const reason = primaryFailureReason(summary)
    const reasonText = reason
      ? resultMessage('trackside.result.notice.reason_suffix', '；主要原因：{reason}', { reason })
      : ''
    return { message: resultMessage('trackside.result.notice.failed', '轨旁 AP 光衰更新失败：成功 {success}，失败 {failed}{not_executed}{reason}，请在任务窗口查看详情', { success: successCount, failed: failedCount, not_executed: notExecuted, reason: reasonText }), type: 'error', autoHideMs: 0 }
  }
  if (value.status === 'CANCELLED' || status === 'CANCELLED') return { message: t('trackside.result.notice.cancelled', '轨旁 AP 光衰更新已取消，请在任务窗口查看详情'), type: 'warning', autoHideMs: 0 }
  if (status === 'NO_TARGET') return { message: t('trackside.result.notice.no_target', '轨旁 AP 光衰更新未找到目标，请在任务窗口查看详情'), type: 'info', autoHideMs: 4000 }
  if (failedCount > 0) return { message: resultMessage('trackside.result.notice.partial_failed', '轨旁 AP 光衰数据已刷新：成功 {success}，失败 {failed}，请在任务窗口查看详情', { success: successCount, failed: failedCount }), type: 'warning', autoHideMs: 0 }
  if (actionableSkippedCount > 0) return { message: resultMessage('trackside.result.notice.not_executed', '轨旁 AP 光衰数据已刷新：成功 {success}，{not_executed} 个目标未执行，请在任务窗口查看详情', { success: successCount, not_executed: actionableSkippedCount }), type: 'warning', autoHideMs: 0 }
  if (status === 'PARTIAL_SUCCESS') return { message: resultMessage('trackside.result.notice.partial', '轨旁 AP 光衰数据已刷新：成功 {success}，业务结果为部分成功，请在任务窗口查看详情', { success: successCount }), type: 'warning', autoHideMs: 0 }
  const ignored = ignoredSkippedCount
    ? resultMessage('trackside.result.notice.ignored_suffix', '；另有 {count} 项不适用或已忽略', { count: ignoredSkippedCount })
    : ''
  return { message: resultMessage('trackside.result.notice.success', '轨旁 AP 光衰数据已刷新：成功 {success}，失败 0{ignored}', { success: successCount, ignored }), type: 'success', autoHideMs: 4000 }
}
function rememberAutoSavedTask(taskId: string): void {
  const values = [...autoSavedTaskIds().filter((item) => item !== taskId), taskId].slice(-50)
  try { localStorage.setItem(autoSaveStorageKey, JSON.stringify(values)) } catch { /* ignore quota errors */ }
}
function shouldAutoSaveExport(value: TracksideApTask | null): value is TracksideApTask {
  if (!value || value.status !== 'COMPLETED' || !value.available || !isTracksideApBusinessArtifactTask(value) || !value.artifact_id || !value.artifact_name) return false
  return !autoSavedTaskIds().includes(value.task_id) && !autoSaveInFlight.has(value.task_id)
}
async function maybeAutoSaveExport(value: TracksideApTask | null): Promise<void> {
  if (!shouldAutoSaveExport(value)) return
  autoSaveInFlight.add(value.task_id)
  rememberAutoSavedTask(value.task_id)
  try { await saveTracksideApBusinessArtifact(value) }
  finally { autoSaveInFlight.delete(value.task_id) }
}

function handleTerminalTask(value: TracksideApTask | null): void {
  if (!value) return
  if (value.action === sampleTaskAction) {
    if (value.status === 'COMPLETED') {
      setTaskNotice('厂商适配采样完成，原始输出 ZIP 可下载', 'success', 4000)
    } else if (value.status === 'FAILED') {
      setTaskNotice('厂商适配采样失败，请在任务窗口查看原因', 'error')
    } else if (value.status === 'CANCELLED') {
      setTaskNotice('厂商适配采样已取消', 'warning')
    }
    return
  }
  if (value.action === 'trackside_ap_optical_update') {
    const notice = updateFinishedNotice(value)
    if (value.status === 'COMPLETED') {
      void loadRows().then((succeeded) => {
        if (succeeded) setTaskNotice(notice.message, notice.type, notice.autoHideMs)
      })
      return
    }
    if (!isActiveTask(value)) setTaskNotice(notice.message, notice.type, notice.autoHideMs)
    return
  }
  if (isTracksideApBusinessArtifactTask(value)) {
    if (value.status === 'COMPLETED') {
      const done = () => setTaskNotice('轨旁 AP 业务表格已生成', 'success', 4000)
      if (shouldAutoSaveExport(value)) void maybeAutoSaveExport(value).finally(done)
      else done()
      return
    }
    if (value.status === 'FAILED') setTaskNotice('轨旁 AP 业务导出失败，请在任务窗口查看原因', 'error')
    else if (value.status === 'CANCELLED') setTaskNotice('轨旁 AP 业务导出已取消，请在任务窗口查看详情', 'warning')
  }
}

function poll(): void {
  stopPolling()
  if (!task.value || !isActiveTask(task.value)) {
    handleTerminalTask(task.value)
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getTracksideApTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '轨旁 AP 任务状态读取失败') }
  }, 1000)
}

async function loadRows(reset = false): Promise<boolean> {
  if (reset) filters.page = 1
  const generation = ++loadGeneration
  const selectedStation = cleanIdentity(filters.station)
  const firstLoad = page.value === null
  if (firstLoad) initialLoading.value = true
  else refreshing.value = true
  error.value = ''
  let succeeded = false
  try {
    const nextPage = await listTracksideApBusiness({ ...filters })
    if (generation === loadGeneration) {
      page.value = nextPage
      succeeded = true
    }
  } catch (reason) {
    if (generation === loadGeneration) error.value = failure(reason, '轨旁 AP 业务加载失败')
  } finally {
    if (generation === loadGeneration) {
      initialLoading.value = false
      refreshing.value = false
    }
  }
  if (succeeded && selectedStation && !(page.value?.station_options || []).includes(selectedStation)) {
    filters.station = ''
    filters.page = 1
    void loadRows(true)
  }
  return succeeded
}

async function loadSwitchAdapters(): Promise<void> {
  if (!isFeatureEnabled('rail.zte_trackside_switch_adapter')) return
  adapterLoading.value = true
  adapterError.value = ''
  try {
    const catalog = await listTracksideSwitchAdapters()
    adapterCatalog.value = catalog
    if (!catalog.items.some((item) => item.device_uuid === selectedSwitchUuid.value)) {
      selectedSwitchUuid.value = (
        catalog.items.find(
          (item) => item.adapter.verification_status === 'DOCUMENT_SAMPLE_ONLY',
        ) || catalog.items[0]
      )?.device_uuid || ''
    }
  } catch (reason) {
    adapterError.value = failure(reason, '交换机厂商适配信息加载失败')
  } finally {
    adapterLoading.value = false
  }
}

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string, scopeKey: string, notice = '任务已提交，详细进度请查看任务窗口'): Promise<void> {
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true; error.value = ''; clearTaskNotice()
  try {
    const started = await factory()
    rememberTask(started)
    setTaskNotice(notice, 'info')
    poll()
    openTaskWindow()
  }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { taskSubmitting.value = false; pendingScopeKey.value = '' }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate({}), '轨旁 AP 光衰更新启动失败', 'update:all') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败', `update:station:${row.site}`) }
function updateAp(row: TracksideApBusinessRow): void {
  const payload = singleApUpdatePayload(row)
  if (!payload) { error.value = '缺少 AP 身份，无法定向更新'; return }
  const target = cleanIdentity(row.ap_name) || cleanIdentity(row.ap_mac) || cleanIdentity(row.ap_uuid)
  const scopeValue = payload.ap_uuid || payload.ap_mac || payload.ap_name || target
  void startTask(
    () => startTracksideApUpdate(payload),
    'AP 更新启动失败',
    `update:ap:${scopeValue}`,
  )
}
function exportBusiness(): void { void startTask(() => startTracksideApBusinessExport(), '轨旁 AP 业务导出启动失败', 'export:business', '轨旁 AP 业务表格正在生成，详细进度请查看任务窗口') }
function startVendorSample(): void {
  const selected = selectedSwitch.value
  if (!selected) {
    adapterError.value = '请选择要采样的交换机'
    return
  }
  if (!sampleVendorSupported.value) {
    adapterError.value = '第一阶段仅支持 ZTE 交换机厂商适配采样'
    return
  }
  void startTask(
    () => startTracksideSwitchSample({
      device_uuid: selected.device_uuid,
      vendor: selected.adapter.vendor,
      command_profile: selected.adapter.profile.profile_id,
      selected_interface: selectedInterface.value.trim(),
      requested_commands: [],
    }),
    '厂商适配采样启动失败',
    `sample:${selected.device_uuid}`,
    '厂商适配采样已提交，详细进度请查看任务窗口',
  )
}
async function downloadVendorSample(): Promise<void> {
  const current = task.value
  if (!sampleArtifactAvailable.value || !current) return
  sampleDownloading.value = true
  try {
    const result = await downloadBackendResource(
      tracksideSwitchSampleDownloadRequest(
        current.artifact_id,
        current.artifact_name,
      ),
    )
    if (result.status === 'saved') setTaskNotice('厂商适配采样 ZIP 已保存', 'success', 4000)
    else if (result.status === 'started') setTaskNotice('浏览器已开始下载采样 ZIP', 'success', 4000)
    else if (result.status === 'failed') throw new Error(result.error || '采样 ZIP 保存失败')
  } catch (reason) {
    adapterError.value = failure(reason, '采样 ZIP 保存失败')
  } finally {
    sampleDownloading.value = false
  }
}
function capabilityStatusLabel(status: TracksideSwitchCapabilityStatus): string {
  return {
    DOCUMENTED: '已登记',
    IMPLEMENTED: '已实现，待验证',
    SAMPLE_REQUIRED: '待采集真实样本',
    VERIFIED: '已验证',
    UNSUPPORTED: '当前不支持',
  }[status]
}
function profileCommands(selected: TracksideSwitchDevice): Array<{ label: string; commands: string[] }> {
  const profile = selected.adapter.profile
  return [
    { label: '设备版本', commands: profile.device_version },
    { label: '接口摘要', commands: profile.interface_brief },
    { label: '接口详情', commands: profile.interface_detail },
    { label: '光模块摘要', commands: profile.optical_brief },
    { label: '光模块详情', commands: profile.optical_detail },
    { label: 'LLDP 全局候选', commands: profile.lldp_global_candidates },
    { label: 'LLDP 接口候选', commands: profile.lldp_interface_candidates },
    { label: 'LLDP 配置候选', commands: profile.lldp_config_candidates },
  ]
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}

async function recoverTasks(): Promise<void> {
  if (!isFeatureEnabled('web.rail_task_control')) return
  try {
    const rows = (await recoverTracksideApTasks()).filter((item) => businessTaskActions.has(item.action))
    const saved = localStorage.getItem(storageKey) || ''
    const savedTask = rows.find((item) => item.task_id === saved)
    const activeUpdate = rows.find((item) => item.action === 'trackside_ap_optical_update' && isActiveTask(item))
    const activeAny = rows.find((item) => isActiveTask(item))
    const recovered = savedTask && isActiveTask(savedTask) ? savedTask : activeUpdate || activeAny || null
    rememberTask(recovered)
    if (recovered) setTaskNotice('检测到正在运行的轨旁 AP 任务，详细进度请查看任务窗口', 'info')
    else clearTaskNotice()
    poll()
  } catch (reason) { error.value = failure(reason, '轨旁 AP 任务恢复失败') }
}

onMounted(() => { void Promise.all([loadRows(), loadSwitchAdapters(), recoverTasks()]) })
onBeforeUnmount(() => { stopPolling(); clearTaskNotice() })
</script>

<template>
  <section class="trackside-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · TRACKSIDE AP</p><h1>轨旁 AP 业务</h1><p>交换机端口、当前 AP、光功率与异常状态来自正式设备事实和既有光衰规则。</p></div>
      <div class="actions">
        <el-button :loading="refreshing" :disabled="initialLoading" @click="loadRows()">刷新</el-button>
        <el-button
          type="primary"
          :loading="taskSubmitting"
          :disabled="updateTaskRunning || !updateFeatureEnabled"
          @click="updateAll"
        >更新全部光衰</el-button>
        <el-button
          :loading="taskSubmitting"
          :disabled="exportTaskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_export') || !isFeatureEnabled('web.rail_task_control')"
          @click="exportBusiness"
        >导出表格</el-button>
        <el-button @click="openTaskWindow">打开任务窗口</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="true" @close="error = ''"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <el-alert v-if="taskNotice" :title="taskNotice" :type="taskNoticeType" show-icon :closable="taskNoticeType === 'error'" @close="clearTaskNotice" />
    <section
      v-if="isFeatureEnabled('rail.zte_trackside_switch_adapter')"
      class="adapter-section"
      aria-label="轨旁交换机厂商适配"
    >
      <div class="adapter-toolbar">
        <div class="adapter-status">
          <span class="adapter-kicker">{{ selectedSwitch?.adapter.vendor_label || '中兴 ZTE' }}</span>
          <strong>{{ selectedSwitch?.adapter.adaptation_status || '已接入，待实机验证' }}</strong>
          <span>{{ selectedSwitch ? `${selectedSwitch.adapter.platform} ${selectedSwitch.adapter.product_family}` : '暂无已接入交换机' }}</span>
        </div>
        <el-select
          v-model="selectedSwitchUuid"
          class="adapter-device-select"
          filterable
          :loading="adapterLoading"
          placeholder="选择交换机"
        >
          <el-option
            v-for="item in adapterCatalog?.items || []"
            :key="item.device_uuid"
            :label="`${item.device_name} · ${item.adapter.vendor_label}`"
            :value="item.device_uuid"
          />
        </el-select>
        <el-input
          v-model="selectedInterface"
          class="adapter-interface-input"
          clearable
          placeholder="接口（可选）"
        />
        <el-button
          type="primary"
          :loading="taskSubmitting && sampleTaskRunning"
          :disabled="!selectedSwitch || !sampleVendorSupported || sampleTaskRunning || !adapterFeatureEnabled"
          :title="sampleVendorSupported ? '' : '第一阶段仅支持 ZTE 交换机厂商适配采样'"
          @click="startVendorSample"
        >启动厂商采样</el-button>
        <el-button
          :disabled="!selectedSwitch"
          @click="adapterDetailsVisible = !adapterDetailsVisible"
        >{{ adapterDetailsVisible ? '收起 Profile' : '查看 Profile' }}</el-button>
        <el-button
          v-if="sampleArtifactAvailable"
          :loading="sampleDownloading"
          @click="downloadVendorSample"
        >下载原始输出 ZIP</el-button>
      </div>
      <p v-if="adapterError" class="adapter-error">{{ adapterError }}</p>
      <div v-if="adapterDetailsVisible && selectedSwitch" class="adapter-details">
        <div class="adapter-meta">
          <span>Profile</span>
          <strong>{{ selectedSwitch.adapter.profile.profile_id }}</strong>
          <span>参考版本</span>
          <strong>{{ selectedSwitch.adapter.profile.reference_version }}</strong>
          <span>验证状态</span>
          <strong>{{ selectedSwitch.adapter.verification_status }}</strong>
          <span>特权模式</span>
          <strong>{{ selectedSwitch.adapter.profile.privilege_required ? '按配置启用' : '当前不要求' }}</strong>
        </div>
        <div class="adapter-detail-columns">
          <div>
            <h2>能力状态</h2>
            <ul class="capability-list">
              <li v-for="capability in selectedSwitch.adapter.capabilities" :key="capability.key">
                <span>{{ capability.label }}</span>
                <el-tag :class="`capability-${capability.status.toLowerCase()}`">{{ capabilityStatusLabel(capability.status) }}</el-tag>
                <small>{{ capability.message }}</small>
              </li>
            </ul>
          </div>
          <div>
            <h2>只读命令 Profile</h2>
            <dl class="profile-command-list">
              <template v-for="group in profileCommands(selectedSwitch)" :key="group.label">
                <dt>{{ group.label }}</dt>
                <dd>
                  <code v-for="command in group.commands" :key="command">{{ command }}</code>
                  <span v-if="!group.commands.length">—</span>
                </dd>
              </template>
            </dl>
          </div>
          <div>
            <h2>待实机验证</h2>
            <ul class="pending-list">
              <li v-for="item in selectedSwitch.adapter.pending_items" :key="item">{{ item }}</li>
            </ul>
            <p class="attenuation-note">尚未接入真实节点，无法计算光衰</p>
          </div>
        </div>
      </div>
    </section>
    <div v-if="page" class="summary-grid">
      <article><span>站点交换机</span><strong>{{ page.device_count }}</strong></article><article><span>候选 AP 端口</span><strong>{{ page.candidate_interface_count }}</strong></article><article><span>光衰异常</span><strong>{{ page.optical_abnormal_count }}</strong></article><article><span>FIT-AP 资源</span><strong>{{ page.fit_ap_resource_count }}</strong></article><article><span>查询 / 构建</span><strong>{{ page.query_ms }} / {{ page.build_ms }} ms</strong></article>
    </div>
    <div class="content-card">
      <div class="toolbar">
        <el-input v-model="filters.query" clearable placeholder="交换机、接口、AP、MAC" @keyup.enter="loadRows(true)" />
        <el-select
          v-model="filters.station"
          class="station-select"
          clearable
          filterable
          placeholder="全部站点"
          :title="filters.station || '全部站点'"
          @change="handleStationChange"
        >
          <el-option
            v-for="station in page?.station_options || []"
            :key="station"
            :label="station"
            :value="station"
            :title="station"
          />
        </el-select>
        <el-checkbox v-model="filters.optical_anomaly_only">仅光衰异常</el-checkbox>
        <el-button type="primary" :loading="refreshing" :disabled="initialLoading" @click="loadRows(true)">查询</el-button>
        <span v-if="refreshing" class="refresh-indicator">正在刷新，当前数据保持显示</span>
      </div>
      <NcDataTable
        v-loading="initialLoading"
        table-id="trackside-ap-business"
        route-key="/rail-transit/trackside-ap-business"
        :data="page?.items || []"
        :columns="businessColumns"
        height="calc(100vh - 330px)"
        :empty-text="page?.empty_reason || '暂无轨旁 AP 业务数据'"
      >
        <template #cell-switch_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_rx_power) }}</span></template>
        <template #cell-switch_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_tx_power) }}</span></template>
        <template #cell-switch_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.switch_optical_status).tagType" :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ tracksideOpticalPresentation(row.switch_optical_status).label }}</el-tag></template>
        <template #cell-ap_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_rx_power) }}</span></template>
        <template #cell-ap_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_tx_power) }}</span></template>
        <template #cell-ap_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.ap_optical_status).tagType" :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ tracksideOpticalPresentation(row.ap_optical_status).label }}</el-tag></template>
        <template #cell-optical_severity="{ row }"><el-tag :type="tracksideOpticalPresentation(row.optical_severity).tagType" :class="tracksideOpticalPresentation(row.optical_severity).className">{{ tracksideOpticalPresentation(row.optical_severity).label }}</el-tag></template>
        <template #cell-actions="{ row }"><el-button link type="primary" :disabled="updateTaskRunning || !row.site || !updateFeatureEnabled" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :title="hasApIdentity(row) ? '' : '缺少 AP 身份，无法定向更新'" :disabled="updateTaskRunning || !hasApIdentity(row) || !updateFeatureEnabled" @click="updateAp(row)">更新 AP</el-button></template>
      </NcDataTable>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="page?.page || filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" /></div>
    </div>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.pagination,.adapter-toolbar{display:flex;align-items:center;gap:12px}.page-heading,.pagination{justify-content:space-between}.page-heading h1{margin:2px 0 6px}.page-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:0}.actions,.toolbar,.adapter-toolbar{flex-wrap:wrap}.adapter-section{padding:12px 0;border-block:1px solid var(--el-border-color-lighter)}.adapter-status{display:grid;grid-template-columns:auto auto;align-items:baseline;gap:2px 10px;min-width:240px}.adapter-status>span:last-child{grid-column:1/-1;color:var(--el-text-color-secondary);font-size:12px}.adapter-kicker{color:var(--el-color-primary);font-size:12px;font-weight:700}.adapter-device-select{width:260px}.adapter-interface-input{width:180px}.adapter-error{margin:8px 0 0;color:var(--el-color-danger);font-size:13px}.adapter-details{margin-top:14px;padding-top:14px;border-top:1px solid var(--el-border-color-lighter)}.adapter-meta{display:grid;grid-template-columns:auto minmax(130px,1fr) auto minmax(130px,1fr);gap:6px 12px;font-size:13px}.adapter-meta span{color:var(--el-text-color-secondary)}.adapter-detail-columns{display:grid;grid-template-columns:minmax(240px,1fr) minmax(300px,1.2fr) minmax(240px,1fr);gap:24px;margin-top:16px}.adapter-detail-columns h2{margin:0 0 10px;font-size:14px}.capability-list,.pending-list{margin:0;padding:0;list-style:none}.capability-list li{display:grid;grid-template-columns:minmax(92px,auto) auto;gap:4px 8px;padding:7px 0;border-bottom:1px solid var(--el-border-color-extra-light)}.capability-list small{grid-column:1/-1;color:var(--el-text-color-secondary)}.pending-list li{padding:4px 0;color:var(--el-text-color-regular);font-size:13px}.pending-list li::before{content:"·";margin-right:8px;color:var(--el-color-warning)}.profile-command-list{display:grid;grid-template-columns:110px minmax(0,1fr);gap:7px 10px;margin:0;font-size:13px}.profile-command-list dt{color:var(--el-text-color-secondary)}.profile-command-list dd{display:flex;flex-direction:column;gap:3px;margin:0;min-width:0}.profile-command-list code{overflow-wrap:anywhere;color:var(--el-text-color-primary)}.attenuation-note{margin:12px 0 0;padding:9px 10px;border-left:3px solid var(--el-color-warning);background:var(--el-fill-color-light);font-size:13px}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{margin-bottom:12px}.toolbar .el-input{width:230px}.station-select{width:260px}.refresh-indicator{color:var(--el-color-primary);font-size:13px}.pagination{padding-top:12px}.optical-normal{color:var(--el-color-success)}.optical-notice,.optical-warning{color:var(--el-color-warning)}.optical-alarm,.optical-link-abnormal,.optical-link-down,.optical-no-light,.optical-offline{color:var(--el-color-danger);font-weight:600}.optical-no-module,.optical-missing,.optical-skipped,.optical-not-collected,.optical-unknown{color:var(--el-text-color-secondary)}@media(max-width:1100px){.adapter-detail-columns{grid-template-columns:1fr 1fr}.adapter-detail-columns>div:last-child{grid-column:1/-1}}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}.adapter-detail-columns{grid-template-columns:1fr}.adapter-detail-columns>div:last-child{grid-column:auto}.adapter-meta{grid-template-columns:auto minmax(0,1fr)}}@media(max-width:640px){.adapter-device-select,.adapter-interface-input{width:100%}.adapter-status{min-width:0;width:100%}.adapter-meta{grid-template-columns:1fr}}
</style>
