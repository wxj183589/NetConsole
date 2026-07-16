<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  cancelVehicleMrOnlineTask,
  getVehicleMrOnlineTask,
  listVehicleMrEvents,
  listVehicleMrMappings,
  listVehicleMrOnline,
  recoverVehicleMrOnlineTasks,
  refreshVehicleMrApMapping,
  refreshVehicleMrOnline,
  saveVehicleMrMappings,
} from '../../api/vehicleMrOnline'
import { isFeatureEnabled } from '../../features'
import type { VehicleMrOnlinePage, VehicleMrOnlineTask, VehicleMrTrainMapping, VehicleMrTrainState } from '../../types/vehicleMrOnline'

const router = useRouter()
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
const filters = reactive({ query: '', train_status: '', page: 1, page_size: 50 })
let pollTimer: number | undefined

const taskRows = computed(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) })))
function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: VehicleMrOnlineTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value.includes('离线')) return 'danger'
  if (['单端在线', '异常单端', '非预期端在线'].includes(value)) return 'warning'
  if (['在线', '双端在线'].includes(value)) return 'success'
  return 'info'
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) {
    if (task.value?.status === 'COMPLETED') void Promise.all([loadTrains(), loadMappings()])
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getVehicleMrOnlineTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '列车在线任务状态读取失败') }
  }, 1000)
}

async function loadTrains(reset = false): Promise<void> {
  if (reset) filters.page = 1
  loading.value = true; error.value = ''
  try { page.value = await listVehicleMrOnline(filters) }
  catch (reason) { error.value = failure(reason, '列车在线状态加载失败') }
  finally { loading.value = false }
}
async function loadMappings(): Promise<void> { try { mappings.value = await listVehicleMrMappings() } catch (reason) { error.value = failure(reason, '列车 MR 映射加载失败') } }
async function startTask(factory: () => Promise<VehicleMrOnlineTask>, fallback: string): Promise<void> {
  loading.value = true; error.value = ''
  try { rememberTask(await factory()); poll() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { loading.value = false }
}
function refreshAll(): void { void startTask(refreshVehicleMrOnline, '列车在线状态刷新启动失败') }
function refreshApMapping(): void { void startTask(() => refreshVehicleMrApMapping(selectedTrain.value?.train_id || ''), '轨旁 AP 映射刷新启动失败') }
async function openEvents(row: VehicleMrTrainState): Promise<void> {
  selectedTrain.value = row; detailVisible.value = true
  try { events.value = (await listVehicleMrEvents(row.train_id)).items } catch (reason) { error.value = failure(reason, '列车经过历史加载失败') }
}
async function openMappings(): Promise<void> { await loadMappings(); mappingVisible.value = true }
function addMapping(): void { mappings.value.push({ id: null, enabled: true, train_display_name: '', train_id: '', train_no: '', tc1_peer_name: '', tc2_peer_name: '', online_policy: 'auto', remark: '', created_at: '', updated_at: '' }) }
function deleteMapping(index: number): void { mappings.value.splice(index, 1) }
function saveMappings(): void { void startTask(() => saveVehicleMrMappings(mappings.value), '列车 MR 映射保存失败'); mappingVisible.value = false }
async function cancelTask(): Promise<void> { if (task.value && !terminalStates.has(task.value.status)) await startTask(() => cancelVehicleMrOnlineTask(task.value!.task_id), '列车在线任务取消失败') }
async function recoverTasks(): Promise<void> {
  try { const rows = await recoverVehicleMrOnlineTasks(); const saved = localStorage.getItem(storageKey) || ''; rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => !terminalStates.has(item.status)) || rows[0] || null); poll() }
  catch (reason) { error.value = failure(reason, '列车在线任务恢复失败') }
}

