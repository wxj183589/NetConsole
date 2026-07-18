<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Edit, FolderOpened, Refresh, View } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { configArtifactDownloadRequest, submitSnapshotConfigDiff } from '../../api/configCollection'
import {
  getDeviceDetailSection,
  getDeviceDetailHistory,
  getDeviceInterfaceDetail,
  getDeviceOverview,
  refreshDeviceDetails,
} from '../../api/deviceManagement'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import { useTaskStore } from '../../stores/tasks'
import type { TaskStatus } from '../../types/task'
import type {
  DeviceConnectionTest,
  DeviceBusinessAssociationRecord,
  DeviceDataSource,
  DeviceDetailRecord,
  DeviceDetailSource,
  DeviceDetailSectionResponse,
  DeviceDetailSection,
  DeviceDetailSectionPage,
  DeviceDetailHistoryPage,
  DeviceOverviewResponse,
  DeviceTaskReference,
} from '../../types/deviceManagement'
import type { ConfigTaskReference } from '../../types/configCollection'

type DetailMode = 'drawer' | 'page'

interface Props {
  deviceUuid: string
  mode: DetailMode
  overview?: DeviceOverviewResponse | null
  connectionTest?: DeviceConnectionTest | null
}

interface DetailColumn {
  label: string
  key: string
  width?: number
  minWidth?: number
  fixed?: boolean
}

interface HistoryViewPage extends DeviceDetailHistoryPage {
  kind: 'interface' | 'optical' | 'lldp'
  object_name: string
}

interface DeviceTaskWindowBridge {
  openTaskWindow(context: { taskId?: string; module: 'devices'; status?: TaskStatus }): Promise<{ success: boolean; error?: string }>
}

const props = withDefaults(defineProps<Props>(), {
  overview: null,
  connectionTest: null,
})

const emit = defineEmits<{
  (event: 'full-detail'): void
  (event: 'edit', deviceUuid: string): void
  (event: 'terminal', deviceUuid: string): void
}>()

const router = useRouter()
const taskStore = useTaskStore()
const overview = ref<DeviceOverviewResponse | null>(props.overview)
const loading = ref(false)
const error = ref('')
const selectedSection = ref<DeviceDetailSection>('overview')
const connectionTest = ref<DeviceConnectionTest | null>(props.connectionTest)
const sectionLoading = reactive<Record<string, boolean>>({})
const sectionErrors = reactive<Record<string, string>>({})
const sectionPages = ref<Partial<Record<Exclude<DeviceDetailSection, 'overview'>, DeviceDetailSectionPage>>>({})
const sectionCache = new Map<string, DeviceDetailSectionPage>()
const sectionQuery = reactive({ search: '', status: '', severity: '', interface_type: '', linked_only: false, snapshot_type: '', page: 1, page_size: 50 })
const selectedRecord = ref<DeviceDetailRecord | null>(null)
const selectedRecordSection = ref<DeviceDetailSection>('overview')
const recordDetailVisible = ref(false)
const configurationSelection = ref<number[]>([])
const savedArtifactCapability = ref('')
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyPage = ref<HistoryViewPage | null>(null)
const refreshTaskId = ref('')
let loadGeneration = 0
let sectionLoadGeneration = 0
let historyLoadGeneration = 0
let interfaceDetailGeneration = 0
let interfaceDetailAbortController: AbortController | null = null
const pollingConsumer = 'device-detail-panel'

const detailSectionOrder: DeviceDetailSection[] = [
  'overview', 'interfaces', 'optical', 'lldp', 'configuration', 'tasks', 'business',
]

const sectionLabels: Record<DeviceDetailSection, string> = {
  overview: '概览',
  interfaces: '接口',
  optical: '光模块',
  lldp: 'LLDP',
  configuration: '配置',
  tasks: '任务记录',
  business: '关联业务',
}

const columnsBySection: Record<Exclude<DeviceDetailSection, 'overview'>, DetailColumn[]> = {
  interfaces: [
    { label: '接口', key: 'interface_name', minWidth: 180, fixed: true },
    { label: '链路', key: 'link_status', width: 90 },
    { label: '协议', key: 'protocol_status', width: 90 },
    { label: '速率', key: 'speed', width: 100 },
    { label: '双工', key: 'duplex', width: 90 },
    { label: '接口类型', key: 'interface_type', minWidth: 120 },
    { label: '端口状态', key: 'port_status', width: 100 },
    { label: 'PVID', key: 'pvid', width: 80 },
    { label: '描述', key: 'description', minWidth: 180 },
    { label: '接口 IP', key: 'ip_address', minWidth: 130 },
    { label: 'MAC', key: 'mac_address', minWidth: 140 },
    { label: 'VLAN', key: 'vlan', minWidth: 100 },
    { label: '采集时间', key: 'collected_at', minWidth: 175 },
  ],
  optical: [
    { label: '接口', key: 'interface_name', minWidth: 180, fixed: true },
    { label: '严重性', key: 'severity', width: 110 },
    { label: '严重性原因', key: 'severity_reason', minWidth: 200 },
    { label: '接收功率', key: 'rx_power', width: 110 },
    { label: '发送功率', key: 'tx_power', width: 110 },
    { label: '温度', key: 'temperature', width: 90 },
    { label: '电压', key: 'voltage', width: 90 },
    { label: '偏置电流', key: 'bias_current', width: 110 },
    { label: '模块型号', key: 'module_model', minWidth: 160 },
    { label: '序列号', key: 'module_serial_number', minWidth: 160 },
    { label: '厂商', key: 'module_vendor', minWidth: 120 },
    { label: '波长', key: 'wavelength', width: 100 },
    { label: '传输距离', key: 'transmission_distance', width: 110 },
    { label: '连接器', key: 'connector_type', width: 110 },
    { label: '采集时间', key: 'collected_at', minWidth: 175 },
  ],
  lldp: [
    { label: '本地接口', key: 'local_interface', minWidth: 180, fixed: true },
    { label: '邻居系统名', key: 'neighbor_sysname', minWidth: 160 },
    { label: '邻居 MAC', key: 'neighbor_mac', minWidth: 150 },
    { label: '邻居接口', key: 'neighbor_interface', minWidth: 180 },
    { label: '邻居 IP', key: 'neighbor_ip', minWidth: 150 },
    { label: '采集时间', key: 'collected_at', minWidth: 175 },
  ],
  configuration: [
    { label: '配置类型', key: 'snapshot_type', minWidth: 180, fixed: true },
    { label: '时间', key: 'timestamp', minWidth: 175 },
    { label: '文件名', key: 'filename', minWidth: 220 },
    { label: '大小', key: 'size_bytes', width: 110 },
    { label: 'SHA-256', key: 'sha256', minWidth: 240 },
    { label: '错误摘要', key: 'error_summary', minWidth: 220 },
  ],
  tasks: [
    { label: '任务', key: 'task_name', minWidth: 200, fixed: true },
    { label: '状态', key: 'status', width: 110 },
    { label: '阶段', key: 'stage', minWidth: 120 },
    { label: '消息', key: 'message', minWidth: 260 },
    { label: '耗时', key: 'duration_seconds', width: 100 },
    { label: '更新时间', key: 'updated_time', minWidth: 175 },
    { label: '错误摘要', key: 'error_summary', minWidth: 220 },
  ],
  business: [
    { label: '业务对象', key: 'name', minWidth: 200, fixed: true },
    { label: '类型', key: 'association_type', minWidth: 140 },
    { label: '状态', key: 'status', width: 110 },
    { label: '关联标识', key: 'association_id', minWidth: 220 },
    { label: '本地接口', key: 'local_interface', minWidth: 150 },
    { label: '邻居地址', key: 'peer_address', minWidth: 150 },
    { label: '链路状态', key: 'trackside_link_status', minWidth: 120 },
    { label: '交换机接收功率', key: 'switch_rx_power', minWidth: 140 },
    { label: 'AP 接收功率', key: 'ap_rx_power', minWidth: 120 },
    { label: '更新时间', key: 'updated_at', minWidth: 175 },
  ],
}

