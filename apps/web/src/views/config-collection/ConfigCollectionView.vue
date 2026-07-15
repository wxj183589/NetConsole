<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Download, Refresh, Search, View } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'

import { isFeatureEnabled } from '../../features'
import {
  configArtifactUrl,
  cancelConfigTask,
  confirmSaveForce,
  confirmSnapshotDelete,
  getConfigDirectory,
  getConfigTask,
  issueSnapshotDelete,
  listConfigDevices,
  listConfigSnapshots,
  listConfigTasks,
  previewSaveForce,
  submitConfigDiffExport,
  submitConfigCollection,
  submitConfigSnapshotsExport,
  submitDeviceConfigDiff,
  submitLatestConfigDiff,
  submitSnapshotConfigDiff,
  submitSnapshotContent,
} from '../../api/configCollection'
import type {
  ConfigDevice,
  ConfigDevicePage,
  ConfigSnapshot,
  ConfigTaskReference,
  ConfigTaskStatus,
} from '../../types/configCollection'

const emptyPage: ConfigDevicePage = { items: [], total: 0, page: 1, page_size: 50, total_pages: 1, groups: [] }
const devicePage = ref<ConfigDevicePage>(emptyPage)
const snapshots = ref<ConfigSnapshot[]>([])
const tasks = ref<ConfigTaskStatus[]>([])
const selectedDevices = ref<ConfigDevice[]>([])
const selectedDevice = ref<ConfigDevice | null>(null)
const selectedSnapshots = ref<ConfigSnapshot[]>([])
const search = ref('')
const groupFilter = ref('')
const snapshotType = ref('')
const loading = ref(false)
const snapshotLoading = ref(false)
const error = ref('')
const resultTitle = ref('')
const resultText = ref('')
const resultDiff = ref('')
const resultArtifactId = ref('')
const diffFilter = ref<'all' | 'added' | 'removed'>('all')
const focusedTaskId = ref('')
const activeTaskIds = ref(new Set<string>())
const handledTerminalTasks = new Set<string>()
let pollTimer: ReturnType<typeof setInterval> | undefined

const visibleTasks = computed(() => tasks.value.slice(0, 20))
const hasActiveTasks = computed(() => activeTaskIds.value.size > 0)

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  void refreshAll()
  startPolling()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  stopPolling()
})

async function refreshAll(): Promise<void> {
  await Promise.all([loadDevices(), loadTasks()])
}

async function loadDevices(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    devicePage.value = await listConfigDevices({ search: search.value.trim(), group_filter: groupFilter.value, page: devicePage.value.page, page_size: devicePage.value.page_size })
    const currentId = selectedDevice.value?.id
    selectedDevice.value = devicePage.value.items.find((item) => item.id === currentId) || devicePage.value.items[0] || null
    selectedDevices.value = selectedDevices.value.filter((item) => devicePage.value.items.some((candidate) => candidate.id === item.id))
    await loadSnapshots()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '设备列表加载失败'
  } finally {
    loading.value = false
  }
}

