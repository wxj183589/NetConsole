<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import {
  cancelFileDownload,
  clearFileDownloads,
  connectDeviceFiles,
  createLocalDirectory,
  disconnectDeviceFiles,
  fileDownloadRequest,
  getFileManagementStatus,
  listFileDownloads,
  listLocalFiles,
  listRemoteDevices,
  listRemoteFiles,
  localFileDownloadRequest,
  prepareFileDesktopAction,
  retryFileDownload,
  startRemoteFileDownloadBatch,
  trustDeviceHostKey,
} from '../../api/fileManagement'
import { ApiRequestError } from '../../api/client'
import { isFeatureEnabled } from '../../features'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import type {
  FileConnection,
  FileDownloadTask,
  FileRemoteDevice,
  LocalFileEntry,
  LocalFilePage,
  RemoteFileEntry,
  RemoteFilePage,
} from '../../types/fileManagement'
import {
  activeDownloadTasks,
  formatBytes,
  formatSpeed,
  mergeDownloadTasks,
  selectableRemoteFiles,
  summarizeDownloadBatches,
} from './fileManagementModel'
import { createFileManagementTranslator } from './fileManagementI18n'
import { useConfirm } from '../../components/feedback/useConfirm'

const t = createFileManagementTranslator()
const { confirm, confirmChoice } = useConfirm()

const router = useRouter()
const siteId = ref('')
const loading = ref(false)
const error = ref('')
const localError = ref('')
const remoteError = ref('')
const queueError = ref('')
const deviceFilesMessage = ref('')
const winscpAvailable = ref(false)
const winscpMessage = ref('')
const desktopAvailable = Boolean(window.netconsoleDesktop)
const localPage = ref<LocalFilePage | null>(null)
const localLoading = ref(false)
const localPageNumber = ref(1)
const devices = ref<FileRemoteDevice[]>([])
const selectedDeviceId = ref('')
const deviceSearch = ref('')
const deviceGroup = ref('')
const allowSftpSetup = ref(false)
const sftpSetupConfirmed = ref(false)
const sftpSetupConfirmationPending = ref(false)
const sftpSetupTaskId = ref('')
const connection = ref<FileConnection | null>(null)
const remotePage = ref<RemoteFilePage | null>(null)
const remoteLoading = ref(false)
const downloadLoading = ref(false)
const remotePageNumber = ref(1)
const remoteSelected = ref<RemoteFileEntry[]>([])
const remoteTable = ref<{ clearSelection(): void; toggleRowSelection(row: RemoteFileEntry, selected: boolean): void } | null>(null)
const tasks = ref<FileDownloadTask[]>([])
const savedCapabilities = ref(new Map<string, string>())
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const activeTasks = computed(() => activeDownloadTasks(tasks.value))
const selectedDevice = computed(() => devices.value.find((device) => device.device_id === selectedDeviceId.value) || null)
const isVehicleMrDevice = computed(() => {
  const device = selectedDevice.value
  if (!device) return false
  const deviceType = String(device.device_type || '').trim().toUpperCase()
  const groupName = String(device.group_name || '')
  return deviceType === 'MR' || deviceType === 'MOBILE_ROUTER' || groupName.includes('车载-MR')
})
const deviceGroups = computed(() => [...new Set(devices.value.map((device) => device.group_name || '未分组'))].sort((a, b) => a.localeCompare(b)))
const meshRemoteFiles = computed(() => selectableRemoteFiles(remotePage.value?.items || [], true))
const filteredDevices = computed(() => {
  const query = deviceSearch.value.trim().toLocaleLowerCase()
  return devices.value.filter((device) => {
    const group = device.group_name || '未分组'
    return (!deviceGroup.value || group === deviceGroup.value)
      && (!query || `${device.name} ${device.address} ${device.station} ${group} ${device.device_type}`.toLocaleLowerCase().includes(query))
  })
})
const batchSummaries = computed(() => summarizeDownloadBatches(tasks.value).slice(0, 5))
const localFileColumns: NcTableColumn<LocalFileEntry>[] = [
  { key: 'name', label: '名称', valueType: 'name', align: 'left', alignmentReason: 'long-text' },
  { key: 'type', label: '类型', valueType: 'text', displayValue: (row) => row.is_dir ? '目录' : row.file_type },
  { key: 'size_bytes', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '修改时间', valueType: 'datetime' },
]
const remoteFileColumns: NcTableColumn<RemoteFileEntry>[] = [
  {
    key: 'selection', label: '', type: 'selection', valueType: 'selection', hideable: false,
    columnAttrs: { selectable: (row: RemoteFileEntry) => !row.is_dir && row.downloadable },
  },
  { key: 'name', label: '名称', valueType: 'name', align: 'left', alignmentReason: 'long-text' },
  { key: 'category', label: '分类', valueType: 'text' },
  { key: 'size_bytes', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '修改时间', valueType: 'datetime' },
]
const downloadTaskColumns: NcTableColumn<FileDownloadTask>[] = [
  {
    key: 'file', label: '文件', valueType: 'description', alignmentReason: 'long-text',
    measureValue: (row) => `${row.remote_name || row.result?.name || row.task_id} ${row.device_name || ''}`,
  },
  { key: 'batch', label: '批次', valueType: 'text', displayValue: (row) => row.batch_id ? row.batch_id.slice(0, 10) : '—' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'progress', label: '进度', valueType: 'percentage', measureValue: (row) => `${row.progress}% ${formatBytes(row.downloaded_bytes)} / ${formatBytes(row.total_bytes)}` },
  { key: 'message', label: '信息', valueType: 'description', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['取消', '重试', '保存', '打开', '所在目录'] },
]
const SFTP_SETUP_SUCCESS_MESSAGE = '已在设备侧启用 SFTP，并完成重新连接。'
const SFTP_CONNECTION_ERROR_MESSAGES: Record<string, string> = {
  DEVICE_FILE_SFTP_UNAVAILABLE: '设备 SFTP 未启用。请开启“SFTP 未启用时，允许自动配置并重连”后重试。',
  DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED: '当前设备厂商或版本不支持自动启用 SFTP，未执行设备配置。',
  DEVICE_FILE_SFTP_ENABLE_PENDING: '启用设备 SFTP 的受控任务仍在运行，请稍候后从任务中心查看结果。',
  DEVICE_FILE_SFTP_ENABLE_FAILED: '设备 SFTP 自动启用失败。请查看任务日志，并检查设备权限和 Command Profile。',
  DEVICE_FILE_SFTP_ENABLE_SUCCEEDED_BUT_RECONNECT_FAILED: '设备侧 SFTP 已启用，但重新连接失败。请查看任务，并检查 SFTP 服务和网络连通性。',
}
const MESH_IMPORT_STATUS_LABELS: Record<string, string> = {
  completed: '完成',
  duplicate: '重复',
  failed: '失败',
  rebuild_required: '重建待处理',
}

