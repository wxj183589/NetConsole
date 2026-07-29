<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'

import {
  exportVehicleMrHistory,
  exportVehicleMrMappingTemplate,
  getVehicleMrOnlineTask,
  getVehicleMrOnlineDetail,
  listVehicleMrEvents,
  listVehicleMrControllers,
  listVehicleMrMappings,
  listVehicleMrOnline,
  recoverVehicleMrOnlineTasks,
  previewVehicleMrMappings,
  refreshVehicleMrApMapping,
  refreshVehicleMrOnline,
  saveVehicleMrMappings,
  startVehicleMrCollection,
  stopVehicleMrCollection,
} from '../../api/vehicleMrOnline'
import NcDataTable from '../../components/table/NcDataTable.vue'
import NcOverflowTooltip from '../../components/table/NcOverflowTooltip.vue'
import type { NcColumnValueType, NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import type {
  VehicleMrController,
  VehicleMrHistoryFilters,
  VehicleMrMappingPreview,
  VehicleMrMappingPreviewRow,
  VehicleMrOnlinePage,
  VehicleMrOnlineTask,
  VehicleMrTrainMapping,
  VehicleMrTrainState,
} from '../../types/vehicleMrOnline'

const router = useRouter()
const route = useRoute()
const { confirm } = useConfirm()
const userSelectedExport = useUserSelectedExport()
const storageKey = 'netconsole.vehicle-mr-online.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const loading = ref(false)
const error = ref('')
const page = ref<VehicleMrOnlinePage | null>(null)
const task = ref<VehicleMrOnlineTask | null>(null)
const events = ref<Array<Record<string, unknown>>>([])
const selectedTrain = ref<VehicleMrTrainState | null>(null)
const detailVisible = ref(false)
const mappingVisible = ref(false)
const mappings = ref<VehicleMrTrainMapping[]>([])
const controllers = ref<VehicleMrController[]>([])
const selectedControllerId = ref('')
const collectionInterval = ref(10)
const historyRange = ref<[string, string] | []>([])
const historyFilters = reactive({ car_end_label: '', event_status: '', station: '', ap_name: '' })
const mappingImportInput = ref<HTMLInputElement | null>(null)
const mappingDuplicateStrategy = ref<'replace' | 'skip' | 'error'>('replace')
const mappingPreview = ref<VehicleMrMappingPreview | null>(null)
const mappingPreviewVisible = ref(false)
const filters = reactive({
  query: '', overall_status: '', station: '', section: '', data_status: '', unmatched_only: false,
  page: 1, page_size: 50,
})
let pollTimer: number | undefined

function vehicleColumn<Row extends object>(
  key: string,
  label: string,
  valueType: NcColumnValueType = 'text',
  options: Partial<NcTableColumn<Row>> = {},
): NcTableColumn<Row> {
  return { key, label, valueType, ...options }
}

const trainColumns: NcTableColumn<VehicleMrTrainState>[] = [
  vehicleColumn('train_name', '列车', 'name', { width: 100, fixed: 'left' }),
  vehicleColumn('overall_status', '综合状态', 'status', { width: 120, cellKind: 'tag' }),
  vehicleColumn('ct_ap', 'CT 当前 AP', 'name', { minWidth: 165 }),
  vehicleColumn('ct_station_rssi', 'CT 站点 / RSSI', 'text', { minWidth: 180 }),
  vehicleColumn('tc_ap', 'TC 当前 AP', 'name', { minWidth: 165 }),
  vehicleColumn('tc_station_rssi', 'TC 站点 / RSSI', 'text', { minWidth: 180 }),
  vehicleColumn('current_station', '当前位置', 'text', { minWidth: 130 }),
  vehicleColumn('direction', '方向', 'text', { width: 85 }),
  vehicleColumn('policy', '在线策略', 'status', { width: 130 }),
  vehicleColumn('reason_text', '状态原因', 'description', { minWidth: 190, align: 'left', alignmentReason: 'long-text' }),
  vehicleColumn('updated_at', '最近更新时间', 'datetime', { width: 175 }),
  vehicleColumn('actions', '操作', 'actions', { width: 100, cellKind: 'actions', actionLabels: ['通信详情'] }),
]

type TaskResultRow = { name: string; value: string }
type VehicleMrEventRow = Record<string, unknown>

const taskResultColumns: NcTableColumn<TaskResultRow>[] = [
  vehicleColumn('name', '结果项', 'name', { width: 220 }),
  vehicleColumn('value', '值', 'description', { align: 'left', alignmentReason: 'long-text' }),
]

const eventColumns: NcTableColumn<VehicleMrEventRow>[] = [
  vehicleColumn('event_time', '时间', 'datetime', { width: 180 }),
  vehicleColumn('car_end_label', '端', 'text', { width: 80 }),
  vehicleColumn('status', '状态', 'status', { width: 100 }),
  vehicleColumn('station', '站点', 'text', { width: 140 }),
  vehicleColumn('ap_name', '轨旁 AP', 'name', { minWidth: 160 }),
  vehicleColumn('rssi', 'RSSI', 'number', { width: 90 }),
  vehicleColumn('event_type', '事件类型', 'status', { width: 130 }),
  vehicleColumn('status_reason', '判断说明', 'description', { minWidth: 180, align: 'left', alignmentReason: 'long-text' }),
]

const mappingColumns: NcTableColumn<VehicleMrTrainMapping>[] = [
  vehicleColumn('enabled', '启用', 'status', { width: 70 }),
  vehicleColumn('train_display_name', '车次', 'name', { width: 130 }),
  vehicleColumn('tc1_peer_name', 'TC1 Peer Name', 'name', { minWidth: 190 }),
  vehicleColumn('tc2_peer_name', 'TC2 Peer Name', 'name', { minWidth: 190 }),
  vehicleColumn('online_policy', '在线策略', 'status', { width: 170 }),
  vehicleColumn('remark', '备注', 'description', { minWidth: 180, align: 'left', alignmentReason: 'long-text' }),
  vehicleColumn('actions', '操作', 'actions', { width: 80, cellKind: 'actions', actionLabels: ['删除'] }),
]

const previewColumns: NcTableColumn<VehicleMrMappingPreviewRow>[] = [
  vehicleColumn('row_number', '行', 'number', { width: 70 }),
  vehicleColumn('status', '状态', 'status', { width: 100 }),
  vehicleColumn('key', '车次', 'name', { minWidth: 140 }),
  vehicleColumn('message', '说明', 'description', { minWidth: 260, align: 'left', alignmentReason: 'long-text' }),
]

const taskRows = computed(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) })))
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const collectionRunning = computed(() => Boolean(task.value?.action === 'vehicle_mr_online_collection_start' && !terminalStates.has(task.value.status)))
function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '—' : `${value}${suffix}` }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: VehicleMrOnlineTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
const statusText: Record<string, string> = {
  BOTH_ONLINE: '双端在线', ONE_SIDE_ONLINE: '单端在线', BOTH_OFFLINE: '双端离线', STALE: '数据过期', UNKNOWN: '状态未知',
}
const endpointStatusText: Record<string, string> = { ONLINE: '在线', OFFLINE: '离线', STALE: '数据过期', UNKNOWN: '未知' }
const matchText: Record<string, string> = { EXACT: '精确匹配', NAME_NORMALIZED: '名称标准化匹配', MAC_MATCHED: 'MAC 匹配', UNMATCHED: '未匹配', UNKNOWN: '未知' }
const policyText: Record<string, string> = { auto: '自动', dual_active: '双端在线', single_tail: '尾端在线', single_tc1: 'CT 固定在线', single_tc2: 'TC 固定在线' }
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'BOTH_OFFLINE' || value === 'OFFLINE') return 'danger'
  if (value === 'ONE_SIDE_ONLINE' || value === 'STALE') return 'warning'
  if (value === 'BOTH_ONLINE' || value === 'ONLINE') return 'success'
  return 'info'
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) {
    if (task.value?.status === 'COMPLETED') void Promise.all([loadTrains(), loadMappings()])
    return
  }
  pollTimer = window.setTimeout(async () => {
    try {
      rememberTask(await getVehicleMrOnlineTask(task.value!.task_id)); error.value = ''
      if (task.value?.action === 'vehicle_mr_online_collection_start') await loadTrains(false, true)
      poll()
    }
    catch (reason) { error.value = failure(reason, '列车在线任务状态读取失败') }
  }, 1000)
}

