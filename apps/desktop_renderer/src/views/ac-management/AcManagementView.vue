<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Download, Refresh, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import { getAcApCurrentLldp, getAcApHistory } from '../../api/acManagement'
import { listStations } from '../../api/railTransitBaseData'
import {
  confirmAcActionPlan,
  createAcActionPlan,
  executeAcActionPlan,
  getAcActionAudit,
  getAcActionPlan,
  acFitApResourceArtifactDownloadRequest,
  startAcFitApResourceExport,
} from '../../api/acWebParity'
import type { AcFitApResourceExportScope } from '../../api/acWebParity'
import { isFeatureEnabled } from '../../features'
import { downloadBackendResource, getPlatformAdapter, getRuntimeConfig } from '../../platform/runtime'
import { useAcManagementStore } from '../../stores/acManagement'
import { useConfirm } from '../../components/feedback/useConfirm'
import { useTaskStore } from '../../stores/tasks'
import { t } from '../../i18n/runtime'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { useExternalTerminalLauncher } from '../../composables/useExternalTerminalLauncher'
import NcDataTable from '../../components/table/NcDataTable.vue'
import ConfigDiffViewer from '../../components/config-diff/ConfigDiffViewer.vue'
import type { NcDataTableContextMenuItem } from '../../components/table/NcDataTableContextMenu'
import type { NcColumnValueType, NcTableColumn } from '../../components/table/NcTableColumn'
import AcOmniPeekExportDialog from './AcOmniPeekExportDialog.vue'
import type { AcAp, AcApHistoryPage, AcConfigSnapshot, AcCurrentLldp, AcOptical, AcRadio } from '../../types/acManagement'
import type { Station } from '../../types/railTransitBaseData'
import type {
  AcActionAudit,
  AcActionPlan,
  AcWebTask,
} from '../../types/acWebParity'
import { displayInterfaceName } from '../../utils/interfaceName'
import {
  apOpticalStatusPresentation,
  dualOpticalReason,
  dualOpticalStatusPresentation,
  formatOpticalPower,
  opticalStatusPresentation,
  opticalValuePresentation,
} from '../../utils/opticalPresentation'
import { acConfigDiffModel } from './configDiffAdapter'

const store = useAcManagementStore()
const taskStore = useTaskStore()
const route = useRoute()
const { confirm } = useConfirm()
const userSelectedExport = useUserSelectedExport()
const {
  busy: terminalLoading,
  fitApTerminalVisible: terminalVisible,
  fitApTerminalType: terminalType,
  fitApTerminalOptions: terminalOptions,
  requestFitApTerminal,
  launchSelectedFitApTerminal,
} = useExternalTerminalLauncher()
const activeTab = ref('aps')
const detailVisible = ref(false)
const configVisible = ref(false)
const configSearch = ref('')
const currentMatch = ref(-1)
const selectedApIds = ref(new Set<string>())
const desktopHost = computed(() => getRuntimeConfig().hostType === 'electron')
const pollingConsumer = 'ac-management-view'
const metadataForm = reactive({ station_id: '', station_override_enabled: false, site_name: '', mileage: '', location_note: '', direction: '' })
const stations = ref<Station[]>([])
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const historyPage = ref<AcApHistoryPage | null>(null)
const historyKind = ref<'radio' | 'lldp' | 'optical'>('radio')
const currentLldpRows = ref<AcCurrentLldp[]>([])
const currentLldpLoading = ref(false)
const currentLldpError = ref('')
const actionPlanStorageKey = 'netconsole.ac-management.action-plan'
const actionPlan = ref<AcActionPlan | null>(null)
const actionAudit = ref<AcActionAudit | null>(null)
const actionDialogVisible = ref(false)
const actionLoading = reactive<Record<'persist_auto_ap' | 'enable_ap_remote_login', boolean>>({ persist_auto_ap: false, enable_ap_remote_login: false })
const omniPeekVisible = ref(false)
const omniPeekScopeIds = ref<string[]>([])
const resourceExportBusy = ref(false)
const resourceExportSaving = ref(false)
const lastResourceExportTask = ref<AcWebTask | null>(null)
const historyTitle = computed(() => ({ radio: 'Radio 历史', lldp: 'LLDP 历史', optical: '光衰历史' }[historyKind.value]))

function acColumn<Row extends object>(
  key: string,
  label: string,
  valueType: NcColumnValueType = 'text',
  options: Partial<NcTableColumn<Row>> = {},
): NcTableColumn<Row> {
  return { key, label, valueType, ...options }
}

const columns: NcTableColumn<AcAp>[] = [
  acColumn('selection', '', 'selection', { fixed: 'left', hideable: false }),
  acColumn('name', 'AP 名称', 'name', { sortable: 'custom', fixed: 'left' }),
  acColumn('ip', 'AP IP', 'ip', { sortable: 'custom' }),
  acColumn('mac', 'AP MAC', 'mac'),
  acColumn('status', '状态', 'status', { sortable: 'custom', cellKind: 'tag' }),
  acColumn('model', '型号', 'name'),
  acColumn('radio1_status', 'Mesh Radio 1 状态', 'status'),
  acColumn('radio2_status', 'Mesh Radio 2 状态', 'status'),
  acColumn('radio1_channel', 'Mesh Radio 1 信道', 'number'),
  acColumn('radio2_channel', 'Mesh Radio 2 信道', 'number'),
  acColumn('radio1_power', 'Mesh Radio 1 功率', 'number'),
  acColumn('radio2_power', 'Mesh Radio 2 功率', 'number'),
  acColumn('switch_name', '连接交换机', 'name'),
  acColumn('switch_interface', '连接端口', 'port', { displayValue: (row) => displayColumnValue('switch_interface', row.switch_interface) }),
  acColumn('lldp_status', 'LLDP 状态', 'status'),
  acColumn('optical_status', '光衰状态', 'status', { sortable: 'custom', cellKind: 'tag' }),
  acColumn('optical_rx_power', 'AP侧收光光衰', 'number', { sortable: 'custom' }),
  acColumn('station', '归属站点', 'text', { sortable: 'custom' }),
  acColumn('section', '归属区间', 'text', { sortable: 'custom' }),
  acColumn('mileage', '里程', 'mileage', { sortable: 'custom' }),
  acColumn('direction', '线路方向'),
  acColumn('updated_at', '最近更新时间', 'datetime', { sortable: 'custom' }),
  acColumn('actions', '操作', 'actions', { cellKind: 'actions', actionLabels: ['详情'] }),
]

const snapshotColumns: NcTableColumn<AcConfigSnapshot>[] = [
  acColumn('timestamp', '采集时间', 'datetime', { displayValue: (row) => formatTime(row.timestamp) }),
  acColumn('ac_name', 'AC 名称', 'name'),
  acColumn('type', '配置类型'),
  acColumn('status', '状态', 'status', { cellKind: 'tag' }),
  acColumn('size_bytes', '文件大小', 'number', { displayValue: (row) => formatBytes(row.size_bytes) }),
  acColumn('path_id', '路径标识'),
  acColumn('error_summary', '错误摘要', 'error', { align: 'left', alignmentReason: 'long-text' }),
  acColumn('actions', '只读操作', 'actions', { cellKind: 'actions', actionLabels: ['查看', '对比'] }),
]