function openTaskWindow(taskId = ''): void {
  if (window.netconsoleDesktop) void window.netconsoleDesktop.openTaskWindow({ module: 'files', ...(taskId ? { taskId } : {}) })
  else void router.push({ name: 'tasks', query: { module: 'files', ...(taskId ? { task_id: taskId } : {}) } })
}

onMounted(() => void initialize())

onBeforeUnmount(() => {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
  if (connection.value) void disconnectDeviceFiles(connection.value.connection_id, siteId.value).catch(() => undefined)
})

async function initialize(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const status = await getFileManagementStatus(siteId.value)
    siteId.value = status.site_id
    deviceFilesMessage.value = status.device_files.message
    winscpAvailable.value = status.winscp.available
    winscpMessage.value = status.winscp.message
    if (isFeatureEnabled('web.file_management_remote')) {
      try { devices.value = await listRemoteDevices(siteId.value) } catch (reason) {
        devices.value = []
        remoteError.value = messageOf(reason, '设备列表读取失败')
      }
    }
    await Promise.all([loadLocal('', 1), recoverTasks()])
  } catch (reason) {
    error.value = messageOf(reason, '文件管理初始化失败')
  } finally {
    loading.value = false
  }
}

async function refreshAll(): Promise<void> {
  await initialize()
  if (connection.value) await loadRemote(remotePage.value?.current_entry_id || connection.value.root_entry_id, remotePageNumber.value)
}