const visibleSections = computed<DeviceDetailSection[]>(() => {
  const response = overview.value
  if (!response) return ['overview']
  return detailSectionOrder.filter((section) => response.visible_sections.includes(section))
})

const currentPage = computed(() => {
  if (selectedSection.value === 'overview') return null
  return sectionPages.value[selectedSection.value]
})

const currentColumns = computed(() => selectedSection.value === 'overview' ? [] : columnsBySection[selectedSection.value])
const currentRows = computed(() => currentPage.value?.items ?? [])
const sectionTableHeight = computed(() => props.mode === 'page' ? 'max(320px, calc(100dvh - 390px))' : undefined)
const sectionTableMaxHeight = computed(() => props.mode === 'drawer' ? 560 : undefined)
const historyColumns = computed(() => {
  const kind = historyPage.value?.kind
  if (kind === 'interface') return [['采集时间', 'collected_at'], ['接口', 'interface_name'], ['链路', 'link_status'], ['协议', 'protocol_status'], ['速率', 'speed'], ['双工', 'duplex'], ['类型', 'interface_type'], ['端口状态', 'port_status'], ['PVID', 'pvid'], ['描述', 'description'], ['接口 IP', 'ip_address'], ['MAC', 'mac_address'], ['VLAN', 'vlan']]
  if (kind === 'optical') return [['采集时间', 'collected_at'], ['接口', 'interface_name'], ['严重性', 'severity'], ['严重性原因', 'severity_reason'], ['接收功率', 'rx_power'], ['发送功率', 'tx_power'], ['温度', 'temperature'], ['电压', 'voltage'], ['偏置电流', 'bias_current'], ['模块型号', 'module_model'], ['序列号', 'module_serial_number'], ['厂商', 'module_vendor'], ['波长', 'wavelength'], ['传输距离', 'transmission_distance'], ['连接器', 'connector_type']]
  return [['采集时间', 'collected_at'], ['本地接口', 'local_interface'], ['邻居系统名', 'neighbor_sysname'], ['邻居 MAC', 'neighbor_mac'], ['邻居接口', 'neighbor_interface'], ['邻居 IP', 'neighbor_ip'], ['关联状态', 'association_status']]
})
const publicDeviceTasks = computed(() => taskStore.tasks.filter((task) => task.module === 'devices' || task.owner === 'web_device_management' || task.type.startsWith('device_')))
const sectionFilterOptions: Partial<Record<DeviceDetailSection, Array<{ label: string; value: string }>>> = {
  interfaces: [
    { label: '链路 UP', value: 'UP' },
    { label: '链路 DOWN', value: 'DOWN' },
  ],
  optical: [
    { label: '正常', value: 'normal' },
    { label: '提示', value: 'notice' },
    { label: '警告', value: 'warning' },
    { label: '告警', value: 'alarm' },
    { label: '链路异常', value: 'link_abnormal' },
    { label: '无光', value: 'no_light' },
    { label: '无模块', value: 'no_module' },
    { label: '未知', value: 'unknown' },
  ],
  tasks: [
    { label: '等待中', value: 'PENDING' },
    { label: '启动中', value: 'STARTING' },
    { label: '运行中', value: 'RUNNING' },
    { label: '停止中', value: 'STOPPING' },
    { label: '已完成', value: 'COMPLETED' },
    { label: '失败', value: 'FAILED' },
    { label: '已取消', value: 'CANCELLED' },
  ],
  configuration: [
    { label: '运行配置', value: 'running' },
    { label: '保存配置', value: 'saved' },
    { label: '差异配置', value: 'diff' },
  ],
}

function getSectionFilterOptions(section: DeviceDetailSection): Array<{ label: string; value: string }> {
  return sectionFilterOptions[section] ?? []
}

const terminalRefreshStatuses = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
watch(
  () => refreshTaskId.value ? taskStore.tasks.find((task) => task.id === refreshTaskId.value)?.status || '' : '',
  async (status, previousStatus) => {
    if (!status || status === previousStatus || !terminalRefreshStatuses.has(status)) return
    refreshTaskId.value = ''
    await reloadAfterRefresh()
  },
)

watch(() => props.connectionTest, (value) => { connectionTest.value = value ?? null })
watch(() => props.overview, (value) => {
  overview.value = value ?? null
  selectedSection.value = 'overview'
  clearSectionState()
})
watch(() => props.deviceUuid, () => {
  interfaceDetailGeneration += 1
  interfaceDetailAbortController?.abort()
  interfaceDetailAbortController = null
  void initialize()
})

onMounted(() => {
  taskStore.acquirePolling(pollingConsumer)
  void initialize()
})

onBeforeUnmount(() => {
  loadGeneration += 1
  interfaceDetailGeneration += 1
  interfaceDetailAbortController?.abort()
  interfaceDetailAbortController = null
  refreshTaskId.value = ''
  sectionLoadGeneration += 1
  historyLoadGeneration += 1
  taskStore.releasePolling(pollingConsumer)
})

