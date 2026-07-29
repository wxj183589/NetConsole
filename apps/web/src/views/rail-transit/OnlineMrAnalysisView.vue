<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { Delete, Download, Files, FolderOpened, Refresh, Search, Tickets } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { ApiRequestError } from '../../api/client'
import {
  getOnlineMrBusinessSummary,
  getOnlineMrRawTail,
  getOnlineMrSession,
  listOnlineMrRawFiles,
  listRecentOnlineMrSessions,
  queryOnlineMrBusinessTable,
  queryOnlineMrMetrics,
  queryOnlineMrSwitchRssiWindows,
} from '../../api/onlineMr'
import { deleteOnlineMrSession, exportOnlineMrReport, getRailTransitTask, parseOnlineMrSession, recoverRailTransitTasks } from '../../api/railTransitWeb'
import OnlineMrAnalysisChart from '../../components/online-mr-analysis/OnlineMrAnalysisChart.vue'
import { useConfirm } from '../../components/feedback/useConfirm'
import { useAvailablePanelHeight } from '../../composables/useAvailablePanelHeight'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import type {
  OnlineMrBusinessSummary,
  OnlineMrBusinessRow,
  OnlineMrBusinessTable,
  OnlineMrMetricPoint,
  OnlineMrMetricSeries,
  OnlineMrRawFile,
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
  OnlineMrSwitchRssiSource,
  OnlineMrSwitchRssiWindow,
} from '../../types/onlineMr'
import type { RailTransitTask } from '../../types/railTransitWeb'

const route = useRoute()
const router = useRouter()
const { confirm } = useConfirm()
const userSelectedExport = useUserSelectedExport()

type BusinessRow = OnlineMrBusinessRow
type RequestContext = { sessionId: string; generation: number; signal: AbortSignal }
type ChartDefinition = { key: string; title: string; unit: string; metric?: readonly string[]; switchSource?: OnlineMrSwitchRssiSource }

const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const chartDefinitions: readonly ChartDefinition[] = [
  { key: 'rssi', title: '主链路 RSSI', metric: ['rssi'], unit: 'dBm' },
  { key: 'ping-loss', title: 'Ping 丢包率', metric: ['ping_loss'], unit: '%' },
  { key: 'ping-rtt', title: 'Ping 延迟（fping RTT）', metric: ['ping_rtt'], unit: 'ms' },
  { key: 'interface', title: '接口速率', metric: ['interface_in_pps', 'interface_out_pps'], unit: 'pps' },
  { key: 'traffic', title: '业务打流', metric: ['iperf_bitrate'], unit: 'Mbps' },
  { key: 'busy', title: '信道繁忙度（Channel Busy）', metric: ['ctl_busy', 'tx_busy', 'rx_busy'], unit: '%' },
  { key: 'switch-rssi', title: '切换历史 RSSI 快照', switchSource: 'history', unit: 'dBm' },
  { key: 'switch-log-rssi', title: '实时切换日志 RSSI 快照', switchSource: 'realtime', unit: 'dBm' },
]

const businessTabToTable: Record<string, OnlineMrBusinessTable> = {
  'mesh-link': 'main_link',
  'mesh-detail': 'link_detail',
  'channel-busy': 'channel_busy',
  'switch-history': 'switch_history',
  'active-switch': 'switch_realtime',
  'interface-rate': 'interface_rate',
  fping: 'fping_1s',
  iperf: 'iperf',
  diagnosis: 'diagnostics',
}

const businessTableLabels: Record<OnlineMrBusinessTable, string> = {
  main_link: '主链路信息',
  link_detail: '链路明细',
  channel_busy: '信道繁忙度',
  switch_history: '主链路切换历史',
  switch_realtime: '主链路切换日志',
  interface_rate: '接口速率',
  fping_1s: 'fping 1s 聚合',
  iperf: '打流测试',
  diagnostics: '诊断',
}

const sessions = ref<OnlineMrSessionSummary[]>([])
const sessionId = ref('')
const detail = ref<OnlineMrSessionDetail | null>(null)
const businessSummary = ref<OnlineMrBusinessSummary | null>(null)
const activeTab = ref('session-history')
const chartTab = ref('rssi')
const metrics = ref<Record<string, OnlineMrMetricSeries[]>>({})
const metricOffsets = ref<Record<string, number>>({})
const metricHasMore = ref<Record<string, boolean>>({})
const switchWindows = ref<Record<OnlineMrSwitchRssiSource, OnlineMrSwitchRssiWindow[]>>({ history: [], realtime: [] })
const switchOffsets = ref<Record<OnlineMrSwitchRssiSource, number>>({ history: 0, realtime: 0 })
const switchHasMore = ref<Record<OnlineMrSwitchRssiSource, boolean>>({ history: false, realtime: false })
const businessRows = ref<Record<OnlineMrBusinessTable, BusinessRow[]>>({
  main_link: [],
  link_detail: [],
  channel_busy: [],
  switch_history: [],
  switch_realtime: [],
  interface_rate: [],
  fping_1s: [],
  iperf: [],
  diagnostics: [],
})
const businessOffsets = ref<Record<OnlineMrBusinessTable, number>>({
  main_link: 0,
  link_detail: 0,
  channel_busy: 0,
  switch_history: 0,
  switch_realtime: 0,
  interface_rate: 0,
  fping_1s: 0,
  iperf: 0,
  diagnostics: 0,
})
const businessHasMore = ref<Record<OnlineMrBusinessTable, boolean>>({
  main_link: false,
  link_detail: false,
  channel_busy: false,
  switch_history: false,
  switch_realtime: false,
  interface_rate: false,
  fping_1s: false,
  iperf: false,
  diagnostics: false,
})
const rawFiles = ref<OnlineMrRawFile[]>([])
const rawTail = ref<string[]>([])
const rawName = ref('')
const task = ref<RailTransitTask | null>(null)
const loading = ref(false)
const parseSubmitting = ref(false)
const reportSubmitting = ref(false)
const deleting = ref(false)
const openingLocation = ref(false)
const error = ref('')
const analysisError = ref('')
const startTime = ref('')
const endTime = ref('')
const downsample = ref<'NONE' | 'BUCKET_AVG' | 'MIN_MAX' | 'LATEST_PER_BUCKET'>('LATEST_PER_BUCKET')
const bucketSeconds = ref(1)
const analysisTabsHost = ref<HTMLElement | null>(null)
const pendingDeleteTarget = ref<{ sessionId: string; index: number } | null>(null)
const panel = useAvailablePanelHeight(analysisTabsHost, { minHeight: 420, bottomGap: 40 })

const metricLimit = 1_000
const businessLimit = 500
const switchLimit = 200
const timelineLimit = 200
let pollTimer: number | undefined
let requestGeneration = 0
let requestController: AbortController | null = null