async function loadTrains(reset = false, silent = false): Promise<void> {
  if (reset) filters.page = 1
  if (!silent) loading.value = true
  error.value = ''
  try { page.value = await listVehicleMrOnline(filters) }
  catch (reason) { error.value = failure(reason, '列车在线状态加载失败') }
  finally { if (!silent) loading.value = false }
}
async function loadMappings(): Promise<void> { try { mappings.value = await listVehicleMrMappings() } catch (reason) { error.value = failure(reason, '列车 MR 映射加载失败') } }
async function loadControllers(): Promise<void> {
  try {
    controllers.value = await listVehicleMrControllers()
    if (!selectedControllerId.value && controllers.value.length === 1) selectedControllerId.value = controllers.value[0].controller_id
  } catch (reason) { error.value = failure(reason, '无线控制器 AC 加载失败') }
}
async function startTask(factory: () => Promise<VehicleMrOnlineTask>, fallback: string): Promise<void> {
  loading.value = true; error.value = ''
  try { rememberTask(await factory()); poll(); openTaskWindow() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { loading.value = false }
}
function refreshAll(): void {
  if (!selectedControllerId.value) { error.value = '请选择连接信息完整的无线控制器 AC'; return }
  void startTask(() => refreshVehicleMrOnline(String(selectedControllerId.value)), '列车在线状态刷新启动失败')
}
function refreshApMapping(): void { void startTask(() => refreshVehicleMrApMapping(selectedTrain.value?.train_id || ''), '轨旁 AP 映射刷新启动失败') }
function startCollection(): void {
  if (!selectedControllerId.value) { error.value = '请选择连接信息完整的无线控制器 AC'; return }
  const selected = controllers.value.find((item) => item.controller_id === selectedControllerId.value)
  if (!selected) { error.value = '无线控制器 AC 不存在'; return }
  void startTask(() => startVehicleMrCollection(selected.device_id, collectionInterval.value), '列车在线连续采集启动失败')
}
async function stopCollection(): Promise<void> {
  if (!task.value || task.value.action !== 'vehicle_mr_online_collection_start') return
  await startTask(() => stopVehicleMrCollection(task.value!.task_id), '列车在线连续采集停止失败')
}
function currentHistoryFilters(): VehicleMrHistoryFilters {
  return {
    start_time: historyRange.value[0] || '', end_time: historyRange.value[1] || '',
    car_end_label: historyFilters.car_end_label, event_status: historyFilters.event_status,
    station: historyFilters.station, ap_name: historyFilters.ap_name, limit: 1000,
  }
}
async function loadEvents(): Promise<void> {
  if (!selectedTrain.value) return
  loading.value = true; error.value = ''
  try { events.value = (await listVehicleMrEvents(selectedTrain.value.train_id, currentHistoryFilters())).items }
  catch (reason) { error.value = failure(reason, '列车经过历史加载失败') }
  finally { loading.value = false }
}
async function openDetail(row: VehicleMrTrainState): Promise<void> {
  selectedTrain.value = row; detailVisible.value = true; loading.value = true; error.value = ''
  try {
    const [detail, history] = await Promise.all([
      getVehicleMrOnlineDetail(row.train_id),
      listVehicleMrEvents(row.train_id, currentHistoryFilters()),
    ])
    selectedTrain.value = detail
    events.value = history.items
  } catch (reason) { error.value = failure(reason, '列车通信详情加载失败') }
  finally { loading.value = false }
}
function resetHistory(): void { historyRange.value = []; historyFilters.car_end_label = ''; historyFilters.event_status = ''; historyFilters.station = ''; historyFilters.ap_name = ''; void loadEvents() }
async function exportHistory(): Promise<void> {
  if (!selectedTrain.value) return
  loading.value = true
  error.value = ''
  try {
    const selected = selectedTrain.value
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.vehicle_history',
      suggestedName: `${safeExportPart(selected.train_name || selected.train_id || '列车')}-经过历史-${exportTimestamp()}.xlsx`,
      context: { trainId: selected.train_id },
      submit: () => exportVehicleMrHistory(selected.train_id, currentHistoryFilters()),
    })
    if (result.status === 'cancelled') return
    rememberTask(result.task)
    poll()
    openTaskWindow()
  } catch (reason) {
    error.value = failure(reason, '列车经过历史导出启动失败')
  } finally {
    loading.value = false
  }
}
async function openMappings(): Promise<void> { await loadMappings(); mappingVisible.value = true }
function addMapping(): void { mappings.value.push({ id: null, enabled: true, train_display_name: '', train_id: '', train_no: '', tc1_peer_name: '', tc2_peer_name: '', online_policy: 'auto', remark: '', created_at: '', updated_at: '' }) }
function deleteMapping(index: number): void { mappings.value.splice(index, 1) }
async function saveMappings(): Promise<void> {
  if (!await confirm({ type: 'DANGER', title: '保存映射确认', message: `确认用当前 ${mappings.value.length} 行替换列车 MR 映射并持久化？`, confirmText: '确认保存映射' })) return
  await startTask(() => saveVehicleMrMappings(mappings.value), '列车 MR 映射保存失败'); mappingVisible.value = false
}
async function chooseMappingImport(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''
  if (!file) return
  loading.value = true; error.value = ''
  try { mappingPreview.value = await previewVehicleMrMappings(file, mappingDuplicateStrategy.value); mappingPreviewVisible.value = true }
  catch (reason) { error.value = failure(reason, '列车 MR 映射导入预览失败') }
  finally { loading.value = false }
}
function applyMappingPreview(): void {
  if (!mappingPreview.value?.can_apply) return
  mappings.value = mappingPreview.value.result_rows; mappingPreviewVisible.value = false
  ElMessage.success('导入预览已应用到映射编辑区，请确认后保存')
}
async function exportMappingTemplate(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.vehicle_mapping_template',
      suggestedName: `列车MR映射模板-${exportTimestamp()}.xlsx`,
      submit: exportVehicleMrMappingTemplate,
    })
    if (result.status === 'cancelled') return
    rememberTask(result.task)
    poll()
    openTaskWindow()
  } catch (reason) {
    error.value = failure(reason, '列车 MR 映射模板导出启动失败')
  } finally {
    loading.value = false
  }
}
function safeExportPart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || '列车'
}
function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}
async function recoverTasks(): Promise<void> {
  try { const rows = await recoverVehicleMrOnlineTasks(); const saved = localStorage.getItem(storageKey) || ''; rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => !terminalStates.has(item.status)) || rows[0] || null); poll() }
  catch (reason) { error.value = failure(reason, '列车在线任务恢复失败') }
}

