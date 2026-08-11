<script setup lang="ts">
import { computed, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'

import ExecutionTargetSelect from '../traffic/ExecutionTargetSelect.vue'
import { isFeatureEnabled } from '../../features'
import { useTrafficStore } from '../../stores/traffic'
import type { TrafficExecutionTargetRequest, TrafficRun } from '../../types/traffic'

const store = useTrafficStore()
const form = reactive({ targetKind: '', target: '', port: 443, interval_ms: 1000, timeout_ms: 3000, count: 4 })
const tcpRuns = computed(() => store.runs.filter((run) => run.test_type === 'TCP_PORT_TEST'))
const latest = computed(() => tcpRuns.value[0] || null)
const running = computed(() => latest.value && ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(latest.value.status))

onMounted(async () => {
  await Promise.all([store.refreshTargets(), store.refreshRuns()])
  const first = store.targets.find((target) => target.available && (target.kind === 'LOCAL' || target.capabilities.tcp_ping_probe))
  if (first) form.targetKind = first.kind === 'LOCAL' ? 'LOCAL' : `AGENT:${first.agent_id}`
})

function executionTarget(): TrafficExecutionTargetRequest {
  if (!form.targetKind || form.targetKind === 'LOCAL') return { kind: 'LOCAL' }
  const agentId = form.targetKind.replace(/^AGENT:/, '')
  const target = store.targets.find((item) => item.agent_id === agentId)
  return { kind: 'AGENT', agent_id: agentId, display_name: target?.display_name || agentId }
}

async function start(): Promise<void> {
  if (!form.target.trim()) {
    ElMessage.warning('请输入 TCP 目标地址')
    return
  }
  try {
    const run = await store.createTcpPortTest({
      execution_target: executionTarget(),
      target: form.target.trim(),
      port: form.port,
      interval_ms: form.interval_ms,
      timeout_ms: form.timeout_ms,
      count: form.count,
    })
    ElMessage.success(`TCP 端口测试已提交：${run.traffic_run_id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : 'TCP 端口测试启动失败')
  }
}

async function select(run: TrafficRun): Promise<void> {
  await store.selectRun(run.traffic_run_id)
}
</script>

<template>
  <el-card v-loading="store.loading" shadow="never">
    <template #header><div class="header"><div><h2>TCP 端口测试</h2><p>复用本地 Job 或 Agent ping_probe，结果关联任务中心</p></div><el-button :loading="store.loading" @click="store.refreshRuns">刷新</el-button></div></template>
    <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" />
    <el-form label-position="top">
      <el-form-item label="执行端"><ExecutionTargetSelect v-model="form.targetKind" :targets="store.targets" test-type="TCP_PORT_TEST" /></el-form-item>
      <div class="form-grid">
        <el-form-item label="目标地址"><el-input v-model="form.target" placeholder="例如 127.0.0.1" /></el-form-item>
        <el-form-item label="TCP 端口"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="间隔 ms"><el-input-number v-model="form.interval_ms" :min="1" :max="60000" /></el-form-item>
        <el-form-item label="超时 ms"><el-input-number v-model="form.timeout_ms" :min="1" :max="60000" /></el-form-item>
        <el-form-item label="次数"><el-input-number v-model="form.count" :min="1" :max="1000000" /></el-form-item>
      </div>
      <el-button type="primary" :loading="store.starting" :disabled="!isFeatureEnabled('capability.network_tools.tcp_port_test')" @click="start">开始测试</el-button>
    </el-form>

    <el-divider />
    <el-empty v-if="!store.loading && !tcpRuns.length" description="暂无 TCP 端口测试" />
    <template v-else-if="latest">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="状态">{{ latest.status }}</el-descriptions-item>
        <el-descriptions-item label="执行端">{{ latest.executor_kind === 'LOCAL' ? '本机' : latest.agent_id }}</el-descriptions-item>
        <el-descriptions-item label="目标">{{ latest.normalized_config.target }}:{{ latest.normalized_config.port }}</el-descriptions-item>
        <el-descriptions-item label="结果">{{ latest.status === 'COMPLETED' ? (latest.summary.last_status || '已完成') : (running ? '执行中' : latest.error_message || '—') }}</el-descriptions-item>
      </el-descriptions>
      <div class="actions">
        <el-button link type="primary" @click="select(latest)">查看实时事件</el-button>
        <el-button v-if="latest.cancellable" link type="danger" @click="store.requestCancel(latest.traffic_run_id)">停止</el-button>
      </div>
    </template>
  </el-card>
</template>

<style scoped>
.header { align-items: center; display: flex; justify-content: space-between; gap: 16px; }
.header h2 { margin: 0 0 4px; }
.header p { color: var(--el-text-color-secondary); margin: 0; }
.form-grid { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.actions { margin-top: 12px; }
@media (max-width: 900px) { .form-grid { grid-template-columns: 1fr; } }
</style>
