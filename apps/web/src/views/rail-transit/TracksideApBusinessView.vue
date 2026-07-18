<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTracksideApTask,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
  tracksideApBusinessDownloadRequest,
} from '../../api/tracksideApBusiness'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import { downloadBackendResource } from '../../platform/runtime'
import type { TracksideApBusinessPage, TracksideApBusinessRow, TracksideApTask } from '../../types/tracksideApBusiness'
import { displayInterfaceName } from '../../utils/interfaceName'
import { displayTracksideValue, tracksideOpticalPresentation } from './tracksideApBusinessDisplay'

const storageKey = 'netconsole.trackside-ap.last-task'
const router = useRouter()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const businessTaskActions = new Set(['trackside_ap_optical_update', 'trackside_ap_business_export'])
const initialLoading = ref(false)
const refreshing = ref(false)
const taskSubmitting = ref(false)
const error = ref('')
const page = ref<TracksideApBusinessPage | null>(null)
const task = ref<TracksideApTask | null>(null)
const filters = reactive({ station: '', query: '', optical_anomaly_only: false, page: 1, page_size: 50 })
let pollTimer: number | undefined
let loadGeneration = 0

interface TaskResultRow { name: string; value: string }

const businessColumns: NcTableColumn<TracksideApBusinessRow>[] = [
  { key: 'site', label: '站点', valueType: 'name', fixed: 'left' },
  { key: 'device_name', label: '车站交换机', valueType: 'name', fixed: 'left' },
  { key: 'interface_name', label: '接口', valueType: 'port', displayValue: (row) => displayTracksideValue(displayInterfaceName(row.interface_name)) },
  { key: 'link_status', label: '链路', valueType: 'status' },
  { key: 'port_type', label: '端口类型', valueType: 'status' },
  { key: 'description', label: '描述', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
  { key: 'pvid', label: 'PVID', valueType: 'number', displayValue: (row) => displayTracksideValue(row.pvid) },
  { key: 'vlan', label: 'VLAN', displayValue: (row) => displayTracksideValue(row.vlan) },
  { key: 'switch_rx_power', label: '交换机 Rx', valueType: 'number' },
  { key: 'switch_optical_status', label: '交换机光衰', valueType: 'status', cellKind: 'tag' },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac' },
  { key: 'ap_name', label: '当前轨旁 AP', valueType: 'name' },
  { key: 'ap_rx_power', label: 'AP Rx', valueType: 'number' },
  { key: 'ap_optical_status', label: 'AP 光衰', valueType: 'status', cellKind: 'tag' },
  { key: 'optical_severity', label: '综合', valueType: 'status', cellKind: 'tag' },
  { key: 'updated_at', label: '更新时间', valueType: 'datetime' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['更新站点', '更新 AP'] },
]
const taskResultColumns: NcTableColumn<TaskResultRow>[] = [
  { key: 'name', label: '结果项', valueType: 'name' },
  { key: 'value', label: '值', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
const taskRows = computed<TaskResultRow[]>(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) })))
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const exportArtifactAvailable = computed(() => (
  task.value?.status === 'COMPLETED'
  && task.value.action === 'trackside_ap_business_export'
  && task.value.available
  && Boolean(task.value.artifact_id)
))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: TracksideApTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) {
    if (task.value?.status === 'COMPLETED' && task.value.action === 'trackside_ap_optical_update') void loadRows()
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getTracksideApTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '轨旁 AP 任务状态读取失败') }
  }, 1000)
}

async function loadRows(reset = false): Promise<void> {
  if (reset) filters.page = 1
  const generation = ++loadGeneration
  const firstLoad = page.value === null
  if (firstLoad) initialLoading.value = true
  else refreshing.value = true
  error.value = ''
  try {
    const nextPage = await listTracksideApBusiness({ ...filters })
    if (generation === loadGeneration) page.value = nextPage
  } catch (reason) {
    if (generation === loadGeneration) error.value = failure(reason, '轨旁 AP 业务加载失败')
  } finally {
    if (generation === loadGeneration) {
      initialLoading.value = false
      refreshing.value = false
    }
  }
}

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string): Promise<void> {
  taskSubmitting.value = true; error.value = ''
  try { rememberTask(await factory()); poll(); openTaskWindow() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { taskSubmitting.value = false }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate(), '轨旁 AP 光衰更新启动失败') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败') }
function updateAp(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ ap_mac: row.ap_mac, ap_name: row.ap_name }), 'AP 更新启动失败') }
function exportBusiness(): void { void startTask(() => startTracksideApBusinessExport(), '轨旁 AP 业务导出启动失败') }
async function downloadExport(): Promise<void> {
  if (!task.value?.artifact_id || !exportArtifactAvailable.value) return
  try {
    const result = await downloadBackendResource(tracksideApBusinessDownloadRequest(task.value.artifact_id))
    if (result.status === 'failed') ElMessage.error(result.error || '轨旁 AP 业务表格保存失败')
    else if (result.status === 'saved') ElMessage.success('轨旁 AP 业务表格已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载')
  } catch {
    ElMessage.error('轨旁 AP 业务表格保存失败')
  }
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
  if (!isFeatureEnabled('web.rail_task_control')) return
  try {
    const rows = (await recoverTracksideApTasks()).filter((item) => businessTaskActions.has(item.action))
    const saved = localStorage.getItem(storageKey) || ''
    rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => !terminalStates.has(item.status)) || rows[0] || null); poll()
  } catch (reason) { error.value = failure(reason, '轨旁 AP 任务恢复失败') }
}

