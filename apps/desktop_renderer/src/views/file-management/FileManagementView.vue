<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  cancelFileDownload,
  clearFileDownloads,
  confirmDeviceSftpSetup,
  connectDeviceFiles,
  createLocalDirectory,
  disconnectDeviceFiles,
  getFileManagementStatus,
  listFileDownloads,
  listLocalFiles,
  listRemoteDevices,
  listRemoteFiles,
  prepareFileDesktopAction,
  retryFileDownload,
  retryMeshFileImport,
  startRemoteFileDownloadBatch,
  trustDeviceHostKey,
} from '../../api/fileManagement'
import { ApiRequestError } from '../../api/client'
import { isFeatureEnabled } from '../../features'
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
const deviceLoading = ref(false)
const queueLoading = ref(false)
const desktopActionBusy = ref(false)
const localPageNumber = ref(1)
const devices = ref<FileRemoteDevice[]>([])
const selectedDeviceId = ref('')
const deviceSearch = ref('')
const deviceGroup = ref('')
const sftpSetupTaskId = ref('')
const connection = ref<FileConnection | null>(null)
const connectionStatus = ref('未连接')
const remotePage = ref<RemoteFilePage | null>(null)
const remoteLoading = ref(false)
const downloadLoading = ref(false)
const remotePageNumber = ref(1)
const remoteSelected = ref<RemoteFileEntry[]>([])
const remoteTable = ref<{ clearSelection(): void; toggleRowSelection(row: RemoteFileEntry, selected: boolean): void } | null>(null)
const tasks = ref<FileDownloadTask[]>([])
const localSelectedEntryId = ref('')
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const activeTasks = computed(() => activeDownloadTasks(tasks.value))
const selectedDevice = computed(() => devices.value.find((device) => device.device_id === selectedDeviceId.value) || null)
const deviceGroups = computed(() => [...new Set(devices.value.map((device) => device.group_name || '未分组'))].sort((a, b) => a.localeCompare(b)))
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
  { key: 'remote_path', label: '远程路径', valueType: 'description', alignmentReason: 'long-text' },
  { key: 'local_path', label: '真实本地路径', valueType: 'description', alignmentReason: 'long-text' },
  { key: 'batch', label: '批次', valueType: 'text', displayValue: (row) => row.batch_id ? row.batch_id.slice(0, 10) : '—' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'analysis', label: '分析状态', valueType: 'status', cellKind: 'tag' },
  { key: 'progress', label: '进度', valueType: 'percentage', measureValue: (row) => `${row.progress}% ${formatBytes(row.downloaded_bytes)} / ${formatBytes(row.total_bytes)}` },
  { key: 'message', label: '信息', valueType: 'description', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['取消', '重试', '打开', '所在目录', '导入到 MESH 分析', '查看分析'] },
]
const SFTP_SETUP_SUCCESS_MESSAGE = '已在设备侧启用 SFTP，并完成重新连接。'
const SFTP_CONNECTION_ERROR_MESSAGES: Record<string, string> = {
  DEVICE_FILE_DIRECT_UNREACHABLE: '设备地址直连不可达或 SSH 端口不可用。',
  DEVICE_FILE_JUMP_HOST_UNREACHABLE: '跳板机网络不可达或 SSH 端口不可用。',
  DEVICE_FILE_JUMP_HOST_AUTH_FAILED: '跳板机 SSH 认证失败，请检查隧道凭据。',
  DEVICE_FILE_JUMP_HOST_KEY_MISMATCH: '跳板机主机密钥与已保存记录不一致，连接已阻止。',
  DEVICE_FILE_FORWARD_OPEN_FAILED: '跳板机已认证，但无法建立到目标设备的转发通道。',
  DEVICE_FILE_TARGET_UNREACHABLE_VIA_TUNNEL: '跳板机已连接，但经隧道无法访问目标设备。',
  DEVICE_FILE_TARGET_AUTH_FAILED: '目标设备 SSH 认证失败，请检查用户名和密码。',
  DEVICE_FILE_TARGET_HOST_KEY_MISMATCH: '目标设备主机密钥与已保存记录不一致，连接已阻止。',
  DEVICE_FILE_SFTP_UNAVAILABLE: '设备 SSH 已登录，但 SFTP 子系统不可用。',
  DEVICE_FILE_SFTP_NEGOTIATION_FAILED: 'SSH 登录成功，但建立 SFTP 子系统失败。',
  DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED: '当前设备厂商或版本不支持自动启用 SFTP，未执行设备配置。',
  DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED: '无法确认设备的软件版本，未执行 SFTP 配置命令。',
  DEVICE_FILE_SFTP_ENABLE_PENDING: '启用设备 SFTP 的受控任务仍在运行，请稍候后从任务中心查看结果。',
  DEVICE_FILE_SFTP_ENABLE_FAILED: '设备 SFTP 自动启用失败。请查看任务日志，并检查设备权限和 Command Profile。',
  DEVICE_FILE_SFTP_RECONNECT_FAILED: '设备侧 SFTP 已启用，但重新连接失败。请查看任务，并检查 SFTP 服务和网络连通性。',
  DEVICE_FILE_REMOTE_ROOT_NOT_FOUND: '已建立 SFTP 会话，但未找到可读取的远程根目录。',
  DEVICE_FILE_SESSION_DISCONNECTED: '设备文件会话已断开，请重新连接。',
}
const MESH_IMPORT_STATUS_LABELS: Record<string, string> = {
  completed: '已导入',
  duplicate: '重复，已存在',
  failed: '日志解析失败，可重试',
  rebuild_required: '已下载，正在自动修复',
  waiting_repair: '等待分析数据库升级',
  repairing: '正在自动修复',
  repair_failed: '自动修复失败，可重试',
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
  } catch (reason) {
    error.value = messageOf(reason, '文件管理初始化失败')
  } finally {
    loading.value = false
  }
  void loadLocal('', 1)
  void loadDevices()
  void recoverTasks()
}

