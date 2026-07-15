<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, CopyDocument, Delete, Download, Edit, FolderOpened, Plus, Refresh, Upload, View } from '@element-plus/icons-vue'

import { isFeatureEnabled } from '../../features'
import {
  cancelDeviceTask,
  downloadDeviceExport,
  getDevice,
  getDeviceConnectionTest,
  getDeviceTask,
  listDevices,
  assignDeviceGroup,
  confirmDeviceImport,
  createDevice,
  createDeviceGroup,
  deleteDevices,
  deleteDeviceGroup,
  duplicateDevice,
  issueDeviceDeleteToken,
  previewDeviceImport,
  previewDeviceEdit,
  requestExternalTerminal,
  renameDeviceGroup,
  startBatchRefreshDetails,
  startDeviceCsvExport,
  startDeviceConnectionTest,
  startDeviceDiagnosticDownload,
  startDeviceTemplateExport,
  startOmniPeekExport,
  startSecureCrtExport,
  updateDevice,
} from '../../api/deviceManagement'
import type {
  DeviceConnectionProtocol,
  DeviceConnectionStatus,
  DeviceConnectionTest,
  DeviceDetailResponse,
  DeviceEditPreview,
  DeviceEditPreviewRequest,
  DeviceExportRequest,
  DeviceImportPreview,
  DeviceListItem,
  DevicePage,
  DeviceTaskReference,
} from '../../types/deviceManagement'

const emptyPage = (): DevicePage => ({ items: [], groups: [], total: 0, page: 1, page_size: 50, total_pages: 1 })
const loading = ref(false)
const error = ref('')
const pageData = ref<DevicePage>(emptyPage())
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref<DeviceDetailResponse | null>(null)
const connectionTest = ref<DeviceConnectionTest | null>(null)
const connectionLoading = ref(false)
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewResult = ref<DeviceEditPreview | null>(null)
const writeVisible = ref(false)
const writeMode = ref<'create' | 'edit'>('create')
const writeLoading = ref(false)
const selectedUuids = ref<string[]>([])
const groupVisible = ref(false)
const groupName = ref('')
const groupAssignVisible = ref(false)
const groupAssignId = ref<number | null>(null)
const importVisible = ref(false)
const importFile = ref<File | null>(null)
const importFileInput = ref<HTMLInputElement | null>(null)
const importLoading = ref(false)
const importPreview = ref<DeviceImportPreview | null>(null)
const trackedTasks = ref<DeviceTaskReference[]>([])
const filters = reactive({
  search: '',
  group: '',
  device_type: '',
  connection_status: '' as DeviceConnectionStatus | '',
  sort_by: 'name',
  sort_order: 'asc' as 'asc' | 'desc',
  page: 1,
  page_size: 50,
})
const editForm = reactive<DeviceEditPreviewRequest>({ name: '', primary_address: '' })
const writeForm = reactive<DeviceEditPreviewRequest>({ name: '', primary_address: '', ssh_enabled: true, ssh_port: 22, telnet_enabled: false, telnet_port: 23, snmp_enabled: true, snmp_v2c_enabled: true, snmp_port: 161 })
let pollTimer: number | undefined
let taskPollTimer: number | undefined
const taskStorageKey = 'netconsole.device-management.task-ids'

const isEmpty = computed(() => !loading.value && !error.value && pageData.value.items.length === 0)
const testTerminal = computed(() => connectionTest.value && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(connectionTest.value.task_status))
const testActive = computed(() => Boolean(connectionTest.value && !testTerminal.value))

onMounted(async () => {
  await loadDevices()
  await restoreTrackedTasks()
  await restoreConnectionTest()
})

onBeforeUnmount(() => {
  stopPolling()
  stopTaskPolling()
})

async function loadDevices(resetPage = false): Promise<void> {
  if (resetPage) filters.page = 1
  loading.value = true
  error.value = ''
  try {
    const groupId = filters.group && filters.group !== 'ungrouped' ? Number(filters.group) : undefined
    pageData.value = await listDevices({
      search: filters.search,
      group_id: groupId,
      ungrouped: filters.group === 'ungrouped' || undefined,
      device_type: filters.device_type,
      connection_status: filters.connection_status,
      page: filters.page,
      page_size: filters.page_size,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    })
    filters.page = pageData.value.page
  } catch (cause) {
    error.value = errorMessage(cause, '设备列表加载失败')
    pageData.value = emptyPage()
  } finally {
    loading.value = false
  }
}

