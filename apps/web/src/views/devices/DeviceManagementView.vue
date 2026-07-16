<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { TableInstance } from 'element-plus'
import { Connection, CopyDocument, Delete, Download, Edit, FolderOpened, Plus, Refresh, Upload, View } from '@element-plus/icons-vue'

import { isFeatureEnabled } from '../../features'
import {
  cancelDeviceTask,
  deviceExportDownloadRequest,
  getDevice,
  getDeviceConnectionTest,
  getDeviceHistory,
  getDeviceTask,
  getExternalTerminalSettings,
  issueExternalTerminalConfirmation,
  getOmniPeekPreview,
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
  launchExternalTerminals,
  renameDeviceGroup,
  startBatchRefreshDetails,
  startBatchConnectionTests,
  startDeviceCsvExport,
  startDeviceConnectionTest,
  startDeviceDiagnosticDownload,
  startDeviceOpticalRefresh,
  startDeviceTemplateExport,
  startOmniPeekExport,
  startOmniPeekPreview,
  startSecureCrtExport,
  startSecureCrtExportWithTemplate,
  updateDevice,
  updateExternalTerminalSettings,
} from '../../api/deviceManagement'
import { downloadBackendResource, getPlatformAdapter, getRuntimeConfig } from '../../platform/runtime'
import type {
  DeviceConnectionProtocol,
  DeviceConnectionStatus,
  DeviceConnectionTest,
  DeviceDetailResponse,
  DeviceEditPreview,
  DeviceEditPreviewRequest,
  DeviceExportRequest,
  DeviceExternalTerminalSettings,
  DeviceImportPreview,
  DeviceHistoryPage,
  DeviceListItem,
  DeviceOmniPeekPreview,
  DeviceOmniPeekPreviewItem,
  DevicePage,
  DeviceTaskReference,
  DeviceWriteRequest,
} from '../../types/deviceManagement'

const emptyPage = (): DevicePage => ({ items: [], groups: [], total: 0, page: 1, page_size: 50, total_pages: 1 })
const loading = ref(false)
const error = ref('')
const pageData = ref<DevicePage>(emptyPage())
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref<DeviceDetailResponse | null>(null)
const detailTab = ref('overview')
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyPage = ref<DeviceHistoryPage | null>(null)
const connectionTest = ref<DeviceConnectionTest | null>(null)
const connectionLoading = ref(false)
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewResult = ref<DeviceEditPreview | null>(null)
const writeVisible = ref(false)
const writeMode = ref<'create' | 'edit'>('create')
const writeLoading = ref(false)
const selectedUuids = ref<string[]>([])
const deviceTable = ref<TableInstance>()
const groupVisible = ref(false)
const groupName = ref('')
const groupAssignVisible = ref(false)
const groupAssignId = ref<number | null>(null)
const importVisible = ref(false)
const importFile = ref<File | null>(null)
const importFileInput = ref<HTMLInputElement | null>(null)
const importLoading = ref(false)
const importPreview = ref<DeviceImportPreview | null>(null)
const secureCrtVisible = ref(false)
const secureCrtTemplateFile = ref<File | null>(null)
const secureCrtTemplateInput = ref<HTMLInputElement | null>(null)
const omniPeekVisible = ref(false)
const omniPeekLoading = ref(false)
const omniPeekLineName = ref('NetConsole')
const omniPeekPreview = ref<DeviceOmniPeekPreview | null>(null)
const omniPeekSelectedKeys = ref<string[]>([])
const omniPeekForceKeys = ref<string[]>([])
const omniPeekTable = ref<TableInstance>()
const trackedTasks = ref<DeviceTaskReference[]>([])
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
  vendor: '',
  device_type: '',
  connection_status: '' as DeviceConnectionStatus | '',
  sort_by: 'name',
  sort_order: 'asc' as 'asc' | 'desc',
  page: 1,
  page_size: 50,
})
const editForm = reactive<DeviceEditPreviewRequest>({ name: '', primary_address: '' })
const writeForm = reactive<DeviceWriteRequest>({ name: '', primary_address: '', ssh_enabled: true, ssh_port: 22, telnet_enabled: false, telnet_port: 23, snmp_enabled: true, snmp_v2c_enabled: true, snmp_port: 161 })
const contextMenu = reactive<{ visible: boolean; x: number; y: number; row: DeviceListItem | null; cellValue: string }>({ visible: false, x: 0, y: 0, row: null, cellValue: '' })
let pollTimer: number | undefined
let taskPollTimer: number | undefined
let omniPeekPollGeneration = 0
let componentActive = true
const taskStorageKey = 'netconsole.device-management.task-ids'

const isEmpty = computed(() => !loading.value && !error.value && pageData.value.items.length === 0)
const testTerminal = computed(() => connectionTest.value && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(connectionTest.value.task_status))
const testActive = computed(() => Boolean(connectionTest.value && !testTerminal.value))
const desktopHost = computed(() => getRuntimeConfig().hostType === 'electron')
const historyColumns = computed(() => {
  const kind = historyPage.value?.kind
  if (kind === 'interface') return [
    ['采集时间', 'collected_at'], ['接口', 'interface_name'], ['链路', 'link_status'], ['协议', 'protocol_status'], ['速率', 'speed'], ['双工', 'duplex'], ['类型', 'interface_type'], ['端口状态', 'port_status'], ['PVID', 'pvid'], ['描述', 'description'], ['接口 IP', 'ip_address'], ['MAC', 'mac_address'], ['VLAN', 'vlan'],
  ]
  if (kind === 'optical') return [
    ['采集时间', 'collected_at'], ['接口', 'interface_name'], ['接收功率', 'rx_power'], ['发送功率', 'tx_power'], ['温度', 'temperature'], ['电压', 'voltage'], ['偏置电流', 'bias_current'], ['模块型号', 'module_model'], ['序列号', 'module_serial_number'], ['厂商', 'module_vendor'], ['波长', 'wavelength'], ['传输距离', 'transmission_distance'], ['状态', 'status'],
  ]
  return [['采集时间', 'collected_at'], ['本地接口', 'local_interface'], ['邻居系统名', 'neighbor_sysname'], ['邻居 MAC', 'neighbor_mac'], ['邻居接口', 'neighbor_interface']]
})

