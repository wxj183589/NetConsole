<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Delete, Download, Files, FolderOpened, FullScreen, Hide, Lock, Refresh, Search, Unlock, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import { ApiRequestError } from '../../api/client'
import {
  getOnlineMrBusinessSummary,
  getOnlineMrTrafficOverview,
  getOnlineMrRawTail,
  listOnlineMrRawFiles,
  queryOnlineMrBusinessTable,
  queryOnlineMrMetrics,
  queryOnlineMrTimelineMetrics,
  queryOnlineMrSwitchRssiWindows,
} from '../../api/onlineMr'
import { deleteOnlineMrSession, ensureOnlineMrParsedDatabaseCurrent, exportOnlineMrReport, getRailTransitTask, parseOnlineMrSession, recoverRailTransitTasks } from '../../api/railTransitWeb'
import OnlineMrAnalysisChart from '../../components/online-mr-analysis/OnlineMrAnalysisChart.vue'
import OnlineMrAnalysisInfoPanel, { type OnlineMrAnalysisInfoSection } from '../../components/online-mr-analysis/OnlineMrAnalysisInfoPanel.vue'
import OnlineMrPingQualityChart from '../../components/online-mr-analysis/OnlineMrPingQualityChart.vue'
import OnlineMrRssiChart from '../../components/online-mr-analysis/OnlineMrRssiChart.vue'
import {
  nearestRailTimelineSample,
  useRailTimelineController,
} from '../../components/rail-timeline/railTimeline'
import { useConfirm } from '../../components/feedback/useConfirm'
import { useAvailablePanelHeight } from '../../composables/useAvailablePanelHeight'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import {
  createOnlineMrAnalysisSessionCache,
  onlineMrAnalysisCacheKey,
  onlineMrSessionRevision,
  onlineMrSessionDeleteBlockReason,
  useOnlineMrAnalysisStore,
  type OnlineMrAnalysisSessionCache,
} from '../../stores/onlineMrAnalysis'
import type {
  OnlineMrBusinessSummary,
  OnlineMrBusinessRow,
  OnlineMrBusinessTable,
  OnlineMrMainLinkRow,
  OnlineMrMetricPoint,
  OnlineMrMetricSeries,
  OnlineMrTrafficOverview,
  OnlineMrRawFile,
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
  OnlineMrSwitchRssiSource,
  OnlineMrSwitchRssiWindow,
} from '../../types/onlineMr'
import { createFullMeshViewportFromDomain, type MeshChartViewport, type MeshSharedPointerChange } from '../../components/mesh-analysis/meshChartViewport'
import type { MeshChartEvent } from '../../types/meshAnalysis'
import type { MeshRssiLayoutMode } from '../../components/mesh-analysis/meshRssiLayout'
import type { OnlineMrParsedDatabaseEnsureResult, RailTransitTask } from '../../types/railTransitWeb'
import { BEFORE_SITE_SWITCH_EVENT } from '../../workspace/site-switch'
import { formatDbmValue, formatRssiValue } from '../../components/rail-timeline/rssiPresentation'
import { formatTimelineMetricValue } from '../../components/rail-timeline/timelineMetricPresentation'

const route = useRoute()
const router = useRouter()
const { confirm } = useConfirm()
const userSelectedExport = useUserSelectedExport()
const analysisStore = useOnlineMrAnalysisStore()
const {
  sessions,
  selectedSessionId: sessionId,
  selectedSessionDetail: detail,
  loading: sessionsLoading,
} = storeToRefs(analysisStore)

type BusinessRow = OnlineMrBusinessRow
type RequestContext = { siteKey: string; sessionId: string; generation: number; signal: AbortSignal }
type ChartDefinition = { key: string; title: string; unit: string; metric?: readonly string[]; switchSource?: OnlineMrSwitchRssiSource }

const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const chartDefinitions: readonly ChartDefinition[] = [
  { key: 'rssi', title: '主链路 RSSI', unit: '' },
  { key: 'switch-log-rssi', title: '实时切换日志 RSSI 快照', switchSource: 'realtime', unit: 'dBm' },
  { key: 'ping-quality', title: 'Ping 质量', metric: ['ping_loss', 'ping_rtt'], unit: '' },
  { key: 'interface', title: '接口速率', metric: ['interface_in_pps', 'interface_out_pps'], unit: 'pps' },
  { key: 'traffic', title: '业务打流', metric: ['iperf_bitrate'], unit: 'Mbps' },
  { key: 'busy', title: '信道繁忙度（Channel Busy）', metric: ['ctl_busy', 'tx_busy', 'rx_busy'], unit: '%' },
  { key: 'switch-rssi', title: '切换历史 RSSI 快照', switchSource: 'history', unit: 'dBm' },
]
const trafficMetricDefinitions = [
  { key: 'throughput', title: '吞吐率', metric: ['iperf_bitrate'], unit: 'Mbps', tooltipKind: 'traffic' as const },
  { key: 'loss', title: '流量丢失', metric: ['iperf_loss'], unit: '%', tooltipKind: 'traffic-loss' as const },
  { key: 'jitter', title: 'Jitter', metric: ['iperf_jitter'], unit: 'ms', tooltipKind: 'traffic-jitter' as const },
  { key: 'retransmits', title: 'TCP 重传', metric: ['iperf_retransmits'], unit: '次', tooltipKind: 'traffic-retransmits' as const },
] as const
const timelineMetricTypes = [
  'rssi',
  'trackside_rssi',
  'ping_loss',
  'ping_rtt',
  'interface_in_pps',
  'interface_out_pps',
  'iperf_bitrate',
  'iperf_loss',
  'iperf_jitter',
  'iperf_retransmits',
  'ctl_busy',
  'tx_busy',
  'rx_busy',
] as const
const relatedMetricDefinitions = chartDefinitions.filter((item) => item.metric)

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

