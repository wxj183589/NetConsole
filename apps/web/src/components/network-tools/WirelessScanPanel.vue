<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelWirelessTask,
  createWirelessProject,
  deleteWirelessProject,
  exportWirelessScan,
  getWirelessExportArtifact,
  getWirelessTask,
  listWirelessAdapters,
  listWirelessProjects,
  listWirelessResults,
  listWirelessRuns,
  listWirelessTasks,
  startWirelessScan,
} from '../../api/networkTools'
import { downloadBackendResource } from '../../platform/runtime'
import type { NetworkToolTask, WirelessAdapter, WirelessProject, WirelessScanRun } from '../../types/networkTools'

const adapters = ref<WirelessAdapter[]>([])
const projects = ref<WirelessProject[]>([])
const runs = ref<WirelessScanRun[]>([])
const results = ref<Record<string, unknown>[]>([])
const runPage = ref(1)
const runPageSize = 50
const runTotal = ref(0)
const resultPage = ref(1)
const resultPageSize = 100
const resultTotal = ref(0)
const selectedRun = ref<WirelessScanRun | null>(null)
const task = ref<NetworkToolTask | null>(null)
const exportTaskState = ref<NetworkToolTask | null>(null)
const loading = ref(false)
const form = reactive({ adapter_guid: '', project_id: '', project_name: '', project_description: '' })
let timer: number | null = null
let downloadedExportTaskId = ''
const SCAN_TASK_KEY = 'netconsole.wireless-scan.task-id'
const EXPORT_TASK_KEY = 'netconsole.wireless-scan.export-task-id'
const ACTIVE_STATUSES = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING']

const rowKeys = computed(() => {
  const keys: string[] = []
  for (const row of results.value) for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key)
  return keys
})
const running = computed(() => task.value && ACTIVE_STATUSES.includes(task.value.status))
const exportRunning = computed(() => exportTaskState.value && ACTIVE_STATUSES.includes(exportTaskState.value.status))

onMounted(async () => {
  await refresh()
  await recoverTasks()
})

onBeforeUnmount(() => stopPolling())

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [loadedAdapters, loadedProjects, runPageResult] = await Promise.all([
      listWirelessAdapters(),
      listWirelessProjects(),
      listWirelessRuns(runPage.value, runPageSize),
    ])
    adapters.value = loadedAdapters
    projects.value = loadedProjects
    runs.value = runPageResult.items
    runTotal.value = runPageResult.total
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描数据加载失败')
  } finally {
    loading.value = false
  }
}

async function deleteProject(): Promise<void> {
  const project = projects.value.find((item) => item.project_id === form.project_id)
  if (!project) return
  if (running.value) {
    ElMessage.warning('存在进行中的无线扫描，请先停止后再删除项目')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除项目“${project.name}”？已有扫描历史会保留项目名称和说明快照。`,
      '删除无线扫描项目',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await deleteWirelessProject(project.project_id)
    projects.value = projects.value.filter((item) => item.project_id !== project.project_id)
    form.project_id = ''
    ElMessage.success('无线扫描项目已删除，历史记录保持可辨识')
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描项目删除失败')
  }
}

async function createProject(): Promise<void> {
  if (!form.project_name.trim()) return
  try {
    const project = await createWirelessProject(form.project_name.trim(), form.project_description.trim())
    projects.value.unshift(project)
    form.project_id = project.project_id
    form.project_name = ''
    form.project_description = ''
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描项目创建失败')
  }
}

async function startScan(): Promise<void> {
  try {
    const adapter = adapters.value.find((item) => item.guid === form.adapter_guid)
    const response = await startWirelessScan({ adapter_name: adapter?.name || '', adapter_guid: form.adapter_guid, project_id: form.project_id })
    task.value = response.task
    window.localStorage.setItem(SCAN_TASK_KEY, response.task.id)
    startPolling()
    ElMessage.success(`无线扫描已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描启动失败')
  }
}

