<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTracksideApTask,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
} from '../../api/tracksideApBusiness'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import type { TracksideApBusinessPage, TracksideApBusinessRow, TracksideApTask, TracksideApUpdateRequest } from '../../types/tracksideApBusiness'
import { displayInterfaceName } from '../../utils/interfaceName'
import {
  isTracksideApBusinessArtifactTask,
  saveTracksideApBusinessArtifact,
  TRACKSIDE_AP_BUSINESS_EXPORT_ACTION,
} from './tracksideApBusinessArtifact'
import { displayTracksideValue, tracksideOpticalPresentation } from './tracksideApBusinessDisplay'

const storageKey = 'netconsole.trackside-ap.last-task'
const autoSaveStorageKey = 'netconsole.trackside-ap-business.auto-saved-task-ids'
const router = useRouter()
const activeStates = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'QUEUED', 'CANCELLING'])
const businessTaskActions = new Set(['trackside_ap_optical_update', TRACKSIDE_AP_BUSINESS_EXPORT_ACTION])
const autoSaveInFlight = new Set<string>()
const initialLoading = ref(false)
const refreshing = ref(false)
const taskSubmitting = ref(false)
const pendingScopeKey = ref('')
const error = ref('')
const taskNotice = ref('')
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
const updateTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === 'trackside_ap_optical_update')
const exportTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === TRACKSIDE_AP_BUSINESS_EXPORT_ACTION)
const updateFeatureEnabled = computed(() => isFeatureEnabled('web.rail_trackside_ap_business_update') && isFeatureEnabled('web.rail_task_control'))
const taskOutcome = computed(() => {
  if (!task.value || task.value.action !== 'trackside_ap_optical_update' || isActiveTask(task.value)) return null
  const summary = task.value.result_summary || {}
  const status = String(summary.status || task.value.status || '').toUpperCase()
  const targetCount = Number(summary.target_count ?? 0)
  const successCount = Number(summary.success_count ?? 0)
  const failedCount = Number(summary.failed_count ?? 0)
  const skippedCount = Number(summary.skipped_count ?? 0)
  if (status === 'NO_TARGET' || targetCount === 0) return { type: 'info', title: '未找到目标' }
  if (task.value.status === 'FAILED' || failedCount > 0 && successCount === 0) return { type: 'error', title: '更新失败' }
  if (failedCount > 0 || skippedCount > 0 || status === 'CANCELLED') return { type: 'warning', title: '部分成功' }
  return { type: 'success', title: '更新成功' }
})
const exportArtifactAvailable = computed(() => (
  task.value?.status === 'COMPLETED'
  && isTracksideApBusinessArtifactTask(task.value)
  && task.value.available
  && Boolean(task.value.artifact_id)
  && Boolean(task.value.artifact_name)
))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: TracksideApTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function isActiveTask(value: TracksideApTask | null): boolean { return Boolean(value && activeStates.has(value.status)) }
function cleanIdentity(value: string): string { return String(value || '').trim() }
function singleApUpdatePayload(row: TracksideApBusinessRow): TracksideApUpdateRequest | null {
  const apUuid = cleanIdentity(row.ap_uuid)
  if (apUuid) return { ap_uuid: apUuid }
  const apMac = cleanIdentity(row.ap_mac)
  if (apMac) return { ap_mac: apMac }
  const apName = cleanIdentity(row.ap_name)
  if (apName) return { ap_name: apName }
  return null
}
function hasApIdentity(row: TracksideApBusinessRow): boolean { return singleApUpdatePayload(row) !== null }
function autoSavedTaskIds(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(autoSaveStorageKey) || '[]')
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}
function rememberAutoSavedTask(taskId: string): void {
  const values = [...autoSavedTaskIds().filter((item) => item !== taskId), taskId].slice(-50)
  try { localStorage.setItem(autoSaveStorageKey, JSON.stringify(values)) } catch { /* ignore quota errors */ }
}
function shouldAutoSaveExport(value: TracksideApTask | null): value is TracksideApTask {
  if (!value || value.status !== 'COMPLETED' || !value.available || !isTracksideApBusinessArtifactTask(value) || !value.artifact_id || !value.artifact_name) return false
  return !autoSavedTaskIds().includes(value.task_id) && !autoSaveInFlight.has(value.task_id)
}
async function maybeAutoSaveExport(value: TracksideApTask | null): Promise<void> {
  if (!shouldAutoSaveExport(value)) return
  autoSaveInFlight.add(value.task_id)
  rememberAutoSavedTask(value.task_id)
  try { await saveTracksideApBusinessArtifact(value) }
  finally { autoSaveInFlight.delete(value.task_id) }
}
function taskSubmitNotice(started: TracksideApTask, scope: string, target: string): string {
  return `任务已提交：范围 ${scope}；目标 ${target}；状态 ${started.status}`
}