async function loadLocal(directoryId = '', page = 1): Promise<void> {
  localLoading.value = true
  localError.value = ''
  try {
    localPage.value = await listLocalFiles({
      site_id: siteId.value,
      directory_id: directoryId,
      device_id: selectedDeviceId.value,
      page,
      limit: 500,
    })
    localPageNumber.value = localPage.value.page
  } catch (reason) {
    localError.value = messageOf(reason, '本地目录读取失败')
  } finally {
    localLoading.value = false
  }
}

async function deviceChanged(): Promise<void> {
  await disconnectDevice()
  await loadLocal('', 1)
}

async function openLocal(row: LocalFileEntry): Promise<void> {
  if (row.is_dir) {
    await loadLocal(row.entry_id, 1)
    return
  }
  try {
    const result = await downloadBackendResource(localFileDownloadRequest(row.entry_id, siteId.value, row.name))
    if (result.status === 'saved' && result.capabilityId) {
      const opened = await getPlatformAdapter().openPath(result.capabilityId)
      if (!opened.success) localError.value = opened.error || '文件打开失败'
    } else if (result.status === 'failed') {
      localError.value = result.error || '文件打开失败'
    }
  } catch (reason) {
    localError.value = messageOf(reason, '文件打开失败')
  }
}

async function createDirectory(): Promise<void> {
  if (!localPage.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入新目录名称', '新建目录', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '目录名不能为空',
    })
    localPage.value = await createLocalDirectory({
      site_id: siteId.value,
      directory_id: localPage.value.current_entry_id,
      device_id: selectedDeviceId.value,
      name: value,
    })
    ElMessage.success('目录已创建')
  } catch (reason) {
    if (reason !== 'cancel' && reason !== 'close') localError.value = messageOf(reason, '目录创建失败')
  }
}

async function prepareLocalOpen(): Promise<void> {
  if (!localPage.value) return
  await showDesktopDependency('open_local', { local_entry_id: localPage.value.current_entry_id })
}

async function confirmSftpSetup(enabled: boolean): Promise<void> {
  if (!enabled || sftpSetupConfirmed.value) return
  sftpSetupConfirmationPending.value = true
  try {
    const accepted = await confirm({
      type: 'DANGER',
      title: '确认允许自动配置 SFTP',
      message: 'SFTP 未启用时，NetConsole 将通过版本化 Command Profile 执行受控设备配置并重新连接。',
      detail: '请确认你拥有设备配置权限。远程文件始终只读，不会上传、删除、重命名或创建远程目录。',
      confirmText: '允许自动配置',
    })
    if (accepted) sftpSetupConfirmed.value = true
    else allowSftpSetup.value = false
  } catch {
    allowSftpSetup.value = false
  } finally {
    sftpSetupConfirmationPending.value = false
  }
}

function applySftpConnectionError(reason: ApiRequestError, fallback: string): void {
  const taskId = reason.details.task_id
  sftpSetupTaskId.value = typeof taskId === 'string' ? taskId : ''
  remoteError.value = SFTP_CONNECTION_ERROR_MESSAGES[reason.code] || messageOf(reason, fallback)
}

