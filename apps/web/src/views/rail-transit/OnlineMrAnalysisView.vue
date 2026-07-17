<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getOnlineMrSession, listRecentOnlineMrSessions } from '../../api/onlineMr'
import {
  exportOnlineMrReport,
  getRailTransitTask,
  queryOnlineMrMetrics,
  queryOnlineMrTimeline,
  recoverRailTransitTasks,
} from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import type { OnlineMrSessionDetail, OnlineMrSessionSummary } from '../../types/onlineMr'
import type { OnlineMrMetricSeries, OnlineMrTimelineEvent, RailTransitTask } from '../../types/railTransitWeb'

const route = useRoute()
const router = useRouter()
const storageKey = 'netconsole.online-mr-analysis.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const sessions = ref<OnlineMrSessionSummary[]>([])
const sessionId = ref('')
const detail = ref<OnlineMrSessionDetail | null>(null)
const metrics = ref<OnlineMrMetricSeries[]>([])
const timeline = ref<OnlineMrTimelineEvent[]>([])
const metricTypes = ref(['rssi', 'ctl_busy', 'ping_rtt', 'ping_loss', 'iperf_bitrate'])
const task = ref<RailTransitTask | null>(null)
const outputName = ref('')
const loading = ref(false)
const taskLoading = ref(false)
const error = ref('')
let pollTimer: number | undefined

const metricRows = computed(() => metrics.value.map((series) => ({
  metric_type: series.metric_type,
  series_key: series.series_key || '默认序列',
  count: series.summary.count,
  minimum: series.summary.minimum,
  average: series.summary.average,
  maximum: series.summary.maximum,
  latest: [...series.points].reverse().find((point) => point.value !== null || point.text_value)?.value
    ?? [...series.points].reverse().find((point) => point.text_value)?.text_value
    ?? null,
})))

function message(cause: unknown, fallback: string): string { return cause instanceof Error ? cause.message : fallback }
function display(value: unknown): string { return value === null || value === undefined || value === '' ? '无数据' : String(value) }
function rememberTask(value: RailTransitTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getRailTransitTask(task.value!.task_id)); poll() }
    catch (cause) { error.value = message(cause, 'Online MR 报告任务读取失败') }
  }, 1000)
}

async function loadSessions(): Promise<void> {
  loading.value = true; error.value = ''
  try {
    sessions.value = await listRecentOnlineMrSessions(100)
    const requested = typeof route.query.session_id === 'string' ? route.query.session_id : ''
    sessionId.value = sessions.value.find((item) => item.session_id === requested)?.session_id || sessionId.value || sessions.value[0]?.session_id || ''
    if (sessionId.value) await loadAnalysis()
  } catch (cause) { error.value = message(cause, 'Online MR 会话列表加载失败') }
  finally { loading.value = false }
}
async function loadAnalysis(): Promise<void> {
  if (!sessionId.value) return
  loading.value = true; error.value = ''
  try {
    const [nextDetail, nextMetrics, nextTimeline] = await Promise.all([
      getOnlineMrSession(sessionId.value),
      queryOnlineMrMetrics(sessionId.value, metricTypes.value),
      queryOnlineMrTimeline(sessionId.value),
    ])
    detail.value = nextDetail; metrics.value = nextMetrics; timeline.value = nextTimeline
  } catch (cause) { error.value = message(cause, 'Online MR 分析数据加载失败') }
  finally { loading.value = false }
}
async function startReport(): Promise<void> {
  if (!detail.value || !isFeatureEnabled('web.online_mr_report_export')) return
  taskLoading.value = true; error.value = ''
  try { rememberTask(await exportOnlineMrReport(detail.value.session_id, outputName.value)); poll(); openTaskWindow() }
  catch (cause) { error.value = message(cause, 'Online MR 报告生成启动失败') }
  finally { taskLoading.value = false }
}
async function recoverTask(): Promise<void> {
  try {
    const saved = localStorage.getItem(storageKey) || ''
    const rows = await recoverRailTransitTasks()
    rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => item.action === 'online_mr_report') || null)
    poll()
  } catch (cause) { error.value = message(cause, 'Online MR 报告任务恢复失败') }
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}

