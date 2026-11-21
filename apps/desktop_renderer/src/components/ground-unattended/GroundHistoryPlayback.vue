<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getGroundMrMonitoring } from '../../api/groundUnattended'
import type { GroundMrMonitoring, GroundRun, GroundTrain } from '../../types/groundUnattended'
import MrMonitoringChart from './MrMonitoringChart.vue'
import QuickPingChart from './QuickPingChart.vue'
import { generateSimulatedQuickPing, simulatedQuickPingStats, type SimulatedQuickPingRow } from './quickPingReplay'

const props = defineProps<{ siteId: string; runs: GroundRun[]; trains: GroundTrain[]; active: boolean }>()
interface MrOption { id: string; role: string; name: string; trainId: string; trainNo: string }
const selectedRunId = ref(''), selectedMrId = ref(''), range = ref<Date[]>([])
const result = ref<GroundMrMonitoring | null>(null), loading = ref(false), error = ref('')
const fullStart = ref(''), fullEnd = ref(''), visibleStart = ref(''), visibleEnd = ref(''), cursorTime = ref('')
const primaryPingExpanded = ref(true), backupPingExpanded = ref(true), primaryQuickExpanded = ref(true), backupQuickExpanded = ref(true), peerExpanded = ref(true)
const lossPage = ref(1), eventResult = ref<GroundMrMonitoring | null>(null)
let controller: AbortController | null = null, eventController: AbortController | null = null, eventTimer: ReturnType<typeof setTimeout> | undefined, generation = 0

const mrOptions = computed<MrOption[]>(() => {
  const items: MrOption[] = []
  for (const train of props.trains) for (const endpoint of train.endpoints || []) {
    if (!endpoint.mr_id || items.some((item) => item.id === endpoint.mr_id)) continue
    items.push({ id: endpoint.mr_id, role: endpoint.endpoint, name: endpoint.mr_name, trainId: train.train_id, trainNo: train.train_no })
  }
  return items.sort((a, b) => `${a.trainNo}-${a.role}`.localeCompare(`${b.trainNo}-${b.role}`, 'zh-CN', { numeric: true }))
})
const selectedRun = computed(() => props.runs.find((item) => item.run_id === selectedRunId.value))
const selectedMr = computed(() => mrOptions.value.find((item) => item.id === selectedMrId.value))
const displayEvents = computed(() => eventResult.value || result.value)
const recentSwitchEvents = computed(() => (displayEvents.value?.mesh_events || []).slice().sort((a, b) => Date.parse(b.event_time) - Date.parse(a.event_time)).slice(0, 3))
const lossEvents = computed(() => displayEvents.value?.loss_events || [])
const lossTotal = computed(() => displayEvents.value?.loss_event_total || 0)

function monitoringDataFor(targetIp: string): GroundMrMonitoring | null {
  if (!result.value || !targetIp) return null
  return { ...result.value, series: { ...result.value.series, points: result.value.series.points.filter((point) => point.target_ip === targetIp) } }
}
const primaryData = computed(() => monitoringDataFor(result.value?.mr.management_ip || ''))
const backupData = computed(() => monitoringDataFor(result.value?.mr.backup_management_ip || ''))
function quickPingRows(targetIp: string): SimulatedQuickPingRow[] {
  if (!result.value || !targetIp) return []
  return generateSimulatedQuickPing(props.siteId, result.value.mr.train_id, result.value.mr.mr_uuid, selectedRunId.value, targetIp, fullStart.value, fullEnd.value)
}
const primaryQuickRows = computed(() => quickPingRows(result.value?.mr.management_ip || ''))
const backupQuickRows = computed(() => quickPingRows(result.value?.mr.backup_management_ip || ''))
const primaryQuickStats = computed(() => simulatedQuickPingStats(primaryQuickRows.value))
const backupQuickStats = computed(() => simulatedQuickPingStats(backupQuickRows.value))