const radioColumns: NcTableColumn<AcRadio>[] = [
  acColumn('radio_id', 'Mesh Radio ID', 'number'), acColumn('status', '状态', 'status'),
  acColumn('mode', '模式'), acColumn('band', '频段'), acColumn('channel', '信道', 'number'),
  acColumn('bandwidth', '带宽', 'rate'), acColumn('usage', '利用率 (%)', 'percentage'),
  acColumn('tx_power', '功率', 'number'), acColumn('clients', '客户端', 'number'), acColumn('bssid', 'BSSID', 'mac'),
]
const currentLldpColumns: NcTableColumn<AcCurrentLldp>[] = [
  acColumn('collected_at', '采集时间', 'datetime'),
  acColumn('local_interface', '本地接口', 'port', { displayValue: (row) => displayColumnValue('local_interface', row.local_interface) }),
  acColumn('lldp_neighbor', 'LLDP 邻居', 'name'),
  acColumn('neighbor_device_name', '交换机', 'name'),
  acColumn('neighbor_interface', '交换机端口', 'port', { displayValue: (row) => displayColumnValue('neighbor_interface', row.neighbor_interface) }),
  acColumn('neighbor_mac', '邻居 MAC', 'mac'),
  acColumn('source', '来源'),
]
const detailRadios = computed(() => (store.selected?.radios || []).filter((radio) => radio.radio_id <= 2))
const configLines = computed(() => (store.configContent?.content || '').split('\n'))
const sharedConfigDiff = computed(() => store.configDiff ? acConfigDiffModel(store.configDiff) : null)
const taskActive = computed(() => !!store.refreshTask && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(store.refreshTask.status))
const actionTaskActive = computed(() => !!store.actionTask && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(store.actionTask.status))
const acActionConflict = computed(() => actionTaskActive.value && store.actionTask?.target_id === store.filters.ac_id)
const currentActionLoading = computed(() => {
  const actionId = actionPlan.value?.action_id
  return actionId === 'persist_auto_ap' || actionId === 'enable_ap_remote_login' ? actionLoading[actionId] : false
})
const historyColumns = computed<NcTableColumn<Record<string, unknown>>[]>(() => ({
  radio: [
    ['collected_at', '采集时间'], ['ap_name', 'AP 名称'], ['rid', 'Radio ID'], ['status', '状态'], ['mode', '模式'], ['band', '频段'],
    ['channel', '信道'], ['bandwidth', '带宽'], ['usage', '利用率'], ['tx_power', '功率'], ['clients', '客户端'], ['bbssid', 'BSSID'],
  ],
  lldp: [
    ['collected_at', '采集时间'], ['source', '来源'], ['is_changed', '是否变化'], ['conflict_flag', '冲突'],
    ['local_interface', '本地接口'], ['lldp_neighbor', 'LLDP 邻居'], ['neighbor_interface', '邻居接口'],
    ['neighbor_mac', '邻居 MAC'], ['neighbor_device_name', '邻居设备'], ['neighbor_name', '邻居名称'],
  ],
  optical: [
    ['collected_at', '采集时间'], ['interface_name', '接口'], ['optical_alarm_status', '告警'], ['temperature', '温度'],
    ['voltage', '电压'], ['bias_current', '偏置电流'], ['tx_power', 'Tx Power'], ['rx_power', 'Rx Power'],
    ['rx_low_alarm', 'Rx 低告警'], ['rx_high_alarm', 'Rx 高告警'], ['tx_low_alarm', 'Tx 低告警'], ['tx_high_alarm', 'Tx 高告警'],
    ['rx_low_warning', 'Rx 低预警'], ['rx_high_warning', 'Rx 高预警'], ['tx_low_warning', 'Tx 低预警'], ['tx_high_warning', 'Tx 高预警'],
    ['module_model', '模块型号'], ['module_vendor', '厂商'],
    ['wavelength', '波长'], ['transmission_distance', '传输距离'], ['connector_type', '连接器'], ['status', '状态'], ['error_message', '错误'],
  ],
}[historyKind.value] as string[][]).map(([key, label]) => acColumn(key, label, key === 'collected_at' ? 'datetime' : key.includes('interface') ? 'port' : key.includes('mac') || key === 'bbssid' ? 'mac' : key.includes('error') ? 'error' : 'text', {
  displayValue: (row) => displayColumnValue(key, row[key]),
  ...(key.includes('error') ? { align: 'left' as const, alignmentReason: 'long-text' } : {}),
})))
const matchingLines = computed(() => {
  const needle = configSearch.value.trim().toLowerCase()
  if (!needle) return []
  return configLines.value.flatMap((line, index) => (line.toLowerCase().includes(needle) ? [index] : []))
})
const fitApContextMenuItems = computed<NcDataTableContextMenuItem<AcAp>[]>(() => [
  { key: 'detail', label: t('ac.context.detail', '查看详情'), action: ({ row }) => openDetail(row) },
  {
    key: 'external-terminal',
    label: t('ac.context.external_terminal', '打开外部终端'),
    action: ({ row }) => requestExternalTerminal(row),
    disabled: ({ row }) => Boolean(externalTerminalDisabledReason(row)),
    disabledReason: ({ row }) => externalTerminalDisabledReason(row),
  },
  {
    key: 'refresh-optical',
    label: t('ac.context.refresh_optical', '更新该 AP 光衰'),
    action: ({ row }) => store.startApOpticalRefresh(row.id),
    disabled: taskActive.value,
    disabledReason: taskActive.value ? '当前已有 AC 采集任务运行中' : '',
  },
  { key: 'copy-cell', label: t('ac.context.copy_cell', '复制单元格'), separatorBefore: true, action: ({ cellValue }) => copyText(String(cellValue ?? '')) },
  { key: 'copy-row', label: t('ac.context.copy_row', '复制整行'), action: ({ row }) => copyApRow(row) },
])

async function openRouteApDetail(): Promise<void> {
  const acId = typeof route.query.ac_id === 'string' ? route.query.ac_id : ''
  const apId = typeof route.query.ap === 'string' ? route.query.ap : ''
  if (!apId) {
    detailVisible.value = false
    return
  }
  if (acId && store.filters.ac_id !== acId) {
    store.filters.ac_id = acId
    await store.refreshAps()
  }
  await openDetailById(apId)
}

watch(() => [route.query.ac_id, route.query.ap], () => { void openRouteApDetail() })

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  store.startPolling()
  taskStore.acquirePolling(pollingConsumer)
  void openRouteApDetail()
  void recoverActionPlan()
  void loadStations()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
  taskStore.releasePolling(pollingConsumer)
})

function handleVisibility(): void {
  if (document.hidden) {
    store.stopPolling()
    taskStore.releasePolling(pollingConsumer)
  } else {
    store.startPolling()
    taskStore.acquirePolling(pollingConsumer)
  }
}

function clearFilters(): void {
  Object.assign(store.filters, {
    query: '',
    status: '',
    station: '',
    section: '',
    model: '',
    switch: '',
    optical_status: '',
    sort_by: 'topology',
    sort_order: 'asc',
  })
  store.applyFilters()
}

function setApSelected(apId: string, selected: boolean): void {
  const next = new Set(selectedApIds.value)
  if (selected) next.add(apId)
  else next.delete(apId)
  selectedApIds.value = next
}

function selectCurrentPage(): void {
  const next = new Set(selectedApIds.value)
  for (const ap of store.aps) next.add(ap.id)
  selectedApIds.value = next
}

function invertCurrentPage(): void {
  const next = new Set(selectedApIds.value)
  for (const ap of store.aps) {
    if (next.has(ap.id)) next.delete(ap.id)
    else next.add(ap.id)
  }
  selectedApIds.value = next
}

