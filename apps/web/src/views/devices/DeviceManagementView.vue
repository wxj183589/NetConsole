<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { Connection, CopyDocument, Delete, Download, Edit, FolderOpened, Hide, Plus, Refresh, Upload, View } from '@element-plus/icons-vue'

import { isFeatureEnabled } from '../../features'
import {
  getDeviceEditProfile,
  getDeviceExportTask,
  getDeviceConnectionTest,
  getBatchRefresh,
  getExternalTerminalSettings,
  issueExternalTerminalConfirmation,
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
  launchExternalTerminals,
  renameDeviceGroup,
  revealDeviceCredential,
  startBatchRefreshDetails,
  startBatchConnectionTests,
  startDeviceCsvExport,
  startDeviceFormConnectionTest,
  startDeviceDiagnosticDownload,
  startDeviceTemplateExport,
  startSecureCrtExport,
  startSecureCrtExportWithTemplate,
  updateDevice,
  updateExternalTerminalSettings,
} from '../../api/deviceManagement'
import { downloadBackendResource, getPlatformAdapter, getRuntimeConfig } from '../../platform/runtime'
import { useTaskStore } from '../../stores/tasks'
import DeviceDetailPanel from '../../components/device-detail/DeviceDetailPanel.vue'
import { useConfirm } from '../../components/feedback/useConfirm'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import {
  DEVICE_VENDOR_OPTIONS,
  formatDeviceVendor,
} from '../../types/deviceManagement'
import type {
  DeviceConnectionProtocol,
  DeviceConnectionStatus,
  DeviceConnectionTest,
  DeviceBatchRefreshItem,
  DeviceExportRequest,
  DeviceEditProfileResponse,
  DeviceExternalTerminalSettings,
  DeviceImportPreview,
  DeviceListItem,
  DevicePage,
  DeviceSecretField,
  DeviceTaskReference,
  DeviceTaskBatch,
  DeviceVendor,
  DeviceWriteRequest,
} from '../../types/deviceManagement'
import type { TaskItem, TaskStatus } from '../../types/task'

interface PublicTaskArtifact {
  artifact_id: string
  api_path: string
  query: Record<string, string>
  display_name: string
  size_bytes: number
  sha256?: string
  media_type: string
}

type DevicePublicTask = TaskItem & {
  module?: string
  artifact_download?: PublicTaskArtifact | null
}

type DeviceExportAction = 'export_csv' | 'export_template'
type DeviceExportScope = 'selected' | 'filtered_all' | 'template'
type PendingDeviceExportState =
  | 'task_running'
  | 'artifact_ready'
  | 'saving'
  | 'saved'
  | 'save_failed'

interface PendingDeviceExport {
  taskId: string
  action: DeviceExportAction
  destinationPath: string
  suggestedName: string
  fileName: string
  directoryLabel: string
  requestedRowCount: number
  scope: DeviceExportScope
  state: PendingDeviceExportState
  artifact?: PublicTaskArtifact
  actualRowCount?: number
  error?: string
}

type DeviceTaskWindowBridge = {
  openTaskWindow(context: { taskId?: string; module: 'devices'; status?: TaskStatus }): Promise<{ success: boolean; error?: string }>
}

interface TableSelectionController<Row> {
  clearSelection(): void
  toggleRowSelection(row: Row, selected?: boolean): void
}

const emptyPage = (): DevicePage => ({ items: [], groups: [], site_name: '', total: 0, page: 1, page_size: 50, total_pages: 1 })
const PENDING_DEVICE_EXPORTS_KEY = 'netconsole.devices.pending-exports.v1'
const DEVICE_TYPE_OPTIONS = ['AC', 'SW', 'FW', 'Route', 'Cloud-AP', 'FAT-AP', 'MR', 'Other'] as const
const router = useRouter()
const { confirm } = useConfirm()
const taskStore = useTaskStore()
const loading = ref(false)
const error = ref('')
const pageData = ref<DevicePage>(emptyPage())
const detailVisible = ref(false)
const detailDeviceUuid = ref('')
const detailDrawerWidthPx = ref(0)
const detailDrawerDragging = ref(false)
const detail = ref<DeviceEditProfileResponse | null>(null)
const editingDeviceUuid = ref('')
const editingProfileLoading = ref(false)
const connectionTest = ref<DeviceConnectionTest | null>(null)
const writeVisible = ref(false)
const writeMode = ref<'create' | 'edit'>('create')
const writeLoading = ref(false)
const writeConnectionLoading = ref(false)
const writeConnectionTest = ref<DeviceConnectionTest | null>(null)
const writeTestProtocol = ref<DeviceConnectionProtocol>('SSH')
const selectedUuids = ref<string[]>([])
const batchRefreshSubmitting = ref(false)
const batchRefreshTargetCount = ref(0)
const batchRefresh = ref<DeviceTaskBatch | null>(null)
const batchRefreshDetailsVisible = ref(false)
const deviceTable = ref<TableSelectionController<DeviceListItem>>()
const groupVisible = ref(false)
const groupName = ref('')
const groupAssignVisible = ref(false)
const groupAssignId = ref<number | null>(null)
const importVisible = ref(false)
const importFile = ref<File | null>(null)
const importFileInput = ref<HTMLInputElement | null>(null)
const importLoading = ref(false)
const importPreview = ref<DeviceImportPreview | null>(null)
const importDuplicateStrategy = ref<'reject' | 'skip' | 'create_new'>('reject')
const secureCrtVisible = ref(false)
const secureCrtTemplateFile = ref<File | null>(null)
const secureCrtTemplateInput = ref<HTMLInputElement | null>(null)
const lastSubmittedTask = ref<DeviceTaskReference | null>(null)
const savedArtifactCapability = ref('')
const savedDeviceArtifactNotice = ref<{ title: string; description: string } | null>(null)
const pendingDeviceExports = reactive<Record<string, PendingDeviceExport>>({})
const pendingDeviceExportRetryTick = ref(0)
let pendingDeviceExportRetryTimer: ReturnType<typeof setTimeout> | null = null
let batchRefreshPollTimer: ReturnType<typeof setTimeout> | null = null
let batchRefreshGeneration = 0
let activeBatchRefreshId = ''
const csvExportSubmitting = ref(false)
const templateExportSubmitting = ref(false)
const csvExportScopeVisible = ref(false)
const csvExportScope = ref<Exclude<DeviceExportScope, 'template'>>('filtered_all')
const csvExportIncludeCredentials = ref(false)
const terminalSettingsVisible = ref(false)
const terminalSettingsLoading = ref(false)
const terminalLaunchVisible = ref(false)
const terminalTargetUuids = ref<string[]>([])
const terminalSettings = reactive<DeviceExternalTerminalSettings>({
  terminal_type: 'securecrt',
  securecrt_path: '',
  xshell_path: '',
  putty_path: '',
  pass_password: false,
})
const filters = reactive({
  search: '',
  group: '',
  vendor: '' as DeviceVendor | '',
  device_type: '',
  connection_status: '' as DeviceConnectionStatus | '',
  sort_by: 'name',
  sort_order: 'asc' as 'asc' | 'desc',
  page: 1,
  page_size: 50,
})
const deviceColumns: NcTableColumn<DeviceListItem>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', fixed: 'left', hideable: false, stretch: 'none' },
  { key: 'name', label: '名称', valueType: 'name', fixed: 'left', stretch: 'priority', stretchWeight: 4 },
  { key: 'group_name', label: '分组', valueType: 'text', stretch: 'normal' },
  { key: 'device_vendor', label: '厂商', valueType: 'text', stretch: 'normal', displayValue: (row) => formatDeviceVendor(row.device_vendor) },
  { key: 'system_name', label: '系统名', valueType: 'name', stretch: 'normal' },
  { key: 'station', label: '站点', valueType: 'text', stretch: 'priority' },
  { key: 'primary_address', label: '主地址', valueType: 'ip', stretch: 'normal' },
  { key: 'backup_address', label: '备用地址', valueType: 'ip', stretch: 'normal' },
  {
    key: 'login_protocol',
    label: '登录协议',
    valueType: 'text',
    stretch: 'none',
    displayValue: (row) => [row.capabilities.ssh && 'SSH', row.capabilities.telnet && 'Telnet'].filter(Boolean).join('/') || '—',
  },
  { key: 'metadata_updated_at', label: '资料更新时间', valueType: 'datetime', stretch: 'none' },
  { key: 'last_collected_at', label: '最后采集时间', valueType: 'datetime', stretch: 'none' },
  { key: 'last_collect_status', label: '采集状态', valueType: 'status', cellKind: 'tag', stretch: 'none' },
  { key: 'credential_status', label: '凭据状态', valueType: 'status', cellKind: 'tag', stretch: 'none' },
  { key: 'connection_status', label: '连接状态', valueType: 'status', cellKind: 'tag', stretch: 'none' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['详情', '编辑', '删除'], stretch: 'none' },
]
const importErrorColumns: NcTableColumn<DeviceImportPreview['errors'][number]>[] = [
  { key: 'line', label: 'CSV 行', valueType: 'number', stretch: 'none' },
  { key: 'device_name', label: '设备名称', valueType: 'name', stretch: 'normal' },
  { key: 'field', label: '字段', valueType: 'text', stretch: 'none' },
  { key: 'raw_value', label: '原始值', valueType: 'text', stretch: 'normal' },
  { key: 'message', label: '错误信息', valueType: 'text', stretch: 'priority' },
]
const batchRefreshColumns: NcTableColumn<DeviceBatchRefreshItem>[] = [
  { key: 'device_name', label: '设备', valueType: 'name', stretch: 'priority' },
  { key: 'primary_address', label: '地址', valueType: 'ip', stretch: 'normal' },
  { key: 'vendor', label: '厂商', valueType: 'text', stretch: 'none' },
  { key: 'status', label: '结果', valueType: 'status', cellKind: 'tag', stretch: 'none' },
  { key: 'interfaces_updated', label: '接口', valueType: 'number', stretch: 'none' },
  { key: 'optical_modules_updated', label: '光模块', valueType: 'number', stretch: 'none' },
  { key: 'last_collected_at', label: '采集时间', valueType: 'datetime', stretch: 'none' },
  { key: 'error_message', label: '错误信息', valueType: 'text', stretch: 'priority' },
]
const writeForm = reactive<DeviceWriteRequest>({ name: '', primary_address: '', ssh_enabled: true, ssh_port: 22, telnet_enabled: false, telnet_port: 23, snmp_enabled: true, snmp_v2c_enabled: true, snmp_port: 161 })
const secretClears = reactive<Record<DeviceSecretField, boolean>>({
  ssh_password: false,
  telnet_password: false,
  tunnel1_password: false,
  tunnel2_password: false,
  snmp_ro_community: false,
})
const secretVisible = reactive<Record<DeviceSecretField, boolean>>({
  ssh_password: false,
  telnet_password: false,
  tunnel1_password: false,
  tunnel2_password: false,
  snmp_ro_community: false,
})
const secretRevealLoading = reactive<Record<DeviceSecretField, boolean>>({
  ssh_password: false,
  telnet_password: false,
  tunnel1_password: false,
  tunnel2_password: false,
  snmp_ro_community: false,
})
const contextMenu = reactive<{ visible: boolean; x: number; y: number; row: DeviceListItem | null; cellValue: string }>({ visible: false, x: 0, y: 0, row: null, cellValue: '' })
let editLoadGeneration = 0
let editProfileAbortController: AbortController | null = null
let componentActive = true
const pollingConsumer = 'device-management-view'
let drawerDragStartX = 0
let drawerDragStartWidth = 0

const detailDrawerWidth = computed(() => `${clampDrawerWidth(detailDrawerWidthPx.value || defaultDrawerWidth())}px`)

