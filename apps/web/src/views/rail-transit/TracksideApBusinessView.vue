<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  getTracksideApBusinessExportProposal,
  listTracksideApBusiness,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
} from '../../api/tracksideApBusiness'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import { t } from '../../i18n/runtime'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { useExternalTerminalLauncher } from '../../composables/useExternalTerminalLauncher'
import { getPlatformAdapter } from '../../platform/runtime'
import type { NcDataTableContextMenuItem } from '../../components/table/NcDataTableContextMenu'
import { BEFORE_SITE_SWITCH_EVENT } from '../../workspace/site-switch'
import type {
  TracksideApBusinessPage,
  TracksideApBusinessRow,
  TracksideApScopeExcluded,
  TracksideApUnmatchedOnline,
  TracksideApTask,
  TracksideApUpdateRequest,
} from '../../types/tracksideApBusiness'
import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import { displayInterfaceName } from '../../utils/interfaceName'
import { TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE } from './tracksideApBusinessArtifact'
import { activeTaskStatuses } from '../../utils/taskStatus'
import {
  displayLldpStatus,
  displayPowerThreshold,
  displaySwitchVendor,
  displayTracksideSnapshotTime,
  displayTracksideValue,
  tracksideOpticalPresentation,
} from './tracksideApBusinessDisplay'

const userSelectedExport = useUserSelectedExport()
const taskStore = useTaskStore()
const terminalLauncher = useExternalTerminalLauncher()
const {
  busy: terminalLoading,
  fitApTerminalVisible: terminalVisible,
  fitApTerminalType: terminalType,
  fitApTerminalOptions: terminalOptions,
  launchSelectedFitApTerminal,
} = terminalLauncher
const activeStates = new Set(activeTaskStatuses)
const businessTaskTypes = new Set([
  'trackside_ap_optical_update',
  TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE,
])
const businessProjectionTaskTypes = new Set([
  'trackside_ap_optical_update',
  'device_detail_collect',
  'device_optical_refresh',
  'ac_fit_ap_resources_refresh',
  'ac_fit_ap_detail_refresh',
  'ac_fit_ap_verbose_all_refresh',
  'ac_fit_ap_verbose_selected_refresh',
  'ac_fit_ap_optical_refresh',
])
const initialLoading = ref(false)
const refreshing = ref(false)
const taskSubmitting = ref(false)
const pendingScopeKey = ref('')
const loadError = ref('')
const actionError = ref('')
const page = ref<TracksideApBusinessPage | null>(null)
const excludedVisible = ref(false)
const unmatchedVisible = ref(false)
const currentTaskId = ref('')
const filters = reactive({ station: '', query: '', optical_anomaly_only: false, page: 1, page_size: 50 })
const pageActive = ref(true)
const pageDirty = ref(false)
const lastLoadedAt = ref(0)
const pendingRefreshReason = ref('')
const savedTableScroll = reactive({ top: 0, left: 0 })
const businessTableHost = ref<HTMLElement | null>(null)
const desktopHost = computed(() => getPlatformAdapter().hostType === 'electron')
const deviceTerminalFeatureEnabled = computed(() => isFeatureEnabled('web.device_management_desktop'))
const fitApTerminalFeatureEnabled = computed(() => (
  isFeatureEnabled('web.ac_fit_ap_external_terminal')
  && isFeatureEnabled('desktop.native_bridge')
))
let loadGeneration = 0
let pageMounted = false
let taskObservationReady = false
const BUSINESS_PAGE_STALE_MS = 5 * 60 * 1000
const terminalTaskRefreshes = new Set<string>()

