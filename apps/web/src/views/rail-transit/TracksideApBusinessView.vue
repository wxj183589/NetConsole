<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  getTracksideApBusinessExportProposal,
  listTracksideApBusiness,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
} from '../../api/tracksideApBusiness'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import { t } from '../../i18n/runtime'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import type {
  TracksideApBusinessPage,
  TracksideApBusinessRow,
  TracksideApScopeExcluded,
  TracksideApUnmatchedOnline,
  TracksideApTask,
  TracksideApUpdateRequest,
} from '../../types/tracksideApBusiness'
import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import { displayInterfaceName } from '../../utils/interfaceName'
import { TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE } from './tracksideApBusinessArtifact'
import { activeTaskStatuses } from '../../utils/taskStatus'
import {
  displayLldpStatus,
  displayPowerThreshold,
  displaySwitchVendor,
  displayTracksideSnapshotTime,
  displayTracksideValue,
  tracksideOpticalPresentation,
} from './tracksideApBusinessDisplay'

const userSelectedExport = useUserSelectedExport()
const taskStore = useTaskStore()
const activeStates = new Set(activeTaskStatuses)
const businessTaskTypes = new Set([
  'trackside_ap_optical_update',
  TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE,
])
const initialLoading = ref(false)
const refreshing = ref(false)
const taskSubmitting = ref(false)
const pendingScopeKey = ref('')
const loadError = ref('')
const actionError = ref('')
const page = ref<TracksideApBusinessPage | null>(null)
const excludedVisible = ref(false)
const unmatchedVisible = ref(false)
const currentTaskId = ref('')
const filters = reactive({ station: '', query: '', optical_anomaly_only: false, page: 1, page_size: 50 })
let loadGeneration = 0