async function exportFitApResources(command: string): Promise<void> {
  if (!['filtered', 'selected', 'all'].includes(command)) return
  const scope = command as AcFitApResourceExportScope
  if (!store.filters.ac_id) {
    ElMessage.warning(t('ac.fit_ap_resource.select_ac', '请先选择 AC'))
    return
  }
  if (scope === 'selected' && !selectedApIds.value.size) {
    ElMessage.warning(t('ac.fit_ap_resource.select_ap', '请先选择要导出的 FIT-AP'))
    return
  }
  if (resourceExportBusy.value) return
  resourceExportBusy.value = true
  try {
    const acId = store.filters.ac_id
    const apIds = scope === 'selected' ? [...selectedApIds.value] : []
    const exportFilters = scope === 'filtered'
      ? {
          query: store.filters.query,
          status: store.filters.status,
          optical_status: store.filters.optical_status,
          station: store.filters.station,
          section: store.filters.section,
          model: store.filters.model,
          switch: store.filters.switch,
        }
      : {}
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'ac.fit_ap_resources',
      suggestedName: `${safeExportPart(store.activeAc?.name || 'AC')}-FIT-AP资源-${exportTimestamp()}.xlsx`,
      context: { acId, scope, selectedCount: apIds.length },
      submit: () => startAcFitApResourceExport(acId, scope, apIds, exportFilters),
    })
    if (result.status === 'cancelled') return
    lastResourceExportTask.value = result.task
    ElMessage.success('FIT-AP 资源导出任务已创建，完成后将写入所选位置')
    await taskStore.refresh()
  } catch (cause) {
    ElMessage.error(safeError(cause, t('ac.fit_ap_resource.failed', 'FIT-AP 资源导出失败')))
  } finally {
    resourceExportBusy.value = false
    void taskStore.refresh()
  }
}

async function saveResourceExportArtifact(): Promise<void> {
  const task = lastResourceExportTask.value
  if (!task?.available || !task.artifact_id || resourceExportSaving.value) return
  resourceExportSaving.value = true
  try {
    const result = await downloadBackendResource(acFitApResourceArtifactDownloadRequest(task))
    if (result.status === 'saved') {
      ElMessage.success(resourceExportText(
        'ac.fit_ap_resource.saved',
        'FIT-AP 资源已保存：{fileName}',
        { fileName: result.fileName || task.artifact_name || '' },
      ))
    } else if (result.status === 'started') {
      ElMessage.success(t('ac.fit_ap_resource.browser_started', 'FIT-AP 资源已交给浏览器下载'))
    } else if (result.status === 'cancelled') {
      ElMessage.info(t('ac.fit_ap_resource.save_cancelled', '已取消保存，导出文件仍保留在任务中心'))
    } else {
      ElMessage.error(result.error || t(
        'ac.fit_ap_resource.save_failed_retry',
        '本地保存失败，导出文件仍保留在任务中心，可再次保存',
      ))
    }
  } catch (cause) {
    ElMessage.error(resourceExportText(
      'ac.fit_ap_resource.save_failed_detail',
      '{error}；导出文件仍保留在任务中心，可再次保存',
      { error: safeError(cause, t('ac.fit_ap_resource.save_failed', '本地保存失败')) },
    ))
  } finally {
    resourceExportSaving.value = false
  }
}

async function deleteSelectedAps(): Promise<void> {
  const apIds = [...selectedApIds.value]
  if (!apIds.length) return
  try {
    if (!await confirm({ type: 'DESTRUCTIVE', title: '批量删除 FIT-AP', message: `确认从当前 AC 资源库删除选中的 ${apIds.length} 个 FIT-AP 及其关联光衰/元数据？`, confirmText: '确认删除' })) return
  } catch {
    return
  }
  await store.startFitApDelete(apIds)
  if (store.refreshTask?.action === 'ac_fit_ap_delete_many') selectedApIds.value = new Set()
}

async function openAcWeb(): Promise<void> {
  const url = store.activeAc?.web_url || ''
  if (!url || !desktopHost.value) return
  const result = await getPlatformAdapter().openExternalUrl(url)
  if (!result.success) ElMessage.error(result.error || '无法打开 AC Web 管理地址')
}

async function saveMetadata(): Promise<void> {
  await store.startFitApMetadataSave({ ...metadataForm })
}

async function startVerboseRefresh(scope: 'all' | 'selected'): Promise<void> {
  const ids = scope === 'selected' ? [...selectedApIds.value] : []
  if (scope === 'selected' && !ids.length) {
    ElMessage.warning('请先选择要获取详细信息的 FIT-AP')
    return
  }
  if (scope === 'all') {
    try {
      if (!await confirm({ type: 'WARNING', title: '获取全部 AP 详细信息', message: `当前 AC 约有 ${store.activeAc?.ap_total || store.total} 台 AP，详细回显较大且可能耗时较长，确认继续？`, confirmText: '开始获取' })) return
    } catch {
      return
    }
  }
  await store.startFitApVerbose(scope, ids)
}

async function loadStations(): Promise<void> {
  try {
    const result = await listStations({ page: 1, page_size: 500, sort_order: 'asc' })
    stations.value = result.items.filter((item) => item.enabled !== false)
  } catch {
    stations.value = []
  }
}

function adoptAutomaticStation(): void {
  const ap = store.selected?.ap
  if (!ap?.auto_station_id) return
  metadataForm.station_id = ap.auto_station_id
  metadataForm.station_override_enabled = true
  metadataForm.site_name = ap.auto_station_name
}

function clearManualStationOverride(): void {
  metadataForm.station_id = ''
  metadataForm.station_override_enabled = false
  metadataForm.site_name = ''
}

async function openHistory(kind: 'radio' | 'lldp' | 'optical', page = 1): Promise<void> {
  if (!store.selected) return
  historyKind.value = kind
  historyVisible.value = true
  historyLoading.value = true
  historyError.value = ''
  try {
    historyPage.value = await getAcApHistory(store.selected.ap.id, kind, page)
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : 'FIT-AP 历史加载失败'
  } finally {
    historyLoading.value = false
  }
}

function handleSort(event: { prop: string; order: 'ascending' | 'descending' | null }): void {
  const sortMap: Record<string, string> = {
    name: 'name',
    ip: 'ip',
    status: 'status',
    station: 'station',
    section: 'section',
    mileage: 'mileage',
    optical_status: 'optical_status',
    optical_rx_power: 'optical_value',
    updated_at: 'updated_at',
  }
  store.filters.sort_by = event.order ? (sortMap[event.prop] || 'topology') : 'topology'
  store.filters.sort_order = event.order === 'descending' ? 'desc' : 'asc'
  store.applyFilters()
}

async function openDetail(row: AcAp): Promise<void> {
  await openDetailById(row.id)
}

async function openDetailById(apId: string): Promise<void> {
  detailVisible.value = true
  currentLldpRows.value = []
  currentLldpError.value = ''
  currentLldpLoading.value = true
  await store.selectAp(apId)
  try {
    currentLldpRows.value = await getAcApCurrentLldp(apId)
  } catch (cause) {
    currentLldpError.value = cause instanceof Error ? cause.message : '当前 LLDP 加载失败'
  } finally {
    currentLldpLoading.value = false
  }
  const ap = store.selected?.ap
  if (ap) Object.assign(metadataForm, {
    station_id: ap.manual_station_id || '',
    station_override_enabled: ap.manual_override_enabled,
    site_name: ap.manual_station_name || '',
    mileage: ap.mileage || '',
    location_note: ap.location_note || '',
    direction: ap.direction || '',
  })
}

async function openConfig(snapshot: AcConfigSnapshot): Promise<void> {
  configVisible.value = true
  configSearch.value = ''
  currentMatch.value = -1
  await store.loadConfig(snapshot.id)
}

async function openDiff(snapshot: AcConfigSnapshot): Promise<void> {
  if (snapshot.status !== 'AVAILABLE' || snapshot.size_bytes <= 0) {
    ElMessage.warning(snapshot.status === 'MISSING' ? '配置快照文件缺失，无法对比' : '配置快照不可读取或内容为空，无法对比')
    return
  }
  configVisible.value = true
  configSearch.value = ''
  currentMatch.value = -1
  await store.loadDiff(snapshot.id)
}

