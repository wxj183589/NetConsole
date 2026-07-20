<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Document, Download, Files, Refresh, Search, Tickets } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { getOnlineMrRawTail, getOnlineMrSession, listOnlineMrRawFiles, listRecentOnlineMrSessions, queryOnlineMrMetrics, queryOnlineMrSwitchRssiWindows, queryOnlineMrTimeline } from '../../api/onlineMr'
import { exportOnlineMrReport, getRailTransitTask, recoverRailTransitTasks } from '../../api/railTransitWeb'
import OnlineMrAnalysisChart from '../../components/online-mr-analysis/OnlineMrAnalysisChart.vue'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import type { OnlineMrMetricPoint, OnlineMrMetricSeries, OnlineMrRawFile, OnlineMrSessionDetail, OnlineMrSessionSummary, OnlineMrSwitchRssiSource, OnlineMrSwitchRssiWindow, OnlineMrTimelineEvent } from '../../types/onlineMr'
import type { RailTransitTask } from '../../types/railTransitWeb'

const route = useRoute()
const router = useRouter()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const sessions = ref<OnlineMrSessionSummary[]>([])
const sessionId = ref('')
const detail = ref<OnlineMrSessionDetail | null>(null)
const activeTab = ref('session-history')
const chartTab = ref('rssi')
const metrics = ref<Record<string, OnlineMrMetricSeries[]>>({})
const metricOffsets = ref<Record<string, number>>({})
const metricHasMore = ref<Record<string, boolean>>({})
const switchWindows = ref<Record<OnlineMrSwitchRssiSource, OnlineMrSwitchRssiWindow[]>>({ history: [], realtime: [] })
const switchOffsets = ref<Record<OnlineMrSwitchRssiSource, number>>({ history: 0, realtime: 0 })
const switchHasMore = ref<Record<OnlineMrSwitchRssiSource, boolean>>({ history: false, realtime: false })
const timeline = ref<OnlineMrTimelineEvent[]>([])
const rawFiles = ref<OnlineMrRawFile[]>([])
const rawTail = ref<string[]>([])
const rawName = ref('')
const timelineOffset = ref(0)
const timelineHasMore = ref(false)
const timelineLimit = 200
const metricLimit = 1_000
const switchLimit = 200
const startTime = ref('')
const endTime = ref('')
const downsample = ref<'NONE' | 'BUCKET_AVG' | 'MIN_MAX' | 'LATEST_PER_BUCKET'>('LATEST_PER_BUCKET')
const bucketSeconds = ref(1)
const task = ref<RailTransitTask | null>(null)
const outputName = ref('')
const loading = ref(false)
const taskLoading = ref(false)
const error = ref('')
let pollTimer: number | undefined

type ChartDefinition = { key: string; title: string; unit: string; metric?: readonly string[]; switchSource?: OnlineMrSwitchRssiSource }
const chartDefinitions: readonly ChartDefinition[] = [
  { key: 'rssi', title: '主链路 RSSI', metric: ['rssi'], unit: 'dBm' },
  { key: 'ping-loss', title: 'Ping 丢包率', metric: ['ping_loss'], unit: '%' },
  { key: 'ping-rtt', title: 'Ping 延迟（fping RTT）', metric: ['ping_rtt'], unit: 'ms' },
  { key: 'interface', title: '接口 PPS', metric: ['interface_in_pps', 'interface_out_pps'], unit: 'pps' },
  { key: 'traffic', title: '业务打流', metric: ['iperf_bitrate'], unit: 'Mbps' },
  { key: 'busy', title: '信道繁忙度（Channel Busy）', metric: ['ctl_busy', 'tx_busy', 'rx_busy'], unit: '%' },
  { key: 'switch-rssi', title: '切换历史 RSSI 快照', switchSource: 'history', unit: 'dBm' },
  { key: 'switch-log-rssi', title: '实时切换日志 RSSI 快照', switchSource: 'realtime', unit: 'dBm' },
]

type MetricRow = { timestamp: string | null; series: string; value: number | null; unit: string; text: string | null; dimensions: string }
type TimelineRow = OnlineMrTimelineEvent