const businessColumns: NcTableColumn<TracksideApBusinessRow>[] = [
  { key: 'site', label: '站点', valueType: 'name', fixed: 'left' },
  { key: 'device_name', label: '车站交换机', valueType: 'name', fixed: 'left' },
  { key: 'switch_vendor', label: '交换机厂商', valueType: 'name', displayValue: (row) => displaySwitchVendor(row.switch_vendor) },
  { key: 'interface_name', label: '接口', valueType: 'port', displayValue: (row) => displayTracksideValue(displayInterfaceName(row.interface_name)) },
  { key: 'lldp_match_status', label: 'LLDP 状态', valueType: 'status', displayValue: (row) => displayLldpStatus(row.lldp_match_status) },
  { key: 'link_status', label: '链路', valueType: 'status' },
  { key: 'switch_interface_updated_at', label: t('trackside.snapshot.interface_time', '接口采集时间'), valueType: 'datetime', displayValue: (row) => displayTracksideSnapshotTime(row.switch_interface_updated_at, row.switch_interface_data_status) },
  { key: 'port_type', label: '端口类型', valueType: 'status', width: 100 },
  { key: 'description', label: '描述', valueType: 'description', width: 90, maxWidth: 120, align: 'center', headerAlign: 'center', stretch: 'none', showOverflowTooltip: true },
  { key: 'pvid', label: 'PVID', valueType: 'number', displayValue: (row) => displayTracksideValue(row.pvid) },
  { key: 'vlan', label: 'VLAN', displayValue: (row) => displayTracksideValue(row.vlan) },
  { key: 'switch_rx_power', label: '本端 Rx (dBm)', valueType: 'number' },
  { key: 'switch_tx_power', label: '本端 Tx (dBm)', valueType: 'number' },
  { key: 'switch_rx_low_alarm', label: 'Rx 门限', displayValue: (row) => displayPowerThreshold(row.switch_rx_low_alarm, row.switch_rx_high_alarm) },
  { key: 'switch_tx_low_alarm', label: 'Tx 门限', displayValue: (row) => displayPowerThreshold(row.switch_tx_low_alarm, row.switch_tx_high_alarm) },
  { key: 'switch_optical_status', label: '模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'switch_optical_updated_at', label: t('trackside.snapshot.optical_time', '模块采集时间'), valueType: 'datetime', displayValue: (row) => displayTracksideSnapshotTime(row.switch_optical_updated_at, row.switch_optical_data_status) },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac', stretch: 'priority' },
  { key: 'ap_name', label: '当前轨旁 AP', valueType: 'name' },
  { key: 'ap_rx_power', label: '对端 Rx (dBm)', valueType: 'number' },
  { key: 'ap_tx_power', label: '对端 Tx (dBm)', valueType: 'number' },
  { key: 'ap_optical_status', label: 'AP 模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'optical_severity', label: '综合', valueType: 'status', cellKind: 'tag' },
  { key: 'updated_at', label: t('trackside.snapshot.business_time', '业务更新时间'), valueType: 'datetime' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['更新站点', '更新 AP'] },
]

const excludedColumns: NcTableColumn<TracksideApScopeExcluded>[] = [
  { key: 'device_name', label: '设备名称', valueType: 'name', minWidth: 170 },
  { key: 'station_name', label: '归属站点', valueType: 'name', minWidth: 150 },
  { key: 'operation_status', label: '当前工作状态', valueType: 'status', width: 130 },
  { key: 'project_phase', label: '建设批次', valueType: 'status', width: 120 },
  { key: 'reason', label: '排除原因', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
]
const unmatchedColumns: NcTableColumn<TracksideApUnmatchedOnline>[] = [
  { key: 'ap_name', label: 'AP名称', valueType: 'name', minWidth: 170 },
  { key: 'mac', label: 'AP MAC', valueType: 'mac', width: 170 },
  { key: 'ac_status', label: 'AC状态', valueType: 'status', width: 130 },
  { key: 'runtime_station_text', label: '运行态站点', valueType: 'name', minWidth: 170 },
  { key: 'reason', label: '资料状态', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
  { key: 'suggested_action', label: '建议处理', valueType: 'description', minWidth: 300, align: 'left', alignmentReason: 'long-text' },
]
const currentTask = computed<TaskItem | null>(() => (
  taskStore.tasks.find((item) => item.id === currentTaskId.value) || null
))
const updateTaskRunning = computed(() => taskStore.tasks.some(
  (item) => item.type === 'trackside_ap_optical_update' && activeStates.has(item.status),
))
const exportTaskRunning = computed(() => taskStore.tasks.some(
  (item) => item.type === TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE && activeStates.has(item.status),
))
const updateFeatureEnabled = computed(() => isFeatureEnabled('web.rail_trackside_ap_business_update') && isFeatureEnabled('web.rail_task_control'))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function cleanIdentity(value: string): string { return String(value || '').trim() }
function handleStationChange(): void { filters.page = 1; void loadRows() }
function singleApUpdatePayload(row: TracksideApBusinessRow): TracksideApUpdateRequest | null {
  const apUuid = cleanIdentity(row.ap_uuid)
  if (apUuid) return { ap_uuid: apUuid }
  const apMac = cleanIdentity(row.ap_mac)
  if (apMac) return { ap_mac: apMac }
  return null
}
function hasApIdentity(row: TracksideApBusinessRow): boolean { return singleApUpdatePayload(row) !== null }
function emptyReasonLabel(value: string): string {
  const labels: Record<string, string> = {
    'trackside.empty.no_devices': '当前工作范围内没有可用的车站交换机。',
    'trackside.empty.no_interfaces': '当前车站交换机没有接口事实。',
    'trackside.empty.no_ap_interfaces': '已找到车站交换机，但未识别到候选 AP 端口。',
    'trackside.empty.no_optical_or_fit': '已找到候选 AP 端口，但暂未采集光衰或 FIT-AP 运行态。',
    'trackside.empty.no_lldp_or_fit': '已找到候选 AP 端口，但暂未采集 LLDP 或 FIT-AP 运行态。',
    'trackside.empty.no_fit_ap_optical': '已发现候选 AP 端口，暂未关联 AP 光衰资料。',
    'trackside.empty.no_fit_ap_resource': '已发现候选 AP 端口，部分端口尚未关联 AP 运行态资料。',
    'trackside.empty.no_rows': '已发现候选 AP 端口，部分端口尚未关联 AP 运行态资料。',
  }
  if (labels[value]) return labels[value]
  if (value.startsWith('trackside.')) return '暂无轨旁 AP 业务数据'
  return value || '暂无轨旁 AP 业务数据'
}
type DataAvailability = 'loaded' | 'partial' | 'failed' | 'unloaded'
function dataAvailability(sources: string[]): DataAvailability {
  if (!page.value) return 'unloaded'
  const statuses = page.value.source_statuses
  if (!statuses) return 'loaded'
  const values = sources.map((source) => statuses[source]).filter(Boolean)
  if (values.includes('failed')) return 'failed'
  if (values.includes('partial')) return 'partial'
  return 'loaded'
}
function metricValue(value: number | undefined, sources: string[]): string | number {
  const availability = dataAvailability(sources)
  if (availability === 'unloaded') return '—'
  if (availability === 'failed') return '加载失败'
  if (availability === 'partial') return '部分可用'
  return Number(value ?? 0)
}
async function loadRows(reset = false): Promise<boolean> {
  if (reset) filters.page = 1
  const generation = ++loadGeneration
  const selectedStation = cleanIdentity(filters.station)
  const firstLoad = page.value === null
  if (firstLoad) initialLoading.value = true
  else refreshing.value = true
  loadError.value = ''
  let succeeded = false
  try {
    const nextPage = await listTracksideApBusiness({ ...filters })
    if (generation === loadGeneration) {
      page.value = nextPage
      succeeded = true
    }
  } catch (reason) {
    if (generation === loadGeneration) {
      loadError.value = page.value
        ? '部分数据不可用，已保留最后成功数据。'
        : failure(reason, '轨旁 AP 业务加载失败')
    }
  } finally {
    if (generation === loadGeneration) {
      initialLoading.value = false
      refreshing.value = false
    }
  }
  if (succeeded && selectedStation && !(page.value?.station_options || []).includes(selectedStation)) {
    filters.station = ''
    filters.page = 1
    void loadRows(true)
  }
  return succeeded
}

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string, scopeKey: string): Promise<void> {
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true
  actionError.value = ''
  try {
    const started = await factory()
    currentTaskId.value = started.task_id
    await taskStore.refresh()
  }
  catch (reason) { actionError.value = failure(reason, fallback) }
  finally { taskSubmitting.value = false; pendingScopeKey.value = '' }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate({}), '轨旁 AP 光衰更新启动失败', 'update:all') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败', `update:station:${row.site}`) }
function updateAp(row: TracksideApBusinessRow): void {
  const payload = singleApUpdatePayload(row)
  if (!payload) { actionError.value = '缺少 AP 身份，无法定向更新'; return }
  const target = cleanIdentity(row.ap_mac) || cleanIdentity(row.ap_uuid)
  const scopeValue = payload.ap_uuid || payload.ap_mac || target
  void startTask(
    () => startTracksideApUpdate(payload),
    'AP 更新启动失败',
    `update:ap:${scopeValue}`,
  )
}
async function exportBusiness(): Promise<void> {
  const scopeKey = 'export:business'
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true
  actionError.value = ''
  try {
    const proposal = await getTracksideApBusinessExportProposal()
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.trackside_business',
      suggestedName: proposal.suggested_name,
      submit: () => startTracksideApBusinessExport(proposal),
    })
    if (result.status === 'cancelled') return
    currentTaskId.value = result.task.task_id
    await taskStore.refresh()
  } catch (reason) {
    actionError.value = failure(reason, '轨旁 AP 业务导出启动失败')
  } finally {
    taskSubmitting.value = false
    pendingScopeKey.value = ''
  }
}