async function loadSnapshots(): Promise<void> {
  if (!selectedDevice.value) {
    snapshots.value = []
    return
  }
  snapshotLoading.value = true
  try {
    snapshots.value = await listConfigSnapshots(selectedDevice.value.id, snapshotType.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '快照历史加载失败'
  } finally {
    snapshotLoading.value = false
  }
}

async function loadTasks(): Promise<void> {
  try {
    const next = await listConfigTasks()
    tasks.value = next
    activeTaskIds.value = new Set(next.filter((task) => !isTerminal(task.status)).map((task) => task.id))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '配置任务加载失败'
  }
}

function startPolling(): void {
  if (pollTimer) return
  pollTimer = setInterval(() => void pollTasks(), 2000)
}

function stopPolling(): void {
  if (!pollTimer) return
  clearInterval(pollTimer)
  pollTimer = undefined
}

async function pollTasks(): Promise<void> {
  if (document.hidden) return
  try {
    const next = await listConfigTasks()
    tasks.value = next
    const active = new Set<string>()
    for (const task of next) {
      if (!isTerminal(task.status)) active.add(task.id)
      if (isTerminal(task.status) && !handledTerminalTasks.has(task.id)) {
        handledTerminalTasks.add(task.id)
        if (['config_web_snapshot_fetch', 'config_web_save_force', 'config_snapshot_delete_many'].includes(task.type) && task.status === 'COMPLETED') await loadSnapshots()
        if (task.id === focusedTaskId.value) showTaskResult(task)
      }
    }
    activeTaskIds.value = active
  } catch {
    // 保留上一次任务快照，下一轮继续恢复。
  }
}

function handleVisibility(): void {
  if (document.hidden) stopPolling()
  else {
    void pollTasks()
    startPolling()
  }
}

function selectDevice(device: ConfigDevice): void {
  selectedDevice.value = device
  selectedSnapshots.value = []
  void loadSnapshots()
}

function changePage(page: number): void {
  devicePage.value.page = page
  void loadDevices()
}

async function collectSelected(): Promise<void> {
  if (!selectedDevices.value.length) {
    ElMessage.info('请先选择设备')
    return
  }
  try {
    const refs = await submitConfigCollection(selectedDevices.value.map((device) => device.id))
    addTaskReferences(refs)
    ElMessage.success(`已提交 ${refs.length} 个只读配置采集任务`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '配置采集任务提交失败')
  }
}

async function saveSelected(): Promise<void> {
  if (!selectedDevices.value.length) {
    ElMessage.info('请先选择设备')
    return
  }
  try {
    const preview = await previewSaveForce(selectedDevices.value.map((device) => device.id))
    await ElMessageBox.confirm(`${preview.summary}\n${preview.action_plan.join('；')}`, '确认保存配置', { type: 'warning' })
    const task = await confirmSaveForce(preview)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('保存配置任务已提交')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : '保存配置任务提交失败')
  }
}

async function compareLatest(): Promise<void> {
  if (!selectedDevice.value) {
    ElMessage.info('请先选择设备')
    return
  }
  try {
    const task = await submitLatestConfigDiff(selectedDevice.value.id)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('配置差异任务已提交')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '配置差异任务提交失败')
  }
}

async function compareSnapshots(): Promise<void> {
  if (selectedSnapshots.value.length !== 2) {
    ElMessage.info('请选择两个快照进行比较')
    return
  }
  try {
    const task = await submitSnapshotConfigDiff(selectedSnapshots.value[0].id, selectedSnapshots.value[1].id)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('快照差异任务已提交')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '快照差异任务提交失败')
  }
}

async function compareDevices(): Promise<void> {
  if (selectedDevices.value.length !== 2) {
    ElMessage.info('请选择两台设备进行比较')
    return
  }
  try {
    const task = await submitDeviceConfigDiff(selectedDevices.value[0].id, selectedDevices.value[1].id)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('多设备差异任务已提交')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '多设备差异任务提交失败')
  }
}

async function deleteSelectedSnapshots(): Promise<void> {
  if (!selectedSnapshots.value.length) {
    ElMessage.info('请先选择快照')
    return
  }
  try {
    const preview = await issueSnapshotDelete(selectedSnapshots.value.map((snapshot) => snapshot.id))
    await ElMessageBox.confirm(preview.summary, '删除快照', { type: 'warning' })
    const task = await confirmSnapshotDelete(preview)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('快照删除任务已提交')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : '快照删除任务提交失败')
  }
}

async function exportSelectedDiff(): Promise<void> {
  if (selectedSnapshots.value.length !== 2) {
    ElMessage.info('请选择两个快照导出差异')
    return
  }
  try {
    const task = await submitConfigDiffExport(selectedSnapshots.value[0].id, selectedSnapshots.value[1].id)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('配置差异导出任务已提交')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '配置差异导出失败')
  }
}

async function exportSelectedSnapshots(): Promise<void> {
  if (!selectedSnapshots.value.length) {
    ElMessage.info('请先选择快照')
    return
  }
  try {
    const task = await submitConfigSnapshotsExport(selectedSnapshots.value.map((snapshot) => snapshot.id))
    addTaskReferences([task])
    focusedTaskId.value = task.id
    ElMessage.success('快照 ZIP 导出任务已提交')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '快照 ZIP 导出失败')
  }
}

async function viewSnapshot(snapshot: ConfigSnapshot): Promise<void> {
  try {
    const task = await submitSnapshotContent(snapshot.id)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    resultTitle.value = `${snapshot.type} · ${formatTime(snapshot.timestamp)}`
    resultText.value = '正在读取快照内容…'
    resultDiff.value = ''
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '快照读取任务提交失败')
  }
}