const businessColumns: NcTableColumn<TracksideApBusinessRow>[] = [
  { key: 'site', label: '站点', valueType: 'name', fixed: 'left' },
  { key: 'device_name', label: '车站交换机', valueType: 'name', fixed: 'left' },
  { key: 'switch_vendor', label: '交换机厂商', valueType: 'name', displayValue: (row) => displaySwitchVendor(row.switch_vendor) },
  { key: 'interface_name', label: '接口', valueType: 'port', displayValue: (row) => displayTracksideValue(displayInterfaceName(row.interface_name)) },
  { key: 'lldp_match_status', label: 'LLDP 状态', valueType: 'status', displayValue: (row) => displayLldpStatus(row.lldp_match_status) },
  { key: 'link_status', label: '链路', valueType: 'status' },
  { key: 'switch_interface_updated_at', label: t('trackside.snapshot.interface_time', '接口采集时间'), valueType: 'datetime', displayValue: (row) => displayTracksideSnapshotTime(row.switch_interface_updated_at, row.switch_interface_data_status) },
  { key: 'port_type', label: '端口类型', valueType: 'status', width: 100 },
  { key: 'description', label: '描述', valueType: 'description', width: 90, maxWidth: 120, align: 'center', headerAlign: 'center', stretch: 'none', showOverflowTooltip: true },
  { key: 'pvid', label: 'PVID', valueType: 'number', displayValue: (row) => displayTracksideValue(row.pvid) },
  { key: 'vlan', label: 'VLAN', displayValue: (row) => displayTracksideValue(row.vlan) },
  { key: 'switch_rx_power', label: '本端 Rx (dBm)', valueType: 'number' },
  { key: 'switch_tx_power', label: '本端 Tx (dBm)', valueType: 'number' },
  { key: 'switch_rx_low_alarm', label: 'Rx 门限', displayValue: (row) => displayPowerThreshold(row.switch_rx_low_alarm, row.switch_rx_high_alarm) },
  { key: 'switch_tx_low_alarm', label: 'Tx 门限', displayValue: (row) => displayPowerThreshold(row.switch_tx_low_alarm, row.switch_tx_high_alarm) },
  { key: 'switch_optical_status', label: '模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'switch_optical_updated_at', label: t('trackside.snapshot.optical_time', '模块采集时间'), valueType: 'datetime', displayValue: (row) => displayTracksideSnapshotTime(row.switch_optical_updated_at, row.switch_optical_data_status) },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac', stretch: 'priority' },
  { key: 'ap_name', label: '当前轨旁 AP', valueType: 'name' },
  { key: 'ap_rx_power', label: 'AP Rx (dBm)', valueType: 'number' },
  { key: 'ap_tx_power', label: 'AP Tx (dBm)', valueType: 'number' },
  { key: 'ap_device_optical_status', label: t('trackside.ap_device_optical_status', 'AP 设备模块状态'), valueType: 'status', cellKind: 'tag' },
  { key: 'ap_optical_status', label: t('trackside.ap_optical_status', 'AP 业务光衰'), valueType: 'status', cellKind: 'tag' },
  { key: 'ap_business_threshold_dbm', label: t('trackside.ap_business_threshold', 'AP 业务门限'), minWidth: 165, displayValue: (row) => `AP Rx ≥ ${Number(row.ap_business_threshold_dbm ?? -13.90).toFixed(2)} dBm` },
  { key: 'ap_business_reason', label: t('trackside.ap_business_reason', 'AP 业务判定原因'), valueType: 'description', align: 'left', alignmentReason: 'long-text', minWidth: 300, showOverflowTooltip: true },
  { key: 'optical_severity', label: t('trackside.business_overall_status', '业务综合状态'), valueType: 'status', cellKind: 'tag' },
  { key: 'updated_at', label: t('trackside.snapshot.business_time', '业务更新时间'), valueType: 'datetime' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['更新站点', '更新 AP'] },
]