const mainLinkRows = computed(() => businessRows.value.main_link)
const linkDetailRows = computed(() => businessRows.value.link_detail)
const channelBusyRows = computed(() => businessRows.value.channel_busy)
const switchHistoryRows = computed(() => businessRows.value.switch_history)
const switchRealtimeRows = computed(() => businessRows.value.switch_realtime)
const interfaceRows = computed(() => businessRows.value.interface_rate)
const fpingRows = computed(() => businessRows.value.fping_1s)
const iperfRows = computed(() => businessRows.value.iperf)
const diagnosisRows = computed(() => businessRows.value.diagnostics)
const currentBusinessTable = computed<OnlineMrBusinessTable | null>(() => businessTabToTable[activeTab.value] || null)
const currentBusinessRows = computed(() => currentBusinessTable.value ? businessRows.value[currentBusinessTable.value] : [])
const currentBusinessHasMore = computed(() => currentBusinessTable.value ? businessHasMore.value[currentBusinessTable.value] : false)
const selectedChart = computed(() => chartDefinitions.find((item) => item.key === chartTab.value) || chartDefinitions[0])
const chartSeries = computed(() => selectedChart.value.switchSource ? switchRssiSeries(selectedChart.value.switchSource) : metrics.value[selectedChart.value.key] || [])
const chartHasMore = computed(() => selectedChart.value.switchSource ? switchHasMore.value[selectedChart.value.switchSource] : Boolean(metricHasMore.value[selectedChart.value.key]))
const parsedStatus = computed(() => detail.value?.database_summary.status || 'missing')
const parsedReadable = computed(() => ['ready', 'legacy', 'stale'].includes(parsedStatus.value) && detail.value?.database_summary.compatible !== false)
const parsedReady = computed(() => parsedStatus.value === 'ready')
const parsedStatusLabel = computed(() => ({ ready: '解析结果可用', missing: '尚未解析', legacy: '旧版解析结果', stale: '解析结果已过期', unreadable: '解析结果不可读', parsing: '正在解析' }[parsedStatus.value] || parsedStatus.value))
const parsedAlertType = computed(() => parsedReady.value ? 'success' : parsedStatus.value === 'unreadable' ? 'error' : 'warning')
const parsedMessage = computed(() => detail.value?.database_summary.message || '当前会话尚未生成解析结果。')
const canParse = computed(() => Boolean(detail.value?.has_raw_data && isFeatureEnabled('web.online_mr_parse')))
const reportDisabled = computed(() => !parsedReady.value || !isFeatureEnabled('web.online_mr_report_export'))
const taskActive = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const parseBusy = computed(() => parseSubmitting.value || (taskActive.value && task.value?.action === 'online_mr_parse'))
const reportBusy = computed(() => reportSubmitting.value || (taskActive.value && task.value?.action === 'online_mr_report'))
const deleteBusy = computed(() => deleting.value || (taskActive.value && task.value?.action === 'online_mr_session_delete'))
const sessionResourceBusy = computed(() => parseBusy.value || reportBusy.value || deleteBusy.value)
const tableHeight = computed(() => Math.max(360, panel.height.value - 58))
const desktopLocationAvailable = computed(() => Boolean(
  window.netconsoleDesktop?.openOnlineMrSessionLocation
  && isFeatureEnabled('desktop.native_bridge')
  && isFeatureEnabled('web.online_mr_session_open_location'),
))
const sessionActionsDisabled = computed(() => !detail.value || deleteBusy.value)
const openLocationTitle = computed(() => desktopLocationAvailable.value
  ? ''
  : '该功能仅在 NetConsole Electron 桌面端可用。')
const businessSummaryCards = computed(() => {
  const summary = businessSummary.value
  if (!summary) return []
  return [
    { label: '采样点', value: display(summary.sample_count) },
    { label: 'ACTIVE / STANDBY', value: `${display(summary.active_count)} / ${display(summary.standby_count)}` },
    { label: '切换次数', value: display(summary.switch_count) },
    { label: 'fping / 打流', value: `${display(summary.fping_point_count)} / ${display(summary.iperf_point_count)}` },
    { label: '时间同步', value: `${summary.time_sync_status}${summary.time_sync_avg_offset_ms == null ? '' : ` · ${formatNumber(summary.time_sync_avg_offset_ms, 2)} ms`}` },
    { label: '估算间隔', value: summary.estimated_interval_seconds == null ? '无数据' : `${formatNumber(summary.estimated_interval_seconds, 2)} s` },
    { label: '当前链路', value: summary.current_link_state || '无数据' },
    { label: 'Peer / AP', value: `${display(summary.current_peer_name)} / ${display(summary.current_ap_mac)}` },
    { label: 'RSSI', value: summary.current_rssi == null ? '无数据' : `${formatNumber(summary.current_rssi, 0)} dBm` },
    { label: '站点 / 区间', value: `${display(summary.current_station)} / ${display(summary.current_section)}` },
    { label: '当前时段', value: summary.current_segment_duration_seconds == null ? '无数据' : `${formatNumber(summary.current_segment_duration_seconds, 2)} s` },
    { label: '最新采样', value: summary.last_sample_time || '无数据' },
  ]
})

