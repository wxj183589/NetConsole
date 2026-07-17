<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelWirelessTask,
  createWirelessProject,
  deleteWirelessProject,
  exportWirelessScan,
  getWirelessExportArtifact,
  getWirelessRunDetail,
  getWirelessTask,
  listWirelessAdapters,
  listWirelessProjects,
  listWirelessResults,
  listWirelessRuns,
  startWirelessScan,
} from '../../api/networkTools'
import { downloadBackendResource } from '../../platform/runtime'
import { useTaskStore } from '../../stores/tasks'
import type { NetworkToolTask, WirelessAdapter, WirelessProject, WirelessScanRun, WirelessScanRunDetail } from '../../types/networkTools'
import type { TaskItem } from '../../types/task'

const taskStore = useTaskStore()
const adapters = ref<WirelessAdapter[]>([])
const projects = ref<WirelessProject[]>([])
const runs = ref<WirelessScanRun[]>([])
const results = ref<Record<string, unknown>[]>([])
const runPage = ref(1)
const runPageSize = 50
const runTotal = ref(0)
const resultTotal = ref(0)
const resultPage = ref(1)
const resultPageSize = ref(100)
const selectedRun = ref<WirelessScanRun | null>(null)
const runDetail = ref<WirelessScanRunDetail | null>(null)
const selectedResult = ref<Record<string, unknown> | null>(null)
const selectedTask = ref<NetworkToolTask | null>(null)
const loading = ref(false)
const form = reactive({
  adapter_guid: '',
  project_id: '',
  project_name: '',
  project_description: '',
  scan_source: 'auto' as 'auto' | 'hybrid' | 'wlan_api' | 'netsh',
  auto_refresh: false,
  refresh_interval: 5,
  only_trackside: false,
  band: '',
  radio: '',
  search: '',
})
let autoRefreshTimer: number | null = null
const ACTIVE_STATUSES = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING']
const tasks = computed(() => taskStore.tasks.filter((item) => item.owner === 'web_network_tools' && ['network_tools.wireless_scan', 'network_tools.wireless_export'].includes(item.type)))
const runningTask = computed(() => tasks.value.find((item) => item.type === 'network_tools.wireless_scan' && ACTIVE_STATUSES.includes(item.status)) || null)
const selectedTaskSummary = computed(() => tasks.value.find((item) => item.id === selectedTask.value?.id) || selectedTask.value)
const selectedTaskRunning = computed(() => selectedTaskSummary.value && ACTIVE_STATUSES.includes(selectedTaskSummary.value.status))
const selectedExportCompleted = computed(() => selectedTaskSummary.value?.type === 'network_tools.wireless_export' && selectedTaskSummary.value.status === 'COMPLETED')
const detailVisible = computed({
  get: () => selectedResult.value !== null,
  set: (value: boolean) => { if (!value) selectedResult.value = null },
})
const rowKeys = computed(() => {
  const keys: string[] = []
  for (const row of results.value) for (const key of Object.keys(row)) if (!keys.includes(key) && !key.endsWith('_json')) keys.push(key)
  return keys
})

onMounted(async () => {
  await Promise.all([refresh(), taskStore.refresh()])
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})

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

async function createProject(): Promise<void> {
  if (!form.project_name.trim()) return
  try {
    const project = await createWirelessProject(form.project_name.trim(), form.project_description.trim())
    projects.value.unshift(project)
    form.project_id = project.project_id
    form.project_name = form.project_description = ''
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描项目创建失败')
  }
}

async function deleteProject(): Promise<void> {
  const project = projects.value.find((item) => item.project_id === form.project_id)
  if (!project) return
  try {
    await ElMessageBox.confirm(`确认删除项目“${project.name}”？已有扫描历史会保留项目快照。`, '删除无线扫描项目', { type: 'warning' })
    await deleteWirelessProject(project.project_id)
    projects.value = projects.value.filter((item) => item.project_id !== project.project_id)
    form.project_id = ''
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描项目删除失败')
  }
}