async function connectDevice(): Promise<void> {
  if (!selectedDeviceId.value) return
  if (allowSftpSetup.value && (!sftpSetupConfirmed.value || sftpSetupConfirmationPending.value)) return
  remoteLoading.value = true
  remoteError.value = ''
  sftpSetupTaskId.value = ''
  try {
    await disconnectDevice()
    connection.value = await connectDeviceFiles(selectedDeviceId.value, siteId.value, allowSftpSetup.value)
    await loadRemote(connection.value.root_entry_id, 1)
    if (connection.value.message === SFTP_SETUP_SUCCESS_MESSAGE) ElMessage.success(connection.value.message)
  } catch (reason) {
    if (reason instanceof ApiRequestError && reason.code === 'DEVICE_FILE_HOST_KEY_UNKNOWN') {
      const details = reason.details
      const challengeId = String(details.challenge_id || '')
      const choice = await confirmChoice({
        type: 'SECURITY',
        title: '首次连接：确认设备主机密钥',
        message: `设备：${String(details.device_name || selectedDevice.value?.name || '当前设备')}\n地址：${String(details.host || selectedDevice.value?.address || '')}:${String(details.port || 22)}\n密钥算法：${String(details.algorithm || '未知')}\nSHA256 指纹：${String(details.fingerprint_sha256 || '未知')}`,
        detail: '首次连接时请确认该指纹确实属于目标设备。信任错误的主机密钥可能导致连接到错误设备。',
        confirmText: '仅本次信任',
        secondaryText: '信任并保存',
        acknowledgementText: '我已核对该设备指纹',
        requireAcknowledgement: true,
      })
      if (choice !== 'cancel' && challengeId) {
        try {
          connection.value = await trustDeviceHostKey(challengeId, choice === 'secondary', siteId.value, allowSftpSetup.value)
          await loadRemote(connection.value.root_entry_id, 1)
          if (connection.value.message === SFTP_SETUP_SUCCESS_MESSAGE) ElMessage.success(connection.value.message)
          return
        } catch (trustError) {
          if (trustError instanceof ApiRequestError && trustError.code in SFTP_CONNECTION_ERROR_MESSAGES) {
            applySftpConnectionError(trustError, '主机密钥信任失败')
          } else remoteError.value = messageOf(trustError, '主机密钥信任失败')
        }
      } else {
        remoteError.value = '已取消主机密钥信任，连接未建立。'
      }
    } else if (reason instanceof ApiRequestError && reason.code in SFTP_CONNECTION_ERROR_MESSAGES) applySftpConnectionError(reason, '设备文件连接失败')
    else remoteError.value = messageOf(reason, '设备文件连接失败')
    connection.value = null
    remotePage.value = null
  } finally {
    remoteLoading.value = false
  }
}

async function disconnectDevice(): Promise<void> {
  if (connection.value) {
    try { await disconnectDeviceFiles(connection.value.connection_id, siteId.value) } catch { /* 后端会话失效也应清空页面 */ }
  }
  connection.value = null
  remotePage.value = null
  remoteSelected.value = []
  remoteTable.value?.clearSelection()
}

async function loadRemote(entryId = '', page = 1): Promise<void> {
  if (!connection.value) return
  remoteLoading.value = true
  remoteError.value = ''
  try {
    remotePage.value = await listRemoteFiles(connection.value.connection_id, entryId, siteId.value, page, 500)
    remotePageNumber.value = remotePage.value.page
    remoteSelected.value = []
    remoteTable.value?.clearSelection()
  } catch (reason) {
    remoteError.value = messageOf(reason, '远程目录读取失败')
  } finally {
    remoteLoading.value = false
  }
}

function selectRemote(rows: RemoteFileEntry[]): void {
  remoteSelected.value = rows.filter((row) => !row.is_dir && row.downloadable)
}

function selectAllRemote(meshOnly = false): void {
  remoteTable.value?.clearSelection()
  for (const row of selectableRemoteFiles(remotePage.value?.items || [], meshOnly)) {
    remoteTable.value?.toggleRowSelection(row, true)
  }
}

function clearRemoteSelection(): void {
  remoteTable.value?.clearSelection()
  remoteSelected.value = []
}

async function openRemote(row: RemoteFileEntry): Promise<void> {
  if (row.is_dir) {
    await loadRemote(row.entry_id, 1)
    return
  }
  if (row.downloadable) {
    remoteTable.value?.toggleRowSelection(row, !remoteSelected.value.some((item) => item.entry_id === row.entry_id))
  }
}

async function downloadRemote(): Promise<void> {
  await downloadRemoteEntries(remoteSelected.value)
}

async function downloadMeshLogsAndImport(): Promise<void> {
  if (!connection.value || !localPage.value || !isVehicleMrDevice.value) return
  const rows = meshRemoteFiles.value
  if (!rows.length) {
    remoteError.value = '当前目录没有可下载的 MESH 日志'
    return
  }
  const totalBytes = rows.reduce((sum, row) => sum + Math.max(0, Number(row.size_bytes || 0)), 0)
  const accepted = await confirm({
    type: 'INFO',
    title: '确认下载并传入 MESH 分析',
    message: [
      `目标车载 MR：${selectedDevice.value?.name || connection.value.device_name}`,
      `文件数量：${rows.length}`,
      `总大小：${formatBytes(totalBytes)}`,
      '归档目录：对应车载 MR 的 raw 目录',
      '下载完成后将自动尝试导入；若派生库需要重建，系统会单独标记该状态。',
    ].join('\n'),
    confirmText: '下载并导入',
  })
  if (!accepted) return
  await downloadRemoteEntries(rows)
}

