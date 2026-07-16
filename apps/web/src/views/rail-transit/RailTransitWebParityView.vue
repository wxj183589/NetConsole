<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  cancelRailTransitTask,
  exportMeshAnalysisReport,
  exportOnlineMrReport,
  getRailTransitTask,
  importMeshAnalysis,
  listOnlineTrains,
  meshAnalysisReportDownloadRequest,
  onlineMrReportDownloadRequest,
  queryOnlineMrMetrics,
  recoverRailTransitTasks,
  startCarNetworkDiagnostic,
} from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import { downloadBackendResource } from '../../platform/runtime'
import type { MeshImportProfile, OnlineMrMetricSeries, OnlineTrainRow, RailTransitTask } from '../../types/railTransitWeb'

const taskStorageKey = 'netconsole.rail-web.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const sessionId = ref('')
const meshSessionId = ref('')
const trainId = ref('')
const mrId = ref('')
const displayName = ref('')
const selectedFiles = ref<File[]>([])
const metrics = ref<OnlineMrMetricSeries[]>([])
const onlineTrains = ref<OnlineTrainRow[]>([])
const task = ref<RailTransitTask | null>(null)
const error = ref('')
const loading = ref(false)
let pollTimer: number | undefined

const taskSummary = computed(() => Object.entries(task.value?.result_summary || {}).map(([key, value]) => ({ key, value: String(value) })))
const canDownloadTask = computed(() => {
  if (task.value?.action === 'mesh_analysis_report') return isFeatureEnabled('web.mesh_analysis_report_export')
  if (task.value?.action === 'online_mr_report') return isFeatureEnabled('web.online_mr_report_export')
  return false
})

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

function rememberTask(value: RailTransitTask | null): void {
  task.value = value
  if (value) localStorage.setItem(taskStorageKey, value.task_id)
  else localStorage.removeItem(taskStorageKey)
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function schedulePolling(): void {
  stopPolling()
  if (!isFeatureEnabled('web.rail_task_control') || !task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try {
      rememberTask(await getRailTransitTask(task.value!.task_id))
      schedulePolling()
    } catch (cause) {
      error.value = message(cause, '轨交任务状态读取失败')
    }
  }, 1000)
}

async function recoverTask(): Promise<void> {
  if (!isFeatureEnabled('web.rail_task_control')) return
  const savedTaskId = localStorage.getItem(taskStorageKey) || ''
  try {
    const recovered = await recoverRailTransitTasks()
    const selected = recovered.find((item) => item.task_id === savedTaskId)
      || recovered.find((item) => !terminalStates.has(item.status))
      || recovered[0]
    rememberTask(selected || null)
    schedulePolling()
  } catch (cause) {
    error.value = message(cause, '轨交任务恢复失败')
  }
}

async function startTask(factory: () => Promise<RailTransitTask>, fallback: string): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    rememberTask(await factory())
    schedulePolling()
  } catch (cause) {
    error.value = message(cause, fallback)
  } finally {
    loading.value = false
  }
}

function selectFiles(event: Event): void {
  selectedFiles.value = Array.from((event.target as HTMLInputElement).files || [])
}

async function loadOnlineTrains(): Promise<void> {
  loading.value = true
  error.value = ''
  try { onlineTrains.value = (await listOnlineTrains()).items }
  catch (cause) { error.value = message(cause, '列车在线情况加载失败') }
  finally { loading.value = false }
}

function startCarCheck(): void {
  void startTask(() => startCarNetworkDiagnostic(trainId.value), '车内通信检测启动失败')
}

function importLogs(): void {
  const profile: MeshImportProfile = { mr_id: mrId.value, display_name: displayName.value, safe_folder_name: mrId.value }
  void startTask(() => importMeshAnalysis(selectedFiles.value, profile), 'MESH 日志导入启动失败')
}

async function loadMetrics(): Promise<void> {
  loading.value = true
  error.value = ''
  try { metrics.value = await queryOnlineMrMetrics(sessionId.value) }
  catch (cause) { error.value = message(cause, 'Online MR 指标加载失败') }
  finally { loading.value = false }
}

function exportReport(): void {
  void startTask(() => exportOnlineMrReport(sessionId.value), 'Online MR 报告导出启动失败')
}

function exportMeshReport(): void {
  void startTask(() => exportMeshAnalysisReport(meshSessionId.value), 'MESH 报告导出启动失败')
}

async function cancelTask(): Promise<void> {
  if (!task.value || terminalStates.has(task.value.status)) return
  await startTask(() => cancelRailTransitTask(task.value!.task_id), '轨交任务取消失败')
}