const isEmpty = computed(() => !loading.value && !error.value && pageData.value.items.length === 0)
const activeTaskStatuses = new Set<TaskStatus>(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'CREATED', 'QUEUED'])
const publicDeviceTasks = computed(() => (taskStore.tasks as DevicePublicTask[]).filter((task) => (
  task.module === 'devices'
  || task.owner === 'web_device_management'
  || task.type.startsWith('device_')
)))
const csvExportActive = computed(() => csvExportSubmitting.value || isPendingExportActive('export_csv'))
const templateExportActive = computed(() => templateExportSubmitting.value || isPendingExportActive('export_template'))
const latestDeviceTask = computed(() => {
  const submittedId = lastSubmittedTask.value?.task_id
  return (submittedId && publicDeviceTasks.value.find((task) => task.id === submittedId))
    || publicDeviceTasks.value[0]
    || null
})
const latestPendingExport = computed(() => {
  const taskId = latestDeviceTask.value?.id
  return taskId ? pendingDeviceExports[taskId] || null : null
})
const latestArtifactSaveStatus = computed<PendingDeviceExportState | 'manual_ready' | ''>(() => {
  const task = latestDeviceTask.value
  if (!task?.artifact_download) return ''
  return pendingDeviceExports[task.id]?.state || 'manual_ready'
})
const testActive = computed(() => {
  const taskId = connectionTest.value?.task_id
  const task = taskId ? publicDeviceTasks.value.find((item) => item.id === taskId) : null
  return Boolean(task && activeTaskStatuses.has(task.status))
})
const writeTestActive = computed(() => {
  const taskId = writeConnectionTest.value?.task_id
  const task = taskId ? publicDeviceTasks.value.find((item) => item.id === taskId) : null
  if (task) return activeTaskStatuses.has(task.status)
  return Boolean(writeConnectionTest.value && activeTaskStatuses.has(writeConnectionTest.value.task_status as TaskStatus))
})
const availableWriteTestProtocols = computed<DeviceConnectionProtocol[]>(() => {
  const protocols: DeviceConnectionProtocol[] = []
  if (writeForm.ssh_enabled) protocols.push('SSH')
  if (writeForm.telnet_enabled) protocols.push('TELNET')
  if (writeForm.snmp_enabled && (writeForm.snmp_v1_enabled || writeForm.snmp_v2c_enabled)) protocols.push('SNMP')
  return protocols
})
const writeConnectionTask = computed(() => {
  const taskId = writeConnectionTest.value?.task_id
  return taskId ? publicDeviceTasks.value.find((item) => item.id === taskId) || null : null
})
const writeConnectionBusy = computed(() => writeConnectionLoading.value || writeTestActive.value)

function hasUsableWriteSecret(field: DeviceSecretField, configured: boolean): boolean {
  if (String(writeForm[field] || '').length > 0) return true
  return writeMode.value === 'edit' && configured && !secretClears[field]
}

const writeConnectionDisabledReason = computed(() => {
  if (!isFeatureEnabled('web.device_form_connection_test')) return '当前版本未启用表单连接测试'
  if (!isFeatureEnabled('web.device_management_write')) return '设备管理写操作未启用'
  if (editingProfileLoading.value) return '编辑信息仍在加载，请稍候'
  if (writeConnectionBusy.value) return '连接测试正在执行'
  const protocol = writeTestProtocol.value
  if (!availableWriteTestProtocols.value.includes(protocol)) return `请先启用 ${protocol}`
  if (!writeForm.primary_address.trim() && !String(writeForm.backup_address || '').trim()) return '请输入主用地址或备用地址'
  const port = protocol === 'SSH' ? writeForm.ssh_port : protocol === 'TELNET' ? writeForm.telnet_port : writeForm.snmp_port
  if (!Number.isInteger(Number(port)) || Number(port) < 1 || Number(port) > 65535) return `请输入有效的 ${protocol} 端口`
  if (protocol === 'SSH') {
    if (!String(writeForm.ssh_username || '').trim()) return '请输入 SSH 用户名'
    if (!hasUsableWriteSecret('ssh_password', Boolean(detail.value?.ssh_secret_configured))) return '请输入 SSH 密码（缺少认证信息）'
  } else if (protocol === 'TELNET') {
    if (!String(writeForm.telnet_username || '').trim()) return '请输入 Telnet 用户名'
    if (!hasUsableWriteSecret('telnet_password', Boolean(detail.value?.telnet_secret_configured))) return '请输入 Telnet 密码（缺少认证信息）'
  } else if (!hasUsableWriteSecret('snmp_ro_community', Boolean(detail.value?.snmp_ro_secret_configured))) {
    return '请输入 SNMP 只读团体字'
  }
  if (protocol === 'SSH' || protocol === 'TELNET') {
    for (const [prefix, label] of [['tunnel1', '第一跳'], ['tunnel2', '第二跳']] as const) {
      if (!String(writeForm[`${prefix}_host`] || '').trim()) continue
      if (!String(writeForm[`${prefix}_username`] || '').trim()) return `请输入 SSH 隧道${label}用户名`
      if (!hasUsableWriteSecret(`${prefix}_password`, Boolean(detail.value?.[`${prefix}_secret_configured`]))) return `请输入 SSH 隧道${label}密码`
    }
  }
  return ''
})