const businessSummary = ref<OnlineMrBusinessSummary | null>(null)
const trafficOverview = ref<OnlineMrTrafficOverview | null>(null)
const trafficWindowOverview = ref<OnlineMrTrafficOverview | null>(null)
const trafficMetricKey = ref('throughput')
const businessSummaryLoaded = ref(false)
const activeTab = ref('session-history')
const chartTab = ref('rssi')
const metrics = ref<Record<string, OnlineMrMetricSeries[]>>({})
const metricOffsets = ref<Record<string, number>>({})
const metricHasMore = ref<Record<string, boolean>>({})
const metricLoaded = ref<Record<string, boolean>>({})
const switchWindows = ref<Record<OnlineMrSwitchRssiSource, OnlineMrSwitchRssiWindow[]>>({ history: [], realtime: [] })
const switchOffsets = ref<Record<OnlineMrSwitchRssiSource, number>>({ history: 0, realtime: 0 })
const switchHasMore = ref<Record<OnlineMrSwitchRssiSource, boolean>>({ history: false, realtime: false })
const switchLoaded = ref<Record<OnlineMrSwitchRssiSource, boolean>>({ history: false, realtime: false })
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
const businessLoaded = ref<Record<OnlineMrBusinessTable, boolean>>({
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
const rawFilesLoaded = ref(false)
const rawTail = ref<string[]>([])
const rawName = ref('')
const railTimeline = useRailTimelineController()
const rssiViewport = railTimeline.viewport
const timelineCursorTime = railTimeline.cursorTime
const timelineCursorSource = railTimeline.cursorSource
const selectedTime = railTimeline.selectedTime
const timeRangeLocked = railTimeline.timeRangeLocked
const selectedTimeLocked = railTimeline.selectedTimeLocked
const rssiLayoutMode = ref<MeshRssiLayoutMode>('compare')
const rssiSplitRatio = ref(0.5)
const selectedRadio = ref<number | null>(null)
const pointLimit = ref(600)
const showPeerRssi = ref(false)
const showSwitchLines = ref(true)
const showSwitchPoints = ref(true)
const showLocationBand = ref(true)
const rssiImmersive = ref(false)
const relatedMetricKey = ref('ping-quality')
const task = ref<RailTransitTask | null>(null)
const upgradeResult = ref<OnlineMrParsedDatabaseEnsureResult | null>(null)
const detailLoading = ref(false)
const parseSubmitting = ref(false)
const reportSubmitting = ref(false)
const deletingSessionId = ref<string | null>(null)
const openingSessionId = ref<string | null>(null)
const error = ref('')
const analysisError = ref('')
const startTime = ref('')
const endTime = ref('')
const downsample = ref<'NONE' | 'BUCKET_AVG' | 'MIN_MAX' | 'LATEST_PER_BUCKET'>('LATEST_PER_BUCKET')
const bucketSeconds = ref(1)
const analysisTabsHost = ref<HTMLElement | null>(null)
const pendingDeleteTarget = ref<{
  sessionId: string
  previousSessionId: string | null
  nextSessionId: string | null
} | null>(null)
const panel = useAvailablePanelHeight(analysisTabsHost, { minHeight: 420, bottomGap: 40 })

const metricLimit = 1_000
const businessLimit = 500
const switchLimit = 200
const timelineLimit = 200
let pollTimer: number | undefined
let requestGeneration = 0
let requestController: AbortController | null = null
let viewGeneration = 0
let viewActive = true
let initialized = false
let restoringCache = false
let boundSiteKey = ''
let boundSessionId = ''
const chartActive = ref(true)
const deleteRequests = new Set<string>()

const mainLinkRows = computed<OnlineMrMainLinkRow[]>(() => businessRows.value.main_link as OnlineMrMainLinkRow[])
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
const timelineSeries = computed(() => metrics.value['rail-timeline'] || [])
const timelineMainSeries = computed(() => timelineSeries.value.filter((item) => item.metric_type === 'rssi'))
const timelineTracksideSeries = computed(() => timelineSeries.value.filter((item) => item.metric_type === 'trackside_rssi'))
function metricSeries(types: readonly string[]): OnlineMrMetricSeries[] {
  const requested = new Set(types)
  return timelineSeries.value.filter((item) => requested.has(item.metric_type))
}
const trafficMetricDefinition = computed(() => trafficMetricDefinitions.find((item) => item.key === trafficMetricKey.value) || trafficMetricDefinitions[0])
const chartSeries = computed(() => {
  if (selectedChart.value.key === 'ping-quality') return []
  if (selectedChart.value.key === 'traffic') return metricSeries(trafficMetricDefinition.value.metric)
  if (selectedChart.value.switchSource) return switchRssiSeries(selectedChart.value.switchSource)
  const shared = metricSeries(selectedChart.value.metric || [])
  return shared.length ? shared : metrics.value[selectedChart.value.key] || []
})
const relatedMetric = computed(() => relatedMetricDefinitions.find((item) => item.key === relatedMetricKey.value) || relatedMetricDefinitions[0])
const relatedMetricSeries = computed(() => metricSeries(relatedMetric.value?.metric || []))
const availableTimelineRadios = computed(() => {
  const values = new Set<number>()
  for (const series of [...timelineMainSeries.value, ...timelineTracksideSeries.value]) {
    for (const point of series.points) {
      const value = Number(point.dimensions.radio)
      if (Number.isFinite(value)) values.add(value)
    }
  }
  return [...values].sort((left, right) => left - right)
})
const timelineTimeDomain = computed(() => {
  const timestamps = timelineSeries.value.flatMap((series) => series.points.flatMap((point) => point.timestamp ? [point.timestamp] : [])).sort()
  return timestamps.length > 1 ? { full_start_time: timestamps[0], full_end_time: timestamps.at(-1)! } : null
})
const timelineSwitchWindows = computed<Record<OnlineMrSwitchRssiSource, OnlineMrSwitchRssiWindow[]>>(() => {
  const domain = timelineTimeDomain.value
  if (!domain) return switchWindows.value
  const withinDomain = (item: OnlineMrSwitchRssiWindow) => Boolean(
    item.event_time
    && item.event_time >= domain.full_start_time
    && item.event_time <= domain.full_end_time,
  )
  return {
    history: switchWindows.value.history.filter(withinDomain),
    realtime: switchWindows.value.realtime.filter(withinDomain),
  }
})
const timelineWorkspaceHeight = computed(() => rssiImmersive.value
  ? Math.max(420, window.innerHeight - 190)
  : Math.max(420, panel.height.value - 32))
const fullTrafficOverview = computed(() => trafficOverview.value || businessSummary.value?.traffic_overview || null)
const visibleTrafficMetricDefinitions = computed(() => fullTrafficOverview.value?.protocol === 'TCP'
  ? trafficMetricDefinitions.filter((item) => item.key === 'throughput' || item.key === 'retransmits')
  : trafficMetricDefinitions.filter((item) => item.key !== 'retransmits'))

const analysisTime = computed(() => selectedTimeLocked.value
  ? selectedTime.value
  : timelineCursorTime.value || selectedTime.value)

function nearestMetric(types: readonly string[], time = analysisTime.value): { series: OnlineMrMetricSeries; point: OnlineMrMetricPoint } | null {
  const rows = metricSeries(types).flatMap((series) => series.points.map((point) => ({ series, point })))
  return nearestRailTimelineSample(rows, time, (row) => row.point.timestamp)
}

const selectedTimelineDiagnosis = computed(() => {
  const time = analysisTime.value
  if (!time) return null
  const main = nearestMetric(['rssi'])
  const trackside = timelineTracksideSeries.value.flatMap((series) => {
    const point = nearestRailTimelineSample(series.points, time, (row) => row.timestamp)
    return point ? [{ series, point }] : []
  }).sort((left, right) => Number(right.point.value ?? -Infinity) - Number(left.point.value ?? -Infinity)).slice(0, 6)
  const switchEvent = nearestRailTimelineSample(
    [...timelineSwitchWindows.value.realtime, ...timelineSwitchWindows.value.history].filter((item) => item.event_time),
    time,
    (item) => item.event_time,
    10_000,
  )
  return {
    main,
    trackside,
    busy: nearestMetric(['ctl_busy', 'tx_busy', 'rx_busy']),
    pingLoss: nearestMetric(['ping_loss']),
    pingRtt: nearestMetric(['ping_rtt']),
    traffic: nearestMetric(['iperf_bitrate']),
    interfaceRate: nearestMetric(['interface_in_pps', 'interface_out_pps']),
    switchEvent,
  }
})
const chartHasMore = computed(() => {
  if (selectedChart.value.key === 'rssi' || selectedChart.value.metric) return false
  return selectedChart.value.switchSource
    ? switchHasMore.value[selectedChart.value.switchSource]
    : Boolean(metricHasMore.value[selectedChart.value.key])
})
const parsedStatus = computed(() => detail.value?.database_summary.status || 'missing')
const parsedReadable = computed(() => ['ready', 'legacy', 'stale', 'parsing'].includes(parsedStatus.value) && detail.value?.database_summary.compatible !== false)
const parsedReady = computed(() => parsedStatus.value === 'ready')
const effectiveUpgradeStatus = computed(() => upgradeResult.value?.status || detail.value?.database_summary.upgrade_status || (parsedReady.value ? 'CURRENT' : parsedStatus.value === 'parsing' ? 'UPGRADING' : ''))
const parsedStatusLabel = computed(() => effectiveUpgradeStatus.value === 'UPGRADING' ? '解析库升级中'
  : effectiveUpgradeStatus.value === 'RAW_DATA_MISSING' ? '解析库无法自动升级'
    : effectiveUpgradeStatus.value === 'FAILED' ? '解析库升级失败'
      : parsedReady.value ? '解析可用'
        : ({ ready: '解析可用', missing: '尚未解析', legacy: '旧版解析结果', stale: '解析结果已过期', unreadable: '解析结果不可读', parsing: '正在解析' }[parsedStatus.value] || parsedStatus.value))
const parsedAlertType = computed<'success' | 'warning' | 'danger'>(() => parsedReady.value || effectiveUpgradeStatus.value === 'CURRENT' ? 'success' : ['FAILED', 'RAW_DATA_MISSING'].includes(effectiveUpgradeStatus.value) || parsedStatus.value === 'unreadable' ? 'danger' : 'warning')
const parserPanelTone = computed<'success' | 'warning' | 'danger' | 'info'>(() => parsedAlertType.value)
const parsedMessage = computed(() => detail.value?.database_summary.message || '当前会话尚未生成解析结果。')
const canParse = computed(() => Boolean(detail.value?.has_raw_data && isFeatureEnabled('web.online_mr_parse')))
const reportDisabled = computed(() => !parsedReady.value || !isFeatureEnabled('web.online_mr_report_export'))
const taskActive = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const parseBusy = computed(() => parseSubmitting.value || (taskActive.value && task.value?.action === 'online_mr_parse'))
const reportBusy = computed(() => reportSubmitting.value || (taskActive.value && task.value?.action === 'online_mr_report'))
const deleteBusy = computed(() => Boolean(deletingSessionId.value))
const sessionResourceBusy = computed(() => parseBusy.value || reportBusy.value || deleteBusy.value)
const loading = computed(() => sessionsLoading.value || detailLoading.value)
const tableHeight = computed(() => Math.max(360, panel.height.value - 58))
const desktopLocationAvailable = computed(() => Boolean(
  window.netconsoleDesktop?.openOnlineMrSessionLocation
  && isFeatureEnabled('desktop.native_bridge')
  && isFeatureEnabled('web.online_mr_session_open_location'),
))
const sessionActionsDisabled = computed(() => !detail.value || deleteBusy.value)
const selectedDeleteBlockReason = computed(() => onlineMrSessionDeleteBlockReason(detail.value))
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
    { label: 'RSSI', value: summary.current_rssi == null ? '无数据' : formatRssiValue(summary.current_rssi) },
    { label: '站点 / 区间', value: `${display(summary.current_station)} / ${display(summary.current_section)}` },
    { label: '当前时段', value: summary.current_segment_duration_seconds == null ? '无数据' : `${formatNumber(summary.current_segment_duration_seconds, 2)} s` },
    { label: '最新采样', value: summary.last_sample_time || '无数据' },
  ]
})

function infoText(value: unknown): string {
  const text = String(value ?? '').trim()
  return text || '—'
}