onMounted(() => { void Promise.all([loadSessions(), recoverTask()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="analysis-page">
    <header class="page-heading"><div><p class="eyebrow">RAIL TRANSIT · ONLINE MR ANALYSIS</p><h1>车载 MR 收集分析</h1><p>读取正式会话数据库，汇总 RSSI、Channel Busy、fping、丢包、iPerf 与时间线，并通过 Export Process 生成报告。</p></div><div class="actions"><el-select v-model="sessionId" filterable placeholder="选择 Online MR 会话" style="width:360px" @change="loadAnalysis"><el-option v-for="item in sessions" :key="item.session_id" :label="`${item.device_name || item.mr_name} · ${item.status} · ${item.started_at || item.session_id}`" :value="item.session_id" /></el-select><el-button :loading="loading" @click="loadSessions">刷新</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTask">恢复报告任务</el-button></el-alert>
    <el-empty v-if="!detail && !loading" description="当前局点暂无 Online MR 会话" />
    <template v-if="detail">
      <div class="summary-grid"><article><span>会话状态</span><strong>{{ detail.status }}</strong></article><article><span>MR</span><strong>{{ detail.device_name || detail.mr_name }}</strong></article><article><span>完整性</span><strong>{{ detail.data_integrity }}</strong></article><article><span>执行端</span><strong>{{ detail.executor_kind || '无数据' }}</strong></article><article><span>采集时长</span><strong>{{ display(detail.duration_minutes) }} min</strong></article></div>
      <div class="content-card"><div class="toolbar"><strong>指标</strong><el-checkbox-group v-model="metricTypes"><el-checkbox label="rssi">RSSI</el-checkbox><el-checkbox label="ctl_busy">Channel Busy</el-checkbox><el-checkbox label="ping_rtt">fping RTT</el-checkbox><el-checkbox label="ping_loss">丢包</el-checkbox><el-checkbox label="iperf_bitrate">iPerf</el-checkbox></el-checkbox-group><el-button type="primary" :loading="loading" @click="loadAnalysis">重新查询</el-button></div><el-table :data="metricRows" border stripe empty-text="所选会话暂无结构化指标"><el-table-column prop="metric_type" label="指标" width="150" /><el-table-column prop="series_key" label="序列" min-width="220" /><el-table-column prop="count" label="样本" width="90" /><el-table-column label="最小"><template #default="{ row }">{{ display(row.minimum) }}</template></el-table-column><el-table-column label="平均"><template #default="{ row }">{{ display(row.average) }}</template></el-table-column><el-table-column label="最大"><template #default="{ row }">{{ display(row.maximum) }}</template></el-table-column><el-table-column label="最近"><template #default="{ row }">{{ display(row.latest) }}</template></el-table-column></el-table></div>
      <div class="content-card"><h2>会话时间线</h2><el-table :data="timeline" border stripe height="360" empty-text="暂无会话事件"><el-table-column prop="local_time" label="本地时间" width="185" /><el-table-column prop="device_time" label="设备时间" width="185" /><el-table-column prop="source" label="来源" width="130" /><el-table-column prop="event_type" label="事件" width="130" /><el-table-column prop="severity" label="级别" width="90" /><el-table-column prop="title" label="说明" min-width="240" /></el-table></div>
      <div class="content-card report-card"><div><h2>分析报告</h2><p>报告由 Export Process 生成；停止、日志、Artifact 保存和打开操作统一在任务窗口完成。</p></div><div class="report-actions"><el-input v-model="outputName" placeholder="可选报告文件名" /><el-button type="primary" :loading="taskLoading" :disabled="!isFeatureEnabled('web.online_mr_report_export')" @click="startReport">生成 XLSX 报告</el-button><el-button @click="openTaskWindow">打开任务窗口</el-button></div><el-alert v-if="task" :title="`${task.status} · ${task.error_message || task.message || task.task_id}`" :type="task.status === 'FAILED' ? 'error' : 'info'" :closable="false" /></div>
    </template>
  </section>
</template>

<style scoped>
.analysis-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.report-actions{display:flex;align-items:center;gap:12px}.page-heading{justify-content:space-between}.page-heading h1,.content-card h2{margin:2px 0 6px}.page-heading p,.report-card p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:18px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{flex-wrap:wrap;margin-bottom:12px}.report-card{display:flex;flex-direction:column;gap:14px}.report-actions .el-input{width:320px}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}}
</style>
