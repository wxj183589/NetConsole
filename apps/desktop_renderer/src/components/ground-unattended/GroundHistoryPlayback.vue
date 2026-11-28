<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getGroundHeartbeat, getGroundMrMonitoring, getGroundQuickPingSamples, listGroundHistory, listGroundQuickPing, startGroundHistoryExport } from '../../api/groundUnattended'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import { activeSiteContext } from '../../stores/siteContext'
import type { GroundHeartbeatMr, GroundHistoryPage, GroundMrMonitoring, GroundRun, GroundTrain } from '../../types/groundUnattended'
import MrMonitoringChart from './MrMonitoringChart.vue'
import QuickPingChart from './QuickPingChart.vue'
import { heartbeatStatusStatistics } from './pingChartStatus'
import { selectedQuickPingStatistics } from './quickPingStatistics'

const props = defineProps<{ siteId: string; runs: GroundRun[]; trains: GroundTrain[]; active: boolean; deleting?: boolean }>()
const emit = defineEmits<{ 'delete-run': [run: GroundRun]; 'view-syslog': [runId: string] }>()
interface MrOption { id: string; role: string; name: string; trainId: string; trainNo: string }
const selectedRunId = ref(''), selectedMrId = ref(''), range = ref<Date[]>([])
const result = ref<GroundMrMonitoring | null>(null), loading = ref(false), error = ref('')
const timelinePage = ref<GroundHistoryPage | null>(null)
const timelineError = ref('')
const timelineLoading = ref(false)
const timelineEventType = ref('')
const timelineMrOnly = ref(false)
const timelineCursors = ref([''])
const timelinePageIndex = ref(0)
const timelineExporting = ref(false)
const { submitExportAfterDestinationSelected, hasActiveExportAction } = useUserSelectedExport()
const historyExportFeature = 'capability.ground_unattended.history_export'
let timelineRequest: AbortController | null = null
const historyMrs = ref<GroundHeartbeatMr[]>([]), historyLoading = ref(false), historyError = ref('')
const quickRows = ref<Record<'primary' | 'backup', Array<Record<string, unknown>>>>({ primary: [], backup: [] })
const quickBuckets = ref<Record<'primary' | 'backup', Array<Record<string, unknown>>>>({ primary: [], backup: [] })
const quickLoading = ref(false), quickError = ref('')
const quickLoaded = ref(false)
const fullStart = ref(''), fullEnd = ref(''), visibleStart = ref(''), visibleEnd = ref(''), cursorTime = ref('')
const primaryPingExpanded = ref(true), backupPingExpanded = ref(true), primaryQuickExpanded = ref(true), backupQuickExpanded = ref(true), peerExpanded = ref(true)
const lossPage = ref(1), eventResult = ref<GroundMrMonitoring | null>(null)
let controller: AbortController | null = null, eventController: AbortController | null = null, historyController: AbortController | null = null, eventTimer: ReturnType<typeof setTimeout> | undefined, generation = 0

const mrOptions = computed<MrOption[]>(() => {
  const items = new Map<string, MrOption>()
  if (historyMrs.value.length) {
    for (const mr of historyMrs.value) {
      if (!mr.mr_uuid || items.has(mr.mr_uuid)) continue
      items.set(mr.mr_uuid, { id: mr.mr_uuid, role: mr.role, name: mr.mr_name, trainId: mr.train_id, trainNo: mr.train_no })
    }
  } else for (const train of props.trains) for (const endpoint of train.endpoints || []) {
    if (!endpoint.mr_id || items.has(endpoint.mr_id)) continue
    items.set(endpoint.mr_id, { id: endpoint.mr_id, role: endpoint.endpoint, name: endpoint.mr_name, trainId: train.train_id, trainNo: train.train_no })
  }
  return [...items.values()].sort((a, b) => `${a.trainNo}-${a.role}`.localeCompare(`${b.trainNo}-${b.role}`, 'zh-CN', { numeric: true }))
})
const selectedRun = computed(() => props.runs.find((item) => item.run_id === selectedRunId.value))
const selectedMr = computed(() => mrOptions.value.find((item) => item.id === selectedMrId.value))
const displayEvents = computed(() => eventResult.value || result.value)
const eventCutoff = computed(() => {
  const cursor = Date.parse(cursorTime.value)
  if (Number.isFinite(cursor)) return cursor
  const end = Date.parse(visibleEnd.value)
  return Number.isFinite(end) ? end : Number.POSITIVE_INFINITY
})
const recentSwitchEvents = computed(() => (displayEvents.value?.mesh_events || [])
  .filter((event) => event.event_type.toUpperCase() === 'MESH_ACTIVELINK_SWITCH')
  .filter((event) => Date.parse(event.event_time) <= eventCutoff.value)
  .slice().sort((a, b) => Date.parse(b.event_time) - Date.parse(a.event_time)).slice(0, 3).reverse())
