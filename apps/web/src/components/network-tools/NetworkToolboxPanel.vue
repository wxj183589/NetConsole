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
  getNetworkProbeEnvironment,
  getNetworkExportArtifact,
  getNetworkTask,
  listNetworkTaskResults,
  startNetworkTask,
  summarizeRoutes,
} from '../../api/networkTools'
import { downloadBackendResource } from '../../platform/runtime'
import { useTaskStore } from '../../stores/tasks'
import type { NetworkAdapter, NetworkProbeEnvironment, NetworkToolTask, ToolboxResult } from '../../types/networkTools'
import type { TaskItem } from '../../types/task'
import { buildSubnetStatusGrid } from './subnetStatusGrid'

const taskStore = useTaskStore()

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
const probe = reactive({ target: '127.0.0.1', targets: '', port: 443, count: 4, timeout_ms: 1500, interval_ms: 1000, packet_size: 32, concurrency: 100, source_ip: '', usable_only: true })
const probeEnvironment = ref<NetworkProbeEnvironment>({ adapters: [], scan_engine: '检测中', scan_engine_available: false, supports_source_ip: true, message: '' })
const selectedAdapterIndex = ref<number | null>(null)
const selectedTask = ref<NetworkToolTask | null>(null)
const selectedSubnetResult = ref<Record<string, unknown> | null>(null)
const taskResults = ref<Record<string, unknown>[]>([])
const resultOffset = ref(0)
const resultPageSize = 500
const resultTotal = ref(0)
const ACTIVE_STATUSES = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING']
const PROBE_TYPES = ['network_tools.single_ping', 'network_tools.continuous_ping', 'network_tools.batch_ping', 'network_tools.subnet_ping', 'network_tools.tcp_ping']
const PROBE_POLL_INTERVAL_MS = 500
let probePollTimer: number | null = null
let probePollGeneration = 0
let resultCursor = 0
let nextResultOffset = 0
let mounted = true
const tasks = computed(() => taskStore.tasks.filter((item) => item.owner === 'web_network_tools' && (PROBE_TYPES.includes(item.type) || item.type === 'network_tools.toolbox_export')))
const loadingTasks = computed(() => taskStore.loading)
const selectedTaskSummary = computed(() => selectedTask.value)
const selectedAdapter = computed<NetworkAdapter | null>(() => probeEnvironment.value.adapters.find((item) => item.interface_index === selectedAdapterIndex.value) || null)

const rowKeys = computed(() => {
  const keys: string[] = []
  for (const row of result.value.rows) for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key)
  return keys
})
const resultRows = computed(() => {
  return taskResults.value
})
const taskRunning = computed(() => selectedTaskSummary.value && ACTIVE_STATUSES.includes(selectedTaskSummary.value.status))
const selectedProbeTerminal = computed(() => ['COMPLETED', 'CANCELLED'].includes(selectedTaskSummary.value?.status || '') && PROBE_TYPES.includes(selectedTaskSummary.value?.type || ''))
const selectedProbeHasResults = computed(() => selectedProbeTerminal.value && resultTotal.value > 0)
const selectedExportCompleted = computed(() => selectedTaskSummary.value?.status === 'COMPLETED' && selectedTaskSummary.value.type === 'network_tools.toolbox_export')
const subnetGrid = computed(() => taskKind.value === 'subnet_ping' ? buildSubnetStatusGrid(probe.target, probe.usable_only, taskResults.value) : [])
const scanEngine = computed(() => String(selectedTask.value?.result?.engine || probeEnvironment.value.scan_engine))

onMounted(async () => {
  await Promise.all([taskStore.refresh(), loadProbeEnvironment()])
})

onBeforeUnmount(() => {
  mounted = false
  stopProbeMonitor()
})

async function loadProbeEnvironment(): Promise<void> {
  try {
    probeEnvironment.value = await getNetworkProbeEnvironment()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网卡与扫描引擎状态加载失败')
  }
}

