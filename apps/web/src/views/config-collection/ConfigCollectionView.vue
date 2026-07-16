<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete, Download, Refresh, Search, View } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import { isFeatureEnabled } from '../../features'
import {
  configArtifactDownloadRequest,
  confirmSaveForce,
  confirmSnapshotDelete,
  getConfigDirectory,
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
  ConfigDiffRow,
  ConfigDiffSummary,
  ConfigSnapshot,
  ConfigTaskReference,
  ConfigTaskStatus,
} from '../../types/configCollection'
import { downloadBackendResource } from '../../platform/runtime'
import {
  nextConfigDiffChangeIndex,
  parseConfigDiffRows,
  parseConfigDiffSummary,
  statusForConfigDiffFilter,
  type ConfigDiffFilter,
} from './configDiff'

const router = useRouter()
const emptyPage: ConfigDevicePage = { items: [], total: 0, page: 1, page_size: 50, total_pages: 1, groups: [] }
const emptyDiffSummary: ConfigDiffSummary = { added: 0, removed: 0, modified: 0 }
const devicePage = ref<ConfigDevicePage>(emptyPage)
const snapshots = ref<ConfigSnapshot[]>([])
const tasks = ref<ConfigTaskStatus[]>([])
const selectedDevices = ref<ConfigDevice[]>([])
const selectedDevice = ref<ConfigDevice | null>(null)
const selectedSnapshots = ref<ConfigSnapshot[]>([])
type SnapshotChoice = { device: ConfigDevice; snapshot: ConfigSnapshot }
const leftSnapshotChoice = ref<SnapshotChoice | null>(null)
const rightSnapshotChoice = ref<SnapshotChoice | null>(null)
const search = ref('')
const groupFilter = ref('')
const snapshotType = ref('')
const loading = ref(false)
const snapshotLoading = ref(false)
const error = ref('')
const resultTitle = ref('')
const resultText = ref('')
const resultDiff = ref('')
const resultDiffRows = ref<ConfigDiffRow[]>([])
const resultDiffSummary = ref<ConfigDiffSummary>({ ...emptyDiffSummary })
const resultDiffLeftLabel = ref('left')
const resultDiffRightLabel = ref('right')
const diffViewport = ref<HTMLElement | null>(null)
const resultArtifactId = ref('')
const resultArtifactName = ref('')
const diffFilter = ref<ConfigDiffFilter>('all')
const currentDiffChange = ref(0)
const focusedTaskId = ref('')
const activeTaskIds = ref(new Set<string>())
const handledTerminalTasks = new Set<string>()
let pollTimer: ReturnType<typeof setInterval> | undefined

const hasActiveTasks = computed(() => activeTaskIds.value.size > 0)
const failedTaskCount = computed(() => tasks.value.filter((task) => task.status === 'FAILED' || Number(task.result?.failed || 0) > 0).length)
const filteredDiffRows = computed(() => {
  const status = statusForConfigDiffFilter(diffFilter.value)
  return status ? resultDiffRows.value.filter((row) => row.status === status) : resultDiffRows.value
})
const diffChangeCount = computed(() => filteredDiffRows.value.filter((row) => row.status !== '=').length)

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
        if (['config_web_snapshot_fetch', 'config_web_save_force', 'config_snapshot_delete_many'].includes(task.type)) await loadSnapshots()
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

async function downloadArtifact(snapshot: ConfigSnapshot): Promise<void> {
  try {
    const result = await downloadBackendResource(
      configArtifactDownloadRequest(snapshot.artifact_id, snapshot.filename),
    )
    if (result.status === 'failed') ElMessage.error(result.error || '配置文件下载失败')
    else if (result.status === 'saved') ElMessage.success('配置文件已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载')
  } catch {
    ElMessage.error('配置文件下载失败')
  }
}

async function downloadResultArtifact(): Promise<void> {
  if (!resultArtifactId.value) return
  try {
    const result = await downloadBackendResource(
      configArtifactDownloadRequest(resultArtifactId.value, resultArtifactName.value || 'config-artifact.zip'),
    )
    if (result.status === 'failed') ElMessage.error(result.error || 'Artifact 下载失败')
    else if (result.status === 'saved') ElMessage.success('Artifact 已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载')
  } catch {
    ElMessage.error('Artifact 下载失败')
  }
}