onMounted(async () => {
  document.addEventListener('click', closeContextMenu)
  await loadDevices()
  await restoreTrackedTasks()
  await restoreConnectionTest()
})

onBeforeUnmount(() => {
  componentActive = false
  omniPeekPollGeneration += 1
  document.removeEventListener('click', closeContextMenu)
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
      vendor: filters.vendor,
      connection_status: filters.connection_status,
      page: filters.page,
      page_size: filters.page_size,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    })
    filters.page = pageData.value.page
    selectedUuids.value = []
    await nextTick()
    deviceTable.value?.clearSelection()
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
  if (['batch_refresh_details', 'diagnostic_download', 'optical_refresh'].includes(task.action)) {
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
  const succeeded = restored.flatMap((result) => result.status === 'fulfilled' ? [result.value] : [])
  const failedIds = taskIds.filter((_taskId, index) => restored[index]?.status === 'rejected')
  trackTasks(succeeded)
  if (failedIds.length) {
    try {
      const retained = [...new Set([
        ...trackedTasks.value.map((task) => task.task_id),
        ...failedIds,
      ])].slice(0, 30)
      window.sessionStorage.setItem(taskStorageKey, JSON.stringify(retained))
    } catch {
      // 瞬时恢复失败不影响当前页面；下次进入页面仍会重试现有任务。
    }
  }
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

async function downloadTrackedTask(task: DeviceTaskReference): Promise<void> {
  if (!task.available || !task.artifact_id) return
  const names: Record<string, string> = {
    export_csv: '设备清单.csv',
    export_template: '设备导入模板.csv',
    securecrt_sessions: 'SecureCRT会话.zip',
    omnipeek_name_table: 'OmniPeek名称表.nam',
    diagnostic_download: '设备诊断信息.zip',
  }
  const result = await downloadBackendResource(
    deviceExportDownloadRequest(task.task_id, task.artifact_id, names[task.action] || '设备管理导出.zip'),
  )
  if (result.status === 'failed') ElMessage.error(result.error || '设备导出下载失败')
}

function currentDeviceWriteValues(): DeviceWriteRequest | null {
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
    ssh_username: device.ssh_username,
    ssh_password: '',
    telnet_enabled: device.capabilities.telnet,
    telnet_port: device.capabilities.telnet_port || 23,
    telnet_username: device.telnet_username,
    telnet_password: '',
    tunnel_enabled: device.tunnel_enabled,
    tunnel1_enabled: device.tunnel1_enabled,
    tunnel1_host: device.tunnel1_host,
    tunnel1_port: device.tunnel1_port || 22,
    tunnel1_username: device.tunnel1_username,
    tunnel1_password: '',
    tunnel2_enabled: device.tunnel2_enabled,
    tunnel2_host: device.tunnel2_host,
    tunnel2_port: device.tunnel2_port || 22,
    tunnel2_username: device.tunnel2_username,
    tunnel2_password: '',
    snmp_enabled: device.capabilities.snmp,
    snmp_v1_enabled: device.snmp_v1_enabled,
    snmp_v2c_enabled: device.snmp_v2c_enabled,
    snmp_v3_enabled: device.snmp_v3_enabled,
    snmp_port: device.capabilities.snmp_port || 161,
    snmp_ro_community: '',
    snmp_rw_community: '',
    snmpv3_username: device.snmpv3_username,
    snmpv3_security_level: device.snmpv3_security_level,
    snmpv3_auth_protocol: device.snmpv3_auth_protocol,
    snmpv3_auth_password: '',
    snmpv3_priv_protocol: device.snmpv3_priv_protocol,
    snmpv3_priv_password: '',
    snmp_context_name: device.snmp_context_name,
    snmp_timeout_ms: device.snmp_timeout_ms,
    snmp_retries: device.snmp_retries,
    https_port: device.https_port,
    remark: device.remark,
  }
}

async function openHistory(kind: 'interface' | 'optical' | 'lldp', objectName: string): Promise<void> {
  if (!detail.value || !objectName) return
  historyVisible.value = true
  historyLoading.value = true
  historyPage.value = null
  try {
    historyPage.value = await getDeviceHistory(detail.value.device.device_uuid, kind, objectName)
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设备历史加载失败'))
  } finally {
    historyLoading.value = false
  }
}

async function refreshDetailData(): Promise<void> {
  if (!detail.value) return
  try {
    const result = await startBatchRefreshDetails([detail.value.device.device_uuid])
    trackTasks(result.tasks)
    ElMessage.success('设备详情刷新任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设备详情刷新失败'))
  }
}

async function refreshOpticalData(): Promise<void> {
  if (!detail.value) return
  try {
    trackTasks([await startDeviceOpticalRefresh(detail.value.device.device_uuid)])
    ElMessage.success('设备光模块刷新任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设备光模块刷新失败'))
  }
}

function currentDevicePreviewValues(): DeviceEditPreviewRequest | null {
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
    snmp_v1_enabled: device.snmp_v1_enabled,
    snmp_v2c_enabled: device.snmp_v2c_enabled,
    snmp_v3_enabled: device.snmp_v3_enabled,
    snmp_port: device.capabilities.snmp_port || 161,
    https_port: device.https_port,
    remark: device.remark,
  }
}

