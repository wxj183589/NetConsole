<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTracksideApTask,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  startTracksideApUpdate,
} from '../../api/tracksideApBusiness'
import { isFeatureEnabled } from '../../features'
import type { TracksideApBusinessPage, TracksideApBusinessRow, TracksideApTask } from '../../types/tracksideApBusiness'

const storageKey = 'netconsole.trackside-ap.last-task'
const router = useRouter()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const loading = ref(false)
const error = ref('')
const page = ref<TracksideApBusinessPage | null>(null)
const task = ref<TracksideApTask | null>(null)
const filters = reactive({ station: '', query: '', optical_anomaly_only: false, page: 1, page_size: 50 })
let pollTimer: number | undefined

const taskRows = computed(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) })))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function display(value: unknown): string { return value === null || value === undefined || value === '' ? '无数据' : String(value) }
function severityType(value: string): 'success' | 'warning' | 'danger' | 'info' { return value === 'alarm' ? 'danger' : value === 'warning' ? 'warning' : value === 'normal' ? 'success' : 'info' }
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
  loading.value = true; error.value = ''
  try { page.value = await listTracksideApBusiness(filters) }
  catch (reason) { error.value = failure(reason, '轨旁 AP 业务加载失败') }
  finally { loading.value = false }
}

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string): Promise<void> {
  loading.value = true; error.value = ''
  try { rememberTask(await factory()); poll(); openTaskWindow() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { loading.value = false }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate(), '轨旁 AP 光衰更新启动失败') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败') }
function updateAp(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ ap_mac: row.ap_mac, ap_name: row.ap_name }), 'AP 更新启动失败') }
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
    const rows = await recoverTracksideApTasks(); const saved = localStorage.getItem(storageKey) || ''
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
      <div class="actions"><el-button :loading="loading" @click="loadRows()">刷新</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.rail_trackside_ap_business_update') || !isFeatureEnabled('web.rail_task_control')" @click="updateAll">更新全部光衰</el-button><el-button @click="openTaskWindow">打开任务窗口</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <div v-if="page" class="summary-grid">
      <article><span>站点交换机</span><strong>{{ page.device_count }}</strong></article><article><span>候选 AP 端口</span><strong>{{ page.candidate_interface_count }}</strong></article><article><span>光衰异常</span><strong>{{ page.optical_abnormal_count }}</strong></article><article><span>FIT-AP 资源</span><strong>{{ page.fit_ap_resource_count }}</strong></article><article><span>查询 / 构建</span><strong>{{ page.query_ms }} / {{ page.build_ms }} ms</strong></article>
    </div>
    <div class="content-card">
      <div class="toolbar"><el-input v-model="filters.query" clearable placeholder="交换机、接口、AP、MAC" @keyup.enter="loadRows(true)" /><el-input v-model="filters.station" clearable placeholder="站点" /><el-checkbox v-model="filters.optical_anomaly_only">仅光衰异常</el-checkbox><el-button type="primary" @click="loadRows(true)">查询</el-button></div>
      <el-table v-loading="loading" :data="page?.items || []" stripe height="calc(100vh - 470px)" :empty-text="page?.empty_reason || '暂无轨旁 AP 业务数据'">
        <el-table-column prop="site" label="站点" width="130" fixed="left" /><el-table-column prop="device_name" label="车站交换机" min-width="150" fixed="left" /><el-table-column prop="interface_name" label="接口" width="150" /><el-table-column prop="link_status" label="链路" width="85" /><el-table-column prop="port_type" label="端口类型" width="105" /><el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip /><el-table-column prop="pvid" label="PVID" width="80" /><el-table-column prop="vlan" label="VLAN" min-width="100" /><el-table-column label="交换机 Rx" width="110"><template #default="{ row }">{{ display(row.switch_rx_power) }}</template></el-table-column><el-table-column prop="switch_optical_status" label="交换机光衰" width="115" /><el-table-column prop="ap_mac" label="AP MAC" width="145" /><el-table-column prop="ap_name" label="当前轨旁 AP" min-width="155" /><el-table-column label="AP Rx" width="100"><template #default="{ row }">{{ display(row.ap_rx_power) }}</template></el-table-column><el-table-column prop="ap_optical_status" label="AP 光衰" width="105" /><el-table-column label="综合" width="90"><template #default="{ row }"><el-tag :type="severityType(row.optical_severity)">{{ row.optical_severity }}</el-tag></template></el-table-column><el-table-column prop="updated_at" label="更新时间" width="175" /><el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="!row.site || !isFeatureEnabled('web.rail_trackside_ap_business_update')" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :disabled="!row.ap_name || !isFeatureEnabled('web.rail_trackside_ap_business_update')" @click="updateAp(row)">更新 AP</el-button></template></el-table-column>
      </el-table>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" /></div>
    </div>
    <div v-if="task" class="content-card task-card"><div class="task-heading"><div><h2>轨旁 AP 更新结果</h2><p>{{ task.task_id }}</p></div><el-tag>{{ task.status }}</el-tag></div><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><el-table v-if="taskRows.length" :data="taskRows" max-height="300"><el-table-column prop="name" label="结果项" width="220" /><el-table-column prop="value" label="值" /></el-table><el-alert title="停止、日志和恢复统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow">打开任务窗口</el-button></el-alert></div>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.pagination,.task-heading{display:flex;align-items:center;gap:12px}.page-heading,.pagination,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions,.toolbar{flex-wrap:wrap}.summary-grid{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{margin-bottom:12px}.toolbar .el-input{width:230px}.pagination{padding-top:12px}.task-card{display:flex;flex-direction:column;gap:12px}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
</style>