watch(
  () => {
    const task = writeConnectionTask.value
    return task && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)
      ? `${task.id}:${task.status}:${task.updated_time}`
      : ''
  },
  async (terminalKey) => {
    if (!terminalKey) return
    const taskId = terminalKey.split(':', 1)[0]
    try {
      const result = await getDeviceConnectionTest(taskId)
      if (writeConnectionTest.value?.task_id !== taskId) return
      writeConnectionTest.value = result
      if (result.success === true) ElMessage.success(result.safe_message || 'SSH 连接成功')
      else if (result.task_status === 'CANCELLED') ElMessage.warning('连接测试已取消')
      else ElMessage.error(result.safe_message || result.message || 'SSH 连接失败')
    } catch (cause) {
      if (writeConnectionTest.value?.task_id === taskId) ElMessage.error(errorMessage(cause, '连接测试结果读取失败'))
    }
  },
)
watch(
  () => {
    const terminalKeys = Object.values(pendingDeviceExports)
      .map((pending) => {
        const task = publicDeviceTasks.value.find((item) => item.id === pending.taskId)
        if (!task || !['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)) return ''
        const artifact = task.artifact_download
        return `${task.id}:${task.status}:${artifact?.artifact_id || ''}:${artifact?.media_type || ''}:${task.updated_time}`
      })
      .filter(Boolean)
      .sort()
      .join('|')
    return terminalKeys ? `${pendingDeviceExportRetryTick.value}#${terminalKeys}` : ''
  },
  async (terminalState) => {
    if (!terminalState) return
    const terminalKeys = terminalState.slice(terminalState.indexOf('#') + 1)
    for (const terminalKey of terminalKeys.split('|')) {
      const [taskId] = terminalKey.split(':')
      const pending = pendingDeviceExports[taskId]
      if (!pending || ['saving', 'saved', 'save_failed'].includes(pending.state)) continue
      const task = publicDeviceTasks.value.find((item) => item.id === taskId)
      try {
        const result = await getDeviceExportTask(taskId)
        if (result.task_status === 'COMPLETED') {
          const artifact = task?.artifact_download
          if (!artifact || !result.available) {
            schedulePendingDeviceExportRetry()
            continue
          }
          pending.artifact = artifact
          pending.actualRowCount = result.row_count
          pending.state = 'artifact_ready'
          persistPendingDeviceExports()
          await savePendingDeviceExport(pending, result)
        } else if (result.task_status === 'CANCELLED') {
          delete pendingDeviceExports[taskId]
          persistPendingDeviceExports()
          ElMessage.warning(pending.action === 'export_template' ? '设备导入模板导出已取消' : '设备表格导出已取消')
        } else {
          pending.state = 'save_failed'
          pending.error = result.message || '导出任务失败'
          persistPendingDeviceExports()
          ElMessage.error(result.message || (pending.action === 'export_template'
            ? '设备导入模板生成失败，请查看任务日志。'
            : '设备表格导出失败'))
        }
      } catch (cause) {
        console.warn(`EXPORT_ARTIFACT_RECONCILE_RETRY task_id=${taskId}`)
        schedulePendingDeviceExportRetry()
      }
    }
  },
)

function schedulePendingDeviceExportRetry(): void {
  if (!componentActive || pendingDeviceExportRetryTimer !== null) return
  pendingDeviceExportRetryTimer = setTimeout(() => {
    pendingDeviceExportRetryTimer = null
    if (componentActive) pendingDeviceExportRetryTick.value += 1
  }, 1000)
}

const desktopHost = computed(() => getRuntimeConfig().hostType === 'electron')
const batchRefreshProgressText = computed(() => {
  const current = batchRefresh.value
  if (!current) return ''
  const summary = current.summary
  const finished = summary.completed + summary.partial_success + summary.failed + summary.cancelled + summary.rejected
  if (!current.terminal) {
    return `正在更新 ${finished}/${summary.total} 台设备（运行中 ${summary.running}，成功 ${summary.completed}，部分成功 ${summary.partial_success}，失败 ${summary.failed}，拒绝 ${summary.rejected}）`
  }
  return `批量更新完成：成功 ${summary.completed}，部分成功 ${summary.partial_success}，失败 ${summary.failed}，取消 ${summary.cancelled}，拒绝 ${summary.rejected}`
})
onMounted(async () => {
  document.addEventListener('click', closeContextMenu)
  window.addEventListener('resize', resizeDetailDrawer)
  restorePendingDeviceExports()
  taskStore.acquirePolling(pollingConsumer)
  await loadDevices()
})

onBeforeUnmount(() => {
  componentActive = false
  stopBatchRefreshPolling(true)
  clearEditingProfileState()
  savedArtifactCapability.value = ''
  savedDeviceArtifactNotice.value = null
  if (pendingDeviceExportRetryTimer !== null) {
    clearTimeout(pendingDeviceExportRetryTimer)
    pendingDeviceExportRetryTimer = null
  }
  taskStore.releasePolling(pollingConsumer)
  document.removeEventListener('click', closeContextMenu)
  endDrawerResize()
  window.removeEventListener('resize', resizeDetailDrawer)
})

async function loadDevices(resetPage = false, preserveSelection = false): Promise<void> {
  if (resetPage) filters.page = 1
  const preservedUuids = preserveSelection ? new Set(selectedUuids.value) : new Set<string>()
  loading.value = true
  error.value = ''
  try {
    const groupId = filters.group && filters.group !== 'ungrouped' ? Number(filters.group) : undefined
    pageData.value = await listDevices({
      search: filters.search,
      group_id: groupId,
      ungrouped: filters.group === 'ungrouped' || undefined,
      device_type: filters.device_type,
      vendor: filters.vendor,
      connection_status: filters.connection_status,
      page: filters.page,
      page_size: filters.page_size,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    })
    filters.page = pageData.value.page
    await nextTick()
    deviceTable.value?.clearSelection()
    if (preserveSelection) {
      const rows = pageData.value.items.filter((item) => preservedUuids.has(item.device_uuid))
      rows.forEach((row) => deviceTable.value?.toggleRowSelection(row, true))
      selectedUuids.value = rows.map((row) => row.device_uuid)
    } else {
      selectedUuids.value = []
    }
  } catch (cause) {
    error.value = errorMessage(cause, '设备列表加载失败')
    pageData.value = emptyPage()
  } finally {
    loading.value = false
  }
}

function openDetail(item: DeviceListItem): void {
  detailDeviceUuid.value = item.device_uuid
  if (!detailDrawerWidthPx.value) detailDrawerWidthPx.value = defaultDrawerWidth()
  detailVisible.value = true
  detail.value = null
  connectionTest.value = null
}

function clearEditingProfileState(): void {
  editLoadGeneration += 1
  editProfileAbortController?.abort()
  editProfileAbortController = null
  editingDeviceUuid.value = ''
  editingProfileLoading.value = false
  detail.value = null
}

function defaultDrawerWidth(): number {
  const viewport = window.innerWidth || 1280
  return clampDrawerWidth(Math.round(viewport * 0.55))
}

function clampDrawerWidth(value: number): number {
  const viewport = window.innerWidth || 1280
  const minimum = viewport < 900 ? 320 : 820
  const maximum = Math.max(minimum, Math.min(1280, viewport - 24))
  return Math.max(minimum, Math.min(maximum, Math.round(value || viewport * 0.55)))
}

function drawerMinWidth(): number {
  return (window.innerWidth || 1280) < 900 ? 320 : 820
}

function drawerMaxWidth(): number {
  return Math.max(drawerMinWidth(), Math.min(1280, (window.innerWidth || 1280) - 24))
}

function handleDrawerResizeKeydown(event: KeyboardEvent): void {
  const current = detailDrawerWidthPx.value || defaultDrawerWidth()
  if (event.key === 'ArrowLeft') detailDrawerWidthPx.value = clampDrawerWidth(current + 24)
  else if (event.key === 'ArrowRight') detailDrawerWidthPx.value = clampDrawerWidth(current - 24)
  else if (event.key === 'Home') detailDrawerWidthPx.value = drawerMinWidth()
  else if (event.key === 'End') detailDrawerWidthPx.value = drawerMaxWidth()
  else return
  event.preventDefault()
}

function resizeDetailDrawer(): void {
  detailDrawerWidthPx.value = clampDrawerWidth(detailDrawerWidthPx.value || defaultDrawerWidth())
}

function beginDrawerResize(event: PointerEvent): void {
  if ((window.innerWidth || 1280) < 900) return
  drawerDragStartX = event.clientX
  drawerDragStartWidth = detailDrawerWidthPx.value || defaultDrawerWidth()
  detailDrawerDragging.value = true
  document.addEventListener('pointermove', handleDrawerResize)
  document.addEventListener('pointerup', endDrawerResize)
}

function handleDrawerResize(event: PointerEvent): void {
  if (!detailDrawerDragging.value) return
  detailDrawerWidthPx.value = clampDrawerWidth(drawerDragStartWidth + drawerDragStartX - event.clientX)
}

function endDrawerResize(): void {
  detailDrawerDragging.value = false
  document.removeEventListener('pointermove', handleDrawerResize)
  document.removeEventListener('pointerup', endDrawerResize)
}

function openFullDetail(): void {
  const uuid = detailDeviceUuid.value
  if (!uuid) return
  detailVisible.value = false
  void router.push({ name: 'device-detail', params: { deviceId: uuid }, query: { from: 'device-management' } })
}

async function openTaskWindow(
  task: DevicePublicTask | null = latestDeviceTask.value,
  fallbackTaskId = '',
  notifyFailure = true,
): Promise<boolean> {
  const taskId = task?.id || fallbackTaskId
  const context = {
    ...(taskId ? { taskId } : {}),
    module: 'devices' as const,
    ...(task?.status ? { status: task.status } : {}),
  }
  const bridge = window.netconsoleDesktop as (typeof window.netconsoleDesktop & Partial<DeviceTaskWindowBridge>) | undefined
  if (bridge?.openTaskWindow) {
    const result = await bridge.openTaskWindow(context)
    if (!result.success && notifyFailure) ElMessage.error(result.error || '任务中心打开失败')
    return result.success
  }
  await router.push({ name: 'tasks', query: { module: 'devices', ...(taskId ? { task_id: taskId } : {}) } })
  return true
}

async function presentTasks(
  tasks: DeviceTaskReference[],
  message: string,
  openWindow = true,
): Promise<void> {
  const task = tasks[0]
  if (!task) return
  lastSubmittedTask.value = task
  savedArtifactCapability.value = ''
  savedDeviceArtifactNotice.value = null
  let taskStoreRefreshed = true
  try {
    await taskStore.refresh()
  } catch {
    taskStoreRefreshed = false
  }
  const publicTask = publicDeviceTasks.value.find((item) => item.id === task.task_id)
  let taskWindowOpened = true
  if (openWindow) {
    try {
      taskWindowOpened = await openTaskWindow(publicTask || null, task.task_id, false)
    } catch {
      taskWindowOpened = false
    }
  }
  if (taskStoreRefreshed && taskWindowOpened) {
    ElMessage.success(message)
    return
  }
  const failedSteps = [
    !taskStoreRefreshed ? '任务状态刷新失败' : '',
    !taskWindowOpened ? '任务中心打开失败' : '',
  ].filter(Boolean).join('；')
  ElMessage.warning(`任务已提交，但${failedSteps}`)
}

async function savePendingDeviceExport(
  pending: PendingDeviceExport,
  task: DeviceTaskReference,
): Promise<void> {
  const artifact = pending.artifact
  if (
    !artifact
    ||
    task.size_bytes < 0
    || !/^[0-9a-f]{64}$/i.test(task.sha256)
    || artifact.artifact_id !== task.artifact_id
    || artifact.size_bytes !== task.size_bytes
    || artifact.sha256?.toLowerCase() !== task.sha256.toLowerCase()
    || !['text/csv', 'application/csv'].includes(artifact.media_type.toLowerCase())
  ) {
    pending.state = 'save_failed'
    pending.error = '导出任务已完成，但文件完整性信息缺失。'
    persistPendingDeviceExports()
    ElMessage.error('导出任务已完成，但文件完整性信息缺失。')
    return
  }
  if (pending.state === 'saving') return
  pending.state = 'saving'
  pending.error = ''
  persistPendingDeviceExports()
  console.info(`EXPORT_LOCAL_SAVE_REQUESTED task_id=${pending.taskId}`)
  let result
  try {
    result = await downloadBackendResource({
      apiPath: artifact.api_path,
      query: { ...artifact.query },
      suggestedName: pending.suggestedName,
      destinationPath: pending.destinationPath,
      expectedSizeBytes: task.size_bytes,
      expectedSha256: task.sha256,
    })
  } catch (cause) {
    markPendingExportSaveFailed(pending, errorMessage(cause, '本地保存组件不可用，请重新检测后重试。'))
    return
  }
  if (result.status !== 'saved') {
    markPendingExportSaveFailed(
      pending,
      result.status === 'failed'
        ? result.error || '无法写入所选目录。'
        : '桌面保存未返回已落盘结果，请重新选择保存位置。',
    )
    return
  }
  pending.state = 'saved'
  pending.actualRowCount = task.row_count ?? 0
  pending.fileName = result.fileName || pending.fileName
  pending.directoryLabel = pending.directoryLabel || result.directoryLabel || '用户选择的目录'
  pending.error = ''
  persistPendingDeviceExports()
  console.info(`EXPORT_LOCAL_SAVE_RESULT saved task_id=${pending.taskId}`)
  savedArtifactCapability.value = result.capabilityId || ''
  savedDeviceArtifactNotice.value = {
    title: pending.action === 'export_template' ? '设备导入模板已保存' : '设备表格导出完成',
    description: pending.action === 'export_template'
      ? `文件：${pending.fileName}；位置：${pending.directoryLabel}`
      : `范围：${deviceExportScopeLabel(pending)}；实际导出 ${task.row_count ?? 0} 台；文件：${pending.fileName}；位置：${pending.directoryLabel}`,
  }
  ElMessage.success(pending.action === 'export_template'
    ? '设备导入模板已保存'
    : `设备表格导出完成，共 ${task.row_count ?? 0} 台设备`)
}

function markPendingExportSaveFailed(pending: PendingDeviceExport, message: string): void {
  pending.state = 'save_failed'
  pending.error = message
  persistPendingDeviceExports()
  console.info(`EXPORT_LOCAL_SAVE_RESULT failed task_id=${pending.taskId}`)
  ElMessage.error(message)
}

function isPendingExportActive(action: DeviceExportAction): boolean {
  return Object.values(pendingDeviceExports).some((pending) => {
    return pending.action === action && ['task_running', 'artifact_ready', 'saving'].includes(pending.state)
  })
}

async function downloadLatestArtifact(): Promise<void> {
  const latestTask = latestDeviceTask.value
  const artifact = latestTask?.artifact_download
  if (!artifact) return
  const pending = pendingDeviceExports[latestTask.id]
  if (pending) {
    pending.artifact = artifact
    await retryPendingDeviceExport(pending)
    return
  }
  const templateArtifact = latestTask.type.includes('template_csv')
  savedArtifactCapability.value = ''
  const result = await downloadBackendResource({
    apiPath: artifact.api_path,
    query: { ...artifact.query },
    suggestedName: artifact.display_name,
    ...(artifact.size_bytes >= 0 && /^[0-9a-f]{64}$/i.test(artifact.sha256 || '')
      ? {
          expectedSizeBytes: artifact.size_bytes,
          expectedSha256: artifact.sha256,
        }
      : {}),
  })
  if (result.status === 'failed') ElMessage.error(result.error || 'Artifact 下载失败')
  else if (result.status === 'cancelled') ElMessage.warning(
    templateArtifact
      ? '设备导入模板已生成，但尚未保存到本地。'
      : '设备表格已生成，但尚未保存到本地。',
  )
  else if (result.status === 'started') ElMessage.info('文件已交由浏览器下载，请在浏览器下载记录中查看。')
  const capabilityId = result.status === 'saved'
    && 'capabilityId' in result
    && typeof result.capabilityId === 'string'
    ? result.capabilityId
    : ''
  if (capabilityId) {
    savedArtifactCapability.value = capabilityId
    ElMessage.success('Artifact 已保存')
  }
}

async function retryPendingDeviceExport(pending: PendingDeviceExport): Promise<void> {
  if (!pending.artifact) {
    ElMessage.error('Artifact 尚未就绪，请在任务中心查看。')
    return
  }
  const destination = await chooseDeviceExportDestination(pending.fileName || pending.suggestedName)
  if (!destination) return
  pending.destinationPath = destination.path
  pending.fileName = destination.fileName
  pending.directoryLabel = destination.directoryLabel
  pending.suggestedName = destination.fileName
  pending.state = 'artifact_ready'
  pending.error = ''
  persistPendingDeviceExports()
  const result = await getDeviceExportTask(pending.taskId)
  await savePendingDeviceExport(pending, result)
}

function localSaveStatusLabel(status: PendingDeviceExportState | 'manual_ready' | ''): string {
  if (status === 'task_running') return '正在生成 Artifact'
  if (status === 'artifact_ready') return 'Artifact 已生成，等待写入所选位置'
  if (status === 'saving') return '正在写入并校验本地文件'
  if (status === 'saved') return '已保存到本地'
  if (status === 'save_failed') return '本地保存失败，可重新选择位置'
  if (status === 'manual_ready') return 'Artifact 可另存'
  return ''
}

function deviceExportScopeLabel(pending: PendingDeviceExport): string {
  if (pending.scope === 'selected') return `已选择 ${pending.requestedRowCount} 台`
  if (pending.scope === 'filtered_all') return `当前筛选结果全部 ${pending.requestedRowCount} 台`
  return '设备导入模板'
}

function persistPendingDeviceExports(): void {
  if (typeof window === 'undefined') return
  const entries = Object.values(pendingDeviceExports)
    .filter((pending) => pending.state !== 'saved')
  if (entries.length) window.sessionStorage.setItem(PENDING_DEVICE_EXPORTS_KEY, JSON.stringify(entries))
  else window.sessionStorage.removeItem(PENDING_DEVICE_EXPORTS_KEY)
}

function restorePendingDeviceExports(): void {
  if (typeof window === 'undefined') return
  const raw = window.sessionStorage.getItem(PENDING_DEVICE_EXPORTS_KEY)
  if (!raw) return
  try {
    const values = JSON.parse(raw)
    if (!Array.isArray(values)) throw new Error('invalid pending export state')
    for (const value of values) {
      if (!isRestorablePendingDeviceExport(value)) continue
      pendingDeviceExports[value.taskId] = {
        ...value,
        state: value.state === 'saving' ? 'task_running' : value.state,
      }
    }
  } catch {
    window.sessionStorage.removeItem(PENDING_DEVICE_EXPORTS_KEY)
  }
}

function isRestorablePendingDeviceExport(value: unknown): value is PendingDeviceExport {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return typeof record.taskId === 'string'
    && /^[A-Za-z0-9_-]{1,200}$/.test(record.taskId)
    && ['export_csv', 'export_template'].includes(String(record.action))
    && typeof record.destinationPath === 'string'
    && record.destinationPath.length > 0
    && typeof record.suggestedName === 'string'
    && typeof record.fileName === 'string'
    && typeof record.directoryLabel === 'string'
    && Number.isSafeInteger(record.requestedRowCount)
    && Number(record.requestedRowCount) >= 0
    && ['selected', 'filtered_all', 'template'].includes(String(record.scope))
    && ['task_running', 'artifact_ready', 'saving', 'save_failed'].includes(String(record.state))
}

async function useSavedArtifact(reveal: boolean): Promise<void> {
  if (!desktopHost.value || !savedArtifactCapability.value) return
  const result = reveal
    ? await getPlatformAdapter().showItemInFolder(savedArtifactCapability.value)
    : await getPlatformAdapter().openPath(savedArtifactCapability.value)
  if (!result.success) {
    ElMessage.error(result.error || (reveal ? '定位文件失败' : '打开文件失败'))
  }
}

function currentDeviceWriteValues(): DeviceWriteRequest | null {
  if (!detail.value) return null
  const profile = detail.value
  return {
    name: profile.name,
    system_name: profile.system_name,
    station: profile.station,
    location: profile.location,
    group_id: profile.group_id,
    device_vendor: profile.device_vendor,
    device_type: profile.device_type,
    primary_address: profile.primary_address,
    backup_address: profile.backup_address,
    ssh_enabled: profile.ssh_enabled ?? false,
    ssh_port: profile.ssh_port ?? 22,
    ssh_username: profile.ssh_username,
    ssh_password: '',
    telnet_enabled: profile.telnet_enabled ?? false,
    telnet_port: profile.telnet_port ?? 23,
    telnet_username: profile.telnet_username,
    telnet_password: '',
    tunnel_enabled: profile.tunnel_enabled,
    tunnel1_enabled: profile.tunnel1_enabled,
    tunnel1_host: profile.tunnel1_host,
    tunnel1_port: profile.tunnel1_port ?? 22,
    tunnel1_username: profile.tunnel1_username,
    tunnel1_password: '',
    tunnel2_enabled: profile.tunnel2_enabled,
    tunnel2_host: profile.tunnel2_host,
    tunnel2_port: profile.tunnel2_port ?? 22,
    tunnel2_username: profile.tunnel2_username,
    tunnel2_password: '',
    snmp_enabled: profile.snmp_enabled ?? false,
    snmp_v1_enabled: profile.snmp_v1_enabled,
    snmp_v2c_enabled: profile.snmp_v2c_enabled,
    snmp_port: profile.snmp_port ?? 161,
    snmp_ro_community: '',
    snmp_timeout_ms: profile.snmp_timeout_ms,
    snmp_retries: profile.snmp_retries,
    https_port: profile.https_port,
    remark: profile.remark,
  }
}

function onSelectionChange(rows: DeviceListItem[]): void {
  selectedUuids.value = rows.map((row) => row.device_uuid)
}

function clearSelection(): void {
  deviceTable.value?.clearSelection()
}

function invertSelection(): void {
  const selected = new Set(selectedUuids.value)
  for (const row of pageData.value.items) {
    deviceTable.value?.toggleRowSelection(row, !selected.has(row.device_uuid))
  }
}

function showContextMenu(row: DeviceListItem, column: { property?: string; label?: string }, event: MouseEvent): void {
  event.preventDefault()
  contextMenu.visible = true
  contextMenu.x = event.clientX
  contextMenu.y = event.clientY
  contextMenu.row = row
  const value = column.property ? row[column.property as keyof DeviceListItem] : null
  contextMenu.cellValue = value == null
    ? column.label === '登录协议'
      ? [row.capabilities.ssh && 'SSH', row.capabilities.telnet && 'Telnet'].filter(Boolean).join('/')
      : column.label === '连接状态' ? statusLabel(row.connection_status) : ''
    : String(value)
}

function closeContextMenu(): void {
  contextMenu.visible = false
  contextMenu.row = null
  contextMenu.cellValue = ''
}

async function copyCurrentCell(): Promise<void> {
  await copyText(contextMenu.cellValue)
}

async function copyRow(row: DeviceListItem): Promise<void> {
  const protocols = [row.capabilities.ssh && 'SSH', row.capabilities.telnet && 'Telnet'].filter(Boolean).join('/')
  await copyText([
    ['名称', row.name],
    ['分组', row.group_name],
    ['系统名', row.system_name],
    ['站点', row.station],
    ['主地址', row.primary_address],
    ['备用地址', row.backup_address],
    ['登录协议', protocols],
    ['更新时间', row.updated_at],
  ].map(([label, value]) => `${label}: ${value}`).join(' | '))
}

async function copyDeviceInfo(row: DeviceListItem): Promise<void> {
  await copyText([
    `名称: ${row.name}`,
    `分组: ${row.group_name}`,
    `系统名: ${row.system_name}`,
    `站点: ${row.station}`,
    `主地址: ${row.primary_address}`,
    `备用地址: ${row.backup_address}`,
  ].join('\n'))
}

async function editSelected(): Promise<void> {
  const row = pageData.value.items.find((item) => item.device_uuid === selectedUuids.value[0])
  if (row) await editRow(row)
}

function openCreate(): void {
  clearEditingProfileState()
  writeMode.value = 'create'
  resetSecretClears()
  Object.assign(writeForm, {
    name: '', system_name: '', station: '', location: '', group_id: null, device_vendor: 'H3C', device_type: 'SW', primary_address: '', backup_address: '',
    ssh_enabled: true, ssh_port: 22, ssh_username: '', ssh_password: '', telnet_enabled: false, telnet_port: 23, telnet_username: '', telnet_password: '',
    tunnel_enabled: false, tunnel1_enabled: false, tunnel1_host: '', tunnel1_port: 22, tunnel1_username: '', tunnel1_password: '', tunnel2_enabled: false, tunnel2_host: '', tunnel2_port: 22, tunnel2_username: '', tunnel2_password: '',
    snmp_enabled: true, snmp_v1_enabled: false, snmp_v2c_enabled: true, snmp_port: 161, snmp_ro_community: '', snmp_timeout_ms: 2000, snmp_retries: 1,
    https_port: null, remark: '',
  })
  resetWriteConnectionTest()
  writeVisible.value = true
}

function openEditForm(): void {
  const values = currentDeviceWriteValues()
  if (!values) return
  writeMode.value = 'edit'
  resetSecretClears()
  Object.assign(writeForm, values)
  resetWriteConnectionTest()
  writeVisible.value = true
}

async function openEdit(deviceUuid = detailDeviceUuid.value): Promise<void> {
  if (!deviceUuid) return
  editLoadGeneration += 1
  const generation = editLoadGeneration
  editProfileAbortController?.abort()
  const controller = new AbortController()
  editProfileAbortController = controller
  editingDeviceUuid.value = deviceUuid
  editingProfileLoading.value = true
  detail.value = null
  try {
    const profile = await getDeviceEditProfile(deviceUuid, controller.signal)
    if (generation !== editLoadGeneration || controller.signal.aborted || editingDeviceUuid.value !== deviceUuid) return
    detail.value = profile
    openEditForm()
  } catch (cause) {
    if (generation !== editLoadGeneration || controller.signal.aborted) return
    ElMessage.error(errorMessage(cause, '设备编辑信息加载失败'))
  } finally {
    if (generation === editLoadGeneration && editProfileAbortController === controller) {
      editProfileAbortController = null
      editingProfileLoading.value = false
    }
  }
}

function resetWriteConnectionTest(): void {
  writeConnectionTest.value = null
  writeTestProtocol.value = availableWriteTestProtocols.value[0] || 'SSH'
}

function resetSecretClears(): void {
  for (const field of Object.keys(secretClears) as DeviceSecretField[]) secretClears[field] = false
}

function resetSecretVisibility(): void {
  for (const field of Object.keys(secretVisible) as DeviceSecretField[]) {
    secretVisible[field] = false
    secretRevealLoading[field] = false
  }
}

function savedSecretConfigured(field: DeviceSecretField): boolean {
  if (!detail.value) return false
  return Boolean({
    ssh_password: detail.value.ssh_secret_configured,
    telnet_password: detail.value.telnet_secret_configured,
    tunnel1_password: detail.value.tunnel1_secret_configured,
    tunnel2_password: detail.value.tunnel2_secret_configured,
    snmp_ro_community: detail.value.snmp_ro_secret_configured,
  }[field])
}

async function toggleSecretVisibility(field: DeviceSecretField): Promise<void> {
  if (secretVisible[field]) {
    secretVisible[field] = false
    return
  }
  if (
    writeMode.value === 'edit'
    && !String(writeForm[field] || '')
    && savedSecretConfigured(field)
  ) {
    if (!editingDeviceUuid.value || !desktopHost.value) {
      ElMessage.error('仅本机桌面端可以读取已保存凭据')
      return
    }
    secretRevealLoading[field] = true
    try {
      const revealed = await revealDeviceCredential(editingDeviceUuid.value, field)
      if (revealed.credential_field !== field) throw new Error('凭据字段校验失败')
      writeForm[field] = revealed.value
    } catch (cause) {
      ElMessage.error(errorMessage(cause, '读取已保存凭据失败'))
      return
    } finally {
      secretRevealLoading[field] = false
    }
  }
  secretVisible[field] = true
}

function setSecretCleared(field: DeviceSecretField, cleared: boolean): void {
  secretClears[field] = cleared
  if (cleared) {
    writeForm[field] = ''
    secretVisible[field] = false
  }
}

function clearWriteSecrets(): void {
  Object.assign(writeForm, {
    ssh_password: '',
    telnet_password: '',
    tunnel1_password: '',
    tunnel2_password: '',
    snmp_ro_community: '',
  })
  resetSecretClears()
  resetSecretVisibility()
}

function deviceWritePayload(): DeviceWriteRequest {
  const payload: DeviceWriteRequest = { ...writeForm }
  const clearSecretFields = (Object.keys(secretClears) as DeviceSecretField[]).filter((field) => secretClears[field])
  for (const field of clearSecretFields) delete payload[field]
  if (clearSecretFields.length) payload.clear_secret_fields = clearSecretFields
  else delete payload.clear_secret_fields
  return payload
}

async function testWriteConnection(): Promise<void> {
  const protocols = availableWriteTestProtocols.value
  if (!protocols.length) {
    ElMessage.warning('请先启用 SSH、Telnet 或 SNMP')
    return
  }
  if (!protocols.includes(writeTestProtocol.value)) writeTestProtocol.value = protocols[0]
  const editTargetUuid = writeMode.value === 'edit' ? editingDeviceUuid.value : ''
  if (writeMode.value === 'edit' && editingProfileLoading.value) {
    ElMessage.warning('编辑信息仍在加载，请稍候')
    return
  }
  if (writeMode.value === 'edit' && !editTargetUuid) {
    ElMessage.error('详情编辑目标已失效，请关闭后重新打开')
    return
  }
  if (writeConnectionDisabledReason.value) {
    ElMessage.warning(writeConnectionDisabledReason.value)
    return
  }
  writeConnectionLoading.value = true
  try {
    const result = await startDeviceFormConnectionTest({
      ...deviceWritePayload(),
      protocol: writeTestProtocol.value,
      device_uuid: editTargetUuid || undefined,
    })
    writeConnectionTest.value = result
    lastSubmittedTask.value = {
      task_id: result.task_id,
      task_status: result.task_status,
      action: 'connection_test',
      artifact_id: '',
      available: false,
      sha256: '',
      size_bytes: 0,
      message: result.message,
    }
    try {
      await taskStore.refresh()
      ElMessage.success(`${writeTestProtocol.value} 表单连接测试任务已提交`)
    } catch {
      ElMessage.warning('连接测试任务已提交，但任务状态刷新失败；可使用“打开任务中心”继续查看')
    }
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '表单连接测试任务提交失败'))
  } finally {
    writeConnectionLoading.value = false
  }
}