async function compareSnapshots(): Promise<void> {
  if (!leftSnapshotChoice.value || !rightSnapshotChoice.value) {
    ElMessage.info('请分别选择左右快照进行比较')
    return
  }
  try {
    const task = await submitSnapshotConfigDiff(
      leftSnapshotChoice.value.snapshot.id,
      rightSnapshotChoice.value.snapshot.id,
    )
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
    const deletedIds = new Set(selectedSnapshots.value.map((snapshot) => snapshot.id))
    const preview = await issueSnapshotDelete([...deletedIds])
    await ElMessageBox.confirm(preview.summary, '删除快照', { type: 'warning' })
    const task = await confirmSnapshotDelete(preview)
    addTaskReferences([task])
    focusedTaskId.value = task.id
    if (leftSnapshotChoice.value && deletedIds.has(leftSnapshotChoice.value.snapshot.id)) leftSnapshotChoice.value = null
    if (rightSnapshotChoice.value && deletedIds.has(rightSnapshotChoice.value.snapshot.id)) rightSnapshotChoice.value = null
    ElMessage.success('快照删除任务已提交')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : '快照删除任务提交失败')
  }
}

async function exportSelectedDiff(): Promise<void> {
  if (!leftSnapshotChoice.value || !rightSnapshotChoice.value) {
    ElMessage.info('请分别选择左右快照导出差异')
    return
  }
  try {
    const task = await submitConfigDiffExport(
      leftSnapshotChoice.value.snapshot.id,
      rightSnapshotChoice.value.snapshot.id,
    )
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
    resetDiffResult()
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

async function changeDiffFilter(value: ConfigDiffFilter): Promise<void> {
  diffFilter.value = value
  currentDiffChange.value = 0
  await scrollToCurrentDiff()
}

function chooseSnapshot(snapshot: ConfigSnapshot, side: 'left' | 'right'): void {
  if (!selectedDevice.value) return
  const choice = { device: selectedDevice.value, snapshot }
  if (side === 'left') leftSnapshotChoice.value = choice
  else rightSnapshotChoice.value = choice
}

function clearSnapshotChoice(side: 'left' | 'right'): void {
  if (side === 'left') leftSnapshotChoice.value = null
  else rightSnapshotChoice.value = null
}

function snapshotChoiceLabel(choice: SnapshotChoice | null): string {
  if (!choice) return '未选择'
  return `${choice.device.name || choice.device.system_name || choice.device.device_uuid} · ${snapshotTypeLabel(choice.snapshot.type)} · ${choice.snapshot.timestamp}`
}

function snapshotTypeLabel(type: string): string {
  if (type === 'running') return '运行配置'
  if (type === 'saved') return '保存配置'
  if (type === 'diff') return '差异'
  return type || '配置'
}

async function openTaskWindow(): Promise<void> {
  type ConfigTaskWindowBridge = {
    openTaskWindow?: (context: { module: 'config' }) => Promise<{ success: boolean; error?: string }>
  }
  const bridge = window.netconsoleDesktop as (typeof window.netconsoleDesktop & ConfigTaskWindowBridge)
  try {
    if (bridge?.openTaskWindow) {
      const result = await bridge.openTaskWindow({ module: 'config' })
      if (!result.success) ElMessage.error(result.error || '任务窗口打开失败')
      return
    }
    await router.push({ name: 'tasks', query: { module: 'config' } })
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '任务窗口打开失败')
  }
}

async function openResultDirectory(directoryKind: 'config_snapshots' | 'config_exports'): Promise<void> {
  try {
    const result = await getConfigDirectory(directoryKind)
    if (result.success) ElMessage.success(result.message || '已打开结果目录')
    else ElMessage.warning(result.message || '当前运行模式不支持打开目录')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '结果目录不可用')
  }
}

function previousDiff(): void {
  if (!diffChangeCount.value) return
  currentDiffChange.value = nextConfigDiffChangeIndex(currentDiffChange.value, diffChangeCount.value, -1)
  void scrollToCurrentDiff()
}

function nextDiff(): void {
  if (!diffChangeCount.value) return
  currentDiffChange.value = nextConfigDiffChangeIndex(currentDiffChange.value, diffChangeCount.value, 1)
  void scrollToCurrentDiff()
}

async function scrollToCurrentDiff(): Promise<void> {
  await nextTick()
  const rows = diffViewport.value?.querySelectorAll<HTMLElement>('[data-diff-change="true"]')
  rows?.[currentDiffChange.value]?.scrollIntoView({ block: 'center' })
}