const excludedColumns: NcTableColumn<TracksideApScopeExcluded>[] = [
  { key: 'device_name', label: '设备名称', valueType: 'name', minWidth: 170 },
  { key: 'station_name', label: '归属站点', valueType: 'name', minWidth: 150 },
  { key: 'operation_status', label: '当前工作状态', valueType: 'status', width: 130 },
  { key: 'project_phase', label: '建设批次', valueType: 'status', width: 120 },
  { key: 'reason', label: '排除原因', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
]
const unmatchedColumns: NcTableColumn<TracksideApUnmatchedOnline>[] = [
  { key: 'ap_name', label: 'AP名称', valueType: 'name', minWidth: 170 },
  { key: 'mac', label: 'AP MAC', valueType: 'mac', width: 170 },
  { key: 'ac_status', label: 'AC状态', valueType: 'status', width: 130 },
  { key: 'runtime_station_text', label: '运行态站点', valueType: 'name', minWidth: 170 },
  { key: 'association_status', label: '当前关联状态', valueType: 'status', width: 150 },
  { key: 'reason', label: '资料状态', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
  { key: 'suggested_action', label: '建议处理', valueType: 'description', minWidth: 300, align: 'left', alignmentReason: 'long-text' },
]
const currentTask = computed<TaskItem | null>(() => (
  taskStore.tasks.find((item) => item.id === currentTaskId.value) || null
))
const updateTaskRunning = computed(() => taskStore.tasks.some(
  (item) => item.type === 'trackside_ap_optical_update' && activeStates.has(item.status),
))
const exportTaskRunning = computed(() => taskStore.tasks.some(
  (item) => item.type === TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE && activeStates.has(item.status),
))
const updateFeatureEnabled = computed(() => isFeatureEnabled('web.rail_trackside_ap_business_update') && isFeatureEnabled('web.rail_task_control'))
const lldpPendingCount = computed(() => (
  (page.value?.fit_ap_lldp_snapshot_stale_count || 0)
  + (page.value?.fit_ap_lldp_exact_match_pending_count || 0)
))
const lldpConflictCount = computed(() => (
  (page.value?.fit_ap_current_conflict_count || 0)
  + (page.value?.fit_ap_ambiguous_online_count || 0)
))
const planningMissingCount = computed(() => {
  const explicit = page.value?.fit_ap_planning_missing_count
  if (explicit !== undefined) return explicit + (page.value?.fit_ap_station_master_missing_count || 0)
  return lldpPendingCount.value ? 0 : (page.value?.fit_ap_unmatched_online_count || 0)
})
const otherUnmatchedCount = computed(() => Math.max(
  0,
  (page.value?.fit_ap_unmatched_online_count || 0)
  - lldpPendingCount.value
  - lldpConflictCount.value
  - planningMissingCount.value,
))
const unmatchedLabel = computed(() => {
  if (!page.value?.runtime_snapshot && page.value?.fit_ap_planning_missing_count === undefined) return '基础资料待补充'
  if (lldpPendingCount.value && !planningMissingCount.value && !lldpConflictCount.value) return '等待 LLDP 同步'
  if (planningMissingCount.value && !lldpPendingCount.value && !lldpConflictCount.value) return '基础资料待补充'
  return '待关联在线 AP'
})

const businessContextMenuItems = computed<NcDataTableContextMenuItem<TracksideApBusinessRow>[]>(() => [
  {
    key: 'switch-external-terminal',
    label: t('ac.context.external_terminal', '打开外部终端'),
    visible: ({ columnKey }) => columnKey === 'device_name',
    disabled: ({ row }) => !desktopHost.value || !deviceTerminalFeatureEnabled.value || !row.switch_terminal_available,
    disabledReason: ({ row }) => !desktopHost.value
      ? '仅 Electron Desktop 可用'
      : !deviceTerminalFeatureEnabled.value
        ? '外部终端功能未启用'
        : row.switch_terminal_unavailable_reason || '未找到可启动终端的交换机设备记录',
    action: ({ row }) => openDeviceExternalTerminal(row.switch_device_uuid || ''),
  },
  {
    key: 'ap-external-terminal',
    label: t('ac.context.external_terminal', '打开外部终端'),
    visible: ({ columnKey }) => columnKey === 'ap_mac' || columnKey === 'ap_name',
    disabled: ({ row }) => !desktopHost.value || !fitApTerminalFeatureEnabled.value || !row.ap_terminal_available,
    disabledReason: ({ row }) => !desktopHost.value
      ? '仅 Electron Desktop 可用'
      : !fitApTerminalFeatureEnabled.value
        ? '外部终端功能未启用'
        : row.ap_terminal_unavailable_reason || '未关联到 FIT-AP 资源',
    action: ({ row }) => openFitApExternalTerminal(row),
  },
  {
    key: 'copy-cell',
    label: t('ac.context.copy_cell', '复制单元格'),
    action: ({ cellValue }) => copyText(String(cellValue ?? '')),
  },
  {
    key: 'copy-row',
    label: t('ac.context.copy_row', '复制整行'),
    action: ({ row }) => copyBusinessRow(row),
  },
])

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function cleanIdentity(value: string): string { return String(value || '').trim() }
function businessRowKey(row: TracksideApBusinessRow): string {
  return [
    row.effective_station_id || row.station_id || row.site,
    row.device_name,
    row.interface_name,
    row.ap_mac || row.ap_uuid,
  ].map(cleanIdentity).join('|')
}
function excludedRowKey(row: TracksideApScopeExcluded): string { return cleanIdentity(row.item_id) }
function onlineResourceRowKey(row: TracksideApUnmatchedOnline): string { return cleanIdentity(row.item_id) }
function handleStationChange(): void { filters.page = 1; void loadRows() }
function singleApUpdatePayload(row: TracksideApBusinessRow): TracksideApUpdateRequest | null {
  const apUuid = cleanIdentity(row.ap_uuid)
  if (apUuid) return { ap_uuid: apUuid }
  const apMac = cleanIdentity(row.ap_mac)
  if (apMac) return { ap_mac: apMac }
  return null
}
function hasApIdentity(row: TracksideApBusinessRow): boolean { return singleApUpdatePayload(row) !== null }
function emptyReasonLabel(value: string): string {
  const labels: Record<string, string> = {
    'trackside.empty.no_devices': '当前工作范围内没有可用的车站交换机。',
    'trackside.empty.no_interfaces': '当前车站交换机没有接口事实。',
    'trackside.empty.no_ap_interfaces': '已找到车站交换机，但未识别到候选 AP 端口。',
    'trackside.empty.no_optical_or_fit': '已找到候选 AP 端口，但暂未采集光衰或 FIT-AP 运行态。',
    'trackside.empty.no_lldp_or_fit': '已找到候选 AP 端口，但暂未采集 LLDP 或 FIT-AP 运行态。',
    'trackside.empty.no_fit_ap_optical': '已发现候选 AP 端口，暂未关联 AP 光衰资料。',
    'trackside.empty.no_fit_ap_resource': '已发现候选 AP 端口，部分端口尚未关联 AP 运行态资料。',
    'trackside.empty.no_rows': '已发现候选 AP 端口，部分端口尚未关联 AP 运行态资料。',
  }
  if (labels[value]) return labels[value]
  if (value.startsWith('trackside.')) return '暂无轨旁 AP 业务数据'
  return value || '暂无轨旁 AP 业务数据'
}
type DataAvailability = 'loaded' | 'partial' | 'failed' | 'unloaded'
function dataAvailability(sources: string[]): DataAvailability {
  if (!page.value) return 'unloaded'
  const statuses = page.value.source_statuses
  if (!statuses) return 'loaded'
  const values = sources.map((source) => statuses[source]).filter(Boolean)
  if (values.includes('failed')) return 'failed'
  if (values.includes('partial')) return 'partial'
  return 'loaded'
}
function metricValue(value: number | undefined, sources: string[]): string | number {
  const availability = dataAvailability(sources)
  if (availability === 'unloaded') return '—'
  if (availability === 'failed') return '加载失败'
  if (availability === 'partial') return '部分可用'
  return Number(value ?? 0)
}
async function loadRows(reset = false): Promise<boolean> {
  if (reset) filters.page = 1
  const generation = ++loadGeneration
  const selectedStation = cleanIdentity(filters.station)
  const firstLoad = page.value === null
  if (firstLoad) initialLoading.value = true
  else refreshing.value = true
  loadError.value = ''
  let succeeded = false
  try {
    const nextPage = await listTracksideApBusiness({ ...filters })
    if (generation === loadGeneration) {
      page.value = nextPage
      pageDirty.value = false
      pendingRefreshReason.value = ''
      lastLoadedAt.value = Date.now()
      succeeded = true
    }
  } catch (reason) {
    if (generation === loadGeneration) {
      loadError.value = page.value
        ? '部分数据不可用，已保留最后成功数据。'
        : failure(reason, '轨旁 AP 业务加载失败')
    }
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

function tableScrollElement(): HTMLElement | null {
  const host = businessTableHost.value
  return host?.querySelector<HTMLElement>('.el-table__body-wrapper .el-scrollbar__wrap')
    || host?.querySelector<HTMLElement>('.el-table__body-wrapper')
    || host?.querySelector<HTMLElement>('.nc-data-table__scroll')
    || null
}

function saveTableScroll(): void {
  const element = tableScrollElement()
  if (!element) return
  savedTableScroll.top = element.scrollTop
  savedTableScroll.left = element.scrollLeft
}

async function restoreTableScroll(): Promise<void> {
  await nextTick()
  const element = tableScrollElement()
  if (!element) return
  element.scrollTop = savedTableScroll.top
  element.scrollLeft = savedTableScroll.left
}

function markPageDirty(reason: string): void {
  pageDirty.value = true
  pendingRefreshReason.value = reason
}

async function openDeviceExternalTerminal(deviceUuid: string): Promise<void> {
  const target = cleanIdentity(deviceUuid)
  if (!target || !desktopHost.value || !deviceTerminalFeatureEnabled.value) return
  try {
    const preflight = await terminalLauncher.preflightDeviceTerminalTargets([target])
    if (!preflight) return
    if (!preflight.launchableDevices.length) {
      terminalLauncher.showPreflightSkipped(preflight.skippedDevices)
      return
    }
    const result = await terminalLauncher.launchDeviceTerminalTargets(
      preflight.launchableDevices,
      preflight.terminalType,
    )
    if (result) {
      terminalLauncher.showLaunchResult(result)
    }
  } catch (reason) {
    ElMessage.error(failure(reason, '打开外部终端失败'))
  }
}

async function openFitApExternalTerminal(row: TracksideApBusinessRow): Promise<void> {
  if (!desktopHost.value || !fitApTerminalFeatureEnabled.value || !row.ap_terminal_available) return
  await terminalLauncher.requestFitApTerminal({
    acId: row.ap_terminal_ac_id || '',
    apId: row.ap_terminal_ap_id || '',
  })
}

async function copyText(value: string): Promise<void> {
  await navigator.clipboard.writeText(value)
  ElMessage.success(t('common.copied', '已复制'))
}

async function copyBusinessRow(row: TracksideApBusinessRow): Promise<void> {
  await copyText([
    row.site,
    row.device_name,
    row.interface_name,
    row.ap_mac,
    row.ap_name,
    displayTracksideValue(row.switch_rx_power),
    displayTracksideValue(row.ap_rx_power),
    row.updated_at,
  ].join('\t'))
}

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string, scopeKey: string): Promise<void> {
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true
  actionError.value = ''
  try {
    const started = await factory()
    currentTaskId.value = started.task_id
    terminalTaskRefreshes.delete(started.task_id)
    await taskStore.refresh()
  }
  catch (reason) { actionError.value = failure(reason, fallback) }
  finally { taskSubmitting.value = false; pendingScopeKey.value = '' }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate({}), '轨旁 AP 光衰更新启动失败', 'update:all') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败', `update:station:${row.site}`) }
function updateAp(row: TracksideApBusinessRow): void {
  const payload = singleApUpdatePayload(row)
  if (!payload) { actionError.value = '缺少 AP 身份，无法定向更新'; return }
  const target = cleanIdentity(row.ap_mac) || cleanIdentity(row.ap_uuid)
  const scopeValue = payload.ap_uuid || payload.ap_mac || target
  void startTask(
    () => startTracksideApUpdate(payload),
    'AP 更新启动失败',
    `update:ap:${scopeValue}`,
  )
}
async function exportBusiness(): Promise<void> {
  const scopeKey = 'export:business'
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true
  actionError.value = ''
  try {
    const proposal = await getTracksideApBusinessExportProposal()
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.trackside_business',
      suggestedName: proposal.suggested_name,
      submit: () => startTracksideApBusinessExport(proposal),
    })
    if (result.status === 'cancelled') return
    currentTaskId.value = result.task.task_id
    await taskStore.refresh()
  } catch (reason) {
    actionError.value = failure(reason, '轨旁 AP 业务导出启动失败')
  } finally {
    taskSubmitting.value = false
    pendingScopeKey.value = ''
  }
}

function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}