async function downloadRemoteEntries(rows: RemoteFileEntry[]): Promise<void> {
  if (!connection.value || !localPage.value || !rows.length) return
  downloadLoading.value = true
  remoteError.value = ''
  try {
    const batch = await startRemoteFileDownloadBatch(
      connection.value.connection_id,
      rows.map((row) => row.entry_id),
      siteId.value,
      localPage.value.current_entry_id,
    )
    tasks.value = mergeDownloadTasks(tasks.value, batch.tasks)
    if (batch.failures.length) remoteError.value = batch.failures.join('；')
    clearRemoteSelection()
    scheduleTaskRefresh()
  } catch (reason) {
    remoteError.value = messageOf(reason, '批量下载创建失败')
  } finally {
    downloadLoading.value = false
  }
}

function meshImportStatusText(status: string): string {
  return MESH_IMPORT_STATUS_LABELS[status] || status
}

async function prepareWinscp(): Promise<void> {
  if (!selectedDeviceId.value) return
  await showDesktopDependency('winscp', { device_id: selectedDeviceId.value })
}

async function showDesktopDependency(
  action: 'winscp' | 'open_local' | 'open_result_dir',
  values: { device_id?: string; local_entry_id?: string; task_id?: string },
): Promise<void> {
  try {
    if (!window.netconsoleDesktop) throw new Error('该操作只能在 Electron Desktop 中执行')
    const result = await prepareFileDesktopAction(action, { site_id: siteId.value, ...values })
    const executed = await window.netconsoleDesktop.executeFileDesktopAction(result.action_ref)
    if (!executed.success) throw new Error(executed.error || '桌面操作失败')
    ElMessage.success(action === 'winscp' ? '已启动 WinSCP' : '已打开目录')
  } catch (reason) {
    error.value = messageOf(reason, '桌面操作失败')
  }
}

async function recoverTasks(): Promise<void> {
  queueError.value = ''
  try {
    tasks.value = mergeDownloadTasks([], await listFileDownloads(siteId.value, 100))
  } catch (reason) {
    queueError.value = messageOf(reason, '下载队列恢复失败')
  }
  scheduleTaskRefresh()
}

async function refreshTasks(): Promise<void> {
  try {
    tasks.value = mergeDownloadTasks(tasks.value, await listFileDownloads(siteId.value, 100))
  } catch (reason) {
    queueError.value = messageOf(reason, '下载队列刷新失败')
  }
  scheduleTaskRefresh()
}

function scheduleTaskRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = activeTasks.value.length ? setTimeout(() => void refreshTasks(), 1_500) : null
}

async function cancelTask(task: FileDownloadTask): Promise<void> {
  try {
    tasks.value = mergeDownloadTasks(tasks.value, [await cancelFileDownload(task.task_id, siteId.value)])
    scheduleTaskRefresh()
  } catch (reason) {
    queueError.value = messageOf(reason, '下载取消失败')
  }
}

async function retryTask(task: FileDownloadTask): Promise<void> {
  try {
    tasks.value = mergeDownloadTasks(tasks.value, [await retryFileDownload(task.task_id, siteId.value)])
    scheduleTaskRefresh()
  } catch (reason) {
    queueError.value = messageOf(reason, '下载重试失败')
  }
}

async function clearTasks(status: 'COMPLETED' | 'FAILED'): Promise<void> {
  try {
    await clearFileDownloads([status], siteId.value)
    await recoverTasks()
  } catch (reason) {
    queueError.value = messageOf(reason, '下载记录清理失败')
  }
}