async function openWriteConnectionTestTask(): Promise<void> {
  const taskId = writeConnectionTest.value?.task_id
  const task = taskId ? publicDeviceTasks.value.find((item) => item.id === taskId) : null
  await openTaskWindow(task || null, taskId || '')
}

function closeWriteDialog(): void {
  clearWriteSecrets()
  clearEditingProfileState()
}

function cancelWriteDialog(): void {
  writeVisible.value = false
  clearWriteSecrets()
}

async function saveWrite(): Promise<void> {
  const editedUuid = writeMode.value === 'edit' ? editingDeviceUuid.value : ''
  if (writeMode.value === 'edit' && editingProfileLoading.value) {
    ElMessage.warning('编辑信息仍在加载，请稍候')
    return
  }
  if (writeMode.value === 'edit' && !editedUuid) {
    ElMessage.error('详情编辑目标已失效，请关闭后重新打开')
    return
  }
  writeLoading.value = true
  try {
    if (writeMode.value === 'create') await createDevice(deviceWritePayload())
    else await updateDevice(editedUuid, deviceWritePayload())
    writeVisible.value = false
    clearWriteSecrets()
    ElMessage.success(writeMode.value === 'create' ? '设备已创建' : '设备已保存')
    await loadDevices(true)
    if (editedUuid) detail.value = null
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设备保存失败'))
  } finally {
    writeLoading.value = false
  }
}

async function duplicateSelected(): Promise<void> {
  const uuid = selectedUuids.value[0] || detailDeviceUuid.value
  if (!uuid) {
    ElMessage.warning('请先选择设备')
    return
  }
  await duplicateByUuid(uuid)
}

async function deleteRows(deviceUuids: string[]): Promise<void> {
  if (!deviceUuids.length) return
  try {
    if (!await confirm({ type: 'DESTRUCTIVE', title: '删除设备', message: `确认删除 ${deviceUuids.length} 台设备？删除后设备将从当前局点数据库移除。`, confirmText: '确认删除' })) return
    const token = await issueDeviceDeleteToken(deviceUuids)
    await deleteDevices(deviceUuids, token.confirmation_token)
    selectedUuids.value = []
    ElMessage.success('设备已删除')
    await loadDevices(true)
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, '删除设备失败'))
  }
}

async function duplicateRow(row: DeviceListItem): Promise<void> {
  await duplicateByUuid(row.device_uuid)
}

async function duplicateByUuid(deviceUuid: string): Promise<void> {
  try {
    if (!await confirm({ type: 'WARNING', title: '复制设备', message: '将复制当前设备及其已配置凭据，并生成新的设备 UUID。是否继续？', confirmText: '确认复制' })) return
    await duplicateDevice(deviceUuid)
    ElMessage.success('设备已复制')
    await loadDevices(true)
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, '复制设备失败'))
  }
}

async function editRow(row: DeviceListItem): Promise<void> {
  openDetail(row)
  await openEdit(row.device_uuid)
}

async function deleteSelected(): Promise<void> {
  await deleteRows(selectedUuids.value)
}