async function openDetail(item: DeviceListItem): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  connectionTest.value = null
  try {
    detail.value = await getDevice(item.device_uuid)
    if (item.last_test_task_id) connectionTest.value = await getDeviceConnectionTest(item.last_test_task_id)
  } catch (cause) {
    detailError.value = errorMessage(cause, '设备详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function startTest(protocol: DeviceConnectionProtocol): Promise<void> {
  if (!detail.value || connectionLoading.value) return
  connectionLoading.value = true
  try {
    connectionTest.value = await startDeviceConnectionTest(detail.value.device.device_uuid, protocol)
    rememberTask(connectionTest.value.task_id)
    trackTasks([{
      task_id: connectionTest.value.task_id,
      task_status: connectionTest.value.task_status,
      action: 'connection_test',
      artifact_id: '',
      available: false,
      sha256: '',
      size_bytes: 0,
      message: connectionTest.value.message,
    }])
    startPolling()
    ElMessage.success(`${protocol} 连接测试任务已提交`)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '连接测试任务提交失败'))
  } finally {
    connectionLoading.value = false
  }
}

async function restoreConnectionTest(): Promise<void> {
  const taskId = new URLSearchParams(window.location.search).get('task_id')
  if (!taskId) return
  try {
    connectionTest.value = await getDeviceConnectionTest(taskId)
    if (connectionTest.value.device_uuid) {
      detailVisible.value = true
      detail.value = await getDevice(connectionTest.value.device_uuid)
    }
    if (!testTerminal.value) startPolling()
  } catch (cause) {
    ElMessage.warning(errorMessage(cause, '无法恢复连接测试状态'))
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    if (!connectionTest.value) return
    try {
      connectionTest.value = await getDeviceConnectionTest(connectionTest.value.task_id)
      if (testTerminal.value) {
        stopPolling()
        await loadDevices()
      }
    } catch (cause) {
      stopPolling()
      ElMessage.error(errorMessage(cause, '连接测试状态刷新失败'))
    }
  }, 1500)
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
  pollTimer = undefined
}

function rememberTask(taskId: string): void {
  const url = new URL(window.location.href)
  url.searchParams.set('task_id', taskId)
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
}

function isTaskTerminal(task: DeviceTaskReference): boolean {
  return ['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.task_status)
}

function isTaskActionEnabled(task: DeviceTaskReference): boolean {
  if (['batch_refresh_details', 'diagnostic_download'].includes(task.action)) {
    return isFeatureEnabled('web.device_management_collect')
  }
  if (task.action === 'import_csv') return isFeatureEnabled('web.device_management_import')
  if (task.action === 'connection_test') return isFeatureEnabled('web.device_connection_test')
  return isFeatureEnabled('web.device_management_export')
}

function persistTrackedTasks(): void {
  try {
    window.sessionStorage.setItem(taskStorageKey, JSON.stringify(trackedTasks.value.map((task) => task.task_id)))
  } catch {
    // 浏览器禁用会话存储时仍允许当前页面继续轮询。
  }
}

function trackTasks(tasks: DeviceTaskReference[]): void {
  for (const task of tasks) {
    const index = trackedTasks.value.findIndex((item) => item.task_id === task.task_id)
    if (index >= 0) trackedTasks.value[index] = task
    else trackedTasks.value.unshift(task)
  }
  trackedTasks.value = trackedTasks.value.slice(0, 30)
  persistTrackedTasks()
  if (trackedTasks.value.some((task) => !isTaskTerminal(task))) startTaskPolling()
}

async function restoreTrackedTasks(): Promise<void> {
  let taskIds: string[] = []
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(taskStorageKey) || '[]')
    taskIds = Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string') : []
  } catch {
    taskIds = []
  }
  const restored = await Promise.allSettled(taskIds.slice(0, 30).map((taskId) => getDeviceTask(taskId)))
  trackTasks(restored.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []))
}

function startTaskPolling(): void {
  stopTaskPolling()
  taskPollTimer = window.setInterval(() => void refreshTrackedTasks(), 1500)
}

function stopTaskPolling(): void {
  if (taskPollTimer !== undefined) window.clearInterval(taskPollTimer)
  taskPollTimer = undefined
}

async function refreshTrackedTasks(): Promise<void> {
  const active = trackedTasks.value.filter((task) => !isTaskTerminal(task))
  if (!active.length) {
    stopTaskPolling()
    return
  }
  const refreshed = await Promise.allSettled(active.map((task) => getDeviceTask(task.task_id)))
  trackTasks(refreshed.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []))
  if (!trackedTasks.value.some((task) => !isTaskTerminal(task))) {
    stopTaskPolling()
    await loadDevices()
  }
}

async function cancelTrackedTask(task: DeviceTaskReference): Promise<void> {
  try {
    trackTasks([await cancelDeviceTask(task.task_id)])
    ElMessage.success('已请求停止任务')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '任务停止失败'))
  }
}

function downloadTrackedTask(task: DeviceTaskReference): void {
  if (!task.available || !task.artifact_id) return
  window.location.assign(downloadDeviceExport(task.task_id, task.artifact_id))
}