onMounted(() => { void Promise.all([loadRows(), recoverTasks()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="trackside-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · TRACKSIDE AP</p><h1>轨旁 AP 业务</h1><p>交换机端口、当前 AP、光功率与异常状态来自正式设备事实和既有光衰规则。</p></div>
      <div class="actions">
        <el-button :loading="refreshing" :disabled="initialLoading" @click="loadRows()">刷新</el-button>
        <el-button
          type="primary"
          :loading="taskSubmitting"
          :disabled="taskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_update') || !isFeatureEnabled('web.rail_task_control')"
          @click="updateAll"
        >更新全部光衰</el-button>
        <el-button
          :loading="taskSubmitting"
          :disabled="taskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_export') || !isFeatureEnabled('web.rail_task_control')"
          @click="exportBusiness"
        >导出表格</el-button>
        <el-button @click="openTaskWindow">打开任务窗口</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <div v-if="page" class="summary-grid">
      <article><span>站点交换机</span><strong>{{ page.device_count }}</strong></article><article><span>候选 AP 端口</span><strong>{{ page.candidate_interface_count }}</strong></article><article><span>光衰异常</span><strong>{{ page.optical_abnormal_count }}</strong></article><article><span>FIT-AP 资源</span><strong>{{ page.fit_ap_resource_count }}</strong></article><article><span>查询 / 构建</span><strong>{{ page.query_ms }} / {{ page.build_ms }} ms</strong></article>
    </div>
    <div class="content-card">
      <div class="toolbar">
        <el-input v-model="filters.query" clearable placeholder="交换机、接口、AP、MAC" @keyup.enter="loadRows(true)" />
        <el-input v-model="filters.station" clearable placeholder="站点" />
        <el-checkbox v-model="filters.optical_anomaly_only">仅光衰异常</el-checkbox>
        <el-button type="primary" :loading="refreshing" :disabled="initialLoading" @click="loadRows(true)">查询</el-button>
        <span v-if="refreshing" class="refresh-indicator">正在刷新，当前数据保持显示</span>
      </div>
      <NcDataTable
        v-loading="initialLoading"
        table-id="trackside-ap-business"
        route-key="/rail-transit/trackside-ap-business"
        :data="page?.items || []"
        :columns="businessColumns"
        height="calc(100vh - 470px)"
        :empty-text="page?.empty_reason || '暂无轨旁 AP 业务数据'"
      >
        <template #cell-switch_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_rx_power) }}</span></template>
        <template #cell-switch_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.switch_optical_status).tagType" :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ tracksideOpticalPresentation(row.switch_optical_status).label }}</el-tag></template>
        <template #cell-ap_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_rx_power) }}</span></template>
        <template #cell-ap_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.ap_optical_status).tagType" :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ tracksideOpticalPresentation(row.ap_optical_status).label }}</el-tag></template>
        <template #cell-optical_severity="{ row }"><el-tag :type="tracksideOpticalPresentation(row.optical_severity).tagType" :class="tracksideOpticalPresentation(row.optical_severity).className">{{ tracksideOpticalPresentation(row.optical_severity).label }}</el-tag></template>
        <template #cell-actions="{ row }"><el-button link type="primary" :disabled="taskRunning || !row.site || !isFeatureEnabled('web.rail_trackside_ap_business_update')" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :disabled="taskRunning || !row.ap_name || !isFeatureEnabled('web.rail_trackside_ap_business_update')" @click="updateAp(row)">更新 AP</el-button></template>
      </NcDataTable>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="page?.page || filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" /></div>
    </div>
    <div v-if="task" class="content-card task-card"><div class="task-heading"><div><h2>轨旁 AP 任务</h2><p>{{ task.task_id }}</p></div><div class="task-actions"><el-tag>{{ task.status }}</el-tag><el-button v-if="exportArtifactAvailable" type="primary" @click="downloadExport">保存导出表格</el-button></div></div><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><NcDataTable v-if="taskRows.length" table-id="trackside-ap-business-task-result" route-key="/rail-transit/trackside-ap-business" :data="taskRows" :columns="taskResultColumns" max-height="300" :show-column-settings="false" /><el-alert title="停止、日志和恢复统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow">打开任务窗口</el-button></el-alert></div>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.pagination,.task-heading,.task-actions{display:flex;align-items:center;gap:12px}.page-heading,.pagination,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions,.toolbar{flex-wrap:wrap}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{margin-bottom:12px}.toolbar .el-input{width:230px}.refresh-indicator{color:var(--el-color-primary);font-size:13px}.pagination{padding-top:12px}.task-card{display:flex;flex-direction:column;gap:12px}.optical-normal{color:var(--el-color-success)}.optical-notice,.optical-warning{color:var(--el-color-warning)}.optical-alarm,.optical-link-abnormal,.optical-link-down,.optical-no-light,.optical-no-module,.optical-offline{color:var(--el-color-danger);font-weight:600}.optical-missing,.optical-skipped,.optical-not-collected,.optical-unknown{color:var(--el-text-color-secondary)}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
</style>