onMounted(() => { void Promise.all([loadTrains(), loadMappings(), recoverTasks()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="vehicle-page">
    <header class="page-heading"><div><p class="eyebrow">RAIL TRANSIT · VEHICLE MR ONLINE</p><h1>列车在线情况</h1><p>按 CT/TC 展示当前轨旁 AP、站点、RSSI、最后出现时间与映射策略。</p></div><div class="actions"><el-button :loading="loading" @click="loadTrains()">刷新页面</el-button><el-button :disabled="!isFeatureEnabled('web.rail_train_online_refresh')" @click="refreshAll">刷新在线状态</el-button><el-button :disabled="!isFeatureEnabled('web.rail_train_online_refresh')" @click="refreshApMapping">刷新 AP 映射</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.rail_train_online_mapping_write')" @click="openMappings">映射表管理</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <div v-if="page" class="summary-grid"><article><span>在线</span><strong>{{ page.online_count }}</strong></article><article><span>异常</span><strong>{{ page.abnormal_count }}</strong></article><article><span>离线</span><strong>{{ page.offline_count }}</strong></article><article><span>未登记</span><strong>{{ page.unregistered_count }}</strong></article></div>
    <div class="content-card"><div class="toolbar"><el-input v-model="filters.query" clearable placeholder="列车、AP 或站点" @keyup.enter="loadTrains(true)" /><el-select v-model="filters.train_status" clearable placeholder="在线状态"><el-option v-for="value in ['双端在线','在线','单端在线','异常单端','非预期端在线','离线']" :key="value" :label="value" :value="value" /></el-select><el-button type="primary" @click="loadTrains(true)">查询</el-button></div>
      <el-table v-loading="loading" :data="page?.items || []" stripe height="calc(100vh - 430px)" empty-text="暂无列车在线状态" highlight-current-row @current-change="(row: VehicleMrTrainState | undefined) => selectedTrain = row || null" @row-dblclick="openEvents">
        <el-table-column prop="display_name" label="列车" width="100" fixed="left" /><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template></el-table-column><el-table-column label="MR-CT 当前 AP" min-width="165"><template #default="{ row }">{{ display(row.tc1.ap_name) }}</template></el-table-column><el-table-column label="CT 站点 / RSSI" min-width="180"><template #default="{ row }">{{ display(row.tc1.station) }} / {{ display(row.tc1.rssi, ' dBm') }}</template></el-table-column><el-table-column label="MR-TC 当前 AP" min-width="165"><template #default="{ row }">{{ display(row.tc2.ap_name) }}</template></el-table-column><el-table-column label="TC 站点 / RSSI" min-width="180"><template #default="{ row }">{{ display(row.tc2.station) }} / {{ display(row.tc2.rssi, ' dBm') }}</template></el-table-column><el-table-column prop="current_station" label="当前位置" width="130" /><el-table-column prop="direction" label="方向" width="85" /><el-table-column prop="online_policy" label="在线策略" width="105" /><el-table-column prop="status_reason" label="状态原因" min-width="180" show-overflow-tooltip /><el-table-column prop="last_ac_time" label="AC 时间" width="175" /><el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openEvents(row)">经过历史</el-button><el-button link type="primary" @click="router.push({ path: '/rail-transit/train-communication', query: { train: row.train_no } })">通信详情</el-button></template></el-table-column>
      </el-table><div class="pagination"><span>共 {{ page?.total || 0 }} 列车</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadTrains() }" /></div>
    </div>
    <div v-if="task" class="content-card task-card"><div class="task-heading"><div><h2>列车在线任务</h2><p>{{ task.task_id }}</p></div><el-tag>{{ task.status }}</el-tag></div><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><el-table v-if="taskRows.length" :data="taskRows" max-height="260"><el-table-column prop="name" label="结果项" width="220" /><el-table-column prop="value" label="值" /></el-table><el-button :disabled="terminalStates.has(task.status)" @click="cancelTask">取消任务</el-button></div>
    <el-drawer v-model="detailVisible" :title="`${selectedTrain?.display_name || ''} 经过历史`" size="min(1000px, 95vw)"><el-table :data="events" border height="calc(100vh - 150px)" empty-text="暂无经过历史"><el-table-column prop="event_time" label="时间" width="180" /><el-table-column prop="car_end_label" label="端" width="80" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="station" label="站点" width="140" /><el-table-column prop="ap_name" label="轨旁 AP" min-width="160" /><el-table-column prop="rssi" label="RSSI" width="90" /><el-table-column prop="match_method" label="匹配方式" min-width="150" /></el-table></el-drawer>
    <el-dialog v-model="mappingVisible" title="列车 MR 映射表" width="min(1150px, 96vw)" destroy-on-close><el-table :data="mappings" border height="520"><el-table-column label="启用" width="70"><template #default="{ row }"><el-checkbox v-model="row.enabled" /></template></el-table-column><el-table-column label="车次" width="130"><template #default="{ row }"><el-input v-model="row.train_display_name" /></template></el-table-column><el-table-column label="TC1 Peer Name" min-width="190"><template #default="{ row }"><el-input v-model="row.tc1_peer_name" /></template></el-table-column><el-table-column label="TC2 Peer Name" min-width="190"><template #default="{ row }"><el-input v-model="row.tc2_peer_name" /></template></el-table-column><el-table-column label="在线策略" width="170"><template #default="{ row }"><el-select v-model="row.online_policy"><el-option label="自动/未知" value="auto" /><el-option label="单端在线-尾端在线" value="single_tail" /><el-option label="双端在线" value="dual_active" /><el-option label="TC1 固定在线" value="single_tc1" /><el-option label="TC2 固定在线" value="single_tc2" /></el-select></template></el-table-column><el-table-column label="备注" min-width="180"><template #default="{ row }"><el-input v-model="row.remark" /></template></el-table-column><el-table-column label="操作" width="80"><template #default="{ $index }"><el-button link type="danger" @click="deleteMapping($index)">删除</el-button></template></el-table-column></el-table><template #footer><el-button @click="addMapping">新增</el-button><el-button @click="mappingVisible = false">取消</el-button><el-button type="primary" :disabled="!isFeatureEnabled('web.rail_train_online_mapping_write')" @click="saveMappings">保存映射</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.vehicle-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.pagination,.task-heading{display:flex;align-items:center;gap:12px}.page-heading,.pagination,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions,.toolbar{flex-wrap:wrap}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:24px}.content-card{padding:14px 16px;overflow:hidden}.toolbar{margin-bottom:12px}.toolbar .el-input{width:280px}.toolbar .el-select{width:140px}.pagination{padding-top:12px}.task-card{display:flex;flex-direction:column;gap:12px}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
</style>