async function startScan(notify = true): Promise<void> {
  if (runningTask.value) return
  try {
    const adapter = adapters.value.find((item) => item.guid === form.adapter_guid)
    const response = await startWirelessScan({
      adapter_name: adapter?.name || '',
      adapter_guid: form.adapter_guid,
      project_id: form.project_id,
      scan_source: form.scan_source,
    })
    selectedTask.value = response.task
    await taskStore.refresh()
    if (notify) ElMessage.success(`无线扫描已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描启动失败')
  }
}

async function stopScan(): Promise<void> {
  form.auto_refresh = false
  stopAutoRefresh()
  const current = runningTask.value
  if (!current) return
  try {
    selectedTask.value = await cancelWirelessTask(current.id)
    await taskStore.refresh()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描停止失败')
  }
}

function toggleAutoRefresh(): void {
  stopAutoRefresh()
  if (!form.auto_refresh) return
  autoRefreshTimer = window.setInterval(() => {
    if (!runningTask.value) void startScan(false)
  }, form.refresh_interval * 1000)
}

function stopAutoRefresh(): void {
  if (autoRefreshTimer !== null) window.clearInterval(autoRefreshTimer)
  autoRefreshTimer = null
}

async function selectRun(run: WirelessScanRun): Promise<void> {
  selectedRun.value = run
  resultPage.value = 1
  results.value = []
  resultTotal.value = 0
  try {
    const [page, detail] = await Promise.all([
      loadResultPage(run.scan_id),
      getWirelessRunDetail(run.scan_id),
    ])
    results.value = page.items
    resultTotal.value = page.total
    runDetail.value = detail
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描结果加载失败')
  }
}

function loadResultPage(scanId = selectedRun.value?.scan_id || '') {
  return listWirelessResults(scanId, resultPage.value, resultPageSize.value, {
    only_trackside: form.only_trackside,
    band: form.band,
    radio: form.radio,
    search: form.search.trim(),
  })
}

async function applyResultFilters(): Promise<void> {
  if (!selectedRun.value) return
  resultPage.value = 1
  await changeResultPage(1)
}

async function changeResultPage(page: number): Promise<void> {
  if (!selectedRun.value) return
  resultPage.value = page
  try {
    const result = await loadResultPage()
    results.value = result.items
    resultTotal.value = result.total
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描结果加载失败')
  }
}

async function changeResultPageSize(size: number): Promise<void> {
  resultPageSize.value = size
  await applyResultFilters()
}

async function changeRunPage(page: number): Promise<void> {
  runPage.value = page
  await refresh()
}

async function exportRun(format: 'csv' | 'xlsx'): Promise<void> {
  const run = selectedRun.value || runs.value[0]
  if (!run) return
  try {
    const response = await exportWirelessScan(run.scan_id, format)
    selectedTask.value = response.task
    await taskStore.refresh()
    ElMessage.success(`无线扫描导出任务已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描导出失败')
  }
}

async function selectTask(task: TaskItem): Promise<void> {
  try {
    selectedTask.value = await getWirelessTask(task.id)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描任务详情加载失败')
  }
}

async function cancelSelectedTask(): Promise<void> {
  if (!selectedTask.value) return
  try {
    selectedTask.value = await cancelWirelessTask(selectedTask.value.id)
    await taskStore.refresh()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描任务停止失败')
  }
}

async function downloadExport(): Promise<void> {
  if (!selectedTask.value || !selectedExportCompleted.value) return
  try {
    const artifact = await getWirelessExportArtifact(selectedTask.value.id)
    const result = await downloadBackendResource({ apiPath: artifact.download_url, suggestedName: artifact.filename })
    if (result.status === 'failed') throw new Error(result.error || '无线扫描导出下载失败')
    if (result.status !== 'cancelled') ElMessage.success(`下载完成，SHA-256：${artifact.sha256}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描导出下载失败')
  }
}

function showDetail(row: Record<string, unknown>): void {
  selectedResult.value = row
}
</script>

<template>
  <el-card shadow="never">
    <template #header><div class="header"><div><h2>无线扫描</h2><p>网络工具内的 WLAN 扫描；无线勘测模块仍不在本页范围。</p></div><el-button :loading="loading" @click="refresh">刷新</el-button></div></template>
    <el-alert v-if="taskStore.error" :title="taskStore.error" type="error" show-icon :closable="false" />
    <div class="toolbar">
      <el-select v-model="form.adapter_guid" clearable placeholder="选择无线网卡"><el-option v-for="adapter in adapters" :key="adapter.guid || adapter.name" :label="adapter.display_name" :value="adapter.guid" /></el-select>
      <el-select v-model="form.scan_source"><el-option label="自动" value="auto" /><el-option label="WLAN API + netsh" value="hybrid" /><el-option label="Windows WLAN API" value="wlan_api" /><el-option label="netsh" value="netsh" /></el-select>
      <el-select v-model="form.project_id" clearable placeholder="扫描项目"><el-option v-for="project in projects" :key="project.project_id" :label="project.name" :value="project.project_id" /></el-select>
      <el-button type="primary" :disabled="!!runningTask" @click="startScan()">开始扫描</el-button>
      <el-button type="danger" plain :disabled="!runningTask" @click="stopScan">停止</el-button>
      <el-checkbox v-model="form.auto_refresh" @change="toggleAutoRefresh">自动刷新</el-checkbox>
      <el-input-number v-model="form.refresh_interval" :min="3" :max="3600" @change="toggleAutoRefresh" /><span>秒</span>
    </div>
    <el-collapse>
      <el-collapse-item title="扫描项目" name="project"><div class="project-form"><el-input v-model="form.project_name" placeholder="项目名称" /><el-input v-model="form.project_description" placeholder="说明（可选）" /><el-button @click="createProject">创建</el-button><el-button v-if="form.project_id" type="danger" plain :disabled="!!runningTask" @click="deleteProject">删除所选项目</el-button></div></el-collapse-item>
    </el-collapse>

    <el-divider content-position="left">后台任务</el-divider>
    <el-table :data="tasks" empty-text="暂无无线扫描任务" stripe max-height="260" @row-click="selectTask">
      <el-table-column prop="name" label="任务" min-width="180" /><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="progress" label="进度" width="90"><template #default="{ row }">{{ row.progress }}%</template></el-table-column><el-table-column prop="message" label="消息" min-width="220" />
    </el-table>
    <div v-if="selectedTaskSummary" class="actions"><span>{{ selectedTaskSummary.name }}：{{ selectedTaskSummary.status }}</span><el-button v-if="selectedTaskRunning" link type="danger" @click="cancelSelectedTask">停止任务</el-button><el-button v-if="selectedExportCompleted" link type="primary" @click="downloadExport">下载 Artifact</el-button></div>

    <el-divider content-position="left">扫描历史与结果</el-divider>
    <el-table v-loading="loading" :data="runs" empty-text="暂无无线扫描记录" stripe @row-click="selectRun">
      <el-table-column prop="started_at" label="扫描时间" min-width="170" /><el-table-column prop="project_name" label="项目" min-width="140" /><el-table-column prop="adapter_name" label="无线网卡" min-width="160" /><el-table-column prop="network_count" label="结果数" width="90" /><el-table-column prop="status" label="状态" width="100" />
    </el-table>
    <el-pagination v-if="runTotal > runPageSize" v-model:current-page="runPage" :total="runTotal" :page-size="runPageSize" layout="prev, pager, next, total" @current-change="changeRunPage" />
    <div class="actions"><el-button v-if="runs.length" link type="primary" @click="exportRun('csv')">导出 CSV</el-button><el-button v-if="runs.length" link type="primary" @click="exportRun('xlsx')">导出 XLSX</el-button></div>

    <el-tabs v-if="selectedRun" class="result-tabs">
      <el-tab-pane label="扫描结果">
        <div class="filters"><el-checkbox v-model="form.only_trackside">仅轨旁 AP</el-checkbox><el-select v-model="form.band" clearable placeholder="全部频段"><el-option label="2.4G" value="2.4G" /><el-option label="5G" value="5G" /><el-option label="6G" value="6G" /></el-select><el-select v-model="form.radio" clearable placeholder="全部 Radio"><el-option v-for="radio in ['1', '2', '3']" :key="radio" :label="radio" :value="radio" /></el-select><el-input v-model="form.search" clearable placeholder="SSID、BSSID、AP、车站或区间" @keyup.enter="applyResultFilters" /><el-button @click="applyResultFilters">筛选</el-button></div>
        <el-table :data="results" stripe max-height="520" @row-dblclick="showDetail"><el-table-column v-for="key in rowKeys" :key="key" :prop="key" :label="key" min-width="140" show-overflow-tooltip /></el-table>
        <el-pagination v-model:current-page="resultPage" v-model:page-size="resultPageSize" :total="resultTotal" :page-sizes="[50, 100, 200, 500]" layout="sizes, prev, pager, next, total" @current-change="changeResultPage" @size-change="changeResultPageSize" />
      </el-tab-pane>
      <el-tab-pane label="Raw"><el-input :model-value="runDetail?.raw_output || ''" type="textarea" :rows="18" readonly /></el-tab-pane>
      <el-tab-pane label="扫描详情"><el-descriptions v-if="runDetail" :column="2" border><el-descriptions-item label="扫描 ID">{{ runDetail.scan_id }}</el-descriptions-item><el-descriptions-item label="状态">{{ runDetail.status }}</el-descriptions-item><el-descriptions-item label="网卡">{{ runDetail.adapter_name || '—' }}</el-descriptions-item><el-descriptions-item label="结果数">{{ runDetail.network_count }}</el-descriptions-item><el-descriptions-item label="开始">{{ runDetail.started_at }}</el-descriptions-item><el-descriptions-item label="结束">{{ runDetail.ended_at }}</el-descriptions-item><el-descriptions-item label="项目" :span="2">{{ runDetail.project_name || '—' }} {{ runDetail.project_description }}</el-descriptions-item></el-descriptions></el-tab-pane>
    </el-tabs>
  </el-card>

  <el-dialog v-model="detailVisible" title="无线网络详情" width="760px"><pre class="raw-detail">{{ JSON.stringify(selectedResult, null, 2) }}</pre></el-dialog>
</template>

<style scoped>
.header { align-items: center; display: flex; justify-content: space-between; gap: 16px; }
.header h2 { margin: 0 0 4px; }
.header p { color: var(--el-text-color-secondary); margin: 0; }
.toolbar, .project-form, .actions, .filters { align-items: center; display: flex; gap: 10px; flex-wrap: wrap; }
.toolbar { margin-bottom: 14px; }
.actions, .result-tabs { margin-top: 12px; }
.filters { margin-bottom: 12px; }
.filters .el-input { max-width: 360px; }
.raw-detail { max-height: 60vh; overflow: auto; white-space: pre-wrap; word-break: break-all; }
</style>