watch(
  () => taskStore.tasks.map((item) => `${item.id}:${item.type}:${item.status}`),
  () => {
    if (!taskObservationReady) return
    const newlyCompleted = taskStore.tasks.filter((item) => (
      businessProjectionTaskTypes.has(item.type)
      && !activeStates.has(item.status)
      && !terminalTaskRefreshes.has(item.id)
    ))
    if (!newlyCompleted.length) return
    for (const item of newlyCompleted) terminalTaskRefreshes.add(item.id)
    if (pageActive.value) void loadRows()
    else markPageDirty('轨旁 AP 业务相关任务已完成')
  },
)

function handleBeforeSiteSwitch(): void {
  loadGeneration += 1
  page.value = null
  initialLoading.value = false
  refreshing.value = false
  pageDirty.value = false
  pendingRefreshReason.value = ''
  lastLoadedAt.value = 0
  filters.station = ''
  filters.page = 1
  savedTableScroll.top = 0
  savedTableScroll.left = 0
}

onActivated(() => {
  pageActive.value = true
  if (!pageMounted) return
  void restoreTableScroll()
  if (initialLoading.value) return
  if (!page.value) {
    void loadRows()
    return
  }
  if (pageDirty.value || Date.now() - lastLoadedAt.value > BUSINESS_PAGE_STALE_MS) {
    void loadRows()
  }
})