function currentDeviceWriteValues(): DeviceEditPreviewRequest | null {
  if (!detail.value) return null
  const device = detail.value.device
  return {
    name: device.name,
    system_name: device.system_name,
    station: device.station,
    location: device.location,
    group_id: device.group_id,
    device_vendor: device.device_vendor,
    device_type: device.device_type,
    primary_address: device.primary_address,
    backup_address: device.backup_address,
    ssh_enabled: device.capabilities.ssh,
    ssh_port: device.capabilities.ssh_port || 22,
    telnet_enabled: device.capabilities.telnet,
    telnet_port: device.capabilities.telnet_port || 23,
    snmp_enabled: device.capabilities.snmp,
    snmp_v1_enabled: device.capabilities.snmp_versions.includes('v1'),
    snmp_v2c_enabled: device.capabilities.snmp_versions.includes('v2c'),
    snmp_v3_enabled: device.capabilities.snmp_versions.includes('v3'),
    snmp_port: device.capabilities.snmp_port || 161,
    https_port: device.https_port,
    remark: device.remark,
  }
}

function openPreview(): void {
  const values = currentDeviceWriteValues()
  if (!values) return
  Object.assign(editForm, values)
  previewResult.value = null
  previewVisible.value = true
}

async function validatePreview(): Promise<void> {
  if (!detail.value) return
  previewLoading.value = true
  try {
    previewResult.value = await previewDeviceEdit(detail.value.device.device_uuid, { ...editForm })
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '编辑预览校验失败'))
  } finally {
    previewLoading.value = false
  }
}

function onSelectionChange(rows: DeviceListItem[]): void {
  selectedUuids.value = rows.map((row) => row.device_uuid)
}

function openSelectedDetail(): void {
  const row = pageData.value.items.find((item) => item.device_uuid === selectedUuids.value[0])
  if (row) void openDetail(row)
}

function openCreate(): void {
  writeMode.value = 'create'
  Object.assign(writeForm, { name: '', system_name: '', station: '', location: '', group_id: null, device_vendor: 'H3C', device_type: 'SW', primary_address: '', backup_address: '', ssh_enabled: true, ssh_port: 22, telnet_enabled: false, telnet_port: 23, snmp_enabled: true, snmp_v1_enabled: false, snmp_v2c_enabled: true, snmp_v3_enabled: false, snmp_port: 161, https_port: null, remark: '' })
  writeVisible.value = true
}

function openEdit(): void {
  const values = currentDeviceWriteValues()
  if (!values) return
  writeMode.value = 'edit'
  Object.assign(writeForm, values)
  writeVisible.value = true
}

async function saveWrite(): Promise<void> {
  writeLoading.value = true
  try {
    if (writeMode.value === 'create') await createDevice({ ...writeForm })
    else if (detail.value) await updateDevice(detail.value.device.device_uuid, { ...writeForm })
    writeVisible.value = false
    ElMessage.success(writeMode.value === 'create' ? '设备已创建' : '设备已保存')
    await loadDevices(true)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设备保存失败'))
  } finally {
    writeLoading.value = false
  }
}

async function duplicateSelected(): Promise<void> {
  const uuid = selectedUuids.value[0] || detail.value?.device.device_uuid
  if (!uuid) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    await duplicateDevice(uuid)
    ElMessage.success('设备已复制')
    await loadDevices(true)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '复制设备失败'))
  }
}

async function deleteSelected(): Promise<void> {
  if (!selectedUuids.value.length || !window.confirm(`确认删除 ${selectedUuids.value.length} 台设备？`)) return
  try {
    const token = await issueDeviceDeleteToken(selectedUuids.value)
    await deleteDevices(selectedUuids.value, token.confirmation_token)
    selectedUuids.value = []
    ElMessage.success('设备已删除')
    await loadDevices(true)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '删除设备失败'))
  }
}

async function saveGroup(): Promise<void> {
  if (!groupName.value.trim()) return
  try {
    await createDeviceGroup(groupName.value.trim())
    groupName.value = ''
    groupVisible.value = false
    await loadDevices(true)
    ElMessage.success('分组已创建')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '分组创建失败'))
  }
}

async function renameGroup(groupId: number, currentName: string): Promise<void> {
  const name = window.prompt('请输入新分组名称', currentName)?.trim() || ''
  if (!name || name === currentName) return
  try {
    await renameDeviceGroup(groupId, name)
    await loadDevices(true)
    ElMessage.success('分组已重命名')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '分组重命名失败'))
  }
}

async function removeGroup(groupId: number, name: string): Promise<void> {
  if (!window.confirm(`确认删除分组“${name}”？设备将变为未分组。`)) return
  try {
    await deleteDeviceGroup(groupId)
    if (filters.group === String(groupId)) filters.group = ''
    await loadDevices(true)
    ElMessage.success('分组已删除')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '分组删除失败'))
  }
}