const lossEvents = computed(() => (displayEvents.value?.loss_events || [])
  .filter((event) => Date.parse(String(event.started_at || '')) <= eventCutoff.value)
  .slice().sort((a, b) => Date.parse(String(b.started_at || '')) - Date.parse(String(a.started_at || ''))).slice(0, 3).reverse())
const lossTotal = computed(() => displayEvents.value?.loss_event_total || 0)

function monitoringDataFor(targetIp: string): GroundMrMonitoring | null {
  if (!result.value || !targetIp) return null
  return { ...result.value, series: { ...result.value.series, points: result.value.series.points.filter((point) => point.target_ip === targetIp) } }
}
const primaryData = computed(() => monitoringDataFor(result.value?.mr.management_ip || ''))
const backupData = computed(() => monitoringDataFor(result.value?.mr.backup_management_ip || ''))
function heartbeatStatsFor(data: GroundMrMonitoring | null) {
  const start = Date.parse(visibleStart.value), end = Date.parse(visibleEnd.value)
  const points = (data?.series.points || []).filter((point) => {
    const stamp = Date.parse(point.ts)
    return !Number.isFinite(start) || !Number.isFinite(end) || (stamp >= start && stamp <= end)
  })
  return heartbeatStatusStatistics(points as unknown as Array<Record<string, unknown>>)
}
const primaryHeartbeatStats = computed(() => heartbeatStatsFor(primaryData.value))
const backupHeartbeatStats = computed(() => heartbeatStatsFor(backupData.value))
const primaryQuickRows = computed(() => quickRows.value.primary)
const backupQuickRows = computed(() => quickRows.value.backup)
const primaryQuickBuckets = computed(() => quickBuckets.value.primary)
const backupQuickBuckets = computed(() => quickBuckets.value.backup)
const primaryQuickStats = computed(() => selectedQuickPingStatistics(primaryQuickRows.value))
const backupQuickStats = computed(() => selectedQuickPingStatistics(backupQuickRows.value))