const sessionColumns: NcTableColumn<OnlineMrSessionSummary>[] = [
  { key: 'session_id', label: '会话', valueType: 'name', widthMode: 'content', minWidth: 180 },
  { key: 'device_name', label: 'MR', valueType: 'name' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'started_at', label: '开始时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'stopped_at', label: '结束时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'duration_minutes', label: '时长(分钟)', valueType: 'number', displayValue: (row) => display(row.duration_minutes) },
  { key: 'data_integrity', label: '数据状态', valueType: 'status', displayValue: (row) => row.finalization_complete == null ? '无数据' : row.finalization_complete ? '完整' : '部分' },
]
const mainLinkColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'radio', label: '射频ID', valueType: 'number' },
  { key: 'link_state', label: '链路状态', valueType: 'status' },
  { key: 'peer_name', label: '对端名称', valueType: 'name', widthMode: 'content', minWidth: 180 },
  { key: 'peer_mac', label: '对端MAC', valueType: 'mac' },
  { key: 'mr_rssi', label: 'MR端RSSI', valueType: 'number' },
  { key: 'bssid', label: 'BSSID', valueType: 'mac' },
  { key: 'belong_station', label: '归属站点', valueType: 'name' },
  { key: 'belong_section', label: '归属区间', valueType: 'name' },
  { key: 'online_time', label: '在线时长', valueType: 'duration' },
]
const linkDetailColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'sample_time', label: '采样时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'radio', label: 'Radio', valueType: 'number' },
  { key: 'link_state', label: '状态', valueType: 'status' },
  { key: 'peer_mac', label: 'PeerMac', valueType: 'mac' },
  { key: 'peer_name', label: '当前 PEER AP 名称', valueType: 'name', widthMode: 'content', minWidth: 180 },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac' },
  { key: 'belong_station', label: '归属站点', valueType: 'name' },
  { key: 'belong_section', label: '归属区间', valueType: 'name' },
  { key: 'mr_rx_signal', label: 'MR 接收信号', valueType: 'number' },
  { key: 'mesh_interface', label: 'Mesh接口', valueType: 'name' },
  { key: 'online_time', label: 'Online Time', valueType: 'duration' },
]
const channelBusyColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'radio', label: '射频ID', valueType: 'number' },
  { key: 'ctl_channel', label: '控制信道', valueType: 'number' },
  { key: 'bandwidth', label: '频宽', valueType: 'number' },
  { key: 'record_interval', label: '记录间隔', valueType: 'duration' },
  { key: 'ctl_busy', label: '控制信道繁忙度', valueType: 'percentage' },
  { key: 'tx_busy', label: '发送繁忙度', valueType: 'percentage' },
  { key: 'rx_busy', label: '接收繁忙度', valueType: 'percentage' },
]
const switchHistoryColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'device_switch_time', label: '设备切换时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'radio', label: '射频ID', valueType: 'number' },
  { key: 'from_peer_name', label: '切出Peer名称', valueType: 'name', widthMode: 'content', minWidth: 160 },
  { key: 'to_peer_name', label: '切入Peer名称', valueType: 'name', widthMode: 'content', minWidth: 160 },
  { key: 'from_rssi', label: '切出 RSSI', valueType: 'number' },
  { key: 'to_rssi', label: '切入 RSSI', valueType: 'number' },
  { key: 'from_station', label: '切出 归属站点', valueType: 'name' },
  { key: 'to_station', label: '切入 归属站点', valueType: 'name' },
  { key: 'reason_text', label: '切换原因', valueType: 'description', align: 'left', alignmentReason: 'description' },
  { key: 'active_duration', label: 'Active持续时间', valueType: 'duration' },
]
const switchRealtimeColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'device_name', label: '设备名称', valueType: 'name' },
  { key: 'radio', label: 'Radio', valueType: 'number' },
  { key: 'from_peer_name', label: '切出AP名称', valueType: 'name', widthMode: 'content', minWidth: 160 },
  { key: 'from_peer_mac', label: '切出AP MAC', valueType: 'mac' },
  { key: 'from_rssi', label: '切出RSSI', valueType: 'number' },
  { key: 'from_station', label: '切出归属站点', valueType: 'name' },
  { key: 'from_section', label: '切出归属区间', valueType: 'name' },
  { key: 'to_peer_name', label: '切入AP名称', valueType: 'name', widthMode: 'content', minWidth: 160 },
  { key: 'to_peer_mac', label: '切入AP MAC', valueType: 'mac' },
  { key: 'to_rssi', label: '切入RSSI', valueType: 'number' },
  { key: 'to_station', label: '切入归属站点', valueType: 'name' },
  { key: 'to_section', label: '切入归属区间', valueType: 'name' },
  { key: 'peer_quantity', label: 'peer数量', valueType: 'number' },
  { key: 'link_quantity', label: 'Link数量', valueType: 'number' },
  { key: 'reason_code', label: '切换原因码', valueType: 'number' },
  { key: 'reason_text', label: '切换原因', valueType: 'description', align: 'left', alignmentReason: 'description' },
]
const interfaceColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'interface', label: '接口', valueType: 'name' },
  { key: 'direction', label: '方向', valueType: 'status' },
  { key: 'total_pps', label: '总 PPS', valueType: 'rate' },
  { key: 'broadcast_pps', label: '广播 PPS', valueType: 'rate' },
  { key: 'multicast_pps', label: '组播 PPS', valueType: 'rate' },
  { key: 'usage_percent', label: '利用率', valueType: 'percentage' },
]
const fpingColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'index', label: '序号', type: 'index', valueType: 'index', width: 70, fixed: 'left' },
  { key: 'time', label: '时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'device_time', label: '设备对齐时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'local_time', label: '本地时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'target_ip', label: '目标IP', valueType: 'ip' },
  { key: 'sent', label: '发送数', valueType: 'number' },
  { key: 'received', label: '接收数', valueType: 'number' },
  { key: 'loss_count', label: '丢失数', valueType: 'number' },
  { key: 'loss_rate', label: '丢包率%', valueType: 'percentage' },
  { key: 'avg_rtt', label: '平均延迟(ms)', valueType: 'number' },
  { key: 'min_rtt', label: '最小延迟(ms)', valueType: 'number' },
  { key: 'max_rtt', label: '最大延迟(ms)', valueType: 'number' },
  { key: 'jitter_ms', label: '时延抖动(ms)', valueType: 'number' },
  { key: 'status', label: '状态', valueType: 'status' },
]
const iperfColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'local_time', label: '本地时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'runtime', label: '运行时间', valueType: 'duration' },
  { key: 'transfer', label: '传输总量', valueType: 'description' },
  { key: 'bitrate', label: '带宽', valueType: 'rate' },
  { key: 'jitter_ms', label: '抖动', valueType: 'number' },
  { key: 'lost_packets', label: '丢包数', valueType: 'number' },
  { key: 'total_packets', label: '总数据包数', valueType: 'number' },
  { key: 'loss_percent', label: '丢包率', valueType: 'percentage' },
]
const diagnosisColumns: NcTableColumn<BusinessRow>[] = [
  { key: 'issue_type', label: '问题类型', valueType: 'status' },
  { key: 'severity', label: '严重级别', valueType: 'status' },
  { key: 'start_time', label: '开始时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'end_time', label: '结束时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'peer_name', label: '影响 AP / Peer', valueType: 'name' },
  { key: 'station', label: '站点', valueType: 'name' },
  { key: 'section', label: '区间', valueType: 'name' },
  { key: 'description', label: '判断依据', valueType: 'description', align: 'left', alignmentReason: 'description' },
  { key: 'recommendation', label: '建议处理', valueType: 'description', align: 'left', alignmentReason: 'description' },
]
const rawColumns: NcTableColumn<OnlineMrRawFile>[] = [
  { key: 'name', label: '文件', valueType: 'name', widthMode: 'content', minWidth: 240 },
  { key: 'relative_name', label: '相对路径', valueType: 'description', align: 'left', alignmentReason: 'path' },
  { key: 'size_bytes', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '修改时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
]

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}
function display(value: unknown): string {
  return value === null || value === undefined || value === '' ? '无数据' : String(value)
}
function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}
function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '无数据'
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(digits)
  return formatted.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
}
function sampleKey(row: BusinessRow, index: number): string {
  return String(row.sample_time || row.start_time || row.event_time || row.device_time || row.collector_time || row.time || index)
}
function isActiveRow(row: BusinessRow): boolean {
  return String(row.link_state || row.event_type || '').toUpperCase().startsWith('ACTIVE')
}
function businessRowClass(rows: readonly BusinessRow[], rowIndex: number, activeField?: string): string {
  const row = rows[rowIndex]
  if (!row) return ''
  let groupIndex = 0
  let previousKey = ''
  for (let index = 0; index <= rowIndex; index += 1) {
    const currentKey = sampleKey(rows[index], index)
    if (index > 0 && currentKey !== previousKey) groupIndex += 1
    previousKey = currentKey
  }
  const classes = [groupIndex % 2 === 0 ? 'online-mr-row--group-a' : 'online-mr-row--group-b']
  if (activeField && String(row[activeField] || '').toUpperCase().startsWith('ACTIVE')) classes.push('online-mr-row--active')
  return classes.join(' ')
}
function businessTableLabel(table: OnlineMrBusinessTable): string {
  return businessTableLabels[table]
}
function businessSummaryValue(summary: OnlineMrBusinessSummary | null, key: keyof OnlineMrBusinessSummary): unknown {
  return summary ? summary[key] : null
}
function metricSummary(points: OnlineMrMetricPoint[]) {
  const values = points.flatMap((point) => point.value == null ? [] : [point.value])
  return { count: points.length, minimum: values.length ? Math.min(...values) : null, maximum: values.length ? Math.max(...values) : null, average: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null }
}
function appendMetricPage(current: OnlineMrMetricSeries[], incoming: OnlineMrMetricSeries[]): OnlineMrMetricSeries[] {
  const merged = new Map(current.map((series) => [`${series.metric_type}\0${series.series_key}`, { ...series, points: [...series.points] }]))
  for (const series of incoming) {
    const key = `${series.metric_type}\0${series.series_key}`
    const existing = merged.get(key)
    if (existing) {
      existing.points.push(...series.points)
      existing.summary = metricSummary(existing.points)
    } else {
      merged.set(key, { ...series, points: [...series.points] })
    }
  }
  return [...merged.values()]
}
function switchRssiSeries(source: OnlineMrSwitchRssiSource): OnlineMrMetricSeries[] {
  const points = (role: 'old' | 'new'): OnlineMrMetricPoint[] => switchWindows.value[source].map((event) => ({
    timestamp: event.event_time,
    value: role === 'old' ? event.old_rssi_dbm : event.new_rssi_dbm,
    text_value: role === 'old' ? event.old_peer_name : event.new_peer_name,
    dimensions: {
      role,
      radio: event.radio,
      peer_name: role === 'old' ? event.old_peer_name : event.new_peer_name,
      peer_mac: role === 'old' ? event.old_peer_mac : event.new_peer_mac,
      reason: event.reason,
    },
  }))
  return (['old', 'new'] as const).map((role) => {
    const rows = points(role)
    return { metric_type: `switch_${source}_rssi`, series_key: role === 'old' ? '切出链路' : '切入链路', unit: 'dBm', points: rows, summary: metricSummary(rows) }
  })
}
function chartEvents(): Array<{ time: string; label: string }> {
  const source = selectedChart.value.switchSource
  return source ? switchWindows.value[source].filter((event) => event.event_time).map((event) => ({ time: event.event_time!, label: event.reason || '主链路切换' })) : []
}
function rememberTask(value: RailTransitTask | null): void {
  task.value = value
  if (value) localStorage.setItem('netconsole.online-mr-analysis.last-task', value.task_id)
  else localStorage.removeItem('netconsole.online-mr-analysis.last-task')
}
function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}
function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try {
      const updated = await getRailTransitTask(task.value!.task_id)
      rememberTask(updated)
      if (terminalStates.has(updated.status)) {
        if (updated.action === 'online_mr_parse') {
          if (updated.status === 'COMPLETED') await loadAnalysis()
          task.value = updated
        } else if (updated.action === 'online_mr_report' && updated.status === 'FAILED') {
          ElMessage.error(updated.error_message || updated.message || '分析报告生成失败')
        } else if (updated.action === 'online_mr_session_delete') {
          await finishDeleteTask(updated)
        }
        return
      }
      poll()
    } catch (cause) {
      error.value = message(cause, '任务状态读取失败')
    }
  }, 1000)
}
function emptyBusinessState(): Record<OnlineMrBusinessTable, BusinessRow[]> {
  return {
    main_link: [],
    link_detail: [],
    channel_busy: [],
    switch_history: [],
    switch_realtime: [],
    interface_rate: [],
    fping_1s: [],
    iperf: [],
    diagnostics: [],
  }
}
function emptyOffsetState(): Record<OnlineMrBusinessTable, number> {
  return { main_link: 0, link_detail: 0, channel_busy: 0, switch_history: 0, switch_realtime: 0, interface_rate: 0, fping_1s: 0, iperf: 0, diagnostics: 0 }
}
function emptyMoreState(): Record<OnlineMrBusinessTable, boolean> {
  return { main_link: false, link_detail: false, channel_busy: false, switch_history: false, switch_realtime: false, interface_rate: false, fping_1s: false, iperf: false, diagnostics: false }
}
function clearAnalysisData(): void {
  businessSummary.value = null
  businessRows.value = emptyBusinessState()
  businessOffsets.value = emptyOffsetState()
  businessHasMore.value = emptyMoreState()
  metrics.value = {}
  metricOffsets.value = {}
  metricHasMore.value = {}
  switchWindows.value = { history: [], realtime: [] }
  switchOffsets.value = { history: 0, realtime: 0 }
  switchHasMore.value = { history: false, realtime: false }
  analysisError.value = ''
}
function clearSessionData(): void {
  clearAnalysisData()
  rawFiles.value = []
  rawTail.value = []
  rawName.value = ''
}
function nextRequestContext(): RequestContext {
  requestController?.abort()
  requestController = new AbortController()
  requestGeneration += 1
  return { sessionId: sessionId.value, generation: requestGeneration, signal: requestController.signal }
}
function currentRequestContext(): RequestContext {
  if (!requestController) requestController = new AbortController()
  return { sessionId: sessionId.value, generation: requestGeneration, signal: requestController.signal }
}
function isCurrent(context: RequestContext): boolean {
  return context.generation === requestGeneration && context.sessionId === sessionId.value && !context.signal.aborted
}
function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}

