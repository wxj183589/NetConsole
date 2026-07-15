<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  calculateIpv4,
  calculateIpv6,
  calculateSubnets,
  calculateVlsm,
  calculateWildcard,
  cancelNetworkTask,
  exportNetworkTask,
  listNetworkTasks,
  startNetworkTask,
  summarizeRoutes,
} from '../../api/networkTools'
import type { NetworkToolTask, ToolboxResult } from '../../types/networkTools'

const calculator = ref('ipv4')
const text = ref('192.168.1.10/24')
const parent = ref('192.168.0.0/22')
const requests = ref('CBTC,100\nPIS,50')
const prefix = ref(24)
const page = ref(1)
const pageSize = ref(50)
const result = ref<ToolboxResult>({ rows: [], summary: {}, errors: [] })
const calculating = ref(false)
const taskKind = ref<'single_ping' | 'continuous_ping' | 'batch_ping' | 'subnet_ping' | 'tcp_ping'>('single_ping')
const probe = reactive({ target: '127.0.0.1', targets: '', port: 443, count: 4, timeout_ms: 1500, interval_ms: 1000, packet_size: 32, concurrency: 100 })
const tasks = ref<NetworkToolTask[]>([])
const selectedTask = ref<NetworkToolTask | null>(null)
const loadingTasks = ref(false)
let timer: number | null = null

const rowKeys = computed(() => {
  const keys: string[] = []
  for (const row of result.value.rows) for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key)
  return keys
})
const resultRows = computed(() => {
  const rows = selectedTask.value?.result?.rows
  return Array.isArray(rows) ? rows as Record<string, unknown>[] : []
})
const taskRunning = computed(() => selectedTask.value && ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(selectedTask.value.status))

onMounted(() => {
  void refreshTasks()
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})

async function calculate(): Promise<void> {
  calculating.value = true
  try {
    if (calculator.value === 'ipv4') result.value = await calculateIpv4(text.value)
    else if (calculator.value === 'ipv6') result.value = await calculateIpv6(text.value)
    else if (calculator.value === 'vlsm') result.value = await calculateVlsm(parent.value, requests.value)
    else if (calculator.value === 'subnets') result.value = await calculateSubnets(parent.value, prefix.value, page.value, pageSize.value)
    else if (calculator.value === 'summarize') result.value = await summarizeRoutes(text.value)
    else result.value = await calculateWildcard(text.value)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络计算失败')
  } finally {
    calculating.value = false
  }
}