function showTaskResult(task: ConfigTaskStatus): void {
  resultArtifactId.value = typeof task.result?.artifact_id === 'string' ? task.result.artifact_id : ''
  const result = task.result || {}
  resultArtifactName.value = typeof result.display_name === 'string' ? result.display_name : ''
  const failedItems = Array.isArray(result.failed_items) ? result.failed_items : []
  const unknownItems = Array.isArray(result.unknown_items) ? result.unknown_items : []
  const notStartedItems = Array.isArray(result.not_started_items) ? result.not_started_items : []
  if (result.interrupted || typeof result.failed === 'number' && result.failed > 0) {
    const succeeded = Number(result.deleted ?? result.saved ?? 0)
    const details = [
      `成功 ${succeeded} / ${Number(result.total ?? 0)}；失败 ${Number(result.failed ?? 0)}；状态未知 ${unknownItems.length}；未开始 ${notStartedItems.length}`,
      ...failedItems.map(failureItemText),
      unknownItems.length ? `状态未知：${unknownItems.map(failureItemText).join('；')}` : '',
      notStartedItems.length ? `未开始：${notStartedItems.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join('；')}` : '',
      task.error_message ? `终态说明：${task.error_message}` : '',
    ].filter(Boolean)
    resultTitle.value = result.interrupted ? '任务中断，执行记录已保留' : Number(result.failed) === Number(result.total) ? '任务失败' : '任务部分完成'
    resultText.value = details.join('\n')
    resetDiffResult()
  } else if (task.error_message) {
    resultTitle.value = '任务失败'
    resultText.value = task.error_message
    resetDiffResult()
  } else if (typeof result.text === 'string') {
    resultTitle.value = `${result.snapshot_type || '配置快照'} · ${task.device_name || ''}`
    resultText.value = result.text
    resetDiffResult()
  } else if (typeof result.raw_diff === 'string') {
    resultDiffLeftLabel.value = typeof result.left_label === 'string' ? result.left_label : 'left'
    resultDiffRightLabel.value = typeof result.right_label === 'string' ? result.right_label : 'right'
    resultTitle.value = `配置差异 · ${resultDiffLeftLabel.value} → ${resultDiffRightLabel.value}`
    resultDiff.value = result.raw_diff
    resultDiffRows.value = parseConfigDiffRows(result.diff_rows)
    resultDiffSummary.value = parseConfigDiffSummary(result.diff_summary)
    diffFilter.value = 'all'
    currentDiffChange.value = 0
    resultText.value = ''
    void scrollToCurrentDiff()
  } else if (resultArtifactId.value) {
    resultTitle.value = 'Artifact 已生成'
    resultText.value = 'Artifact 已生成，可下载。'
    resetDiffResult()
  }
}