const analysisInfoSections = computed<OnlineMrAnalysisInfoSection[]>(() => {
  const alignment = businessSummary.value?.time_alignment
  const diagnosis = selectedTimelineDiagnosis.value
  const main = diagnosis?.main?.point
  const mainDimensions = main?.dimensions || {}
  const hoveredMetric = selectedChart.value.key === 'rssi' ? relatedMetricKey.value : selectedChart.value.key
  const metricFields: OnlineMrAnalysisInfoSection['fields'] = []
  if (timelineCursorSource.value === 'trackside-rssi' && diagnosis?.trackside[0]) {
    const point = diagnosis.trackside[0].point
    metricFields.push(
      { label: '类型', value: '轨旁 AP RSSI' },
      { label: 'AP', value: infoText(point.dimensions.peer_name || diagnosis.trackside[0].series.series_key) },
      { label: 'Radio', value: infoText(point.dimensions.radio) },
      { label: '状态', value: infoText(point.dimensions.link_state) },
      { label: '轨旁 RSSI', value: point.value == null ? '—' : formatRssiValue(point.value) },
      { label: 'MR RSSI', value: main?.value == null ? '—' : formatRssiValue(main.value) },
      { label: '站点', value: infoText(point.dimensions.station) },
      { label: '区间', value: infoText(point.dimensions.section) },
    )
  } else if (timelineCursorSource.value === 'timeline-metric' && hoveredMetric === 'ping-quality') {
    const rtt = diagnosis?.pingRtt?.point
    const loss = diagnosis?.pingLoss?.point
    metricFields.push(
      { label: '类型', value: 'Ping 质量' },
      { label: '目标', value: infoText(rtt?.dimensions.target_ip || loss?.dimensions.target_ip || rtt?.dimensions.target_name) },
      { label: 'RTT', value: rtt?.value == null ? '—' : formatTimelineMetricValue('ping_rtt', rtt.value) },
      { label: '丢包', value: loss?.value == null ? '—' : formatTimelineMetricValue('ping_loss', loss.value) },
    )
  } else if (timelineCursorSource.value === 'timeline-metric' && hoveredMetric === 'busy') {
    const point = diagnosis?.busy?.point
    metricFields.push(
      { label: '类型', value: 'Channel Busy' },
      { label: '信道', value: infoText(point?.dimensions.ctl_channel) },
      { label: '频宽', value: point?.dimensions.bandwidth_mhz == null ? '—' : `${infoText(point.dimensions.bandwidth_mhz)} MHz` },
      { label: '繁忙度', value: point?.value == null ? '—' : `${formatNumber(point.value, 2)}%` },
    )
  } else if (timelineCursorSource.value === 'timeline-metric' && hoveredMetric === 'interface') {
    const point = diagnosis?.interfaceRate?.point
    metricFields.push(
      { label: '类型', value: '接口速率' },
      { label: '接口', value: infoText(point?.dimensions.interface_normalized || point?.dimensions.interface_name) },
      { label: '速率', value: point?.value == null ? '—' : `${formatNumber(point.value, 2)} pps` },
    )
  } else if (timelineCursorSource.value === 'timeline-metric' && hoveredMetric === 'traffic') {
    const point = diagnosis?.traffic?.point
    metricFields.push(
      { label: '类型', value: '业务打流' },
      { label: '方向', value: infoText(point?.dimensions.direction) },
      { label: '吞吐', value: point?.value == null ? '—' : `${formatNumber(point.value, 2)} Mbps` },
    )
  } else {
    metricFields.push(
      { label: '类型', value: '主链路 RSSI' },
      { label: 'AP', value: infoText(mainDimensions.peer_name) },
      { label: 'RSSI', value: main?.value == null ? '—' : formatRssiValue(main.value) },
    )
  }
  const switchEvent = diagnosis?.switchEvent
  return [
    {
      key: 'timeline', title: '时间轴', fields: [
        { label: '基准', value: 'MR 设备时间' },
        { label: '采集端 → MR', value: alignment?.offset_median_ms == null ? '—' : `已校正 ${formatNumber(Math.abs(alignment.offset_median_ms / 1000), 3)} s` },
        { label: '漂移', value: alignment?.drift_ms_per_minute == null ? '—' : `${formatNumber(alignment.drift_ms_per_minute, 3)} ms/min` },
        { label: '锚点', value: `${alignment?.inlier_count || 0} / ${alignment?.anchor_count || 0}` },
        { label: '方法', value: timeAlignmentMethodLabel(alignment?.method) },
        { label: '置信度', value: timeAlignmentConfidenceLabel(alignment?.confidence), tone: alignment?.confidence === 'low' ? 'warning' : alignment?.confidence ? 'success' : 'normal' },
        { label: 'fping', value: alignment?.fping_status?.startsWith('aligned') ? '已校正' : '采集端时间' },
        { label: '打流', value: alignment?.traffic_status?.startsWith('aligned') ? '已校正' : '采集端时间' },
      ],
    },
    {
      key: 'current', title: '当前分析时刻', fields: [
        { label: '时间', value: analysisTime.value || '移动指针或点击图表' },
        { label: '站点', value: infoText(mainDimensions.station) },
        { label: '区间', value: infoText(mainDimensions.section) },
        { label: '方向', value: infoText(mainDimensions.direction) },
      ],
    },
    {
      key: 'main', title: '主链路', fields: [
        { label: 'AP', value: infoText(mainDimensions.peer_name) },
        { label: 'Peer', value: infoText(mainDimensions.peer_mac) },
        { label: 'Radio', value: infoText(mainDimensions.radio) },
        { label: 'RSSI', value: main?.value == null ? '—' : formatRssiValue(main.value) },
        { label: '状态', value: infoText(mainDimensions.link_state), tone: String(mainDimensions.link_state || '').toUpperCase() === 'ACTIVE' ? 'success' : 'normal' },
      ],
    },
    { key: 'hover', title: '当前悬停指标', fields: metricFields },
    {
      key: 'switch', title: '切换事件', fields: switchEvent ? [
        { label: '切出', value: `${switchEvent.old_peer_name || '—'} / ${switchEvent.old_rssi_dbm == null ? '—' : formatDbmValue(switchEvent.old_rssi_dbm)}` },
        { label: '切入', value: `${switchEvent.new_peer_name || '—'} / ${switchEvent.new_rssi_dbm == null ? '—' : formatDbmValue(switchEvent.new_rssi_dbm)}` },
        { label: '原因', value: infoText(switchEvent.reason) },
      ] : [{ label: '当前时刻', value: '附近无切换' }],
    },
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
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['打开本地目录', '删除'], width: 180, fixed: 'right' },
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
  { key: 'bandwidth_mhz', label: '频宽', valueType: 'number', displayValue: (row) => row.bandwidth_mhz == null ? '-' : `${row.bandwidth_mhz} MHz` },
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
function formatBytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '暂无可靠统计'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let current = value
  let index = 0
  while (Math.abs(current) >= 1024 && index < units.length - 1) { current /= 1024; index += 1 }
  return `${formatNumber(current, index ? 2 : 0)} ${units[index]}`
}
function formatDurationSeconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '暂无可靠统计'
  if (value < 60) return `${formatNumber(value, 2)} s`
  return `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`
}
function trafficValue(value: number | null | undefined, unit: string): string {
  return value == null ? '暂无可靠统计' : `${formatNumber(value, 2)} ${unit}`
}
function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '无数据'
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(digits)
  return formatted.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
}
function timelineMetricValue(value: { point: OnlineMrMetricPoint; series: OnlineMrMetricSeries } | null, unit = ''): string {
  if (!value || value.point.value == null) return '无数据'
  return `${formatNumber(value.point.value, 2)}${unit ? ` ${unit}` : ''}`
}
function timeAlignmentConfidenceLabel(value: string | undefined): string {
  return ({ high: '高', medium: '中', low: '低' } as Record<string, string>)[value || ''] || '低'
}
function timeAlignmentMethodLabel(value: string | undefined): string {
  return ({ 'fixed-offset': '固定偏差', 'linear-drift': '线性漂移', 'piecewise-offset': '分段偏差', none: '未校正' } as Record<string, string>)[value || 'none'] || value || '未校正'
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
        switch_event: event,
      },
  }))
  return (['old', 'new'] as const).map((role) => {
    const rows = points(role)
    return { metric_type: `switch_${source}_rssi`, series_key: role === 'old' ? '切出链路' : '切入链路', unit: 'dBm', points: rows, summary: metricSummary(rows) }
  })
}
function chartEvents(): Array<{ time: string; label: string }> {
  const source = selectedChart.value.switchSource
  const events = source
    ? switchWindows.value[source]
    : switchWindows.value.realtime.length
      ? switchWindows.value.realtime
      : switchWindows.value.history
  return events.filter((event) => event.event_time).map((event) => ({ time: event.event_time!, label: event.reason || '主链路切换' }))
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
function poll(expectedViewGeneration = viewGeneration): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    if (!viewActive || expectedViewGeneration !== viewGeneration || !task.value) return
    try {
      const updated = await getRailTransitTask(task.value!.task_id)
      if (!viewActive || expectedViewGeneration !== viewGeneration) return
      rememberTask(updated)
      if (terminalStates.has(updated.status)) {
        if (updated.action === 'online_mr_parse') {
          if (sessionId.value) {
            saveCurrentSessionCache()
            analysisStore.invalidateSession(currentSiteKey(), sessionId.value)
            await loadAnalysis({ forceDetail: true })
          }
          if (updated.status === 'COMPLETED') upgradeResult.value = upgradeResult.value ? { ...upgradeResult.value, status: 'CURRENT', missing_capabilities: [], message: '解析数据库升级完成。', task: updated } : null
          task.value = updated
        } else if (updated.action === 'online_mr_report' && updated.status === 'FAILED') {
          ElMessage.error(updated.error_message || updated.message || '分析报告生成失败')
        } else if (updated.action === 'online_mr_session_delete') {
          await finishDeleteTask(updated)
        }
        return
      }
      poll(expectedViewGeneration)
    } catch (cause) {
      if (viewActive && expectedViewGeneration === viewGeneration) {
        error.value = message(cause, '任务状态读取失败')
        poll(expectedViewGeneration)
      }
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
function emptyLoadedState(): Record<OnlineMrBusinessTable, boolean> {
  return { main_link: false, link_detail: false, channel_busy: false, switch_history: false, switch_realtime: false, interface_rate: false, fping_1s: false, iperf: false, diagnostics: false }
}
function saveCurrentSessionCache(): void {
  if (!boundSiteKey || !boundSessionId || analysisStore.isDeleted(boundSessionId)) return
  const existing = analysisStore.getSessionCache(boundSiteKey, boundSessionId)
  const cache = createOnlineMrAnalysisSessionCache(boundSiteKey, boundSessionId)
  const currentDetail = detail.value?.session_id === boundSessionId ? detail.value : existing?.detail || null
  Object.assign(cache, {
    revision: currentDetail ? onlineMrSessionRevision(currentDetail) : existing?.revision || null,
    detail: currentDetail,
    detailLoaded: Boolean(currentDetail) || existing?.detailLoaded || false,
    activeTab: activeTab.value,
    chartTab: chartTab.value,
    startTime: startTime.value,
    endTime: endTime.value,
    downsample: downsample.value,
    bucketSeconds: bucketSeconds.value,
    businessSummary: businessSummary.value,
    businessSummaryLoaded: businessSummaryLoaded.value,
    businessRows: businessRows.value,
    businessOffsets: businessOffsets.value,
    businessHasMore: businessHasMore.value,
    businessLoaded: businessLoaded.value,
    metrics: metrics.value,
    metricOffsets: metricOffsets.value,
    metricHasMore: metricHasMore.value,
    metricLoaded: metricLoaded.value,
    switchWindows: switchWindows.value,
    switchOffsets: switchOffsets.value,
    switchHasMore: switchHasMore.value,
    switchLoaded: switchLoaded.value,
    rawFiles: rawFiles.value,
    rawFilesLoaded: rawFilesLoaded.value,
    rawTail: rawTail.value,
    rawName: rawName.value,
    rssiViewport: rssiViewport.value,
    rssiLayoutMode: rssiLayoutMode.value,
    rssiSplitRatio: rssiSplitRatio.value,
    selectedRadio: selectedRadio.value,
    pointLimit: pointLimit.value,
    showPeerRssi: showPeerRssi.value,
    showSwitchLines: showSwitchLines.value,
    showSwitchPoints: showSwitchPoints.value,
    showLocationBand: showLocationBand.value,
    cursorTime: timelineCursorTime.value,
    cursorSource: timelineCursorSource.value,
    selectedTime: selectedTime.value,
    timeRangeLocked: timeRangeLocked.value,
    selectedTimeLocked: selectedTimeLocked.value,
    immersiveMode: rssiImmersive.value,
    relatedMetricKey: relatedMetricKey.value,
    loadedAt: existing?.loadedAt || Date.now(),
  })
  analysisStore.saveSessionCache(cache)
}
function restoreSessionCache(cache: OnlineMrAnalysisSessionCache): void {
  restoringCache = true
  boundSiteKey = cache.siteKey
  boundSessionId = cache.sessionId
  detail.value = cache.detail
  activeTab.value = cache.activeTab
  chartTab.value = cache.chartTab
  startTime.value = cache.startTime
  endTime.value = cache.endTime
  downsample.value = cache.downsample
  bucketSeconds.value = cache.bucketSeconds
  businessSummary.value = cache.businessSummary
  trafficOverview.value = cache.businessSummary?.traffic_overview || null
  trafficWindowOverview.value = null
  businessSummaryLoaded.value = cache.businessSummaryLoaded
  businessRows.value = cache.businessRows
  businessOffsets.value = cache.businessOffsets
  businessHasMore.value = cache.businessHasMore
  businessLoaded.value = cache.businessLoaded
  metrics.value = cache.metrics
  metricOffsets.value = cache.metricOffsets
  metricHasMore.value = cache.metricHasMore
  metricLoaded.value = cache.metricLoaded
  switchWindows.value = cache.switchWindows
  switchOffsets.value = cache.switchOffsets
  switchHasMore.value = cache.switchHasMore
  switchLoaded.value = cache.switchLoaded
  rawFiles.value = cache.rawFiles
  rawFilesLoaded.value = cache.rawFilesLoaded
  rawTail.value = cache.rawTail
  rawName.value = cache.rawName
  railTimeline.restore({
    viewport: cache.rssiViewport,
    cursorTime: cache.cursorTime,
    cursorSource: cache.cursorSource,
    selectedTime: cache.selectedTime,
    timeRangeLocked: cache.timeRangeLocked,
    selectedTimeLocked: cache.selectedTimeLocked,
  })
  rssiLayoutMode.value = cache.rssiLayoutMode
  rssiSplitRatio.value = cache.rssiSplitRatio
  selectedRadio.value = cache.selectedRadio
  pointLimit.value = cache.pointLimit
  showPeerRssi.value = cache.showPeerRssi
  showSwitchLines.value = cache.showSwitchLines
  showSwitchPoints.value = cache.showSwitchPoints
  showLocationBand.value = cache.showLocationBand
  rssiImmersive.value = cache.immersiveMode
  relatedMetricKey.value = cache.relatedMetricKey
  void nextTick(() => { restoringCache = false })
}
function resetSessionUi(): void {
  restoringCache = true
  activeTab.value = 'session-history'
  chartTab.value = 'rssi'
  startTime.value = ''
  endTime.value = ''
  downsample.value = 'LATEST_PER_BUCKET'
  bucketSeconds.value = 1
  railTimeline.reset()
  rssiLayoutMode.value = 'compare'
  rssiSplitRatio.value = 0.5
  selectedRadio.value = null
  pointLimit.value = 600
  showPeerRssi.value = false
  showSwitchLines.value = true
  showSwitchPoints.value = true
  showLocationBand.value = true
  rssiImmersive.value = false
  relatedMetricKey.value = 'ping-quality'
  void nextTick(() => { restoringCache = false })
}
function requestCacheKey(context: RequestContext, resource: string, offset = 0): string {
  const revision = analysisStore.getSessionCache(context.siteKey, context.sessionId)?.revision || 'unversioned'
  const filters = JSON.stringify([startTime.value, endTime.value, downsample.value, bucketSeconds.value, pointLimit.value])
  return `${onlineMrAnalysisCacheKey(context.siteKey, context.sessionId)}\0${revision}\0${resource}\0${filters}\0${offset}\0${context.generation}`
}
function updateRssiViewport(viewport: MeshChartViewport): void {
  railTimeline.setViewport(viewport)
  if (chartTab.value === 'traffic') void loadTrafficWindowOverview()
  saveCurrentSessionCache()
}
function updateTimelinePointer(pointer: MeshSharedPointerChange): void {
  railTimeline.setCursor(pointer)
}
function selectTimelineTime(time: string): void {
  railTimeline.selectTime(time, true)
  saveCurrentSessionCache()
}
function locateMainLink(): void {
  if (!selectedTime.value) return
  railTimeline.focusTime(selectedTime.value, timelineTimeDomain.value)
  chartTab.value = 'rssi'
  saveCurrentSessionCache()
}
function selectTimelineSwitch(event: MeshChartEvent): void {
  selectTimelineTime(event.timestamp)
}
function resetTimelineViewport(): void {
  const domain = timelineTimeDomain.value
  railTimeline.setViewport(domain ? createFullMeshViewportFromDomain(domain, 'programmatic') : null)
  timeRangeLocked.value = false
  saveCurrentSessionCache()
}
function toggleTimeRangeLock(): void {
  if (!rssiViewport.value) return
  timeRangeLocked.value = !timeRangeLocked.value
  saveCurrentSessionCache()
}
function toggleSelectedTimeLock(): void {
  if (!selectedTime.value) return
  selectedTimeLocked.value = !selectedTimeLocked.value
  saveCurrentSessionCache()
}
function unlockSelectedTime(): void {
  if (!selectedTime.value) return
  selectedTimeLocked.value = false
  saveCurrentSessionCache()
}

function handleTimelineEscape(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !selectedTimeLocked.value) return
  unlockSelectedTime()
}
function toggleImmersive(): void {
  rssiImmersive.value = !rssiImmersive.value
  saveCurrentSessionCache()
}
function moveToSwitch(direction: -1 | 1): void {
  const viewport = rssiViewport.value
  const events = [...timelineSwitchWindows.value.realtime, ...timelineSwitchWindows.value.history]
    .filter((item) => Boolean(
      item.event_time
      && (!viewport || (item.event_time >= viewport.start_time && item.event_time <= viewport.end_time)),
    ))
    .sort((left, right) => left.event_time!.localeCompare(right.event_time!))
  if (!events.length) return
  const current = selectedTime.value || (direction > 0 ? '' : '9999')
  const ordered = direction > 0 ? events : [...events].reverse()
  const target = ordered.find((event) => direction > 0 ? event.event_time! > current : event.event_time! < current)
    || ordered[0]
  if (target.event_time) selectTimelineTime(target.event_time)
}
function reloadTimelineForPointLimit(): void {
  metricLoaded.value['rail-timeline'] = false
  delete metrics.value['rail-timeline']
  saveCurrentSessionCache()
  void loadRailTimeline(nextRequestContext(), true)
}
function clearAnalysisData(): void {
  businessSummary.value = null
  trafficOverview.value = null
  trafficWindowOverview.value = null
  businessSummaryLoaded.value = false
  businessRows.value = emptyBusinessState()
  businessOffsets.value = emptyOffsetState()
  businessHasMore.value = emptyMoreState()
  businessLoaded.value = emptyLoadedState()
  metrics.value = {}
  metricOffsets.value = {}
  metricHasMore.value = {}
  metricLoaded.value = {}
  switchWindows.value = { history: [], realtime: [] }
  switchOffsets.value = { history: 0, realtime: 0 }
  switchHasMore.value = { history: false, realtime: false }
  switchLoaded.value = { history: false, realtime: false }
  railTimeline.reset()
  analysisError.value = ''
}
function clearSessionData(): void {
  clearAnalysisData()
  rawFiles.value = []
  rawFilesLoaded.value = false
  rawTail.value = []
  rawName.value = ''
}
function nextRequestContext(): RequestContext {
  requestController?.abort()
  requestController = new AbortController()
  requestGeneration += 1
  return { siteKey: currentSiteKey(), sessionId: sessionId.value || '', generation: requestGeneration, signal: requestController.signal }
}
function currentRequestContext(): RequestContext {
  if (!requestController) requestController = new AbortController()
  return { siteKey: currentSiteKey(), sessionId: sessionId.value || '', generation: requestGeneration, signal: requestController.signal }
}
function isCurrent(context: RequestContext): boolean {
  return viewActive
    && context.siteKey === currentSiteKey()
    && context.generation === requestGeneration
    && context.sessionId === sessionId.value
    && !analysisStore.isDeleted(context.sessionId)
    && !context.signal.aborted
}
function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}
function currentSiteKey(): string {
  return typeof route.query.site_id === 'string' ? route.query.site_id : '__current_site__'
}
function isOnlineMrRoute(): boolean {
  return route.name == null || route.name === 'online-mr-analysis'
}
function disposeForSiteSwitch(): void {
  viewActive = false
  viewGeneration += 1
  requestController?.abort()
  analysisStore.dispose()
  detailLoading.value = false
  clearSessionData()
  openingSessionId.value = null
  deletingSessionId.value = null
  pendingDeleteTarget.value = null
  deleteRequests.clear()
  boundSiteKey = ''
  boundSessionId = ''
  stopPolling()
}
function requestedRouteSessionId(): string | null {
  return typeof route.query.session_id === 'string' && route.query.session_id ? route.query.session_id : null
}
async function syncRouteSessionId(targetSessionId: string | null): Promise<void> {
  const current = requestedRouteSessionId()
  if (current === targetSessionId) return
  const query = { ...route.query }
  if (targetSessionId) query.session_id = targetSessionId
  else delete query.session_id
  await router.replace({ query })
}