async function saveGroupAssignment(): Promise<void> {
  if (!selectedUuids.value.length) return
  try {
    const result = await assignDeviceGroup(selectedUuids.value, groupAssignId.value)
    groupAssignVisible.value = false
    ElMessage.success(`设置分组完成：成功 ${result.success}，失败 ${result.failed}`)
    await loadDevices(true)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设置分组失败'))
  }
}

async function runImportPreview(): Promise<void> {
  if (!importFile.value) return
  importLoading.value = true
  try {
    importPreview.value = await previewDeviceImport(importFile.value)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'CSV 预览失败'))
  } finally {
    importLoading.value = false
  }
}

async function confirmImport(): Promise<void> {
  if (!importPreview.value || importPreview.value.errors.length) return
  try {
    trackTasks([await confirmDeviceImport(importPreview.value.preview_token)])
    closeImportDialog()
    ElMessage.success('CSV 导入任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'CSV 导入失败'))
  }
}

function chooseImportFile(): void {
  importFileInput.value?.click()
}

function onImportFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  importFile.value = input.files?.[0] ?? null
  importPreview.value = null
  if (importFile.value) void runImportPreview()
}

function closeImportDialog(): void {
  importVisible.value = false
  importFile.value = null
  importPreview.value = null
  if (importFileInput.value) importFileInput.value.value = ''
}

function currentExportFilters(): DeviceExportRequest {
  return {
    device_uuids: selectedUuids.value,
    search: filters.search,
    vendor: '',
    device_type: filters.device_type,
    group_filter: filters.group === 'ungrouped' ? '__ungrouped__' : filters.group ? Number(filters.group) : undefined,
  }
}

async function exportCsv(): Promise<void> {
  try {
    trackTasks([await startDeviceCsvExport(currentExportFilters())])
    ElMessage.success('CSV 导出任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'CSV 导出失败'))
  }
}

async function exportTemplate(): Promise<void> {
  try {
    trackTasks([await startDeviceTemplateExport()])
    ElMessage.success('模板导出任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '模板导出失败'))
  }
}

async function exportSecureCrt(): Promise<void> {
  try {
    trackTasks([await startSecureCrtExport(currentExportFilters())])
    ElMessage.success('SecureCRT 会话任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'SecureCRT 会话生成失败'))
  }
}

async function exportOmniPeek(): Promise<void> {
  try {
    trackTasks([await startOmniPeekExport({ ...currentExportFilters(), line_name: 'NetConsole' })])
    ElMessage.success('OmniPeek 名称表任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'OmniPeek 名称表导出失败'))
  }
}

async function refreshSelectedDetails(): Promise<void> {
  if (!selectedUuids.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    const result = await startBatchRefreshDetails(selectedUuids.value)
    trackTasks(result.tasks)
    ElMessage.success('批量详情刷新任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '批量刷新失败'))
  }
}

async function downloadDiagnostics(): Promise<void> {
  if (!selectedUuids.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    trackTasks([await startDeviceDiagnosticDownload(selectedUuids.value)])
    ElMessage.success('诊断信息下载任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '诊断信息下载失败'))
  }
}

async function requestTerminal(): Promise<void> {
  const uuid = detail.value?.device.device_uuid || selectedUuids.value[0]
  if (!uuid) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    const action = await requestExternalTerminal(uuid, 'securecrt')
    ElMessage.info(`${action.native_action} 已生成，等待 Desktop Bridge 执行`)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '外部终端请求失败'))
  }
}

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手工选择文本')
  }
}

function statusType(status: DeviceConnectionStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'REACHABLE') return 'success'
  if (status === 'TESTING') return 'warning'
  if (['UNREACHABLE', 'ERROR'].includes(status)) return 'danger'
  return 'info'
}

function statusLabel(status: DeviceConnectionStatus): string {
  return { UNKNOWN: '未测试', TESTING: '测试中', REACHABLE: '可达', UNREACHABLE: '不可达', ERROR: '任务异常' }[status]
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}
</script>