async function startSelectedConnectionTests(): Promise<void> {
  if (!selectedUuids.value.length) return
  const selected = pageData.value.items.filter((item) => selectedUuids.value.includes(item.device_uuid))
  const blocked = selected.filter((item) => item.credential_status !== 'available')
  if (blocked.length) {
    const first = blocked[0]
    ElMessage.warning(first.credential_message || `${blocked.length} 台设备缺少可用凭据，请先编辑设备重新录入`)
    if (blocked.length === 1) await editRow(first)
    return
  }
  try {
    const result = await startBatchConnectionTests(selectedUuids.value)
    await presentTasks(result.tasks, `已提交 ${result.tasks.length} 个连接测试任务`)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '连接测试任务提交失败'))
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
  if (!await confirm({
    type: 'DESTRUCTIVE',
    title: '确认删除设备分组',
    message: `删除分组“${name}”后，组内设备将变为未分组。`,
    confirmText: '确认删除分组',
  })) return
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
    await presentTasks(
      [await confirmDeviceImport(importPreview.value.preview_token, importDuplicateStrategy.value)],
      'CSV 导入任务已提交',
    )
    closeImportDialog()
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
  importDuplicateStrategy.value = 'reject'
  if (importFileInput.value) importFileInput.value.value = ''
}

function currentExportFilters(
  scope: Exclude<DeviceExportScope, 'template'> = selectedUuids.value.length ? 'selected' : 'filtered_all',
  includeCredentials = false,
): DeviceExportRequest {
  return {
    device_uuids: scope === 'selected' ? [...selectedUuids.value] : [],
    export_scope: scope,
    search: filters.search,
    vendor: filters.vendor,
    device_type: filters.device_type,
    group_filter: filters.group === 'ungrouped' ? '__ungrouped__' : filters.group ? Number(filters.group) : undefined,
    include_credentials: includeCredentials,
  }
}

async function exportCsv(includeCredentials = false): Promise<void> {
  if (csvExportActive.value) return
  try {
    if (includeCredentials) {
      if (!await confirm({ type: 'SECURITY', title: '导出含凭据的 CSV', message: '导出文件将包含设备登录凭据。请仅保存到受控目录并妥善保管，是否继续？', confirmText: '确认导出', acknowledgementText: '我已确认导出目录受控并会妥善保管文件', requireAcknowledgement: true })) return
    }
    csvExportIncludeCredentials.value = includeCredentials
    csvExportScope.value = selectedUuids.value.length ? 'selected' : 'filtered_all'
    csvExportScopeVisible.value = true
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, 'CSV 导出失败'))
  }
}

async function confirmCsvExportScope(): Promise<void> {
  if (csvExportScope.value === 'selected' && !selectedUuids.value.length) {
    ElMessage.warning('请先选择要导出的设备')
    return
  }
  const scope = csvExportScope.value
  const requestedRowCount = scope === 'selected' ? selectedUuids.value.length : pageData.value.total
  csvExportScopeVisible.value = false
  const destination = await chooseDeviceExportDestination(deviceCsvSuggestedName())
  if (!destination) return
  csvExportSubmitting.value = true
  try {
    const task = await startDeviceCsvExport(currentExportFilters(scope, csvExportIncludeCredentials.value))
    registerPendingDeviceExport(task, {
      action: 'export_csv',
      destination,
      requestedRowCount,
      scope,
    })
    await presentTasks([task], 'CSV 导出任务已提交，完成后将写入所选位置', false)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'CSV 导出失败'))
  } finally {
    csvExportSubmitting.value = false
  }
}

async function exportTemplate(): Promise<void> {
  if (templateExportActive.value) return
  const destination = await chooseDeviceExportDestination(deviceTemplateSuggestedName())
  if (!destination) return
  templateExportSubmitting.value = true
  try {
    const task = await startDeviceTemplateExport()
    registerPendingDeviceExport(task, {
      action: 'export_template',
      destination,
      requestedRowCount: 0,
      scope: 'template',
    })
    await presentTasks([task], '模板导出任务已提交，完成后将写入所选位置', false)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '模板导出失败'))
  } finally {
    templateExportSubmitting.value = false
  }
}

function registerPendingDeviceExport(
  task: DeviceTaskReference,
  values: {
    action: DeviceExportAction
    destination: { path: string; fileName: string; directoryLabel: string }
    requestedRowCount: number
    scope: DeviceExportScope
  },
): void {
  pendingDeviceExports[task.task_id] = {
    taskId: task.task_id,
    action: values.action,
    destinationPath: values.destination.path,
    suggestedName: values.destination.fileName,
    fileName: values.destination.fileName,
    directoryLabel: values.destination.directoryLabel,
    requestedRowCount: values.requestedRowCount,
    scope: values.scope,
    state: 'task_running',
  }
  persistPendingDeviceExports()
}

async function chooseDeviceExportDestination(
  suggestedName: string,
): Promise<{ path: string; fileName: string; directoryLabel: string } | null> {
  const result = await getPlatformAdapter().chooseSavePath({
    suggestedName,
    filters: [{ name: 'CSV 文件', extensions: ['csv'] }],
  })
  if (result.cancelled || !result.path) return null
  return {
    path: result.path,
    fileName: selectedFileName(result.path) || suggestedName,
    directoryLabel: selectedDirectoryLabel(result.path),
  }
}

function deviceCsvSuggestedName(): string {
  return `${safeExportFilePart(pageData.value.site_name || '当前局点')}-设备表-${localTimestamp()}.csv`
}

function deviceTemplateSuggestedName(): string {
  return `${safeExportFilePart(pageData.value.site_name || '当前局点')}-设备导入模板.csv`
}

function safeExportFilePart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || '当前局点'
}

function localTimestamp(now = new Date()): string {
  const value = (number: number) => String(number).padStart(2, '0')
  return `${now.getFullYear()}${value(now.getMonth() + 1)}${value(now.getDate())}_${value(now.getHours())}${value(now.getMinutes())}${value(now.getSeconds())}`
}

function selectedFileName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || ''
}

function selectedDirectoryLabel(path: string): string {
  const normalized = path.replace(/[\\/]+$/, '')
  const separator = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'))
  return separator > 0 ? normalized.slice(0, separator) : '用户选择的目录'
}

function openSecureCrtExport(): void {
  secureCrtTemplateFile.value = null
  if (secureCrtTemplateInput.value) secureCrtTemplateInput.value.value = ''
  secureCrtVisible.value = true
}

function chooseSecureCrtTemplate(): void {
  secureCrtTemplateInput.value?.click()
}

function onSecureCrtTemplateChange(event: Event): void {
  secureCrtTemplateFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function exportSecureCrt(): Promise<void> {
  try {
    const payload = currentExportFilters()
    const task = secureCrtTemplateFile.value
      ? await startSecureCrtExportWithTemplate(payload, secureCrtTemplateFile.value)
      : await startSecureCrtExport(payload)
    await presentTasks([task], 'SecureCRT 会话任务已提交')
    secureCrtVisible.value = false
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'SecureCRT 会话生成失败'))
  }
}

async function refreshSelectedDetails(): Promise<void> {
  const targets = [...selectedUuids.value]
  if (!targets.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  if (batchRefreshSubmitting.value) return
  const accepted = await confirm({
    type: 'WARNING',
    title: '批量更新详情',
    message: `确定更新选中的 ${targets.length} 台设备详情吗？`,
    confirmText: '确认更新',
  })
  if (!accepted) return
  batchRefreshSubmitting.value = true
  batchRefreshTargetCount.value = targets.length
  batchRefresh.value = null
  stopBatchRefreshPolling(true)
  const generation = batchRefreshGeneration
  ElMessage.info(`正在更新 0/${targets.length} 台设备`)
  try {
    const result = await startBatchRefreshDetails(targets)
    if (!componentActive) return
    batchRefresh.value = result
    activeBatchRefreshId = result.batch_id
    if (result.terminal) {
      await finishBatchRefresh(result, generation)
    } else {
      scheduleBatchRefreshPoll(result.batch_id, generation)
    }
  } catch (cause) {
    if (componentActive) ElMessage.error(errorMessage(cause, '批量刷新失败'))
    if (componentActive) {
      batchRefreshSubmitting.value = false
      batchRefreshTargetCount.value = 0
    }
  }
}

function stopBatchRefreshPolling(invalidate = false): void {
  if (batchRefreshPollTimer !== null) {
    clearTimeout(batchRefreshPollTimer)
    batchRefreshPollTimer = null
  }
  activeBatchRefreshId = ''
  if (invalidate) batchRefreshGeneration += 1
}

function scheduleBatchRefreshPoll(batchId: string, generation: number): void {
  if (!componentActive || generation !== batchRefreshGeneration || activeBatchRefreshId !== batchId) return
  batchRefreshPollTimer = setTimeout(() => {
    batchRefreshPollTimer = null
    void pollBatchRefresh(batchId, generation)
  }, 1000)
}

async function pollBatchRefresh(batchId: string, generation: number): Promise<void> {
  if (!componentActive || generation !== batchRefreshGeneration || activeBatchRefreshId !== batchId) return
  try {
    const result = await getBatchRefresh(batchId)
    if (!componentActive || generation !== batchRefreshGeneration || activeBatchRefreshId !== batchId) return
    batchRefresh.value = result
    if (result.terminal) {
      await finishBatchRefresh(result, generation)
    } else {
      scheduleBatchRefreshPoll(batchId, generation)
    }
  } catch (cause) {
    if (!componentActive || generation !== batchRefreshGeneration) return
    stopBatchRefreshPolling()
    batchRefreshSubmitting.value = false
    batchRefreshTargetCount.value = 0
    ElMessage.error(errorMessage(cause, '批量刷新状态查询失败'))
  }
}

async function finishBatchRefresh(result: DeviceTaskBatch, generation: number): Promise<void> {
  if (!componentActive || generation !== batchRefreshGeneration || activeBatchRefreshId !== result.batch_id) return
  stopBatchRefreshPolling()
  batchRefreshSubmitting.value = false
  batchRefreshTargetCount.value = 0
  await loadDevices(false, true)
  if (!componentActive || generation !== batchRefreshGeneration) return
  const summary = result.summary
  const problemCount = summary.partial_success + summary.failed + summary.cancelled + summary.rejected
  const message = `批量更新完成：成功 ${summary.completed}，部分成功 ${summary.partial_success}，失败 ${summary.failed}，取消 ${summary.cancelled}，拒绝 ${summary.rejected}`
  if (problemCount) ElMessage.warning(message)
  else ElMessage.success(message)
}

async function downloadDiagnostics(): Promise<void> {
  if (!selectedUuids.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    await presentTasks(
      [await startDeviceDiagnosticDownload(selectedUuids.value)],
      '诊断信息下载任务已提交',
    )
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '诊断信息下载失败'))
  }
}

async function openTerminalSettings(): Promise<void> {
  if (!desktopHost.value) {
    ElMessage.warning('外部终端配置仅在 Electron Desktop 中可用')
    return
  }
  terminalSettingsVisible.value = true
  terminalSettingsLoading.value = true
  try {
    Object.assign(terminalSettings, await getExternalTerminalSettings())
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '外部终端配置加载失败'))
  } finally {
    terminalSettingsLoading.value = false
  }
}

async function chooseTerminalExecutable(terminalType: 'securecrt' | 'putty' | 'xshell'): Promise<void> {
  const result = await getPlatformAdapter().selectFile({
    filters: [{ name: `${terminalType} executable`, extensions: ['exe'] }],
  })
  const path = result.paths[0]
  if (!result.cancelled && path) terminalSettings[`${terminalType}_path`] = path
}

async function saveTerminalSettings(): Promise<void> {
  terminalSettingsLoading.value = true
  const previousPassPassword = terminalSettings.pass_password
  try {
    if (terminalSettings.pass_password) {
      const accepted = await confirm({
        type: 'SECURITY',
        title: '启用终端密码传递？',
        message: '启用后，NetConsole 可能会将设备登录密码作为外部终端启动参数传递。',
        detail: '该参数可能被本机进程查看，仅建议在受控电脑中使用。设置不会写入任务、日志或 API 响应。',
        confirmText: '确认启用',
        acknowledgementText: '我已了解密码可能出现在外部程序启动参数中',
        requireAcknowledgement: true,
      })
      if (!accepted) {
        terminalSettings.pass_password = previousPassPassword
        return
      }
    }
    Object.assign(terminalSettings, await updateExternalTerminalSettings({ ...terminalSettings }))
    terminalSettingsVisible.value = false
    ElMessage.success('外部终端配置已保存')
  } catch (cause) {
    terminalSettings.pass_password = previousPassPassword
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, '外部终端配置保存失败'))
  } finally {
    terminalSettingsLoading.value = false
  }
}

async function requestTerminal(deviceUuid?: string): Promise<void> {
  const targetUuids = deviceUuid
    ? [deviceUuid]
    : selectedUuids.value.length
      ? [...selectedUuids.value]
      : detailDeviceUuid.value
        ? [detailDeviceUuid.value]
        : []
  if (!targetUuids.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    Object.assign(terminalSettings, await getExternalTerminalSettings())
    const configured = (['securecrt', 'xshell', 'putty'] as const).filter((type) => Boolean(terminalSettings[`${type}_path`]))
    if (!configured.length) {
      ElMessage.warning('尚未配置外部终端程序路径')
      await openTerminalSettings()
      return
    }
    if (!configured.includes(terminalSettings.terminal_type)) terminalSettings.terminal_type = configured[0]
    terminalTargetUuids.value = targetUuids
    terminalLaunchVisible.value = true
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, '外部终端请求失败'))
  }
}