function openPreview(): void {
  const values = currentDevicePreviewValues()
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
  writeMode.value = 'create'
  Object.assign(writeForm, {
    name: '', system_name: '', station: '', location: '', group_id: null, device_vendor: 'H3C', device_type: 'SW', primary_address: '', backup_address: '',
    ssh_enabled: true, ssh_port: 22, ssh_username: '', ssh_password: '', telnet_enabled: false, telnet_port: 23, telnet_username: '', telnet_password: '',
    tunnel_enabled: false, tunnel1_enabled: false, tunnel1_host: '', tunnel1_port: 22, tunnel1_username: '', tunnel1_password: '', tunnel2_enabled: false, tunnel2_host: '', tunnel2_port: 22, tunnel2_username: '', tunnel2_password: '',
    snmp_enabled: true, snmp_v1_enabled: false, snmp_v2c_enabled: true, snmp_v3_enabled: false, snmp_port: 161, snmp_ro_community: '', snmp_rw_community: '',
    snmpv3_username: '', snmpv3_security_level: 'noAuthNoPriv', snmpv3_auth_protocol: 'SHA', snmpv3_auth_password: '', snmpv3_priv_protocol: 'AES128', snmpv3_priv_password: '', snmp_context_name: '', snmp_timeout_ms: 2000, snmp_retries: 1,
    https_port: null, remark: '',
  })
  writeVisible.value = true
}

function openEdit(): void {
  const values = currentDeviceWriteValues()
  if (!values) return
  writeMode.value = 'edit'
  Object.assign(writeForm, values)
  writeVisible.value = true
}

function clearWriteSecrets(): void {
  Object.assign(writeForm, {
    ssh_password: '',
    telnet_password: '',
    tunnel1_password: '',
    tunnel2_password: '',
    snmp_ro_community: '',
    snmp_rw_community: '',
    snmpv3_auth_password: '',
    snmpv3_priv_password: '',
  })
}