async function loadSessions(options: {
  preferredSessionId?: string | null
  selectFirstWhenEmpty?: boolean
  preserveDetail?: boolean
  force?: boolean
} = {}): Promise<boolean> {
  error.value = ''
  try {
    const previousSessionId = sessionId.value
    const result = await analysisStore.refreshSessions({
      siteKey: currentSiteKey(),
      requestedSessionId: requestedRouteSessionId(),
      preferredSessionId: options.preferredSessionId,
      selectFirstWhenEmpty: options.selectFirstWhenEmpty ?? previousSessionId == null,
      force: options.force,
    })
    if (!result.applied) return false
    await syncRouteSessionId(result.selectedSessionId)
    if (!result.selectedSessionId) {
      detail.value = null
      detailLoading.value = false
      clearSessionData()
    } else if (result.selectionChanged || !detail.value || !options.preserveDetail) {
      await loadAnalysis()
    }
    return true
  } catch (cause) {
    if (!isAbort(cause)) error.value = message(cause, 'Online MR 会话列表加载失败')
    return false
  }
}
async function refreshCurrentSession(): Promise<void> {
  const targetSessionId = sessionId.value
  if (targetSessionId) {
    analysisStore.invalidateSession(currentSiteKey(), targetSessionId)
    boundSiteKey = currentSiteKey()
    boundSessionId = targetSessionId
    detail.value = null
    clearSessionData()
  }
  await loadSessions({
    preferredSessionId: targetSessionId,
    selectFirstWhenEmpty: true,
    force: true,
  })
}
async function loadAnalysis(options: { forceDetail?: boolean; reset?: boolean } = {}): Promise<void> {
  if (!sessionId.value) return
  const context = nextRequestContext()
  const deletingTaskActive = taskActive.value && task.value?.action === 'online_mr_session_delete'
  if (!deletingTaskActive) {
    stopPolling()
    task.value = null
  }
  const cached = options.reset ? null : analysisStore.getSessionCache(context.siteKey, context.sessionId)
  if (cached) restoreSessionCache(cached)
  if (cached?.detailLoaded) {
    detailLoading.value = false
    error.value = ''
    if (cached.detail) {
      await ensureParsedDatabaseCurrent(context)
      await loadActiveTab(activeTab.value, context)
    }
    return
  }
  if (!cached && boundSessionId && boundSessionId !== context.sessionId) resetSessionUi()
  boundSiteKey = context.siteKey
  boundSessionId = context.sessionId
  detail.value = null
  if (!cached) clearSessionData()
  detailLoading.value = true
  error.value = ''
  try {
    const nextDetail = await analysisStore.loadSelectedSession(context.siteKey, options.forceDetail)
    if (!isCurrent(context)) return
    if (nextDetail) {
      await ensureParsedDatabaseCurrent(context)
      await loadActiveTab(activeTab.value, context)
      saveCurrentSessionCache()
    }
  } catch (cause) {
    if (!isAbort(cause) && isCurrent(context)) error.value = message(cause, 'Online MR 会话详情加载失败')
  } finally {
    if (isCurrent(context)) detailLoading.value = false
  }
}