function format(value: unknown): string {
  const date = new Date(String(value || ''))
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '—'
}
function lossStateLabel(value: unknown): string {
  return ({ OPEN: '丢包中', ACTIVE: '持续异常', RECOVERED: '已恢复', CLOSED: '已恢复' } as Record<string, string>)[String(value || '').toUpperCase()] || '未知'
}
function runStateLabel(value: unknown): string {
  return ({ RUNNING: '运行中', PAUSED: '已暂停', STOPPING: '停止中', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消', ARCHIVING: '归档中' } as Record<string, string>)[String(value || '').toUpperCase()] || '未知'
}
function stopRequests(): void {
  generation++; controller?.abort(); eventController?.abort(); historyController?.abort(); controller = null; eventController = null; historyController = null
  if (eventTimer) clearTimeout(eventTimer)
}
async function loadHistoricalMrs(runId: string): Promise<void> {
  historyController?.abort()
  historyLoading.value = Boolean(runId)
  historyMrs.value = []
  historyError.value = ''
  if (!runId) return
  const request = new AbortController(); historyController = request
  try {
    const page = await getGroundHeartbeat(runId, { signal: request.signal }, { data_mode: 'HISTORICAL_PLAYBACK', page: 1, page_size: 200 })
    if (!request.signal.aborted && selectedRunId.value === runId) {
      historyMrs.value = page.mrs || []
      selectedMrId.value = mrOptions.value[0]?.id || ''
    }
  } catch (reason) {
    if (!request.signal.aborted && selectedRunId.value === runId) {
      historyError.value = reason instanceof Error ? reason.message : String(reason)
      selectedMrId.value = mrOptions.value[0]?.id || ''
    }
  } finally {
    if (historyController === request) {
      historyController = null; historyLoading.value = false
      if (selectedRunId.value === runId && !historyMrs.value.length) selectedMrId.value = mrOptions.value[0]?.id || ''
    }
  }
}
function applyRunRange(): void {
  const run = selectedRun.value
  if (!run) return
  const start = new Date(run.actual_started_at || run.scheduled_start_at || run.created_at)
  const rawEnd = new Date(run.actual_ended_at || run.scheduled_end_at || run.updated_at)
  const end = Number.isFinite(rawEnd.getTime()) && rawEnd > start ? rawEnd : new Date(start.getTime() + 60 * 60 * 1000)
  range.value = [start, new Date(Math.min(end.getTime(), start.getTime() + 86_400_000))]
}
function selectedRange(): [Date, Date] | null {
  const run = selectedRun.value
  const [start, end] = range.value || []
  if (!run || !start || !end || !(start < end)) return null
  const runStart = Date.parse(run.actual_started_at || run.scheduled_start_at || run.created_at)
  const runEnd = Date.parse(run.actual_ended_at || run.scheduled_end_at || run.updated_at)
  if (start.getTime() < runStart || end.getTime() > runEnd || end.getTime() - start.getTime() > 86_400_000) return null
  return [start, end]
}
watch(() => props.runs, (rows) => {
  if (!rows.some((row) => row.run_id === selectedRunId.value)) selectedRunId.value = rows[0]?.run_id || ''
}, { immediate: true })
watch(selectedRunId, (runId) => {
  stopRequests()
  clearTimeline()
  emit('view-syslog', '')
  applyRunRange()
  fullStart.value = fullEnd.value = visibleStart.value = visibleEnd.value = cursorTime.value = ''
  result.value = null
  eventResult.value = null
  loading.value = false
  quickLoading.value = false
  error.value = ''
  quickError.value = ''
  quickRows.value = { primary: [], backup: [] }
  quickBuckets.value = { primary: [], backup: [] }
  selectedMrId.value = mrOptions.value[0]?.id || ''
  void loadHistoricalMrs(runId)
}, { immediate: true, flush: 'sync' })
watch(mrOptions, (rows) => { if (historyLoading.value) return; if (!rows.some((row) => row.id === selectedMrId.value)) selectedMrId.value = rows[0]?.id || '' }, { immediate: true })

async function query(): Promise<void> {
  stopRequests(); const current = generation; error.value = ''; quickError.value = ''; quickLoaded.value = false; quickLoading.value = false; result.value = null; eventResult.value = null; quickRows.value = { primary: [], backup: [] }; quickBuckets.value = { primary: [], backup: [] }
  const selection = selectedRange()
  if (!selectedMrId.value || !selection) { error.value = '请选择 MR，并在当前运行内选择不超过 24 小时的时间范围'; return }
  const [start, end] = selection
  const request = new AbortController(); controller = request; loading.value = true
  try {
    const data = await getGroundMrMonitoring(selectedMrId.value, {
      run_id: selectedRunId.value, data_mode: 'HISTORICAL_PLAYBACK',
      start_time: start.toISOString(), end_time: end.toISOString(), loss_limit: '3', loss_offset: '0',
    }, { signal: request.signal })
    if (current !== generation) return
    result.value = data; fullStart.value = data.queried_start; fullEnd.value = data.queried_end
    visibleStart.value = data.queried_start; visibleEnd.value = data.queried_end; lossPage.value = 1
  } catch (reason) { if (!request.signal.aborted) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (controller === request) controller = null; if (current === generation) loading.value = false }
}

async function queryQuickPing(): Promise<void> {
  if (!result.value || quickLoading.value) return
  const request = new AbortController()
  controller = request
  quickError.value = ''
  try {
    await loadHistoricalQuickPing(fullStart.value, fullEnd.value, generation, request.signal)
    if (!request.signal.aborted && !quickError.value) quickLoaded.value = true
  } finally {
    if (controller === request) controller = null
  }
}

async function loadHistoricalQuickPing(start: string, end: string, current: number, signal: AbortSignal): Promise<void> {
  const mrId = selectedMrId.value
  const addresses = [
    { key: 'primary' as const, ip: result.value?.mr.management_ip || '' },
    { key: 'backup' as const, ip: result.value?.mr.backup_management_ip || '' },
  ].filter((item) => item.ip)
  if (!mrId || !addresses.length) return
  quickLoading.value = true
  try {
    const page = await listGroundQuickPing(100, { signal }, { start_time: start, end_time: end, mr_id: mrId })
    const completed = page.items.filter((run) => !['RUNNING', 'STOPPING'].includes(run.state))
    const rows: Record<'primary' | 'backup', Array<Record<string, unknown>>> = { primary: [], backup: [] }
    const buckets: Record<'primary' | 'backup', Array<Record<string, unknown>>> = { primary: [], backup: [] }
    await Promise.all(addresses.map(async ({ key, ip }) => {
      const matchingRuns = completed.filter((run) => run.targets.some((target) => target.mr_id === mrId && target.target_ip === ip))
      for (const run of matchingRuns) {
        if (signal.aborted) return
        const samplePage = await getGroundQuickPingSamples(run.run_id, {
          target_ip: ip, start_time: start, end_time: end, limit: 2000,
        }, { signal })
        const page = {
          rows: samplePage.items.map((sample) => ({
            ...sample,
            quick_run_id: run.run_id,
            received_at: sample.received_at || sample.ts,
            target_ip: sample.target_ip || ip,
            source: 'REAL_QUICK_PING',
          })),
          buckets: (samplePage.second_loss_buckets || []).map((bucket) => ({ ...bucket, target_ip: ip })),
        }
        rows[key].push(...page.rows)
        buckets[key].push(...page.buckets)
      }
    }))
    if (current === generation && !signal.aborted) {
      quickRows.value = rows
      quickBuckets.value = buckets
      quickError.value = ''
    }
  } catch (reason) {
    if (current === generation && !signal.aborted) quickError.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    if (current === generation) quickLoading.value = false
  }
}
async function loadVisibleEvents(page = 1): Promise<void> {
  if (!result.value || !selectedMrId.value) return
  eventController?.abort(); const request = new AbortController(); eventController = request; const current = generation
  try {
    const data = await getGroundMrMonitoring(selectedMrId.value, {
      run_id: selectedRunId.value, data_mode: 'HISTORICAL_PLAYBACK',
      start_time: visibleStart.value, end_time: visibleEnd.value, loss_limit: '3', loss_offset: String((page - 1) * 3),
    }, { signal: request.signal })
    if (current === generation && !request.signal.aborted) { eventResult.value = data; lossPage.value = page }
  } catch { /* Main playback remains usable when the bounded event query is interrupted. */ }
  finally { if (eventController === request) eventController = null }
}
function changeViewport(value: { start: string; end: string }): void {
  visibleStart.value = value.start; visibleEnd.value = value.end; eventResult.value = null; lossPage.value = 1
  if (eventTimer) clearTimeout(eventTimer)
  eventTimer = setTimeout(() => { void loadVisibleEvents(1) }, 250)
}
function updateCursor(value: string): void { cursorTime.value = value }
function locate(value: string): void {
  const stamp = Date.parse(value), fullBegin = Date.parse(fullStart.value), fullFinish = Date.parse(fullEnd.value)
  if (!Number.isFinite(stamp) || !Number.isFinite(fullBegin) || !Number.isFinite(fullFinish)) return
  const currentBegin = Date.parse(visibleStart.value), currentFinish = Date.parse(visibleEnd.value)
  const span = Number.isFinite(currentBegin) && Number.isFinite(currentFinish) && currentFinish > currentBegin
    ? currentFinish - currentBegin : Math.min(fullFinish - fullBegin, 10 * 60 * 1000)
  const half = span / 2
  const start = Math.max(fullBegin, Math.min(stamp - half, fullFinish - span))
  changeViewport({ start: new Date(start).toISOString(), end: new Date(Math.min(fullFinish, start + span)).toISOString() })
  cursorTime.value = value
}
function clearTimeline(): void {
  timelineRequest?.abort()
  timelineRequest = null
  timelinePage.value = null
  timelineError.value = ''
  timelineLoading.value = false
  timelineCursors.value = ['']
  timelinePageIndex.value = 0
}

const timelineFilters = computed(() => {
  const selection = selectedRange()
  if (!props.active || !selection) return null
  const [start, end] = selection
  return {
    run_id: selectedRunId.value,
    data_type: 'timeline',
    start_at: start.toISOString(),
    end_at: end.toISOString(),
    ...(timelineMrOnly.value && selectedMrId.value ? { mr_id: selectedMrId.value } : {}),
    ...(timelineEventType.value.trim() ? { event_type: timelineEventType.value.trim() } : {}),
  }
})
watch([timelineEventType, timelineMrOnly], clearTimeline, { flush: 'sync' })

async function loadTimeline(cursor = '', pageIndex = 0): Promise<void> {
  const filters = timelineFilters.value
  if (!filters) {
    timelineError.value = '请在当前运行内选择不超过 24 小时的时间范围'
    return
  }
  timelineRequest?.abort()
  const request = new AbortController()
  timelineRequest = request
  timelineLoading.value = true
  timelineError.value = ''
  try {
    const page = await listGroundHistory({
      ...filters,
      page_size: 25,
      include_total: false,
      cursor,
    }, { signal: request.signal })
    if (!request.signal.aborted) {
      timelinePage.value = page
      timelinePageIndex.value = pageIndex
      timelineCursors.value[pageIndex] = cursor
    }
  } catch (reason) {
    if (!request.signal.aborted) timelineError.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    if (timelineRequest === request) {
      timelineRequest = null
      timelineLoading.value = false
    }
  }
}
async function exportTimeline(): Promise<void> {
  const filters = timelineFilters.value
  const site = activeSiteContext.value?.siteId
  if (!filters || !site || timelineExporting.value || !isFeatureEnabled(historyExportFeature)) return
  timelineExporting.value = true
  try {
    await submitExportAfterDestinationSelected({
      action: 'rail.ground_history',
      suggestedName: `ground_timeline_${filters.start_at.slice(0, 10)}.csv`,
      context: filters,
      submit: () => startGroundHistoryExport(filters, site),
      taskId: (task) => task.task_id,
    })
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : String(reason))
  } finally {
    timelineExporting.value = false
  }
}
watch([range, () => props.active, () => timelineMrOnly.value ? selectedMrId.value : ''], clearTimeline, { flush: 'sync' })
watch([selectedMrId, range, () => props.active], () => {
  generation++
  controller?.abort()
  eventController?.abort()
  if (eventTimer) clearTimeout(eventTimer)
  loading.value = false
  quickLoading.value = false
  quickLoaded.value = false
  error.value = ''
  quickError.value = ''
  result.value = null
  eventResult.value = null
  quickRows.value = { primary: [], backup: [] }
  quickBuckets.value = { primary: [], backup: [] }
  cursorTime.value = ''
}, { flush: 'sync' })
onBeforeUnmount(() => { stopRequests(); clearTimeline() })
</script>

<template>
  <section class="playback-workspace">
    <div class="playback-toolbar">
      <el-select :model-value="siteId" disabled aria-label="Site"><el-option :label="siteId || '未注册 Site'" :value="siteId" /></el-select>
      <el-select :model-value="siteId" disabled aria-label="线路"><el-option label="当前 Site 注册线路" :value="siteId" /></el-select>
      <el-select v-model="selectedRunId" filterable placeholder="运行日期">
        <el-option v-for="run in runs" :key="run.run_id" :label="`${run.run_date} · ${runStateLabel(run.state)} · ${format(run.actual_started_at).split(' ').at(-1)}`" :value="run.run_id" />
      </el-select>
      <el-select v-model="selectedMrId" filterable :loading="historyLoading" placeholder="列车 / MR">
        <el-option v-for="mr in mrOptions" :key="mr.id" :label="`${mr.trainNo || mr.trainId} · ${mr.role} · ${mr.name || mr.id}`" :value="mr.id" />
      </el-select>
      <el-date-picker v-model="range" type="datetimerange" start-placeholder="开始时间" end-placeholder="结束时间" />
      <el-button type="primary" :loading="loading" @click="query">查询回放</el-button>
      <el-button @click="applyRunRange">重置时间</el-button>
      <el-button v-if="selectedRun" @click="emit('view-syslog', selectedRun.run_id)">查看历史 Syslog</el-button>
      <el-button v-if="selectedRun" type="danger" plain :loading="deleting" @click="emit('delete-run', selectedRun)">删除历史记录</el-button>
    </div>
    <div v-if="selectedRun" class="timeline-controls">
      <el-input v-model="timelineEventType" clearable aria-label="事件类型" placeholder="事件类型，如 mesh_linkup" @keyup.enter="loadTimeline()" />
      <el-checkbox v-model="timelineMrOnly" :disabled="!selectedMrId">仅所选 MR</el-checkbox>
      <el-button :loading="timelineLoading" @click="loadTimeline()">查询时间轴</el-button>
      <el-button v-if="isFeatureVisible(historyExportFeature)" :loading="timelineExporting" :disabled="!timelinePage?.items.length || !isFeatureEnabled(historyExportFeature) || hasActiveExportAction('rail.ground_history')" @click="exportTimeline">导出时间轴</el-button>
    </div>
    <el-alert v-if="timelineError" :title="timelineError" type="error" :closable="false" />
    <section v-if="timelinePage" aria-label="历史时间轴">
      <el-table :data="timelinePage.items" row-key="record_id" max-height="360" empty-text="当前条件没有事件">
        <el-table-column prop="ts" label="时间" min-width="170" />
        <el-table-column prop="event_type" label="事件" min-width="120" />
        <el-table-column prop="summary" label="详情" min-width="200" />
      </el-table>
      <div class="timeline-controls">
        <el-button :disabled="timelineLoading || timelinePageIndex === 0" @click="loadTimeline(timelineCursors[timelinePageIndex - 1], timelinePageIndex - 1)">上一页</el-button>
        <span>第 {{ timelinePageIndex + 1 }} 页</span>
        <el-button :disabled="timelineLoading || !timelinePage.has_more" @click="loadTimeline(timelinePage.next_cursor, timelinePageIndex + 1)">下一页</el-button>
      </div>
    </section>
    <el-alert v-if="historyError" :title="historyError" type="warning" :closable="false" />
    <p v-if="selectedRun" class="playback-boundary">
      {{ format(selectedRun.actual_started_at) }} 至 {{ format(selectedRun.actual_ended_at) }} ·
      {{ selectedRun.archive_status === 'READY' ? '归档已就绪' : '持久化运行索引' }} ·
      Run 登记 Ping 样本 {{ selectedRun.ping_sample_count ?? '—' }}
    </p>
    <p class="playback-boundary">历史回放只读取已落盘数据，不启动采集。独立采集流按所选 MR 和时间范围显示来源。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="result">
      <div class="playback-identity">
        <b>{{ selectedMr?.trainNo || result.mr.train_no }} · {{ selectedMr?.role || result.mr.role }}</b>
        <span>主用 {{ result.mr.management_ip || '无数据' }}</span><span>备用 {{ result.mr.backup_management_ip || '无数据' }}</span>
        <span>可视窗口 {{ format(visibleStart) }} — {{ format(visibleEnd) }}</span>
        <span>Heartbeat 数据源 {{ result.series.diagnostics.source_run_id || result.series.diagnostics.requested_run_id || '无数据' }}<template v-if="result.series.diagnostics.source_reason"> · {{ result.series.diagnostics.source_reason }}</template></span>
      </div>
      <section class="navigator"><h3>全局时间窗口</h3><p class="navigator-range">{{ format(visibleStart) }} — {{ format(visibleEnd) }}</p><MrMonitoringChart mode="navigator" :data="result" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /></section>
      <section v-if="primaryData" class="track"><button class="track-toggle" @click="primaryPingExpanded = !primaryPingExpanded"><b>主用管理 IP · 通断状态</b><span>{{ primaryPingExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="primaryPingExpanded" class="track-body"><div class="heartbeat-stats"><span>正常连通 {{ primaryHeartbeatStats.success }}</span><span>不通/超时 {{ primaryHeartbeatStats.failure }}</span><span>未知 {{ primaryHeartbeatStats.unknown }}</span><span>连通率 {{ primaryHeartbeatStats.connectivityRate == null ? '暂无数据' : `${primaryHeartbeatStats.connectivityRate.toFixed(2)}%` }}</span></div><MrMonitoringChart mode="heartbeat" :data="primaryData" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /><p v-if="!primaryData.series.points.length" class="empty">当前时间范围没有 Heartbeat 采样数据</p></div></Transition></section>
      <section v-if="backupData" class="track backup-track"><button class="track-toggle" @click="backupPingExpanded = !backupPingExpanded"><b>备用管理 IP · 通断状态</b><span>{{ backupPingExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="backupPingExpanded" class="track-body"><div class="heartbeat-stats"><span>正常连通 {{ backupHeartbeatStats.success }}</span><span>不通/超时 {{ backupHeartbeatStats.failure }}</span><span>未知 {{ backupHeartbeatStats.unknown }}</span><span>连通率 {{ backupHeartbeatStats.connectivityRate == null ? '暂无数据' : `${backupHeartbeatStats.connectivityRate.toFixed(2)}%` }}</span></div><MrMonitoringChart mode="heartbeat" :data="backupData" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /><p v-if="!backupData.series.points.length" class="empty">当前时间范围没有 Heartbeat 采样数据</p></div></Transition></section>
      <el-button v-if="!quickLoaded" :loading="quickLoading" @click="queryQuickPing">加载归档 Quick Ping</el-button>
      <el-alert v-if="quickError" :title="quickError" type="error" :closable="false" />
      <p v-if="quickLoaded && !primaryQuickRows.length && !backupQuickRows.length" class="empty">所选 MR 和时间范围没有专用 Quick Ping 历史记录。</p>
      <section v-if="primaryQuickRows.length" class="track quick-replay-track"><button class="track-toggle track-heading" @click="primaryQuickExpanded = !primaryQuickExpanded"><h3>主地址 Quick Ping <el-tag size="small" type="success">真实归档数据</el-tag></h3><span>{{ primaryQuickExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="primaryQuickExpanded" class="track-body"><QuickPingChart :rows="primaryQuickRows" :second-loss-buckets="primaryQuickBuckets" :interval-ms="1000" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :selected-time="cursorTime" :active="active" @viewport-change="changeViewport" @cursor-change="updateCursor" /><div class="quick-stats"><span>Ping 总数 {{ primaryQuickStats.ping_total }}</span><span>成功 {{ primaryQuickStats.ping_success }}</span><span>丢包 {{ primaryQuickStats.ping_lost }} ({{ primaryQuickStats.packet_loss_rate == null ? '无数据' : `${primaryQuickStats.packet_loss_rate.toFixed(2)}%` }})</span><span>平均 RTT {{ primaryQuickStats.average_rtt_ms == null ? '无数据' : `${primaryQuickStats.average_rtt_ms.toFixed(2)} ms` }}</span><span>最小 / 最大 RTT {{ primaryQuickStats.min_rtt_ms ?? '无数据' }} / {{ primaryQuickStats.max_rtt_ms ?? '无数据' }} ms</span></div></div></Transition></section>
      <section v-if="backupQuickRows.length" class="track quick-replay-track"><button class="track-toggle track-heading" @click="backupQuickExpanded = !backupQuickExpanded"><h3>备用地址 Quick Ping <el-tag size="small" type="success">真实归档数据</el-tag></h3><span>{{ backupQuickExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="backupQuickExpanded" class="track-body"><QuickPingChart :rows="backupQuickRows" :second-loss-buckets="backupQuickBuckets" :interval-ms="1000" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :selected-time="cursorTime" :active="active" @viewport-change="changeViewport" @cursor-change="updateCursor" /><div class="quick-stats"><span>Ping 总数 {{ backupQuickStats.ping_total }}</span><span>成功 {{ backupQuickStats.ping_success }}</span><span>丢包 {{ backupQuickStats.ping_lost }} ({{ backupQuickStats.packet_loss_rate == null ? '无数据' : `${backupQuickStats.packet_loss_rate.toFixed(2)}%` }})</span><span>平均 RTT {{ backupQuickStats.average_rtt_ms == null ? '无数据' : `${backupQuickStats.average_rtt_ms.toFixed(2)} ms` }}</span><span>最小 / 最大 RTT {{ backupQuickStats.min_rtt_ms ?? '无数据' }} / {{ backupQuickStats.max_rtt_ms ?? '无数据' }} ms</span></div></div></Transition></section>
      <section class="track"><button class="track-toggle" @click="peerExpanded = !peerExpanded"><b>Peer AP 主用区间 · 原始 RSSI</b><span>{{ peerExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="peerExpanded" class="track-body"><MrMonitoringChart mode="peer" :data="result" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /><p v-if="!result.peer_intervals.length" class="empty">当前窗口无可由相邻切换记录证明的 Peer AP 区间。</p></div></Transition></section>
      <div class="event-grid">
        <section><h3>当前可视窗口最近 3 次主链路切换</h3><button v-for="event in recentSwitchEvents" :key="event.id" class="event-row" @click="locate(event.event_time)"><b>{{ event.old_ap_name || event.old_bssid || '无数据' }} → {{ event.new_ap_name || event.bssid || '无数据' }}</b><span>{{ format(event.event_time) }} · {{ event.bssid || '无 MAC' }} · {{ event.data_quality || '无数据' }}</span><span>切入 RSSI {{ event.raw_rssi ?? '无记录' }} · 切出 RSSI {{ event.previous_rssi ?? '无记录' }}</span></button><p v-if="!recentSwitchEvents.length" class="empty">无切换记录</p></section>
        <section><details><summary><b>丢包事件 · 当前窗口最近 3 条</b><span>{{ lossTotal }} 条</span></summary><button v-for="event in lossEvents" :key="String(event.id || event.event_key)" class="event-row" @click="locate(String(event.started_at || ''))"><b>{{ lossStateLabel(event.state) }} · {{ event.target_ip || '无 IP' }}</b><span>开始 {{ format(event.started_at) }} · 恢复 {{ format(event.ended_at) }}</span><span>丢包 {{ event.loss_count ?? '无数据' }} · {{ event.ap_name || '无 AP' }}</span></button><p v-if="!lossEvents.length" class="empty">无丢包事件</p><el-pagination v-if="lossTotal > 3" small layout="prev, pager, next" :page-size="3" :total="lossTotal" :current-page="lossPage" @current-change="loadVisibleEvents" /></details></section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.timeline-controls{display:flex;align-items:center;flex-wrap:wrap;gap:10px}
.timeline-controls .el-input{width:270px}
.playback-workspace{display:flex;flex-direction:column;gap:14px;min-width:0}.playback-toolbar{display:grid;grid-template-columns:140px 160px minmax(180px,1fr) minmax(220px,1.2fr) minmax(330px,1.4fr) auto;gap:10px;align-items:center}.playback-boundary,.empty{margin:0;color:var(--el-text-color-secondary);font-size:13px}.playback-identity{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:12px;border:1px solid var(--el-border-color-light);border-radius:8px;background:var(--el-fill-color-lighter)}.track,.navigator,.event-grid>section{border:1px solid var(--el-border-color-light);border-radius:8px;padding:12px;min-width:0}.track h3,.navigator h3,.event-grid h3{margin:0 0 10px;font-size:14px}.track-toggle,summary{display:flex;width:100%;justify-content:space-between;border:0;background:transparent;color:inherit;padding:0;cursor:pointer}.track-heading{display:flex;justify-content:space-between;align-items:center;gap:10px}.track-heading h3{display:flex;align-items:center;gap:8px}.simulated-badge{font-size:11px;color:var(--el-color-warning)}.quick-stats,.heartbeat-stats{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--el-text-color-secondary)}.event-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.event-row{display:flex;width:100%;flex-direction:column;gap:4px;text-align:left;border:0;border-bottom:1px solid var(--el-border-color-lighter);background:transparent;color:inherit;padding:9px 4px;cursor:pointer}.event-row span,summary span{font-size:12px;color:var(--el-text-color-secondary)}@media(max-width:1200px){.playback-toolbar{grid-template-columns:1fr 1fr}.event-grid{grid-template-columns:1fr}}
.navigator{border-color:var(--el-color-primary-light-5);background:var(--el-fill-color-lighter);box-shadow:0 0 0 1px color-mix(in srgb,var(--el-color-primary),transparent 82%)}.navigator-range{margin:-4px 0 4px;color:var(--el-color-primary);font-size:12px;font-weight:600}.track-body{min-width:0}.chart-collapse-enter-active,.chart-collapse-leave-active{max-height:920px;overflow:hidden;transition:max-height .22s ease,opacity .18s ease}.chart-collapse-enter-from,.chart-collapse-leave-to{max-height:0;opacity:0}
</style>