async function launchTerminalTargets(): Promise<void> {
  try {
    let confirmationToken = ''
    if (terminalTargetUuids.value.length > 20) {
      if (!await confirm({ type: 'WARNING', title: '批量打开外部终端', message: `将打开 ${terminalTargetUuids.value.length} 台设备的外部终端，是否继续？`, confirmText: '确认打开终端' })) return
      confirmationToken = (
        await issueExternalTerminalConfirmation(
          terminalTargetUuids.value,
          terminalSettings.terminal_type,
        )
      ).confirmation_token
    }
    const result = await launchExternalTerminals(
      terminalTargetUuids.value,
      terminalSettings.terminal_type,
      confirmationToken,
    )
    terminalLaunchVisible.value = false
    if (result.failed) {
      ElMessage.warning(`外部终端启动完成：成功 ${result.success}，失败 ${result.failed}。${result.failures.slice(0, 3).join('；')}`)
    } else {
      ElMessage.success(`已启动 ${result.success} 个外部终端`)
    }
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, '外部终端启动失败'))
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
  if (['UNREACHABLE', 'AUTH_FAILED', 'ERROR'].includes(status)) return 'danger'
  return 'info'
}

function statusLabel(status: DeviceConnectionStatus): string {
  return { UNKNOWN: '未测试', TESTING: '测试中', REACHABLE: '可达', UNREACHABLE: '不可达', AUTH_FAILED: '认证失败', ERROR: '任务异常' }[status]
}

function collectStatusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status || '').toUpperCase()
  if (normalized === 'COMPLETED' || normalized === 'SUCCESS') return 'success'
  if (['ACCEPTED', 'REUSED', 'RUNNING', 'PARTIAL_SUCCESS'].includes(normalized)) return 'warning'
  if (['FAILED', 'REJECTED', 'CANCELLED'].includes(normalized)) return 'danger'
  return 'info'
}

function collectStatusLabel(status: string): string {
  const normalized = String(status || '').toUpperCase()
  return {
    ACCEPTED: '已受理',
    REUSED: '复用任务',
    REJECTED: '已拒绝',
    RUNNING: '运行中',
    COMPLETED: '成功',
    SUCCESS: '成功',
    PARTIAL_SUCCESS: '部分成功',
    FAILED: '失败',
    CANCELLED: '已取消',
  }[normalized] || '未采集'
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}
</script>