function addTaskReferences(refs: ConfigTaskReference[]): void {
  const known = new Map(tasks.value.map((task) => [task.id, task]))
  for (const item of refs) {
    known.set(item.id, { ...item, stage: '', created_time: '', started_time: '', finished_time: '', error_message: '', result: {} })
  }
  activeTaskIds.value = new Set([...activeTaskIds.value, ...refs.map((item) => item.id)])
  tasks.value = [...known.values()].sort((left, right) => right.created_time.localeCompare(left.created_time))
}

async function openTask(task: ConfigTaskStatus): Promise<void> {
  focusedTaskId.value = task.id
  try {
    const current = await getConfigTask(task.id, diffFilter.value)
    showTaskResult(current)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '配置任务详情加载失败')
  }
}

async function changeDiffFilter(value: 'all' | 'added' | 'removed'): Promise<void> {
  diffFilter.value = value
  if (!focusedTaskId.value) return
  try {
    showTaskResult(await getConfigTask(focusedTaskId.value, value))
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '差异过滤失败')
  }
}

async function cancelTask(task: ConfigTaskStatus): Promise<void> {
  try {
    const current = await cancelConfigTask(task.id)
    tasks.value = tasks.value.map((item) => item.id === current.id ? current : item)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '任务取消失败')
  }
}

async function openResultDirectory(): Promise<void> {
  try {
    const result = await getConfigDirectory('config_exports')
    if (result.success) ElMessage.success(result.message || '已打开结果目录')
    else ElMessage.warning(result.message || '当前运行模式不支持打开目录')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '结果目录不可用')
  }
}

function showTaskResult(task: ConfigTaskStatus): void {
  resultArtifactId.value = typeof task.result?.artifact_id === 'string' ? task.result.artifact_id : ''
  if (task.error_message) {
    resultTitle.value = '任务失败'
    resultText.value = task.error_message
    resultDiff.value = ''
    return
  }
  const result = task.result || {}
  const failedItems = Array.isArray(result.failed_items) ? result.failed_items : []
  if (typeof result.failed === 'number' && result.failed > 0) {
    resultTitle.value = result.failed === result.total ? '任务失败' : '任务部分完成'
    resultText.value = `成功 ${Number(result.deleted ?? result.saved ?? 0)} / ${Number(result.total ?? 0)}；失败 ${result.failed}\n${failedItems.map(failureItemText).join('\n')}`
    resultDiff.value = ''
  } else if (typeof result.text === 'string') {
    resultTitle.value = `${result.snapshot_type || '配置快照'} · ${task.device_name || ''}`
    resultText.value = result.text
    resultDiff.value = ''
  } else if (typeof result.raw_diff === 'string') {
    resultTitle.value = `配置差异 · ${task.device_name || ''}`
    resultDiff.value = result.raw_diff
    resultText.value = ''
  } else if (resultArtifactId.value) {
    resultTitle.value = 'Artifact 已生成'
    resultText.value = 'Artifact 已生成，可下载。'
    resultDiff.value = ''
  }
}