async function loadSessions(options: { preferredIndex?: number } = {}): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    sessions.value = await listRecentOnlineMrSessions(100)
    const requested = typeof route.query.session_id === 'string' ? route.query.session_id : ''
    const retained = sessions.value.find((item) => item.session_id === sessionId.value)?.session_id
    const requestedSession = sessions.value.find((item) => item.session_id === requested)?.session_id
    const preferred = options.preferredIndex == null
      ? ''
      : sessions.value[Math.min(options.preferredIndex, Math.max(0, sessions.value.length - 1))]?.session_id || ''
    sessionId.value = retained || preferred || requestedSession || sessions.value[0]?.session_id || ''
    if (sessionId.value) {
      await loadAnalysis()
    } else {
      detail.value = null
      clearSessionData()
    }
  } catch (cause) {
    error.value = message(cause, 'Online MR 会话列表加载失败')
  } finally {
    loading.value = false
  }
}
async function loadAnalysis(): Promise<void> {
  if (!sessionId.value) return
  const context = nextRequestContext()
  stopPolling()
  task.value = null
  detail.value = null
  clearSessionData()
  loading.value = true
  error.value = ''
  try {
    const nextDetail = await getOnlineMrSession(context.sessionId, context.signal)
    if (!isCurrent(context)) return
    detail.value = nextDetail
    await loadActiveTab(activeTab.value, context)
  } catch (cause) {
    if (!isAbort(cause) && isCurrent(context)) error.value = message(cause, 'Online MR 会话详情加载失败')
  } finally {
    if (isCurrent(context)) loading.value = false
  }
}
async function loadBusinessSummary(context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || businessSummary.value) return
  businessSummary.value = await getOnlineMrBusinessSummary(context.sessionId)
}
async function loadBusinessTable(table: OnlineMrBusinessTable, append = false, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || (!append && businessRows.value[table].length)) return
  const offset = append ? businessOffsets.value[table] : 0
  const page = await queryOnlineMrBusinessTable(context.sessionId, table, { startTime: startTime.value, endTime: endTime.value, limit: businessLimit, offset, signal: context.signal })
  if (!isCurrent(context)) return
  businessRows.value[table] = append ? [...businessRows.value[table], ...page.rows] : page.rows
  businessOffsets.value[table] = page.next_offset
  businessHasMore.value[table] = page.has_more
}
async function loadMetric(name: string, types: string[], append = false, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || (!append && metrics.value[name])) return
  const offset = append ? metricOffsets.value[name] || 0 : 0
  const page = await queryOnlineMrMetrics(context.sessionId, types, { startTime: startTime.value, endTime: endTime.value, limit: metricLimit, offset, downsample: downsample.value, bucketSeconds: bucketSeconds.value, signal: context.signal })
  if (!isCurrent(context)) return
  metrics.value[name] = append ? appendMetricPage(metrics.value[name] || [], page.series) : page.series
  metricOffsets.value[name] = page.next_offset
  metricHasMore.value[name] = page.has_more
}
async function loadSwitchWindows(source: OnlineMrSwitchRssiSource, append = false, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || (!append && switchWindows.value[source].length)) return
  const offset = append ? switchOffsets.value[source] : 0
  const page = await queryOnlineMrSwitchRssiWindows(context.sessionId, source, { startTime: startTime.value, endTime: endTime.value, limit: switchLimit, offset, signal: context.signal })
  if (!isCurrent(context)) return
  switchWindows.value[source] = append ? [...switchWindows.value[source], ...page.items] : page.items
  switchOffsets.value[source] = offset + page.limit
  switchHasMore.value[source] = page.has_more
}
async function loadRaw(context = currentRequestContext()): Promise<void> {
  if (!rawFiles.value.length) {
    const rows = await listOnlineMrRawFiles(context.sessionId, context.signal)
    if (isCurrent(context)) rawFiles.value = rows
  }
}
async function loadCollectorLog(context = currentRequestContext()): Promise<void> {
  const result = await getOnlineMrRawTail(context.sessionId, 'collector_output', 250, context.signal)
  if (isCurrent(context)) {
    rawName.value = 'collector_output'
    rawTail.value = result.lines
  }
}
async function loadActiveTab(tab: string, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context)) return
  const businessTable = businessTabToTable[tab]
  const rawTab = tab === 'session-history' || tab === 'raw' || tab === 'logs'
  if (!rawTab && !parsedReadable.value) {
    analysisError.value = parsedMessage.value
    return
  }
  analysisError.value = ''
  try {
    if (tab === 'mesh-link') await Promise.all([loadBusinessSummary(context), loadBusinessTable('main_link', false, context)])
    else if (businessTable) await loadBusinessTable(businessTable, false, context)
    else if (tab === 'charts') {
      if (selectedChart.value.switchSource) await loadSwitchWindows(selectedChart.value.switchSource, false, context)
      else await loadMetric(selectedChart.value.key, [...(selectedChart.value.metric || [])], false, context)
    } else if (tab === 'raw') await loadRaw(context)
    else if (tab === 'logs') await loadCollectorLog(context)
  } catch (cause) {
    if (!isAbort(cause) && isCurrent(context)) analysisError.value = cause instanceof ApiRequestError && cause.code ? `${cause.message}（${cause.code}）` : message(cause, '当前分析区域加载失败')
  }
}
async function openRaw(row: OnlineMrRawFile): Promise<void> {
  const context = currentRequestContext()
  rawName.value = row.name
  rawTail.value = []
  try {
    const result = await getOnlineMrRawTail(context.sessionId, row.name, 250, context.signal)
    if (isCurrent(context)) rawTail.value = result.lines
  } catch (cause) {
    if (!isAbort(cause) && isCurrent(context)) analysisError.value = message(cause, '原始日志读取失败')
  }
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}
function selectSession(row: OnlineMrSessionSummary): void {
  if (deleteBusy.value || row.session_id === sessionId.value) return
  sessionId.value = row.session_id
  void loadAnalysis()
}
async function openSessionLocation(): Promise<void> {
  const selected = detail.value
  if (!selected || deleteBusy.value) return
  const bridge = window.netconsoleDesktop?.openOnlineMrSessionLocation
  if (!bridge || !desktopLocationAvailable.value) {
    ElMessage.warning('该功能仅在 NetConsole Electron 桌面端可用。')
    return
  }
  openingLocation.value = true
  try {
    const result = await bridge(selected.session_id)
    if (!result.success) ElMessage.error(result.error || '打开会话位置失败')
  } catch (cause) {
    ElMessage.error(message(cause, '打开会话位置失败'))
  } finally {
    openingLocation.value = false
  }
}
async function startParse(forceReparse: boolean): Promise<void> {
  if (!detail.value || !canParse.value || sessionActionsDisabled.value || reportBusy.value || parseBusy.value) return
  if (forceReparse && !await confirm({ type: 'WARNING', title: '强制重新解析', message: '强制解析会重建当前会话 parsed 结果；原始日志不会删除。确认继续？', confirmText: '重新解析' })) return
  parseSubmitting.value = true
  error.value = ''
  try {
    rememberTask(await parseOnlineMrSession(detail.value.session_id, forceReparse))
    poll()
    openTaskWindow()
  } catch (cause) {
    error.value = message(cause, forceReparse ? '强制重新解析启动失败' : '会话解析启动失败')
  } finally {
    parseSubmitting.value = false
  }
}
async function startReport(): Promise<void> {
  if (!detail.value || reportDisabled.value || sessionActionsDisabled.value || sessionResourceBusy.value) return
  reportSubmitting.value = true
  error.value = ''
  try {
    const selected = detail.value
    const suggestedName = `${safeExportPart(selected.device_name || selected.mr_name || 'Online-MR')}-分析报告-${exportTimestamp()}.xlsx`
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.online_mr_report',
      suggestedName,
      context: { sessionId: selected.session_id },
      submit: () => exportOnlineMrReport(selected.session_id, suggestedName),
    })
    if (result.status === 'cancelled') return
    rememberTask(result.task)
    poll()
    ElMessage.success('分析报告任务已提交，完成后将写入所选位置。')
  } catch (cause) {
    error.value = message(cause, 'Online MR 报告生成启动失败')
  } finally {
    reportSubmitting.value = false
  }
}
function safeExportPart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || 'Online-MR'
}
function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}
function taskResultBoolean(value: RailTransitTask, key: string): boolean {
  return value.result_summary[key] === true
}
function taskResultStrings(value: RailTransitTask, key: string): string[] {
  const rows = value.result_summary[key]
  return Array.isArray(rows) ? rows.filter((item): item is string => typeof item === 'string') : []
}
async function finishDeleteTask(updated: RailTransitTask): Promise<void> {
  const target = pendingDeleteTarget.value
  pendingDeleteTarget.value = null
  if (!target) return
  if (updated.status === 'FAILED' || !taskResultBoolean(updated, 'session_deleted')) {
    ElMessage.error(updated.error_message || updated.message || '会话删除失败，原会话已保留。')
    return
  }
  const issues = [...taskResultStrings(updated, 'failed_items'), ...taskResultStrings(updated, 'warnings')]
  if (sessionId.value === target.sessionId) {
    requestController?.abort()
    sessionId.value = ''
    detail.value = null
    clearSessionData()
  }
  await loadSessions({ preferredIndex: target.index })
  if (updated.status === 'COMPLETED' && issues.length === 0) {
    ElMessage.success('会话及其受管本地数据已删除。')
  } else {
    ElMessage.warning(`会话主体已删除，部分关联项处理失败：${issues.join('；') || updated.message || '请在任务中心查看详情。'}`)
  }
}
async function deleteCurrentSession(): Promise<void> {
  const selected = detail.value
  if (!selected || sessionResourceBusy.value || !isFeatureEnabled('web.online_mr_session_delete')) return
  const selectedIndex = Math.max(0, sessions.value.findIndex((item) => item.session_id === selected.session_id))
  const duration = selected.duration_minutes == null ? '无数据' : `${formatNumber(selected.duration_minutes, 3)} min`
  const accepted = await confirm({
    type: 'DESTRUCTIVE',
    title: '删除 Online MR 会话',
    message: [
      `MR：${selected.device_name || selected.mr_name || '无数据'}`,
      `会话 ID：${selected.session_id}`,
      `开始时间：${selected.started_at || '无数据'}`,
      `采集时长：${duration}`,
      `数据完整性：${selected.data_integrity || 'unknown'}`,
      '',
      '删除后将移除该会话的解析数据、缓存、报告记录及 NetConsole 管理的本地会话文件，此操作不可撤销。',
    ].join('\n'),
    confirmText: '确认删除',
  })
  if (!accepted || detail.value?.session_id !== selected.session_id) return
  deleting.value = true
  error.value = ''
  try {
    const submitted = await deleteOnlineMrSession(selected.session_id)
    pendingDeleteTarget.value = { sessionId: selected.session_id, index: selectedIndex }
    rememberTask(submitted)
    poll()
  } catch (cause) {
    error.value = message(cause, 'Online MR 会话删除启动失败')
  } finally {
    deleting.value = false
  }
}
async function recoverTask(): Promise<void> {
  try {
    const saved = localStorage.getItem('netconsole.online-mr-analysis.last-task') || ''
    const rows = await recoverRailTransitTasks()
    rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => ['online_mr_parse', 'online_mr_report', 'online_mr_session_delete'].includes(item.action)) || null)
    if (task.value?.action === 'online_mr_session_delete' && task.value.status !== 'COMPLETED') {
      const deletingSession = String(task.value.result_summary.session_id || sessionId.value)
      pendingDeleteTarget.value = { sessionId: deletingSession, index: Math.max(0, sessions.value.findIndex((item) => item.session_id === deletingSession)) }
    }
    poll()
  } catch (cause) {
    error.value = message(cause, '任务恢复失败')
  }
}
function changeTab(tab: string): void {
  activeTab.value = tab
  const context = nextRequestContext()
  void loadActiveTab(tab, context)
}
function changeChartTab(tab: string): void {
  chartTab.value = tab
  const context = nextRequestContext()
  const definition = chartDefinitions.find((item) => item.key === tab)
  if (definition?.switchSource) void loadSwitchWindows(definition.switchSource, false, context)
  else void loadMetric(tab, [...(definition?.metric || [])], false, context)
}
function loadMoreChart(): void {
  const definition = selectedChart.value
  if (definition.switchSource) void loadSwitchWindows(definition.switchSource, true)
  else void loadMetric(definition.key, [...(definition.metric || [])], true)
}
function loadMoreActiveTab(): void {
  if (currentBusinessTable.value) void loadBusinessTable(currentBusinessTable.value, true)
  else if (activeTab.value === 'charts') loadMoreChart()
}
watch([startTime, endTime], () => {
  if (!currentBusinessTable.value && activeTab.value !== 'charts') return
  clearAnalysisData()
  const context = nextRequestContext()
  void loadActiveTab(activeTab.value, context)
})
watch([downsample, bucketSeconds], () => {
  if (activeTab.value !== 'charts') return
  clearAnalysisData()
  const context = nextRequestContext()
  void loadActiveTab('charts', context)
})
watch(() => route.query.site_id, () => {
  detail.value = null
  businessSummary.value = null
  sessionId.value = ''
  sessions.value = []
  clearSessionData()
  nextRequestContext()
  void loadSessions()
})