async function deliverTask(task: FileDownloadTask, action: 'save' | 'open' | 'folder'): Promise<void> {
  if (!task.result) return
  queueError.value = ''
  try {
    let capabilityId = savedCapabilities.value.get(task.task_id)
    if (action === 'save') {
      const result = await downloadBackendResource(fileDownloadRequest(task.task_id, task.site_id, task.result.name))
      if (result.status === 'failed') {
        queueError.value = result.error || '下载结果交付失败'
        return
      }
      if (result.status === 'cancelled') return
      if (result.status === 'started') {
        ElMessage.success('已开始下载')
        return
      }
      capabilityId = result.capabilityId
      if (capabilityId) savedCapabilities.value.set(task.task_id, capabilityId)
      ElMessage.success(capabilityId ? '文件已保存' : '文件已保存；该文件类型不支持直接打开或定位')
      return
    }
    if (!capabilityId) {
      ElMessage.warning('请先保存文件；只有支持的文件类型才能直接打开或定位')
      return
    }
    const result = action === 'open'
      ? await getPlatformAdapter().openPath(capabilityId)
      : await getPlatformAdapter().showItemInFolder(capabilityId)
    if (!result.success) queueError.value = result.error || '桌面打开失败'
  } catch (reason) {
    queueError.value = messageOf(reason, '下载结果交付失败')
  }
}

function taskType(status: FileDownloadTask['status']): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'warning'
  return 'info'
}

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}
</script>