async function ensureParsedDatabaseCurrent(context = currentRequestContext()): Promise<void> {
  const selected = detail.value
  if (!selected || !isCurrent(context) || !isFeatureEnabled('web.online_mr_parse')) return
  const sessionState = String(selected.status || '').toUpperCase()
  if (['CREATED', 'CONNECTING', 'INITIALIZING', 'COLLECTING', 'RECONNECTING', 'STARTING', 'RUNNING', 'STOPPING', 'FINALIZING', 'PACKAGING'].includes(sessionState)) return
  const summary = selected.database_summary
  if (summary.status === 'ready' && !summary.missing_capabilities.length && summary.action !== 'ensure_current') {
    upgradeResult.value = null
    return
  }
  try {
    const result = await analysisStore.runDeduped(
      `${onlineMrAnalysisCacheKey(context.siteKey, context.sessionId)}\0ensure-current`,
      () => ensureOnlineMrParsedDatabaseCurrent(context.sessionId),
    )
    if (!isCurrent(context)) return
    upgradeResult.value = result
    if (result.status === 'UPGRADING' && result.task) {
      rememberTask(result.task)
      poll()
      return
    }
    if (result.status === 'FAILED' || result.status === 'RAW_DATA_MISSING') {
      const noticeKey = `${context.siteKey}:${context.sessionId}:${result.status}:${result.message}`
      if (analysisStore.markUpgradeNotice(noticeKey)) {
        ElMessage.warning(result.message || '解析库版本较旧，无法自动升级。')
      }
    }
  } catch (cause) {
    if (!isAbort(cause) && isCurrent(context)) analysisError.value = message(cause, '解析数据库自动升级检查失败')
  }
}
async function loadBusinessSummary(context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || businessSummaryLoaded.value) return
  const value = await analysisStore.runDeduped(
    requestCacheKey(context, 'business-summary'),
    () => getOnlineMrBusinessSummary(context.sessionId),
  )
  if (isCurrent(context)) {
    businessSummary.value = value
    trafficOverview.value = value.traffic_overview || null
    businessSummaryLoaded.value = true
    saveCurrentSessionCache()
  }
}
async function loadTrafficWindowOverview(context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context)) return
  const viewport = rssiViewport.value
  const key = `${requestCacheKey(context, 'traffic-overview-window')}\0${viewport?.start_time || ''}\0${viewport?.end_time || ''}`
  const value = await analysisStore.runDeduped(
    key,
    () => getOnlineMrTrafficOverview(context.sessionId, {
      startTime: viewport?.start_time || startTime.value,
      endTime: viewport?.end_time || endTime.value,
      signal: context.signal,
    }),
  )
  if (isCurrent(context)) trafficWindowOverview.value = value
}
async function loadBusinessTable(table: OnlineMrBusinessTable, append = false, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || (!append && businessLoaded.value[table])) return
  if (append && (!businessLoaded.value[table] || !businessHasMore.value[table])) return
  const offset = append ? businessOffsets.value[table] : 0
  const page = await analysisStore.runDeduped(
    requestCacheKey(context, `business-table:${table}`, offset),
    () => queryOnlineMrBusinessTable(context.sessionId, table, { startTime: startTime.value, endTime: endTime.value, limit: businessLimit, offset, signal: context.signal }),
  )
  if (!isCurrent(context)) return
  if ((!append && businessLoaded.value[table]) || (append && businessOffsets.value[table] !== offset)) return
  businessRows.value[table] = append ? [...businessRows.value[table], ...page.rows] : page.rows
  businessOffsets.value[table] = page.next_offset
  businessHasMore.value[table] = page.has_more
  businessLoaded.value[table] = true
  saveCurrentSessionCache()
}
async function loadMetric(name: string, types: string[], append = false, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || (!append && metricLoaded.value[name])) return
  if (append && (!metricLoaded.value[name] || !metricHasMore.value[name])) return
  const offset = append ? metricOffsets.value[name] || 0 : 0
  const page = await analysisStore.runDeduped(
    requestCacheKey(context, `metric:${name}:${types.join(',')}`, offset),
    () => queryOnlineMrMetrics(context.sessionId, types, { startTime: startTime.value, endTime: endTime.value, limit: metricLimit, offset, downsample: downsample.value, bucketSeconds: bucketSeconds.value, signal: context.signal }),
  )
  if (!isCurrent(context)) return
  if ((!append && metricLoaded.value[name]) || (append && (metricOffsets.value[name] || 0) !== offset)) return
  metrics.value[name] = append ? appendMetricPage(metrics.value[name] || [], page.series) : page.series
  metricOffsets.value[name] = page.next_offset
  metricHasMore.value[name] = page.has_more
  metricLoaded.value[name] = true
  saveCurrentSessionCache()
}
async function loadRailTimeline(context = currentRequestContext(), force = false): Promise<void> {
  const cacheKey = 'rail-timeline'
  if (!context.sessionId || !isCurrent(context) || (!force && metricLoaded.value[cacheKey])) return
  const first = businessSummary.value?.first_sample_time ? Date.parse(businessSummary.value.first_sample_time.replace(' ', 'T')) : Number.NaN
  const last = businessSummary.value?.last_sample_time ? Date.parse(businessSummary.value.last_sample_time.replace(' ', 'T')) : Number.NaN
  const durationSeconds = Number.isFinite(first) && Number.isFinite(last) ? Math.max(1, (last - first) / 1_000) : pointLimit.value
  const timelineBucketSeconds = Math.max(1, Math.ceil(durationSeconds / Math.max(120, pointLimit.value)))
  const rows = await analysisStore.runDeduped(
    requestCacheKey(context, `metrics:${cacheKey}:${timelineBucketSeconds}`),
    () => queryOnlineMrTimelineMetrics(context.sessionId, [...timelineMetricTypes], {
      startTime: startTime.value,
      endTime: endTime.value,
      limit: 10_000,
      downsample: 'MIN_MAX',
      bucketSeconds: timelineBucketSeconds,
      signal: context.signal,
    }),
  )
  if (!isCurrent(context)) return
  metrics.value[cacheKey] = rows
  metricLoaded.value[cacheKey] = true
  metricOffsets.value[cacheKey] = rows.reduce((count, series) => count + series.points.length, 0)
  metricHasMore.value[cacheKey] = false
  saveCurrentSessionCache()
}
async function loadSwitchWindows(source: OnlineMrSwitchRssiSource, append = false, context = currentRequestContext()): Promise<void> {
  if (!context.sessionId || !isCurrent(context) || (!append && switchLoaded.value[source])) return
  if (append && (!switchLoaded.value[source] || !switchHasMore.value[source])) return
  const offset = append ? switchOffsets.value[source] : 0
  const page = await analysisStore.runDeduped(
    requestCacheKey(context, `switch-rssi:${source}`, offset),
    () => queryOnlineMrSwitchRssiWindows(context.sessionId, source, { startTime: startTime.value, endTime: endTime.value, limit: switchLimit, offset, signal: context.signal }),
  )
  if (!isCurrent(context)) return
  if ((!append && switchLoaded.value[source]) || (append && switchOffsets.value[source] !== offset)) return
  switchWindows.value[source] = append ? [...switchWindows.value[source], ...page.items] : page.items
  switchOffsets.value[source] = offset + page.limit
  switchHasMore.value[source] = page.has_more
  switchLoaded.value[source] = true
  saveCurrentSessionCache()
}
async function loadRaw(context = currentRequestContext()): Promise<void> {
  if (!rawFilesLoaded.value) {
    const rows = await analysisStore.runDeduped(
      requestCacheKey(context, 'raw-files'),
      () => listOnlineMrRawFiles(context.sessionId, context.signal),
    )
    if (isCurrent(context)) {
      rawFiles.value = rows
      rawFilesLoaded.value = true
      saveCurrentSessionCache()
    }
  }
}
async function loadCollectorLog(context = currentRequestContext()): Promise<void> {
  const result = await getOnlineMrRawTail(context.sessionId, 'collector_output', 250, context.signal)
  if (isCurrent(context)) {
    rawName.value = 'collector_output'
    rawTail.value = result.lines
    saveCurrentSessionCache()
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
        await loadBusinessSummary(context)
      if (selectedChart.value.switchSource) await loadSwitchWindows(selectedChart.value.switchSource, false, context)
      else await Promise.all([
        loadRailTimeline(context),
        loadSwitchWindows('history', false, context),
        loadSwitchWindows('realtime', false, context),
        ...(selectedChart.value.key === 'traffic' ? [loadTrafficWindowOverview(context)] : []),
      ])
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
    if (isCurrent(context)) {
      rawTail.value = result.lines
      saveCurrentSessionCache()
    }
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
  if (row.session_id === deletingSessionId.value || row.session_id === sessionId.value) return
  saveCurrentSessionCache()
  analysisStore.selectSession(row.session_id)
  void syncRouteSessionId(row.session_id)
  void loadAnalysis()
}
function selectSessionId(value: string): void {
  if (!value || value === deletingSessionId.value || value === sessionId.value || !analysisStore.sessionById(value)) return
  saveCurrentSessionCache()
  analysisStore.selectSession(value)
  void syncRouteSessionId(value)
  void loadAnalysis()
}
async function openSessionLocation(row?: OnlineMrSessionSummary | OnlineMrSessionDetail): Promise<void> {
  const selected = row || detail.value
  if (!selected || deletingSessionId.value === selected.session_id || openingSessionId.value) return
  const bridge = window.netconsoleDesktop?.openOnlineMrSessionLocation
  if (!bridge || !desktopLocationAvailable.value) {
    ElMessage.warning('该功能仅在 NetConsole Electron 桌面端可用。')
    return
  }
  const targetSessionId = selected.session_id
  openingSessionId.value = targetSessionId
  try {
    const result = await bridge(targetSessionId)
    if (!result.success) {
      const fallback = result.availability === 'MISSING'
        ? '该会话的本地文件已不存在。'
        : result.availability === 'INVALID'
          ? '该会话的本地路径无效或不可访问。'
          : '打开会话位置失败'
      const notice = `${selected.device_name || selected.mr_name || targetSessionId}：${result.error || fallback}`
      if (result.availability === 'MISSING') ElMessage.warning(notice)
      else ElMessage.error(notice)
    }
  } catch (cause) {
    ElMessage.error(`${selected.device_name || selected.mr_name || targetSessionId}：${message(cause, '打开会话位置失败')}`)
  } finally {
    if (openingSessionId.value === targetSessionId) openingSessionId.value = null
  }
}
async function startParse(forceReparse: boolean): Promise<void> {
  if (!detail.value || !canParse.value || sessionActionsDisabled.value || reportBusy.value || parseBusy.value) return
  if (forceReparse && !await confirm({ type: 'WARNING', title: '强制重新解析', message: '强制解析会重建当前会话 parsed 结果；原始日志不会删除。确认继续？', confirmText: '重新解析' })) return
  parseSubmitting.value = true
  error.value = ''
  try {
    analysisStore.invalidateSessionAnalysis(currentSiteKey(), detail.value.session_id)
    clearAnalysisData()
    saveCurrentSessionCache()
    rememberTask(await parseOnlineMrSession(detail.value.session_id, forceReparse))
    if (task.value?.status === 'COMPLETED' && sessionId.value) {
      analysisStore.invalidateSession(currentSiteKey(), sessionId.value)
      clearSessionData()
      await loadAnalysis({ forceDetail: true, reset: true })
    } else {
      poll()
    }
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
function sessionIntegrityLabel(selected: OnlineMrSessionSummary | OnlineMrSessionDetail): string {
  if ('data_integrity' in selected && selected.data_integrity) return selected.data_integrity
  if ('finalization_complete' in selected && selected.finalization_complete != null) return selected.finalization_complete ? 'complete' : 'partial'
  return 'unknown'
}
async function finishDeleteTask(updated: RailTransitTask): Promise<void> {
  const target = pendingDeleteTarget.value
  pendingDeleteTarget.value = null
  const targetSessionId = target?.sessionId || deletingSessionId.value
  if (!targetSessionId) return
  try {
    if (updated.status === 'FAILED' || !taskResultBoolean(updated, 'session_deleted')) {
      ElMessage.error(updated.error_message || updated.message || '会话删除失败，原会话已保留。')
      return
    }
    const issues = [...taskResultStrings(updated, 'failed_items'), ...taskResultStrings(updated, 'warnings')]
    const deletingCurrent = sessionId.value === targetSessionId
    analysisStore.removeSessionLocally(targetSessionId)
    if (deletingCurrent) {
      requestController?.abort()
      detailLoading.value = false
      detail.value = null
      clearSessionData()
      const adjacent = target?.nextSessionId && analysisStore.sessionById(target.nextSessionId)
        ? target.nextSessionId
        : target?.previousSessionId && analysisStore.sessionById(target.previousSessionId)
          ? target.previousSessionId
          : null
      analysisStore.selectSession(adjacent)
      await syncRouteSessionId(adjacent)
      if (adjacent) await loadAnalysis()
    }
    const refreshed = await loadSessions({ preserveDetail: true, selectFirstWhenEmpty: false, force: true })
    if (!refreshed) {
      ElMessage.warning('会话已删除，但会话列表刷新失败，可手动刷新。')
    } else if (updated.status === 'COMPLETED' && issues.length === 0) {
      ElMessage.success('会话及其受管本地数据已删除。')
    } else {
      ElMessage.warning(`会话主体已删除，部分关联项处理失败：${issues.join('；') || updated.message || '请在任务中心查看详情。'}`)
    }
  } finally {
    deleteRequests.delete(targetSessionId)
    if (deletingSessionId.value === targetSessionId) deletingSessionId.value = null
  }
}
async function deleteSession(targetSessionId: string): Promise<void> {
  if (!targetSessionId || deleteRequests.size > 0 || deletingSessionId.value) return
  const selected = analysisStore.sessionById(targetSessionId) || (detail.value?.session_id === targetSessionId ? detail.value : null)
  if (!selected || !isFeatureEnabled('web.online_mr_session_delete')) return
  const blockReason = onlineMrSessionDeleteBlockReason(selected)
  if (blockReason) {
    ElMessage.warning(`${selected.device_name || selected.mr_name || targetSessionId}：${blockReason}`)
    return
  }
  if (parseBusy.value || reportBusy.value) return
  deleteRequests.add(targetSessionId)
  const selectedIndex = sessions.value.findIndex((item) => item.session_id === targetSessionId)
  const previousSessionId = selectedIndex > 0 ? sessions.value[selectedIndex - 1]?.session_id || null : null
  const nextSessionId = selectedIndex >= 0 ? sessions.value[selectedIndex + 1]?.session_id || null : null
  const duration = selected.duration_minutes == null ? '无数据' : `${formatNumber(selected.duration_minutes, 3)} min`
  let submitted = false
  try {
    const accepted = await confirm({
      type: 'DESTRUCTIVE',
      title: '删除 Online MR 会话',
      message: [
        `MR：${selected.device_name || selected.mr_name || '无数据'}`,
        `会话 ID：${targetSessionId}`,
        `开始时间：${selected.started_at || '无数据'}`,
        `会话状态：${selected.status || '无数据'}`,
        `采集时长：${duration}`,
        `数据完整性：${sessionIntegrityLabel(selected)}`,
        `原始日志：${selected.has_raw_data ? '有' : '无'}；归档文件：${selected.has_package ? '有' : '无'}`,
        '',
        '删除后将移除该会话的解析数据、缓存、报告记录及 NetConsole 管理的本地会话文件，此操作不可撤销。',
      ].join('\n'),
      confirmText: '确认删除',
    })
    if (!accepted) return
    deletingSessionId.value = targetSessionId
    error.value = ''
    const submittedTask = await deleteOnlineMrSession(targetSessionId)
    submitted = true
    pendingDeleteTarget.value = { sessionId: targetSessionId, previousSessionId, nextSessionId }
    rememberTask(submittedTask)
    if (terminalStates.has(submittedTask.status)) await finishDeleteTask(submittedTask)
    else poll(viewGeneration)
  } catch (cause) {
    error.value = message(cause, 'Online MR 会话删除启动失败')
  } finally {
    if (!submitted) {
      deleteRequests.delete(targetSessionId)
      if (deletingSessionId.value === targetSessionId) deletingSessionId.value = null
    }
  }
}
async function deleteCurrentSession(row?: OnlineMrSessionSummary | OnlineMrSessionDetail): Promise<void> {
  const selected = row || detail.value
  if (selected) await deleteSession(selected.session_id)
}
async function recoverTask(): Promise<void> {
  try {
    const saved = localStorage.getItem('netconsole.online-mr-analysis.last-task') || ''
    const rows = await recoverRailTransitTasks()
    const recovered = rows.find((item) => item.task_id === saved)
      || rows.find((item) => ['online_mr_parse', 'online_mr_report', 'online_mr_session_delete'].includes(item.action))
      || null
    if (!task.value || terminalStates.has(task.value.status) || recovered?.task_id === task.value.task_id) {
      rememberTask(recovered)
    }
    if (task.value?.action === 'online_mr_session_delete') {
      const deletingSession = String(task.value.result_summary.session_id || '')
      const index = sessions.value.findIndex((item) => item.session_id === deletingSession)
      deletingSessionId.value = deletingSession || null
      if (deletingSession) deleteRequests.add(deletingSession)
      pendingDeleteTarget.value = deletingSession ? {
        sessionId: deletingSession,
        previousSessionId: index > 0 ? sessions.value[index - 1]?.session_id || null : null,
        nextSessionId: index >= 0 ? sessions.value[index + 1]?.session_id || null : null,
      } : null
      if (terminalStates.has(task.value.status)) {
        await finishDeleteTask(task.value)
        return
      }
    }
    poll()
  } catch (cause) {
    error.value = message(cause, '任务恢复失败')
  }
}
function changeTab(tab: string): void {
  activeTab.value = tab
  saveCurrentSessionCache()
  const context = currentRequestContext()
  void loadActiveTab(tab, context)
}
function changeChartTab(tab: string): void {
  chartTab.value = tab
  saveCurrentSessionCache()
  const context = currentRequestContext()
  const definition = chartDefinitions.find((item) => item.key === tab)
  if (definition?.switchSource) void loadSwitchWindows(definition.switchSource, false, context)
  else void Promise.all([
    loadRailTimeline(context),
    loadSwitchWindows('history', false, context),
    loadSwitchWindows('realtime', false, context),
    ...(definition?.key === 'traffic' ? [loadTrafficWindowOverview(context)] : []),
  ])
}
function loadMoreChart(): void {
  const definition = selectedChart.value
  if (definition.key === 'rssi') {
    return
  } else if (definition.switchSource) void loadSwitchWindows(definition.switchSource, true)
}
function loadMoreActiveTab(): void {
  if (currentBusinessTable.value) void loadBusinessTable(currentBusinessTable.value, true)
  else if (activeTab.value === 'charts') loadMoreChart()
}
watch([startTime, endTime, downsample, bucketSeconds], (current, previous) => {
  if (restoringCache) return
  const timeChanged = current[0] !== previous[0] || current[1] !== previous[1]
  const chartSettingsChanged = current[2] !== previous[2] || current[3] !== previous[3]
  const needsReload = (timeChanged && Boolean(currentBusinessTable.value || activeTab.value === 'charts'))
    || (chartSettingsChanged && activeTab.value === 'charts')
  if (!needsReload) return
  clearAnalysisData()
  const context = nextRequestContext()
  void loadActiveTab(activeTab.value, context)
})
watch(() => route.query.site_id, () => {
  if (!viewActive || !isOnlineMrRoute()) return
  viewGeneration += 1
  stopPolling()
  requestController?.abort()
  analysisStore.resetForSite(currentSiteKey())
  detail.value = null
  detailLoading.value = false
  businessSummary.value = null
  clearSessionData()
  nextRequestContext()
  openingSessionId.value = null
  deletingSessionId.value = null
  pendingDeleteTarget.value = null
  deleteRequests.clear()
  boundSiteKey = ''
  boundSessionId = ''
  void loadSessions({ selectFirstWhenEmpty: true })
})
watch(() => route.query.session_id, (next) => {
  if (!viewActive || !isOnlineMrRoute()) return
  const target = typeof next === 'string' && next ? next : null
  if (target === sessionId.value) return
  if (target && analysisStore.sessionById(target) && !analysisStore.isDeleted(target)) {
    saveCurrentSessionCache()
    analysisStore.selectSession(target)
    void loadAnalysis()
    return
  }
  analysisStore.clearSelectedSession()
  detail.value = null
  detailLoading.value = false
  clearSessionData()
  if (target) void syncRouteSessionId(null)
})

onMounted(async () => {
  viewActive = true
  window.addEventListener(BEFORE_SITE_SWITCH_EVENT, disposeForSiteSwitch)
  window.addEventListener('keydown', handleTimelineEscape, true)
  await loadSessions({ selectFirstWhenEmpty: true })
  await recoverTask()
  initialized = true
})
onActivated(() => {
  viewActive = true
  chartActive.value = true
  if (initialized && isOnlineMrRoute()) {
    if (!analysisStore.sessionsLoaded || analysisStore.siteKey !== currentSiteKey()) {
      void loadSessions({ selectFirstWhenEmpty: true })
      return
    }
    const target = requestedRouteSessionId()
    if (target && target !== sessionId.value && analysisStore.sessionById(target)) {
      analysisStore.selectSession(target)
    }
    if (sessionId.value && (boundSessionId !== sessionId.value || boundSiteKey !== currentSiteKey())) {
      void loadAnalysis()
    }
  }
  if (task.value && !terminalStates.has(task.value.status)) poll()
})
onDeactivated(() => {
  saveCurrentSessionCache()
  viewActive = false
  chartActive.value = false
  viewGeneration += 1
  requestController?.abort()
  detailLoading.value = false
  openingSessionId.value = null
  deletingSessionId.value = null
  stopPolling()
})
onBeforeUnmount(() => {
  saveCurrentSessionCache()
  viewActive = false
  chartActive.value = false
  viewGeneration += 1
  requestController?.abort()
  detailLoading.value = false
  openingSessionId.value = null
  deletingSessionId.value = null
  stopPolling()
  window.removeEventListener(BEFORE_SITE_SWITCH_EVENT, disposeForSiteSwitch)
  window.removeEventListener('keydown', handleTimelineEscape, true)
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
        <p>会话、原始日志与采集记录不依赖 parsed 数据库；业务表按解析结果结构化展示，主链路 RSSI 复用 MESH 动态图。</p>
      </div>
      <div class="actions">
        <el-select :model-value="sessionId || ''" class="session-selector" filterable placeholder="选择 Online MR 会话" @change="selectSessionId">
          <el-option v-for="item in sessions" :key="item.session_id" :label="`${item.device_name || item.mr_name} · ${item.status} · ${item.started_at || item.session_id}`" :value="item.session_id" />
        </el-select>
        <el-button data-testid="refresh-session" :icon="Refresh" :loading="loading" :disabled="deleteBusy" @click="refreshCurrentSession">刷新</el-button>
        <el-button data-testid="parse-session" :disabled="!canParse || parsedStatus === 'parsing' || sessionActionsDisabled || reportBusy || parseBusy" :loading="parseBusy" @click="startParse(false)">{{ parsedStatus === 'missing' ? '解析当前会话' : '重新解析' }}</el-button>
        <el-button data-testid="force-reparse-session" :disabled="!canParse || parsedStatus === 'parsing' || sessionActionsDisabled || reportBusy || parseBusy" :loading="parseBusy" @click="startParse(true)">强制重新解析</el-button>
        <el-button data-testid="open-session-location" :icon="FolderOpened" :loading="openingSessionId === sessionId" :disabled="sessionActionsDisabled || Boolean(openingSessionId) || !desktopLocationAvailable" :title="openLocationTitle" @click="openSessionLocation()">打开本地目录</el-button>
        <el-button data-testid="generate-report" type="primary" :icon="Download" :loading="reportBusy" :disabled="reportDisabled || sessionActionsDisabled || sessionResourceBusy" :title="reportDisabled ? parsedMessage : ''" @click="startReport">生成 XLSX 报告</el-button>
        <el-button data-testid="delete-session" type="danger" plain :icon="Delete" :loading="deletingSessionId === sessionId" :disabled="sessionActionsDisabled || sessionResourceBusy || Boolean(selectedDeleteBlockReason) || !isFeatureEnabled('web.online_mr_session_delete')" :title="selectedDeleteBlockReason" @click="deleteCurrentSession()">删除</el-button>
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

      <div class="analysis-status-row">
        <el-popover placement="bottom-end" trigger="hover" :width="360">
          <dl class="parser-status-details">
            <dt>解析结果</dt><dd>{{ parsedStatusLabel }}</dd>
            <dt>解析数据库</dt><dd>{{ detail.database_summary.compatible === false ? '不可用' : parsedReadable ? '可用' : '待处理' }}</dd>
            <dt>说明</dt><dd>{{ parsedMessage }}</dd>
            <dt v-if="detail.database_summary.parser_version">Parser</dt><dd v-if="detail.database_summary.parser_version">{{ detail.database_summary.parser_version }}</dd>
            <dt v-if="detail.database_summary.missing_capabilities.length">缺少能力</dt><dd v-if="detail.database_summary.missing_capabilities.length">{{ detail.database_summary.missing_capabilities.join('、') }}</dd>
          </dl>
          <template #reference>
            <el-tag class="parser-status-tag" :type="parsedAlertType" effect="plain" round :title="parsedMessage">{{ parsedStatusLabel }}</el-tag>
          </template>
        </el-popover>
      </div>

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
          <NcDataTable table-id="online-mr-analysis-session-history" route-key="/rail-transit/online-mr-analysis" :data="sessions" :columns="sessionColumns" row-key="session_id" :current-row-key="sessionId || ''" highlight-current-row border :height="tableHeight" empty-text="暂无会话" @row-click="selectSession">
            <template #cell-actions="{ row }">
              <el-button :data-testid="`row-open-session-location-${row.session_id}`" link type="primary" :icon="FolderOpened" :loading="openingSessionId === row.session_id" :disabled="Boolean(openingSessionId) || deletingSessionId === row.session_id || !desktopLocationAvailable" :title="openLocationTitle" @click.stop="openSessionLocation(row)">打开本地目录</el-button>
              <el-button :data-testid="`row-delete-session-${row.session_id}`" link type="danger" :icon="Delete" :loading="deletingSessionId === row.session_id" :disabled="sessionResourceBusy || openingSessionId === row.session_id || Boolean(onlineMrSessionDeleteBlockReason(row)) || !isFeatureEnabled('web.online_mr_session_delete')" :title="onlineMrSessionDeleteBlockReason(row)" @click.stop="deleteSession(row.session_id)">删除</el-button>
            </template>
          </NcDataTable>
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
          <div class="timeline-workbench" :class="{ 'is-immersive': rssiImmersive }">
            <div class="timeline-toolbar">
              <el-radio-group v-model="rssiLayoutMode" size="small" @change="saveCurrentSessionCache">
                <el-radio-button value="compare">对比</el-radio-button>
                <el-radio-button value="active-focus">主链</el-radio-button>
                <el-radio-button value="trackside-focus">轨旁</el-radio-button>
              </el-radio-group>
              <el-select v-model="selectedRadio" clearable placeholder="全部 Radio" style="width:132px" @change="saveCurrentSessionCache">
                <el-option v-for="radio in availableTimelineRadios" :key="radio" :label="`Radio ${radio}`" :value="radio" />
              </el-select>
              <el-select v-model="pointLimit" style="width:132px" @change="reloadTimelineForPointLimit">
                <el-option label="目标 300 点" :value="300" />
                <el-option label="目标 600 点" :value="600" />
                <el-option label="目标 1200 点" :value="1200" />
                <el-option label="目标 2000 点" :value="2000" />
              </el-select>
              <el-checkbox v-model="showPeerRssi" @change="saveCurrentSessionCache">显示 Peer RSSI</el-checkbox>
              <el-button :icon="showSwitchLines ? View : Hide" @click="showSwitchLines = !showSwitchLines; saveCurrentSessionCache()">切换时刻线</el-button>
              <el-button :icon="showSwitchPoints ? View : Hide" @click="showSwitchPoints = !showSwitchPoints; saveCurrentSessionCache()">切换节点</el-button>
              <el-button :icon="showLocationBand ? View : Hide" @click="showLocationBand = !showLocationBand; saveCurrentSessionCache()">站点/区间</el-button>
              <el-button @click="resetTimelineViewport">重置视图</el-button>
              <el-button :icon="timeRangeLocked ? Unlock : Lock" :type="timeRangeLocked ? 'primary' : undefined" :disabled="!rssiViewport" @click="toggleTimeRangeLock">
                {{ timeRangeLocked ? '解除范围锁定' : '锁定当前范围' }}
              </el-button>
              <el-button v-if="selectedTime" data-testid="selected-time-lock" :icon="selectedTimeLocked ? Unlock : Lock" :type="selectedTimeLocked ? 'primary' : undefined" @click="toggleSelectedTimeLock">
                {{ selectedTimeLocked ? '解除时刻锁定' : '锁定分析时刻' }}
              </el-button>
              <el-button v-if="selectedTime && chartTab !== 'rssi'" size="small" @click="locateMainLink">定位主链路</el-button>
              <el-button data-testid="previous-timeline-switch" :icon="ArrowLeft" title="前一切换" @click="moveToSwitch(-1)" />
              <el-button data-testid="next-timeline-switch" :icon="ArrowRight" title="后一切换" @click="moveToSwitch(1)" />
              <el-button v-if="chartHasMore" size="small" @click="loadMoreChart">加载更多数据</el-button>
              <el-button data-testid="toggle-immersive" :icon="FullScreen" :type="rssiImmersive ? 'primary' : undefined" @click="toggleImmersive">
                {{ rssiImmersive ? '退出沉浸' : '沉浸式对比' }}
              </el-button>
            </div>

            <el-tabs :model-value="chartTab" type="card" @tab-change="changeChartTab">
              <el-tab-pane v-for="item in chartDefinitions" :key="item.key" :name="item.key" :label="item.title">
                <template v-if="chartTab === item.key">
                  <div class="timeline-analysis-layout">
                    <OnlineMrAnalysisInfoPanel
                      :sections="analysisInfoSections"
                      :locked="selectedTimeLocked"
                      :parser-label="parsedStatusLabel"
                      :parser-message="upgradeResult?.message || detail?.database_summary.upgrade_message || parsedMessage"
                      :parser-tone="parserPanelTone"
                      @unlock="unlockSelectedTime"
                    />
                    <main :class="item.key === 'rssi' ? 'timeline-chart-stack' : 'timeline-chart-pane'">
                      <template v-if="item.key === 'rssi'">
                      <OnlineMrRssiChart
                        class="rssi-pair-panel"
                        :main-series="timelineMainSeries"
                        :trackside-series="timelineTracksideSeries"
                        :history-events="timelineSwitchWindows.history"
                        :realtime-events="timelineSwitchWindows.realtime"
                        :active="chartActive && activeTab === 'charts'"
                        :viewport="rssiViewport"
                        :cursor-time="timelineCursorTime"
                        :cursor-source="timelineCursorSource"
                        :selected-time="selectedTime"
                        :layout-mode="rssiLayoutMode"
                        :split-ratio="rssiSplitRatio"
                        :workspace-height="timelineWorkspaceHeight"
                        :radio="selectedRadio"
                        :show-peer="showPeerRssi"
                        :show-switch-lines="showSwitchLines"
                        :show-switch-points="showSwitchPoints"
                        :show-location-band="showLocationBand"
                        @update:viewport="updateRssiViewport"
                        @update:split-ratio="rssiSplitRatio = $event; saveCurrentSessionCache()"
                        @pointer-change="updateTimelinePointer"
                        @select-time="selectTimelineTime"
                        @select-switch="selectTimelineSwitch"
                      />
                      <section class="related-metric-panel">
                        <header>
                          <strong>同期关联指标</strong>
                          <el-select v-model="relatedMetricKey" style="width:220px" @change="saveCurrentSessionCache">
                            <el-option v-for="metric in relatedMetricDefinitions" :key="metric.key" :label="metric.title" :value="metric.key" />
                          </el-select>
                        </header>
                        <OnlineMrAnalysisChart
                          :series="relatedMetricSeries"
                          :title="relatedMetric?.title"
                          :unit="relatedMetric?.unit"
                          :tooltip-kind="relatedMetric?.key === 'ping-quality' ? 'ping-loss' : relatedMetric?.key === 'interface' ? 'interface' : relatedMetric?.key === 'busy' ? 'channel-busy' : relatedMetric?.key === 'traffic' ? 'traffic' : 'generic'"
                          :viewport="rssiViewport"
                          :cursor-time="timelineCursorTime"
                          :selected-time="selectedTime"
                          :shared-time-domain="timelineTimeDomain"
                          :active="chartActive && activeTab === 'charts'"
                          @update:viewport="updateRssiViewport"
                          @pointer-change="updateTimelinePointer"
                          @select-time="selectTimelineTime"
                        />
                      </section>
                      </template>

                  <OnlineMrPingQualityChart
                    v-else-if="item.key === 'ping-quality'"
                    class="metric-chart-panel metric-chart-panel--dual"
                    :loss-series="metricSeries(['ping_loss'])"
                    :rtt-series="metricSeries(['ping_rtt'])"
                    :events="chartEvents()"
                    :viewport="rssiViewport"
                    :cursor-time="timelineCursorTime"
                    :selected-time="selectedTime"
                    :shared-time-domain="timelineTimeDomain"
                    :active="chartActive && activeTab === 'charts'"
                    @update:viewport="updateRssiViewport"
                    @pointer-change="updateTimelinePointer"
                    @select-time="selectTimelineTime"
                  />

                  <template v-else-if="item.key === 'traffic'">
                    <section v-if="fullTrafficOverview" class="traffic-overview">
                      <header><strong>打流测试概览</strong><el-tag size="small" effect="plain">整场测试</el-tag></header>
                      <dl class="traffic-overview__meta">
                        <div><dt>状态</dt><dd>{{ fullTrafficOverview.status || '无数据' }}</dd></div>
                        <div><dt>协议</dt><dd>{{ fullTrafficOverview.protocol || '无数据' }}</dd></div>
                        <div><dt>方向</dt><dd>{{ fullTrafficOverview.direction || '无数据' }}</dd></div>
                        <div><dt>服务端</dt><dd>{{ fullTrafficOverview.server_ip || '无数据' }}{{ fullTrafficOverview.port == null ? '' : `:${fullTrafficOverview.port}` }}</dd></div>
                        <div><dt>并发流</dt><dd>{{ fullTrafficOverview.parallel == null ? '无数据' : fullTrafficOverview.parallel }}</dd></div>
                        <div><dt>测试时长</dt><dd>{{ formatDurationSeconds(fullTrafficOverview.overall.duration_seconds) }}</dd></div>
                      </dl>
                      <div class="traffic-overview__stats">
                        <article><span>平均吞吐</span><strong>{{ trafficValue(fullTrafficOverview.overall.average_mbps, 'Mbps') }}</strong></article>
                        <article><span>最小吞吐</span><strong>{{ trafficValue(fullTrafficOverview.overall.minimum_mbps, 'Mbps') }}</strong></article>
                        <article><span>最大吞吐</span><strong>{{ trafficValue(fullTrafficOverview.overall.maximum_mbps, 'Mbps') }}</strong></article>
                        <article><span>发送数据</span><strong>{{ formatBytes(fullTrafficOverview.overall.sent_bytes) }}</strong></article>
                        <article><span>接收数据</span><strong>{{ formatBytes(fullTrafficOverview.overall.received_bytes) }}</strong></article>
                        <article v-if="fullTrafficOverview.protocol === 'UDP'"><span>流量丢失率</span><strong>{{ fullTrafficOverview.overall.loss_percent == null ? '暂无可靠统计' : `${formatNumber(fullTrafficOverview.overall.loss_percent, 3)}%` }}</strong></article>
                        <article v-if="fullTrafficOverview.protocol === 'UDP'"><span>平均 Jitter</span><strong>{{ trafficValue(fullTrafficOverview.overall.average_jitter_ms, 'ms') }}</strong></article>
                        <article v-else><span>TCP 重传</span><strong>{{ fullTrafficOverview.overall.retransmits == null ? '暂无可靠统计' : fullTrafficOverview.overall.retransmits }}</strong></article>
                        <article><span>记录数</span><strong>{{ fullTrafficOverview.overall.record_count }}</strong></article>
                      </div>
                      <p v-if="fullTrafficOverview.data_quality_note" class="traffic-overview__note">{{ fullTrafficOverview.data_quality_note }}</p>
                      <div v-if="fullTrafficOverview.directions.length > 1" class="traffic-overview__rows">
                        <span v-for="row in fullTrafficOverview.directions" :key="row.run_id">{{ row.label }} · {{ trafficValue(row.average_mbps, 'Mbps') }} · {{ formatDurationSeconds(row.duration_seconds) }}</span>
                      </div>
                    </section>
                    <section v-if="trafficWindowOverview" class="traffic-window-summary">
                      <strong>当前窗口</strong><span>{{ rssiViewport?.start_time || '全部时间' }} ~ {{ rssiViewport?.end_time || '全部时间' }}</span><span>平均 {{ trafficValue(trafficWindowOverview.overall.average_mbps, 'Mbps') }}</span><span v-if="fullTrafficOverview?.protocol === 'UDP'">丢失 {{ trafficWindowOverview.overall.loss_percent == null ? '暂无可靠统计' : `${formatNumber(trafficWindowOverview.overall.loss_percent, 3)}%` }}</span>
                    </section>
                    <el-radio-group v-model="trafficMetricKey" class="traffic-metric-tabs" size="small">
                      <el-radio-button v-for="definition in visibleTrafficMetricDefinitions" :key="definition.key" :value="definition.key">{{ definition.title }}</el-radio-button>
                    </el-radio-group>
                    <OnlineMrAnalysisChart
                      class="metric-chart-panel"
                      :series="chartSeries"
                      :title="trafficMetricDefinition.title"
                      :unit="trafficMetricDefinition.unit"
                      :tooltip-kind="trafficMetricDefinition.tooltipKind"
                      :events="chartEvents()"
                      :viewport="rssiViewport"
                      :cursor-time="timelineCursorTime"
                      :selected-time="selectedTime"
                      :shared-time-domain="timelineTimeDomain"
                      :active="chartActive && activeTab === 'charts'"
                      @update:viewport="updateRssiViewport"
                      @pointer-change="updateTimelinePointer"
                      @select-time="selectTimelineTime"
                    />
                  </template>

                  <OnlineMrAnalysisChart
                    v-else
                    class="metric-chart-panel"
                    :series="chartSeries"
                    :title="item.title"
                    :unit="item.unit"
                    :tooltip-kind="item.key === 'interface' ? 'interface' : item.key === 'busy' ? 'channel-busy' : item.switchSource ? 'switch-rssi' : 'generic'"
                    :events="chartEvents()"
                    :viewport="rssiViewport"
                    :cursor-time="timelineCursorTime"
                    :selected-time="selectedTime"
                    :shared-time-domain="timelineTimeDomain"
                    :active="chartActive && activeTab === 'charts'"
                    @update:viewport="updateRssiViewport"
                    @pointer-change="updateTimelinePointer"
                    @select-time="selectTimelineTime"
                  />
                    </main>
                  </div>
                </template>
              </el-tab-pane>
            </el-tabs>
          </div>
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

      <div v-if="currentBusinessTable" class="timeline-actions">
        <el-button :disabled="!currentBusinessHasMore" @click="loadMoreActiveTab">加载更多业务数据</el-button>
        <span>当前 {{ currentBusinessRows.length }} 条 {{ businessTableLabel(currentBusinessTable) }}</span>
      </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.analysis-page{display:flex;min-width:0;min-height:0;height:100%;flex-direction:column;gap:12px}
.page-heading,.actions,.query-bar,.logs-toolbar{display:flex;align-items:center;gap:12px}
.page-heading{justify-content:space-between;align-items:flex-start}
.page-heading h1{margin:2px 0 6px}
.page-heading p,.query-hint,.logs-toolbar{margin:0;color:var(--el-text-color-secondary)}
.actions{justify-content:flex-end;flex-wrap:wrap;min-width:0}
.session-selector{flex:1 1 340px;max-width:430px;min-width:260px}
.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}
.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}
.summary-grid article,.business-summary article{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:8px}
.summary-grid article{padding:13px}
.summary-grid span,.business-summary span{color:var(--el-text-color-secondary);font-size:12px}
.summary-grid strong,.business-summary strong{display:block;margin-top:6px;font-size:18px}
.business-summary{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:10px;margin:0 0 10px}
.business-summary article{padding:12px}
.query-bar{flex-wrap:wrap}
.query-hint{display:inline-flex;align-items:center;gap:4px;font-size:12px}
.inline-icon{width:16px!important;height:16px!important;max-width:16px!important;max-height:16px!important;flex:0 0 16px!important;flex-shrink:0!important}
.inline-icon :deep(svg){width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important}
.analysis-status-row{display:flex;min-height:0;justify-content:flex-end}
.parser-status-tag{cursor:help}
.parser-status-details{display:grid;grid-template-columns:88px minmax(0,1fr);gap:7px 10px;margin:0;font-size:12px}
.parser-status-details dt{color:var(--el-text-color-secondary)}
.parser-status-details dd{min-width:0;margin:0;overflow-wrap:anywhere}
.analysis-tabs-host,.analysis-tabs{min-width:0;min-height:0}
.analysis-tabs-host{display:flex;flex:1 1 auto;flex-direction:column}
.analysis-tabs{display:flex;min-height:0;flex:1 1 auto;flex-direction:column}
.analysis-tabs:deep(.el-tabs__content){min-height:0;flex:1 1 auto}
.analysis-tabs:deep(.el-tab-pane){height:100%;min-height:0}
.raw-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:12px}
.raw-preview{margin:0;min-height:360px;max-height:480px;overflow:auto;padding:12px;border:1px solid var(--el-border-color-lighter);border-radius:8px;background:var(--el-fill-color-light);font:12px/1.6 Consolas,monospace;white-space:pre-wrap}
.timeline-actions{display:flex;align-items:center;gap:8px}
.timeline-workbench{display:flex;min-width:0;min-height:0;height:100%;flex-direction:column;overflow:hidden;background:var(--el-bg-color)}
.timeline-workbench.is-immersive{position:fixed;inset:0;z-index:2000;min-height:0;height:100dvh;overflow:hidden;padding:6px;border:0;background:var(--el-bg-color);box-shadow:var(--el-box-shadow-dark)}
.timeline-toolbar{display:flex;min-height:0;flex:none;align-items:center;gap:7px;flex-wrap:wrap;padding:0 0 6px}
.timeline-workbench.is-immersive .timeline-toolbar{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-x:contain;padding-bottom:4px}
.timeline-workbench>:deep(.el-tabs){display:flex;min-height:0;flex:1 1 auto;flex-direction:column}
.timeline-workbench>:deep(.el-tabs .el-tabs__header){flex:none;margin-bottom:6px}
.timeline-workbench>:deep(.el-tabs .el-tabs__content){min-height:0;flex:1 1 auto;overflow:hidden}
.timeline-workbench>:deep(.el-tabs .el-tab-pane){height:100%;min-height:0}
.timeline-analysis-layout{position:relative;display:grid;min-width:0;min-height:0;height:100%;grid-template-columns:clamp(240px,14vw,288px) minmax(0,1fr);overflow:hidden;border:1px solid var(--el-border-color-lighter)}
.timeline-chart-stack{display:grid;min-width:0;min-height:0;height:100%;grid-template-rows:minmax(428px,1.45fr) minmax(170px,.65fr);gap:8px;overflow-y:auto;overscroll-behavior:contain;padding:0 0 2px 8px}
.timeline-chart-pane{display:flex;min-width:0;min-height:0;height:100%;flex-direction:column;overflow-y:auto;overscroll-behavior:contain;padding-left:8px}
.rssi-pair-panel{min-width:0;min-height:428px}
.related-metric-panel{display:flex;min-width:0;min-height:170px;flex-direction:column;border-top:1px solid var(--el-border-color-lighter);padding-top:4px}
.related-metric-panel>header{display:flex;min-height:30px;flex:none;align-items:center;justify-content:space-between;gap:8px;padding:0 6px}
.related-metric-panel>:deep(.chart-shell){min-height:0;flex:1 1 auto}
.metric-chart-panel{display:flex;min-width:0;min-height:0;height:100%;flex:1 1 auto;overflow:hidden}
.metric-chart-panel--dual{height:100%}
.traffic-overview{display:flex;flex:none;flex-direction:column;gap:10px;margin-bottom:8px;padding:10px;border:1px solid var(--el-border-color-lighter);border-radius:8px;background:var(--el-fill-color-extra-light)}
.traffic-overview>header{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:14px}
.traffic-overview__meta{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:6px 10px;margin:0}
.traffic-overview__meta div{min-width:0}.traffic-overview__meta dt{color:var(--el-text-color-secondary);font-size:12px}.traffic-overview__meta dd{margin:2px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.traffic-overview__stats{display:grid;grid-template-columns:repeat(9,minmax(120px,1fr));gap:6px}.traffic-overview__stats article{min-width:0;padding:7px 8px;border:1px solid var(--el-border-color-lighter);border-radius:6px;background:var(--el-bg-color)}.traffic-overview__stats span{display:block;color:var(--el-text-color-secondary);font-size:12px}.traffic-overview__stats strong{display:block;min-width:0;margin-top:3px;overflow:hidden;font-size:14px;text-overflow:ellipsis;white-space:nowrap}
.traffic-overview__note{margin:0;color:var(--el-text-color-secondary);font-size:12px}.traffic-overview__rows{display:flex;gap:10px;overflow-x:auto;color:var(--el-text-color-secondary);font-size:12px;white-space:nowrap}.traffic-window-summary{display:flex;flex:none;align-items:center;gap:10px;overflow-x:auto;padding:6px 8px;color:var(--el-text-color-secondary);font-size:12px;white-space:nowrap}.traffic-window-summary strong{color:var(--el-text-color-primary)}.traffic-metric-tabs{flex:none;margin:0 0 8px}
:deep(.online-mr-row--group-a > td.el-table__cell){background:color-mix(in srgb, var(--nc-primary), transparent 96%)}
:deep(.online-mr-row--group-b > td.el-table__cell){background:color-mix(in srgb, var(--nc-success), transparent 96%)}
:deep(.online-mr-row--active .nc-table-cell){color:var(--el-color-success);font-weight:600}
:deep(.online-mr-row--active > td.el-table__cell){background:color-mix(in srgb, var(--nc-success), transparent 94%)}
@media(max-width:1399px){
  .summary-grid{grid-template-columns:repeat(3,minmax(140px,1fr))}
  .business-summary{grid-template-columns:repeat(2,minmax(140px,1fr))}
  .raw-layout{grid-template-columns:1fr}
  .timeline-analysis-layout{grid-template-columns:1fr}
}
@media(max-height:1080px){
  .analysis-page{gap:8px}
  .summary-grid article{padding:9px 11px}.summary-grid strong{margin-top:3px;font-size:16px}
  .query-bar{gap:8px}.timeline-toolbar{gap:5px;padding-bottom:4px}
  .timeline-workbench>:deep(.el-tabs .el-tabs__header){margin-bottom:4px}
  .timeline-workbench>:deep(.el-tabs--card>.el-tabs__header .el-tabs__item){height:32px;padding:0 12px}
}
@media(max-width:800px){
  .page-heading{align-items:flex-start;flex-direction:column}
  .actions{justify-content:flex-start;width:100%}
  .session-selector{max-width:none;width:100%}
  .summary-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}
  .query-bar>*{max-width:100%;width:100%!important}
  .timeline-workbench.is-immersive{inset:0}
}
</style>
