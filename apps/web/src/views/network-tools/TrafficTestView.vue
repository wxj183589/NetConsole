<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import NcStatusTag from '../../components/NcStatusTag.vue'
import TcpPortTestPanel from '../../components/network-tools/TcpPortTestPanel.vue'
import ExecutionTargetSelect from '../../components/traffic/ExecutionTargetSelect.vue'
import TrafficBandwidthChart from '../../components/traffic/TrafficBandwidthChart.vue'
import TrafficLogViewer from '../../components/traffic/TrafficLogViewer.vue'
import TrafficRealtimeChart from '../../components/traffic/TrafficRealtimeChart.vue'
import TrafficRunHistory from '../../components/traffic/TrafficRunHistory.vue'
import { useTrafficStore } from '../../stores/traffic'
import type { TrafficExecutionTargetRequest, TrafficRun } from '../../types/traffic'

const store = useTrafficStore()
const router = useRouter()
const activeTab = ref('fping')
const serverForm = reactive({ target: 'LOCAL', bind_ip: '', port: 5201, interval_seconds: 1, one_off: false })
const clientForm = reactive({
  target: 'LOCAL',
  server_ip: '',
  port: 5201,
  protocol: 'TCP' as 'TCP' | 'UDP',
  duration_seconds: 10,
  interval_seconds: 1,
  parallel: 1,
  direction: 'upload' as 'upload' | 'download' | 'bidirectional',
  target_bandwidth: '',
  tcp_block_size: '',
  packet_length: undefined as number | undefined,
})
const fpingForm = reactive({
  target: 'LOCAL',
  targets: '192.168.1.1',
  interval_ms: 100,
  timeout_ms: 100,
  packet_size: 64,
  count: 20,
  continuous: false,
  source_address: '',
})
const clearedEventSequence = ref(0)
const clearedSampleSequence = ref(0)

const summaryItems = computed(() => Object.entries(store.summary || {}).slice(0, 8))
const latestSamples = computed(() => store.samples.filter((item) => item.sequence > clearedSampleSequence.value).slice(-500))
const latestEvents = computed(() => store.events.filter((item) => item.sequence > clearedEventSequence.value).slice(-400))

onMounted(async () => {
  await store.refreshTargets()
  chooseDefaultTargets()
  await store.refreshRuns()
})

onBeforeUnmount(() => store.disconnectSocket())

async function startServer(): Promise<void> {
  try {
    const run = await store.createIperfServer({
      execution_target: targetRequest(serverForm.target),
      bind_ip: serverForm.bind_ip,
      port: serverForm.port,
      interval_seconds: serverForm.interval_seconds,
      one_off: serverForm.one_off,
    })
    ElMessage.success(`iPerf 服务端任务已提交：${run.traffic_run_id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : 'iPerf 服务端启动失败')
  }
}

async function startClient(): Promise<void> {
  try {
    const run = await store.createIperfClient({
      execution_target: targetRequest(clientForm.target),
      server_ip: clientForm.server_ip,
      port: clientForm.port,
      protocol: clientForm.protocol,
      duration_seconds: clientForm.duration_seconds,
      interval_seconds: clientForm.interval_seconds,
      parallel: clientForm.parallel,
      direction: clientForm.direction,
      target_bandwidth: clientForm.target_bandwidth || null,
      tcp_block_size: clientForm.tcp_block_size || null,
      packet_length: clientForm.packet_length || null,
    })
    ElMessage.success(`iPerf 客户端任务已提交：${run.traffic_run_id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : 'iPerf 客户端启动失败')
  }
}

async function startFping(): Promise<void> {
  const targets = fpingForm.targets.split(/[\s,;，；]+/).map((item) => item.trim()).filter(Boolean)
  if (!targets.length) {
    ElMessage.warning('请至少填写一个 Ping 目标')
    return
  }
  try {
    const run = await store.createFping({
      execution_target: targetRequest(fpingForm.target),
      targets,
      interval_ms: fpingForm.interval_ms,
      timeout_ms: fpingForm.timeout_ms,
      packet_size: fpingForm.packet_size,
      count: fpingForm.continuous ? 0 : fpingForm.count,
      continuous: fpingForm.continuous,
      source_address: fpingForm.source_address,
    })
    ElMessage.success(`高频 Ping 任务已提交：${run.traffic_run_id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '高频 Ping 启动失败')
  }
}

async function selectRun(run: TrafficRun): Promise<void> {
  try {
    await store.selectRun(run.traffic_run_id)
    clearedEventSequence.value = 0
    clearedSampleSequence.value = 0
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '流量任务详情加载失败')
  }
}

async function cancelRun(run: TrafficRun): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认停止流量任务 ${run.traffic_run_id}？`, '停止流量任务', { type: 'warning' })
    await store.requestCancel(run.traffic_run_id)
    ElMessage.success('已提交停止请求')
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '停止流量任务失败')
  }
}