onMounted(async () => {
  await loadSessions()
  await recoverTask()
})
onActivated(() => {
  if (task.value && !terminalStates.has(task.value.status)) poll()
})
onDeactivated(stopPolling)
onBeforeUnmount(() => {
  requestController?.abort()
  stopPolling()
})

function businessRowsFor(table: OnlineMrBusinessTable): BusinessRow[] {
  return businessRows.value[table]
}
function mainLinkRowClass({ rowIndex }: { rowIndex: number }): string {
  return businessRowClass(mainLinkRows.value, rowIndex, 'link_state')
}
function linkDetailRowClass({ rowIndex }: { rowIndex: number }): string {
  return businessRowClass(linkDetailRows.value, rowIndex, 'link_state')
}
</script>

<template>
  <section class="analysis-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">RAIL TRANSIT · ONLINE MR ANALYSIS</p>
        <h1>车载 MR 收集分析</h1>
        <p>会话、原始日志与采集记录不依赖 parsed 数据库；业务表按解析结果结构化展示，动态图继续复用现有指标接口。</p>
      </div>
      <div class="actions">
        <el-select v-model="sessionId" class="session-selector" filterable placeholder="选择 Online MR 会话" :disabled="deleteBusy" @change="loadAnalysis">
          <el-option v-for="item in sessions" :key="item.session_id" :label="`${item.device_name || item.mr_name} · ${item.status} · ${item.started_at || item.session_id}`" :value="item.session_id" />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" :disabled="deleteBusy" @click="loadSessions()">刷新</el-button>
        <el-button data-testid="parse-session" :disabled="!canParse || parsedStatus === 'parsing' || sessionActionsDisabled || reportBusy || parseBusy" :loading="parseBusy" @click="startParse(false)">{{ parsedStatus === 'missing' ? '解析当前会话' : '重新解析' }}</el-button>
        <el-button data-testid="force-reparse-session" :disabled="!canParse || parsedStatus === 'parsing' || sessionActionsDisabled || reportBusy || parseBusy" :loading="parseBusy" @click="startParse(true)">强制重新解析</el-button>
        <el-button data-testid="open-session-location" :icon="FolderOpened" :loading="openingLocation" :disabled="sessionActionsDisabled || openingLocation || !desktopLocationAvailable" :title="openLocationTitle" @click="openSessionLocation">打开本地目录</el-button>
        <el-button data-testid="generate-report" type="primary" :icon="Download" :loading="reportBusy" :disabled="reportDisabled || sessionActionsDisabled || sessionResourceBusy" :title="reportDisabled ? parsedMessage : ''" @click="startReport">生成 XLSX 报告</el-button>
        <el-button :icon="Tickets" @click="openTaskWindow">打开任务中心</el-button>
        <el-button data-testid="delete-session" type="danger" plain :icon="Delete" :loading="deleteBusy" :disabled="sessionActionsDisabled || sessionResourceBusy || !isFeatureEnabled('web.online_mr_session_delete')" @click="deleteCurrentSession">删除</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-empty v-if="!detail && !loading" description="当前局点暂无 Online MR 会话" />

    <template v-if="detail">
      <div class="summary-grid">
        <article><span>会话状态</span><strong>{{ detail.status || '无数据' }}</strong></article>
        <article><span>MR</span><strong>{{ detail.device_name || detail.mr_name || '无数据' }}</strong></article>
        <article><span>完整性</span><strong>{{ detail.data_integrity || '无数据' }}</strong></article>
        <article><span>执行端</span><strong>{{ detail.executor_kind || '无数据' }}</strong></article>
        <article><span>采集时长</span><strong>{{ display(detail.duration_minutes) }} min</strong></article>
      </div>

      <el-alert class="parsed-status" :type="parsedAlertType" :title="`${parsedStatusLabel} · ${parsedMessage}`" show-icon :closable="false">
        <template #default>
          <span v-if="detail.database_summary.parser_version">Parser：{{ detail.database_summary.parser_version }}</span>
          <span v-if="detail.database_summary.missing_capabilities.length">；缺少能力：{{ detail.database_summary.missing_capabilities.join('、') }}</span>
        </template>
      </el-alert>

      <el-alert v-if="analysisError" class="analysis-error" :title="analysisError" type="warning" show-icon :closable="false" />

      <div class="query-bar">
        <el-date-picker v-model="startTime" type="datetime" placeholder="开始时间" value-format="YYYY-MM-DD HH:mm:ss.SSS" />
        <span>至</span>
        <el-date-picker v-model="endTime" type="datetime" placeholder="结束时间" value-format="YYYY-MM-DD HH:mm:ss.SSS" />
        <el-select v-model="downsample" style="width:160px">
          <el-option label="不降采样" value="NONE" />
          <el-option label="按桶平均" value="BUCKET_AVG" />
          <el-option label="保留首尾异常" value="LATEST_PER_BUCKET" />
          <el-option label="最小最大" value="MIN_MAX" />
        </el-select>
        <el-input-number v-model="bucketSeconds" :min="1" :max="86400" controls-position="right" />
        <span class="query-hint"><el-icon :size="16" class="inline-icon"><Search /></el-icon>查询窗口仅在当前页签加载</span>
      </div>

      <div ref="analysisTabsHost" class="analysis-tabs-host">
      <el-tabs :model-value="activeTab" class="analysis-tabs" @tab-change="changeTab">
        <el-tab-pane name="session-history" label="会话记录">
          <NcDataTable table-id="online-mr-analysis-session-history" route-key="/rail-transit/online-mr-analysis" :data="sessions" :columns="sessionColumns" row-key="session_id" :current-row-key="sessionId" highlight-current-row border :height="tableHeight" empty-text="暂无会话" @row-click="selectSession" />
        </el-tab-pane>

        <el-tab-pane name="mesh-link" label="主链路信息">
          <div class="business-summary" v-if="businessSummary">
            <article v-for="item in businessSummaryCards" :key="item.label">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
          <NcDataTable
            table-id="online-mr-analysis-mesh-link"
            route-key="/rail-transit/online-mr-analysis"
            :data="mainLinkRows"
            :columns="mainLinkColumns"
            :row-class-name="mainLinkRowClass"
            border
            :height="tableHeight"
            empty-text="暂无主链路信息"
          />
        </el-tab-pane>

        <el-tab-pane name="mesh-detail" label="链路明细">
          <NcDataTable table-id="online-mr-analysis-mesh-detail" route-key="/rail-transit/online-mr-analysis" :data="linkDetailRows" :columns="linkDetailColumns" :row-class-name="linkDetailRowClass" border :height="tableHeight" empty-text="暂无链路明细" />
        </el-tab-pane>

        <el-tab-pane name="channel-busy" label="信道繁忙度">
          <NcDataTable table-id="online-mr-analysis-channel-busy" route-key="/rail-transit/online-mr-analysis" :data="channelBusyRows" :columns="channelBusyColumns" border :height="tableHeight" empty-text="暂无信道数据" />
        </el-tab-pane>

        <el-tab-pane name="switch-history" label="主链路切换历史">
          <NcDataTable table-id="online-mr-analysis-switch-history" route-key="/rail-transit/online-mr-analysis" :data="switchHistoryRows" :columns="switchHistoryColumns" border :height="tableHeight" empty-text="暂无主链路切换历史" />
        </el-tab-pane>

        <el-tab-pane name="active-switch" label="主链路切换日志">
          <NcDataTable table-id="online-mr-analysis-active-switch" route-key="/rail-transit/online-mr-analysis" :data="switchRealtimeRows" :columns="switchRealtimeColumns" border :height="tableHeight" empty-text="暂无主链路切换日志" />
        </el-tab-pane>

        <el-tab-pane name="interface-rate" label="接口速率">
          <NcDataTable table-id="online-mr-analysis-interface-rate" route-key="/rail-transit/online-mr-analysis" :data="interfaceRows" :columns="interfaceColumns" border :height="tableHeight" empty-text="暂无接口速率数据" />
        </el-tab-pane>

        <el-tab-pane name="charts" label="动态图">
          <el-tabs :model-value="chartTab" type="card" @tab-change="changeChartTab">
            <el-tab-pane v-for="item in chartDefinitions" :key="item.key" :name="item.key" :label="item.title">
              <OnlineMrAnalysisChart :series="chartTab === item.key ? chartSeries : (metrics[item.key] || [])" :title="item.title" :unit="item.unit" :events="chartTab === item.key ? chartEvents() : []" />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane name="fping" label="fping 1s 聚合">
          <NcDataTable table-id="online-mr-analysis-fping" route-key="/rail-transit/online-mr-analysis" :data="fpingRows" :columns="fpingColumns" border :height="tableHeight" empty-text="暂无 fping 数据" />
        </el-tab-pane>

        <el-tab-pane name="iperf" label="打流测试">
          <NcDataTable table-id="online-mr-analysis-iperf" route-key="/rail-transit/online-mr-analysis" :data="iperfRows" :columns="iperfColumns" border :height="tableHeight" empty-text="暂无打流测试数据" />
        </el-tab-pane>

        <el-tab-pane name="diagnosis" label="诊断">
          <NcDataTable table-id="online-mr-analysis-diagnosis" route-key="/rail-transit/online-mr-analysis" :data="diagnosisRows" :columns="diagnosisColumns" border :height="tableHeight" empty-text="暂无诊断事件" />
        </el-tab-pane>

        <el-tab-pane name="raw" label="原始日志">
          <div class="raw-layout">
            <NcDataTable table-id="online-mr-analysis-raw" route-key="/rail-transit/online-mr-analysis" :data="rawFiles" :columns="rawColumns" border height="360" empty-text="暂无原始文件" @row-click="openRaw" />
            <pre class="raw-preview">{{ rawName ? `${rawName}\n\n${rawTail.join('\n')}` : '选择文件查看原始日志' }}</pre>
          </div>
        </el-tab-pane>

        <el-tab-pane name="logs" label="采集日志">
          <div class="logs-toolbar">
            <el-button :icon="Files" @click="loadCollectorLog">刷新采集日志</el-button>
            <span>采集器日志与原始设备输出分开保存</span>
          </div>
          <pre class="raw-preview">{{ rawTail.join('\n') || '暂无采集日志' }}</pre>
        </el-tab-pane>
      </el-tabs>

      <div v-if="currentBusinessTable || activeTab === 'charts'" class="timeline-actions">
        <el-button v-if="currentBusinessTable" :disabled="!currentBusinessHasMore" @click="loadMoreActiveTab">加载更多业务数据</el-button>
        <el-button v-else :disabled="!chartHasMore" @click="loadMoreChart">加载更多图表数据</el-button>
        <span v-if="currentBusinessTable">当前 {{ currentBusinessRows.length }} 条 {{ businessTableLabel(currentBusinessTable) }}</span>
        <span v-else>图表数据按当前时间范围分批加载</span>
      </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.analysis-page{display:flex;flex-direction:column;gap:16px;min-width:0}