async function loadDevices(): Promise<void> {
  if (!isFeatureEnabled('capability.file_management.remote')) return
  deviceLoading.value = true
  try {
    devices.value = await listRemoteDevices(siteId.value)
  } catch (reason) {
    devices.value = []
    remoteError.value = messageOf(reason, '设备列表读取失败')
  } finally {
    deviceLoading.value = false
  }
}

async function refreshAll(): Promise<void> {
  await initialize()
  if (connection.value) await loadRemote(remotePage.value?.current_entry_id || connection.value.root_entry_id, remotePageNumber.value)
}

async function loadLocal(directoryId = '', page = 1, selectName = ''): Promise<void> {
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
    localSelectedEntryId.value = selectName
      ? (localPage.value.items.find((item) => item.name === selectName)?.entry_id || '')
      : ''
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
  await showDesktopDependency('open_local', { local_entry_id: row.entry_id })
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

function applySftpConnectionError(reason: ApiRequestError, fallback: string): void {
  const taskId = reason.details.task_id
  sftpSetupTaskId.value = typeof taskId === 'string' ? taskId : ''
  const base = SFTP_CONNECTION_ERROR_MESSAGES[reason.code] || messageOf(reason, fallback)
  const attempts = Array.isArray(reason.details.attempts) ? reason.details.attempts : []
  const summaries = attempts
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => {
      const role = item.target_role === 'backup' ? '备用地址' : '主用地址'
      const tunnel = item.tunnel_label === 'tunnel1' ? '第一跳' : item.tunnel_label === 'tunnel2' ? '第二跳' : ''
      const path = tunnel ? `${tunnel} → ${role}` : `${role}直连`
      return `${path}：${String(item.message || (item.success ? '成功' : '失败'))}`
    })
  remoteError.value = summaries.length ? `${base} ${summaries.join('；')}` : base
  connectionStatus.value = reason.code === 'DEVICE_FILE_SESSION_DISCONNECTED' ? '未连接' : '连接失败'
}