const metricColumns: NcTableColumn<MetricRow>[] = [
  { key: 'timestamp', label: '采样时间', valueType: 'datetime', widthMode: 'content', minWidth: 220, showOverflowTooltip: true },
  { key: 'series', label: '序列', valueType: 'name', widthMode: 'content', minWidth: 180 },
  { key: 'value', label: '数值', valueType: 'number', displayValue: (row) => display(row.value) },
  { key: 'unit', label: '单位', valueType: 'name', displayValue: (row) => row.unit || '无数据' },
  { key: 'text', label: '文本', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
  { key: 'dimensions', label: '维度', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
const timelineColumns: NcTableColumn<TimelineRow>[] = [
  { key: 'local_time', label: '本地时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'source', label: '来源', valueType: 'name', widthMode: 'content', minWidth: 130 },
  { key: 'event_type', label: '事件', valueType: 'status' },
  { key: 'severity', label: '级别', valueType: 'status' },
  { key: 'title', label: '说明', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
const sessionColumns: NcTableColumn<OnlineMrSessionSummary>[] = [
  { key: 'session_id', label: '会话', valueType: 'name', widthMode: 'content', minWidth: 180 },
  { key: 'device_name', label: 'MR', valueType: 'name' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'started_at', label: '开始时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'stopped_at', label: '结束时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
  { key: 'duration_minutes', label: '时长(分钟)', valueType: 'number', displayValue: (row) => display(row.duration_minutes) },
  { key: 'data_integrity', label: '数据状态', valueType: 'status', displayValue: (row) => row.finalization_complete == null ? '无数据' : row.finalization_complete ? '完整' : '部分' },
]
const rawColumns: NcTableColumn<OnlineMrRawFile>[] = [
  { key: 'name', label: '文件', valueType: 'name', widthMode: 'content', minWidth: 240 },
  { key: 'relative_name', label: '相对路径', valueType: 'description', align: 'left', alignmentReason: 'path' },
  { key: 'size_bytes', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '修改时间', valueType: 'datetime', widthMode: 'content', minWidth: 220 },
]

const selectedChart = computed(() => chartDefinitions.find((item) => item.key === chartTab.value) || chartDefinitions[0])
const chartSeries = computed(() => selectedChart.value.switchSource ? switchRssiSeries(selectedChart.value.switchSource) : metrics.value[selectedChart.value.key] || [])
const meshRows = computed(() => flattenMetrics(metrics.value['mesh-link'] || []))
const detailRows = computed(() => flattenMetrics(metrics.value['mesh-detail'] || []))
const busyRows = computed(() => flattenMetrics(metrics.value['channel-busy'] || []))
const interfaceRows = computed(() => flattenMetrics(metrics.value['interface-rate'] || []))
const fpingRows = computed(() => flattenMetrics(metrics.value.fping || []))
const iperfRows = computed(() => flattenMetrics(metrics.value.iperf || []))
const statisticsRows = computed(() => flattenMetrics(metrics.value.statistics || []))
const switchRows = computed(() => timeline.value.filter((row) => row.event_type.toLowerCase().includes('switch') || row.source.toLowerCase().includes('switch')))
const switchHistoryRows = computed(() => switchRows.value.filter((row) => row.source === 'switch_history'))
const switchRealtimeRows = computed(() => switchRows.value.filter((row) => row.source === 'switch_realtime'))
const diagnosisRows = computed(() => timeline.value.filter((row) => Boolean(row.severity) || row.source === 'analysis'))
const activeMetric = computed(() => ({
  'mesh-link': ['rssi', 'main_link'],
  'mesh-detail': ['rssi'],
  'channel-busy': ['ctl_busy', 'tx_busy', 'rx_busy'],
  statistics: ['radio_statistics'],
  'interface-rate': ['interface_in_pps', 'interface_out_pps'],
  fping: ['ping_rtt', 'ping_loss'],
  iperf: ['iperf_bitrate'],
} as Record<string, string[]>)[activeTab.value])

function message(cause: unknown, fallback: string): string { return cause instanceof Error ? cause.message : fallback }
function display(value: unknown): string { return value === null || value === undefined || value === '' ? '无数据' : String(value) }
function formatBytes(value: number): string { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`; return `${(value / 1024 / 1024).toFixed(1)} MiB` }
function flattenMetrics(rows: OnlineMrMetricSeries[]): MetricRow[] { return rows.flatMap((series) => series.points.map((point) => ({ timestamp: point.timestamp, series: series.series_key || '默认序列', value: point.value, unit: String(point.dimensions.metric_unit || series.unit || ''), text: point.text_value, dimensions: Object.entries(point.dimensions || {}).map(([key, value]) => `${key}=${value}`).join('，') || '无数据' }))) }
function metricSummary(points: OnlineMrMetricPoint[]) { const values = points.flatMap((point) => point.value == null ? [] : [point.value]); return { count: points.length, minimum: values.length ? Math.min(...values) : null, maximum: values.length ? Math.max(...values) : null, average: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null } }
function appendMetricPage(current: OnlineMrMetricSeries[], incoming: OnlineMrMetricSeries[]): OnlineMrMetricSeries[] {
  const merged = new Map(current.map((series) => [`${series.metric_type}\0${series.series_key}`, { ...series, points: [...series.points] }]))
  for (const series of incoming) { const key = `${series.metric_type}\0${series.series_key}`; const existing = merged.get(key); if (existing) { existing.points.push(...series.points); existing.summary = metricSummary(existing.points) } else merged.set(key, { ...series, points: [...series.points] }) }
  return [...merged.values()]
}
function switchRssiSeries(source: OnlineMrSwitchRssiSource): OnlineMrMetricSeries[] {
  const points = (role: 'old' | 'new'): OnlineMrMetricPoint[] => switchWindows.value[source].map((event) => ({ timestamp: event.event_time, value: role === 'old' ? event.old_rssi_dbm : event.new_rssi_dbm, text_value: role === 'old' ? event.old_peer_name : event.new_peer_name, dimensions: { role, radio: event.radio, peer_name: role === 'old' ? event.old_peer_name : event.new_peer_name, peer_mac: role === 'old' ? event.old_peer_mac : event.new_peer_mac, reason: event.reason, raw_file: event.raw_file, raw_line_start: event.raw_line_start, raw_line_end: event.raw_line_end } }))
  return (['old', 'new'] as const).map((role) => { const rows = points(role); return { metric_type: `switch_${source}_rssi`, series_key: role === 'old' ? '切出链路' : '切入链路', unit: 'dBm', points: rows, summary: metricSummary(rows) } })
}
function chartEvents(): Array<{ time: string; label: string }> { const source = selectedChart.value.switchSource; return source ? switchWindows.value[source].filter((event) => event.event_time).map((event) => ({ time: event.event_time!, label: event.reason || '主链路切换' })) : [] }
function rememberTask(value: RailTransitTask | null): void { task.value = value; if (value) localStorage.setItem('netconsole.online-mr-analysis.last-task', value.task_id); else localStorage.removeItem('netconsole.online-mr-analysis.last-task') }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function poll(): void { stopPolling(); if (!task.value || terminalStates.has(task.value.status)) return; pollTimer = window.setTimeout(async () => { try { rememberTask(await getRailTransitTask(task.value!.task_id)); poll() } catch (cause) { error.value = message(cause, '报告任务读取失败') } }, 1000) }

async function loadSessions(): Promise<void> {
  loading.value = true; error.value = ''
  try {
    sessions.value = await listRecentOnlineMrSessions(100)
    const requested = typeof route.query.session_id === 'string' ? route.query.session_id : ''
    sessionId.value = sessions.value.find((item) => item.session_id === requested)?.session_id || sessionId.value || sessions.value[0]?.session_id || ''
    if (sessionId.value) await loadAnalysis()
  } catch (cause) { error.value = message(cause, 'Online MR 会话列表加载失败') } finally { loading.value = false }
}
async function loadAnalysis(): Promise<void> { if (!sessionId.value) return; loading.value = true; error.value = ''; try { detail.value = await getOnlineMrSession(sessionId.value); metrics.value = {}; metricOffsets.value = {}; metricHasMore.value = {}; switchWindows.value = { history: [], realtime: [] }; switchOffsets.value = { history: 0, realtime: 0 }; switchHasMore.value = { history: false, realtime: false }; timeline.value = []; rawFiles.value = []; await loadActiveTab(activeTab.value) } catch (cause) { error.value = message(cause, 'Online MR 分析数据加载失败') } finally { loading.value = false } }
async function loadMetric(name: string, types: string[], append = false): Promise<void> {
  if (!sessionId.value || (!append && metrics.value[name])) return
  const offset = append ? metricOffsets.value[name] || 0 : 0
  const page = await queryOnlineMrMetrics(sessionId.value, types, { startTime: startTime.value, endTime: endTime.value, limit: metricLimit, offset, downsample: downsample.value, bucketSeconds: bucketSeconds.value })
  metrics.value[name] = append ? appendMetricPage(metrics.value[name] || [], page.series) : page.series
  metricOffsets.value[name] = page.next_offset
  metricHasMore.value[name] = page.has_more
}
async function loadSwitchWindows(source: OnlineMrSwitchRssiSource, append = false): Promise<void> {
  if (!sessionId.value || (!append && switchWindows.value[source].length)) return
  const offset = append ? switchOffsets.value[source] : 0
  const page = await queryOnlineMrSwitchRssiWindows(sessionId.value, source, { startTime: startTime.value, endTime: endTime.value, limit: switchLimit, offset })
  switchWindows.value[source] = append ? [...switchWindows.value[source], ...page.items] : page.items
  switchOffsets.value[source] = offset + page.limit
  switchHasMore.value[source] = page.has_more
}
async function loadTimelinePage(reset = false): Promise<void> { if (!sessionId.value) return; if (reset) timelineOffset.value = 0; const rows = await queryOnlineMrTimeline(sessionId.value, timelineLimit, timelineOffset.value); timeline.value = reset ? rows : [...timeline.value, ...rows]; timelineOffset.value += rows.length; timelineHasMore.value = rows.length === timelineLimit }
async function loadRaw(): Promise<void> { if (!rawFiles.value.length) rawFiles.value = await listOnlineMrRawFiles(sessionId.value) }
async function loadCollectorLog(): Promise<void> { const result = await getOnlineMrRawTail(sessionId.value, 'collector_output', 250); rawName.value = 'collector_output'; rawTail.value = result.lines }
async function loadActiveTab(tab: string): Promise<void> {
  if (!sessionId.value) return
  try {
    if (tab === 'mesh-link') await loadMetric('mesh-link', ['rssi', 'main_link'])
    else if (tab === 'mesh-detail') await loadMetric('mesh-detail', ['rssi'])
    else if (tab === 'channel-busy') await loadMetric('channel-busy', ['ctl_busy', 'tx_busy', 'rx_busy'])
    else if (tab === 'statistics') await loadMetric('statistics', ['radio_statistics'])
    else if (tab === 'interface-rate') await loadMetric('interface-rate', ['interface_in_pps', 'interface_out_pps'])
    else if (tab === 'fping') await loadMetric('fping', ['ping_rtt', 'ping_loss'])
    else if (tab === 'iperf') await loadMetric('iperf', ['iperf_bitrate'])
    else if (tab === 'switch-history') await Promise.all([loadTimelinePage(true), loadSwitchWindows('history')])
    else if (tab === 'active-switch') await Promise.all([loadTimelinePage(true), loadSwitchWindows('realtime')])
    else if (tab === 'diagnosis') await loadTimelinePage(true)
    else if (tab === 'raw') await loadRaw()
    else if (tab === 'logs') await loadCollectorLog()
    else if (tab === 'charts') { if (selectedChart.value.switchSource) await loadSwitchWindows(selectedChart.value.switchSource); else await loadMetric(selectedChart.value.key, [...(selectedChart.value.metric || [])]) }
  } catch (cause) { error.value = message(cause, '分析数据加载失败') }
}
async function openRaw(row: OnlineMrRawFile): Promise<void> { rawName.value = row.name; try { const result = await getOnlineMrRawTail(sessionId.value, row.name, 250); rawTail.value = result.lines } catch (cause) { error.value = message(cause, '原始日志读取失败') } }
async function startReport(): Promise<void> { if (!detail.value || !isFeatureEnabled('web.online_mr_report_export')) return; taskLoading.value = true; error.value = ''; try { rememberTask(await exportOnlineMrReport(detail.value.session_id, outputName.value)); poll(); openTaskWindow() } catch (cause) { error.value = message(cause, 'Online MR 报告生成启动失败') } finally { taskLoading.value = false } }
function openTaskWindow(): void { const taskId = task.value?.task_id || ''; if (window.netconsoleDesktop) { void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) }); return }; void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } }) }
async function recoverTask(): Promise<void> { try { const saved = localStorage.getItem('netconsole.online-mr-analysis.last-task') || ''; const rows = await recoverRailTransitTasks(); rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => item.action === 'online_mr_report') || null); poll() } catch (cause) { error.value = message(cause, '报告任务恢复失败') } }
function changeTab(tab: string): void { activeTab.value = tab; void loadActiveTab(tab) }
function changeChartTab(tab: string): void { chartTab.value = tab; const definition = chartDefinitions.find((item) => item.key === tab); if (definition?.switchSource) void loadSwitchWindows(definition.switchSource); else void loadMetric(tab, [...(definition?.metric || [])]) }
function loadMoreMetric(): void { if (activeMetric.value) void loadMetric(activeTab.value, activeMetric.value, true) }
function loadMoreChart(): void { const definition = selectedChart.value; if (definition.switchSource) void loadSwitchWindows(definition.switchSource, true); else void loadMetric(definition.key, [...(definition.metric || [])], true) }

watch([startTime, endTime, downsample, bucketSeconds], () => { metrics.value = {}; metricOffsets.value = {}; metricHasMore.value = {}; switchWindows.value = { history: [], realtime: [] }; switchOffsets.value = { history: 0, realtime: 0 }; switchHasMore.value = { history: false, realtime: false }; if (activeTab.value !== 'session-history') void loadActiveTab(activeTab.value) })
onMounted(() => { void Promise.all([loadSessions(), recoverTask()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="analysis-page">
    <header class="page-heading"><div><p class="eyebrow">RAIL TRANSIT · ONLINE MR ANALYSIS</p><h1>车载 MR 收集分析</h1><p>分析车载 MR 手工采集会话及网络测试数据，原始 MESH 日志保持独立入口。</p></div><div class="actions"><el-select v-model="sessionId" filterable placeholder="选择 Online MR 会话" style="width:360px" @change="loadAnalysis"><el-option v-for="item in sessions" :key="item.session_id" :label="`${item.device_name || item.mr_name} · ${item.status} · ${item.started_at || item.session_id}`" :value="item.session_id" /></el-select><el-button :icon="Refresh" :loading="loading" @click="loadSessions">刷新</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTask">恢复报告任务</el-button></el-alert>
    <el-empty v-if="!detail && !loading" description="当前局点暂无 Online MR 会话" />
    <template v-if="detail">
      <div class="summary-grid"><article><span>会话状态</span><strong>{{ detail.status || '无数据' }}</strong></article><article><span>MR</span><strong>{{ detail.device_name || detail.mr_name || '无数据' }}</strong></article><article><span>完整性</span><strong>{{ detail.data_integrity || '无数据' }}</strong></article><article><span>执行端</span><strong>{{ detail.executor_kind || '无数据' }}</strong></article><article><span>采集时长</span><strong>{{ display(detail.duration_minutes) }} min</strong></article></div>
      <div class="query-bar"><el-date-picker v-model="startTime" type="datetime" placeholder="开始时间" value-format="YYYY-MM-DD HH:mm:ss.SSS" /><span>至</span><el-date-picker v-model="endTime" type="datetime" placeholder="结束时间" value-format="YYYY-MM-DD HH:mm:ss.SSS" /><el-select v-model="downsample" style="width:160px"><el-option label="不降采样" value="NONE" /><el-option label="按桶平均" value="BUCKET_AVG" /><el-option label="保留首尾异常" value="LATEST_PER_BUCKET" /><el-option label="最小最大" value="MIN_MAX" /></el-select><el-input-number v-model="bucketSeconds" :min="1" :max="86400" controls-position="right" /><span class="query-hint"><Search /> 查询窗口仅在当前页签加载</span></div>
      <el-tabs :model-value="activeTab" class="analysis-tabs" @tab-change="changeTab">
        <el-tab-pane name="session-history" label="会话记录"><NcDataTable table-id="online-mr-analysis-session-history" route-key="/rail-transit/online-mr-analysis" :data="sessions" :columns="sessionColumns" border height="460" empty-text="暂无会话" @row-click="(row: OnlineMrSessionSummary) => { sessionId = row.session_id; void loadAnalysis() }" /></el-tab-pane>
        <el-tab-pane name="mesh-link" label="MESH 链路"><NcDataTable table-id="online-mr-analysis-mesh-link" route-key="/rail-transit/online-mr-analysis" :data="meshRows" :columns="metricColumns" border height="460" empty-text="暂无 MESH 链路数据" /></el-tab-pane>
        <el-tab-pane name="mesh-detail" label="MESH 明细"><NcDataTable table-id="online-mr-analysis-mesh-detail" route-key="/rail-transit/online-mr-analysis" :data="detailRows" :columns="metricColumns" border height="460" empty-text="暂无链路明细" /></el-tab-pane>
        <el-tab-pane name="channel-busy" label="信道繁忙度"><NcDataTable table-id="online-mr-analysis-channel-busy" route-key="/rail-transit/online-mr-analysis" :data="busyRows" :columns="metricColumns" border height="460" empty-text="暂无信道数据" /></el-tab-pane>
        <el-tab-pane name="statistics" label="无线统计"><NcDataTable table-id="online-mr-analysis-statistics" route-key="/rail-transit/online-mr-analysis" :data="statisticsRows" :columns="metricColumns" border height="460" empty-text="暂无统计数据" /></el-tab-pane>
        <el-tab-pane name="switch-history" label="切换历史"><NcDataTable table-id="online-mr-analysis-switch-history" route-key="/rail-transit/online-mr-analysis" :data="switchHistoryRows" :columns="timelineColumns" border height="460" empty-text="暂无切换历史" /></el-tab-pane>
        <el-tab-pane name="active-switch" label="实时切换日志"><NcDataTable table-id="online-mr-analysis-active-switch" route-key="/rail-transit/online-mr-analysis" :data="switchRealtimeRows" :columns="timelineColumns" border height="460" empty-text="暂无实时切换日志" /></el-tab-pane>
        <el-tab-pane name="interface-rate" label="接口 PPS"><NcDataTable table-id="online-mr-analysis-interface-rate" route-key="/rail-transit/online-mr-analysis" :data="interfaceRows" :columns="metricColumns" border height="460" empty-text="暂无接口 PPS 数据" /></el-tab-pane>
        <el-tab-pane name="charts" label="动态图"><el-tabs :model-value="chartTab" type="card" @tab-change="changeChartTab"><el-tab-pane v-for="item in chartDefinitions" :key="item.key" :name="item.key" :label="item.title"><OnlineMrAnalysisChart :series="chartTab === item.key ? chartSeries : (metrics[item.key] || [])" :title="item.title" :unit="item.unit" :events="chartTab === item.key ? chartEvents() : []" /></el-tab-pane></el-tabs><div class="timeline-actions"><el-button :disabled="selectedChart.switchSource ? !switchHasMore[selectedChart.switchSource] : !metricHasMore[selectedChart.key]" @click="loadMoreChart">加载更多图表数据</el-button></div></el-tab-pane>
        <el-tab-pane name="fping" label="fping 1 秒聚合"><NcDataTable table-id="online-mr-analysis-fping" route-key="/rail-transit/online-mr-analysis" :data="fpingRows" :columns="metricColumns" border height="460" empty-text="暂无 fping 数据" /></el-tab-pane>
        <el-tab-pane name="iperf" label="iPerf"><NcDataTable table-id="online-mr-analysis-iperf" route-key="/rail-transit/online-mr-analysis" :data="iperfRows" :columns="metricColumns" border height="460" empty-text="暂无 iPerf 数据" /></el-tab-pane>
        <el-tab-pane name="diagnosis" label="诊断"><NcDataTable table-id="online-mr-analysis-diagnosis" route-key="/rail-transit/online-mr-analysis" :data="diagnosisRows" :columns="timelineColumns" border height="460" empty-text="暂无诊断事件" /></el-tab-pane>
        <el-tab-pane name="raw" label="原始日志"><div class="raw-layout"><NcDataTable table-id="online-mr-analysis-raw" route-key="/rail-transit/online-mr-analysis" :data="rawFiles" :columns="rawColumns" border height="360" empty-text="暂无原始文件" @row-click="openRaw" /><pre class="raw-preview">{{ rawName ? `${rawName}\n\n${rawTail.join('\n')}` : '选择文件查看原始日志' }}</pre></div></el-tab-pane>
        <el-tab-pane name="logs" label="采集日志"><div class="logs-toolbar"><el-button :icon="Files" @click="loadCollectorLog">刷新采集日志</el-button><span>采集器日志与原始设备输出分开保存</span></div><pre class="raw-preview">{{ rawTail.join('\n') || '暂无采集日志' }}</pre></el-tab-pane>
      </el-tabs>
      <div v-if="activeMetric" class="timeline-actions"><el-button :disabled="!metricHasMore[activeTab]" @click="loadMoreMetric">加载更多指标数据</el-button><span>每页最多 {{ metricLimit }} 个原始点</span></div>
      <div v-if="['switch-history','active-switch','diagnosis'].includes(activeTab)" class="timeline-actions"><el-button :disabled="timelineOffset === 0" @click="loadTimelinePage(true)">重新读取</el-button><el-button :disabled="!timelineHasMore" @click="loadTimelinePage(false)">加载更多</el-button><span>当前 {{ timelineOffset }} 条</span></div>
      <div class="report-card"><div><h2><Document /> 分析报告</h2><p>报告由 Export Process 生成；任务、日志、Artifact 保存和打开操作统一在任务窗口完成。</p></div><div class="report-actions"><el-input v-model="outputName" placeholder="可选报告文件名" /><el-button type="primary" :icon="Download" :loading="taskLoading" :disabled="!isFeatureEnabled('web.online_mr_report_export')" @click="startReport">生成 XLSX 报告</el-button><el-button :icon="Tickets" @click="openTaskWindow">打开任务窗口</el-button></div><el-alert v-if="task" :title="`${task.status} · ${task.error_message || task.message || task.task_id}`" :type="task.status === 'FAILED' ? 'error' : 'info'" :closable="false" /></div>
    </template>
  </section>
</template>

<style scoped>
.analysis-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.query-bar,.report-actions,.logs-toolbar{display:flex;align-items:center;gap:12px}.page-heading{justify-content:space-between}.page-heading h1,.report-card h2{margin:2px 0 6px}.page-heading p,.report-card p,.query-hint,.logs-toolbar{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}.summary-grid article,.report-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:10px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:18px}.query-bar{flex-wrap:wrap}.query-hint{display:inline-flex;align-items:center;gap:4px;font-size:12px}.analysis-tabs{min-width:0}.raw-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:12px}.raw-preview{margin:0;min-height:360px;max-height:480px;overflow:auto;padding:12px;border:1px solid var(--el-border-color-lighter);border-radius:8px;background:var(--el-fill-color-light);font:12px/1.6 Consolas,monospace;white-space:pre-wrap}.timeline-actions{display:flex;align-items:center;gap:8px}.report-card{display:flex;flex-direction:column;gap:14px;padding:14px 16px}.report-card h2{display:flex;align-items:center;gap:6px}.report-actions .el-input{width:320px}@media(max-width:1200px){.summary-grid{grid-template-columns:repeat(3,minmax(140px,1fr))}.raw-layout{grid-template-columns:1fr}}@media(max-width:800px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.query-bar>*{max-width:100%;width:100%!important}.report-actions{align-items:stretch;flex-direction:column}.report-actions .el-input{width:100%}}
</style>