onDeactivated(() => {
  pageActive.value = false
  saveTableScroll()
})

onMounted(() => {
  pageMounted = true
  window.addEventListener(BEFORE_SITE_SWITCH_EVENT, handleBeforeSiteSwitch)
  void Promise.all([
    loadRows(),
    taskStore.refresh().then(() => {
      currentTaskId.value = taskStore.tasks.find(
        (item) => businessTaskTypes.has(item.type) && activeStates.has(item.status),
      )?.id || ''
      for (const item of taskStore.tasks) {
        if (businessProjectionTaskTypes.has(item.type) && !activeStates.has(item.status)) {
          terminalTaskRefreshes.add(item.id)
        }
      }
      taskObservationReady = true
    }),
  ])
})

onBeforeUnmount(() => {
  window.removeEventListener(BEFORE_SITE_SWITCH_EVENT, handleBeforeSiteSwitch)
  loadGeneration += 1
})
</script>

<template>
  <section class="trackside-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · TRACKSIDE AP</p><h1>轨旁 AP 业务</h1><p>交换机侧沿用设备模块门限，AP 侧业务光衰按固定业务门限投影。</p></div>
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
          :disabled="updateTaskRunning || exportTaskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_export') || !isFeatureEnabled('web.rail_task_control')"
          @click="exportBusiness"
        >导出表格</el-button>
      </div>
    </header>
    <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="true" @close="loadError = ''" />
    <el-alert
      v-if="page?.partial_data"
      title="部分数据不可用，已展示成功构建的交换机/AP 端口行。"
      type="warning"
      show-icon
      :closable="false"
      class="source-warning"
    >
      <details v-if="page.unavailable_sources?.length">
        <summary>查看不可用来源</summary>
        <span v-for="issue in page.unavailable_sources" :key="`${issue.source}:${issue.device_id || ''}`">
          {{ issue.label }}：{{ issue.code }}<template v-if="issue.device_id">（设备 {{ issue.device_id }}）</template>
        </span>
      </details>
    </el-alert>
    <el-alert v-if="actionError" :title="actionError" type="error" show-icon closable @close="actionError = ''" />
    <el-alert
      v-if="page?.runtime_snapshot?.snapshot_status === 'lldp_stale'"
      :title="`FIT-AP：${page.runtime_snapshot.fit_ap_collected_at || '未知'}；交换机 LLDP：${page.runtime_snapshot.switch_lldp_collected_at || '未知'}。LLDP 快照较旧，站点关联结果可能暂时不完整。`"
      type="warning"
      show-icon
      :closable="false"
    />
    <div v-if="page" class="scope-summary">
      <strong>统计范围：{{ page.scope_description || '当前项目 · 当前工作范围轨旁 AP' }}</strong>
      <span>纳入站点 {{ page.scope_station_count || 0 }}</span>
      <span>基础 AP 资料 {{ page.scope_ap_reference_count ?? page.scope_device_count ?? 0 }}</span>
      <span>排除设备 {{ page.excluded_device_count || 0 }}</span>
      <el-button v-if="lldpPendingCount" link type="warning" @click="unmatchedVisible = true">等待 LLDP 同步 {{ lldpPendingCount }}</el-button>
      <el-button v-if="lldpConflictCount" link type="danger" @click="unmatchedVisible = true">当前 LLDP 冲突 {{ lldpConflictCount }}</el-button>
      <el-button v-if="planningMissingCount" link type="warning" @click="unmatchedVisible = true">基础资料待补充 {{ planningMissingCount }}</el-button>
      <el-button v-if="otherUnmatchedCount" link type="warning" @click="unmatchedVisible = true">其他待关联 {{ otherUnmatchedCount }}</el-button>
      <el-button v-if="page.excluded_device_count" link type="warning" @click="excludedVisible = true">查看排除项</el-button>
    </div>
    <div class="summary-grid">
      <article><span>站点交换机</span><strong>{{ metricValue(page?.device_count, ['switch_devices']) }}</strong></article><article><span>候选 AP 端口</span><strong>{{ metricValue(page?.candidate_interface_count, ['switch_devices', 'interfaces', 'planning']) }}</strong></article><article><span>AC AP 资源</span><strong>{{ metricValue(page?.fit_ap_resource_count, ['fit_ap_resources']) }}</strong></article><article><span>{{ unmatchedLabel }}</span><strong>{{ metricValue(page?.fit_ap_unmatched_online_count, ['fit_ap_resources']) }}</strong></article><article><span>业务光衰异常</span><strong>{{ metricValue(page?.optical_abnormal_count, ['interfaces', 'switch_optical', 'fit_ap_optical']) }}</strong></article>
      <template v-if="page?.runtime_snapshot">
        <article><span>FIT-AP 总数</span><strong>{{ metricValue(page?.fit_ap_resource_total_count ?? page?.fit_ap_resource_count, ['fit_ap_resources']) }}</strong></article><article><span>实际在线</span><strong>{{ metricValue(page?.fit_ap_online_total_count ?? ((page?.fit_ap_matched_online_count || 0) + (page?.fit_ap_unmatched_online_count || 0)), ['fit_ap_resources']) }}</strong></article><article><span>实际离线</span><strong>{{ metricValue(page?.fit_ap_offline_total_count, ['fit_ap_resources']) }}</strong></article><article><span>状态未知</span><strong>{{ metricValue(page?.fit_ap_unknown_total_count, ['fit_ap_resources']) }}</strong></article><article><span>等待 LLDP 同步</span><strong>{{ metricValue(lldpPendingCount, ['fit_ap_resources']) }}</strong></article><article><span>当前 LLDP 冲突</span><strong>{{ metricValue(lldpConflictCount, ['fit_ap_resources']) }}</strong></article><article><span>真实资料缺失</span><strong>{{ metricValue(planningMissingCount, ['fit_ap_resources']) }}</strong></article>
      </template>
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
        <el-checkbox v-model="filters.optical_anomaly_only">仅业务光衰异常</el-checkbox>
        <el-button type="primary" :loading="refreshing" :disabled="initialLoading" @click="loadRows(true)">查询</el-button>
        <span v-if="refreshing" class="refresh-indicator">正在刷新，当前数据保持显示</span>
        <span class="work-scope-filter-hint">设备管理与 AC 生成业务行；基础资料仅补充站点和工程属性</span>
      </div>
      <div ref="businessTableHost" class="business-table-host">
        <NcDataTable
          v-loading="initialLoading"
          table-id="trackside-ap-business"
          route-key="/rail-transit/trackside-ap-business"
          :data="page?.items || []"
          :columns="businessColumns"
          :row-key="businessRowKey"
          :context-menu-items="businessContextMenuItems"
          class="business-table"
          height="100%"
          :empty-text="emptyReasonLabel(page?.empty_reason || '')"
        >
          <template #cell-switch_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_rx_power) }}</span></template>
          <template #cell-switch_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_tx_power) }}</span></template>
          <template #cell-switch_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.switch_optical_status).tagType" :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ tracksideOpticalPresentation(row.switch_optical_status).label }}</el-tag></template>
          <template #cell-ap_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_rx_power) }}</span></template>
          <template #cell-ap_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_device_optical_status || row.ap_optical_status).className">{{ displayTracksideValue(row.ap_tx_power) }}</span></template>
          <template #cell-ap_device_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.ap_device_optical_status || row.ap_optical_status).tagType" :class="tracksideOpticalPresentation(row.ap_device_optical_status || row.ap_optical_status).className">{{ tracksideOpticalPresentation(row.ap_device_optical_status || row.ap_optical_status).label }}</el-tag></template>
          <template #cell-ap_optical_status="{ row }"><el-tooltip :content="row.ap_business_reason || '无业务判定说明'"><el-tag :type="tracksideOpticalPresentation(row.ap_business_optical_status || row.ap_optical_status).tagType" :class="tracksideOpticalPresentation(row.ap_business_optical_status || row.ap_optical_status).className">{{ tracksideOpticalPresentation(row.ap_business_optical_status || row.ap_optical_status).label }}</el-tag></el-tooltip></template>
          <template #cell-optical_severity="{ row }"><el-tag :type="tracksideOpticalPresentation(row.optical_severity).tagType" :class="tracksideOpticalPresentation(row.optical_severity).className">{{ tracksideOpticalPresentation(row.optical_severity).label }}</el-tag></template>
          <template #cell-actions="{ row }"><el-button link type="primary" :disabled="updateTaskRunning || !row.site || !updateFeatureEnabled" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :title="hasApIdentity(row) ? '' : '缺少 AP 身份，无法定向更新'" :disabled="updateTaskRunning || !hasApIdentity(row) || !updateFeatureEnabled" @click="updateAp(row)">更新 AP</el-button></template>
        </NcDataTable>
      </div>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="page?.page || filters.page" :page-size="filters.page_size" :page-sizes="[20, 50, 100, 200]" layout="sizes, prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" @size-change="(value: number) => { filters.page_size = value; filters.page = 1; loadRows() }" /></div>
    </div>
    <el-dialog v-model="terminalVisible" :title="t('ac.terminal.select', '选择外部终端')" width="420px">
      <el-select v-model="terminalType" style="width: 100%"><el-option v-for="option in terminalOptions" :key="option.terminal_type" :label="option.label" :value="option.terminal_type" /></el-select>
      <template #footer><el-button @click="terminalVisible = false">{{ t('common.cancel', '取消') }}</el-button><el-button type="primary" :loading="terminalLoading" @click="launchSelectedFitApTerminal">{{ t('ac.terminal.open', '打开终端') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="excludedVisible" title="当前统计范围排除项" width="min(1040px, 94vw)">
      <NcDataTable
        table-id="trackside-ap-business-scope-excluded"
        route-key="/rail-transit/trackside-ap-business"
        :data="page?.excluded_items || []"
        :columns="excludedColumns"
        :row-key="excludedRowKey"
        height="460"
        empty-text="没有排除项"
      />
    </el-dialog>
    <el-dialog v-model="unmatchedVisible" :title="`${unmatchedLabel}的在线 AP`" width="min(1280px, 96vw)">
      <NcDataTable
        table-id="trackside-ap-business-unmatched-online"
        route-key="/rail-transit/trackside-ap-business"
        :data="page?.unmatched_online_items || []"
        :columns="unmatchedColumns"
        :row-key="onlineResourceRowKey"
        height="460"
        empty-text="没有待补充基础资料的在线 AP"
      />
    </el-dialog>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;height:100%;min-height:0;min-width:0;flex-direction:column;gap:16px}.page-heading,.actions,.toolbar,.pagination,.scope-summary{display:flex;align-items:center;gap:12px}.page-heading,.pagination{flex:none;justify-content:space-between}.page-heading h1{margin:2px 0 6px}.page-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:0}.actions,.toolbar,.scope-summary{flex-wrap:wrap}.scope-summary{color:var(--el-text-color-secondary)}.scope-summary strong{color:var(--el-text-color-primary)}.summary-grid{display:grid;flex:none;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:8px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{display:flex;min-height:0;min-width:0;flex:1;flex-direction:column;padding:14px 16px;overflow:hidden}.business-table-host{min-height:0;min-width:0;flex:1}.toolbar{flex:none;margin-bottom:12px}.toolbar .el-input{width:230px}.station-select{width:260px}.refresh-indicator{color:var(--el-color-primary);font-size:13px}.work-scope-filter-hint{color:var(--el-text-color-secondary);font-size:12px}.pagination{flex-wrap:wrap;padding-top:12px}.optical-normal{color:var(--el-color-success)}.optical-notice,.optical-warning{color:var(--el-color-warning)}.optical-alarm,.optical-link-abnormal,.optical-link-down,.optical-no-light,.optical-offline{color:var(--el-color-danger);font-weight:600}.optical-no-module,.optical-missing,.optical-skipped,.optical-not-collected,.optical-unknown{color:var(--el-text-color-secondary)}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
.source-warning details{display:grid;gap:4px;margin-top:6px}.source-warning summary{cursor:pointer}.source-warning details span{display:block}
</style>