.page-heading,.actions,.query-bar,.logs-toolbar{display:flex;align-items:center;gap:12px}
.page-heading{justify-content:space-between;align-items:flex-start}
.page-heading h1{margin:2px 0 6px}
.page-heading p,.query-hint,.logs-toolbar{margin:0;color:var(--el-text-color-secondary)}
.actions{justify-content:flex-end;flex-wrap:wrap;min-width:0}
.session-selector{flex:1 1 340px;max-width:430px;min-width:260px}
.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}
.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}
.summary-grid article,.business-summary article{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:10px}
.summary-grid article{padding:13px}
.summary-grid span,.business-summary span{color:var(--el-text-color-secondary);font-size:12px}
.summary-grid strong,.business-summary strong{display:block;margin-top:6px;font-size:18px}
.business-summary{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:10px;margin:0 0 10px}
.business-summary article{padding:12px}
.query-bar{flex-wrap:wrap}
.query-hint{display:inline-flex;align-items:center;gap:4px;font-size:12px}
.inline-icon{width:16px!important;height:16px!important;max-width:16px!important;max-height:16px!important;flex:0 0 16px!important;flex-shrink:0!important}
.inline-icon :deep(svg){width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important}
.analysis-tabs-host,.analysis-tabs{min-width:0}
.raw-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:12px}
.raw-preview{margin:0;min-height:360px;max-height:480px;overflow:auto;padding:12px;border:1px solid var(--el-border-color-lighter);border-radius:8px;background:var(--el-fill-color-light);font:12px/1.6 Consolas,monospace;white-space:pre-wrap}
.timeline-actions{display:flex;align-items:center;gap:8px}
:deep(.online-mr-row--group-a > td.el-table__cell){background:color-mix(in srgb, var(--nc-primary), transparent 96%)}
:deep(.online-mr-row--group-b > td.el-table__cell){background:color-mix(in srgb, var(--nc-success), transparent 96%)}
:deep(.online-mr-row--active .nc-table-cell){color:var(--el-color-success);font-weight:600}
:deep(.online-mr-row--active > td.el-table__cell){background:color-mix(in srgb, var(--nc-success), transparent 94%)}
@media(max-width:1200px){
  .summary-grid{grid-template-columns:repeat(3,minmax(140px,1fr))}
  .business-summary{grid-template-columns:repeat(2,minmax(140px,1fr))}
  .raw-layout{grid-template-columns:1fr}
}
@media(max-width:800px){
  .page-heading{align-items:flex-start;flex-direction:column}
  .actions{justify-content:flex-start;width:100%}
  .session-selector{max-width:none;width:100%}
  .summary-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}
  .query-bar>*{max-width:100%;width:100%!important}
}
</style>
