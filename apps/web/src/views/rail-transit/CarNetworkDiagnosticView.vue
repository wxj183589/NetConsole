<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  cancelCarNetworkDiagnostic,
  getCarNetworkDiagnosticTask,
  listOnlineTrains,
  recoverCarNetworkDiagnostics,
  startCarNetworkDiagnostic,
} from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import type { OnlineTrainRow, RailTransitTask } from '../../types/railTransitWeb'
import CarNetworkPointTableDialog from './CarNetworkPointTableDialog.vue'

const storageKey = 'netconsole.car-network-diagnostic.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const trains = ref<OnlineTrainRow[]>([])
const selectedTrainId = ref('')
const task = ref<RailTransitTask | null>(null)
const loading = ref(false)
const error = ref('')
const pointTableVisible = ref(false)
let pollTimer: number | undefined

const canStart = computed(() => Boolean(
  selectedTrainId.value
  && !loading.value
  && (!task.value || terminalStates.has(task.value.status))
  && isFeatureEnabled('web.rail_car_network_diagnostic_execute')
  && isFeatureEnabled('web.rail_task_control'),
))
const resultRows = computed(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({
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
  } catch (reason) {
    error.value = failure(reason, '车内通信检测启动失败')
  } finally {
    loading.value = false
  }
}

async function cancelDiagnostic(): Promise<void> {
  if (!task.value || terminalStates.has(task.value.status)) return
  loading.value = true
  error.value = ''
  try {
    rememberTask(await cancelCarNetworkDiagnostic(task.value.task_id))
    poll()
  } catch (reason) {
    error.value = failure(reason, '车内通信检测取消失败')
  } finally {
    loading.value = false
  }
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
      <div class="actions"><el-button :loading="loading" @click="loadTrains">刷新列车</el-button><el-button :disabled="!isFeatureEnabled('web.rail_car_network_point_table_write')" @click="pointTableVisible = true">点表管理</el-button><el-button type="primary" :disabled="!canStart" :loading="loading" @click="startDiagnostic">开始检测</el-button><el-button type="danger" plain :disabled="!task || terminalStates.has(task.status)" @click="cancelDiagnostic">取消检测</el-button></div>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverDiagnostic">恢复任务状态</el-button></el-alert>

    <div class="content-card">
      <el-table v-loading="loading" :data="trains" stripe height="340" empty-text="暂无可检测的在线列车" highlight-current-row @current-change="(row: OnlineTrainRow | undefined) => selectedTrainId = row?.train_id || ''">
        <el-table-column prop="train_no" label="列车" width="95" fixed="left" />
        <el-table-column prop="train_name" label="名称" min-width="140" />
        <el-table-column prop="communication_status" label="通信状态" width="110" />
        <el-table-column prop="current_mesh_links" label="Mesh-Link" width="105" />
        <el-table-column prop="active_sessions" label="活动会话" width="100" />
        <el-table-column prop="warning_count" label="告警" width="80" />
        <el-table-column prop="last_updated_at" label="更新时间" width="180" />
      </el-table>
      <p class="selection">当前选择：{{ trains.find((item) => item.train_id === selectedTrainId)?.train_name || '请选择列车' }}</p>
    </div>

    <div v-if="task" class="content-card task-card">
      <div class="task-heading"><div><h2>检测任务</h2><p>{{ task.task_id }}</p></div><el-tag :type="task.status === 'COMPLETED' ? 'success' : task.status === 'FAILED' ? 'danger' : task.status === 'CANCELLED' ? 'warning' : 'primary'">{{ task.status }}</el-tag></div>
      <el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" show-icon />
      <p v-else-if="task.message" class="task-message">{{ task.message }}</p>
      <el-table v-if="resultRows.length" :data="resultRows" border max-height="460"><el-table-column prop="name" label="结果项" width="220" /><el-table-column prop="value" label="诊断结果" min-width="520" show-overflow-tooltip /></el-table>
      <el-empty v-else-if="terminalStates.has(task.status)" description="任务没有返回诊断结果" />
      <el-skeleton v-else :rows="4" animated />
    </div>
    <CarNetworkPointTableDialog v-model="pointTableVisible" />
  </section>
</template>

<style scoped>
.diagnostic-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.task-heading{display:flex;align-items:center;gap:12px}.page-heading,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p,.selection,.task-message{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions{flex-wrap:wrap}.content-card{padding:14px 16px;overflow:hidden;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.selection{padding-top:12px}.task-card{display:flex;flex-direction:column;gap:12px}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}}
</style>