async function downloadArtifact(): Promise<void> {
  if (!task.value?.available || !task.value.artifact_id) return
  loading.value = true
  error.value = ''
  try {
    if (task.value.action === 'mesh_analysis_report') {
      const result = await downloadBackendResource(meshAnalysisReportDownloadRequest(task.value.artifact_id))
      if (result.status === 'failed') throw new Error(result.error || 'MESH 报告下载失败')
    } else if (task.value.action === 'online_mr_report') {
      const result = await downloadBackendResource(onlineMrReportDownloadRequest(task.value.artifact_id))
      if (result.status === 'failed') throw new Error(result.error || 'Online MR 报告下载失败')
    }
    else throw new Error('当前任务没有可下载报告')
  } catch (cause) {
    error.value = message(cause, '轨交报告下载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadOnlineTrains()
  if (isFeatureEnabled('web.rail_task_control')) void recoverTask()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="rail-web-parity">
    <header><p class="eyebrow">RAIL TRANSIT WEB · BOUNDED ENTRY</p><h1>轨交诊断与 MR 任务入口</h1><p>本页恢复自身任务与受控报告；既有 Online MR、MESH 详情和轨旁业务页面继续作为正式展示入口。</p></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button link @click="recoverTask">重试任务恢复</el-button></el-alert>
    <el-card shadow="never"><template #header>在线列车（{{ onlineTrains.length }}）</template><div class="row"><el-input v-model="trainId" placeholder="列车 ID（可选）" /><el-button :loading="loading" @click="loadOnlineTrains">重新加载</el-button><el-button type="primary" :loading="loading" :disabled="!isFeatureEnabled('web.rail_car_network_diagnostic_execute') || !isFeatureEnabled('web.rail_task_control')" @click="startCarCheck">开始车内通信检测</el-button></div><el-table :data="onlineTrains" height="280" empty-text="暂无在线列车"><el-table-column prop="train_no" label="列车" /><el-table-column prop="train_name" label="名称" /><el-table-column prop="communication_status" label="通信状态" /><el-table-column prop="current_mesh_links" label="MESH 链路" /><el-table-column prop="active_sessions" label="活动会话" /><el-table-column prop="warning_count" label="告警" /><el-table-column prop="last_updated_at" label="更新时间" /></el-table></el-card>
    <el-card v-if="isFeatureEnabled('web.mesh_analysis_import')" shadow="never"><template #header>MR 原始日志导入</template><div class="row"><el-input v-model="mrId" placeholder="MR ID" /><el-input v-model="displayName" placeholder="显示名称" /><input type="file" multiple accept=".log,.txt" @change="selectFiles"><el-button type="primary" :loading="loading" :disabled="!selectedFiles.length || !mrId || !displayName || !isFeatureEnabled('web.rail_task_control')" @click="importLogs">提交受控导入</el-button></div></el-card>
    <el-card shadow="never"><template #header>Online MR 指标与报告</template><div class="row"><el-input v-model="sessionId" placeholder="Session ID" /><el-button :loading="loading" @click="loadMetrics">读取指标</el-button><el-button :loading="loading" :disabled="!isFeatureEnabled('web.online_mr_report_export') || !isFeatureEnabled('web.rail_task_control')" @click="exportReport">提交报告导出</el-button></div><el-table :data="metrics" empty-text="暂无指标"><el-table-column prop="metric_type" label="指标" /><el-table-column prop="series_key" label="序列" /><el-table-column prop="summary.count" label="点数" /></el-table></el-card>
    <el-card v-if="isFeatureEnabled('web.mesh_analysis_report_export')" shadow="never"><template #header>离线 MESH 报告</template><div class="row"><el-input v-model="meshSessionId" placeholder="MESH Session ID" /><el-button :loading="loading" :disabled="!isFeatureEnabled('web.rail_task_control')" @click="exportMeshReport">提交报告导出</el-button></div></el-card>
    <el-card v-if="task" shadow="never"><template #header>任务 {{ task.task_id }}</template><el-descriptions :column="3" border><el-descriptions-item label="动作">{{ task.action }}</el-descriptions-item><el-descriptions-item label="状态">{{ task.status }}</el-descriptions-item><el-descriptions-item label="消息">{{ task.error_message || task.message || '—' }}</el-descriptions-item><el-descriptions-item label="Artifact">{{ task.artifact_id || '—' }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ task.sha256 || '—' }}</el-descriptions-item><el-descriptions-item label="大小">{{ task.size_bytes }}</el-descriptions-item></el-descriptions><el-table v-if="taskSummary.length" :data="taskSummary" size="small"><el-table-column prop="key" label="结果项" /><el-table-column prop="value" label="值" /></el-table><div class="row task-actions"><el-button :disabled="terminalStates.has(task.status) || !isFeatureEnabled('web.rail_task_control')" @click="cancelTask">取消任务</el-button><el-button :disabled="!task.available || !canDownloadTask" @click="downloadArtifact">受控下载</el-button></div></el-card>
  </section>
</template>

<style scoped>
.rail-web-parity { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.eyebrow { color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: .08em; }.rail-web-parity h1 { margin: 4px 0; }.rail-web-parity header p:last-child { color: var(--el-text-color-secondary); }.row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }.row .el-input { width: 190px; }.task-actions { margin-top: 12px; }
</style>