<template>
  <section class="device-management">
    <div class="page-heading">
      <div><h1>设备管理</h1><p>管理当前局点设备、连接参数、采集任务和导入导出。</p></div>
      <div class="heading-actions"><el-button type="primary" :icon="Plus" :disabled="!isFeatureEnabled('web.device_management_write')" @click="openCreate">新建设备</el-button><el-button :icon="FolderOpened" :disabled="!desktopHost || !isFeatureEnabled('web.device_management_desktop')" @click="openTerminalSettings">外部终端配置</el-button><el-button :icon="Refresh" :loading="loading" @click="loadDevices()">刷新</el-button></div>
    </div>

    <div class="content-card filters">
      <el-input v-model="filters.search" clearable placeholder="搜索名称、地址、站点、类型或分组" @keyup.enter="loadDevices(true)" />
      <el-select v-model="filters.group" clearable placeholder="全部分组" @change="loadDevices(true)">
        <el-option label="未分组" value="ungrouped" />
        <el-option v-for="group in pageData.groups" :key="group.id" :label="group.name" :value="String(group.id)" />
      </el-select>
      <el-select v-model="filters.device_type" clearable placeholder="全部类型" @change="loadDevices(true)">
        <el-option v-for="type in DEVICE_TYPE_OPTIONS" :key="type" :label="type" :value="type" />
      </el-select>
      <el-select v-model="filters.vendor" clearable placeholder="全部厂商" @change="loadDevices(true)">
        <el-option v-for="vendor in DEVICE_VENDOR_OPTIONS" :key="vendor.value" :label="vendor.label" :value="vendor.value" />
      </el-select>
      <el-select v-model="filters.connection_status" clearable placeholder="全部状态" @change="loadDevices(true)">
        <el-option label="未测试" value="UNKNOWN" /><el-option label="测试中" value="TESTING" />
        <el-option label="可达" value="REACHABLE" /><el-option label="不可达" value="UNREACHABLE" />
        <el-option label="认证失败" value="AUTH_FAILED" /><el-option label="任务异常" value="ERROR" />
      </el-select>
      <el-select v-model="filters.sort_by" @change="loadDevices(true)">
        <el-option label="按名称" value="name" /><el-option label="按地址" value="primary_address" />
        <el-option label="按站点" value="station" /><el-option label="按资料更新时间" value="metadata_updated_at" />
        <el-option label="按最后采集时间" value="last_collected_at" />
        <el-option label="按采集状态" value="last_collect_status" /><el-option label="按连接状态" value="status" />
      </el-select>
      <el-select v-model="filters.sort_order" @change="loadDevices(true)">
        <el-option label="升序" value="asc" /><el-option label="降序" value="desc" />
      </el-select>
      <el-button type="primary" @click="loadDevices(true)">筛选</el-button>
    </div>

    <div class="content-card action-bar">
      <span>已选 {{ selectedUuids.length }} 台</span>
      <el-button :icon="Edit" :disabled="selectedUuids.length !== 1 || !isFeatureEnabled('web.device_management_write')" @click="editSelected">编辑</el-button>
      <el-button :icon="CopyDocument" :disabled="selectedUuids.length !== 1 || !isFeatureEnabled('web.device_management_write')" @click="duplicateSelected">复制</el-button>
      <el-button :icon="Delete" type="danger" plain :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_write')" @click="deleteSelected">批量删除</el-button>
      <el-button :icon="FolderOpened" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_write')" @click="groupAssignVisible = true">设置分组</el-button>
      <el-button :icon="Plus" :disabled="!isFeatureEnabled('web.device_management_write')" @click="groupVisible = true">分组管理</el-button>
      <el-button :icon="Connection" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_connection_test')" @click="startSelectedConnectionTests">测试连接</el-button>
      <el-button :icon="FolderOpened" :disabled="!desktopHost || !selectedUuids.length || !isFeatureEnabled('web.device_management_desktop')" @click="requestTerminal()">外部终端</el-button>
      <el-button data-testid="batch-refresh-details" :icon="Refresh" :loading="batchRefreshSubmitting" :disabled="!selectedUuids.length || batchRefreshSubmitting || !isFeatureEnabled('web.device_management_collect')" @click="refreshSelectedDetails">批量更新详情</el-button>
      <span v-if="batchRefreshSubmitting">{{ batchRefreshProgressText || `正在更新 0/${batchRefreshTargetCount} 台设备` }}</span>
      <el-button :icon="Download" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_collect')" @click="downloadDiagnostics">下载诊断</el-button>
      <el-button :icon="Upload" :disabled="!isFeatureEnabled('web.device_management_import')" @click="importVisible = true">导入 CSV</el-button>
      <el-button
        data-testid="device-export-template"
        :icon="Download"
        :loading="templateExportSubmitting"
        :disabled="templateExportActive || !isFeatureEnabled('web.device_management_export')"
        @click="exportTemplate"
      >下载模板</el-button>
      <el-dropdown>
        <el-button :icon="Download" :loading="csvExportSubmitting" :disabled="!isFeatureEnabled('web.device_management_export')">导出</el-button>
        <template #dropdown><el-dropdown-menu><el-dropdown-item data-testid="device-export-csv-no-credentials" :disabled="csvExportActive || !isFeatureEnabled('web.device_management_export')" @click="exportCsv(false)">CSV 导出（不含凭据）</el-dropdown-item><el-dropdown-item :disabled="csvExportActive || !isFeatureEnabled('web.device_management_export')" @click="exportCsv(true)">CSV 导出（含凭据）</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="openSecureCrtExport">SecureCRT 会话</el-dropdown-item></el-dropdown-menu></template>
      </el-dropdown>
      <el-button :disabled="!selectedUuids.length" @click="clearSelection">清空选择</el-button>
      <el-button :disabled="!pageData.items.length" @click="invertSelection">反选当前页</el-button>
    </div>

    <el-alert
      v-if="latestDeviceTask?.artifact_download"
      title="设备任务文件已生成"
      :description="latestPendingExport
        ? `${deviceExportScopeLabel(latestPendingExport)} · 目标：${latestPendingExport.fileName} · ${localSaveStatusLabel(latestPendingExport.state)}`
        : `${latestDeviceTask.name || latestDeviceTask.type} · ${latestDeviceTask.message || latestDeviceTask.id}`"
      :type="latestPendingExport?.state === 'save_failed' ? 'warning' : 'success'"
      :closable="false"
      show-icon
      class="task-summary"
    >
      <el-button
        link
        type="primary"
        :disabled="latestArtifactSaveStatus === 'saving'"
        @click="downloadLatestArtifact"
      >{{ latestPendingExport?.state === 'save_failed' ? '重新保存' : latestPendingExport?.state === 'saved' ? '再次另存为' : '另存 Artifact' }}</el-button>
      <el-button v-if="desktopHost && savedArtifactCapability" link type="primary" @click="useSavedArtifact(false)">打开文件</el-button>
      <el-button v-if="desktopHost && savedArtifactCapability" link type="primary" @click="useSavedArtifact(true)">所在目录</el-button>
    </el-alert>
    <el-alert
      v-if="savedDeviceArtifactNotice"
      :title="savedDeviceArtifactNotice.title"
      :description="savedDeviceArtifactNotice.description"
      type="success"
      :closable="false"
      show-icon
      class="task-summary"
    />
    <el-alert
      v-if="batchRefresh"
      :title="batchRefresh.terminal ? '批量更新详情已结束' : '批量更新详情运行中'"
      :description="batchRefreshProgressText"
      :type="batchRefresh.terminal && (batchRefresh.summary.failed || batchRefresh.summary.rejected) ? 'warning' : batchRefresh.terminal ? 'success' : 'info'"
      :closable="false"
      show-icon
      class="task-summary"
    >
      <el-button link type="primary" @click="batchRefreshDetailsVisible = true">查看结果明细</el-button>
    </el-alert>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />
    <div v-loading="loading" class="content-card table-card" :data-state="isEmpty ? 'empty' : 'success'">
      <div class="device-table-host">
        <el-empty v-if="isEmpty" description="没有符合条件的设备" />
        <NcDataTable
          v-else
          ref="deviceTable"
          table-id="device-list"
          route-key="/devices"
          :data="pageData.items"
          :columns="deviceColumns"
          row-key="device_uuid"
          height="100%"
          empty-text="暂无设备"
          @selection-change="onSelectionChange"
          @row-dblclick="openDetail"
          @row-contextmenu="showContextMenu"
        >
          <template #cell-connection_status="{ row }"><el-tag :type="statusType(row.connection_status)">{{ statusLabel(row.connection_status) }}</el-tag></template>
          <template #cell-last_collect_status="{ row }"><el-tag :type="collectStatusType(row.last_collect_status)">{{ collectStatusLabel(row.last_collect_status) }}</el-tag></template>
          <template #cell-credential_status="{ row }">
            <el-tooltip :content="row.credential_message || '凭据字段已配置，不代表已成功登录'">
              <el-tag :type="row.credential_status === 'available' ? 'success' : row.credential_status === 'needs_reentry' ? 'warning' : 'danger'">
                {{ row.credential_status === 'available' ? '可用' : row.credential_status === 'needs_reentry' ? '需重新录入' : '缺失' }}
              </el-tag>
            </el-tooltip>
          </template>
          <template #cell-actions="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button><el-button link :disabled="!isFeatureEnabled('web.device_management_write')" @click="editRow(row)">编辑</el-button><el-button link type="danger" :disabled="!isFeatureEnabled('web.device_management_write')" @click="deleteRows([row.device_uuid])">删除</el-button></template>
        </NcDataTable>
      </div>
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

    <el-dialog v-model="batchRefreshDetailsVisible" title="批量更新详情结果" width="min(1080px, 94vw)">
      <p v-if="batchRefresh" class="batch-refresh-summary">{{ batchRefreshProgressText }}</p>
      <NcDataTable
        v-if="batchRefresh"
        table-id="device-batch-refresh-results"
        route-key="/devices/batch-refresh-results"
        :data="batchRefresh.items"
        :columns="batchRefreshColumns"
        row-key="device_uuid"
        height="420px"
        empty-text="暂无批次结果"
      >
        <template #cell-status="{ row }"><el-tag :type="collectStatusType(row.status)">{{ collectStatusLabel(row.status) }}</el-tag></template>
      </NcDataTable>
    </el-dialog>

    <el-dialog v-model="csvExportScopeVisible" title="确认设备导出范围" width="min(560px, 94vw)">
      <div class="export-scope-summary">
        <span>当前局点<strong>{{ pageData.site_name || '当前局点' }}</strong></span>
        <span>当前筛选结果<strong>{{ pageData.total }} 台</strong></span>
        <span>当前已选择<strong>{{ selectedUuids.length }} 台</strong></span>
      </div>
      <div class="export-scope-options" role="radiogroup" aria-label="导出范围">
        <button
          v-if="selectedUuids.length"
          data-testid="device-export-scope-selected"
          type="button"
          role="radio"
          :aria-checked="csvExportScope === 'selected'"
          :class="{ active: csvExportScope === 'selected' }"
          @click="csvExportScope = 'selected'"
        >
          <strong>已选择的 {{ selectedUuids.length }} 台</strong>
          <span>仅导出当前明确勾选的设备</span>
        </button>
        <button
          data-testid="device-export-scope-filtered-all"
          type="button"
          role="radio"
          :aria-checked="csvExportScope === 'filtered_all'"
          :class="{ active: csvExportScope === 'filtered_all' }"
          @click="csvExportScope = 'filtered_all'"
        >
          <strong>当前筛选结果全部 {{ pageData.total }} 台</strong>
          <span>跨页导出，不受当前页分页限制</span>
        </button>
      </div>
      <template #footer>
        <el-button @click="csvExportScopeVisible = false">取消</el-button>
        <el-button data-testid="confirm-device-export-scope" type="primary" :loading="csvExportSubmitting" @click="confirmCsvExportScope">选择保存位置</el-button>
      </template>
    </el-dialog>

    <div v-if="contextMenu.visible && contextMenu.row" class="device-context-menu" :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }" @click.stop>
      <button type="button" @click="openDetail(contextMenu.row); closeContextMenu()">详情</button>
      <button type="button" :disabled="!isFeatureEnabled('web.device_management_write')" @click="editRow(contextMenu.row); closeContextMenu()">编辑</button>
      <button type="button" :disabled="!isFeatureEnabled('web.device_management_write')" @click="duplicateRow(contextMenu.row); closeContextMenu()">复制设备</button>
      <button type="button" @click="copyCurrentCell(); closeContextMenu()">复制当前单元格</button>
      <button type="button" @click="copyText(contextMenu.row.name); closeContextMenu()">复制名称</button>
      <button type="button" @click="copyText(contextMenu.row.primary_address); closeContextMenu()">复制主地址</button>
      <button type="button" @click="copyText(contextMenu.row.backup_address); closeContextMenu()">复制备用地址</button>
      <button type="button" @click="copyText(contextMenu.row.system_name); closeContextMenu()">复制系统名</button>
      <button type="button" @click="copyText(contextMenu.row.station); closeContextMenu()">复制站点</button>
      <button type="button" @click="copyRow(contextMenu.row); closeContextMenu()">复制整行</button>
      <button type="button" @click="copyDeviceInfo(contextMenu.row); closeContextMenu()">复制设备信息</button>
      <button type="button" :disabled="!desktopHost || !isFeatureEnabled('web.device_management_desktop')" @click="requestTerminal(contextMenu.row.device_uuid); closeContextMenu()">外部终端</button>
      <button type="button" class="danger" :disabled="!isFeatureEnabled('web.device_management_write')" @click="deleteRows([contextMenu.row.device_uuid]); closeContextMenu()">删除</button>
    </div>

    <el-drawer v-model="detailVisible" title="设备详情" :size="detailDrawerWidth" :class="{ 'is-detail-drawer-dragging': detailDrawerDragging }" @closed="endDrawerResize">
      <div class="detail-drawer-resizer" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整设备详情宽度" :aria-valuenow="detailDrawerWidthPx || defaultDrawerWidth()" :aria-valuemin="drawerMinWidth()" :aria-valuemax="drawerMaxWidth()" @pointerdown="beginDrawerResize" @keydown="handleDrawerResizeKeydown" />
      <DeviceDetailPanel
        v-if="detailDeviceUuid"
        :device-uuid="detailDeviceUuid"
        mode="drawer"
        :connection-test="connectionTest"
        @full-detail="openFullDetail"
        @edit="openEdit"
        @terminal="requestTerminal"
      />
    </el-drawer>

    <el-dialog v-model="terminalLaunchVisible" title="选择外部终端" width="440px">
      <el-radio-group v-model="terminalSettings.terminal_type">
        <el-radio value="securecrt" :disabled="!terminalSettings.securecrt_path">SecureCRT</el-radio>
        <el-radio value="xshell" :disabled="!terminalSettings.xshell_path">Xshell</el-radio>
        <el-radio value="putty" :disabled="!terminalSettings.putty_path">PuTTY</el-radio>
      </el-radio-group>
      <p>将为 {{ terminalTargetUuids.length }} 台设备启动外部终端。</p>
      <template #footer><el-button @click="terminalLaunchVisible = false">取消</el-button><el-button type="primary" @click="launchTerminalTargets">启动</el-button></template>
    </el-dialog>

    <el-dialog v-model="terminalSettingsVisible" title="外部终端配置" width="min(760px, 94vw)">
      <div v-loading="terminalSettingsLoading">
        <el-alert title="程序路径只能通过 Electron 原生文件选择器设置；后端仅接受已存在的 SecureCRT.exe、Xshell.exe 或 putty.exe。" type="info" show-icon :closable="false" />
        <el-form label-width="140px" class="terminal-settings-form">
          <el-form-item label="默认终端"><el-select v-model="terminalSettings.terminal_type" style="width:100%"><el-option label="SecureCRT" value="securecrt" /><el-option label="Xshell" value="xshell" /><el-option label="PuTTY" value="putty" /></el-select></el-form-item>
          <el-form-item label="SecureCRT.exe"><el-input v-model="terminalSettings.securecrt_path" readonly><template #append><el-button @click="chooseTerminalExecutable('securecrt')">选择</el-button><el-button @click="terminalSettings.securecrt_path = ''">清空</el-button></template></el-input></el-form-item>
          <el-form-item label="Xshell.exe"><el-input v-model="terminalSettings.xshell_path" readonly><template #append><el-button @click="chooseTerminalExecutable('xshell')">选择</el-button><el-button @click="terminalSettings.xshell_path = ''">清空</el-button></template></el-input></el-form-item>
          <el-form-item label="putty.exe"><el-input v-model="terminalSettings.putty_path" readonly><template #append><el-button @click="chooseTerminalExecutable('putty')">选择</el-button><el-button @click="terminalSettings.putty_path = ''">清空</el-button></template></el-input></el-form-item>
          <el-form-item label="传递密码"><el-switch v-model="terminalSettings.pass_password" /><span class="field-warning">默认关闭；启用后密码可能进入外部程序进程参数。</span></el-form-item>
        </el-form>
      </div>
      <template #footer><el-button @click="terminalSettingsVisible = false">取消</el-button><el-button type="primary" :loading="terminalSettingsLoading" @click="saveTerminalSettings">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="writeVisible" :title="writeMode === 'create' ? '新建设备' : '编辑设备'" width="min(1120px, 96vw)" top="4vh" @closed="closeWriteDialog">
      <el-alert :title="writeMode === 'edit' ? '秘密字段留空会保留原值；点击眼睛可在本机桌面端查看已保存值；输入新值会替换；勾选清除才会删除。' : '秘密字段只用于当前设备保存和后续连接。'" type="info" show-icon :closable="false" />
      <el-alert
        v-if="writeMode === 'edit' && detail?.credential_status === 'needs_reentry'"
        title="该设备凭据来自局点包，请在当前电脑重新录入用户名和密码后保存。"
        type="warning"
        show-icon
        :closable="false"
        class="state-alert"
      />
      <el-alert v-if="writeConnectionTest" :title="`${writeConnectionTest.protocol || writeTestProtocol} · ${writeConnectionTest.task_status} · ${writeConnectionTest.safe_message || writeConnectionTest.message || '等待结果'}`" :type="writeConnectionTest.success === true ? 'success' : writeConnectionTest.success === false || writeConnectionTest.task_status === 'FAILED' ? 'error' : 'info'" :description="`Task ID: ${writeConnectionTest.task_id}${writeConnectionTest.failure_category ? `；分类：${writeConnectionTest.failure_category}` : ''}${writeConnectionTest.elapsed_ms != null ? `；耗时：${writeConnectionTest.elapsed_ms} ms` : ''}${writeConnectionTest.suggestion ? `；建议：${writeConnectionTest.suggestion}` : ''}`" show-icon :closable="false" />
      <el-form label-width="118px" class="device-write-form">
        <div class="form-grid">
          <section class="form-section"><h3>基础信息</h3>
            <el-form-item label="设备名称 *"><el-input v-model="writeForm.name" data-testid="device-name" /></el-form-item>
            <el-form-item label="系统名"><el-input v-model="writeForm.system_name" /></el-form-item>
            <el-form-item label="分组"><el-select v-model="writeForm.group_id" clearable style="width:100%"><el-option v-for="group in pageData.groups" :key="group.id" :label="group.name" :value="group.id" /></el-select></el-form-item>
            <el-form-item label="厂商"><el-select v-model="writeForm.device_vendor" style="width:100%"><el-option v-for="vendor in DEVICE_VENDOR_OPTIONS" :key="vendor.value" :label="vendor.label" :value="vendor.value" /></el-select></el-form-item>
            <el-form-item label="类型"><el-select v-model="writeForm.device_type" style="width:100%"><el-option v-for="type in DEVICE_TYPE_OPTIONS" :key="type" :label="type" :value="type" /></el-select></el-form-item>
            <el-form-item label="站点"><el-input v-model="writeForm.station" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="writeForm.remark" type="textarea" :rows="3" /></el-form-item>
          </section>
          <section class="form-section"><h3>连接</h3>
            <el-form-item label="主地址 *"><el-input v-model="writeForm.primary_address" data-testid="device-address" /></el-form-item>
            <el-form-item label="备用地址"><el-input v-model="writeForm.backup_address" /></el-form-item>
            <el-form-item label="SSH"><el-checkbox v-model="writeForm.ssh_enabled" data-testid="ssh-enabled">启用</el-checkbox><el-input-number v-model="writeForm.ssh_port" data-testid="ssh-port" :min="1" :max="65535" controls-position="right" /></el-form-item>
            <el-form-item label="Telnet"><el-checkbox v-model="writeForm.telnet_enabled">启用</el-checkbox><el-input-number v-model="writeForm.telnet_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
          </section>
          <section class="form-section"><h3>SSH 认证</h3>
            <el-form-item label="用户名"><el-input v-model="writeForm.ssh_username" data-testid="ssh-username" autocomplete="off" /></el-form-item>
            <el-form-item label="密码"><el-input v-model="writeForm.ssh_password" data-testid="ssh-password" :type="secretVisible.ssh_password ? 'text' : 'password'" autocomplete="new-password" :disabled="secretClears.ssh_password" :placeholder="writeMode === 'edit' && detail?.ssh_secret_configured ? '已配置；留空保留' : ''"><template #suffix><el-button data-testid="ssh-reveal" link :icon="secretVisible.ssh_password ? Hide : View" :loading="secretRevealLoading.ssh_password" aria-label="查看或隐藏 SSH 密码" @click="toggleSecretVisibility('ssh_password')" /></template></el-input><el-checkbox v-if="writeMode === 'edit' && detail?.ssh_secret_configured" data-testid="ssh-clear" :model-value="secretClears.ssh_password" @change="setSecretCleared('ssh_password', Boolean($event))">清除已保存值</el-checkbox></el-form-item>
          </section>
          <section class="form-section"><h3>Telnet 认证</h3>
            <el-form-item label="用户名"><el-input v-model="writeForm.telnet_username" autocomplete="off" /></el-form-item>
            <el-form-item label="密码"><el-input v-model="writeForm.telnet_password" :type="secretVisible.telnet_password ? 'text' : 'password'" autocomplete="new-password" :disabled="secretClears.telnet_password" :placeholder="writeMode === 'edit' && detail?.telnet_secret_configured ? '已配置；留空保留' : ''"><template #suffix><el-button link :icon="secretVisible.telnet_password ? Hide : View" :loading="secretRevealLoading.telnet_password" aria-label="查看或隐藏 Telnet 密码" @click="toggleSecretVisibility('telnet_password')" /></template></el-input><el-checkbox v-if="writeMode === 'edit' && detail?.telnet_secret_configured" :model-value="secretClears.telnet_password" @change="setSecretCleared('telnet_password', Boolean($event))">清除已保存值</el-checkbox></el-form-item>
          </section>
        </div>

        <section class="form-section full-width"><h3>SSH 隧道</h3><div class="form-grid two-columns">
          <div><h4>第一跳</h4><el-form-item label="主机"><el-input v-model="writeForm.tunnel1_host" /></el-form-item><el-form-item label="端口"><el-input-number v-model="writeForm.tunnel1_port" :min="1" :max="65535" /></el-form-item><el-form-item label="用户名"><el-input v-model="writeForm.tunnel1_username" /></el-form-item><el-form-item label="密码"><el-input v-model="writeForm.tunnel1_password" :type="secretVisible.tunnel1_password ? 'text' : 'password'" autocomplete="new-password" :disabled="secretClears.tunnel1_password" :placeholder="writeMode === 'edit' && detail?.tunnel1_secret_configured ? '已配置；留空保留' : ''"><template #suffix><el-button link :icon="secretVisible.tunnel1_password ? Hide : View" :loading="secretRevealLoading.tunnel1_password" aria-label="查看或隐藏第一跳密码" @click="toggleSecretVisibility('tunnel1_password')" /></template></el-input><el-checkbox v-if="writeMode === 'edit' && detail?.tunnel1_secret_configured" :model-value="secretClears.tunnel1_password" @change="setSecretCleared('tunnel1_password', Boolean($event))">清除已保存值</el-checkbox></el-form-item></div>
          <div><h4>第二跳</h4><el-form-item label="主机"><el-input v-model="writeForm.tunnel2_host" /></el-form-item><el-form-item label="端口"><el-input-number v-model="writeForm.tunnel2_port" :min="1" :max="65535" /></el-form-item><el-form-item label="用户名"><el-input v-model="writeForm.tunnel2_username" /></el-form-item><el-form-item label="密码"><el-input v-model="writeForm.tunnel2_password" :type="secretVisible.tunnel2_password ? 'text' : 'password'" autocomplete="new-password" :disabled="secretClears.tunnel2_password" :placeholder="writeMode === 'edit' && detail?.tunnel2_secret_configured ? '已配置；留空保留' : ''"><template #suffix><el-button link :icon="secretVisible.tunnel2_password ? Hide : View" :loading="secretRevealLoading.tunnel2_password" aria-label="查看或隐藏第二跳密码" @click="toggleSecretVisibility('tunnel2_password')" /></template></el-input><el-checkbox v-if="writeMode === 'edit' && detail?.tunnel2_secret_configured" :model-value="secretClears.tunnel2_password" @change="setSecretCleared('tunnel2_password', Boolean($event))">清除已保存值</el-checkbox></el-form-item></div>
        </div></section>

        <section class="form-section full-width"><h3>SNMP</h3><div class="form-grid two-columns">
          <div>
            <el-form-item label="启用"><el-checkbox v-model="writeForm.snmp_enabled">SNMP</el-checkbox><el-checkbox v-model="writeForm.snmp_v1_enabled">v1</el-checkbox><el-checkbox v-model="writeForm.snmp_v2c_enabled">v2c</el-checkbox></el-form-item>
            <el-form-item label="端口"><el-input-number v-model="writeForm.snmp_port" :min="1" :max="65535" /></el-form-item>
            <el-form-item label="超时(ms)"><el-input-number v-model="writeForm.snmp_timeout_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item label="重试"><el-input-number v-model="writeForm.snmp_retries" :min="0" :max="10" /></el-form-item>
            <el-form-item label="只读团体字"><el-input v-model="writeForm.snmp_ro_community" :type="secretVisible.snmp_ro_community ? 'text' : 'password'" autocomplete="new-password" :disabled="secretClears.snmp_ro_community" :placeholder="writeMode === 'edit' && detail?.snmp_ro_secret_configured ? '已配置；留空保留' : ''"><template #suffix><el-button link :icon="secretVisible.snmp_ro_community ? Hide : View" :loading="secretRevealLoading.snmp_ro_community" aria-label="查看或隐藏 SNMP 团体字" @click="toggleSecretVisibility('snmp_ro_community')" /></template></el-input><el-checkbox v-if="writeMode === 'edit' && detail?.snmp_ro_secret_configured" :model-value="secretClears.snmp_ro_community" @change="setSecretCleared('snmp_ro_community', Boolean($event))">清除已保存值</el-checkbox></el-form-item>
          </div>
        </div></section>
      </el-form>
      <template #footer><div class="write-footer"><div class="write-test-actions"><el-select v-model="writeTestProtocol" style="width:120px"><el-option v-for="protocol in availableWriteTestProtocols" :key="protocol" :label="protocol" :value="protocol" /></el-select><el-tooltip :content="writeConnectionDisabledReason" :disabled="!writeConnectionDisabledReason"><span><el-button data-testid="form-connection-test" :icon="Connection" :loading="writeConnectionBusy" :disabled="!!writeConnectionDisabledReason" @click="testWriteConnection">测试表单连接</el-button></span></el-tooltip><span v-if="writeConnectionDisabledReason && !writeConnectionBusy" data-testid="form-connection-disabled-reason" class="field-warning">{{ writeConnectionDisabledReason }}</span><el-button v-if="writeConnectionTest" data-testid="form-connection-task" plain @click="openWriteConnectionTestTask">打开任务中心</el-button></div><div><el-button data-testid="device-form-cancel" @click="cancelWriteDialog">取消</el-button><el-button data-testid="device-save" type="primary" :loading="writeLoading" :disabled="editingProfileLoading || !isFeatureEnabled('web.device_management_write')" @click="saveWrite">保存</el-button></div></div></template>
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
      <div v-if="importPreview" class="import-summary">
        <p>{{ importPreview.source_name }} · 编码 {{ importPreview.detected_encoding }} · SHA-256 {{ importPreview.source_sha256 }}</p>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="总行数">{{ importPreview.total_rows }}</el-descriptions-item>
          <el-descriptions-item label="有效">{{ importPreview.valid_rows }}</el-descriptions-item>
          <el-descriptions-item label="无效">{{ importPreview.invalid_rows }}</el-descriptions-item>
          <el-descriptions-item label="新华三 H3C">{{ importPreview.vendor_summary.H3C || 0 }}</el-descriptions-item>
          <el-descriptions-item label="中兴 ZTE">{{ importPreview.vendor_summary.ZTE || 0 }}</el-descriptions-item>
          <el-descriptions-item label="新增 / 更新">{{ importPreview.create_count }} / {{ importPreview.update_count }}</el-descriptions-item>
        </el-descriptions>
        <NcDataTable
          v-if="importPreview.errors.length"
          table-id="device-import-errors"
          route-key="/devices/import-preview"
          :data="importPreview.errors"
          :columns="importErrorColumns"
          row-key="line"
          :max-height="240"
          empty-text="没有导入错误"
        />
        <el-alert v-for="item in importPreview.warnings" :key="item" :title="item" type="warning" :closable="false" />
        <el-form-item v-if="importPreview.duplicate_rows.length" label="重复地址"><el-select v-model="importDuplicateStrategy" style="width:100%"><el-option label="拒绝导入（安全默认）" value="reject" /><el-option label="跳过重复行" value="skip" /><el-option label="仍新增为独立设备" value="create_new" /></el-select><span class="field-warning">涉及 CSV 行：{{ importPreview.duplicate_rows.join('、') }}</span></el-form-item>
      </div>
      <template #footer><el-button @click="closeImportDialog">关闭</el-button><el-button :loading="importLoading" :disabled="!importFile || !isFeatureEnabled('web.device_management_import')" @click="runImportPreview">预览</el-button><el-button type="primary" :disabled="!importPreview || !!importPreview.errors.length || !isFeatureEnabled('web.device_management_import')" @click="confirmImport">确认导入</el-button></template>
    </el-dialog>

    <el-dialog v-model="secureCrtVisible" title="生成 SecureCRT 会话" width="min(560px, 94vw)">
      <el-alert title="默认使用内置会话配置；也可以选择现有 SecureCRT .ini 作为模板。" type="info" show-icon :closable="false" />
      <input ref="secureCrtTemplateInput" class="visually-hidden" type="file" accept=".ini" @change="onSecureCrtTemplateChange" />
      <div class="import-file-picker"><el-button @click="chooseSecureCrtTemplate">选择可选模板</el-button><span>{{ secureCrtTemplateFile?.name || '使用内置模板' }}</span><el-button v-if="secureCrtTemplateFile" link @click="secureCrtTemplateFile = null">清除</el-button></div>
      <template #footer><el-button @click="secureCrtVisible = false">取消</el-button><el-button type="primary" @click="exportSecureCrt">生成会话</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.device-management { display: flex; width: 100%; height: 100%; max-width: none; min-width: 0; min-height: 0; flex-direction: column; margin: 0; overflow: hidden; }