function startPolling(): void {
  if (timer !== null) return
  timer = window.setInterval(async () => {
    try {
      if (task.value) task.value = await getWirelessTask(task.value.id)
      if (exportTaskState.value) exportTaskState.value = await getWirelessTask(exportTaskState.value.id)
      await finishRecoveredTasks()
      if (!running.value && !exportRunning.value) stopPolling()
    } catch {
      stopPolling()
    }
  }, 1000)
}

function stopPolling(): void {
  if (timer !== null) window.clearInterval(timer)
  timer = null
}

async function selectRun(run: WirelessScanRun): Promise<void> {
  selectedRun.value = run
  resultPage.value = 1
  results.value = []
  resultTotal.value = 0
  await loadResults()
}

async function loadResults(): Promise<void> {
  if (!selectedRun.value) return
  try {
    const page = await listWirelessResults(selectedRun.value.scan_id, resultPage.value, resultPageSize)
    results.value = page.items
    resultTotal.value = page.total
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描结果加载失败')
  }
}

async function changeRunPage(page: number): Promise<void> {
  runPage.value = page
  try {
    const response = await listWirelessRuns(runPage.value, runPageSize)
    runs.value = response.items
    runTotal.value = response.total
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描历史分页加载失败')
  }
}

async function changeResultPage(page: number): Promise<void> {
  resultPage.value = page
  await loadResults()
}