async function saveWrite(): Promise<void> {
  writeLoading.value = true
  try {
    if (writeMode.value === 'create') await createDevice({ ...writeForm })
    else if (detail.value) await updateDevice(detail.value.device.device_uuid, { ...writeForm })
    writeVisible.value = false
    clearWriteSecrets()
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
  await duplicateByUuid(uuid)
}

async function deleteRows(deviceUuids: string[]): Promise<void> {
  if (!deviceUuids.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除 ${deviceUuids.length} 台设备？删除后设备将从当前局点数据库移除。`,
      '删除设备',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
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
    await ElMessageBox.confirm(
      '将复制当前设备及其已配置凭据，并生成新的设备 UUID。是否继续？',
      '复制设备',
      { confirmButtonText: '确认复制', cancelButtonText: '取消', type: 'warning' },
    )
    await duplicateDevice(deviceUuid)
    ElMessage.success('设备已复制')
    await loadDevices(true)
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(errorMessage(cause, '复制设备失败'))
  }
}

async function editRow(row: DeviceListItem): Promise<void> {
  await openDetail(row)
  if (detail.value) openEdit()
}

async function deleteSelected(): Promise<void> {
  await deleteRows(selectedUuids.value)
}

async function startSelectedConnectionTests(): Promise<void> {
  if (!selectedUuids.value.length) return
  try {
    const result = await startBatchConnectionTests(selectedUuids.value)
    trackTasks(result.tasks)
    ElMessage.success(`已提交 ${result.tasks.length} 个连接测试任务`)
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

function currentExportFilters(includeCredentials = false): DeviceExportRequest {
  return {
    device_uuids: selectedUuids.value,
    search: filters.search,
    vendor: filters.vendor,
    device_type: filters.device_type,
    group_filter: filters.group === 'ungrouped' ? '__ungrouped__' : filters.group ? Number(filters.group) : undefined,
    include_credentials: includeCredentials,
  }
}

async function exportCsv(includeCredentials = false): Promise<void> {
  try {
    if (includeCredentials) {
      await ElMessageBox.confirm(
        '导出文件将包含设备登录凭据。请仅保存到受控目录并妥善保管，是否继续？',
        '导出含凭据的 CSV',
        { confirmButtonText: '确认导出', cancelButtonText: '取消', type: 'warning' },
      )
    }
    trackTasks([await startDeviceCsvExport(currentExportFilters(includeCredentials))])
    ElMessage.success('CSV 导出任务已提交')
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
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
    trackTasks([task])
    secureCrtVisible.value = false
    ElMessage.success('SecureCRT 会话任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'SecureCRT 会话生成失败'))
  }
}

async function openOmniPeekExport(): Promise<void> {
  const generation = ++omniPeekPollGeneration
  const deadline = Date.now() + 120_000
  omniPeekVisible.value = true
  omniPeekLoading.value = true
  omniPeekPreview.value = null
  omniPeekSelectedKeys.value = []
  omniPeekForceKeys.value = []
  try {
    const task = await startOmniPeekPreview(currentExportFilters())
    trackTasks([task])
    for (;;) {
      if (!componentActive || generation !== omniPeekPollGeneration || !omniPeekVisible.value) return
      if (Date.now() >= deadline) {
        try {
          await cancelDeviceTask(task.task_id)
        } catch {
          // 超时错误仍由当前预览操作统一呈现。
        }
        throw new Error('OmniPeek 预览超过 120 秒，任务已请求取消')
      }
      const preview = await getOmniPeekPreview(task.task_id)
      if (!componentActive || generation !== omniPeekPollGeneration || !omniPeekVisible.value) return
      if (preview.ready) {
        omniPeekPreview.value = preview
        omniPeekSelectedKeys.value = preview.items.filter((item) => item.selected).map((item) => item.key)
        omniPeekForceKeys.value = preview.items.filter((item) => item.force_export).map((item) => item.key)
        await nextTick()
        for (const item of preview.items) {
          if (omniPeekSelectedKeys.value.includes(item.key)) omniPeekTable.value?.toggleRowSelection(item, true)
        }
        if (!preview.items.length) ElMessage.warning('当前筛选或勾选设备中没有可导出的车载 MR')
        break
      }
      if (['FAILED', 'CANCELLED'].includes(preview.task_status)) throw new Error(preview.message || 'OmniPeek 预览失败')
      await new Promise((resolve) => window.setTimeout(resolve, 500))
    }
  } catch (cause) {
    if (componentActive && generation === omniPeekPollGeneration) {
      ElMessage.error(errorMessage(cause, 'OmniPeek 名称表预览失败'))
    }
  } finally {
    if (generation === omniPeekPollGeneration) omniPeekLoading.value = false
  }
}

function stopOmniPeekPreview(): void {
  omniPeekPollGeneration += 1
  omniPeekLoading.value = false
}

function onOmniPeekSelectionChange(rows: DeviceOmniPeekPreviewItem[]): void {
  omniPeekSelectedKeys.value = rows.map((row) => row.key)
  omniPeekForceKeys.value = omniPeekForceKeys.value.filter((key) => omniPeekSelectedKeys.value.includes(key))
}

function setOmniPeekForce(key: string, enabled: boolean): void {
  omniPeekForceKeys.value = enabled
    ? [...new Set([...omniPeekForceKeys.value, key])]
    : omniPeekForceKeys.value.filter((value) => value !== key)
}

async function exportOmniPeek(): Promise<void> {
  if (!omniPeekPreview.value || !omniPeekSelectedKeys.value.length) {
    ElMessage.warning('请至少选择一条名称记录')
    return
  }
  try {
    const selected = new Set(omniPeekSelectedKeys.value)
    trackTasks([await startOmniPeekExport({
      ...currentExportFilters(),
      line_name: omniPeekLineName.value.trim() || 'NetConsole',
      selected_item_keys: [...selected],
      excluded_item_keys: omniPeekPreview.value.items.filter((item) => !selected.has(item.key)).map((item) => item.key),
      force_export_keys: omniPeekForceKeys.value,
    })])
    omniPeekVisible.value = false
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
  try {
    if (terminalSettings.pass_password) {
      await ElMessageBox.confirm(
        '启用后密码可能出现在外部终端进程参数中。确认仅在受控本机使用？',
        '传递终端密码',
        { confirmButtonText: '确认启用', cancelButtonText: '取消', type: 'warning' },
      )
    }
    Object.assign(terminalSettings, await updateExternalTerminalSettings({ ...terminalSettings }))
    terminalSettingsVisible.value = false
    ElMessage.success('外部终端配置已保存')
  } catch (cause) {
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
      : detail.value
        ? [detail.value.device.device_uuid]
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
      await ElMessageBox.confirm(
        `将打开 ${terminalTargetUuids.value.length} 台设备的外部终端，是否继续？`,
        '批量打开外部终端',
        { confirmButtonText: '继续', cancelButtonText: '取消', type: 'warning' },
      )
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
  if (['UNREACHABLE', 'ERROR'].includes(status)) return 'danger'
  return 'info'
}

function statusLabel(status: DeviceConnectionStatus): string {
  return { UNKNOWN: '未测试', TESTING: '测试中', REACHABLE: '可达', UNREACHABLE: '不可达', ERROR: '任务异常' }[status]
}

async function openDeviceWeb(): Promise<void> {
  if (!detail.value?.device.web_url || !desktopHost.value) return
  const result = await getPlatformAdapter().openExternalUrl(detail.value.device.web_url)
  if (!result.success) ElMessage.error(result.error || '无法打开设备 Web 管理地址')
}

function recordText(row: Record<string, unknown>, field: string): string {
  return String(row[field] ?? '')
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
        <el-option v-for="type in ['AC', 'SW', 'FW', 'Route', 'Cloud-AP', 'FAT-AP', 'Other']" :key="type" :label="type" :value="type" />
      </el-select>
      <el-select v-model="filters.vendor" clearable placeholder="全部厂商" @change="loadDevices(true)">
        <el-option v-for="vendor in ['H3C', 'Huawei', 'Ruijie', 'Cisco', 'Other']" :key="vendor" :label="vendor" :value="vendor" />
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
      <el-button :icon="Edit" :disabled="selectedUuids.length !== 1 || !isFeatureEnabled('web.device_management_write')" @click="editSelected">编辑</el-button>
      <el-button :icon="CopyDocument" :disabled="selectedUuids.length !== 1 || !isFeatureEnabled('web.device_management_write')" @click="duplicateSelected">复制</el-button>
      <el-button :icon="Delete" type="danger" plain :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_write')" @click="deleteSelected">批量删除</el-button>
      <el-button :icon="FolderOpened" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_write')" @click="groupAssignVisible = true">设置分组</el-button>
      <el-button :icon="Plus" :disabled="!isFeatureEnabled('web.device_management_write')" @click="groupVisible = true">分组管理</el-button>
      <el-button :icon="Connection" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_connection_test')" @click="startSelectedConnectionTests">测试连接</el-button>
      <el-button :icon="FolderOpened" :disabled="!desktopHost || !selectedUuids.length || !isFeatureEnabled('web.device_management_desktop')" @click="requestTerminal()">外部终端</el-button>
      <el-button :icon="Refresh" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_collect')" @click="refreshSelectedDetails">批量更新详情</el-button>
      <el-button :icon="Download" :disabled="!selectedUuids.length || !isFeatureEnabled('web.device_management_collect')" @click="downloadDiagnostics">下载诊断</el-button>
      <el-button :icon="Upload" :disabled="!isFeatureEnabled('web.device_management_import')" @click="importVisible = true">导入 CSV</el-button>
      <el-dropdown>
        <el-button :icon="Download" :disabled="!isFeatureEnabled('web.device_management_export')">导出</el-button>
        <template #dropdown><el-dropdown-menu><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportCsv(false)">CSV 导出（不含凭据）</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportCsv(true)">CSV 导出（含凭据）</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="exportTemplate">模板导出</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="openOmniPeekExport">OmniPeek 名称表</el-dropdown-item><el-dropdown-item :disabled="!isFeatureEnabled('web.device_management_export')" @click="openSecureCrtExport">SecureCRT 会话</el-dropdown-item></el-dropdown-menu></template>
      </el-dropdown>
      <el-button :disabled="!selectedUuids.length" @click="clearSelection">清空选择</el-button>
      <el-button :disabled="!pageData.items.length" @click="invertSelection">反选当前页</el-button>
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
      <el-table ref="deviceTable" v-else :data="pageData.items" row-key="device_uuid" stripe height="calc(100vh - 380px)" empty-text="暂无设备" @selection-change="onSelectionChange" @row-contextmenu="showContextMenu">
        <el-table-column type="selection" width="44" fixed="left" />
        <el-table-column prop="name" label="名称" min-width="180" fixed="left" show-overflow-tooltip />
        <el-table-column prop="group_name" label="分组" min-width="120" />
        <el-table-column prop="system_name" label="系统名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="station" label="站点" min-width="160" />
        <el-table-column prop="primary_address" label="主地址" min-width="135" />
        <el-table-column prop="backup_address" label="备用地址" min-width="135" />
        <el-table-column label="登录协议" min-width="110"><template #default="{ row }">{{ [row.capabilities.ssh && 'SSH', row.capabilities.telnet && 'Telnet'].filter(Boolean).join('/') || '--' }}</template></el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="175" />
        <el-table-column label="连接状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.connection_status)">{{ statusLabel(row.connection_status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="180" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button><el-button link :disabled="!isFeatureEnabled('web.device_management_write')" @click="editRow(row)">编辑</el-button><el-button link type="danger" :disabled="!isFeatureEnabled('web.device_management_write')" @click="deleteRows([row.device_uuid])">删除</el-button></template></el-table-column>
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

    <el-drawer v-model="detailVisible" title="设备详情" size="min(880px, 96vw)">
      <div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" :title="detailError" type="error" show-icon :closable="false" />
        <template v-else-if="detail">
          <div class="detail-heading">
            <div><h2>{{ detail.device.name }}</h2><p>{{ detail.device.device_uuid }}</p></div>
            <div class="heading-actions"><el-button v-if="detail.device.web_url" :disabled="!desktopHost" @click="openDeviceWeb">打开设备 Web</el-button><el-button :icon="FolderOpened" :disabled="!desktopHost || !isFeatureEnabled('web.device_management_desktop')" @click="requestTerminal">外部终端</el-button><el-button :icon="Edit" :disabled="!isFeatureEnabled('web.device_edit_preview') || !isFeatureEnabled('web.device_management_write')" @click="openPreview">编辑预览</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.device_management_write')" @click="openEdit">正式编辑</el-button></div>
          </div>
          <el-tabs v-model="detailTab" class="device-detail-tabs">
            <el-tab-pane label="概览" name="overview">
              <div class="action-row"><el-button :icon="Refresh" :disabled="!isFeatureEnabled('web.device_management_collect')" @click="refreshDetailData">刷新设备详情</el-button></div>
              <el-descriptions :column="2" border>
                <el-descriptions-item label="名称">{{ detail.device.name }}</el-descriptions-item>
                <el-descriptions-item label="系统名">{{ detail.device.system_name || '--' }}</el-descriptions-item>
                <el-descriptions-item label="主地址">{{ detail.device.primary_address }}</el-descriptions-item>
                <el-descriptions-item label="备用地址">{{ detail.device.backup_address || '--' }}</el-descriptions-item>
                <el-descriptions-item label="MAC">{{ detail.device.mac_address || detail.fact?.mac_address || '--' }}</el-descriptions-item>
                <el-descriptions-item label="分组">{{ detail.device.group_name }}</el-descriptions-item>
                <el-descriptions-item label="类型">{{ detail.device.device_type }}</el-descriptions-item>
                <el-descriptions-item label="站点">{{ detail.device.station || '--' }}</el-descriptions-item>
                <el-descriptions-item label="SSH 端口">{{ detail.device.capabilities.ssh_port || '--' }}</el-descriptions-item>
                <el-descriptions-item label="登录协议">{{ [detail.device.capabilities.ssh && 'SSH', detail.device.capabilities.telnet && 'Telnet'].filter(Boolean).join('/') || '--' }}</el-descriptions-item>
                <el-descriptions-item label="型号">{{ detail.fact?.model || '--' }}</el-descriptions-item>
                <el-descriptions-item label="软件版本">{{ detail.fact?.software_version || '--' }}</el-descriptions-item>
                <el-descriptions-item label="备注" :span="2">{{ detail.device.remark || '--' }}</el-descriptions-item>
                <el-descriptions-item label="更新时间" :span="2">{{ detail.device.updated_at || '--' }}</el-descriptions-item>
              </el-descriptions>
              <section class="detail-section"><h3>连接测试</h3><div class="action-row">
                <el-button v-if="detail.device.capabilities.ssh" :icon="Connection" :loading="connectionLoading" :disabled="testActive || !isFeatureEnabled('web.device_connection_test')" @click="startTest('SSH')">测试 SSH</el-button>
                <el-button v-if="detail.device.capabilities.telnet" :icon="Connection" :loading="connectionLoading" :disabled="testActive || !isFeatureEnabled('web.device_connection_test')" @click="startTest('TELNET')">测试 Telnet</el-button>
                <el-button v-if="detail.device.capabilities.snmp" :icon="Connection" :loading="connectionLoading" :disabled="testActive || !isFeatureEnabled('web.device_connection_test')" @click="startTest('SNMP')">测试 SNMP</el-button>
              </div><el-alert v-if="connectionTest" :title="`${connectionTest.protocol || '连接'} · ${connectionTest.task_status} · ${connectionTest.message || '等待结果'}`" :type="connectionTest.success === true ? 'success' : connectionTest.success === false ? 'error' : 'info'" :description="`Task ID: ${connectionTest.task_id}${connectionTest.suggestion ? `；建议：${connectionTest.suggestion}` : ''}`" show-icon :closable="false" /></section>
              <section v-if="detail.connection_commands.length" class="detail-section"><h3>连接命令（不含凭据）</h3><div v-for="item in detail.connection_commands" :key="item.protocol" class="command-row"><code>{{ item.command }}</code><el-button link :icon="CopyDocument" @click="copyText(item.command)">复制</el-button></div></section>
              <section class="detail-section"><h3>最近任务</h3><el-table :data="detail.recent_tasks" size="small" empty-text="暂无关联任务"><el-table-column prop="task_name" label="任务" min-width="180" /><el-table-column prop="status" label="状态" width="105" /><el-table-column prop="updated_time" label="更新时间" width="190" /><el-table-column prop="error_summary" label="错误" min-width="180" show-overflow-tooltip /></el-table></section>
              <section v-if="detail.recent_collection" class="detail-section"><h3>最近采集</h3><el-alert :title="`${detail.recent_collection.collect_type} · ${detail.recent_collection.status}`" :description="detail.recent_collection.error_summary || detail.recent_collection.ended_at" type="info" :closable="false" /></section>
              <section v-if="detail.recent_errors.length" class="detail-section"><h3>最近错误</h3><el-table :data="detail.recent_errors" size="small"><el-table-column prop="source" label="来源" width="100" /><el-table-column prop="time" label="时间" width="190" /><el-table-column prop="message" label="错误摘要" min-width="260" show-overflow-tooltip /></el-table></section>
            </el-tab-pane>
            <el-tab-pane label="接口" name="interfaces"><el-table :data="detail.interfaces" max-height="520" empty-text="暂无接口数据"><el-table-column prop="interface_name" label="接口" min-width="180" fixed /><el-table-column prop="link_status" label="链路" width="90" /><el-table-column prop="protocol_status" label="协议" width="90" /><el-table-column prop="speed" label="速率" width="100" /><el-table-column prop="duplex" label="双工" width="90" /><el-table-column prop="interface_type" label="接口类型" min-width="120" /><el-table-column prop="port_status" label="端口状态" width="100" /><el-table-column prop="pvid" label="PVID" width="80" /><el-table-column prop="description" label="描述" min-width="180" /><el-table-column prop="ip_address" label="接口 IP" min-width="130" /><el-table-column prop="mac_address" label="MAC" min-width="140" /><el-table-column prop="vlan" label="VLAN" min-width="100" /><el-table-column prop="collected_at" label="采集时间" min-width="175" /><el-table-column label="历史" width="80" fixed="right"><template #default="{ row }"><el-button link @click="openHistory('interface', recordText(row, 'interface_name'))">历史</el-button></template></el-table-column></el-table></el-tab-pane>
            <el-tab-pane label="光模块" name="optical"><div class="action-row"><el-button :icon="Refresh" :disabled="!isFeatureEnabled('web.device_management_collect')" @click="refreshOpticalData">刷新光模块</el-button></div><el-table :data="detail.optical_modules" max-height="520" empty-text="暂无光模块数据"><el-table-column prop="interface_name" label="接口" min-width="180" fixed /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="rx_power" label="接收功率" width="110" /><el-table-column prop="tx_power" label="发送功率" width="110" /><el-table-column prop="temperature" label="温度" width="90" /><el-table-column prop="voltage" label="电压" width="90" /><el-table-column prop="bias_current" label="偏置电流" width="110" /><el-table-column prop="module_model" label="模块型号" min-width="160" /><el-table-column prop="module_serial_number" label="序列号" min-width="160" /><el-table-column prop="module_vendor" label="厂商" min-width="120" /><el-table-column prop="wavelength" label="波长" width="100" /><el-table-column prop="transmission_distance" label="传输距离" width="110" /><el-table-column prop="connector_type" label="接口类型" width="100" /><el-table-column prop="collected_at" label="采集时间" min-width="175" /><el-table-column label="历史" width="80" fixed="right"><template #default="{ row }"><el-button link @click="openHistory('optical', recordText(row, 'interface_name'))">历史</el-button></template></el-table-column></el-table></el-tab-pane>
            <el-tab-pane label="LLDP" name="lldp"><el-table :data="detail.lldp_neighbors" max-height="520" empty-text="暂无 LLDP 数据"><el-table-column prop="local_interface" label="本地接口" min-width="180" /><el-table-column prop="neighbor_sysname" label="邻居系统名" min-width="160" /><el-table-column prop="neighbor_mac" label="邻居 MAC" min-width="150" /><el-table-column prop="neighbor_interface" label="邻居接口" min-width="180" /><el-table-column prop="collected_at" label="采集时间" min-width="175" /><el-table-column label="历史" width="80" fixed="right"><template #default="{ row }"><el-button link @click="openHistory('lldp', recordText(row, 'local_interface'))">历史</el-button></template></el-table-column></el-table></el-tab-pane>
            <el-tab-pane label="轨旁 AP 业务" name="trackside"><el-table :data="detail.trackside_ap_business" max-height="520" empty-text="暂无轨旁 AP 业务数据"><el-table-column prop="interface_name" label="接口" min-width="180" /><el-table-column prop="link_status" label="链路" width="90" /><el-table-column prop="port_type" label="端口类型" width="110" /><el-table-column prop="description" label="描述" min-width="180" /><el-table-column prop="pvid" label="PVID" width="80" /><el-table-column prop="vlan" label="VLAN" min-width="100" /><el-table-column prop="switch_rx_power" label="交换机接收功率" min-width="130" /><el-table-column prop="switch_optical_status" label="交换机光衰状态" min-width="130" /><el-table-column prop="ap_mac" label="AP MAC" min-width="140" /><el-table-column prop="ap_name" label="AP 名称" min-width="140" /><el-table-column prop="ap_rx_power" label="AP 接收功率" min-width="120" /><el-table-column prop="ap_optical_status" label="AP 光衰状态" min-width="120" /><el-table-column prop="updated_at" label="更新时间" min-width="175" /></el-table></el-tab-pane>
          </el-tabs>
        </template>
      </div>
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

    <el-dialog v-model="historyVisible" :title="`历史数据 · ${historyPage?.object_name || ''}`" width="min(1180px, 96vw)">
      <div v-loading="historyLoading" class="history-table">
        <el-table :data="historyPage?.items || []" max-height="620" empty-text="暂无历史数据">
          <el-table-column v-for="column in historyColumns" :key="column[1]" :label="column[0]" :prop="column[1]" min-width="140" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer><el-button @click="historyVisible = false">关闭</el-button></template>
    </el-dialog>

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

    <el-dialog v-model="writeVisible" :title="writeMode === 'create' ? '新建设备' : '编辑设备'" width="min(1120px, 96vw)" top="4vh" @closed="clearWriteSecrets">
      <el-alert :title="writeMode === 'edit' ? '秘密字段留空会保留原值；服务端响应、任务参数和日志不会回传秘密。' : '秘密字段只用于当前设备保存和后续连接，不会在 API 响应中回显。'" type="info" show-icon :closable="false" />
      <el-form label-width="118px" class="device-write-form">
        <div class="form-grid">
          <section class="form-section"><h3>基础信息</h3>
            <el-form-item label="设备名称 *"><el-input v-model="writeForm.name" /></el-form-item>
            <el-form-item label="系统名"><el-input v-model="writeForm.system_name" /></el-form-item>
            <el-form-item label="分组"><el-select v-model="writeForm.group_id" clearable style="width:100%"><el-option v-for="group in pageData.groups" :key="group.id" :label="group.name" :value="group.id" /></el-select></el-form-item>
            <el-form-item label="厂商"><el-select v-model="writeForm.device_vendor" style="width:100%"><el-option v-for="vendor in ['H3C', 'Huawei', 'Ruijie', 'Cisco', 'Other']" :key="vendor" :label="vendor" :value="vendor" /></el-select></el-form-item>
            <el-form-item label="类型"><el-select v-model="writeForm.device_type" style="width:100%"><el-option v-for="type in ['AC', 'SW', 'FW', 'Route', 'Cloud-AP', 'FAT-AP', 'Other']" :key="type" :label="type" :value="type" /></el-select></el-form-item>
            <el-form-item label="站点"><el-input v-model="writeForm.station" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="writeForm.remark" type="textarea" :rows="3" /></el-form-item>
          </section>
          <section class="form-section"><h3>连接</h3>
            <el-form-item label="主地址 *"><el-input v-model="writeForm.primary_address" /></el-form-item>
            <el-form-item label="备用地址"><el-input v-model="writeForm.backup_address" /></el-form-item>
            <el-form-item label="SSH"><el-checkbox v-model="writeForm.ssh_enabled">启用</el-checkbox><el-input-number v-model="writeForm.ssh_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
            <el-form-item label="Telnet"><el-checkbox v-model="writeForm.telnet_enabled">启用</el-checkbox><el-input-number v-model="writeForm.telnet_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
          </section>
          <section class="form-section"><h3>SSH 认证</h3>
            <el-form-item label="用户名"><el-input v-model="writeForm.ssh_username" autocomplete="off" /></el-form-item>
            <el-form-item label="密码"><el-input v-model="writeForm.ssh_password" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.ssh_secret_configured ? '已配置；留空保留' : ''" /></el-form-item>
          </section>
          <section class="form-section"><h3>Telnet 认证</h3>
            <el-form-item label="用户名"><el-input v-model="writeForm.telnet_username" autocomplete="off" /></el-form-item>
            <el-form-item label="密码"><el-input v-model="writeForm.telnet_password" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.telnet_secret_configured ? '已配置；留空保留' : ''" /></el-form-item>
          </section>
        </div>

        <section class="form-section full-width"><h3>SSH 隧道</h3><div class="form-grid two-columns">
          <div><h4>第一跳</h4><el-form-item label="主机"><el-input v-model="writeForm.tunnel1_host" /></el-form-item><el-form-item label="端口"><el-input-number v-model="writeForm.tunnel1_port" :min="1" :max="65535" /></el-form-item><el-form-item label="用户名"><el-input v-model="writeForm.tunnel1_username" /></el-form-item><el-form-item label="密码"><el-input v-model="writeForm.tunnel1_password" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.tunnel1_secret_configured ? '已配置；留空保留' : ''" /></el-form-item></div>
          <div><h4>第二跳</h4><el-form-item label="主机"><el-input v-model="writeForm.tunnel2_host" /></el-form-item><el-form-item label="端口"><el-input-number v-model="writeForm.tunnel2_port" :min="1" :max="65535" /></el-form-item><el-form-item label="用户名"><el-input v-model="writeForm.tunnel2_username" /></el-form-item><el-form-item label="密码"><el-input v-model="writeForm.tunnel2_password" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.tunnel2_secret_configured ? '已配置；留空保留' : ''" /></el-form-item></div>
        </div></section>

        <section class="form-section full-width"><h3>SNMP</h3><div class="form-grid two-columns">
          <div>
            <el-form-item label="启用"><el-checkbox v-model="writeForm.snmp_enabled">SNMP</el-checkbox><el-checkbox v-model="writeForm.snmp_v1_enabled">v1</el-checkbox><el-checkbox v-model="writeForm.snmp_v2c_enabled">v2c</el-checkbox><el-checkbox v-model="writeForm.snmp_v3_enabled">v3</el-checkbox></el-form-item>
            <el-form-item label="端口"><el-input-number v-model="writeForm.snmp_port" :min="1" :max="65535" /></el-form-item>
            <el-form-item label="超时(ms)"><el-input-number v-model="writeForm.snmp_timeout_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item label="重试"><el-input-number v-model="writeForm.snmp_retries" :min="0" :max="10" /></el-form-item>
            <el-form-item label="只读团体字"><el-input v-model="writeForm.snmp_ro_community" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.snmp_ro_secret_configured ? '已配置；留空保留' : ''" /></el-form-item>
            <el-form-item label="读写团体字"><el-input v-model="writeForm.snmp_rw_community" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.snmp_rw_secret_configured ? '已配置；留空保留' : ''" /></el-form-item>
          </div>
          <div v-if="writeForm.snmp_v3_enabled">
            <el-form-item label="v3 用户名"><el-input v-model="writeForm.snmpv3_username" /></el-form-item>
            <el-form-item label="安全级别"><el-select v-model="writeForm.snmpv3_security_level" style="width:100%"><el-option v-for="level in ['noAuthNoPriv', 'AuthNoPriv', 'AuthPriv']" :key="level" :label="level" :value="level" /></el-select></el-form-item>
            <el-form-item v-if="writeForm.snmpv3_security_level !== 'noAuthNoPriv'" label="认证协议"><el-select v-model="writeForm.snmpv3_auth_protocol" style="width:100%"><el-option v-for="protocol in ['MD5', 'SHA', 'SHA224', 'SHA256', 'SHA384', 'SHA512']" :key="protocol" :label="protocol" :value="protocol" /></el-select></el-form-item>
            <el-form-item v-if="writeForm.snmpv3_security_level !== 'noAuthNoPriv'" label="认证密码"><el-input v-model="writeForm.snmpv3_auth_password" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.snmpv3_auth_secret_configured ? '已配置；留空保留' : ''" /></el-form-item>
            <el-form-item v-if="writeForm.snmpv3_security_level === 'AuthPriv'" label="加密协议"><el-select v-model="writeForm.snmpv3_priv_protocol" style="width:100%"><el-option v-for="protocol in ['DES', '3DES', 'AES128', 'AES192', 'AES256']" :key="protocol" :label="protocol" :value="protocol" /></el-select></el-form-item>
            <el-form-item v-if="writeForm.snmpv3_security_level === 'AuthPriv'" label="加密密码"><el-input v-model="writeForm.snmpv3_priv_password" type="password" show-password autocomplete="new-password" :placeholder="writeMode === 'edit' && detail?.device.snmpv3_priv_secret_configured ? '已配置；留空保留' : ''" /></el-form-item>
            <el-form-item label="Context"><el-input v-model="writeForm.snmp_context_name" /></el-form-item>
          </div>
        </div></section>
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

    <el-dialog v-model="omniPeekVisible" title="导出 OmniPeek 名称表" width="min(1120px, 96vw)" @closed="stopOmniPeekPreview">
      <el-form label-width="90px"><el-form-item label="线路名称"><el-input v-model="omniPeekLineName" maxlength="200" /></el-form-item></el-form>
      <el-alert v-if="omniPeekPreview" :title="`共 ${omniPeekPreview.stats.total || 0} 项，异常 ${omniPeekPreview.stats.abnormal || 0} 项；异常项需人工确认后才能强制导出。`" type="info" show-icon :closable="false" />
      <el-table ref="omniPeekTable" v-loading="omniPeekLoading" :data="omniPeekPreview?.items || []" row-key="key" max-height="520" empty-text="暂无可导出数据" @selection-change="onOmniPeekSelectionChange">
        <el-table-column type="selection" width="48" reserve-selection />
        <el-table-column prop="name" label="名称" min-width="180" fixed />
        <el-table-column prop="physical_mac" label="物理 MAC" min-width="150" />
        <el-table-column prop="r1_mac" label="R1" min-width="150" />
        <el-table-column prop="r2_mac" label="R2" min-width="150" />
        <el-table-column prop="location" label="位置" min-width="140" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column label="强制导出" width="100"><template #default="{ row }"><el-checkbox :model-value="omniPeekForceKeys.includes(row.key)" :disabled="row.status === '正常' || !omniPeekSelectedKeys.includes(row.key)" @change="setOmniPeekForce(row.key, Boolean($event))" /></template></el-table-column>
      </el-table>
      <template #footer><el-button @click="omniPeekVisible = false">取消</el-button><el-button type="primary" :loading="omniPeekLoading" :disabled="!omniPeekPreview || !omniPeekSelectedKeys.length" @click="exportOmniPeek">确认导出</el-button></template>
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
.device-management { max-width: 1720px; margin: 0 auto; }
.page-heading, .detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.heading-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.group-list { margin-top: 16px; max-height: 260px; overflow-y: auto; }
.group-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.page-heading h1, .detail-heading h2, .detail-section h3 { margin: 0; }
.page-heading p, .detail-heading p { margin: 5px 0 0; color: #718096; font-size: 13px; }
.filters { display: grid; grid-template-columns: minmax(240px, 2fr) repeat(6, minmax(120px, 1fr)) auto; gap: 10px; padding: 14px; margin-bottom: 14px; }
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
.device-write-form { max-height: 70vh; padding: 18px 4px 0; overflow-y: auto; }
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
@media (max-width: 760px) { .filters, .form-grid, .form-grid.two-columns { grid-template-columns: 1fr; } .page-heading { align-items: flex-start; } }
</style>