function isTerminal(status: string): boolean {
  return ['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)
}

function taskType(task: ConfigTaskStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (task.status === 'COMPLETED' && Number(task.result?.failed || 0) > 0) return 'warning'
  if (task.status === 'COMPLETED') return 'success'
  if (task.status === 'FAILED') return 'danger'
  if (task.status === 'RUNNING' || task.status === 'STARTING' || task.status === 'PENDING') return 'warning'
  return 'info'
}

function taskStatusLabel(task: ConfigTaskStatus): string {
  return task.status === 'COMPLETED' && Number(task.result?.failed || 0) > 0 ? '部分完成' : task.status
}

function taskFailureText(task: ConfigTaskStatus): string {
  const failedItems = Array.isArray(task.result?.failed_items) ? task.result.failed_items : []
  return task.error_message || failedItems.map(failureItemText).join('；')
}

function failureItemText(value: unknown): string {
  if (!value || typeof value !== 'object') return String(value || '')
  const item = value as Record<string, unknown>
  return `${String(item.snapshot_id || item.device_uuid || '项目')}: ${String(item.error || '失败')}`
}

function formatTime(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}
</script>

<template>
  <section class="config-collection">
    <el-alert
      title="配置采集中心"
       description="采集、保存、比较、删除和导出均进入持久 Task；下载只接受服务端 Artifact ID，不接收本机路径。"
      type="info"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <div class="toolbar content-card">
      <el-input v-model="search" :prefix-icon="Search" clearable placeholder="搜索设备名称、系统名或站点" @keyup.enter="loadDevices" />
      <el-select v-model="groupFilter" clearable placeholder="设备分组" @change="loadDevices">
        <el-option label="全部分组" value="" />
        <el-option label="未分组" value="__ungrouped__" />
        <el-option v-for="group in devicePage.groups" :key="group.id" :label="`${group.name} (${group.device_count})`" :value="String(group.id)" />
      </el-select>
      <el-button type="primary" :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      <el-button :icon="Search" :disabled="loading" @click="loadDevices">应用筛选</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="page-error" />

    <div class="main-grid">
      <div class="content-card device-card">
        <div class="card-heading"><div><h2>设备选择</h2><p>共 {{ devicePage.total }} 台 H3C 设备</p></div><div class="heading-actions"><el-button type="primary" :disabled="!selectedDevices.length || hasActiveTasks || !isFeatureEnabled('web.config_collection_fetch')" @click="collectSelected">采集 running / saved</el-button><el-button :disabled="!selectedDevices.length || hasActiveTasks || !isFeatureEnabled('web.config_collection_save_force')" @click="saveSelected">保存配置</el-button><el-button :disabled="selectedDevices.length !== 2 || hasActiveTasks || !isFeatureEnabled('web.config_collection_diff')" @click="compareDevices">比较两台设备</el-button></div></div>
        <el-table v-loading="loading" :data="devicePage.items" row-key="id" stripe height="calc(100vh - 430px)" @row-click="selectDevice" @selection-change="selectedDevices = $event">
          <el-table-column type="selection" width="48" />
          <el-table-column label="设备" min-width="170"><template #default="{ row }"><strong>{{ row.name || '--' }}</strong><small>{{ row.system_name || '--' }}</small></template></el-table-column>
          <el-table-column prop="device_type" label="类型" width="92" />
          <el-table-column prop="station" label="归属站点" min-width="120" show-overflow-tooltip />
        </el-table>
        <div class="pagination-row">
          <span>第 {{ devicePage.page }} / {{ devicePage.total_pages }} 页</span>
           <el-pagination :current-page="devicePage.page" :page-size="devicePage.page_size" :total="devicePage.total" layout="prev, next" @current-change="changePage" />
        </div>
      </div>

      <div class="content-card snapshot-card">
        <div class="card-heading"><div><h2>快照历史</h2><p>{{ selectedDevice?.name || '请选择设备' }} · 选两个快照可比较</p></div><div class="heading-actions"><el-select v-model="snapshotType" clearable placeholder="配置类型" @change="loadSnapshots"><el-option label="运行配置" value="running" /><el-option label="保存配置" value="saved" /><el-option label="差异" value="diff" /></el-select><el-button :disabled="selectedSnapshots.length !== 2 || !isFeatureEnabled('web.config_collection_diff')" @click="compareSnapshots">比较快照</el-button><el-button :disabled="!selectedDevice || !isFeatureEnabled('web.config_collection_diff')" @click="compareLatest">最新差异</el-button><el-button :disabled="selectedSnapshots.length !== 2 || !isFeatureEnabled('web.config_collection_export')" @click="exportSelectedDiff">导出差异</el-button><el-button :disabled="!selectedSnapshots.length || !isFeatureEnabled('web.config_collection_export')" @click="exportSelectedSnapshots">导出 ZIP</el-button><el-button :icon="Delete" :disabled="!selectedSnapshots.length || !isFeatureEnabled('web.config_collection_delete')" @click="deleteSelectedSnapshots">删除历史</el-button></div></div>
        <el-table v-loading="snapshotLoading" :data="snapshots" row-key="id" stripe height="calc(100vh - 430px)" @selection-change="selectedSnapshots = $event">
          <el-table-column type="selection" width="48" />
          <el-table-column prop="type" label="类型" width="100"><template #default="{ row }"><el-tag :type="row.type === 'diff' ? 'warning' : row.type === 'saved' ? 'success' : 'info'">{{ row.type === 'running' ? '运行配置' : row.type === 'saved' ? '保存配置' : '差异' }}</el-tag></template></el-table-column>
          <el-table-column label="采集时间" min-width="180"><template #default="{ row }">{{ formatTime(row.timestamp) }}</template></el-table-column>
          <el-table-column label="大小" width="100"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column>
          <el-table-column label="操作" width="130" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="View" @click.stop="viewSnapshot(row)">查看</el-button><el-button link :icon="Download" tag="a" :disabled="!isFeatureEnabled('web.config_collection_download')" :href="isFeatureEnabled('web.config_collection_download') ? configArtifactUrl(row.artifact_id) : undefined" target="_blank" @click.stop>下载</el-button></template></el-table-column>
        </el-table>
      </div>
    </div>

    <div class="content-card task-card">
      <div class="card-heading"><div><h2>配置任务</h2><p>任务来自 Task Center，刷新页面后可恢复</p></div><div class="heading-actions"><el-button :disabled="!isFeatureEnabled('web.config_collection_open_directory')" @click="openResultDirectory">结果目录</el-button><el-button :loading="hasActiveTasks" @click="loadTasks">刷新任务</el-button></div></div>
      <el-table :data="visibleTasks" stripe empty-text="暂无配置任务" @row-click="openTask">
        <el-table-column prop="device_name" label="设备" min-width="170" />
        <el-table-column prop="type" label="任务类型" min-width="250" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="taskType(row)">{{ taskStatusLabel(row) }}</el-tag></template></el-table-column>
        <el-table-column label="进度" width="150"><template #default="{ row }"><el-progress :percentage="row.progress" :stroke-width="7" /></template></el-table-column>
        <el-table-column label="时间" width="180"><template #default="{ row }">{{ formatTime(row.finished_time || row.created_time) }}</template></el-table-column>
        <el-table-column label="错误" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ taskFailureText(row) }}</template></el-table-column>
        <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button v-if="!isTerminal(row.status)" link type="danger" @click.stop="cancelTask(row)">取消</el-button></template></el-table-column>
      </el-table>
    </div>

    <div v-if="resultText || resultDiff" class="content-card result-card">
      <div class="card-heading"><div><h2>{{ resultTitle || '配置结果' }}</h2><p>内容由后台任务返回，未暴露本机绝对路径</p></div><div class="heading-actions"><el-select v-if="resultDiff" :model-value="diffFilter" size="small" @update:model-value="changeDiffFilter"><el-option label="全部差异" value="all" /><el-option label="仅新增" value="added" /><el-option label="仅删除" value="removed" /></el-select><el-button v-if="resultArtifactId" tag="a" :href="configArtifactUrl(resultArtifactId)" target="_blank">下载 Artifact</el-button><el-button @click="resultText = ''; resultDiff = ''; resultArtifactId = ''">清空</el-button></div></div>
      <pre v-if="resultText" class="code-panel">{{ resultText }}</pre>
      <pre v-else class="code-panel diff-panel">{{ resultDiff }}</pre>
    </div>
  </section>