function format(value: unknown): string {
  const date = new Date(String(value || ''))
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '—'
}
function lossStateLabel(value: unknown): string {
  return ({ OPEN: '丢包中', ACTIVE: '持续异常', RECOVERED: '已恢复', CLOSED: '已恢复' } as Record<string, string>)[String(value || '').toUpperCase()] || '未知'
}
function stopRequests(): void {
  generation++; controller?.abort(); eventController?.abort(); controller = null; eventController = null
  if (eventTimer) clearTimeout(eventTimer)
}
function applyRunRange(): void {
  const run = selectedRun.value
  if (!run) return
  const start = new Date(run.actual_started_at || run.scheduled_start_at || run.created_at)
  const rawEnd = new Date(run.actual_ended_at || run.scheduled_end_at || run.updated_at)
  const end = Number.isFinite(rawEnd.getTime()) && rawEnd > start ? rawEnd : new Date(start.getTime() + 60 * 60 * 1000)
  range.value = [start, new Date(Math.min(end.getTime(), start.getTime() + 86_400_000))]
}
watch(() => props.runs, (rows) => {
  if (!selectedRunId.value && rows.length) { selectedRunId.value = rows[0]!.run_id; applyRunRange() }
}, { immediate: true })
watch(selectedRunId, () => { applyRunRange(); result.value = null; eventResult.value = null })
watch(mrOptions, (rows) => { if (!rows.some((row) => row.id === selectedMrId.value)) selectedMrId.value = rows[0]?.id || '' }, { immediate: true })