<template>
  <section class="device-file-downloads-page" v-loading="loading">
    <header class="page-heading">
      <div>
        <p class="eyebrow">LOCAL / DEVICE FILES</p>
        <h1>设备文件下载</h1>
        <p>通过受控 SFTP 浏览设备文件并下载到本地。设备侧保持只读，不支持上传、删除、重命名或远程创建目录。</p>
      </div>
      <el-button :loading="loading" @click="refreshAll">{{ t('refreshAll') }}</el-button>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="deviceFilesMessage && isFeatureEnabled('web.file_management_remote')" :title="deviceFilesMessage" type="info" :closable="false" show-icon />

    <div class="device-toolbar content-card">
      <el-input v-model="deviceSearch" clearable placeholder="搜索设备 / IP / 分组 / 类型" />
      <el-select v-model="deviceGroup" clearable placeholder="全部分组">
        <el-option v-for="group in deviceGroups" :key="group" :label="group" :value="group" />
      </el-select>
      <el-select v-model="selectedDeviceId" clearable filterable placeholder="选择设备（决定默认本地目录）" @change="deviceChanged">
        <el-option v-for="device in filteredDevices" :key="device.device_id" :label="`${device.name} · ${device.address}`" :value="device.device_id" />
      </el-select>
      <span>{{ selectedDevice ? `当前设备：${selectedDevice.name}` : '当前为局点下载根目录' }}</span>
      <template v-if="isFeatureEnabled('web.file_management_remote')">
        <el-checkbox v-model="allowSftpSetup" :disabled="sftpSetupConfirmationPending || !!connection" @change="confirmSftpSetup">SFTP 未启用时，允许自动配置并重连</el-checkbox>
        <el-button type="primary" :disabled="!selectedDeviceId || !!connection || sftpSetupConfirmationPending || (allowSftpSetup && !sftpSetupConfirmed)" :loading="remoteLoading" @click="connectDevice">{{ t('connect') }}</el-button>
        <el-button :disabled="!connection" @click="disconnectDevice">{{ t('disconnect') }}</el-button>
        <el-button v-if="isFeatureEnabled('web.file_management_desktop_actions') && desktopAvailable" :title="winscpMessage" :disabled="!selectedDeviceId || !winscpAvailable" @click="prepareWinscp">{{ t('winscp') }}</el-button>
      </template>
    </div>

    <div class="panes">
      <article class="content-card pane">
        <div class="section-heading"><h2>本地</h2><span>{{ localPage?.current_label || '下载目录' }}</span></div>
        <el-alert v-if="localError" :title="localError" type="error" :closable="false" show-icon />
        <div class="toolbar">
          <el-button :disabled="!localPage || localPage.current_entry_id === localPage.root_entry_id" @click="loadLocal(localPage?.parent_entry_id, 1)">{{ t('back') }}</el-button>
          <el-button :disabled="!localPage" @click="loadLocal(localPage?.root_entry_id, 1)">{{ t('root') }}</el-button>
          <el-button :loading="localLoading" :disabled="!localPage" @click="loadLocal(localPage?.current_entry_id, localPageNumber)">{{ t('refresh') }}</el-button>
          <el-button v-if="isFeatureEnabled('web.file_management_local_write')" :disabled="!localPage" @click="createDirectory">{{ t('newDirectory') }}</el-button>
          <el-button v-if="isFeatureEnabled('web.file_management_desktop_actions') && desktopAvailable" :disabled="!localPage" @click="prepareLocalOpen">{{ t('openCurrent') }}</el-button>
        </div>
        <NcDataTable
          v-loading="localLoading"
          :data="localPage?.items || []"
          :columns="localFileColumns"
          table-id="file-local-entries"
          route-key="/file-management"
          height="430"
          empty-text="当前目录为空"
          @row-dblclick="openLocal"
        />
        <el-pagination
          v-if="localPage && localPage.total > localPage.limit"
          v-model:current-page="localPageNumber"
          small layout="prev, pager, next, total" :page-size="localPage.limit" :total="localPage.total"
          @current-change="(page: number) => loadLocal(localPage?.current_entry_id, page)"
        />
        <p class="hint">双击目录进入；双击文件会通过受控下载桥保存后打开。</p>
      </article>

      <article v-if="isFeatureEnabled('web.file_management_remote')" class="content-card pane">
        <div class="section-heading"><h2>设备文件（只读）</h2><span>{{ connection ? `${connection.device_name} · ${remotePage?.current_label || '根目录'}` : '未连接' }}</span></div>
        <el-alert v-if="remoteError" :title="remoteError" type="error" :closable="false" show-icon><el-button v-if="sftpSetupTaskId" link type="primary" @click="openTaskWindow(sftpSetupTaskId)">查看自动配置任务</el-button></el-alert>
        <div class="toolbar">
          <el-button :disabled="!connection || !remotePage || remotePage.current_entry_id === connection.root_entry_id" @click="loadRemote(remotePage?.parent_entry_id, 1)">{{ t('up') }}</el-button>
          <el-button :disabled="!connection" @click="loadRemote(connection?.root_entry_id, 1)">{{ t('root') }}</el-button>
          <el-button :disabled="!connection" :loading="remoteLoading" @click="loadRemote(remotePage?.current_entry_id, remotePageNumber)">{{ t('refresh') }}</el-button>
          <el-button :disabled="!connection" @click="selectAllRemote(false)">{{ t('selectAll') }}</el-button>
          <el-button :disabled="!connection" @click="clearRemoteSelection">{{ t('clearSelection') }}</el-button>
          <el-button :disabled="!connection" @click="selectAllRemote(true)">{{ t('meshLogs') }}</el-button>
          <el-button :icon="Download" :loading="downloadLoading" :disabled="!connection || !localPage || !isVehicleMrDevice || !meshRemoteFiles.length || !isFeatureEnabled('web.file_management_download')" @click="downloadMeshLogsAndImport">{{ t('downloadAndImportMesh') }}</el-button>
          <el-button type="primary" :loading="downloadLoading" :disabled="!connection || !remoteSelected.length || !isFeatureEnabled('web.file_management_download')" @click="downloadRemote">{{ t('downloadSelected') }}（{{ remoteSelected.length }}）</el-button>
        </div>
        <NcDataTable
          ref="remoteTable" :data="remotePage?.items || []" border stripe height="430" row-key="entry_id"
          :columns="remoteFileColumns" table-id="file-remote-entries" route-key="/file-management"
          empty-text="暂无远程文件或尚未连接" v-loading="remoteLoading"
          @selection-change="selectRemote" @row-dblclick="openRemote"
        />
        <el-pagination
          v-if="remotePage && remotePage.total > remotePage.limit"
          v-model:current-page="remotePageNumber"
          small layout="prev, pager, next, total" :page-size="remotePage.limit" :total="remotePage.total"
          @current-change="(page: number) => loadRemote(remotePage?.current_entry_id, page)"
        />
        <p class="hint">远程目录和文件只使用会话 opaque 引用；不提供删除或远程建目录。</p>
      </article>
    </div>

    <article class="content-card">
      <div class="section-heading">
        <div><h2>{{ t('queue') }}</h2><span>状态由现有 TaskRepository 恢复；设备文件与 Artifact 分离。</span></div>
        <div class="toolbar compact">
          <el-button type="primary" plain @click="openTaskWindow">打开任务窗口</el-button>
          <el-button @click="refreshTasks">{{ t('refresh') }}</el-button>
          <el-button @click="clearTasks('COMPLETED')">{{ t('clearCompleted') }}</el-button>
          <el-button @click="clearTasks('FAILED')">{{ t('clearFailed') }}</el-button>
        </div>
      </div>
      <el-alert v-if="queueError" :title="queueError" type="error" :closable="false" show-icon />
      <div v-if="batchSummaries.length" class="batch-summaries">
        <el-tag v-for="batch in batchSummaries" :key="batch.batchId" effect="plain">
          {{ batch.batchId.slice(0, 10) }}：{{ batch.completed }}/{{ batch.total }} 完成，{{ batch.failed }} 失败，{{ batch.cancelled }} 取消，{{ batch.active }} 进行中
        </el-tag>
      </div>
      <NcDataTable :data="tasks" :columns="downloadTaskColumns" table-id="file-download-queue" route-key="/file-management" empty-text="暂无下载任务">
        <template #cell-file="{ row }"><strong>{{ row.remote_name || row.result?.name || row.task_id }}</strong><small>{{ row.device_name || (row.result?.result_kind === 'device_file' ? '设备文件' : '受控本地文件') }}{{ row.result?.target_kind === 'mr_raw' ? ' · MR 日志目录' : '' }}{{ row.result?.mesh_import_status ? ` · MESH 导入 ${meshImportStatusText(row.result.mesh_import_status)}` : '' }}</small></template>
        <template #cell-status="{ row }"><el-tag :type="taskType(row.status)">{{ row.status }}</el-tag></template>
        <template #cell-progress="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'FAILED' ? 'exception' : row.status === 'COMPLETED' ? 'success' : undefined" /><small>{{ formatBytes(row.downloaded_bytes) }} / {{ formatBytes(row.total_bytes) }} · {{ formatSpeed(row.speed_bytes_per_second) }}</small></template>
        <template #cell-actions="{ row }">
          <el-button v-if="activeTasks.some((item) => item.task_id === row.task_id)" link type="warning" @click="cancelTask(row)">{{ t('cancel') }}</el-button>
          <el-button v-if="row.retryable" link type="primary" @click="retryTask(row)">{{ t('retry') }}</el-button>
          <template v-if="row.status === 'COMPLETED' && row.result">
            <el-button link type="primary" @click="deliverTask(row, 'save')">{{ t('save') }}</el-button>
            <el-button link type="primary" :disabled="!savedCapabilities.has(row.task_id)" title="请先保存文件" @click="deliverTask(row, 'open')">{{ t('open') }}</el-button>
            <el-button link type="primary" :disabled="!savedCapabilities.has(row.task_id)" title="请先保存文件" @click="deliverTask(row, 'folder')">{{ t('containingFolder') }}</el-button>
          </template>
        </template>
      </NcDataTable>
    </article>
  </section>
</template>

<style scoped>
.file-management-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.section-heading,.device-toolbar,.toolbar{display:flex;align-items:center;gap:10px}.page-heading,.section-heading{justify-content:space-between}.page-heading h1,.section-heading h2{margin:2px 0 6px}.page-heading p,.section-heading span,.hint{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.content-card{padding:14px 16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px;overflow:hidden}.device-toolbar{flex-wrap:wrap}.device-toolbar .el-input{width:250px}.device-toolbar .el-select{width:210px}.panes{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.pane{min-width:0}.toolbar{flex-wrap:wrap;margin-bottom:10px}.toolbar.compact{margin:0}.hint{padding-top:10px;font-size:12px}.batch-summaries{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}.el-pagination{justify-content:flex-end;padding-top:10px}strong,small{display:block}small{margin-top:4px;color:var(--el-text-color-secondary)}@media(max-width:1200px){.panes{grid-template-columns:1fr}}@media(max-width:760px){.page-heading,.section-heading{align-items:flex-start;flex-direction:column}.device-toolbar .el-input,.device-toolbar .el-select{width:100%}}
</style>