function isTerminal(status: string): boolean {
  return ['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)
}

function resetDiffResult(): void {
  resultDiff.value = ''
  resultDiffRows.value = []
  resultDiffSummary.value = { ...emptyDiffSummary }
  resultDiffLeftLabel.value = 'left'
  resultDiffRightLabel.value = 'right'
  diffFilter.value = 'all'
  currentDiffChange.value = 0
}

function clearResult(): void {
  resultTitle.value = ''
  resultText.value = ''
  resultArtifactId.value = ''
  resultArtifactName.value = ''
  resetDiffResult()
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
      <div class="toolbar-actions">
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
        <el-button :icon="Search" :disabled="loading" @click="loadDevices">应用筛选</el-button>
        <el-button :disabled="!isFeatureEnabled('web.config_collection_open_directory')" @click="openResultDirectory('config_snapshots')">快照目录</el-button>
        <el-button :disabled="!isFeatureEnabled('web.config_collection_open_directory')" @click="openResultDirectory('config_exports')">导出目录</el-button>
        <el-button :disabled="!isFeatureEnabled('web.job_center')" @click="openTaskWindow">任务窗口（运行 {{ activeTaskIds.size }} / 异常 {{ failedTaskCount }}）</el-button>
      </div>
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
        <div class="card-heading"><div><h2>快照历史</h2><p>{{ selectedDevice?.name || '请选择设备' }} · 左右选择在切换设备或类型后仍保留</p></div><div class="heading-actions"><el-select v-model="snapshotType" clearable placeholder="配置类型" @change="loadSnapshots"><el-option label="运行配置" value="running" /><el-option label="保存配置" value="saved" /><el-option label="差异" value="diff" /></el-select><el-button :disabled="!selectedDevice || !isFeatureEnabled('web.config_collection_diff')" @click="compareLatest">最新差异</el-button><el-button :disabled="!selectedSnapshots.length || !isFeatureEnabled('web.config_collection_export')" @click="exportSelectedSnapshots">导出 ZIP</el-button><el-button :icon="Delete" :disabled="!selectedSnapshots.length || !isFeatureEnabled('web.config_collection_delete')" @click="deleteSelectedSnapshots">删除历史</el-button></div></div>
        <div class="comparison-basket" aria-label="配置快照左右选择篮">
          <div class="snapshot-choice" data-testid="left-snapshot-choice"><span>左侧快照</span><strong>{{ snapshotChoiceLabel(leftSnapshotChoice) }}</strong><el-button link :disabled="!leftSnapshotChoice" @click="clearSnapshotChoice('left')">清除</el-button></div>
          <div class="snapshot-choice" data-testid="right-snapshot-choice"><span>右侧快照</span><strong>{{ snapshotChoiceLabel(rightSnapshotChoice) }}</strong><el-button link :disabled="!rightSnapshotChoice" @click="clearSnapshotChoice('right')">清除</el-button></div>
          <div class="comparison-actions"><el-button type="primary" :disabled="!leftSnapshotChoice || !rightSnapshotChoice || !isFeatureEnabled('web.config_collection_diff')" @click="compareSnapshots">比较左右快照</el-button><el-button :disabled="!leftSnapshotChoice || !rightSnapshotChoice || !isFeatureEnabled('web.config_collection_export')" @click="exportSelectedDiff">导出左右差异</el-button></div>
        </div>
        <el-table v-loading="snapshotLoading" :data="snapshots" row-key="id" stripe height="calc(100vh - 430px)" @selection-change="selectedSnapshots = $event">
          <el-table-column type="selection" width="48" />
          <el-table-column prop="type" label="类型" width="100"><template #default="{ row }"><el-tag :type="row.type === 'diff' ? 'warning' : row.type === 'saved' ? 'success' : 'info'">{{ row.type === 'running' ? '运行配置' : row.type === 'saved' ? '保存配置' : '差异' }}</el-tag></template></el-table-column>
          <el-table-column label="采集时间" min-width="180"><template #default="{ row }">{{ formatTime(row.timestamp) }}</template></el-table-column>
          <el-table-column label="大小" width="100"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column>
          <el-table-column label="操作" width="260" fixed="right"><template #default="{ row }"><el-button link @click.stop="chooseSnapshot(row, 'left')">设为左侧</el-button><el-button link @click.stop="chooseSnapshot(row, 'right')">设为右侧</el-button><el-button link type="primary" :icon="View" @click.stop="viewSnapshot(row)">查看</el-button><el-button link :icon="Download" :disabled="!isFeatureEnabled('web.config_collection_download')" @click.stop="downloadArtifact(row)">下载</el-button></template></el-table-column>
        </el-table>
      </div>
    </div>

    <div v-if="resultText || resultDiff || resultDiffRows.length" class="content-card result-card">
      <div class="card-heading"><div><h2>{{ resultTitle || '配置结果' }}</h2><p v-if="resultDiffRows.length">新增 {{ resultDiffSummary.added }} · 删除 {{ resultDiffSummary.removed }} · 修改块 {{ resultDiffSummary.modified }}</p><p v-else>内容由后台任务返回，未暴露本机绝对路径</p></div><div class="heading-actions"><el-select v-if="resultDiffRows.length" :model-value="diffFilter" size="small" @update:model-value="changeDiffFilter"><el-option label="全部行" value="all" /><el-option label="仅新增" value="added" /><el-option label="仅删除" value="removed" /><el-option label="仅修改" value="modified" /></el-select><el-button v-if="resultDiffRows.length" :disabled="!diffChangeCount" @click="previousDiff">上一处差异</el-button><span v-if="resultDiffRows.length" class="diff-position">{{ diffChangeCount ? currentDiffChange + 1 : 0 }} / {{ diffChangeCount }}</span><el-button v-if="resultDiffRows.length" :disabled="!diffChangeCount" @click="nextDiff">下一处差异</el-button><el-button v-if="resultArtifactId" @click="downloadResultArtifact">下载 Artifact</el-button><el-button @click="clearResult">清空</el-button></div></div>
      <pre v-if="resultText" class="code-panel">{{ resultText }}</pre>
      <div v-else-if="resultDiffRows.length" ref="diffViewport" class="diff-table" role="table" aria-label="配置差异双栏视图">
        <div class="diff-row diff-header" role="row"><span>#</span><strong>{{ resultDiffLeftLabel }}</strong><span>状态</span><span>#</span><strong>{{ resultDiffRightLabel }}</strong></div>
        <div
          v-for="(row, index) in filteredDiffRows"
          :key="`${row.left_line}-${row.right_line}-${index}`"
          class="diff-row"
          :class="{ 'is-added': row.status === '+', 'is-removed': row.status === '-', 'is-modified': row.status === '~', 'is-equal': row.status === '=' }"
          :data-diff-change="row.status !== '=' ? 'true' : 'false'"
          role="row"
        >
          <span class="line-number">{{ row.left_line ?? '' }}</span><code>{{ row.left_text }}</code><span class="diff-status">{{ row.status }}</span><span class="line-number">{{ row.right_line ?? '' }}</span><code>{{ row.right_text }}</code>
        </div>
      </div>
      <pre v-else class="code-panel diff-panel">{{ resultDiff }}</pre>
    </div>
  </section>
</template>

<style scoped>
.config-collection { max-width: 1780px; margin: 0 auto; }
.page-alert, .page-error { margin-bottom: 16px; }
.content-card { overflow: hidden; background: #fff; border: 1px solid #dfe7f1; border-radius: 10px; }
.toolbar { display: grid; grid-template-columns: minmax(260px, 1fr) 210px minmax(520px, auto); gap: 10px; padding: 14px 16px; margin-bottom: 16px; }
.toolbar-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.main-grid { display: grid; grid-template-columns: minmax(420px, 0.85fr) minmax(560px, 1.15fr); gap: 16px; }
.card-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 17px; border-bottom: 1px solid #edf1f6; }
.card-heading h2 { margin: 0; color: #172033; font-size: 18px; }
.card-heading p { margin: 5px 0 0; color: #718096; font-size: 12px; }
.card-heading small { display: block; margin-top: 4px; color: #8793a5; font-size: 11px; }
.heading-actions { display: flex; align-items: center; gap: 8px; }
.pagination-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; color: #718096; font-size: 12px; }
.comparison-basket { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(220px, 1fr) auto; gap: 10px; align-items: stretch; padding: 12px 16px; border-bottom: 1px solid #edf1f6; background: #f8fafc; }
.snapshot-choice { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: center; min-height: 42px; padding: 8px 10px; border: 1px solid #dfe7f1; border-radius: 8px; background: #fff; }
.snapshot-choice span { color: #718096; font-size: 12px; }
.snapshot-choice strong { overflow: hidden; color: #172033; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.comparison-actions { display: flex; align-items: center; gap: 8px; }
.result-card { margin-top: 16px; }
.code-panel { max-height: 470px; margin: 0; padding: 16px; overflow: auto; color: #d9e2ed; background: #101827; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; white-space: pre; }
.diff-panel { color: #e6edf5; }
.diff-position { min-width: 48px; color: #718096; text-align: center; }
.diff-table { max-height: 560px; overflow: auto; background: #101827; }
.diff-row { display: grid; grid-template-columns: 70px minmax(360px, 1fr) 70px 70px minmax(360px, 1fr); min-width: 1100px; color: #f5f7fa; background: #1f2b3a; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; }
.diff-row > * { min-height: 28px; padding: 5px 8px; border-right: 1px solid #334155; border-bottom: 1px solid #334155; }
.diff-row code { overflow: hidden; color: inherit; font: inherit; text-overflow: ellipsis; white-space: pre; }
.diff-header { position: sticky; z-index: 2; top: 0; color: #d9e2ed; background: #182333; }
.diff-header > * { font-weight: 600; text-align: center; }
.line-number { color: #c9d4e2; background: #182333; text-align: center; }
.diff-status { text-align: center; }
.diff-row.is-added { color: #d8ffe3; background: #1f3d2b; }
.diff-row.is-removed { color: #ffd8dc; background: #4a2428; }
.diff-row.is-modified { color: #fff0c2; background: #4a3a1f; }
@media (max-width: 1200px) { .main-grid { grid-template-columns: 1fr; } }
@media (max-width: 1200px) { .comparison-basket { grid-template-columns: 1fr 1fr; } .comparison-actions { grid-column: 1 / -1; } }
@media (max-width: 1200px) { .toolbar { grid-template-columns: minmax(260px, 1fr) 210px; } .toolbar-actions { grid-column: 1 / -1; justify-content: flex-start; } }
@media (max-width: 760px) { .toolbar { grid-template-columns: 1fr; } .toolbar-actions { grid-column: auto; } .card-heading { align-items: flex-start; flex-direction: column; } .heading-actions { flex-wrap: wrap; width: 100%; } }
</style>