async function initialize(): Promise<void> {
  const generation = ++loadGeneration
  clearSectionState()
  selectedSection.value = 'overview'
  error.value = ''
  connectionTest.value = props.connectionTest ?? null
  if (props.overview) {
    overview.value = props.overview
    return
  }
  overview.value = null
  loading.value = true
  try {
    const result = await getDeviceOverview(props.deviceUuid)
    if (generation === loadGeneration) overview.value = result
  } catch (cause) {
    if (generation === loadGeneration) error.value = errorMessage(cause, '设备详情加载失败')
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

function clearSectionState(): void {
  sectionLoadGeneration += 1
  historyLoadGeneration += 1
  sectionPages.value = {}
  sectionCache.clear()
  for (const key of Object.keys(sectionLoading)) delete sectionLoading[key]
  for (const key of Object.keys(sectionErrors)) delete sectionErrors[key]
}

async function activateSection(name: string | number): Promise<void> {
  const section = String(name) as DeviceDetailSection
  if (section === 'overview' || !visibleSections.value.includes(section)) return
  selectedSection.value = section
  sectionQuery.search = ''
  sectionQuery.status = ''
  sectionQuery.severity = ''
  sectionQuery.interface_type = ''
  sectionQuery.linked_only = false
  sectionQuery.snapshot_type = ''
  sectionQuery.page = 1
  await loadSection(section, false)
}

async function loadSection(section = selectedSection.value as Exclude<DeviceDetailSection, 'overview'>, resetPage = false): Promise<void> {
  if (!overview.value) return
  const generation = ++sectionLoadGeneration
  if (resetPage) sectionQuery.page = 1
  const query = {
    page: sectionQuery.page,
    page_size: sectionQuery.page_size,
    search: ['interfaces', 'optical', 'lldp'].includes(section) ? sectionQuery.search.trim() : undefined,
    status: ['interfaces', 'tasks'].includes(section) ? sectionQuery.status : undefined,
    severity: section === 'optical' ? sectionQuery.severity : undefined,
    interface_type: section === 'interfaces' ? sectionQuery.interface_type : undefined,
    linked_only: section === 'lldp' ? sectionQuery.linked_only : undefined,
    snapshot_type: section === 'configuration' ? sectionQuery.snapshot_type : undefined,
  }
  const cacheKey = [section, query.page, query.page_size, query.search, query.status || '', query.severity || '', query.interface_type || '', query.linked_only ? '1' : '0', query.snapshot_type || ''].join('|')
  const cached = sectionCache.get(cacheKey)
  if (cached) {
    sectionPages.value[section] = cached
    return
  }
  sectionLoading[section] = true
  sectionErrors[section] = ''
  try {
    const result = normalizeSectionResponse(section, await getDeviceDetailSection(props.deviceUuid, section, query))
    if (generation !== sectionLoadGeneration) return
    sectionCache.set(cacheKey, result)
    sectionPages.value[section] = result
  } catch (cause) {
    if (generation === sectionLoadGeneration) sectionErrors[section] = errorMessage(cause, `${sectionLabels[section]}加载失败`)
  } finally {
    if (generation === sectionLoadGeneration) sectionLoading[section] = false
  }
}

function mapBusinessAssociation(item: DeviceBusinessAssociationRecord): DeviceDetailRecord {
  const base: DeviceDetailRecord = {
    association_type: item.association_type,
    association_id: item.association_id,
    name: item.name,
    status: item.status,
    local_interface: item.local_interface,
    peer_address: item.peer_address,
    updated_at: item.updated_at,
  }
  if (item.association_type === 'trackside_ap') {
    return {
      ...base,
      trackside_link_status: item.trackside_ap?.link_status,
      switch_rx_power: item.trackside_ap?.switch_rx_power,
      ap_rx_power: item.trackside_ap?.ap_rx_power,
    }
  }
  if (item.association_type === 'fit_ap') {
    return {
      ...base,
      ac_mac: item.fit_ap?.mac_address,
      optical_status: item.fit_ap?.optical_status,
      optical_rx_power: item.fit_ap?.optical_rx_power,
    }
  }
  if (item.association_type === 'online_mr_session') {
    return {
      ...base,
      mr_site_id: item.online_mr_session?.site_id,
      mr_started_at: item.online_mr_session?.started_at,
      mr_stopped_at: item.online_mr_session?.stopped_at,
      mr_executor_kind: item.online_mr_session?.executor_kind,
      mr_has_raw_data: item.online_mr_session?.has_raw_data,
      mr_has_parsed_data: item.online_mr_session?.has_parsed_data,
      mr_has_package: item.online_mr_session?.has_package,
      mr_mesh_available: item.online_mr_session?.mesh_available,
      mr_rssi_available: item.online_mr_session?.rssi_available,
      mr_fping_available: item.online_mr_session?.fping_available,
      mr_iperf_available: item.online_mr_session?.iperf_available,
    }
  }
  return base
}

function normalizeSectionResponse(
  section: Exclude<DeviceDetailSection, 'overview'>,
  response: DeviceDetailSectionResponse,
): DeviceDetailSectionPage {
  const rawItems = response.items ?? []
  const items = rawItems.map((item) => {
    if (section === 'business') return mapBusinessAssociation(item as unknown as DeviceBusinessAssociationRecord)
    if (section === 'interfaces' && item.name !== undefined && item.interface_name === undefined) return { ...item, interface_name: item.name }
    if (section === 'lldp' && item.neighbor_system_name !== undefined && item.neighbor_sysname === undefined) return { ...item, neighbor_sysname: item.neighbor_system_name }
    if (section === 'configuration' && item.snapshot_type !== undefined && item.key === undefined) return { ...item, key: item.snapshot_type }
    if (section === 'tasks' && item.updated_time === undefined && item.updated_at !== undefined) return { ...item, updated_time: item.updated_at }
    return item
  })
  return {
    section,
    items,
    total: response.total ?? items.length,
    page: response.page ?? 1,
    page_size: response.page_size ?? 50,
    total_pages: response.total_pages ?? 1,
    fetched_at: response.source.collected_at ?? undefined,
    source: response.source,
    task_id: response.source.task_id ?? response.task_id ?? '',
    truncated: response.truncated ?? false,
  }
}

async function refreshCurrentSection(): Promise<void> {
  if (selectedSection.value === 'overview') {
    await initialize()
    return
  }
  for (const key of [...sectionCache.keys()]) if (key.startsWith(`${selectedSection.value}|`)) sectionCache.delete(key)
  await loadSection(selectedSection.value, false)
}

async function refreshAll(): Promise<void> {
  if (!overview.value?.command_profile?.executable) {
    ElMessage.warning(`设备详情刷新不可用：${formatValue(overview.value?.command_profile?.reason)}`)
    return
  }
  try {
    const result = await refreshDeviceDetails(props.deviceUuid)
    refreshTaskId.value = result.task_id
    await presentTasks([{
      task_id: result.task_id,
      task_status: result.status,
      action: result.operation_id,
      artifact_id: '',
      available: false,
      sha256: '',
      size_bytes: 0,
      message: result.message ?? '',
    }], result.reused ? '设备详情刷新任务已复用' : '设备详情刷新任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '设备详情刷新失败'))
  }
}

async function presentTasks(tasks: DeviceTaskReference[], message: string): Promise<void> {
  const task = tasks[0]
  if (!task) return
  let taskStoreRefreshed = true
  try {
    await taskStore.refresh()
  } catch {
    taskStoreRefreshed = false
  }
  const publicTask = publicDeviceTasks.value.find((item) => item.id === task.task_id)
  let taskWindowOpened = true
  try {
    taskWindowOpened = await openTaskWindow(publicTask?.id || task.task_id, publicTask?.status)
  } catch {
    taskWindowOpened = false
  }
  if (taskStoreRefreshed && taskWindowOpened) {
    ElMessage.success(message)
    return
  }
  const failedSteps = [
    !taskStoreRefreshed ? '任务状态刷新失败' : '',
    !taskWindowOpened ? '任务窗口打开失败' : '',
  ].filter(Boolean).join('；')
  ElMessage.warning(`任务已提交，但${failedSteps}`)
}

async function reloadAfterRefresh(): Promise<void> {
  const loadedSections = [...new Set([...sectionCache.keys()].map((key) => key.split('|')[0] as Exclude<DeviceDetailSection, 'overview'>))]
  const activeSection = selectedSection.value
  await initialize()
  const sectionsToReload = loadedSections.includes(activeSection as Exclude<DeviceDetailSection, 'overview'>)
    ? loadedSections
    : [...loadedSections, ...(activeSection === 'overview' ? [] : [activeSection as Exclude<DeviceDetailSection, 'overview'>])]
  for (const section of sectionsToReload) {
    if (!visibleSections.value.includes(section)) continue
    selectedSection.value = section
    await loadSection(section, false)
  }
  selectedSection.value = visibleSections.value.includes(activeSection) ? activeSection : 'overview'
}

async function openTaskWindow(taskId = '', status?: TaskStatus): Promise<boolean> {
  const context = {
    ...(taskId ? { taskId } : {}),
    module: 'devices' as const,
    ...(status ? { status } : {}),
  }
  const bridge = window.netconsoleDesktop as (typeof window.netconsoleDesktop & Partial<DeviceTaskWindowBridge>) | undefined
  if (bridge?.openTaskWindow) {
    const result = await bridge.openTaskWindow(context)
    if (!result.success) ElMessage.error(result.error || '统一任务窗口打开失败')
    return result.success
  }
  await router.push({ name: 'tasks', query: { module: 'devices', ...(taskId ? { task_id: taskId } : {}) } })
  return true
}

async function openHistory(section: DeviceDetailSection, row: DeviceDetailRecord): Promise<void> {
  const kind = section === 'interfaces' ? 'interface' : section === 'optical' ? 'optical' : section === 'lldp' ? 'lldp' : null
  const objectName = recordText(row, section === 'lldp' ? 'local_interface' : 'interface_name')
  if (!kind || !objectName) return
  historyVisible.value = true
  historyLoading.value = true
  historyPage.value = null
  const generation = ++historyLoadGeneration
  try {
    const result = await getDeviceDetailHistory(props.deviceUuid, kind, objectName, 1, 50)
    if (generation === historyLoadGeneration) historyPage.value = flattenHistoryPage(result, kind, objectName)
  } catch (cause) {
    if (generation === historyLoadGeneration) ElMessage.error(errorMessage(cause, '设备历史加载失败'))
  } finally {
    if (generation === historyLoadGeneration) historyLoading.value = false
  }
}

async function loadHistoryPage(page = 1): Promise<void> {
  const current = historyPage.value
  if (!current) return
  historyLoading.value = true
  const generation = ++historyLoadGeneration
  try {
    const result = await getDeviceDetailHistory(props.deviceUuid, current.kind, current.object_name, page, current.page_size)
    if (generation === historyLoadGeneration) historyPage.value = flattenHistoryPage(result, current.kind, current.object_name)
  } catch (cause) {
    if (generation === historyLoadGeneration) ElMessage.error(errorMessage(cause, '设备历史加载失败'))
  } finally {
    if (generation === historyLoadGeneration) historyLoading.value = false
  }
}

async function changeHistoryPageSize(pageSize: number): Promise<void> {
  if (!historyPage.value) return
  historyPage.value = { ...historyPage.value, page_size: pageSize }
  await loadHistoryPage(1)
}

function flattenHistoryPage(page: DeviceDetailHistoryPage, kind: HistoryViewPage['kind'], objectName: string): HistoryViewPage {
  return {
    ...page,
    kind,
    object_name: objectName,
    items: page.items.map((item) => ({ ...item, ...item.values })),
  }
}

function recordText(row: DeviceDetailRecord, key: string): string {
  const value = row[key]
  return value === null || value === undefined ? '' : String(value)
}

function openRecordDetail(section: DeviceDetailSection, row: DeviceDetailRecord): void {
  selectedRecordSection.value = section
  selectedRecord.value = row
  recordDetailVisible.value = true
}

async function openRowDetail(section: DeviceDetailSection, row: DeviceDetailRecord): Promise<void> {
  const generation = ++interfaceDetailGeneration
  interfaceDetailAbortController?.abort()
  interfaceDetailAbortController = null
  if (section !== 'interfaces') {
    openRecordDetail(section, row)
    return
  }
  const name = recordText(row, 'name') || recordText(row, 'interface_name')
  if (!name) {
    openRecordDetail(section, row)
    return
  }
  const controller = new AbortController()
  interfaceDetailAbortController = controller
  try {
    const detail = await getDeviceInterfaceDetail(props.deviceUuid, name, controller.signal)
    if (generation !== interfaceDetailGeneration || controller.signal.aborted) return
    selectedRecordSection.value = section
    selectedRecord.value = detail as unknown as DeviceDetailRecord
    recordDetailVisible.value = true
  } catch (cause) {
    if (generation === interfaceDetailGeneration && !controller.signal.aborted) ElMessage.error(errorMessage(cause, '接口详情加载失败'))
  } finally {
    if (interfaceDetailAbortController === controller) interfaceDetailAbortController = null
  }
}

interface DetailField {
  label: string
  key: string
  value: unknown
  context: DeviceDetailRecord
}

const detailFieldsBySection: Partial<Record<DeviceDetailSection, Array<[string, string]>>> = {
  interfaces: [
    ['接口', 'name'], ['归一化接口', 'normalized_name'], ['类别', 'category'], ['链路', 'link_status'], ['协议', 'protocol_status'],
    ['速率', 'speed'], ['双工', 'duplex'], ['接口类型', 'interface_type'], ['端口状态', 'port_status'], ['PVID', 'pvid'],
    ['描述', 'description'], ['接口 IP', 'ip_address'], ['MAC', 'mac_address'], ['VLAN', 'vlan'], ['采集时间', 'collected_at'],
  ],
  optical: [
    ['接口', 'interface_name'], ['严重性', 'severity'], ['严重性原因', 'severity_reason'],
    ['接收功率', 'rx_power'], ['发送功率', 'tx_power'], ['温度', 'temperature'], ['电压', 'voltage'], ['偏置电流', 'bias_current'],
    ['模块型号', 'module_model'], ['序列号', 'module_serial_number'], ['厂商', 'module_vendor'], ['波长', 'wavelength'],
    ['传输距离', 'transmission_distance'], ['连接器', 'connector_type'], ['采集时间', 'collected_at'],
  ],
  lldp: [
    ['本地接口', 'local_interface'], ['邻居系统名', 'neighbor_system_name'], ['邻居 MAC', 'neighbor_mac'], ['邻居接口', 'neighbor_interface'],
    ['邻居 IP', 'neighbor_ip'], ['关联状态', 'association_status'], ['采集时间', 'collected_at'],
  ],
  configuration: [
    ['快照 ID', 'snapshot_id'], ['配置类型', 'snapshot_type'], ['时间', 'timestamp'], ['大小', 'size_bytes'], ['文件名', 'filename'],
    ['SHA-256', 'sha256'], ['Artifact', 'artifact_id'], ['错误摘要', 'error_summary'], ['创建时间', 'created_at'],
  ],
  tasks: [
    ['任务 ID', 'task_id'], ['任务类型', 'task_type'], ['任务', 'task_name'], ['状态', 'status'], ['阶段', 'stage'], ['消息', 'message'],
    ['耗时（秒）', 'duration_seconds'], ['创建时间', 'created_at'], ['开始时间', 'started_at'], ['完成时间', 'finished_at'], ['错误摘要', 'error_summary'],
  ],
  business: [
    ['业务类型', 'association_type'], ['关联标识', 'association_id'], ['业务对象', 'name'], ['状态', 'status'], ['本地接口', 'local_interface'],
    ['邻居地址', 'peer_address'], ['链路状态', 'trackside_link_status'], ['交换机接收功率', 'switch_rx_power'], ['AP 接收功率', 'ap_rx_power'],
    ['AC MAC', 'ac_mac'], ['光模块状态', 'optical_status'], ['光模块接收功率', 'optical_rx_power'],
    ['MR 站点', 'mr_site_id'], ['更新时间', 'updated_at'],
  ],
}

const selectedDetailFields = computed<DetailField[]>(() => {
  const record = selectedRecord.value
  if (!record) return []
  if (selectedRecordSection.value === 'interfaces' && record.interface) {
    const interfaceRecord = record.interface as DeviceDetailRecord
    const transceiver = record.transceiver as DeviceDetailRecord | null
    const neighbors = Array.isArray(record.lldp_neighbors) ? record.lldp_neighbors : []
    return [
      ...((detailFieldsBySection.interfaces ?? []).map(([label, key]) => ({ label, key, value: interfaceRecord[key], context: interfaceRecord }))),
      { label: '光模块型号', key: 'module_model', value: transceiver?.module_model, context: transceiver ?? {} },
      { label: '光模块严重性', key: 'severity', value: transceiver?.severity, context: transceiver ?? {} },
      { label: 'LLDP 邻居数', key: 'lldp_neighbor_count', value: neighbors.length, context: record },
      { label: 'LLDP 结果截断', key: 'lldp_truncated', value: record.lldp_truncated, context: record },
      { label: '来源', key: 'source', value: (record.source as DeviceDetailSource | undefined)?.source, context: record },
    ]
  }
  const fields = detailFieldsBySection[selectedRecordSection.value] ?? []
  return fields.map(([label, key]) => ({ label, key, value: record[key], context: record }))
})

function formatDetailValue(key: string, value: unknown, context: DeviceDetailRecord): string {
  if (Array.isArray(value)) return value.length ? value.map((item) => formatEnumeratedValue(key, item, context)).join(', ') : '—'
  if (value && typeof value === 'object') return '—'
  return formatEnumeratedValue(key, value, context)
}

function toggleConfigurationSelection(snapshotId: number, checked: boolean): void {
  if (checked) {
    configurationSelection.value = [...configurationSelection.value.filter((id) => id !== snapshotId), snapshotId].slice(-2)
  } else {
    configurationSelection.value = configurationSelection.value.filter((id) => id !== snapshotId)
  }
}

function toDeviceTaskReference(task: ConfigTaskReference): DeviceTaskReference {
  return {
    task_id: task.id,
    task_status: task.status,
    action: task.type,
    artifact_id: '',
    available: false,
    sha256: '',
    size_bytes: 0,
    message: task.message,
  }
}

async function compareConfigurationSnapshots(): Promise<void> {
  if (configurationSelection.value.length !== 2) {
    ElMessage.warning('请选择两个配置快照进行比较')
    return
  }
  try {
    const [leftSnapshotId, rightSnapshotId] = configurationSelection.value
    const task = await submitSnapshotConfigDiff(leftSnapshotId, rightSnapshotId)
    await presentTasks([toDeviceTaskReference(task)], '配置快照比较任务已提交')
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '配置快照比较任务提交失败'))
  }
}

async function downloadConfigurationArtifact(row: DeviceDetailRecord): Promise<void> {
  const artifactId = recordText(row, 'artifact_id')
  if (!artifactId) {
    ElMessage.warning('该快照暂无可下载 Artifact')
    return
  }
  const result = await downloadBackendResource(configArtifactDownloadRequest(artifactId, recordText(row, 'filename') || `snapshot-${recordText(row, 'snapshot_id')}.cfg`))
  if (result.status === 'failed') ElMessage.error(result.error || '配置 Artifact 下载失败')
  else if (result.status === 'saved' && 'capabilityId' in result && typeof result.capabilityId === 'string') {
    savedArtifactCapability.value = result.capabilityId
    ElMessage.success('配置 Artifact 已保存')
  }
}

async function openSavedArtifact(reveal: boolean): Promise<void> {
  if (!savedArtifactCapability.value) return
  const result = reveal
    ? await getPlatformAdapter().showItemInFolder(savedArtifactCapability.value)
    : await getPlatformAdapter().openPath(savedArtifactCapability.value)
  if (!result.success) ElMessage.error(result.error || (reveal ? '定位文件失败' : '打开文件失败'))
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return '—'
  return String(value)
}

const displayEnumLabels: Record<string, Record<string, string>> = {
  severity: {
    normal: '正常',
    notice: '注意',
    warning: '警告',
    alarm: '告警',
    critical: '严重告警',
    unknown: '未知',
    no_light: '无光',
    no_module: '无模块',
    link_abnormal: '链路异常',
    link_down: '链路中断',
    offline: '离线',
    not_collected: '未采集',
    skipped: '已跳过',
  },
  association_status: {
    matched: '已关联',
    unresolved: '未关联',
  },
  link_status: {
    up: '已连接',
    down: '已断开',
  },
  protocol_status: {
    up: '已启用',
    down: '未启用',
  },
  status: {
    pending: '等待中',
    queued: '已排队',
    starting: '启动中',
    running: '运行中',
    stopping: '停止中',
    succeeded: '已成功',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    aborted: '已中止',
  },
  task_status: {},
}
displayEnumLabels.task_status = displayEnumLabels.status

const exactDisplayValueLabels: Record<string, Record<string, string>> = {
  severity_reason: {
    'optical module is not present': '未检测到光模块',
    'rx power is missing or <= -35 dbm': '接收功率缺失或不高于 -35 dBm',
    'port is down': '端口已断开',
    'rx threshold is missing': '接收功率阈值缺失',
    'rx power is above maintenance normal line': '接收功率高于维护正常线',
    'rx power is below maintenance normal line': '接收功率低于维护正常线',
    'rx power is between alarm low and warning low threshold': '接收功率介于告警低阈值和警告低阈值之间',
    'rx power below alarm low threshold': '接收功率低于告警低阈值',
  },
}

function formatEnumeratedValue(key: string, value: unknown, context?: DeviceDetailRecord): string {
  if (key === 'severity_reason' && isNormalSeverity(context?.severity)) return '—'
  if (typeof value !== 'string') return formatValue(value)
  const normalizedValue = value.trim().toLowerCase()
  const exactLabel = exactDisplayValueLabels[key]?.[normalizedValue]
  if (exactLabel) return exactLabel
  const label = displayEnumLabels[key]?.[normalizedValue]
  return label ?? formatValue(value)
}

function isNormalSeverity(value: unknown): boolean {
  const normalizedValue = String(value ?? '').trim().toLowerCase()
  return normalizedValue === 'normal' || normalizedValue === '正常'
}

function opticalRxPowerClass(section: DeviceDetailSection, key: string, row: DeviceDetailRecord): string[] {
  if (section !== 'optical' || key !== 'rx_power') return []
  const severity = String(row.severity ?? '').trim().toLowerCase()
  if (['alarm', 'critical', 'no_light', 'no_module', 'link_abnormal', 'link_down', 'offline'].includes(severity)) {
    return ['optical-rx-power', 'is-danger']
  }
  if (['warning', 'notice', 'not_collected', 'skipped'].includes(severity)) {
    return ['optical-rx-power', 'is-warning']
  }
  return ['optical-rx-power']
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function sourceLabel(source: DeviceDataSource | DeviceDetailSource | undefined): string {
  const value = typeof source === 'string' ? source : source?.source
  return { live: '实时', snapshot: '快照', cache: '缓存', unknown: '未知' }[value || 'unknown'] || value || '未知'
}

function sourceReason(source: DeviceDataSource | DeviceDetailSource | undefined): string {
  return typeof source === 'string' ? '—' : formatValue(source?.reason)
}

function statusType(status: DeviceConnectionTest['success']): 'success' | 'danger' | 'info' {
  if (status === true) return 'success'
  if (status === false) return 'danger'
  return 'info'
}

async function copyText(value: unknown): Promise<void> {
  const text = formatValue(value)
  if (text === '—') return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手工选择文本')
  }
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}
</script>

<template>
  <section class="device-detail-panel" :data-mode="mode">
    <div v-loading="loading" class="device-detail-content">
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
      <template v-else-if="overview">
        <header class="detail-heading">
          <div>
            <h2>{{ formatValue(overview.name) }}</h2>
            <p>{{ formatValue(overview.device_uuid) }}</p>
          </div>
          <div class="heading-actions">
            <el-button v-if="mode === 'drawer'" :icon="FolderOpened" @click="emit('terminal', overview.device_uuid)">外部终端</el-button>
            <el-button v-if="mode === 'drawer'" type="primary" :icon="Edit" @click="emit('edit', overview.device_uuid)">编辑</el-button>
            <el-button v-if="mode === 'drawer'" type="primary" plain @click="emit('full-detail')">完整详情</el-button>
          </div>
        </header>

        <el-tabs v-model="selectedSection" class="device-detail-tabs" @tab-change="activateSection">
          <el-tab-pane v-for="section in visibleSections" :key="section" :label="sectionLabels[section]" :name="section">
            <template v-if="section === 'overview'">
              <div class="section-actions">
                <el-button :icon="Refresh" :disabled="!overview.command_profile?.executable" :title="!overview.command_profile?.executable ? `刷新不可用：${formatValue(overview.command_profile?.reason)}` : undefined" @click="refreshAll">刷新全部</el-button>
                <el-button :icon="Refresh" plain @click="refreshCurrentSection">刷新概览</el-button>
              </div>
              <el-alert v-if="!overview.command_profile?.executable" :title="`刷新不可用：${formatValue(overview.command_profile?.reason)}`" type="warning" show-icon :closable="false" />
              <el-descriptions :column="2" border>
                <el-descriptions-item label="名称">{{ formatValue(overview.name) }}</el-descriptions-item>
                <el-descriptions-item label="系统名">{{ formatValue(overview.system_name) }}</el-descriptions-item>
                <el-descriptions-item label="主地址">{{ formatValue(overview.primary_address) }}</el-descriptions-item>
                <el-descriptions-item label="备用地址">{{ formatValue(overview.backup_address) }}</el-descriptions-item>
                <el-descriptions-item label="MAC">{{ formatValue(overview.mac_address) }}</el-descriptions-item>
                <el-descriptions-item label="类型">{{ formatValue(overview.device_type) }}</el-descriptions-item>
                <el-descriptions-item label="站点">{{ formatValue(overview.station) }}</el-descriptions-item>
                <el-descriptions-item label="位置">{{ formatValue(overview.location) }}</el-descriptions-item>
                <el-descriptions-item label="连接状态">{{ formatValue(overview.connection_status) }}</el-descriptions-item>
                <el-descriptions-item label="型号">{{ formatValue(overview.model) }}</el-descriptions-item>
                <el-descriptions-item label="序列号">{{ formatValue(overview.serial_number) }}</el-descriptions-item>
                <el-descriptions-item label="BootROM">{{ formatValue(overview.bootrom_version) }}</el-descriptions-item>
                <el-descriptions-item label="运行时间">{{ formatValue(overview.uptime) }}</el-descriptions-item>
              </el-descriptions>

              <section class="detail-section">
                <h3>平台事实</h3>
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="厂商">{{ formatValue(overview.platform_facts.vendor) }}</el-descriptions-item>
                  <el-descriptions-item label="角色">{{ formatValue(overview.platform_facts.role) }}</el-descriptions-item>
                  <el-descriptions-item label="平台">{{ formatValue(overview.platform_facts.platform) }}</el-descriptions-item>
                  <el-descriptions-item label="软件版本">{{ formatValue(overview.platform_facts.software_version) }}</el-descriptions-item>
                  <el-descriptions-item label="软件主版本">{{ formatValue(overview.platform_facts.software_major) }}</el-descriptions-item>
                  <el-descriptions-item label="事实来源">{{ formatValue(overview.platform_facts.source) }}</el-descriptions-item>
                  <el-descriptions-item label="置信度">{{ formatValue(overview.platform_facts.confidence) }}</el-descriptions-item>
                  <el-descriptions-item label="采集时间">{{ formatTime(overview.platform_facts.collected_at) }}</el-descriptions-item>
                </el-descriptions>
              </section>

              <section class="detail-section">
                <h3>数据元信息</h3>
                <div class="metadata-row"><span>刷新时间：{{ formatTime(overview.snapshot.collected_at) }}</span><span>来源：{{ sourceLabel(overview.snapshot) }}</span><span>可用：{{ formatValue(overview.snapshot.available) }}</span><span>原因：{{ formatValue(overview.snapshot.reason) }}</span></div>
              </section>

              <section class="detail-section">
                <h3>计数与任务事实</h3>
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="接口数">{{ formatValue(overview.counts.interfaces) }}</el-descriptions-item>
                  <el-descriptions-item label="光模块数">{{ formatValue(overview.counts.transceivers) }}</el-descriptions-item>
                  <el-descriptions-item label="LLDP 邻居数">{{ formatValue(overview.counts.lldp_neighbors) }}</el-descriptions-item>
                  <el-descriptions-item label="配置快照数">{{ formatValue(overview.counts.config_snapshots) }}</el-descriptions-item>
                  <el-descriptions-item label="最近任务数">{{ formatValue(overview.task_facts.recent_task_count) }}</el-descriptions-item>
                  <el-descriptions-item label="活跃任务数">{{ formatValue(overview.task_facts.active_task_count) }}</el-descriptions-item>
                  <el-descriptions-item label="最近运行任务">{{ formatValue(overview.task_facts.latest_running_task?.task_id) }}</el-descriptions-item>
                  <el-descriptions-item label="最近成功任务">{{ formatValue(overview.task_facts.latest_successful_task?.task_id) }}</el-descriptions-item>
                  <el-descriptions-item label="最近失败任务">{{ formatValue(overview.task_facts.latest_failed_task?.task_id) }}</el-descriptions-item>
                  <el-descriptions-item label="最新错误">{{ formatValue(overview.task_facts.latest_error) }}</el-descriptions-item>
                  <el-descriptions-item label="数据截断">{{ formatValue(overview.task_facts.truncated) }}</el-descriptions-item>
                </el-descriptions>
              </section>

              <section class="detail-section">
                <h3>命令画像</h3>
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="画像标识">{{ formatValue(overview.command_profile.capability_id) }}</el-descriptions-item>
                  <el-descriptions-item label="可用">{{ formatValue(overview.command_profile.available) }}</el-descriptions-item>
                  <el-descriptions-item label="可执行">{{ formatValue(overview.command_profile.executable) }}</el-descriptions-item>
                  <el-descriptions-item label="来源">{{ formatValue(overview.command_profile.source) }}</el-descriptions-item>
                  <el-descriptions-item label="画像 ID">{{ formatValue(overview.command_profile.profile_id) }}</el-descriptions-item>
                  <el-descriptions-item label="画像版本">{{ formatValue(overview.command_profile.profile_version) }}</el-descriptions-item>
                  <el-descriptions-item label="兼容性">{{ formatValue(overview.command_profile.compatibility) }}</el-descriptions-item>
                  <el-descriptions-item label="风险">{{ formatValue(overview.command_profile.risk) }}</el-descriptions-item>
                  <el-descriptions-item label="设备状态">{{ formatValue(overview.command_profile.real_device_status) }}</el-descriptions-item>
                  <el-descriptions-item label="原因">{{ formatValue(overview.command_profile.reason) }}</el-descriptions-item>
                </el-descriptions>
              </section>

              <section class="detail-section">
                <h3>能力事实</h3>
                <el-table :data="overview.capabilities" size="small" empty-text="暂无能力事实">
                  <el-table-column prop="capability_id" label="能力标识" min-width="220" />
                  <el-table-column label="可用" width="80"><template #default="{ row }">{{ formatValue(row.available) }}</template></el-table-column>
                  <el-table-column label="可执行" width="90"><template #default="{ row }">{{ formatValue(row.executable) }}</template></el-table-column>
                  <el-table-column prop="source" label="来源" min-width="130" />
                  <el-table-column prop="profile_id" label="画像 ID" min-width="140" />
                  <el-table-column prop="profile_version" label="画像版本" width="100" />
                  <el-table-column prop="compatibility" label="兼容性" min-width="130" />
                  <el-table-column prop="risk" label="风险" min-width="110" />
                  <el-table-column prop="real_device_status" label="设备状态" min-width="140" />
                  <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
                </el-table>
              </section>

              <section v-if="connectionTest" class="detail-section">
                <h3>连接测试</h3>
                <div class="section-actions"><el-button link @click="openTaskWindow(connectionTest?.task_id || '')">打开任务窗口</el-button></div>
                <el-alert v-if="connectionTest" :title="`${formatValue(connectionTest.protocol)} · ${formatValue(connectionTest.task_status)} · ${formatValue(connectionTest.message)}`" :type="statusType(connectionTest.success)" :description="`Task ID: ${formatValue(connectionTest.task_id)}${connectionTest.suggestion ? `；建议：${connectionTest.suggestion}` : ''}`" show-icon :closable="false" />
              </section>
            </template>

            <template v-else>
              <div class="section-toolbar">
                <el-input v-if="['interfaces', 'optical', 'lldp'].includes(section)" v-model="sectionQuery.search" clearable placeholder="搜索当前分区" @keyup.enter="loadSection(section, true)" />
                <el-select v-if="section === 'optical'" v-model="sectionQuery.severity" clearable placeholder="全部严重性" @change="loadSection(section, true)"><el-option v-for="option in getSectionFilterOptions(section)" :key="option.value" :label="option.label" :value="option.value" /></el-select>
                <el-select v-else-if="['interfaces', 'tasks'].includes(section) && getSectionFilterOptions(section).length" v-model="sectionQuery.status" clearable placeholder="全部状态" @change="loadSection(section, true)"><el-option v-for="option in getSectionFilterOptions(section)" :key="option.value" :label="option.label" :value="option.value" /></el-select>
                <el-checkbox v-if="section === 'lldp'" v-model="sectionQuery.linked_only" @change="loadSection(section, true)">仅已关联</el-checkbox>
                <el-select v-if="section === 'configuration'" v-model="sectionQuery.snapshot_type" clearable placeholder="全部快照" @change="loadSection(section, true)"><el-option v-for="option in getSectionFilterOptions(section)" :key="option.value" :label="option.label" :value="option.value" /></el-select>
                <el-button v-if="section === 'configuration'" :disabled="configurationSelection.length !== 2" @click="compareConfigurationSnapshots">比较选中</el-button>
                <el-button v-if="section === 'configuration' && savedArtifactCapability" @click="openSavedArtifact(false)">打开 Artifact</el-button>
                <el-button v-if="section === 'configuration' && savedArtifactCapability" @click="openSavedArtifact(true)">所在目录</el-button>
                <el-button :icon="Refresh" :loading="sectionLoading[section]" @click="refreshCurrentSection">刷新</el-button>
              </div>
              <el-alert v-if="sectionErrors[section]" :title="sectionErrors[section]" type="error" show-icon :closable="false" />
              <div class="section-metadata"><span>刷新时间：{{ formatTime(currentPage?.fetched_at) }}</span><span>来源：{{ sourceLabel(currentPage?.source) }}</span><span>任务：{{ formatValue(currentPage?.task_id) }}</span><span v-if="currentPage?.truncated">结果已截断：{{ sourceReason(currentPage?.source) }}</span></div>
              <el-table v-loading="sectionLoading[section]" :data="currentRows" :height="sectionTableHeight" :max-height="sectionTableMaxHeight" empty-text="暂无数据">
                <el-table-column v-if="section === 'configuration'" label="选择" width="70" fixed="left"><template #default="{ row }"><el-checkbox :model-value="configurationSelection.includes(Number(row.snapshot_id))" @change="(checked: boolean) => toggleConfigurationSelection(Number(row.snapshot_id), checked)" /></template></el-table-column>
                <el-table-column v-for="column in currentColumns" :key="column.key" :prop="column.key" :label="column.label" :width="column.width" :min-width="column.minWidth" :fixed="column.fixed ? 'left' : false" show-overflow-tooltip>
                  <template #default="{ row }"><span :class="opticalRxPowerClass(section, column.key, row)">{{ formatEnumeratedValue(column.key, row[column.key], row) }}</span></template>
                </el-table-column>
                <el-table-column v-if="['interfaces', 'optical', 'lldp', 'configuration', 'tasks'].includes(section)" label="操作" width="220" fixed="right">
                  <template #default="{ row }">
                    <el-button v-if="['interfaces', 'optical', 'lldp'].includes(section)" link :icon="View" @click="openHistory(section, row)">历史</el-button>
                    <el-button v-if="section !== 'tasks'" link :icon="CopyDocument" @click="openRowDetail(section, row)">详情</el-button>
                    <el-button v-if="section === 'tasks'" link @click="openTaskWindow(recordText(row, 'task_id'))">任务中心</el-button>
                    <el-button v-if="section === 'configuration'" link @click="downloadConfigurationArtifact(row)">下载</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-pagination v-if="currentPage?.total" :current-page="currentPage.page" :page-size="currentPage.page_size" :total="currentPage.total" :page-sizes="[20, 50, 100, 200]" layout="total, sizes, prev, pager, next" @current-change="(page: number) => { sectionQuery.page = page; loadSection(section) }" @size-change="(size: number) => { sectionQuery.page_size = size; sectionQuery.page = 1; loadSection(section) }" />
            </template>
          </el-tab-pane>
        </el-tabs>
      </template>
    </div>

    <el-dialog v-model="historyVisible" :title="`历史数据 · ${formatValue(historyPage?.object_name)}`" width="min(1180px, 96vw)">
      <div v-loading="historyLoading">
        <el-table :data="historyPage?.items || []" max-height="620" empty-text="暂无历史数据">
          <el-table-column v-for="column in historyColumns" :key="column[1]" :label="column[0]" :prop="column[1]" min-width="140" show-overflow-tooltip><template #default="{ row }">{{ formatEnumeratedValue(column[1], row[column[1]], row) }}</template></el-table-column>
        </el-table>
        <el-pagination v-if="historyPage?.total" :current-page="historyPage.page" :page-size="historyPage.page_size" :total="historyPage.total" layout="total, prev, pager, next" @current-change="loadHistoryPage" @size-change="changeHistoryPageSize" />
      </div>
      <template #footer><el-button @click="historyVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="recordDetailVisible" title="详情" width="min(760px, 94vw)">
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="field in selectedDetailFields" :key="field.label" :label="field.label">{{ formatDetailValue(field.key, field.value, field.context) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </section>
</template>

<style scoped>
.device-detail-panel { min-width: 0; }
.device-detail-content { min-height: 280px; }
.detail-heading { position: sticky; z-index: 5; top: 0; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: -1px 0 16px; padding: 10px 0; background: var(--nc-bg-card); border-bottom: 1px solid var(--nc-border-light); }
.detail-heading h2, .detail-section h3 { margin: 0; }
.detail-heading p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 12px; }
.heading-actions, .section-actions, .section-toolbar, .metadata-row, .section-metadata { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.section-actions { margin-bottom: 14px; }
.detail-section { margin-top: 22px; }
.detail-section h3 { margin-bottom: 11px; font-size: 15px; }
.section-toolbar { margin-bottom: 12px; }
.section-toolbar .el-input { width: min(320px, 100%); }
.section-toolbar .el-select { width: 150px; }
.metadata-row, .section-metadata { margin: 10px 0; color: var(--el-text-color-secondary); font-size: 12px; }
.optical-rx-power.is-danger { color: var(--nc-danger); font-weight: 600; }
.optical-rx-power.is-warning { color: var(--nc-warning); font-weight: 600; }
.device-detail-panel :deep(.el-pagination) { justify-content: flex-end; padding: 14px 0 0; }
.record-detail { max-height: 60vh; margin: 0; padding: 12px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: var(--el-fill-color-light); border-radius: 6px; font: 12px/1.5 Consolas, "Microsoft YaHei", monospace; }
@media (max-width: 760px) {
  .detail-heading { align-items: flex-start; flex-direction: column; }
  .heading-actions { width: 100%; }
  .section-toolbar .el-input, .section-toolbar .el-select { width: 100%; }
}
</style>