async function retryRun(run: TrafficRun): Promise<void> {
  try {
    const retried = await store.requestRetry(run.traffic_run_id)
    ElMessage.success(`已按原配置重试：${retried.traffic_run_id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '重试流量任务失败')
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([store.refreshTargets(), store.refreshRuns()])
  chooseDefaultTargets()
}

function targetRequest(value: string): TrafficExecutionTargetRequest {
  if (!value || value === 'LOCAL') return { kind: 'LOCAL' }
  const agentId = value.replace(/^AGENT:/, '')
  const target = store.targets.find((item) => item.agent_id === agentId)
  return { kind: 'AGENT', agent_id: agentId, display_name: target?.display_name || agentId }
}

function chooseDefaultTargets(): void {
  const first = store.targets.find((target) => target.available)
  const value = first ? (first.kind === 'LOCAL' ? 'LOCAL' : `AGENT:${first.agent_id}`) : 'LOCAL'
  if (!serverForm.target) serverForm.target = value
  if (!clientForm.target) clientForm.target = value
  if (!fpingForm.target) fpingForm.target = value
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

function formatTime(value: string): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function openTaskCenter(): void {
  if (store.selected) void router.push({ name: 'tasks', query: { task_id: store.selected.controller_task_id, module: 'network' } })
}

function clearCurrentView(): void {
  clearedEventSequence.value = store.events.at(-1)?.sequence || 0
  clearedSampleSequence.value = store.samples.at(-1)?.sequence || 0
}
</script>

<template>
  <section class="traffic-page">
    <div class="metric-grid">
      <div class="metric-card"><span>流量任务</span><strong>{{ store.runs.length }}</strong></div>
      <div class="metric-card active"><span>运行中</span><strong>{{ store.runningCount }}</strong></div>
      <div class="metric-card success"><span>已完成</span><strong>{{ store.completedCount }}</strong></div>
      <div class="metric-card danger"><span>失败</span><strong>{{ store.failedCount }}</strong></div>
    </div>

    <div class="traffic-layout">
      <el-card class="control-card" shadow="never">
        <template #header>
          <div class="card-header">
            <div><h2>流量测试</h2><p>本地或 Agent 执行，统一关联任务中心</p></div>
            <el-button :icon="Refresh" :loading="store.loading" @click="refreshAll">刷新</el-button>
          </div>
        </template>

        <el-tabs v-model="activeTab">
          <el-tab-pane label="TCP 端口" name="tcp"><TcpPortTestPanel /></el-tab-pane>
          <el-tab-pane label="高频 Ping" name="fping">
            <el-form label-position="top">
              <el-form-item label="执行端">
                <ExecutionTargetSelect v-model="fpingForm.target" :targets="store.targets" test-type="HIGH_FREQUENCY_PING" />
              </el-form-item>
              <el-form-item label="目标地址">
                <el-input v-model="fpingForm.targets" type="textarea" :rows="3" placeholder="多个目标用换行、空格或逗号分隔" />
              </el-form-item>
              <div class="form-grid">
                <el-form-item label="间隔 ms"><el-input-number v-model="fpingForm.interval_ms" :min="1" :max="60000" /></el-form-item>
                <el-form-item label="超时 ms"><el-input-number v-model="fpingForm.timeout_ms" :min="1" :max="60000" /></el-form-item>
                <el-form-item label="包大小"><el-input-number v-model="fpingForm.packet_size" :min="1" :max="65507" /></el-form-item>
                <el-form-item label="次数"><el-input-number v-model="fpingForm.count" :min="1" :max="1000000" :disabled="fpingForm.continuous" /></el-form-item>
              </div>
              <el-form-item label="源地址（Agent 可用）"><el-input v-model="fpingForm.source_address" clearable /></el-form-item>
              <el-checkbox v-model="fpingForm.continuous">持续运行，直到手动停止</el-checkbox>
              <div class="form-actions"><el-button type="primary" :loading="store.starting" @click="startFping">开始高频 Ping</el-button></div>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="iPerf 客户端" name="client">
            <el-form label-position="top">
              <el-form-item label="执行端">
                <ExecutionTargetSelect v-model="clientForm.target" :targets="store.targets" test-type="IPERF_CLIENT" />
              </el-form-item>
              <el-form-item label="服务端地址"><el-input v-model="clientForm.server_ip" placeholder="例如 192.168.10.10" /></el-form-item>
              <div class="form-grid">
                <el-form-item label="端口"><el-input-number v-model="clientForm.port" :min="1" :max="65535" /></el-form-item>
                <el-form-item label="协议"><el-select v-model="clientForm.protocol"><el-option label="TCP" value="TCP" /><el-option label="UDP" value="UDP" /></el-select></el-form-item>
                <el-form-item label="时长 s"><el-input-number v-model="clientForm.duration_seconds" :min="1" :max="86400" /></el-form-item>
                <el-form-item label="间隔 s"><el-input-number v-model="clientForm.interval_seconds" :min="1" :max="60" /></el-form-item>
                <el-form-item label="并行流"><el-input-number v-model="clientForm.parallel" :min="1" :max="128" /></el-form-item>
                <el-form-item label="方向">
                  <el-select v-model="clientForm.direction">
                    <el-option label="上传" value="upload" />
                    <el-option label="下载" value="download" />
                    <el-option label="双向" value="bidirectional" />
                  </el-select>
                </el-form-item>
              </div>
              <div class="form-grid">
                <el-form-item label="目标带宽"><el-input v-model="clientForm.target_bandwidth" placeholder="例如 20M" clearable /></el-form-item>
                <el-form-item label="TCP Block"><el-input v-model="clientForm.tcp_block_size" placeholder="例如 16K" clearable /></el-form-item>
                <el-form-item label="UDP 包长"><el-input-number v-model="clientForm.packet_length" :min="1" :max="65507" /></el-form-item>
              </div>
              <div class="form-actions"><el-button type="primary" :loading="store.starting" @click="startClient">开始 iPerf Client</el-button></div>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="iPerf 服务端" name="server">
            <el-form label-position="top">
              <el-form-item label="执行端">
                <ExecutionTargetSelect v-model="serverForm.target" :targets="store.targets" test-type="IPERF_SERVER" />
              </el-form-item>
              <div class="form-grid">
                <el-form-item label="绑定地址"><el-input v-model="serverForm.bind_ip" placeholder="空表示全部地址" clearable /></el-form-item>
                <el-form-item label="端口"><el-input-number v-model="serverForm.port" :min="1" :max="65535" /></el-form-item>
                <el-form-item label="报告间隔 s"><el-input-number v-model="serverForm.interval_seconds" :min="1" :max="60" /></el-form-item>
              </div>
              <el-checkbox v-model="serverForm.one_off">单次连接后退出</el-checkbox>
              <div class="form-actions"><el-button type="primary" :loading="store.starting" @click="startServer">启动 iPerf Server</el-button></div>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <el-card class="detail-card" shadow="never">
        <template #header>
          <div class="card-header">
            <div>
              <h2>实时状态</h2>
              <p><span :class="['status-dot', store.socketConnected ? 'online' : 'offline']"></span>{{ store.socketConnected ? '专用流量通道已连接' : '未连接实时通道' }}</p>
            </div>
            <NcStatusTag v-if="store.selected" :status="store.selected.status" />
            <div v-if="store.selected" class="detail-actions">
              <el-button link type="primary" @click="openTaskCenter">任务中心</el-button>
              <el-button link @click="clearCurrentView">清空日志视图</el-button>
              <el-button v-if="store.selected.cancellable" link type="danger" @click="cancelRun(store.selected)">停止</el-button>
            </div>
          </div>
        </template>
        <template v-if="store.selected">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Run ID">{{ store.selected.traffic_run_id }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{ store.selected.test_type }}</el-descriptions-item>
            <el-descriptions-item label="执行端">{{ store.selected.executor_kind === 'LOCAL' ? '本机' : store.selected.agent_id }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ formatTime(store.selected.updated_at) }}</el-descriptions-item>
            <el-descriptions-item label="错误" :span="2">{{ store.selected.error_message || '—' }}</el-descriptions-item>
          </el-descriptions>
          <div class="summary-grid">
            <div v-for="[key, value] in summaryItems" :key="key" class="summary-item">
              <span>{{ key }}</span><strong>{{ formatValue(value) }}</strong>
            </div>
          </div>
          <TrafficRealtimeChart v-if="['HIGH_FREQUENCY_PING', 'TCP_PORT_TEST'].includes(store.selected.test_type)" :samples="latestSamples" />
          <TrafficBandwidthChart v-else :events="latestEvents" />
          <TrafficLogViewer :events="latestEvents" />
        </template>
        <el-empty v-else description="选择或启动一个流量任务查看实时状态" />
      </el-card>
    </div>

    <el-card class="history-card" shadow="never">
      <template #header><div class="card-header"><h2>历史任务</h2><span>{{ store.runs.length }} 条</span></div></template>
      <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" />
      <TrafficRunHistory :runs="store.runs" :loading="store.loading" @select="selectRun" @cancel="cancelRun" @retry="retryRun" @task="(run) => router.push({ name: 'tasks', query: { task_id: run.controller_task_id, module: 'network' } })" />
    </el-card>
  </section>
</template>

<style scoped>
.traffic-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.metric-grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-card {
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  box-shadow: 0 10px 30px rgb(15 23 42 / 4%);
  padding: 18px;
}

.metric-card span,
.card-header p {
  color: var(--el-text-color-secondary);
  margin: 0;
}

.metric-card strong {
  display: block;
  font-size: 30px;
  margin-top: 8px;
}

.metric-card.active strong { color: var(--el-color-primary); }
.metric-card.success strong { color: var(--el-color-success); }
.metric-card.danger strong { color: var(--el-color-danger); }

.traffic-layout {
  display: grid;
  gap: 18px;
  grid-template-columns: minmax(380px, 0.85fr) minmax(520px, 1.15fr);
}

.card-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.card-header h2 {
  font-size: 18px;
  margin: 0 0 4px;
}

.form-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.form-actions {
  margin-top: 18px;
}

.summary-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 16px 0;
}

.summary-item {
  background: var(--el-fill-color-light);
  border-radius: 12px;
  padding: 12px;
}

.summary-item span {
  color: var(--el-text-color-secondary);
  display: block;
  font-size: 12px;
}

.summary-item strong {
  display: block;
  margin-top: 4px;
}

.status-dot {
  border-radius: 50%;
  display: inline-block;
  height: 8px;
  margin-right: 6px;
  width: 8px;
}

.status-dot.online { background: var(--el-color-success); }
.status-dot.offline { background: var(--el-color-warning); }

@media (max-width: 1180px) {
  .metric-grid,
  .traffic-layout {
    grid-template-columns: 1fr;
  }

  .summary-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