async function connectDevice(): Promise<void> {
  if (!selectedDeviceId.value) return
  if (selectedDevice.value?.file_download_supported === false) {
    remoteError.value = selectedDevice.value?.file_download_unavailable_reason || '设备文件下载当前仅支持 H3C 设备'
    return
  }
  remoteLoading.value = true
  remoteError.value = ''
  sftpSetupTaskId.value = ''
  try {
    await disconnectDevice()
    connectionStatus.value = '正在连接 SFTP（单条路径最多等待 5 秒，失败后自动尝试下一路径）'
    await completeConnection(() => connectDeviceFiles(selectedDeviceId.value, siteId.value))
  } finally {
    remoteLoading.value = false
  }
}

async function completeConnection(request: () => Promise<FileConnection>): Promise<boolean> {
  try {
    connection.value = await request()
    connectionStatus.value = connection.value.via_tunnel ? '通过 SSH 隧道连接' : 'SFTP 直连成功'
    await loadRemote(connection.value.root_entry_id, 1)
    if (connection.value.message === SFTP_SETUP_SUCCESS_MESSAGE) ElMessage.success(connection.value.message)
    return true
  } catch (reason) {
    if (
      reason instanceof ApiRequestError
      && ['DEVICE_FILE_HOST_KEY_UNKNOWN', 'DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN', 'DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN'].includes(reason.code)
    ) {
      const details = reason.details
      const challengeId = String(details.challenge_id || '')
      const jumpHost = details.host_key_role === 'jump'
      const identityLabel = jumpHost ? '跳板机' : '目标设备'
      const choice = await confirmChoice({
        type: 'SECURITY',
        title: `首次连接：确认${identityLabel}主机密钥`,
        message: `设备：${String(details.device_name || selectedDevice.value?.name || '当前设备')}\n${identityLabel}地址：${String(details.host || selectedDevice.value?.address || '')}:${String(details.port || 22)}\n密钥算法：${String(details.algorithm || '未知')}\nSHA256 指纹：${String(details.fingerprint_sha256 || '未知')}`,
        detail: `首次连接时请确认该指纹确实属于${identityLabel}。信任错误的主机密钥可能导致连接到错误设备。`,
        confirmText: '仅本次信任',
        secondaryText: '信任并保存',
        acknowledgementText: '我已核对该设备指纹',
        requireAcknowledgement: true,
      })
      if (choice !== 'cancel' && challengeId) {
        connectionStatus.value = 'SSH 登录成功'
        return completeConnection(() => trustDeviceHostKey(challengeId, choice === 'secondary', siteId.value))
      }
      remoteError.value = '已取消主机密钥信任，连接未建立。'
    } else if (reason instanceof ApiRequestError && reason.code === 'DEVICE_FILE_SFTP_UNAVAILABLE') {
      connectionStatus.value = '检测到设备未启用 SFTP'
      const confirmationId = String(reason.details.confirmation_id || '')
      const accepted = confirmationId && await confirm({
        type: 'DANGER',
        title: '确认启用设备 SFTP',
        message: '设备未启用 SFTP，NetConsole 将通过受控命令启用 SFTP并重新连接。',
        detail: '远程文件操作仍保持只读；不会上传、删除、重命名或创建远程目录。',
        confirmText: '启用并继续连接',
      })
      if (accepted) {
        connectionStatus.value = '正在启用设备 SFTP'
        try {
          const resumed = await confirmDeviceSftpSetup(confirmationId, siteId.value)
          connectionStatus.value = '正在重新连接 SFTP'
          return completeConnection(() => Promise.resolve(resumed))
        } catch (setupError) {
          return completeConnection(() => Promise.reject(setupError))
        }
      }
      remoteError.value = '已取消启用设备 SFTP，连接未建立。'
    } else if (reason instanceof ApiRequestError && reason.code in SFTP_CONNECTION_ERROR_MESSAGES) {
      applySftpConnectionError(reason, '设备文件连接失败')
    } else {
      remoteError.value = messageOf(reason, '设备文件连接失败')
    }
    connection.value = null
    remotePage.value = null
    connectionStatus.value = '未连接'
    return false
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
  connectionStatus.value = '未连接'
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
    if (reason instanceof ApiRequestError && reason.code === 'DEVICE_FILE_SESSION_DISCONNECTED') {
      connection.value = null
      remotePage.value = null
      remoteSelected.value = []
      remoteTable.value?.clearSelection()
      connectionStatus.value = '未连接'
      remoteError.value = '设备文件会话已断开，请重新连接。'
    } else remoteError.value = messageOf(reason, '远程目录读取失败')
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
    if (reason instanceof ApiRequestError && reason.code === 'DEVICE_FILE_SESSION_DISCONNECTED') {
      connection.value = null
      remotePage.value = null
      remoteSelected.value = []
      connectionStatus.value = '未连接'
      remoteError.value = '设备文件会话已断开，请重新连接。'
    } else remoteError.value = messageOf(reason, '批量下载创建失败')
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
  action: 'winscp' | 'open_local' | 'open_result' | 'open_result_dir',
  values: { device_id?: string; local_entry_id?: string; task_id?: string },
): Promise<void> {
  if (desktopActionBusy.value) return
  desktopActionBusy.value = true
  try {
    if (!window.netconsoleDesktop) throw new Error('该操作只能在 Electron Desktop 中执行')
    const result = await prepareFileDesktopAction(action, { site_id: siteId.value, ...values })
    const executed = await window.netconsoleDesktop.executeFileDesktopAction(result.action_ref)
    if (!executed.success) throw new Error(executed.error || '桌面操作失败')
    ElMessage.success(action === 'winscp' ? '已启动 WinSCP' : action === 'open_result' ? '已打开文件' : '已打开目录')
  } catch (reason) {
    error.value = messageOf(reason, '桌面操作失败')
  } finally {
    desktopActionBusy.value = false
  }
}

async function recoverTasks(): Promise<void> {
  queueLoading.value = true
  queueError.value = ''
  try {
    tasks.value = mergeDownloadTasks([], await listFileDownloads(siteId.value, 20))
  } catch (reason) {
    queueError.value = messageOf(reason, '下载队列恢复失败')
  } finally {
    queueLoading.value = false
  }
  scheduleTaskRefresh()
}

async function refreshTasks(): Promise<void> {
  try {
    const before = new Map(tasks.value.map((task) => [task.task_id, task.status]))
    const incoming = await listFileDownloads(siteId.value, 20)
    tasks.value = mergeDownloadTasks(tasks.value, incoming)
    const completed = incoming.filter((task) => task.status === 'COMPLETED' && before.get(task.task_id) !== 'COMPLETED')
    if (completed.length && localPage.value) {
      const latest = [...completed].reverse().find((task) => task.result?.name) || completed[completed.length - 1]
      const refreshFromRoot = latest.result?.target_kind === 'mr_raw'
      await loadLocal(refreshFromRoot ? '' : localPage.value.current_entry_id, refreshFromRoot ? 1 : localPageNumber.value, latest.result?.name || '')
    }
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

async function openTaskResult(task: FileDownloadTask, containingFolder = false): Promise<void> {
  if (!task.result) return
  await showDesktopDependency(containingFolder ? 'open_result_dir' : 'open_result', { task_id: task.task_id })
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

async function importDownloadedMesh(task: FileDownloadTask): Promise<void> {
  try {
    tasks.value = mergeDownloadTasks(tasks.value, [await retryMeshFileImport(task.task_id, siteId.value)])
    scheduleTaskRefresh()
  } catch (reason) {
    queueError.value = messageOf(reason, 'MESH 日志导入任务启动失败')
  }
}

function viewMeshAnalysis(task: FileDownloadTask): void {
  const sessionId = task.result?.mesh_session_id
  if (!sessionId) return
  void router.push({ name: 'mesh-analysis', query: { session_id: sessionId } })
}

function connectionRouteText(value: FileConnection): string {
  const role = value.target_role === 'backup' ? '备用地址' : '主用地址'
  const target = `${role} ${value.target_host}:${value.target_port}`
  if (!value.via_tunnel) return `实际链路：${target} 直连`
  const tunnel = value.tunnel_label === 'tunnel1' ? '第一跳' : value.tunnel_label === 'tunnel2' ? '第二跳' : 'SSH 隧道'
  return `实际链路：${tunnel} ${value.jump_host}:${value.jump_port} → ${target}`
}
</script>

<template>
  <section class="device-file-downloads-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">LOCAL / DEVICE FILES</p>
        <h1>设备文件下载</h1>
        <p>通过受控 SFTP 浏览设备文件并下载到本地。设备侧保持只读，不支持上传、删除、重命名或远程创建目录。</p>
      </div>
      <el-button :loading="loading" @click="refreshAll">{{ t('refreshAll') }}</el-button>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="deviceFilesMessage && isFeatureEnabled('capability.file_management.remote')" :title="deviceFilesMessage" type="info" :closable="false" show-icon />

    <div class="device-toolbar content-card">
      <el-input v-model="deviceSearch" clearable placeholder="搜索设备 / IP / 分组 / 类型" />
      <el-select v-model="deviceGroup" clearable placeholder="全部分组">
        <el-option v-for="group in deviceGroups" :key="group" :label="group" :value="group" />
      </el-select>
      <el-select v-model="selectedDeviceId" clearable filterable :loading="deviceLoading" placeholder="选择设备（决定默认本地目录）" @change="deviceChanged">
        <el-option v-for="device in filteredDevices" :key="device.device_id" :disabled="device.file_download_supported === false" :label="`${device.name} · ${device.address}${device.file_download_supported === false ? '（仅支持 H3C）' : ''}`" :value="device.device_id" />
      </el-select>
      <span>{{ selectedDevice ? `当前设备：${selectedDevice.name}` : '当前为局点下载根目录' }}</span>
      <template v-if="isFeatureEnabled('capability.file_management.remote')">
        <span>连接状态：{{ connectionStatus }}</span>
        <el-button type="primary" :disabled="!selectedDeviceId || !!connection" :loading="remoteLoading" @click="connectDevice">{{ t('connect') }}</el-button>
        <el-button :disabled="!connection" @click="disconnectDevice">{{ t('disconnect') }}</el-button>
        <el-button v-if="isFeatureEnabled('capability.file_management.desktop_actions') && desktopAvailable" :title="winscpMessage" :disabled="!selectedDeviceId || !winscpAvailable" @click="prepareWinscp">{{ t('winscp') }}</el-button>
      </template>
      <span v-if="connection" class="connection-route">{{ connectionRouteText(connection) }}</span>
    </div>

    <div class="panes">
      <article class="content-card pane">
        <div class="section-heading"><h2>本地</h2><span>{{ localPage?.current_label || '下载目录' }}</span></div>
        <el-alert v-if="localError" :title="localError" type="error" :closable="false" show-icon />
        <div class="toolbar">
          <el-button :disabled="!localPage || localPage.current_entry_id === localPage.root_entry_id" @click="loadLocal(localPage?.parent_entry_id, 1)">{{ t('back') }}</el-button>
          <el-button :disabled="!localPage" @click="loadLocal(localPage?.root_entry_id, 1)">{{ t('root') }}</el-button>
          <el-button :loading="localLoading" :disabled="!localPage" @click="loadLocal(localPage?.current_entry_id, localPageNumber)">{{ t('refresh') }}</el-button>
          <el-button v-if="isFeatureEnabled('capability.file_management.local_write')" :disabled="!localPage" @click="createDirectory">{{ t('newDirectory') }}</el-button>
          <el-button v-if="isFeatureEnabled('capability.file_management.desktop_actions') && desktopAvailable" :loading="desktopActionBusy" :disabled="!localPage || desktopActionBusy" @click="prepareLocalOpen">{{ t('openCurrent') }}</el-button>
        </div>
        <NcDataTable
          v-loading="localLoading"
          :data="localPage?.items || []"
          :columns="localFileColumns"
          table-id="file-local-entries"
          route-key="/file-management"
          height="430"
          row-key="entry_id"
          highlight-current-row
          :current-row-key="localSelectedEntryId"
          empty-text="当前目录为空"
          @row-dblclick="openLocal"
        />
        <el-pagination
          v-if="localPage && localPage.total > localPage.limit"
          v-model:current-page="localPageNumber"
          small layout="prev, pager, next, total" :page-size="localPage.limit" :total="localPage.total"
          @current-change="(page: number) => loadLocal(localPage?.current_entry_id, page)"
        />
        <p class="hint">双击目录进入；双击文件会通过受控 Desktop Bridge 直接打开真实下载文件。</p>
      </article>

      <article v-if="isFeatureEnabled('capability.file_management.remote')" class="content-card pane">
        <div class="section-heading"><h2>设备文件（只读）</h2><span>{{ connection ? `${connection.device_name} · ${remotePage?.current_label || '根目录'}` : '未连接' }}</span></div>
        <el-alert v-if="remoteError" :title="remoteError" type="error" :closable="false" show-icon><el-button v-if="sftpSetupTaskId" link type="primary" @click="openTaskWindow(sftpSetupTaskId)">查看自动配置任务</el-button></el-alert>
        <div class="toolbar">
          <el-button :disabled="!connection || !remotePage || remotePage.current_entry_id === connection.root_entry_id" @click="loadRemote(remotePage?.parent_entry_id, 1)">{{ t('up') }}</el-button>
          <el-button :disabled="!connection" @click="loadRemote(connection?.root_entry_id, 1)">{{ t('root') }}</el-button>
          <el-button :disabled="!connection" :loading="remoteLoading" @click="loadRemote(remotePage?.current_entry_id, remotePageNumber)">{{ t('refresh') }}</el-button>
          <el-button :disabled="!connection" @click="selectAllRemote(false)">{{ t('selectAll') }}</el-button>
          <el-button :disabled="!connection" @click="clearRemoteSelection">{{ t('clearSelection') }}</el-button>
          <el-button :disabled="!connection" @click="selectAllRemote(true)">{{ t('meshLogs') }}</el-button>
          <el-button type="primary" :loading="downloadLoading" :disabled="!connection || !remoteSelected.length || !isFeatureEnabled('capability.file_management.download')" @click="downloadRemote">{{ t('downloadSelected') }}（{{ remoteSelected.length }}）</el-button>
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
          <el-button type="primary" plain @click="openTaskWindow">打开任务中心</el-button>
          <el-button @click="refreshTasks">{{ t('refresh') }}</el-button>
          <el-button @click="clearTasks('COMPLETED')">{{ t('clearCompleted') }}</el-button>
          <el-button @click="clearTasks('FAILED')">{{ t('clearFailed') }}</el-button>
        </div>
      </div>
      <el-alert v-if="queueError" :title="queueError" type="error" :closable="false" show-icon />
      <div v-if="batchSummaries.length" class="batch-summaries">
        <el-tag v-for="batch in batchSummaries" :key="batch.batchId" effect="plain">
          {{ batch.batchId.slice(0, 10) }}：成功 {{ batch.completed }}、失败 {{ batch.failed }}、取消 {{ batch.cancelled }}<template v-if="batch.active">、进行中 {{ batch.active }}</template>
        </el-tag>
      </div>
      <NcDataTable v-loading="queueLoading" :data="tasks" :columns="downloadTaskColumns" table-id="file-download-queue" route-key="/file-management" empty-text="暂无下载任务">
        <template #cell-file="{ row }"><strong>{{ row.remote_name || row.result?.name || row.task_id }}</strong><small>{{ row.device_name || (row.result?.result_kind === 'device_file' ? '设备文件' : '受控本地文件') }}{{ row.result?.target_kind === 'mr_raw' ? ' · MR 日志目录' : '' }}</small></template>
        <template #cell-status="{ row }"><el-tag :type="taskType(row.status)">{{ row.status }}</el-tag></template>
        <template #cell-analysis="{ row }">
          <el-tag v-if="row.result?.target_kind === 'mr_raw'" :type="['failed', 'repair_failed'].includes(row.result.mesh_import_status) ? 'danger' : row.result.mesh_import_status === 'completed' ? 'success' : 'info'">
            {{ row.result.mesh_import_status ? meshImportStatusText(row.result.mesh_import_status) : '等待导入' }}
          </el-tag>
          <span v-else>—</span>
        </template>
        <template #cell-progress="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'FAILED' ? 'exception' : row.status === 'COMPLETED' ? 'success' : undefined" /><small>{{ formatBytes(row.downloaded_bytes) }} / {{ formatBytes(row.total_bytes) }} · {{ formatSpeed(row.speed_bytes_per_second) }}</small></template>
        <template #cell-actions="{ row }">
          <el-button v-if="activeTasks.some((item) => item.task_id === row.task_id)" link type="warning" @click="cancelTask(row)">{{ t('cancel') }}</el-button>
          <el-button v-if="row.retryable" link type="primary" @click="retryTask(row)">{{ ['failed', 'repair_failed'].includes(row.result?.mesh_import_status || '') ? '重新导入' : t('retry') }}</el-button>
          <el-button v-else-if="row.status === 'COMPLETED' && row.result?.target_kind === 'mr_raw' && !row.result.mesh_import_status" link type="primary" @click="importDownloadedMesh(row)">导入到 MESH 分析</el-button>
          <el-button v-if="row.result?.mesh_session_id" link type="primary" @click="viewMeshAnalysis(row)">查看分析</el-button>
          <template v-if="row.status === 'COMPLETED' && row.result">
            <el-button link type="primary" :loading="desktopActionBusy" :disabled="desktopActionBusy" @click="openTaskResult(row)">{{ t('open') }}</el-button>
            <el-button link type="primary" :loading="desktopActionBusy" :disabled="desktopActionBusy" @click="openTaskResult(row, true)">{{ t('containingFolder') }}</el-button>
          </template>
        </template>
      </NcDataTable>
    </article>
  </section>
</template>

<style scoped>
.file-management-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.section-heading,.device-toolbar,.toolbar{display:flex;align-items:center;gap:10px}.page-heading,.section-heading{justify-content:space-between}.page-heading h1,.section-heading h2{margin:2px 0 6px}.page-heading p,.section-heading span,.hint{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.content-card{padding:14px 16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px;overflow:hidden}.device-toolbar{flex-wrap:wrap}.device-toolbar .el-input{width:250px}.device-toolbar .el-select{width:210px}.connection-route{flex:1 0 100%;font-size:13px}.panes{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.pane{min-width:0}.toolbar{flex-wrap:wrap;margin-bottom:10px}.toolbar.compact{margin:0}.hint{padding-top:10px;font-size:12px}.batch-summaries{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}.el-pagination{justify-content:flex-end;padding-top:10px}strong,small{display:block}small{margin-top:4px;color:var(--el-text-color-secondary)}@media(max-width:1200px){.panes{grid-template-columns:1fr}}@media(max-width:760px){.page-heading,.section-heading{align-items:flex-start;flex-direction:column}.device-toolbar .el-input,.device-toolbar .el-select{width:100%}}
</style>