function selectAdapter(): void {
  const address = selectedAdapter.value?.ipv4_addresses[0] || ''
  probe.source_ip = address.split('/', 1)[0] || ''
  if (address) probe.target = address
}

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
      count: taskKind.value === 'subnet_ping' ? 1 : probe.count,
      timeout_ms: probe.timeout_ms,
      interval_ms: probe.interval_ms,
      packet_size: probe.packet_size,
      concurrency: probe.concurrency,
      source_ip: taskKind.value === 'subnet_ping' ? probe.source_ip : '',
      usable_only: probe.usable_only,
    })
    selectedTask.value = response.task
    taskResults.value = []
    resultTotal.value = 0
    resultOffset.value = 0
    resultCursor = 0
    nextResultOffset = 0
    monitorProbeTask(response.task.id)
    await refreshTasks()
    ElMessage.success(`网络任务已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务启动失败')
  }
}

async function refreshTasks(): Promise<void> {
  try {
    await taskStore.refresh()
    if (selectedTask.value) {
      const previousStatus = selectedTask.value.status
      const current = await getNetworkTask(selectedTask.value.id)
      selectedTask.value = current
      if (ACTIVE_STATUSES.includes(current.status) && PROBE_TYPES.includes(current.type)) {
        monitorProbeTask(current.id)
      } else if (['COMPLETED', 'CANCELLED'].includes(current?.status || '') && current?.status !== previousStatus && !current.type.endsWith('_export')) {
        resultOffset.value = 0
        await loadTaskResults()
      }
    }
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务加载失败')
  }
}

async function selectTask(task: TaskItem): Promise<void> {
  stopProbeMonitor()
  selectedTask.value = await getNetworkTask(task.id)
  resultOffset.value = 0
  resultCursor = 0
  nextResultOffset = 0
  if (ACTIVE_STATUSES.includes(selectedTask.value.status) && PROBE_TYPES.includes(selectedTask.value.type)) {
    taskResults.value = []
    resultTotal.value = 0
    monitorProbeTask(selectedTask.value.id)
  } else if (['COMPLETED', 'CANCELLED'].includes(selectedTask.value.status) && PROBE_TYPES.includes(selectedTask.value.type)) await loadTaskResults()
  else {
    taskResults.value = []
    resultTotal.value = 0
  }
}

async function cancelTask(): Promise<void> {
  if (!selectedTask.value) return
  try {
    selectedTask.value = await cancelNetworkTask(selectedTask.value.id)
    monitorProbeTask(selectedTask.value.id)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '停止网络任务失败')
  }
}

async function exportTask(format: 'csv' | 'xlsx'): Promise<void> {
  if (!selectedTask.value || !selectedProbeHasResults.value) return
  try {
    const response = await exportNetworkTask(selectedTask.value.id, format)
    stopProbeMonitor()
    selectedTask.value = response.task
    await taskStore.refresh()
    ElMessage.success(`导出任务已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务导出失败')
  }
}

async function loadTaskResults(): Promise<void> {
  if (!selectedTask.value || !selectedProbeTerminal.value) return
  try {
    const page = await listNetworkTaskResults(selectedTask.value.id, resultOffset.value, resultPageSize)
    taskResults.value = page.items
    resultTotal.value = page.total
    nextResultOffset = page.next_offset
    resultCursor = page.next_cursor
    selectedSubnetResult.value = null
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络任务结果加载失败')
  }
}

function monitorProbeTask(taskId: string): void {
  stopProbeMonitor()
  const generation = probePollGeneration
  scheduleProbePoll(taskId, generation, 0)
}

function stopProbeMonitor(): void {
  probePollGeneration += 1
  if (probePollTimer !== null) window.clearTimeout(probePollTimer)
  probePollTimer = null
}

function scheduleProbePoll(taskId: string, generation: number, delay: number): void {
  if (!mounted || generation !== probePollGeneration) return
  probePollTimer = window.setTimeout(() => void pollProbeTask(taskId, generation), delay)
}