<template>
  <section class="device-management">
    <div class="page-heading">
      <div><h1>设备管理</h1><p>与 Qt 设备页共享设备库、采集事实和后台任务；本页不保存凭据。</p></div>
      <div class="heading-actions"><el-button type="primary" :icon="Plus" :disabled="!isFeatureEnabled('web.device_management_write')" @click="openCreate">新建设备</el-button><el-button :icon="Refresh" :loading="loading" @click="loadDevices()">刷新</el-button></div>
    </div>

    <div class="content-card filters">
      <el-input v-model="filters.search" clearable placeholder="搜索名称、地址、站点、类型或分组" @keyup.enter="loadDevices(true)" />
      <el-select v-model="filters.group" clearable placeholder="全部分组" @change="loadDevices(true)">
        <el-option label="未分组" value="ungrouped" />
        <el-option v-for="group in pageData.groups" :key="group.id" :label="group.name" :value="String(group.id)" />
      </el-select>
      <el-select v-model="filters.device_type" clearable placeholder="全部类型" @change="loadDevices(true)">
        <el-option v-for="type in ['AC', 'SW', 'FW', 'Route', 'Cloud-AP', 'FAT-AP', 'Other']" :key="type" :label="type" :value="type" />
      </el-select>
      <el-select v-model="filters.connection_status" clearable placeholder="全部状态" @change="loadDevices(true)">
        <el-option label="未测试" value="UNKNOWN" /><el-option label="测试中" value="TESTING" />
        <el-option label="可达" value="REACHABLE" /><el-option label="不可达" value="UNREACHABLE" />
        <el-option label="任务异常" value="ERROR" />
      </el-select>
      <el-select v-model="filters.sort_by" @change="loadDevices(true)">
        <el-option label="按名称" value="name" /><el-option label="按地址" value="primary_address" />
        <el-option label="按站点" value="station" /><el-option label="按更新时间" value="updated_at" />
        <el-option label="按状态" value="status" />
      </el-select>
      <el-select v-model="filters.sort_order" @change="loadDevices(true)">
        <el-option label="升序" value="asc" /><el-option label="降序" value="desc" />
      </el-select>
      <el-button type="primary" @click="loadDevices(true)">筛选</el-button>
    </div>

    <div class="content-card action-bar">
      <span>已选 {{ selectedUuids.length }} 台</span>
      <el-button :icon="Edit" :disabled="selectedUuids.length !== 1 || !isFeatureEnabled('web.device_management_write')" @click="openSelectedDetail">编辑</el-button>
      <el-button :icon="CopyDocument" :disabled="selectedUuids.length !== 1 || !isFeatureEnabled('web.device_management_write')" @click="duplicateSelected">复制</el-button>
      <el-button :icon="Delete" type="danger" plain :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_write')" @click="deleteSelected">批量删除</el-button>
      <el-button :icon="FolderOpened" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_write')" @click="groupAssignVisible = true">设置分组</el-button>
      <el-button :icon="Plus" :disabled="!isFeatureEnabled('web.device_management_write')" @click="groupVisible = true">分组管理</el-button>
      <el-button :icon="Refresh" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_collect')" @click="refreshSelectedDetails">批量更新详情</el-button>
      <el-button :icon="Download" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_collect')" @click="downloadDiagnostics">下载诊断</el-button>
      <el-button :icon="Upload" :disabled="!isFeatureEnabled('web.device_management_import')" @click="importVisible = true">导入 CSV</el-button>
      <el-dropdown>
        <el-button :icon="Download" :disabled="!isFeatureEnabled('web.device_management_export')">导出</el-button>
        <template #dropdown><el-dropdown-menu><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportCsv">CSV 导出</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportTemplate">模板导出</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportOmniPeek">OmniPeek 名称表</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportSecureCrt">SecureCRT 会话</el-dropdown-item></el-dropdown-menu></template>
      </el-dropdown>
    </div>

    <div v-if="trackedTasks.length" class="content-card task-card">
      <div class="task-card-heading"><strong>本页任务</strong><span>刷新页面后仍会恢复最近 30 个任务</span></div>
      <el-table :data="trackedTasks" size="small" max-height="240">
        <el-table-column prop="action" label="动作" min-width="150" />
        <el-table-column prop="task_status" label="状态" width="110" />
        <el-table-column prop="task_id" label="Task ID" min-width="260" show-overflow-tooltip />
        <el-table-column prop="message" label="消息" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button v-if="row.available" link type="primary" :disabled="!isFeatureEnabled('web.device_management_export')" @click="downloadTrackedTask(row)">下载</el-button>
            <el-button v-if="!isTaskTerminal(row)" link type="danger" :disabled="!isTaskActionEnabled(row)" @click="cancelTrackedTask(row)">停止</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />
    <div v-loading="loading" class="content-card table-card" :data-state="isEmpty ? 'empty' : 'success'">
      <el-empty v-if="isEmpty" description="没有符合条件的设备" />
      <el-table v-else :data="pageData.items" stripe height="calc(100vh - 380px)" empty-text="暂无设备" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="44" fixed="left" />
        <el-table-column label="设备" min-width="190" fixed="left">
          <template #default="{ row }"><strong>{{ row.name }}</strong><small>{{ row.system_name || '未采集系统名' }}</small></template>
        </el-table-column>
        <el-table-column prop="primary_address" label="主地址" min-width="135" />
        <el-table-column prop="backup_address" label="备用地址" min-width="135" />
        <el-table-column prop="group_name" label="分组" min-width="120" />
        <el-table-column prop="station" label="归属站点" min-width="140" />
        <el-table-column label="厂商 / 类型" min-width="130"><template #default="{ row }">{{ row.device_vendor }} / {{ row.device_type }}</template></el-table-column>
        <el-table-column label="能力" min-width="180"><template #default="{ row }">{{ [row.capabilities.ssh && 'SSH', row.capabilities.telnet && 'Telnet', row.capabilities.snmp && 'SNMP'].filter(Boolean).join(' / ') || '--' }}</template></el-table-column>
        <el-table-column label="连接状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.connection_status)">{{ statusLabel(row.connection_status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="88" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination
        v-if="pageData.total"
        v-model:current-page="filters.page"
        v-model:page-size="filters.page_size"
        :total="pageData.total"
        :page-sizes="[20, 50, 100, 200]"
        layout="total, sizes, prev, pager, next"
        @current-change="loadDevices()"
        @size-change="loadDevices(true)"
      />
    </div>

    <el-drawer v-model="detailVisible" title="设备详情" size="min(880px, 96vw)">
      <div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" :title="detailError" type="error" show-icon :closable="false" />
        <template v-else-if="detail">
          <div class="detail-heading">
            <div><h2>{{ detail.device.name }}</h2><p>{{ detail.device.device_uuid }}</p></div>
            <div class="heading-actions"><el-button :icon="FolderOpened" :disabled="!isFeatureEnabled('web.device_management_desktop')" @click="requestTerminal">外部终端</el-button><el-button :icon="Edit" :disabled="!isFeatureEnabled('web.device_edit_preview') || !isFeatureEnabled('web.device_management_write')" @click="openPreview">编辑预览</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.device_management_write')" @click="openEdit">正式编辑</el-button></div>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="系统名">{{ detail.device.system_name || '--' }}</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag :type="statusType(detail.device.connection_status)">{{ statusLabel(detail.device.connection_status) }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="主 / 备用地址">{{ detail.device.primary_address }} / {{ detail.device.backup_address || '--' }}</el-descriptions-item>
            <el-descriptions-item label="厂商 / 类型">{{ detail.device.device_vendor }} / {{ detail.device.device_type }}</el-descriptions-item>
            <el-descriptions-item label="站点 / 位置">{{ detail.device.station || '--' }} / {{ detail.device.location || '--' }}</el-descriptions-item>
            <el-descriptions-item label="MAC">{{ detail.device.mac_address || detail.fact?.mac_address || '--' }}</el-descriptions-item>
            <el-descriptions-item label="型号 / 版本">{{ detail.fact?.model || '--' }} / {{ detail.fact?.software_version || '--' }}</el-descriptions-item>
            <el-descriptions-item label="最近采集">{{ detail.fact?.collected_at || '--' }}</el-descriptions-item>
            <el-descriptions-item label="备注" :span="2">{{ detail.device.remark || '--' }}</el-descriptions-item>
          </el-descriptions>

          <section class="detail-section">
            <h3>连接测试</h3>
            <div class="action-row">
              <el-button v-if="detail.device.capabilities.ssh" :icon="Connection" :loading="connectionLoading" :disabled="testActive || !isFeatureEnabled('web.device_connection_test')" @click="startTest('SSH')">测试 SSH</el-button>
              <el-button v-if="detail.device.capabilities.telnet" :icon="Connection" :loading="connectionLoading" :disabled="testActive || !isFeatureEnabled('web.device_connection_test')" @click="startTest('TELNET')">测试 Telnet</el-button>
              <el-button v-if="detail.device.capabilities.snmp" :icon="Connection" :loading="connectionLoading" :disabled="testActive || !isFeatureEnabled('web.device_connection_test')" @click="startTest('SNMP')">测试 SNMP</el-button>
            </div>
            <el-alert
              v-if="connectionTest"
              :title="`${connectionTest.protocol || '连接'} · ${connectionTest.task_status} · ${connectionTest.message || '等待结果'}`"
              :type="connectionTest.success === true ? 'success' : connectionTest.success === false ? 'error' : 'info'"
              :description="`Task ID: ${connectionTest.task_id}${connectionTest.suggestion ? `；建议：${connectionTest.suggestion}` : ''}`"
              show-icon
              :closable="false"
            />
          </section>

          <section v-if="detail.connection_commands.length" class="detail-section">
            <h3>连接命令（不含凭据）</h3>
            <div v-for="item in detail.connection_commands" :key="item.protocol" class="command-row">
              <code>{{ item.command }}</code><el-button link :icon="CopyDocument" @click="copyText(item.command)">复制</el-button>
            </div>
          </section>

          <section class="detail-section">
            <h3>最近任务</h3>
            <el-table :data="detail.recent_tasks" size="small" empty-text="暂无关联任务">
              <el-table-column prop="task_name" label="任务" min-width="180" /><el-table-column prop="status" label="状态" width="105" />
              <el-table-column prop="updated_time" label="更新时间" width="190" /><el-table-column prop="error_summary" label="错误" min-width="180" show-overflow-tooltip />
            </el-table>
          </section>

          <section v-if="detail.recent_collection" class="detail-section">
            <h3>最近采集</h3>
            <el-alert :title="`${detail.recent_collection.collect_type} · ${detail.recent_collection.status}`" :description="detail.recent_collection.error_summary || detail.recent_collection.ended_at" type="info" :closable="false" />
          </section>
          <section v-if="detail.recent_errors.length" class="detail-section">
            <h3>最近错误</h3>
            <el-table :data="detail.recent_errors" size="small">
              <el-table-column prop="source" label="来源" width="100" /><el-table-column prop="time" label="时间" width="190" />
              <el-table-column prop="message" label="错误摘要" min-width="260" show-overflow-tooltip />
            </el-table>
          </section>
          <el-alert v-if="!detail.fact && !detail.recent_tasks.length && !detail.recent_collection" title="当前没有采集事实、关联任务或错误记录" type="info" :closable="false" show-icon />
        </template>
      </div>
    </el-drawer>

    <el-dialog v-model="previewVisible" title="受控编辑预览" width="min(760px, 94vw)">
      <el-alert title="仅校验和预览，不保存设备或凭据" type="info" show-icon :closable="false" />
      <el-form label-width="100px" class="preview-form">
        <el-form-item label="设备名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="系统名"><el-input v-model="editForm.system_name" /></el-form-item>
        <el-form-item label="主地址"><el-input v-model="editForm.primary_address" /></el-form-item>
        <el-form-item label="备用地址"><el-input v-model="editForm.backup_address" /></el-form-item>
        <el-form-item label="站点"><el-input v-model="editForm.station" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="editForm.location" /></el-form-item>
        <el-form-item label="连接能力">
          <el-checkbox v-model="editForm.ssh_enabled">SSH</el-checkbox><el-checkbox v-model="editForm.telnet_enabled">Telnet</el-checkbox><el-checkbox v-model="editForm.snmp_enabled">SNMP</el-checkbox>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="editForm.remark" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <el-alert v-if="previewResult" :title="previewResult.valid ? '校验通过（尚未保存）' : '校验未通过'" :description="[...previewResult.errors, ...previewResult.warnings].join('；') || '字段符合当前设备表单规则'" :type="previewResult.valid ? 'success' : 'error'" show-icon :closable="false" />
      <template #footer><el-button @click="previewVisible = false">关闭</el-button><el-button type="primary" :loading="previewLoading" :disabled="!isFeatureEnabled('web.device_edit_preview') || !isFeatureEnabled('web.device_management_write')" @click="validatePreview">校验预览</el-button></template>
    </el-dialog>

    <el-dialog v-model="writeVisible" :title="writeMode === 'create' ? '新建设备' : '正式编辑设备'" width="min(760px, 94vw)">
      <el-alert title="Web 写入不接收或显示任何密码、community、SNMPv3 secret；编辑时保留服务端原凭据。" type="info" show-icon :closable="false" />
      <el-form label-width="100px" class="preview-form">
        <el-form-item label="设备名称"><el-input v-model="writeForm.name" /></el-form-item>
        <el-form-item label="系统名"><el-input v-model="writeForm.system_name" /></el-form-item>
        <el-form-item label="主地址"><el-input v-model="writeForm.primary_address" /></el-form-item>
        <el-form-item label="备用地址"><el-input v-model="writeForm.backup_address" /></el-form-item>
        <el-form-item label="厂商 / 类型"><el-input v-model="writeForm.device_vendor" /><el-input v-model="writeForm.device_type" /></el-form-item>
        <el-form-item label="站点 / 位置"><el-input v-model="writeForm.station" /><el-input v-model="writeForm.location" /></el-form-item>
        <el-form-item label="连接能力"><el-checkbox v-model="writeForm.ssh_enabled">SSH</el-checkbox><el-checkbox v-model="writeForm.telnet_enabled">Telnet</el-checkbox><el-checkbox v-model="writeForm.snmp_enabled">SNMP</el-checkbox></el-form-item>
        <el-form-item label="备注"><el-input v-model="writeForm.remark" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="writeVisible = false">取消</el-button><el-button type="primary" :loading="writeLoading" :disabled="!isFeatureEnabled('web.device_management_write')" @click="saveWrite">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="groupVisible" title="分组管理" width="420px">
      <el-input v-model="groupName" placeholder="新分组名称" @keyup.enter="saveGroup" />
      <div class="group-list">
        <div v-for="group in pageData.groups" :key="group.id" class="group-row">
          <span>{{ group.name }}</span>
          <span>
            <el-button link type="primary" :disabled="!isFeatureEnabled('web.device_management_write')" @click="renameGroup(group.id, group.name)">重命名</el-button>
            <el-button link type="danger" :disabled="!isFeatureEnabled('web.device_management_write')" @click="removeGroup(group.id, group.name)">删除</el-button>
          </span>
        </div>
        <el-empty v-if="!pageData.groups.length" description="暂无分组" :image-size="56" />
      </div>
      <template #footer><el-button @click="groupVisible = false">取消</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.device_management_write')" @click="saveGroup">新增分组</el-button></template>
    </el-dialog>

    <el-dialog v-model="groupAssignVisible" title="设置分组" width="420px">
      <el-select v-model="groupAssignId" clearable placeholder="选择分组（清空为未分组）" style="width: 100%"><el-option v-for="group in pageData.groups" :key="group.id" :label="group.name" :value="group.id" /></el-select>
      <template #footer><el-button @click="groupAssignVisible = false">取消</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.device_management_write')" @click="saveGroupAssignment">确认</el-button></template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="CSV 导入预览 / 确认" width="min(680px, 94vw)" @close="closeImportDialog">
      <el-alert title="先预览再确认；服务端校验 SHA-256 并以单事务提交。备份只供人工恢复，任务失败不会覆盖同期数据。" type="info" show-icon :closable="false" />
      <input ref="importFileInput" class="visually-hidden" type="file" accept=".csv,text/csv" @change="onImportFileChange" />
      <div class="import-file-picker"><el-button :disabled="!isFeatureEnabled('web.device_management_import')" @click="chooseImportFile">选择 CSV 文件</el-button><span>{{ importFile?.name || '尚未选择文件' }}</span></div>
      <div v-if="importPreview" class="import-summary"><p>{{ importPreview.source_name }} · {{ importPreview.row_count }} 行 · {{ importPreview.source_sha256 }}</p><el-alert v-for="item in importPreview.errors" :key="item" :title="item" type="error" :closable="false" /><el-alert v-for="item in importPreview.warnings" :key="item" :title="item" type="warning" :closable="false" /></div>
      <template #footer><el-button @click="closeImportDialog">关闭</el-button><el-button :loading="importLoading" :disabled="!importFile || !isFeatureEnabled('web.device_management_import')" @click="runImportPreview">预览</el-button><el-button type="primary" :disabled="!importPreview || !!importPreview.errors.length || !isFeatureEnabled('web.device_management_import')" @click="confirmImport">确认导入</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.device-management { max-width: 1720px; margin: 0 auto; }
.page-heading, .detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.heading-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.group-list { margin-top: 16px; max-height: 260px; overflow-y: auto; }
.group-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.page-heading h1, .detail-heading h2, .detail-section h3 { margin: 0; }
.page-heading p, .detail-heading p { margin: 5px 0 0; color: #718096; font-size: 13px; }
.filters { display: grid; grid-template-columns: minmax(240px, 2fr) repeat(5, minmax(120px, 1fr)) auto; gap: 10px; padding: 14px; margin-bottom: 14px; }
.state-alert { margin-bottom: 14px; }
.action-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; margin-bottom: 14px; }
.action-bar > span { margin-right: 4px; color: #718096; font-size: 13px; }
.task-card { padding: 12px 14px; margin-bottom: 14px; }
.task-card-heading { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 10px; color: #718096; font-size: 13px; }
.task-card-heading strong { color: var(--el-text-color-primary); }
.table-card { min-height: 300px; padding: 0 0 12px; }
.table-card :deep(.el-pagination) { justify-content: flex-end; padding: 14px 16px 0; }
.table-card strong, .table-card small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-card small { margin-top: 4px; color: #8491a3; }
.detail-body { min-height: 240px; }
.detail-section { margin-top: 22px; }
.detail-section h3 { margin-bottom: 11px; font-size: 15px; }
.action-row { display: flex; flex-wrap: wrap; gap: 9px; margin-bottom: 12px; }
.command-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 12px; background: #f4f7fa; border-radius: 7px; }
.command-row + .command-row { margin-top: 8px; }
.command-row code { overflow-wrap: anywhere; }
.preview-form { margin-top: 18px; }
.import-summary { margin-top: 16px; overflow-wrap: anywhere; }
.import-file-picker { display: flex; align-items: center; gap: 12px; margin-top: 18px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 1280px) { .filters { grid-template-columns: repeat(3, minmax(150px, 1fr)); } }
@media (max-width: 760px) { .filters { grid-template-columns: 1fr; } .page-heading { align-items: flex-start; } }
</style>