async function startProbe(): Promise<void> {
  const values = probe.targets.split(/[\s,;，；]+/).map((item) => item.trim()).filter(Boolean)
  if (!probe.target.trim() && !values.length) {
    ElMessage.warning('请输入目标地址')
    return
  }
  try {
    const response = await startNetworkTask({
      kind: taskKind.value,
      target: probe.target.trim(),
      targets: values,
      port: probe.port,
      count: probe.count,
      timeout_ms: probe.timeout_ms,
      interval_ms: probe.interval_ms,
      packet_size: probe.packet_size,
      concurrency: probe.concurrency,
    })
    selectedTask.value = response.task
    await refreshTasks()
    startPolling()
    ElMessage.success(`网络任务已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务启动失败')
  }
}

async function refreshTasks(): Promise<void> {
  loadingTasks.value = true
  try {
    tasks.value = await listNetworkTasks()
    if (selectedTask.value) {
      const current = tasks.value.find((item) => item.id === selectedTask.value?.id)
      if (current) selectedTask.value = current
    }
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务加载失败')
  } finally {
    loadingTasks.value = false
  }
}

function startPolling(): void {
  if (timer !== null) return
  timer = window.setInterval(async () => {
    await refreshTasks()
    if (!taskRunning.value) stopPolling()
  }, 1000)
}

function stopPolling(): void {
  if (timer !== null) window.clearInterval(timer)
  timer = null
}

async function selectTask(task: NetworkToolTask): Promise<void> {
  selectedTask.value = task
  if (['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(task.status)) startPolling()
}

async function cancelTask(): Promise<void> {
  if (!selectedTask.value) return
  try {
    selectedTask.value = await cancelNetworkTask(selectedTask.value.id)
    await refreshTasks()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '停止网络任务失败')
  }
}

async function exportTask(format: 'csv' | 'xlsx'): Promise<void> {
  if (!selectedTask.value) return
  try {
    const artifact = await exportNetworkTask(selectedTask.value.id, format)
    ElMessage.success(`导出完成，SHA-256：${artifact.sha256}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务导出失败')
  }
}
</script>

<template>
  <el-card shadow="never">
    <template #header><div class="header"><div><h2>网络小工具</h2><p>算法由 Python Service 执行，结果可进入任务中心与导出。</p></div><el-button :loading="loadingTasks" @click="refreshTasks">刷新</el-button></div></template>
    <el-tabs v-model="calculator">
      <el-tab-pane label="IPv4" name="ipv4" />
      <el-tab-pane label="IPv6" name="ipv6" />
      <el-tab-pane label="VLSM" name="vlsm" />
      <el-tab-pane label="子网划分" name="subnets" />
      <el-tab-pane label="路由汇总" name="summarize" />
      <el-tab-pane label="反掩码" name="wildcard" />
    </el-tabs>
    <div class="calculator-form">
      <el-input v-if="!['vlsm', 'subnets'].includes(calculator)" v-model="text" type="textarea" :rows="3" placeholder="每行一个输入" />
      <template v-else>
        <el-input v-model="parent" placeholder="主网络，例如 192.168.0.0/22" />
        <el-input v-if="calculator === 'vlsm'" v-model="requests" type="textarea" :rows="3" placeholder="名称,主机数，每行一项" />
        <div v-else class="inline-form"><el-input-number v-model="prefix" :min="1" :max="32" /><el-input-number v-model="page" :min="1" /><el-input-number v-model="pageSize" :min="1" :max="500" /></div>
      </template>
      <el-button type="primary" :loading="calculating" @click="calculate">计算</el-button>
    </div>
    <el-alert v-if="result.errors.length" :title="result.errors.join('；')" type="error" show-icon :closable="false" />
    <el-table v-if="result.rows.length" :data="result.rows" stripe max-height="360">
      <el-table-column v-for="key in rowKeys" :key="key" :prop="key" :label="key" min-width="140" />
    </el-table>
    <el-descriptions v-if="Object.keys(result.summary).length" :column="3" border class="summary">
      <el-descriptions-item v-for="([key, value]) in Object.entries(result.summary)" :key="key" :label="key">{{ value }}</el-descriptions-item>
    </el-descriptions>
  </el-card>

  <el-card shadow="never">
    <template #header><div class="header"><div><h2>连通性检测</h2><p>单次、持续、批量、网段 Ping 与 TCP Ping 均进入任务链。</p></div><el-button :loading="loadingTasks" @click="refreshTasks">刷新历史</el-button></div></template>
    <el-form label-position="top">
      <div class="inline-form"><el-form-item label="类型"><el-select v-model="taskKind"><el-option label="单个 Ping" value="single_ping" /><el-option label="持续 Ping" value="continuous_ping" /><el-option label="批量 Ping" value="batch_ping" /><el-option label="网段 Ping" value="subnet_ping" /><el-option label="TCP Ping" value="tcp_ping" /></el-select></el-form-item><el-form-item label="目标"><el-input v-model="probe.target" placeholder="主机、IP 或 IPv4 网段" /></el-form-item><el-form-item label="端口"><el-input-number v-model="probe.port" :min="1" :max="65535" /></el-form-item></div>
      <el-form-item v-if="taskKind === 'batch_ping'" label="批量目标"><el-input v-model="probe.targets" type="textarea" :rows="2" placeholder="多个目标用空格、逗号或换行分隔" /></el-form-item>
      <div class="inline-form"><el-form-item label="次数"><el-input-number v-model="probe.count" :min="1" :max="1000" /></el-form-item><el-form-item label="超时 ms"><el-input-number v-model="probe.timeout_ms" :min="1" :max="60000" /></el-form-item><el-form-item label="间隔 ms"><el-input-number v-model="probe.interval_ms" :min="1" :max="60000" /></el-form-item><el-form-item label="并发"><el-input-number v-model="probe.concurrency" :min="1" :max="500" /></el-form-item></div>
      <el-button type="primary" @click="startProbe">开始检测</el-button>
    </el-form>
    <el-divider />
    <el-table v-loading="loadingTasks" :data="tasks" empty-text="暂无网络工具任务" stripe @row-click="selectTask">
      <el-table-column prop="name" label="任务" min-width="140" /><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="progress" label="进度" width="100"><template #default="{ row }">{{ row.total ? `${row.progress}%` : `${row.current} 条` }}</template></el-table-column><el-table-column prop="message" label="消息" min-width="220" />
    </el-table>
    <div v-if="selectedTask" class="task-detail"><span>{{ selectedTask.name }}：{{ selectedTask.status }}</span><el-button v-if="taskRunning" link type="danger" @click="cancelTask">停止</el-button><el-button v-if="selectedTask.result?.rows" link @click="exportTask('csv')">导出 CSV</el-button><el-button v-if="selectedTask.result?.rows" link @click="exportTask('xlsx')">导出 XLSX</el-button></div>
    <el-table v-if="resultRows.length" :data="resultRows" stripe max-height="360"><el-table-column v-for="key in Object.keys(resultRows[0])" :key="key" :prop="key" :label="key" min-width="140" /></el-table>
  </el-card>
</template>

<style scoped>
.header { align-items: center; display: flex; justify-content: space-between; gap: 16px; }
.header h2 { margin: 0 0 4px; }
.header p { color: var(--el-text-color-secondary); margin: 0; }
.calculator-form { display: flex; flex-direction: column; gap: 12px; }
.inline-form { display: flex; gap: 12px; flex-wrap: wrap; }
.summary { margin-top: 16px; }
.task-detail { align-items: center; display: flex; gap: 8px; margin: 12px 0; }
</style>