</template>

<style scoped>
.config-collection { max-width: 1780px; margin: 0 auto; }
.page-alert, .page-error { margin-bottom: 16px; }
.content-card { overflow: hidden; background: #fff; border: 1px solid #dfe7f1; border-radius: 10px; }
.toolbar { display: grid; grid-template-columns: minmax(260px, 1fr) 210px auto auto; gap: 10px; padding: 14px 16px; margin-bottom: 16px; }
.main-grid { display: grid; grid-template-columns: minmax(420px, 0.85fr) minmax(560px, 1.15fr); gap: 16px; }
.card-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 17px; border-bottom: 1px solid #edf1f6; }
.card-heading h2 { margin: 0; color: #172033; font-size: 18px; }
.card-heading p { margin: 5px 0 0; color: #718096; font-size: 12px; }
.card-heading small { display: block; margin-top: 4px; color: #8793a5; font-size: 11px; }
.heading-actions { display: flex; align-items: center; gap: 8px; }
.pagination-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; color: #718096; font-size: 12px; }
.task-card, .result-card { margin-top: 16px; }
.code-panel { max-height: 470px; margin: 0; padding: 16px; overflow: auto; color: #d9e2ed; background: #101827; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; white-space: pre; }
.diff-panel { color: #e6edf5; }
@media (max-width: 1200px) { .main-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .toolbar { grid-template-columns: 1fr; } .card-heading { align-items: flex-start; flex-direction: column; } .heading-actions { flex-wrap: wrap; width: 100%; } }
</style>