function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}

watch(
  () => currentTask.value?.status,
  (status, previousStatus) => {
    if (
      currentTask.value?.type === 'trackside_ap_optical_update'
      && status
      && !activeStates.has(status)
      && status !== previousStatus
    ) void loadRows()
  },
)

onMounted(() => {
  void Promise.all([
    loadRows(),
    taskStore.refresh().then(() => {
      currentTaskId.value = taskStore.tasks.find(
        (item) => businessTaskTypes.has(item.type) && activeStates.has(item.status),
      )?.id || ''
    }),
  ])
})
</script>

<template>
  <section class="trackside-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · TRACKSIDE AP</p><h1>轨旁 AP 业务</h1><p>交换机端口、当前 AP、光功率与异常状态来自正式设备事实和轨旁业务维护规则。</p></div>
      <div class="actions">
        <el-button :loading="refreshing" :disabled="initialLoading" @click="loadRows()">刷新</el-button>
        <el-button
          type="primary"
          :loading="taskSubmitting"
          :disabled="updateTaskRunning || !updateFeatureEnabled"
          @click="updateAll"
        >更新全部光衰</el-button>
        <el-button
          :loading="taskSubmitting"
          :disabled="updateTaskRunning || exportTaskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_export') || !isFeatureEnabled('web.rail_task_control')"
          @click="exportBusiness"
        >导出表格</el-button>
      </div>
    </header>
    <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="true" @close="loadError = ''" />
    <el-alert
      v-if="page?.partial_data"
      title="部分数据不可用，已展示成功构建的交换机/AP 端口行。"
      type="warning"
      show-icon
      :closable="false"
      class="source-warning"
    >
      <details v-if="page.unavailable_sources?.length">
        <summary>查看不可用来源</summary>
        <span v-for="issue in page.unavailable_sources" :key="`${issue.source}:${issue.device_id || ''}`">
          {{ issue.label }}：{{ issue.code }}<template v-if="issue.device_id">（设备 {{ issue.device_id }}）</template>
        </span>
      </details>
    </el-alert>
    <el-alert v-if="actionError" :title="actionError" type="error" show-icon closable @close="actionError = ''" />
    <div v-if="page" class="scope-summary">
      <strong>统计范围：{{ page.scope_description || '当前项目 · 当前工作范围轨旁 AP' }}</strong>
      <span>纳入站点 {{ page.scope_station_count || 0 }}</span>
      <span>基础 AP 资料 {{ page.scope_ap_reference_count ?? page.scope_device_count ?? 0 }}</span>
      <span>排除设备 {{ page.excluded_device_count || 0 }}</span>
      <el-button v-if="page.fit_ap_unmatched_online_count" link type="warning" @click="unmatchedVisible = true">基础资料待补充 {{ page.fit_ap_unmatched_online_count }}</el-button>
      <el-button v-if="page.excluded_device_count" link type="warning" @click="excludedVisible = true">查看排除项</el-button>
    </div>
    <div class="summary-grid">
      <article><span>站点交换机</span><strong>{{ metricValue(page?.device_count, ['switch_devices']) }}</strong></article><article><span>候选 AP 端口</span><strong>{{ metricValue(page?.candidate_interface_count, ['switch_devices', 'interfaces', 'planning']) }}</strong></article><article><span>AC AP 资源</span><strong>{{ metricValue(page?.fit_ap_resource_count, ['fit_ap_resources']) }}</strong></article><article><span>基础资料待补充</span><strong>{{ metricValue(page?.fit_ap_unmatched_online_count, ['fit_ap_resources']) }}</strong></article><article><span>光衰异常</span><strong>{{ metricValue(page?.optical_abnormal_count, ['interfaces', 'switch_optical', 'fit_ap_optical']) }}</strong></article>
    </div>
    <div class="content-card">
      <div class="toolbar">
        <el-input v-model="filters.query" clearable placeholder="交换机、接口、AP、MAC" @keyup.enter="loadRows(true)" />
        <el-select
          v-model="filters.station"
          class="station-select"
          clearable
          filterable
          placeholder="全部站点"
          :title="filters.station || '全部站点'"
          @change="handleStationChange"
        >
          <el-option
            v-for="station in page?.station_options || []"
            :key="station"
            :label="station"
            :value="station"
            :title="station"
          />
        </el-select>
        <el-checkbox v-model="filters.optical_anomaly_only">仅光衰异常</el-checkbox>
        <el-button type="primary" :loading="refreshing" :disabled="initialLoading" @click="loadRows(true)">查询</el-button>
        <span v-if="refreshing" class="refresh-indicator">正在刷新，当前数据保持显示</span>
        <span class="work-scope-filter-hint">设备管理与 AC 生成业务行；基础资料仅补充站点和工程属性</span>
      </div>
      <div class="business-table-host">
        <NcDataTable
          v-loading="initialLoading"
          table-id="trackside-ap-business"
          route-key="/rail-transit/trackside-ap-business"
          :data="page?.items || []"
          :columns="businessColumns"
          class="business-table"
          height="100%"
          :empty-text="emptyReasonLabel(page?.empty_reason || '')"
        >
          <template #cell-switch_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_rx_power) }}</span></template>
          <template #cell-switch_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_tx_power) }}</span></template>
          <template #cell-switch_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.switch_optical_status).tagType" :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ tracksideOpticalPresentation(row.switch_optical_status).label }}</el-tag></template>
          <template #cell-ap_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_rx_power) }}</span></template>
          <template #cell-ap_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_tx_power) }}</span></template>
          <template #cell-ap_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.ap_optical_status).tagType" :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ tracksideOpticalPresentation(row.ap_optical_status).label }}</el-tag></template>
          <template #cell-optical_severity="{ row }"><el-tag :type="tracksideOpticalPresentation(row.optical_severity).tagType" :class="tracksideOpticalPresentation(row.optical_severity).className">{{ tracksideOpticalPresentation(row.optical_severity).label }}</el-tag></template>
          <template #cell-actions="{ row }"><el-button link type="primary" :disabled="updateTaskRunning || !row.site || !updateFeatureEnabled" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :title="hasApIdentity(row) ? '' : '缺少 AP 身份，无法定向更新'" :disabled="updateTaskRunning || !hasApIdentity(row) || !updateFeatureEnabled" @click="updateAp(row)">更新 AP</el-button></template>
        </NcDataTable>
      </div>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="page?.page || filters.page" :page-size="filters.page_size" :page-sizes="[20, 50, 100, 200]" layout="sizes, prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" @size-change="(value: number) => { filters.page_size = value; filters.page = 1; loadRows() }" /></div>
    </div>
    <el-dialog v-model="excludedVisible" title="当前统计范围排除项" width="min(1040px, 94vw)">
      <NcDataTable
        table-id="trackside-ap-business-scope-excluded"
        route-key="/rail-transit/trackside-ap-business"
        :data="page?.excluded_items || []"
        :columns="excludedColumns"
        height="460"
        empty-text="没有排除项"
      />
    </el-dialog>
    <el-dialog v-model="unmatchedVisible" title="基础资料待补充的在线 AP" width="min(1280px, 96vw)">
      <NcDataTable
        table-id="trackside-ap-business-unmatched-online"
        route-key="/rail-transit/trackside-ap-business"
        :data="page?.unmatched_online_items || []"
        :columns="unmatchedColumns"
        height="460"
        empty-text="没有待补充基础资料的在线 AP"
      />
    </el-dialog>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;height:100%;min-height:0;min-width:0;flex-direction:column;gap:16px}.page-heading,.actions,.toolbar,.pagination,.scope-summary{display:flex;align-items:center;gap:12px}.page-heading,.pagination{flex:none;justify-content:space-between}.page-heading h1{margin:2px 0 6px}.page-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:0}.actions,.toolbar,.scope-summary{flex-wrap:wrap}.scope-summary{color:var(--el-text-color-secondary)}.scope-summary strong{color:var(--el-text-color-primary)}.summary-grid{display:grid;flex:none;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:8px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{display:flex;min-height:0;min-width:0;flex:1;flex-direction:column;padding:14px 16px;overflow:hidden}.business-table-host{min-height:0;min-width:0;flex:1}.toolbar{flex:none;margin-bottom:12px}.toolbar .el-input{width:230px}.station-select{width:260px}.refresh-indicator{color:var(--el-color-primary);font-size:13px}.work-scope-filter-hint{color:var(--el-text-color-secondary);font-size:12px}.pagination{flex-wrap:wrap;padding-top:12px}.optical-normal{color:var(--el-color-success)}.optical-notice,.optical-warning{color:var(--el-color-warning)}.optical-alarm,.optical-link-abnormal,.optical-link-down,.optical-no-light,.optical-offline{color:var(--el-color-danger);font-weight:600}.optical-no-module,.optical-missing,.optical-skipped,.optical-not-collected,.optical-unknown{color:var(--el-text-color-secondary)}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
.source-warning details{display:grid;gap:4px;margin-top:6px}.source-warning summary{cursor:pointer}.source-warning details span{display:block}
</style>