async function pollProbeTask(taskId: string, generation: number): Promise<void> {
  probePollTimer = null
  try {
    const current = await getNetworkTask(taskId)
    if (!mounted || generation !== probePollGeneration || selectedTask.value?.id !== taskId) return
    selectedTask.value = current
    if (PROBE_TYPES.includes(current.type)) {
      const page = await listNetworkTaskResults(taskId, nextResultOffset, resultPageSize, resultCursor)
      if (!mounted || generation !== probePollGeneration || selectedTask.value?.id !== taskId) return
      if (page.items.length) {
        taskResults.value.push(...page.items)
        if (taskResults.value.length > resultPageSize) {
          taskResults.value.splice(0, taskResults.value.length - resultPageSize)
        }
      }
      resultTotal.value = page.total
      nextResultOffset = page.next_offset
      resultCursor = page.next_cursor
      if (page.has_more) {
        scheduleProbePoll(taskId, generation, 0)
        return
      }
      if (['COMPLETED', 'CANCELLED'].includes(current.status) && page.total > resultPageSize) {
        resultOffset.value = 0
        await loadTaskResults()
        return
      }
    }
    if (ACTIVE_STATUSES.includes(current.status)) scheduleProbePoll(taskId, generation, PROBE_POLL_INTERVAL_MS)
  } catch (cause) {
    if (mounted && generation === probePollGeneration) {
      scheduleProbePoll(taskId, generation, PROBE_POLL_INTERVAL_MS)
    }
  }
}

async function changeResultPage(page: number): Promise<void> {
  resultOffset.value = Math.max(0, page - 1) * resultPageSize
  await loadTaskResults()
}