async function nextConfigMatch(): Promise<void> {
  if (!matchingLines.value.length) return
  currentMatch.value = (currentMatch.value + 1) % matchingLines.value.length
  await nextTick()
  document.querySelector(`[data-config-line="${matchingLines.value[currentMatch.value]}"]`)?.scrollIntoView({ block: 'center' })
}

function display(value: unknown): string {
  return value === null || value === undefined || value === '' ? '--' : String(value)
}

function safeExportPart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || 'AC'
}

function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}

async function recoverActionPlan(): Promise<void> {
  const planId = window.localStorage?.getItem(actionPlanStorageKey) || ''
  if (!planId || !isFeatureEnabled('capability.ac.dangerous_actions')) return
  try {
    actionPlan.value = await getAcActionPlan(planId)
    actionAudit.value = await getAcActionAudit(planId)
    if (actionPlan.value.task_id) await store.trackActionTask(actionPlan.value.task_id)
  } catch {
    window.localStorage?.removeItem(actionPlanStorageKey)
  }
}

async function prepareAcAction(actionId: 'persist_auto_ap' | 'enable_ap_remote_login'): Promise<void> {
  if (!store.filters.ac_id || acActionConflict.value) return
  actionLoading[actionId] = true
  try {
    actionPlan.value = await createAcActionPlan(store.filters.ac_id, actionId)
    actionAudit.value = null
    window.localStorage?.setItem(actionPlanStorageKey, actionPlan.value.plan_id)
    actionDialogVisible.value = true
  } catch (cause) {
    ElMessage.error(safeError(cause, t('ac.action.plan_failed', 'AC 动作计划创建失败')))
  } finally {
    actionLoading[actionId] = false
  }
}

async function confirmAndExecuteAcAction(): Promise<void> {
  const plan = actionPlan.value
  if (!plan) return
  actionLoading[plan.action_id as 'persist_auto_ap' | 'enable_ap_remote_login'] = true
  try {
    const confirmed = await confirmAcActionPlan(plan)
    actionPlan.value = await executeAcActionPlan(confirmed.plan_id)
    actionAudit.value = await getAcActionAudit(confirmed.plan_id)
    if (actionPlan.value.task_id) {
      await store.trackActionTask(actionPlan.value.task_id)
      await taskStore.refresh()
    }
    actionDialogVisible.value = false
    ElMessage.success(t('ac.action.task_submitted', 'AC 配置动作任务已提交'))
  } catch (cause) {
    ElMessage.error(safeError(cause, t('ac.action.execute_failed', 'AC 配置动作执行失败')))
  } finally {
    actionLoading[plan.action_id as 'persist_auto_ap' | 'enable_ap_remote_login'] = false
  }
}

async function openOmniPeekPreview(): Promise<void> {
  if (!store.filters.ac_id) return
  omniPeekScopeIds.value = [...selectedApIds.value]
  omniPeekVisible.value = true
}

function externalTerminalDisabledReason(row: AcAp): string {
  if (!desktopHost.value) return t('ac.terminal.desktop_only', '仅桌面版支持打开外部终端')
  if (!isFeatureEnabled('capability.ac.external_terminal') || !isFeatureEnabled('capability.desktop_native_integration')) return '当前功能配置未启用外部终端'
  if (!row.ip) return t('ac.terminal.no_ip', '当前 AP 没有 IP，无法打开外部终端')
  if (row.status !== 'online') return t('ac.terminal.offline', '当前 AP 离线或状态异常，无法打开外部终端')
  return ''
}

async function copyText(value: string): Promise<void> {
  await navigator.clipboard.writeText(value)
  ElMessage.success(t('common.copied', '已复制'))
}

async function copyApRow(row: AcAp): Promise<void> {
  await copyText([row.name, row.ip, row.mac, statusLabel(row.status), row.model, row.station, row.switch_name, row.switch_interface].join('\t'))
}

async function requestExternalTerminal(row: AcAp): Promise<void> {
  const disabledReason = externalTerminalDisabledReason(row)
  if (disabledReason) return void ElMessage.warning(disabledReason)
  await requestFitApTerminal({ apId: row.id, acId: store.filters.ac_id })
}

function safeError(cause: unknown, fallback: string): string {
  const message = cause instanceof Error ? cause.message : fallback
  return message
    .replace(/(password|token)\s*[:=]\s*[^,;\s]+/gi, '$1=***')
    .replace(/[A-Za-z]:\\[^\r\n]+/g, '<本机路径>')
}

function resourceExportText(
  key: string,
  fallback: string,
  values: Record<string, string | number>,
): string {
  return Object.entries(values).reduce(
    (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)),
    t(key, fallback),
  )
}

const interfaceValueKeys = new Set(['switch_interface', 'interface_name', 'local_interface', 'neighbor_interface'])

function displayColumnValue(key: string, value: unknown): string {
  return interfaceValueKeys.has(key) ? display(displayInterfaceName(value)) : display(value)
}

function statusLabel(value: string): string {
  return { online: '在线', offline: '离线', unauthenticated: '未认证', unknown: '无数据' }[value] || value || '无数据'
}

function opticalLabel(value: string, freshness = 'fresh'): string {
  const label = { normal: '正常', warning: '一般告警', critical: '严重告警', no_data: '无数据' }[value] || value
  return freshness === 'stale' ? `${label}（数据已过期）` : label
}

function apOpticalPresentation(ap: AcAp) {
  return apOpticalStatusPresentation({
    backendStatus: ap.optical_status,
    rxPower: ap.optical_rx_power,
    model: ap.model,
    opticalApplicable: ap.optical_applicable,
    freshness: ap.optical_data_freshness,
  })
}

function detailDualOpticalPresentation(optical: AcOptical) {
  const ap = store.selected?.ap
  return dualOpticalStatusPresentation({
    apBackendStatus: optical.ap_rx_status || optical.raw_status || optical.optical_status,
    apRxPower: optical.rx_power,
    switchBackendStatus: optical.switch_rx_status || optical.raw_status || optical.optical_status,
    switchRxPower: optical.switch_rx_power,
    model: ap?.model,
    opticalApplicable: optical.optical_applicable ?? ap?.optical_applicable,
    freshness: optical.data_freshness,
  })
}

function detailApOpticalPresentation(optical: AcOptical) {
  return detailDualOpticalPresentation(optical).overall
}

function detailApOpticalValuePresentation(optical: AcOptical) {
  return opticalValuePresentation(
    detailDualOpticalPresentation(optical).ap.status,
    optical.data_freshness,
  )
}

function detailSwitchOpticalValuePresentation(optical: AcOptical) {
  return opticalValuePresentation(
    detailDualOpticalPresentation(optical).switch.status,
    optical.data_freshness,
  )
}

function detailThresholdPresentation(optical: AcOptical) {
  return opticalValuePresentation(
    detailDualOpticalPresentation(optical).overall.status,
    optical.data_freshness,
  )
}

function opticalAlertTitle(optical: AcOptical): string {
  const ap = store.selected?.ap
  return dualOpticalReason({
    apBackendStatus: optical.ap_rx_status || optical.raw_status || optical.optical_status,
    apRxPower: optical.rx_power,
    switchBackendStatus: optical.switch_rx_status || optical.raw_status || optical.optical_status,
    switchRxPower: optical.switch_rx_power,
    model: ap?.model,
    opticalApplicable: optical.optical_applicable ?? ap?.optical_applicable,
    freshness: optical.data_freshness,
  })
}