function handleTerminalTask(value: TracksideApTask | null): void {
  if (value?.status === 'COMPLETED' && value.action === 'trackside_ap_optical_update') void loadRows()
  if (shouldAutoSaveExport(value)) void maybeAutoSaveExport(value)
}

function poll(): void {
  stopPolling()
  if (!task.value || !isActiveTask(task.value)) {
    handleTerminalTask(task.value)
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

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string, scopeKey: string, scope: string, target: string, notice = ''): Promise<void> {
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true; error.value = ''
  try {
    const started = await factory()
    rememberTask(started)
    taskNotice.value = notice || taskSubmitNotice(started, scope, target)
    poll()
    openTaskWindow()
  }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { taskSubmitting.value = false; pendingScopeKey.value = '' }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate({}), '轨旁 AP 光衰更新启动失败', 'update:all', '全部', '当前局点') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败', `update:station:${row.site}`, '站点', row.site) }
function updateAp(row: TracksideApBusinessRow): void {
  const payload = singleApUpdatePayload(row)
  if (!payload) { error.value = '缺少 AP 身份，无法定向更新'; return }
  const target = cleanIdentity(row.ap_name) || cleanIdentity(row.ap_mac) || cleanIdentity(row.ap_uuid)
  const scopeValue = payload.ap_uuid || payload.ap_mac || payload.ap_name || target
  void startTask(
    () => startTracksideApUpdate(payload),
    'AP 更新启动失败',
    `update:ap:${scopeValue}`,
    'AP',
    target,
  )
}
function exportBusiness(): void { void startTask(() => startTracksideApBusinessExport(), '轨旁 AP 业务导出启动失败', 'export:business', '导出', '轨旁 AP 业务表格', '轨旁 AP 业务表格正在生成') }
async function downloadExport(): Promise<void> {
  if (!task.value || !exportArtifactAvailable.value) return
  await saveTracksideApBusinessArtifact(task.value)
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
    const savedTask = rows.find((item) => item.task_id === saved)
    const activeUpdate = rows.find((item) => item.action === 'trackside_ap_optical_update' && isActiveTask(item))
    const activeAny = rows.find((item) => isActiveTask(item))
    rememberTask(savedTask && isActiveTask(savedTask) ? savedTask : activeUpdate || activeAny || null); poll()
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
          :disabled="updateTaskRunning || !updateFeatureEnabled"
          @click="updateAll"
        >更新全部光衰</el-button>
        <el-button
          :loading="taskSubmitting"
          :disabled="exportTaskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_export') || !isFeatureEnabled('web.rail_task_control')"
          @click="exportBusiness"
        >导出表格</el-button>
        <el-button @click="openTaskWindow">打开任务窗口</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <el-alert v-if="taskNotice" :title="taskNotice" type="success" show-icon :closable="false" />
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
        <template #cell-actions="{ row }"><el-button link type="primary" :disabled="updateTaskRunning || !row.site || !updateFeatureEnabled" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :title="hasApIdentity(row) ? '' : '缺少 AP 身份，无法定向更新'" :disabled="updateTaskRunning || !hasApIdentity(row) || !updateFeatureEnabled" @click="updateAp(row)">更新 AP</el-button></template>
      </NcDataTable>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="page?.page || filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" /></div>
    </div>
    <div v-if="task" class="content-card task-card"><div class="task-heading"><div><h2>轨旁 AP 任务</h2><p>{{ task.task_id }}</p></div><div class="task-actions"><el-tag>{{ task.status }}</el-tag><el-button v-if="exportArtifactAvailable" type="primary" @click="downloadExport">保存导出表格</el-button></div></div><el-alert v-if="taskOutcome" :title="taskOutcome.title" :type="taskOutcome.type" :closable="false" show-icon /><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><NcDataTable v-if="taskRows.length" table-id="trackside-ap-business-task-result" route-key="/rail-transit/trackside-ap-business" :data="taskRows" :columns="taskResultColumns" max-height="300" :show-column-settings="false" /><el-alert title="停止、日志和恢复统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow">打开任务窗口</el-button></el-alert></div>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.pagination,.task-heading,.task-actions{display:flex;align-items:center;gap:12px}.page-heading,.pagination,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions,.toolbar{flex-wrap:wrap}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{margin-bottom:12px}.toolbar .el-input{width:230px}.refresh-indicator{color:var(--el-color-primary);font-size:13px}.pagination{padding-top:12px}.task-card{display:flex;flex-direction:column;gap:12px}.optical-normal{color:var(--el-color-success)}.optical-notice,.optical-warning{color:var(--el-color-warning)}.optical-alarm,.optical-link-abnormal,.optical-link-down,.optical-no-light,.optical-offline{color:var(--el-color-danger);font-weight:600}.optical-no-module,.optical-missing,.optical-skipped,.optical-not-collected,.optical-unknown{color:var(--el-text-color-secondary)}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
</style>