async function exportRun(format: 'csv' | 'xlsx'): Promise<void> {
  const run = selectedRun.value || runs.value[0]
  if (!run) return
  try {
    const response = await exportWirelessScan(run.scan_id, format)
    exportTaskState.value = response.task
    window.localStorage.setItem(EXPORT_TASK_KEY, response.task.id)
    startPolling()
    ElMessage.success(`无线扫描导出任务已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描导出失败')
  }
}

async function cancelScan(): Promise<void> {
  if (!task.value) return
  try {
    task.value = await cancelWirelessTask(task.value.id)
    startPolling()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描停止失败')
  }
}

async function cancelExport(): Promise<void> {
  if (!exportTaskState.value) return
  try {
    exportTaskState.value = await cancelWirelessTask(exportTaskState.value.id)
    startPolling()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描导出停止失败')
  }
}

async function recoverTasks(): Promise<void> {
  try {
    const tasks = await listWirelessTasks()
    const scanTaskId = window.localStorage.getItem(SCAN_TASK_KEY)
    const exportTaskId = window.localStorage.getItem(EXPORT_TASK_KEY)
    task.value = scanTaskId ? tasks.find((item) => item.id === scanTaskId) || await getWirelessTask(scanTaskId) : tasks.find((item) => item.type === 'network_tools.wireless_scan' && ACTIVE_STATUSES.includes(item.status)) || null
    exportTaskState.value = exportTaskId ? tasks.find((item) => item.id === exportTaskId) || await getWirelessTask(exportTaskId) : tasks.find((item) => item.type === 'network_tools.wireless_export' && ACTIVE_STATUSES.includes(item.status)) || null
    await finishRecoveredTasks()
    if (running.value || exportRunning.value) startPolling()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描任务恢复失败')
  }
}

async function finishRecoveredTasks(): Promise<void> {
  if (task.value && !ACTIVE_STATUSES.includes(task.value.status)) {
    window.localStorage.removeItem(SCAN_TASK_KEY)
    if (task.value.status === 'COMPLETED') {
      runPage.value = 1
      await refresh()
    }
  }
  const currentExport = exportTaskState.value
  if (!currentExport || ACTIVE_STATUSES.includes(currentExport.status)) return
  if (currentExport.status !== 'COMPLETED') {
    window.localStorage.removeItem(EXPORT_TASK_KEY)
    return
  }
  if (downloadedExportTaskId === currentExport.id) return
  const artifact = await getWirelessExportArtifact(currentExport.id)
  const result = await downloadBackendResource({ apiPath: artifact.download_url, suggestedName: artifact.filename })
  if (result.status === 'failed') throw new Error(result.error || '无线扫描导出下载失败')
  if (result.status === 'cancelled') return
  downloadedExportTaskId = currentExport.id
  window.localStorage.removeItem(EXPORT_TASK_KEY)
  ElMessage.success(`无线扫描导出完成，SHA-256：${artifact.sha256}`)
}
</script>

<template>
  <el-card shadow="never">
    <template #header><div class="header"><div><h2>无线扫描</h2><p>独立于无线勘测，使用 Fake Adapter 可做 Web 闭环验收。</p></div><el-button :loading="loading" @click="refresh">刷新</el-button></div></template>
    <div class="toolbar">
      <el-select v-model="form.adapter_guid" clearable placeholder="选择无线网卡"><el-option v-for="adapter in adapters" :key="adapter.guid || adapter.name" :label="adapter.display_name" :value="adapter.guid" /></el-select>
      <el-select v-model="form.project_id" clearable placeholder="扫描项目"><el-option v-for="project in projects" :key="project.project_id" :label="project.name" :value="project.project_id" /></el-select>
      <el-button v-if="form.project_id" type="danger" plain :disabled="!!running" @click="deleteProject">删除所选项目</el-button>
      <el-button type="primary" :loading="!!running" @click="startScan">开始扫描</el-button>
    </div>
    <el-collapse>
      <el-collapse-item title="新建扫描项目" name="project"><div class="project-form"><el-input v-model="form.project_name" placeholder="项目名称" /><el-input v-model="form.project_description" placeholder="说明（可选）" /><el-button @click="createProject">创建</el-button></div></el-collapse-item>
    </el-collapse>
    <el-alert v-if="task" :title="`${task.name}：${task.status} ${task.message}`" :type="running ? 'info' : task.status === 'COMPLETED' ? 'success' : 'warning'" show-icon :closable="false"><el-button v-if="running" link type="danger" @click="cancelScan">停止扫描</el-button></el-alert>
    <el-progress v-if="task" :percentage="task.progress" :status="task.status === 'FAILED' ? 'exception' : task.status === 'COMPLETED' ? 'success' : undefined" />
    <div v-if="exportTaskState" class="task-progress"><span>{{ exportTaskState.name }}：{{ exportTaskState.status }}</span><el-progress :percentage="exportTaskState.progress" :status="exportTaskState.status === 'FAILED' ? 'exception' : exportTaskState.status === 'COMPLETED' ? 'success' : undefined" /><el-button v-if="exportRunning" link type="danger" @click="cancelExport">停止导出</el-button></div>
    <el-divider />
    <el-table :data="runs" empty-text="暂无无线扫描记录" stripe @row-click="selectRun">
      <el-table-column prop="scan_id" label="扫描 ID" min-width="230" /><el-table-column prop="project_name" label="项目" min-width="140" /><el-table-column prop="project_description" label="项目说明" min-width="180" show-overflow-tooltip /><el-table-column prop="adapter_name" label="无线网卡" min-width="160" /><el-table-column prop="network_count" label="结果数" width="90" /><el-table-column prop="status" label="状态" width="100" />
    </el-table>
    <el-pagination v-if="runTotal > runPageSize" v-model:current-page="runPage" :total="runTotal" :page-size="runPageSize" layout="prev, pager, next, total" @current-change="changeRunPage" />
    <div class="actions"><el-button v-if="runs.length" link type="primary" @click="exportRun('csv')">导出 CSV</el-button><el-button v-if="runs.length" link type="primary" @click="exportRun('xlsx')">导出 XLSX</el-button></div>
    <el-table v-if="results.length" :data="results" stripe max-height="420"><el-table-column v-for="key in rowKeys" :key="key" :prop="key" :label="key" min-width="140" /></el-table>
    <el-pagination v-if="resultTotal > resultPageSize" v-model:current-page="resultPage" :total="resultTotal" :page-size="resultPageSize" layout="prev, pager, next, total" @current-change="changeResultPage" />
  </el-card>
</template>

<style scoped>
.header { align-items: center; display: flex; justify-content: space-between; gap: 16px; }
.header h2 { margin: 0 0 4px; }
.header p { color: var(--el-text-color-secondary); margin: 0; }
.toolbar, .project-form, .actions { display: flex; gap: 10px; flex-wrap: wrap; }
.toolbar { margin-bottom: 14px; }
.actions { margin-top: 12px; }
.task-progress { margin-top: 12px; }
</style>