.page-heading, .detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.heading-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.group-list { margin-top: 16px; max-height: 260px; overflow-y: auto; }
.group-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.page-heading h1, .detail-heading h2, .detail-section h3 { margin: 0; }
.page-heading p, .detail-heading p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 13px; }
.filters { display: grid; grid-template-columns: minmax(240px, 2fr) repeat(6, minmax(120px, 1fr)) auto; gap: 10px; padding: 14px; margin-bottom: 14px; }
.state-alert { margin-bottom: 14px; }
.action-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; margin-bottom: 14px; }
.action-bar > span { margin-right: 4px; color: var(--nc-text-secondary); font-size: 13px; }
.task-summary { margin-bottom: 14px; }
.export-scope-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.export-scope-summary span { display: grid; gap: 4px; color: var(--nc-text-secondary); font-size: 13px; }
.export-scope-summary strong { color: var(--nc-text-primary); font-size: 15px; }
.export-scope-options { display: grid; gap: 8px; }
.export-scope-options button { display: grid; gap: 4px; width: 100%; min-height: 62px; padding: 10px 12px; border: 1px solid var(--nc-border); border-radius: 6px; background: var(--nc-surface); color: var(--nc-text-primary); text-align: left; cursor: pointer; }
.export-scope-options button.active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); box-shadow: inset 3px 0 0 var(--el-color-primary); }
.export-scope-options button span { color: var(--nc-text-secondary); font-size: 13px; }
.table-card { display: flex; min-height: 0; flex: 1; flex-direction: column; padding: 0 0 12px; overflow: hidden; }
.device-table-host { display: flex; min-height: 0; flex: 1; flex-direction: column; overflow: hidden; }
.device-table-host > .el-empty { flex: 1; }
.table-card :deep(.el-pagination) { justify-content: flex-end; padding: 14px 16px 0; }
.table-card strong, .table-card small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-card small { margin-top: 4px; color: var(--nc-text-tertiary); }
.detail-body { min-height: 240px; }
.detail-drawer-resizer { position: absolute; z-index: 2; top: 0; bottom: 0; left: 0; width: 8px; cursor: col-resize; }
.detail-drawer-resizer:hover { background: var(--el-color-primary-light-8); }
.is-detail-drawer-dragging, .is-detail-drawer-dragging * { user-select: none; }
.detail-section { margin-top: 22px; }
.detail-section h3 { margin-bottom: 11px; font-size: 15px; }
.action-row { display: flex; flex-wrap: wrap; gap: 9px; margin-bottom: 12px; }
.command-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 12px; background: var(--nc-bg-muted); border-radius: 7px; }
.command-row + .command-row { margin-top: 8px; }
.command-row code { overflow-wrap: anywhere; }
.device-write-form { max-height: 70vh; padding: 18px 4px 0; overflow-y: auto; }
.write-footer, .write-test-actions { display: flex; align-items: center; gap: 8px; }
.write-footer { justify-content: space-between; flex-wrap: wrap; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.form-grid.two-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-section { padding: 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
.form-section.full-width { margin-top: 14px; }
.form-section h3, .form-section h4 { margin: 0 0 14px; }
.terminal-settings-form { margin-top: 18px; }
.field-warning { margin-left: 10px; color: var(--el-color-warning); font-size: 12px; }
.device-context-menu { position: fixed; z-index: 5000; display: flex; min-width: 170px; padding: 6px; flex-direction: column; background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color); border-radius: 7px; box-shadow: var(--el-box-shadow-light); }
.device-context-menu button { padding: 8px 12px; color: var(--el-text-color-primary); text-align: left; background: transparent; border: 0; border-radius: 4px; cursor: pointer; }
.device-context-menu button:hover:not(:disabled) { background: var(--el-fill-color-light); }
.device-context-menu button.danger { color: var(--el-color-danger); }
.device-context-menu button:disabled { color: var(--el-text-color-disabled); cursor: not-allowed; }
.import-summary { margin-top: 16px; overflow-wrap: anywhere; }
.import-file-picker { display: flex; align-items: center; gap: 12px; margin-top: 18px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 1280px) { .filters { grid-template-columns: repeat(3, minmax(150px, 1fr)); } }
@media (max-width: 760px) { .device-management { height: auto; min-height: 100%; overflow: visible; } .table-card { min-height: 55dvh; flex: none; } .filters, .form-grid, .form-grid.two-columns, .export-scope-summary { grid-template-columns: 1fr; } .page-heading { align-items: flex-start; } }
</style>