function opticalJudgement(optical: AcOptical): string {
  const presentation = detailApOpticalPresentation(optical)
  if (presentation.status === 'not_applicable') return '不适用'
  if (optical.data_freshness === 'stale') return '数据已过期'
  if (presentation.tone === 'danger' || optical.is_current_anomaly) return '异常'
  if (presentation.status === 'not_collected') {
    const dual = detailDualOpticalPresentation(optical)
    return [dual.ap.status, dual.switch.status].includes('normal')
      ? '数据不完整'
      : '光诊断未采集'
  }
  return '正常'
}

function opticalAlarmLevel(optical: AcOptical): string {
  const presentation = detailApOpticalPresentation(optical)
  if (presentation.status === 'not_applicable') return '不适用'
  if (presentation.tone === 'danger') return '严重告警'
  return presentation.label
}

function opticalFreshnessLabel(value: string): string {
  return { fresh: '当前有效', stale: '数据已过期', unknown: '采集时间未知' }[value] || value
}

function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'online' || value === 'normal') return 'success'
  if (value === 'unauthenticated' || value === 'warning') return 'warning'
  if (value === 'offline' || value === 'critical') return 'danger'
  return 'info'
}

function formatTime(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value: number): string {
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

function opticalEvidenceTitle(label: string, value: unknown, status: string, optical: AcOptical): string {
  const lines = [
    `${label}：${formatOpticalPower(value)}`,
    `判定：${opticalStatusPresentation(status).label}`,
    optical.updated_at ? `采集时间：${formatTime(optical.updated_at)}` : '',
    optical.source_switch || optical.source_interface
      ? `来源：${[optical.source_switch, displayInterfaceName(optical.source_interface)].filter(Boolean).join(' / ')}`
      : '',
  ]
  return lines.filter(Boolean).join('\n')
}

</script>

<template>
  <section class="ac-management">
    <div class="page-toolbar">
      <div>
        <h2>{{ store.activeAc?.name || 'AC 管理' }}</h2>
        <p>{{ store.summary?.site_id || '--' }} · 数据源：{{ store.activeAc?.data_source || 'SQLite 已采集数据' }} · 更新于 {{ formatTime(store.summary?.updated_at || '') }}</p>
      </div>
      <div class="toolbar-actions">
        <el-select :model-value="store.filters.ac_id" placeholder="选择 AC" style="width: 220px" @change="store.setAcId">
          <el-option v-for="ac in store.summary?.acs || []" :key="ac.id" :label="`${ac.name} (${ac.management_ip || '--'})`" :value="ac.id" />
        </el-select>
        <el-button
          v-if="isFeatureEnabled('capability.ac.open_management')"
          :disabled="!desktopHost || !store.activeAc?.web_url"
          @click="openAcWeb"
        >打开 AC Web</el-button>
        <el-button :icon="Refresh" :loading="store.loading" @click="store.manualRefresh">刷新已有数据</el-button>
        <el-button :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startAcInfoRefresh">更新 AC 信息</el-button>
        <el-button type="primary" :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startFitApRefresh">更新 FIT-AP 资源</el-button>
        <el-button :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="startVerboseRefresh('all')">获取全部 AP 详细信息</el-button>
        <el-button :icon="Refresh" :loading="store.refreshStarting" :disabled="!selectedApIds.size || taskActive" @click="startVerboseRefresh('selected')">获取已选择 AP 详细信息</el-button>
        <el-button :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startOpticalRefresh">更新光衰</el-button>
        <span v-if="isFeatureEnabled('capability.ac.dangerous_actions')" class="toolbar-separator" aria-hidden="true" />
        <el-button
          v-if="isFeatureEnabled('capability.ac.dangerous_actions')"
          :loading="actionLoading.persist_auto_ap"
          :disabled="!store.filters.ac_id || acActionConflict"
          @click="prepareAcAction('persist_auto_ap')"
        >{{ t('ac.action.persist_auto_ap', '一键固化新上线 AP') }}</el-button>
        <el-button
          v-if="isFeatureEnabled('capability.ac.dangerous_actions')"
          :loading="actionLoading.enable_ap_remote_login"
          :disabled="!store.filters.ac_id || acActionConflict"
          @click="prepareAcAction('enable_ap_remote_login')"
        >{{ t('ac.action.enable_remote_login', '一键开启 AP 远程登入') }}</el-button>
      </div>
    </div>

    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="page-error" />
    <el-empty v-if="store.summary?.message && !store.summary.acs.length" :description="store.summary.message" />

    <el-descriptions v-else-if="store.activeAc" :column="4" border class="ac-info-strip">
      <el-descriptions-item label="AC 型号">{{ display(store.activeAc.model) }}</el-descriptions-item>
      <el-descriptions-item label="软件版本">{{ display(store.activeAc.software_version) }}</el-descriptions-item>
      <el-descriptions-item label="CPU 使用率">{{ display(store.activeAc.cpu_usage) }}</el-descriptions-item>
      <el-descriptions-item label="内存使用率">{{ display(store.activeAc.memory_usage) }}</el-descriptions-item>
      <el-descriptions-item label="管理地址">{{ display(store.activeAc.management_ip) }}</el-descriptions-item>
      <el-descriptions-item label="HTTPS 端口">{{ display(store.activeAc.https_port) }}</el-descriptions-item>
    </el-descriptions>

    <div v-if="store.activeAc" class="summary-grid">
      <article><span>AP 总数</span><strong>{{ store.activeAc?.ap_total || 0 }}</strong></article>
      <article class="success"><span>在线 AP</span><strong>{{ store.activeAc?.online_aps || 0 }}</strong></article>
      <article class="danger"><span>离线 AP</span><strong>{{ store.activeAc?.offline_aps || 0 }}</strong></article>
      <article class="warning"><span>未认证 AP</span><strong>{{ store.activeAc?.unauthenticated_aps || 0 }}</strong></article>
      <article><span>Radio 总数</span><strong>{{ store.activeAc?.radio_total || 0 }}</strong></article>
      <article class="danger"><span>关联光衰异常</span><strong>{{ store.activeAc?.optical_anomalies || 0 }}</strong></article>
    </div>

    <div class="content-card">
      <el-tabs v-model="activeTab" class="ac-tabs">
        <el-tab-pane label="FIT-AP 资源" name="aps">
          <div class="filter-bar">
            <el-input v-model="store.filters.query" clearable placeholder="AP 名称 / IP / MAC" @keyup.enter="store.applyFilters" />
            <el-select v-model="store.filters.status" clearable placeholder="AP 状态">
              <el-option label="在线" value="online" /><el-option label="离线" value="offline" /><el-option label="未认证" value="unauthenticated" />
            </el-select>
            <el-select v-model="store.filters.optical_status" clearable placeholder="光衰状态">
              <el-option label="正常" value="normal" /><el-option label="一般告警" value="warning" /><el-option label="严重告警" value="critical" />
              <el-option label="无数据" value="no_data" />
            </el-select>
            <el-select v-model="store.filters.station" clearable filterable allow-create default-first-option placeholder="归属站点">
              <el-option v-for="option in store.filterOptions.stations" :key="option" :label="option" :value="option" />
            </el-select>
            <el-select v-model="store.filters.section" clearable filterable allow-create default-first-option placeholder="归属区间">
              <el-option v-for="option in store.filterOptions.sections" :key="option" :label="option" :value="option" />
            </el-select>
            <el-select v-model="store.filters.model" clearable filterable allow-create default-first-option placeholder="型号">
              <el-option v-for="option in store.filterOptions.models" :key="option" :label="option" :value="option" />
            </el-select>
            <el-select v-model="store.filters.switch" clearable filterable allow-create default-first-option placeholder="交换机">
              <el-option v-for="option in store.filterOptions.switches" :key="option" :label="option" :value="option" />
            </el-select>
            <el-button type="primary" @click="store.applyFilters">应用筛选</el-button>
            <el-button @click="clearFilters">清除</el-button>
            <el-button @click="selectCurrentPage">选择本页</el-button>
            <el-button @click="invertCurrentPage">反选本页</el-button>
            <el-button :disabled="!selectedApIds.size" @click="selectedApIds = new Set()">清空选择</el-button>
            <el-button
              v-if="isFeatureEnabled('ac.omnipeek_name_table_export')"
              :disabled="!store.filters.ac_id"
              @click="openOmniPeekPreview"
            >{{ t('ac.omnipeek.export', '导出 OmniPeek 名称表') }}</el-button>
            <el-dropdown
              v-if="isFeatureEnabled('capability.ac.fit_ap.resource_export')"
              trigger="click"
              :disabled="!store.filters.ac_id || resourceExportBusy"
              @command="exportFitApResources"
            >
              <el-button
                :icon="Download"
                :loading="resourceExportBusy"
                :disabled="!store.filters.ac_id"
              >{{ t('ac.fit_ap_resource.export', '导出 AP 资源') }}</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="filtered">{{ resourceExportText('ac.fit_ap_resource.scope_filtered', '导出当前筛选结果（{count}）', { count: store.total }) }}</el-dropdown-item>
                  <el-dropdown-item command="selected" :disabled="!selectedApIds.size">{{ resourceExportText('ac.fit_ap_resource.scope_selected', '导出已选择 AP（{count}）', { count: selectedApIds.size }) }}</el-dropdown-item>
                  <el-dropdown-item command="all">{{ resourceExportText('ac.fit_ap_resource.scope_all', '导出当前 AC 全部 AP（{count}）', { count: store.activeAc?.ap_total || 0 }) }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button
              v-if="lastResourceExportTask?.available"
              :icon="Download"
              :loading="resourceExportSaving"
              @click="saveResourceExportArtifact"
            >{{ t('ac.fit_ap_resource.save_again', '再次保存') }}</el-button>
            <el-button
              v-if="isFeatureEnabled('capability.ac.fit_ap.delete')"
              type="danger"
              plain
              :loading="store.refreshStarting"
              :disabled="!selectedApIds.size || taskActive"
              @click="deleteSelectedAps"
            >批量删除（{{ selectedApIds.size }}）</el-button>
          </div>

          <NcDataTable
            v-loading="store.loading"
            table-id="ac-fit-ap-resources"
            route-key="/ac-management"
            :data="store.aps"
            :columns="columns"
            :context-menu-items="fitApContextMenuItems"
            height="calc(100vh - 455px)"
            empty-text="暂无 FIT-AP 资源数据"
            @sort-change="handleSort"
          >
            <template #cell-selection="{ row }"><el-checkbox :model-value="selectedApIds.has(row.id)" @change="setApSelected(row.id, Boolean($event))" /></template>
            <template #cell-status="{ row }"><el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag></template>
            <template #cell-optical_status="{ row }"><el-tag :type="apOpticalPresentation(row).tagType" effect="light">{{ apOpticalPresentation(row).label }}</el-tag></template>
            <template #cell-actions="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button></template>
          </NcDataTable>
          <div class="pagination-row">
            <span>共 {{ store.total }} 条</span>
            <el-pagination
              :current-page="store.filters.page"
              :page-size="store.filters.page_size"
              :page-sizes="[20, 50, 100, 200]"
              layout="sizes, prev, pager, next"
              :total="store.total"
              @current-change="store.setPage"
              @size-change="store.setPageSize"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="配置采集与对比" name="config">
          <div class="config-toolbar">
            <div><h3>配置快照</h3><p>只读取当前局点受控目录；配置正文和差异按选择加载，不轮询大文本。</p></div>
            <div class="toolbar-actions">
              <el-select :model-value="store.snapshotType" clearable placeholder="配置类型" style="width: 145px" @change="store.setSnapshotType">
                <el-option label="运行配置" value="running" /><el-option label="保存配置" value="saved" /><el-option label="差异" value="diff" />
              </el-select>
              <el-button :icon="Refresh" @click="store.refreshSnapshots">刷新历史</el-button>
            </div>
          </div>
          <NcDataTable table-id="ac-config-snapshots" route-key="/ac-management" :data="store.snapshots" :columns="snapshotColumns" empty-text="暂无 AC 配置快照" height="calc(100vh - 405px)">
            <template #cell-status="{ row }"><el-tag :type="row.status === 'AVAILABLE' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'">{{ row.status }}</el-tag></template>
            <template #cell-actions="{ row }"><el-button link type="primary" :disabled="row.status !== 'AVAILABLE'" @click="openConfig(row)">查看</el-button><el-button link type="primary" :disabled="row.status !== 'AVAILABLE' || row.size_bytes <= 0" @click="openDiff(row)">对比</el-button></template>
          </NcDataTable>
          <div class="pagination-row">
            <span>共 {{ store.snapshotTotal }} 条</span>
            <el-pagination :current-page="store.snapshotPage" :page-size="store.snapshotPageSize" layout="prev, pager, next" :total="store.snapshotTotal" @current-change="store.setSnapshotPage" />
          </div>
        </el-tab-pane>

      </el-tabs>
    </div>

    <el-dialog v-model="actionDialogVisible" :title="t('ac.action.confirm_title', '确认 AC 配置动作')" width="min(680px, 94vw)" :close-on-click-modal="false">
      <template v-if="actionPlan && store.activeAc">
        <el-alert type="error" :title="t('ac.action.real_device_warning', '该操作将修改真实 AC 配置')" show-icon :closable="false" />
        <el-descriptions :column="1" border class="action-summary">
          <el-descriptions-item :label="t('ac.action.target', '当前 AC')">{{ store.activeAc.name }}（{{ store.activeAc.management_ip || '--' }}）</el-descriptions-item>
          <el-descriptions-item :label="t('ac.action.name', '动作名称')">{{ actionPlan.action_label }}</el-descriptions-item>
        </el-descriptions>
        <pre class="command-preview">{{ actionPlan.command_summary.join('\n') }}</pre>
      </template>
      <template #footer>
        <el-button @click="actionDialogVisible = false">{{ t('common.cancel', '取消') }}</el-button>
        <el-button type="danger" :loading="currentActionLoading" @click="confirmAndExecuteAcAction">{{ t('ac.action.confirm_execute', '确认并执行真实配置') }}</el-button>
      </template>
    </el-dialog>

    <AcOmniPeekExportDialog
      v-if="store.filters.ac_id"
      v-model="omniPeekVisible"
      :ac-id="store.filters.ac_id"
      :ap-ids="omniPeekScopeIds"
      @task-submitted="taskStore.refresh"
    />

    <el-dialog v-model="terminalVisible" :title="t('ac.terminal.select', '选择外部终端')" width="420px">
      <el-select v-model="terminalType" style="width: 100%"><el-option v-for="option in terminalOptions" :key="option.terminal_type" :label="option.label" :value="option.terminal_type" /></el-select>
      <template #footer><el-button @click="terminalVisible = false">{{ t('common.cancel', '取消') }}</el-button><el-button type="primary" :loading="terminalLoading" @click="launchSelectedFitApTerminal">{{ t('ac.terminal.open', '打开终端') }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="FIT-AP 详情" size="min(920px, 95vw)">
      <div v-loading="store.detailLoading">
        <template v-if="store.selected">
          <div class="detail-heading">
            <div><h2>{{ store.selected.ap.name }}</h2><p>{{ store.selected.ap.ip || '--' }} · {{ store.selected.ap.mac || '--' }}</p></div>
            <div class="toolbar-actions">
              <el-tag :type="statusType(store.selected.ap.status)" size="large">{{ statusLabel(store.selected.ap.status) }}</el-tag>
              <el-button type="primary" :icon="Refresh" :loading="store.refreshStarting" :disabled="taskActive" @click="store.startFitApDetailRefresh">更新当前 AP 详细信息</el-button>
            </div>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="型号">{{ display(store.selected.ap.model) }}</el-descriptions-item>
            <el-descriptions-item label="软件版本">{{ display(store.selected.ap.software_version) }}</el-descriptions-item>
            <el-descriptions-item label="硬件版本">{{ display(store.selected.ap.hardware_version) }}</el-descriptions-item>
            <el-descriptions-item label="Boot 版本">{{ display(store.selected.ap.boot_version) }}</el-descriptions-item>
            <el-descriptions-item label="详细信息更新时间">{{ formatTime(store.selected.ap.detail_updated_at) }}</el-descriptions-item>
            <el-descriptions-item label="上线时长">{{ display(store.selected.ap.online_time) }}</el-descriptions-item>
            <el-descriptions-item label="当前有效归属站点">{{ display(store.selected.ap.effective_station_name || store.selected.ap.station) }}</el-descriptions-item>
            <el-descriptions-item label="关联来源">{{ display(store.selected.ap.station_source_detail || store.selected.ap.station_source) }}</el-descriptions-item>
            <el-descriptions-item label="归属区间">{{ display(store.selected.ap.section) }}</el-descriptions-item>
            <el-descriptions-item label="里程">{{ display(store.selected.ap.mileage) }}</el-descriptions-item>
            <el-descriptions-item label="线路方向">{{ display(store.selected.ap.direction) }}</el-descriptions-item>
          </el-descriptions>

          <div class="metadata-editor">
            <div class="section-heading"><h3>自动关联信息（只读）</h3></div>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="基础资料站点">{{ display(store.selected.ap.auto_station_name) }}</el-descriptions-item>
              <el-descriptions-item label="基础资料 AP">{{ display(store.selected.ap.trackside_ap_name) }}</el-descriptions-item>
              <el-descriptions-item label="LLDP 建议站点">{{ display(store.selected.ap.lldp_suggested_station_name) }}</el-descriptions-item>
              <el-descriptions-item label="AC 原始站点">{{ display(store.selected.ap.resource_station_text) }}</el-descriptions-item>
            </el-descriptions>
            <div class="section-heading"><h3>手工站点覆盖</h3><div class="toolbar-actions"><el-button link type="primary" @click="adoptAutomaticStation" :disabled="!store.selected.ap.auto_station_id">采用自动关联结果</el-button><el-button link type="warning" @click="clearManualStationOverride" :disabled="!metadataForm.station_override_enabled">清除手工覆盖</el-button><el-button v-if="isFeatureEnabled('capability.ac.fit_ap.metadata_write')" type="primary" :loading="store.refreshStarting" :disabled="taskActive" @click="saveMetadata">保存手工覆盖</el-button></div></div>
            <el-form :model="metadataForm" label-width="88px" :disabled="!isFeatureEnabled('capability.ac.fit_ap.metadata_write')">
              <div class="metadata-grid">
                <el-form-item label="归属站点">
                  <div class="metadata-field">
                    <el-select v-model="metadataForm.station_id" clearable filterable placeholder="选择正式站点" @change="metadataForm.station_override_enabled = Boolean(metadataForm.station_id)">
                      <el-option v-for="station in stations" :key="station.id" :label="`${station.code || '--'}-${station.name}`" :value="station.id" />
                    </el-select>
                    <small>保存时只提交正式 station_id；自动关联、LLDP 建议和 AC 原始站点不会自动写入。</small>
                  </div>
                </el-form-item>
                <el-form-item label="里程"><el-input v-model="metadataForm.mileage" maxlength="100" placeholder="例如 ZDK1+200" /></el-form-item>
                <el-form-item label="线路方向"><el-select v-model="metadataForm.direction" clearable><el-option label="上行" value="上行" /><el-option label="下行" value="下行" /><el-option v-if="metadataForm.direction && !['上行', '下行'].includes(metadataForm.direction)" :label="metadataForm.direction" :value="metadataForm.direction" /></el-select></el-form-item>
                <el-form-item label="点位说明"><el-input v-model="metadataForm.location_note" maxlength="500" /></el-form-item>
              </div>
            </el-form>
          </div>

          <h3 class="detail-section-title">AC 连接记录</h3>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="连接状态">{{ display(store.selected.connection.state) }}</el-descriptions-item>
            <el-descriptions-item label="连接 IP">{{ display(store.selected.connection.ip_address) }}</el-descriptions-item>
            <el-descriptions-item label="最近建链时间">{{ display(store.selected.connection.connected_at) }}</el-descriptions-item>
            <el-descriptions-item label="数据更新时间">{{ formatTime(store.selected.connection.updated_at) }}</el-descriptions-item>
          </el-descriptions>

          <div class="section-heading"><h3>Mesh Radio 1 / 2</h3><el-button v-if="isFeatureEnabled('capability.ac.fit_ap.history')" link type="primary" @click="openHistory('radio')">查看历史</el-button></div>
          <NcDataTable table-id="ac-fit-ap-radios" route-key="/ac-management" :data="detailRadios" :columns="radioColumns" :show-column-settings="false" border />

          <div class="section-heading"><h3>当前 LLDP 关系（最多 10 条）</h3><el-button v-if="isFeatureEnabled('capability.ac.fit_ap.history')" link type="primary" @click="openHistory('lldp')">查看历史</el-button></div>
          <el-alert v-if="currentLldpError" :title="currentLldpError" type="error" :closable="false" show-icon />
          <NcDataTable v-loading="currentLldpLoading" table-id="ac-fit-ap-current-lldp" route-key="/ac-management" :data="currentLldpRows" :columns="currentLldpColumns" :show-column-settings="false" border empty-text="暂无有效 LLDP 关系" />

          <div class="section-heading"><h3>光衰</h3><el-button v-if="isFeatureEnabled('capability.ac.fit_ap.history')" link type="primary" @click="openHistory('optical')">查看历史</el-button></div>
          <el-alert :title="opticalAlertTitle(store.selected.optical)" :type="detailApOpticalPresentation(store.selected.optical).tagType" :closable="false" show-icon />
          <el-descriptions :column="2" border class="optical-detail">
            <el-descriptions-item label="Tx Power">
              <el-tooltip
                :content="opticalEvidenceTitle('AP 侧发光', store.selected.optical.tx_power, store.selected.optical.tx_power_status, store.selected.optical)"
                placement="top"
              >
                <span
                  data-testid="optical-tx-power"
                  :class="opticalValuePresentation(store.selected.optical.tx_power_status, store.selected.optical.data_freshness).className"
                >{{ formatOpticalPower(store.selected.optical.tx_power) }}</span>
              </el-tooltip>
            </el-descriptions-item>
            <el-descriptions-item label="Rx Power">
              <el-tooltip
                :content="opticalEvidenceTitle('AP 侧收光', store.selected.optical.rx_power, store.selected.optical.ap_rx_status, store.selected.optical)"
                placement="top"
              >
                <span
                  data-testid="optical-ap-rx-power"
                  :class="detailApOpticalValuePresentation(store.selected.optical).className"
                >{{ formatOpticalPower(store.selected.optical.rx_power) }}</span>
              </el-tooltip>
            </el-descriptions-item>
            <el-descriptions-item label="交换机 Rx">
              <el-tooltip
                :content="opticalEvidenceTitle('交换机侧收光', store.selected.optical.switch_rx_power, store.selected.optical.switch_rx_status, store.selected.optical)"
                placement="top"
              >
                <span
                  data-testid="optical-switch-rx-power"
                  :class="detailSwitchOpticalValuePresentation(store.selected.optical).className"
                >{{ formatOpticalPower(store.selected.optical.switch_rx_power) }}</span>
              </el-tooltip>
            </el-descriptions-item>
            <el-descriptions-item label="阈值状态">
              <el-tag
                data-testid="optical-threshold-status"
                :type="detailThresholdPresentation(store.selected.optical).tagType"
                :class="detailThresholdPresentation(store.selected.optical).className"
                effect="light"
              >{{ detailThresholdPresentation(store.selected.optical).label }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="AP 在线状态">{{ statusLabel(store.selected.optical.ap_online_status) }}</el-descriptions-item>
            <el-descriptions-item label="光衰判定"><span data-testid="optical-judgement">{{ opticalJudgement(store.selected.optical) }}</span></el-descriptions-item>
            <el-descriptions-item label="告警等级">{{ opticalAlarmLevel(store.selected.optical) }}</el-descriptions-item>
            <el-descriptions-item label="数据状态">{{ opticalFreshnessLabel(store.selected.optical.data_freshness) }}</el-descriptions-item>
            <el-descriptions-item label="温度">{{ display(store.selected.optical.temperature) }}</el-descriptions-item>
            <el-descriptions-item label="电压">{{ display(store.selected.optical.voltage) }}</el-descriptions-item>
            <el-descriptions-item label="偏置电流">{{ display(store.selected.optical.bias_current) }}</el-descriptions-item>
            <el-descriptions-item label="最近更新时间">{{ formatTime(store.selected.optical.updated_at) }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </div>
    </el-drawer>

    <el-drawer v-model="historyVisible" :title="historyTitle" size="min(1100px, 96vw)">
      <div v-loading="historyLoading">
        <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
        <NcDataTable table-id="ac-fit-ap-history" route-key="/ac-management" :preference-scope="historyKind" :data="historyPage?.items || []" :columns="historyColumns" empty-text="暂无历史记录" height="calc(100vh - 190px)" />
        <div class="pagination-row">
          <span>共 {{ historyPage?.total || 0 }} 条</span>
          <el-pagination :current-page="historyPage?.page || 1" :page-size="historyPage?.page_size || 100" layout="prev, pager, next" :total="historyPage?.total || 0" @current-change="openHistory(historyKind, $event)" />
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="configVisible" title="AC 配置只读查看" size="min(1100px, 96vw)">
      <div v-loading="store.configLoading" class="config-viewer">
        <template v-if="store.configContent">
          <div class="config-searchbar">
            <el-input v-model="configSearch" clearable placeholder="搜索配置文本" />
            <el-button @click="nextConfigMatch">下一个匹配（{{ matchingLines.length }}）</el-button>
            <span>{{ store.configContent.snapshot.path_id }} · {{ store.configContent.total_chars }} 字符</span>
          </div>
          <div class="code-panel">
            <div
              v-for="(line, index) in configLines"
              :key="index"
              :data-config-line="index"
              :class="['config-line', { matched: matchingLines.includes(index), current: matchingLines[currentMatch] === index }]"
            ><span>{{ index + 1 }}</span><code>{{ line || ' ' }}</code></div>
          </div>
          <el-button v-if="store.configContent.next_offset" class="load-more" @click="store.loadMoreConfig">加载下一块</el-button>
        </template>
        <ConfigDiffViewer v-else-if="sharedConfigDiff" :model="sharedConfigDiff" />
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.ac-management { width: 100%; max-width: none; margin: 0; }
.page-error { margin-bottom: 16px; }
.page-toolbar, .config-toolbar, .detail-heading, .config-searchbar, .pagination-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-toolbar { margin-bottom: 16px; }
.page-toolbar h2, .config-toolbar h3, .detail-heading h2 { margin: 0; }
.page-toolbar p, .config-toolbar p, .detail-heading p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.toolbar-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; min-width: 0; }
.toolbar-separator { width: 1px; height: 24px; background: var(--nc-divider); }
.ac-info-strip { margin-bottom: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(6, minmax(125px, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-grid article { padding: 15px 17px; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-top: 3px solid var(--nc-border-strong); border-radius: 10px; }
.summary-grid article.success { border-top-color: var(--nc-success); }
.summary-grid article.warning { border-top-color: var(--nc-warning); }
.summary-grid article.danger { border-top-color: var(--nc-danger); }
.summary-grid span { display: block; color: var(--nc-text-secondary); font-size: 12px; }
.summary-grid strong { display: block; margin-top: 6px; color: var(--nc-text-primary); font-size: 24px; }
.content-card { overflow: hidden; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 10px; }
.ac-tabs :deep(.el-tabs__header) { margin: 0; padding: 0 18px; }
.filter-bar { display: grid; grid-template-columns: minmax(220px, 1.5fr) repeat(6, minmax(115px, 1fr)) auto auto auto; gap: 8px; padding: 14px; border-bottom: 1px solid var(--nc-divider); }
.column-picker :deep(.el-checkbox) { margin-right: 8px; }
.pagination-row { padding: 12px 16px; color: var(--nc-text-secondary); font-size: 12px; }
.config-toolbar { padding: 15px 18px; border-bottom: 1px solid var(--nc-divider); }
.detail-section-title { margin: 23px 0 10px; }
.metadata-editor { margin-top: 18px; padding: 14px 16px 2px; border: 1px solid var(--nc-border); border-radius: 8px; }
.metadata-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.metadata-field { width: 100%; }
.metadata-field small { display: block; margin-top: 4px; color: var(--el-color-info); line-height: 1.4; }
.section-heading { display: flex; align-items: center; justify-content: space-between; margin: 23px 0 10px; }
.section-heading h3, .metadata-editor .section-heading { margin: 0; }
.optical-detail { margin-top: 12px; }
.optical-value-normal { color: var(--el-color-success); }
.optical-value-warning { color: var(--el-color-warning); font-weight: 600; }
.optical-value-danger { color: var(--el-color-danger); font-weight: 700; }
.optical-value-stale { color: var(--el-color-warning); font-weight: 600; }
.optical-value-muted { color: var(--el-text-color-secondary); }
.config-viewer { min-height: 360px; }
.config-searchbar { position: sticky; top: 0; z-index: 2; padding: 10px 0; background: var(--nc-bg-panel); }
.config-searchbar .el-input { max-width: 360px; }
.config-searchbar span { color: var(--nc-text-secondary); font-size: 12px; }
.code-panel { max-height: calc(100vh - 190px); overflow: auto; background: var(--nc-bg-code); border-radius: 8px; color: var(--nc-text-code); font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; }
.config-line { display: grid; grid-template-columns: 58px minmax(max-content, 1fr); min-width: max-content; border-bottom: 1px solid var(--nc-border-code); }
.config-line > span { padding: 2px 10px; color: var(--nc-text-code-muted); text-align: right; border-right: 1px solid var(--nc-border-code); user-select: none; }
.config-line code { padding: 2px 12px; white-space: pre; }
.config-line.matched { background: var(--nc-bg-code-match); }
.config-line.current { background: var(--nc-bg-code-current); }
.load-more { display: block; margin: 12px auto 0; }
.action-summary { margin-top: 14px; }
.command-preview { max-height: 260px; overflow: auto; padding: 14px; background: var(--nc-bg-code); border-radius: 8px; color: var(--nc-text-code); font: 13px/1.6 Consolas, "Microsoft YaHei", monospace; }
@media (max-width: 1400px) {
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .filter-bar { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
}
@media (max-width: 900px) {
  .page-toolbar, .config-toolbar { align-items: flex-start; flex-direction: column; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .filter-bar { grid-template-columns: 1fr 1fr; }
  .toolbar-actions { justify-content: flex-start; }
  .toolbar-separator { display: none; }
}
</style>
