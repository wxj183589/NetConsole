<script setup lang="ts">
import { ref } from 'vue'

import { cancelRailTransitTask, exportMeshAnalysisReport, exportOnlineMrReport, importMeshAnalysis, listOnlineTrains, queryOnlineMrMetrics, startCarNetworkDiagnostic, refreshTracksideBusiness } from '../../api/railTransitWeb'
import type { MeshImportProfile, OnlineMrMetricSeries, RailTransitTask } from '../../types/railTransitWeb'

const sessionId = ref('')
const meshSessionId = ref('')
const trainId = ref('')
const mrId = ref('')
const displayName = ref('')
const selectedFiles = ref<File[]>([])
const metrics = ref<OnlineMrMetricSeries[]>([])
const trainPayload = ref<Record<string, unknown> | null>(null)
const task = ref<RailTransitTask | null>(null)
const error = ref('')

function selectFiles(event: Event): void { selectedFiles.value = Array.from((event.target as HTMLInputElement).files || []) }
async function loadOnlineTrains(): Promise<void> { trainPayload.value = await listOnlineTrains() }
async function startCarCheck(): Promise<void> { task.value = await startCarNetworkDiagnostic(trainId.value) }
async function refreshTrackside(): Promise<void> { task.value = await refreshTracksideBusiness() }
async function importLogs(): Promise<void> {
  const profile: MeshImportProfile = { mr_id: mrId.value, display_name: displayName.value, safe_folder_name: mrId.value }
  task.value = await importMeshAnalysis(selectedFiles.value, profile)
}
async function loadMetrics(): Promise<void> { metrics.value = await queryOnlineMrMetrics(sessionId.value) }
async function exportReport(): Promise<void> { task.value = await exportOnlineMrReport(sessionId.value) }
async function exportMeshReport(): Promise<void> { task.value = await exportMeshAnalysisReport(meshSessionId.value) }
async function cancelTask(): Promise<void> { if (task.value) task.value = await cancelRailTransitTask(task.value.task_id) }
</script>

<template>
  <section class="rail-web-parity">
    <header><p class="eyebrow">RAIL TRANSIT WEB · TASK + ARTIFACT</p><h1>轨交诊断与 MR 分析入口</h1><p>导入、解析、报告和导出均返回任务 ID，关闭页面后仍可在任务中心跟踪。</p></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <div class="grid"><el-card shadow="never"><template #header>列车在线与车内通信</template><div class="row"><el-input v-model="trainId" placeholder="列车 ID（可选）" /><el-button @click="loadOnlineTrains">列车在线情况</el-button><el-button type="primary" @click="startCarCheck">开始车内通信检测</el-button></div><pre v-if="trainPayload">{{ JSON.stringify(trainPayload, null, 2) }}</pre></el-card><el-card shadow="never"><template #header>轨旁 AP 业务</template><p>沿用轨旁 AP 正式查询与刷新任务，业务层不在 Vue 重写身份或规则。</p><el-button @click="refreshTrackside">刷新轨旁 AP 业务</el-button></el-card></div>
    <el-card shadow="never"><template #header>MR 原始日志导入</template><div class="row"><el-input v-model="mrId" placeholder="MR ID" /><el-input v-model="displayName" placeholder="显示名称" /><input type="file" multiple accept=".log,.txt" @change="selectFiles"><el-button type="primary" :disabled="!selectedFiles.length" @click="importLogs">提交受控导入</el-button></div></el-card>
    <el-card shadow="never"><template #header>Online MR 链路与报告</template><div class="row"><el-input v-model="sessionId" placeholder="Session ID" /><el-button @click="loadMetrics">读取指标</el-button><el-button @click="exportReport">提交报告导出</el-button></div><el-table :data="metrics" empty-text="暂无指标"><el-table-column prop="metric_type" label="指标" /><el-table-column prop="series_key" label="序列" /><el-table-column prop="summary.count" label="点数" /></el-table></el-card>
    <el-card shadow="never"><template #header>离线 MESH 报告</template><div class="row"><el-input v-model="meshSessionId" placeholder="MESH Session ID" /><el-button @click="exportMeshReport">提交报告导出</el-button></div></el-card>
    <el-alert v-if="task" type="info" :title="`${task.action} · ${task.task_id} · ${task.status}`" :closable="false"><el-button size="small" @click="cancelTask">取消任务</el-button></el-alert>
  </section>
</template>

<style scoped>
.rail-web-parity { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.eyebrow { color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: .08em; }.rail-web-parity h1 { margin: 4px 0; }.rail-web-parity header p:last-child { color: var(--el-text-color-secondary); }.grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 16px; }.row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }.row .el-input { width: 190px; }pre { max-height: 230px; overflow: auto; margin-top: 14px; padding: 10px; background: var(--el-fill-color-light); }@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