onMounted(() => {
  filters.query = String(route.query.query || route.query.mr_name || route.query.peer_ap_name || '')
  void Promise.all([loadTrains(), loadMappings(), loadControllers(), recoverTasks()])
})
onActivated(() => {
  if (task.value && !terminalStates.has(task.value.status)) poll()
})
onDeactivated(stopPolling)
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="vehicle-page">
    <header class="page-heading"><div><p class="eyebrow">RAIL TRANSIT · VEHICLE MR ONLINE</p><h1>列车在线情况</h1><p>连续采集 AC Mesh-Link，按 CT/TC 展示当前轨旁 AP、站点、RSSI、最后出现时间与映射策略。</p></div><div class="actions"><el-button :loading="loading" @click="loadTrains()">刷新页面</el-button><el-button :disabled="taskRunning || !selectedControllerId || !isFeatureEnabled('web.rail_train_online_refresh')" @click="refreshAll">刷新在线状态</el-button><el-button :disabled="taskRunning || !isFeatureEnabled('web.rail_train_online_refresh')" @click="refreshApMapping">刷新 AP 映射</el-button><el-button type="primary" :disabled="collectionRunning || !isFeatureEnabled('web.rail_train_online_mapping_write')" @click="openMappings">映射表管理</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <div class="content-card collection-bar">
      <strong>连续采集</strong>
      <el-select v-model="selectedControllerId" :disabled="collectionRunning" placeholder="选择无线控制器 AC" style="width:300px"><el-option v-for="item in controllers" :key="item.controller_id" :label="`${item.name} (${item.primary_address}) · ${item.protocol || '未配置协议'}`" :value="item.controller_id" :disabled="!item.connection_ready" /></el-select>
      <el-input-number v-model="collectionInterval" :disabled="collectionRunning" :min="3" :max="300" controls-position="right" /><span>秒</span>
      <el-button type="primary" :disabled="taskRunning || !selectedControllerId || !isFeatureEnabled('web.rail_train_online_collect') || !isFeatureEnabled('web.rail_task_control')" @click="startCollection">开始</el-button>
      <el-button type="danger" plain :disabled="!collectionRunning" @click="stopCollection">停止</el-button>
      <el-tag :type="collectionRunning ? 'success' : 'info'">{{ collectionRunning ? '采集中' : task?.action === 'vehicle_mr_online_collection_start' ? task.status : '未开始' }}</el-tag>
    </div>
    <div v-if="page" class="summary-grid">
      <article><span>列车 / MR</span><strong>{{ page.total }} / {{ page.mr_total }}</strong></article>
      <article><span>双端在线</span><strong>{{ page.both_online_count }}</strong></article>
      <article><span>单端在线</span><strong>{{ page.one_side_online_count }}</strong></article>
      <article><span>双端离线</span><strong>{{ page.both_offline_count }}</strong></article>
      <article><span>状态未知</span><strong>{{ page.unknown_count }}</strong></article>
      <article><span>数据过期</span><strong>{{ page.stale_count }}</strong></article>
      <article><span>有效 Mesh-Link</span><strong>{{ page.active_mesh_link_count }}</strong></article>
      <article><span>未匹配轨旁 AP</span><strong>{{ page.unmatched_ap_count }}</strong></article>
    </div>
    <div class="content-card"><div class="toolbar"><el-input v-model="filters.query" clearable placeholder="列车 / MR / AP / 站点" @keyup.enter="loadTrains(true)" /><el-select v-model="filters.overall_status" clearable placeholder="综合状态"><el-option v-for="value in ['BOTH_ONLINE','ONE_SIDE_ONLINE','BOTH_OFFLINE','STALE','UNKNOWN']" :key="value" :label="statusText[value]" :value="value" /></el-select><el-input v-model="filters.station" clearable placeholder="站点" /><el-input v-model="filters.section" clearable placeholder="区间" /><el-select v-model="filters.data_status" clearable placeholder="数据状态"><el-option label="最新" value="FRESH" /><el-option label="过期" value="STALE" /><el-option label="无数据" value="NO_DATA" /><el-option label="错误" value="ERROR" /></el-select><el-checkbox v-model="filters.unmatched_only">只看未匹配</el-checkbox><el-button type="primary" @click="loadTrains(true)">查询</el-button></div>
      <NcDataTable v-loading="loading" table-id="rail-vehicle-mr-online-trains" route-key="/rail-transit/train-online" :data="page?.items || []" :columns="trainColumns" height="calc(100vh - 480px)" empty-text="暂无列车在线状态" highlight-current-row @current-change="(row: VehicleMrTrainState | undefined) => selectedTrain = row || null" @row-dblclick="openDetail">
        <template #cell-overall_status="{ row }"><el-tag :type="statusType(row.overall_status)">{{ statusText[row.overall_status] }}</el-tag></template>
        <template #cell-ct_ap="{ row }"><NcOverflowTooltip :text="display(row.ct.current_ap_name)">{{ display(row.ct.current_ap_name) }}</NcOverflowTooltip></template>
        <template #cell-ct_station_rssi="{ row }"><NcOverflowTooltip :text="`${display(row.ct.station_name)} / ${display(row.ct.rssi_dbm, ' dBm')}`">{{ display(row.ct.station_name) }} / {{ display(row.ct.rssi_dbm, ' dBm') }}</NcOverflowTooltip></template>
        <template #cell-tc_ap="{ row }"><NcOverflowTooltip :text="display(row.tc.current_ap_name)">{{ display(row.tc.current_ap_name) }}</NcOverflowTooltip></template>
        <template #cell-tc_station_rssi="{ row }"><NcOverflowTooltip :text="`${display(row.tc.station_name)} / ${display(row.tc.rssi_dbm, ' dBm')}`">{{ display(row.tc.station_name) }} / {{ display(row.tc.rssi_dbm, ' dBm') }}</NcOverflowTooltip></template>
        <template #cell-policy="{ row }">{{ policyText[row.policy || ''] || display(row.policy) }}</template>
        <template #cell-actions="{ row }"><el-button link type="primary" @click="openDetail(row)">通信详情</el-button></template>
      </NcDataTable><div class="pagination"><span>共 {{ page?.total || 0 }} 列车</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadTrains() }" /></div>
    </div>
    <div v-if="task" class="content-card task-card"><div class="task-heading"><div><h2>列车在线处理结果</h2><p>{{ task.task_id }}</p></div><el-tag>{{ task.status }}</el-tag></div><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><p v-else>{{ task.message }}</p><NcDataTable v-if="taskRows.length" table-id="rail-vehicle-mr-online-task-results" route-key="/rail-transit/train-online" :preference-scope="task.action" :data="taskRows" :columns="taskResultColumns" :show-column-settings="false" :stripe="false" max-height="260" /><el-alert title="停止、日志、恢复和导出文件保存统一在任务中心处理" type="info" :closable="false"><el-button link @click="openTaskWindow">打开任务中心</el-button></el-alert></div>
    <el-drawer v-model="detailVisible" :title="`${selectedTrain?.train_name || ''} 通信详情`" size="min(1180px, 96vw)">
      <div v-if="selectedTrain" class="train-detail-summary">
        <el-descriptions :column="4" border>
          <el-descriptions-item label="综合状态"><el-tag :type="statusType(selectedTrain.overall_status)">{{ statusText[selectedTrain.overall_status] }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="当前位置">{{ display(selectedTrain.current_station) }}</el-descriptions-item>
          <el-descriptions-item label="当前区间">{{ display(selectedTrain.current_section) }}</el-descriptions-item>
          <el-descriptions-item label="方向">{{ display(selectedTrain.direction) }}</el-descriptions-item>
          <el-descriptions-item label="在线策略">{{ policyText[selectedTrain.policy || ''] || display(selectedTrain.policy) }}</el-descriptions-item>
          <el-descriptions-item label="状态原因" :span="2">{{ display(selectedTrain.reason_text) }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ display(selectedTrain.updated_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="endpoint-grid">
          <article v-for="endpoint in [selectedTrain.ct, selectedTrain.tc]" :key="endpoint.endpoint" class="endpoint-card">
            <header><strong>{{ endpoint.endpoint }} 端</strong><el-tag :type="statusType(endpoint.online_status)">{{ endpointStatusText[endpoint.online_status] }}</el-tag></header>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="MR 名称">{{ display(endpoint.mr_name) }}</el-descriptions-item><el-descriptions-item label="当前轨旁 AP">{{ display(endpoint.current_ap_name) }}</el-descriptions-item>
              <el-descriptions-item label="AP MAC">{{ display(endpoint.current_ap_mac) }}</el-descriptions-item><el-descriptions-item label="Mesh Radio">{{ display(endpoint.mesh_radio) }}</el-descriptions-item>
              <el-descriptions-item label="RSSI">{{ display(endpoint.rssi_dbm, ' dBm') }}</el-descriptions-item><el-descriptions-item label="匹配状态">{{ matchText[endpoint.match_status] }}</el-descriptions-item>
              <el-descriptions-item label="站点">{{ display(endpoint.station_name) }}</el-descriptions-item><el-descriptions-item label="区间">{{ display(endpoint.section_name) }}</el-descriptions-item>
              <el-descriptions-item label="里程">{{ display(endpoint.mileage) }}</el-descriptions-item><el-descriptions-item label="方向">{{ display(endpoint.direction) }}</el-descriptions-item>
              <el-descriptions-item label="轨旁 AP 室外侧收光">{{ display(endpoint.outdoor_optical_power) }}</el-descriptions-item><el-descriptions-item label="轨旁 AP 室内侧收光">{{ display(endpoint.indoor_optical_power) }}</el-descriptions-item>
              <el-descriptions-item label="更新时间" :span="2">{{ display(endpoint.updated_at) }}</el-descriptions-item>
            </el-descriptions>
          </article>
        </div>
      </div>
      <h3>最近状态变化</h3>
      <div class="history-toolbar"><el-date-picker v-model="historyRange" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss" start-placeholder="开始时间" end-placeholder="结束时间" /><el-select v-model="historyFilters.car_end_label" clearable placeholder="全部端别"><el-option label="TC1" value="TC1" /><el-option label="TC2" value="TC2" /></el-select><el-select v-model="historyFilters.event_status" clearable placeholder="全部状态"><el-option label="在线" value="在线" /><el-option label="离线" value="离线" /></el-select><el-input v-model="historyFilters.station" clearable placeholder="车站" /><el-input v-model="historyFilters.ap_name" clearable placeholder="轨旁 AP" /><el-button type="primary" :loading="loading" @click="loadEvents">查询</el-button><el-button @click="resetHistory">重置</el-button><el-button :disabled="!isFeatureEnabled('web.rail_train_online_history_export') || taskRunning" @click="exportHistory">导出</el-button></div>
      <NcDataTable table-id="rail-vehicle-mr-online-history" route-key="/rail-transit/train-online" :data="events" :columns="eventColumns" :show-column-settings="false" :stripe="false" border height="360" empty-text="暂无经过历史" />
    </el-drawer>
    <el-dialog v-model="mappingVisible" title="列车 MR 映射表" width="min(1150px, 96vw)" destroy-on-close><div class="mapping-toolbar"><el-select v-model="mappingDuplicateStrategy" style="width:150px"><el-option label="重复时覆盖" value="replace" /><el-option label="重复时跳过" value="skip" /><el-option label="重复时报错" value="error" /></el-select><input ref="mappingImportInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseMappingImport"><el-button :disabled="!isFeatureEnabled('web.rail_train_online_mapping_import')" @click="mappingImportInput?.click()">导入并预览</el-button><el-button :disabled="!isFeatureEnabled('web.rail_train_online_mapping_export')" @click="exportMappingTemplate">导出模板</el-button><el-button @click="loadMappings">刷新</el-button></div><NcDataTable table-id="rail-vehicle-mr-online-mappings" route-key="/rail-transit/train-online" :data="mappings" :columns="mappingColumns" :show-column-settings="false" :stripe="false" border height="520"><template #cell-enabled="{ row }"><el-checkbox v-model="row.enabled" /></template><template #cell-train_display_name="{ row }"><el-input v-model="row.train_display_name" /></template><template #cell-tc1_peer_name="{ row }"><el-input v-model="row.tc1_peer_name" /></template><template #cell-tc2_peer_name="{ row }"><el-input v-model="row.tc2_peer_name" /></template><template #cell-online_policy="{ row }"><el-select v-model="row.online_policy"><el-option label="自动/未知" value="auto" /><el-option label="单端在线-尾端在线" value="single_tail" /><el-option label="双端在线" value="dual_active" /><el-option label="TC1 固定在线" value="single_tc1" /><el-option label="TC2 固定在线" value="single_tc2" /></el-select></template><template #cell-remark="{ row }"><el-input v-model="row.remark" /></template><template #cell-actions="{ $index }"><el-button link type="danger" @click="deleteMapping($index)">删除</el-button></template></NcDataTable><template #footer><el-button @click="addMapping">新增</el-button><el-button @click="mappingVisible = false">取消</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.rail_train_online_mapping_write')" @click="saveMappings">保存映射</el-button></template></el-dialog>
    <el-dialog v-model="mappingPreviewVisible" title="列车 MR 映射导入预览" width="900px" append-to-body><div v-if="mappingPreview" class="preview"><el-descriptions :column="5" border><el-descriptions-item label="总行数">{{ mappingPreview.total_count }}</el-descriptions-item><el-descriptions-item label="有效">{{ mappingPreview.valid_count }}</el-descriptions-item><el-descriptions-item label="重复">{{ mappingPreview.duplicate_count }}</el-descriptions-item><el-descriptions-item label="错误">{{ mappingPreview.error_count }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ mappingPreview.file_sha256.slice(0, 12) }}…</el-descriptions-item></el-descriptions><NcDataTable table-id="rail-vehicle-mr-online-mapping-preview" route-key="/rail-transit/train-online" :data="mappingPreview.rows" :columns="previewColumns" :show-column-settings="false" :stripe="false" border height="350" /><el-alert v-if="!mappingPreview.can_apply" title="预览存在阻断错误，请修正文件或重复策略后重新导入" type="error" :closable="false" /></div><template #footer><el-button @click="mappingPreviewVisible = false">取消</el-button><el-button type="primary" :disabled="!mappingPreview?.can_apply" @click="applyMappingPreview">应用到编辑区</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.vehicle-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.pagination,.task-heading,.collection-bar,.history-toolbar,.mapping-toolbar{display:flex;align-items:center;gap:12px}.page-heading,.pagination,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p,.task-card p,.collection-bar span{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions,.toolbar,.history-toolbar,.collection-bar,.mapping-toolbar{flex-wrap:wrap}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card,.endpoint-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:8px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:24px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{margin-bottom:12px}.toolbar .el-input{width:190px}.toolbar .el-select{width:140px}.history-toolbar,.mapping-toolbar{margin-bottom:12px}.history-toolbar .el-input{width:130px}.history-toolbar .el-select{width:125px}.pagination{padding-top:12px}.task-card,.preview,.train-detail-summary{display:flex;flex-direction:column;gap:12px}.endpoint-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.endpoint-card{padding:12px}.endpoint-card header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.hidden{display:none}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}.endpoint-grid{grid-template-columns:1fr}}@media(max-width:720px){.summary-grid{grid-template-columns:1fr}}
</style>