async function downloadExport(): Promise<void> {
  if (!selectedTask.value || !selectedExportCompleted.value) return
  try {
    const artifact = await getNetworkExportArtifact(selectedTask.value.id)
    const result = await downloadBackendResource({ apiPath: artifact.download_url, suggestedName: artifact.filename })
    if (result.status === 'failed') throw new Error(result.error || '网络工具导出下载失败')
    if (result.status !== 'cancelled') ElMessage.success(`导出完成，SHA-256：${artifact.sha256}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '网络工具导出下载失败')
  }
}

function selectSubnetResult(row: Record<string, unknown>): void {
  selectedSubnetResult.value = row
}

function clearTaskResults(): void {
  taskResults.value = []
  resultTotal.value = 0
  selectedSubnetResult.value = null
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
    <el-alert v-if="taskStore.error" :title="taskStore.error" type="error" show-icon :closable="false" />
    <el-form label-position="top">
      <div class="inline-form"><el-form-item label="类型"><el-select v-model="taskKind"><el-option label="单个 Ping" value="single_ping" /><el-option label="持续 Ping" value="continuous_ping" /><el-option label="批量 Ping" value="batch_ping" /><el-option label="网段 Ping" value="subnet_ping" /><el-option label="TCP Ping" value="tcp_ping" /></el-select></el-form-item><el-form-item label="目标"><el-input v-model="probe.target" placeholder="主机、IP 或 IPv4 网段" /></el-form-item><el-form-item v-if="taskKind === 'tcp_ping'" label="端口"><el-input-number v-model="probe.port" :min="1" :max="65535" /></el-form-item></div>
      <div v-if="taskKind === 'subnet_ping'" class="inline-form subnet-controls"><el-form-item label="网卡"><el-select v-model="selectedAdapterIndex" data-testid="network-adapter-select" clearable placeholder="自动选择" @change="selectAdapter"><el-option v-for="adapter in probeEnvironment.adapters" :key="adapter.interface_index" :label="adapter.display_name" :value="adapter.interface_index" /></el-select></el-form-item><el-form-item label="源地址"><el-input v-model="probe.source_ip" readonly data-testid="source-ip" /></el-form-item><el-form-item label="扫描范围"><el-checkbox v-model="probe.usable_only">只扫描可用主机</el-checkbox></el-form-item><el-button @click="loadProbeEnvironment">刷新网卡</el-button></div>
      <el-alert v-if="taskKind === 'subnet_ping'" :title="`当前引擎：${scanEngine}`" :description="probeEnvironment.message" type="info" :closable="false" />
      <el-form-item v-if="taskKind === 'batch_ping'" label="批量目标"><el-input v-model="probe.targets" type="textarea" :rows="2" placeholder="多个目标用空格、逗号或换行分隔" /></el-form-item>
      <div class="inline-form"><el-form-item label="次数"><el-input-number v-model="probe.count" :min="1" :max="1000" /></el-form-item><el-form-item label="超时 ms"><el-input-number v-model="probe.timeout_ms" :min="1" :max="60000" /></el-form-item><el-form-item label="间隔 ms"><el-input-number v-model="probe.interval_ms" :min="1" :max="60000" /></el-form-item><el-form-item label="并发"><el-input-number v-model="probe.concurrency" :min="1" :max="500" /></el-form-item></div>
      <el-button type="primary" data-testid="start-probe" @click="startProbe">开始检测</el-button>
    </el-form>
    <el-divider />
    <el-table v-loading="loadingTasks" :data="tasks" empty-text="暂无网络工具任务" stripe @row-click="selectTask">
      <el-table-column prop="name" label="任务" min-width="140" /><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="progress" label="进度" width="100"><template #default="{ row }">{{ `${row.progress}%` }}</template></el-table-column><el-table-column prop="message" label="消息" min-width="220" />
    </el-table>
    <div v-if="selectedTaskSummary" class="task-detail"><span>{{ selectedTaskSummary.name }}：{{ selectedTaskSummary.status }}</span><el-button v-if="taskRunning" link type="danger" data-testid="stop-task" @click="cancelTask">停止</el-button><el-button v-if="selectedProbeHasResults" link data-testid="export-csv" @click="exportTask('csv')">导出 CSV</el-button><el-button v-if="selectedProbeHasResults" link data-testid="export-xlsx" @click="exportTask('xlsx')">导出 XLSX</el-button><el-button v-if="resultRows.length" link @click="clearTaskResults">清空显示</el-button><el-button v-if="selectedExportCompleted" link type="primary" @click="downloadExport">下载 Artifact</el-button></div>
    <div v-if="subnetGrid.length" class="subnet-grid" data-testid="subnet-status-grid"><button v-for="host in subnetGrid" :key="host.ip" type="button" class="subnet-host" :class="`is-${host.status}`" :disabled="!host.in_range" :title="host.ip" @click="selectSubnetResult(host.detail)">{{ host.host_number }}</button></div>
    <el-descriptions v-if="selectedSubnetResult" :column="3" border class="subnet-detail" data-testid="subnet-detail"><el-descriptions-item v-for="([key, value]) in Object.entries(selectedSubnetResult)" :key="key" :label="key">{{ value }}</el-descriptions-item></el-descriptions>
    <el-table v-if="resultRows.length" :data="resultRows" stripe max-height="360" @row-click="selectSubnetResult"><el-table-column v-for="key in Object.keys(resultRows[0])" :key="key" :prop="key" :label="key" min-width="140" /></el-table>
    <el-pagination v-if="resultTotal > resultPageSize" :total="resultTotal" :page-size="resultPageSize" layout="prev, pager, next, total" @current-change="changeResultPage" />
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
.subnet-controls .el-select, .subnet-controls .el-input { min-width: 280px; }
.subnet-grid { display: grid; gap: 4px; grid-template-columns: repeat(auto-fill, minmax(38px, 1fr)); margin: 14px 0; }
.subnet-host { border: 1px solid var(--el-border-color); border-radius: 4px; min-height: 34px; }
.subnet-host.is-online { background: var(--el-color-success-light-7); border-color: var(--el-color-success); }
.subnet-host.is-offline, .subnet-host.is-error { background: var(--el-color-danger-light-7); border-color: var(--el-color-danger); }
.subnet-host.is-timeout { background: var(--el-color-warning-light-7); border-color: var(--el-color-warning); }
.subnet-host:disabled { opacity: 0.35; }
.subnet-detail { margin-bottom: 12px; }
</style>
