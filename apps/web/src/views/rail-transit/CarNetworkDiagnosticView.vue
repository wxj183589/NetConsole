<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getCarNetworkDiagnosticTask,
  listOnlineTrains,
  recoverCarNetworkDiagnostics,
  startCarNetworkDiagnostic,
} from '../../api/railTransitWeb'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import type { OnlineTrainRow, RailTransitTask } from '../../types/railTransitWeb'
import CarNetworkPointTableDialog from './CarNetworkPointTableDialog.vue'

const storageKey = 'netconsole.car-network-diagnostic.last-task'
const router = useRouter()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const trains = ref<OnlineTrainRow[]>([])
const selectedTrainId = ref('')
const task = ref<RailTransitTask | null>(null)
const loading = ref(false)
const error = ref('')
const pointTableVisible = ref(false)
let pollTimer: number | undefined

interface DiagnosticResultRow { name: string; value: string }

const trainColumns: NcTableColumn<OnlineTrainRow>[] = [
  { key: 'train_no', label: '列车', valueType: 'name', fixed: 'left' },
  { key: 'train_name', label: '名称', valueType: 'name' },
  { key: 'communication_status', label: '通信状态', valueType: 'status' },
  { key: 'current_mesh_links', label: 'Mesh-Link', valueType: 'number' },
  { key: 'active_sessions', label: '活动会话', valueType: 'number' },
  { key: 'warning_count', label: '告警', valueType: 'number' },
  { key: 'last_updated_at', label: '更新时间', valueType: 'datetime' },
]
const resultColumns: NcTableColumn<DiagnosticResultRow>[] = [
  { key: 'name', label: '结果项', valueType: 'name' },
  { key: 'value', label: '诊断结果', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
const canStart = computed(() => Boolean(
  selectedTrainId.value
  && !loading.value
  && (!task.value || terminalStates.has(task.value.status))
  && isFeatureEnabled('web.rail_car_network_diagnostic_execute')
  && isFeatureEnabled('web.rail_task_control'),
))
const resultRows = computed<DiagnosticResultRow[]>(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({
  name,
  value: typeof value === 'string' ? value : JSON.stringify(value),
})))

function failure(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function rememberTask(value: RailTransitTask | null): void {
  task.value = value
  if (value) localStorage.setItem(storageKey, value.task_id)
  else localStorage.removeItem(storageKey)
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try {
      rememberTask(await getCarNetworkDiagnosticTask(task.value!.task_id))
      error.value = ''
      poll()
    } catch (reason) {
      error.value = failure(reason, '车内通信检测状态读取失败')
    }
  }, 1000)
}

async function loadTrains(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    trains.value = (await listOnlineTrains(1, 200)).items
    if (!selectedTrainId.value && trains.value.length === 1) selectedTrainId.value = trains.value[0].train_id
  } catch (reason) {
    error.value = failure(reason, '在线列车加载失败')
  } finally {
    loading.value = false
  }
}

async function startDiagnostic(): Promise<void> {
  if (!canStart.value) return
  loading.value = true
  error.value = ''
  try {
    rememberTask(await startCarNetworkDiagnostic(selectedTrainId.value))
    poll()
    openTaskWindow()
  } catch (reason) {
    error.value = failure(reason, '车内通信检测启动失败')
  } finally {
    loading.value = false
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

async function recoverDiagnostic(): Promise<void> {
  if (!isFeatureEnabled('web.rail_task_control')) return
  try {
    const savedId = localStorage.getItem(storageKey) || ''
    const recovered = await recoverCarNetworkDiagnostics()
    rememberTask(recovered.find((item) => item.task_id === savedId)
      || recovered.find((item) => item.action === 'car_network_diagnostic' && !terminalStates.has(item.status))
      || recovered.find((item) => item.action === 'car_network_diagnostic')
      || null)
    poll()
  } catch (reason) {
    error.value = failure(reason, '车内通信检测恢复失败')
  }
}

onMounted(() => { void Promise.all([loadTrains(), recoverDiagnostic()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="diagnostic-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · CAR NETWORK</p><h1>车内通信检测</h1><p>按列车执行 AC 在线状态、MR SSH、跨 TC 丢包与核心侧辅助 Ping 检测。</p></div>
      <div class="actions"><el-button :loading="loading" @click="loadTrains">刷新列车</el-button><el-button :disabled="!isFeatureEnabled('web.rail_car_network_point_table_write')" @click="pointTableVisible = true">点表管理</el-button><el-button type="primary" :disabled="!canStart" :loading="loading" @click="startDiagnostic">开始检测</el-button><el-button @click="openTaskWindow">打开任务窗口</el-button></div>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverDiagnostic">恢复任务状态</el-button></el-alert>

    <div class="content-card">
      <NcDataTable v-loading="loading" table-id="car-network-diagnostic-trains" route-key="/rail-transit/car-network-diagnostic" :data="trains" :columns="trainColumns" row-key="train_id" height="340" empty-text="暂无可检测的在线列车" highlight-current-row @current-change="(row: OnlineTrainRow | undefined) => selectedTrainId = row?.train_id || ''" />
      <p class="selection">当前选择：{{ trains.find((item) => item.train_id === selectedTrainId)?.train_name || '请选择列车' }}</p>
    </div>

    <div v-if="task" class="content-card task-card">
      <div class="task-heading"><div><h2>检测任务</h2><p>{{ task.task_id }}</p></div><el-tag :type="task.status === 'COMPLETED' ? 'success' : task.status === 'FAILED' ? 'danger' : task.status === 'CANCELLED' ? 'warning' : 'primary'">{{ task.status }}</el-tag></div>
      <el-alert title="停止、日志和任务恢复统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow">打开任务窗口</el-button></el-alert>
      <el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" show-icon />
      <p v-else-if="task.message" class="task-message">{{ task.message }}</p>
      <NcDataTable v-if="resultRows.length" table-id="car-network-diagnostic-result" route-key="/rail-transit/car-network-diagnostic" :data="resultRows" :columns="resultColumns" border max-height="460" />
      <el-empty v-else-if="terminalStates.has(task.status)" description="任务没有返回诊断结果" />
      <el-skeleton v-else :rows="4" animated />
    </div>
    <CarNetworkPointTableDialog v-model="pointTableVisible" />
  </section>
</template>

<style scoped>
.diagnostic-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.task-heading{display:flex;align-items:center;gap:12px}.page-heading,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p,.selection,.task-message{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions{flex-wrap:wrap}.content-card{padding:14px 16px;overflow:hidden;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.selection{padding-top:12px}.task-card{display:flex;flex-direction:column;gap:12px}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}}
</style>