async function query(): Promise<void> {
  stopRequests(); const current = generation; error.value = ''; result.value = null; eventResult.value = null
  if (!selectedMrId.value || range.value.length !== 2) { error.value = '请选择 MR 和时间范围'; return }
  const start = range.value[0]!, end = range.value[1]!
  if (!(start < end) || end.getTime() - start.getTime() > 86_400_000) { error.value = '时间范围必须为正且不超过 24 小时'; return }
  const request = new AbortController(); controller = request; loading.value = true
  try {
    const data = await getGroundMrMonitoring(selectedMrId.value, {
      start_time: start.toISOString(), end_time: end.toISOString(), loss_limit: '3', loss_offset: '0',
    }, { signal: request.signal })
    if (current !== generation) return
    result.value = data; fullStart.value = data.queried_start; fullEnd.value = data.queried_end
    visibleStart.value = data.queried_start; visibleEnd.value = data.queried_end; lossPage.value = 1
  } catch (reason) { if (!request.signal.aborted) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (controller === request) controller = null; if (current === generation) loading.value = false }
}
async function loadVisibleEvents(page = 1): Promise<void> {
  if (!result.value || !selectedMrId.value) return
  eventController?.abort(); const request = new AbortController(); eventController = request; const current = generation
  try {
    const data = await getGroundMrMonitoring(selectedMrId.value, {
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
onBeforeUnmount(stopRequests)
</script>

<template>
  <section class="playback-workspace">
    <div class="playback-toolbar">
      <el-select :model-value="siteId" disabled aria-label="Site"><el-option :label="siteId || '未注册 Site'" :value="siteId" /></el-select>
      <el-select :model-value="siteId" disabled aria-label="线路"><el-option label="当前 Site 注册线路" :value="siteId" /></el-select>
      <el-select v-model="selectedRunId" filterable placeholder="运行日期">
        <el-option v-for="run in runs" :key="run.run_id" :label="`${run.run_date} · ${run.state}`" :value="run.run_id" />
      </el-select>
      <el-select v-model="selectedMrId" filterable placeholder="列车 / MR">
        <el-option v-for="mr in mrOptions" :key="mr.id" :label="`${mr.trainNo || mr.trainId} · ${mr.role} · ${mr.name || mr.id}`" :value="mr.id" />
      </el-select>
      <el-date-picker v-model="range" type="datetimerange" start-placeholder="开始时间" end-placeholder="结束时间" />
      <el-button type="primary" :loading="loading" @click="query">查询回放</el-button>
      <el-button @click="applyRunRange">重置时间</el-button>
    </div>
    <p class="playback-boundary">历史回放只读取已落盘数据，不启动采集、不访问设备、不补造缺失字段。所选运行仅定义回放时间上下文，各数据源按实际时间戳对齐。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="result">
      <div class="playback-identity">
        <b>{{ selectedMr?.trainNo || result.mr.train_no }} · {{ selectedMr?.role || result.mr.role }}</b>
        <span>主用 {{ result.mr.management_ip || '无数据' }}</span><span>备用 {{ result.mr.backup_management_ip || '无数据' }}</span>
        <span>可视窗口 {{ format(visibleStart) }} — {{ format(visibleEnd) }}</span>
      </div>
      <section class="navigator"><h3>全局时间窗口</h3><p class="navigator-range">{{ format(visibleStart) }} — {{ format(visibleEnd) }}</p><MrMonitoringChart mode="navigator" :data="result" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /></section>
      <section v-if="primaryData" class="track"><button class="track-toggle" @click="primaryPingExpanded = !primaryPingExpanded"><b>主用管理 IP · RTT / 单包丢包</b><span>{{ primaryPingExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="primaryPingExpanded" class="track-body"><MrMonitoringChart mode="ping" :data="primaryData" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /><p v-if="!primaryData.series.points.length" class="empty">当前窗口无主用地址采样。</p></div></Transition></section>
      <section v-if="backupData" class="track backup-track"><button class="track-toggle" @click="backupPingExpanded = !backupPingExpanded"><b>备用管理 IP · RTT / 单包丢包</b><span>{{ backupPingExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="backupPingExpanded" class="track-body"><MrMonitoringChart mode="ping" :data="backupData" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /><p v-if="!backupData.series.points.length" class="empty">当前窗口无备用地址采样。</p></div></Transition></section>
      <section v-if="primaryQuickRows.length" class="track quick-replay-track"><button class="track-toggle track-heading" @click="primaryQuickExpanded = !primaryQuickExpanded"><h3>主地址 Quick Ping <el-tag size="small" type="warning">模拟 Quick Ping</el-tag></h3><span>{{ primaryQuickExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="primaryQuickExpanded" class="track-body"><el-tooltip content="仅在 Renderer 内确定性生成，不访问网络、不写入历史数据库。"><span class="simulated-badge">SIMULATED_QUICK_PING</span></el-tooltip><QuickPingChart :rows="primaryQuickRows" :interval-ms="1000" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :selected-time="cursorTime" :active="active" @viewport-change="changeViewport" @cursor-change="updateCursor" /><div class="quick-stats"><span>发包 {{ primaryQuickStats.sent }}</span><span>收包 {{ primaryQuickStats.received }}</span><span>丢包 {{ primaryQuickStats.lost }} ({{ primaryQuickStats.lossRate.toFixed(2) }}%)</span><span>RTT {{ primaryQuickStats.min ?? '—' }} / {{ primaryQuickStats.average?.toFixed(1) ?? '—' }} / {{ primaryQuickStats.max ?? '—' }} ms</span><span>累计丢包时间 {{ primaryQuickStats.lostSeconds }}s</span></div></div></Transition></section>
      <section v-if="backupQuickRows.length" class="track quick-replay-track"><button class="track-toggle track-heading" @click="backupQuickExpanded = !backupQuickExpanded"><h3>备用地址 Quick Ping <el-tag size="small" type="warning">模拟 Quick Ping</el-tag></h3><span>{{ backupQuickExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="backupQuickExpanded" class="track-body"><el-tooltip content="仅在 Renderer 内确定性生成，不访问网络、不写入历史数据库。"><span class="simulated-badge">SIMULATED_QUICK_PING</span></el-tooltip><QuickPingChart :rows="backupQuickRows" :interval-ms="1000" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :selected-time="cursorTime" :active="active" @viewport-change="changeViewport" @cursor-change="updateCursor" /><div class="quick-stats"><span>发包 {{ backupQuickStats.sent }}</span><span>收包 {{ backupQuickStats.received }}</span><span>丢包 {{ backupQuickStats.lost }} ({{ backupQuickStats.lossRate.toFixed(2) }}%)</span><span>RTT {{ backupQuickStats.min ?? '—' }} / {{ backupQuickStats.average?.toFixed(1) ?? '—' }} / {{ backupQuickStats.max ?? '—' }} ms</span><span>累计丢包时间 {{ backupQuickStats.lostSeconds }}s</span></div></div></Transition></section>
      <section class="track"><button class="track-toggle" @click="peerExpanded = !peerExpanded"><b>Peer AP 主用区间 · RSSI (dBm)</b><span>{{ peerExpanded ? '收起' : '展开' }}</span></button><Transition name="chart-collapse"><div v-if="peerExpanded" class="track-body"><MrMonitoringChart mode="peer" :data="result" :start="fullStart" :end="fullEnd" :visible-start="visibleStart" :visible-end="visibleEnd" :active="active" :selected-time="cursorTime" @viewport-change="changeViewport" @cursor-change="updateCursor" /><p v-if="!result.peer_intervals.length" class="empty">当前窗口无可由相邻切换记录证明的 Peer AP 区间。</p></div></Transition></section>
      <div class="event-grid">
        <section><h3>当前可视窗口最近 3 次切换</h3><button v-for="event in recentSwitchEvents" :key="event.id" class="event-row" @click="locate(event.event_time)"><b>{{ event.old_ap_name || event.old_bssid || '无数据' }} → {{ event.new_ap_name || event.bssid || '无数据' }}</b><span>{{ format(event.event_time) }} · {{ event.bssid || '无 MAC' }} · {{ event.data_quality || 'UNKNOWN' }}</span><span>原始 RSSI {{ event.raw_rssi ?? '无数据' }} · {{ event.rssi ?? '无数据' }} dBm</span></button><p v-if="!recentSwitchEvents.length" class="empty">无切换记录</p></section>
        <section><details><summary><b>丢包事件 · 当前窗口最近 3 条</b><span>{{ lossTotal }} 条</span></summary><button v-for="event in lossEvents" :key="String(event.id || event.event_key)" class="event-row" @click="locate(String(event.started_at || ''))"><b>{{ lossStateLabel(event.state) }} · {{ event.target_ip || '无 IP' }}</b><span>开始 {{ format(event.started_at) }} · 恢复 {{ format(event.ended_at) }}</span><span>丢包 {{ event.loss_count ?? '无数据' }} · {{ event.ap_name || '无 AP' }}</span></button><p v-if="!lossEvents.length" class="empty">无丢包事件</p><el-pagination v-if="lossTotal > 3" small layout="prev, pager, next" :page-size="3" :total="lossTotal" :current-page="lossPage" @current-change="loadVisibleEvents" /></details></section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.playback-workspace{display:flex;flex-direction:column;gap:14px;min-width:0}.playback-toolbar{display:grid;grid-template-columns:140px 160px minmax(180px,1fr) minmax(220px,1.2fr) minmax(330px,1.4fr) auto;gap:10px;align-items:center}.playback-boundary,.empty{margin:0;color:var(--el-text-color-secondary);font-size:13px}.playback-identity{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:12px;border:1px solid var(--el-border-color-light);border-radius:8px;background:var(--el-fill-color-lighter)}.track,.navigator,.event-grid>section{border:1px solid var(--el-border-color-light);border-radius:8px;padding:12px;min-width:0}.track h3,.navigator h3,.event-grid h3{margin:0 0 10px;font-size:14px}.track-toggle,summary{display:flex;width:100%;justify-content:space-between;border:0;background:transparent;color:inherit;padding:0;cursor:pointer}.track-heading{display:flex;justify-content:space-between;align-items:center;gap:10px}.track-heading h3{display:flex;align-items:center;gap:8px}.simulated-badge{font-size:11px;color:var(--el-color-warning)}.quick-stats{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--el-text-color-secondary)}.event-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.event-row{display:flex;width:100%;flex-direction:column;gap:4px;text-align:left;border:0;border-bottom:1px solid var(--el-border-color-lighter);background:transparent;color:inherit;padding:9px 4px;cursor:pointer}.event-row span,summary span{font-size:12px;color:var(--el-text-color-secondary)}@media(max-width:1200px){.playback-toolbar{grid-template-columns:1fr 1fr}.event-grid{grid-template-columns:1fr}}
.navigator{border-color:var(--el-color-primary-light-5);background:var(--el-fill-color-lighter);box-shadow:0 0 0 1px color-mix(in srgb,var(--el-color-primary),transparent 82%)}.navigator-range{margin:-4px 0 4px;color:var(--el-color-primary);font-size:12px;font-weight:600}.track-body{min-width:0}.chart-collapse-enter-active,.chart-collapse-leave-active{max-height:920px;overflow:hidden;transition:max-height .22s ease,opacity .18s ease}.chart-collapse-enter-from,.chart-collapse-leave-to{max-height:0;opacity:0}
</style>
