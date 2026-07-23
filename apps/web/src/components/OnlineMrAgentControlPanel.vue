<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useConfirm } from './feedback/useConfirm'

import {
  getOnlineMrAgentCapabilities,
  getOnlineMrAgentOperation,
  getOnlineMrAgentReadiness,
  getOnlineMrAgentStatus,
  startOnlineMrAgent,
  stopOnlineMrAgent,
} from '../api/onlineMrAgentControl'
import type {
  OnlineMrAgentControlMr,
  OnlineMrAgentOperation,
  OnlineMrAgentProfile,
  OnlineMrAgentReadiness,
  OnlineMrAgentStartConfig,
} from '../types/onlineMrAgentControl'

const props = defineProps<{ siteId: string; mr: OnlineMrAgentControlMr }>()
const { confirm } = useConfirm()
const enabled = ref(false)
const loading = ref(false)
const starting = ref(false)
const stopping = ref(false)
const error = ref('')
const profiles = ref<OnlineMrAgentProfile[]>([])
const profileId = ref('')
const readiness = ref<OnlineMrAgentReadiness | null>(null)
const operation = ref<OnlineMrAgentOperation | null>(null)
let timer: number | null = null

const config = reactive({
  duration_minutes: 0,
  items: { terminal_monitor: true as const, mesh_link: true, channel_busy: true, ap_radio_statistics: true, switch_history: true, interface_rate: true, wireless_status: true },
  intervals: { mesh_link: 1, channel_busy: 9, ap_radio_statistics: 10, switch_history: 300, interface_rate: 2, wireless_status: 3 },
  radio: {
    radio_mode: 'unified' as '' | 'unified' | 'per_collector',
    unified_radio_id: 1,
    collector_radio_ids: { channel_busy: 1, ap_radio_statistics: 1, wireless_status: 1 } as Record<string, number>,
    channel_busy_radio: 1,
    ap_radio_statistics_radio: 1,
    wireless_status_radio: 1,
  },
  fping: { enabled: true, target: '', packet_size: 64, interval_ms: 10, timeout_ms: 100, loss_warn_percent: 0.7, latency_warn_ms: 100 },
  iperf: { enabled: false, server_ip: '', port: 5201, protocol: 'TCP' as 'TCP' | 'UDP', parallel: 1, interval_seconds: 1, udp_bitrate_mbps: null as number | null, tcp_report_threshold_mbps: null as number | null, tcp_rate_limit_mbps: null as number | null, packet_length: null as number | null, reverse: false },
})

const active = computed(() => ['preparing', 'starting', 'running', 'remote_status_degraded', 'remote_unknown', 'stopping', 'waiting_package', 'importing'].includes(operation.value?.state || ''))
const canStart = computed(() => enabled.value && readiness.value?.ready && profileId.value && !active.value && !starting.value && props.mr.device_id !== null)
const canStop = computed(() => enabled.value && active.value && !stopping.value)
const stateLabel = computed(() => ({
  preparing: '正在准备', starting: '正在启动', running: 'Agent 采集中', stopping: '正在正常停止',
  remote_status_degraded: '远端状态暂时不可用', remote_unknown: '远端状态未知',
  waiting_package: '等待采集包', importing: '下载并导入中', stopped: '已完成', failed: '失败',
} as Record<string, string>)[operation.value?.state || ''] || '未启动')

function payload(): OnlineMrAgentStartConfig {
  if (props.mr.device_id === null) throw new Error('当前 MR 未绑定正式设备')
  config.radio.channel_busy_radio = config.radio.unified_radio_id || 1
  config.radio.ap_radio_statistics_radio = config.radio.unified_radio_id || 1
  config.radio.wireless_status_radio = config.radio.unified_radio_id || 1
  config.radio.collector_radio_ids = {
    channel_busy: config.radio.channel_busy_radio,
    ap_radio_statistics: config.radio.ap_radio_statistics_radio,
    wireless_status: config.radio.wireless_status_radio,
  }
  return {
    site_id: props.siteId, device_id: props.mr.device_id, mr_id: props.mr.mr_id,
    agent_profile_id: profileId.value, executor: 'AGENT', ...JSON.parse(JSON.stringify(config)),
  }
}
function selectForMr(rows: OnlineMrAgentOperation[]): OnlineMrAgentOperation | null {
  return rows.find((item) => String(item.device_id) === String(props.mr.device_id) && activeState(item.state))
    || rows.find((item) => String(item.device_id) === String(props.mr.device_id)) || null
}
function activeState(value: string): boolean { return ['preparing', 'starting', 'running', 'remote_status_degraded', 'remote_unknown', 'stopping', 'waiting_package', 'importing'].includes(value) }
async function loadCapabilities(): Promise<void> {
  const capability = await getOnlineMrAgentCapabilities()
  enabled.value = capability.agent_executor_enabled
  profiles.value = capability.profiles
  if (!profiles.value.some((item) => item.profile_id === profileId.value)) profileId.value = profiles.value.find((item) => item.enabled)?.profile_id || ''
}
async function checkReadiness(): Promise<void> {
  readiness.value = profileId.value ? await getOnlineMrAgentReadiness(profileId.value) : null
}
async function refresh(): Promise<void> {
  if (loading.value || document.hidden) return
  loading.value = true
  try {
    await loadCapabilities()
    if (operation.value?.operation_id) operation.value = await getOnlineMrAgentOperation(operation.value.operation_id)
    else if (enabled.value) operation.value = selectForMr((await getOnlineMrAgentStatus()).operations)
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Agent Online MR 状态刷新失败' }
  finally { loading.value = false; schedule() }
}
async function start(): Promise<void> {
  if (!canStart.value) return
  starting.value = true; error.value = ''
  try {
    if (!await confirm({ type: 'WARNING', title: '启动 Agent 采集', message: `确认由所选 Agent 启动 ${props.mr.train_name} ${props.mr.mr_role} 的 Online MR 采集？`, confirmText: '启动' })) return
    operation.value = await startOnlineMrAgent(payload())
    ElMessage.success('Agent 采集任务已创建')
  } catch (cause) { if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '启动失败' }
  finally { starting.value = false; schedule() }
}
async function stop(): Promise<void> {
  if (!canStop.value || !operation.value) return
  stopping.value = true; error.value = ''
  try {
    if (!await confirm({ type: 'WARNING', title: '正常停止 Agent 采集', message: '仅发送正常停止；Controller 将等待 Agent 打包、下载并导入。确认继续？', confirmText: '正常停止' })) return
    operation.value = await stopOnlineMrAgent(operation.value.operation_id)
    ElMessage.success('已发送正常停止请求')
  } catch (cause) { if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '停止失败' }
  finally { stopping.value = false; schedule() }
}
function schedule(): void { clearTimer(); timer = window.setTimeout(refresh, active.value ? 1_500 : 5_000) }
function clearTimer(): void { if (timer !== null) window.clearTimeout(timer); timer = null }
function visibilityChanged(): void { if (document.hidden) clearTimer(); else void refresh() }

watch(profileId, () => { readiness.value = null })
watch(() => props.mr.mr_id, () => { operation.value = null; config.fping.target = props.mr.management_ip || ''; void refresh() })
onMounted(() => { config.fping.target = props.mr.management_ip || ''; document.addEventListener('visibilitychange', visibilityChanged); void refresh() })
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', visibilityChanged); clearTimer() })
</script>

<template>
  <section class="agent-panel">
    <div class="panel-heading"><div><h3>Agent 远程 Online MR</h3><p>仅使用已登记 Profile 和固定 Agent API；页面关闭只停止轮询。</p></div><el-tag>{{ stateLabel }}</el-tag></div>
    <el-alert v-if="!enabled" title="Agent 远程执行默认关闭；后端能力开关未启用。" type="info" show-icon :closable="false" />
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <template v-if="enabled">
      <div class="profile-row">
        <el-select v-model="profileId" placeholder="选择 Agent Profile" :disabled="active"><el-option v-for="item in profiles" :key="item.profile_id" :value="item.profile_id" :disabled="!item.enabled" :label="`${item.name} · ${item.address_display}`" /></el-select>
        <el-button :disabled="!profileId || active" @click="checkReadiness">检查 readiness</el-button>
        <el-tag v-if="readiness" :type="readiness.ready ? 'success' : 'danger'">{{ readiness.ready ? `就绪 · ${readiness.version}` : readiness.error_summary }}</el-tag>
      </div>
      <el-collapse v-if="!active" class="config-panel"><el-collapse-item title="启动配置（设备凭据由 Controller 受控读取）" name="config">
        <el-form label-position="top"><el-form-item label="采集时长（分钟，0 为手动停止）"><el-input-number v-model="config.duration_minutes" :min="0" :max="1440" /></el-form-item>
          <el-form-item label="采集项"><el-checkbox v-model="config.items.terminal_monitor" disabled>terminal monitor（必选）</el-checkbox><el-checkbox v-model="config.items.mesh_link">mesh-link</el-checkbox><el-checkbox v-model="config.items.channel_busy">channel busy</el-checkbox><el-checkbox v-model="config.items.ap_radio_statistics">radio statistics</el-checkbox><el-checkbox v-model="config.items.switch_history">switch history</el-checkbox><el-checkbox v-model="config.items.interface_rate">interface rate</el-checkbox><el-checkbox v-model="config.items.wireless_status">wireless status</el-checkbox></el-form-item>
          <div class="traffic-row"><el-switch v-model="config.fping.enabled" active-text="启用 fping" /><el-switch v-model="config.iperf.enabled" active-text="启用 iPerf" /></div>
        </el-form>
      </el-collapse-item></el-collapse>
      <div class="actions"><el-button type="primary" :disabled="!canStart" :loading="starting" @click="start">启动 Agent 采集</el-button><el-button type="warning" :disabled="!canStop" :loading="stopping" @click="stop">正常停止</el-button><el-button :loading="loading" @click="refresh">刷新</el-button></div>
      <el-descriptions v-if="operation" :column="3" border class="operation">
        <el-descriptions-item label="Controller Task">{{ operation.controller_task_id }}</el-descriptions-item><el-descriptions-item label="Agent / Profile">{{ operation.agent_id || '待识别' }} / {{ operation.agent_profile_id }}</el-descriptions-item><el-descriptions-item label="Agent Task / Session">{{ operation.agent_task_id || '待创建' }} / {{ operation.remote_session_id || '待生成' }}</el-descriptions-item>
        <el-descriptions-item label="本地 Session">{{ operation.session_id || '待导入' }}</el-descriptions-item><el-descriptions-item label="阶段 / 远端状态">{{ operation.phase }} / {{ operation.remote_status || '无数据' }}</el-descriptions-item><el-descriptions-item label="状态失败次数">{{ operation.consecutive_status_failures }}</el-descriptions-item>
        <el-descriptions-item label="Package / 下载">{{ operation.package_status }} / {{ operation.download_status }}</el-descriptions-item><el-descriptions-item label="导入 / 完整性">{{ operation.import_status }} / {{ operation.data_integrity }}</el-descriptions-item><el-descriptions-item label="错误">{{ operation.error_code ? `${operation.error_code} · ${operation.error_summary}` : '无' }}</el-descriptions-item>
      </el-descriptions>
    </template>
  </section>
</template>

<style scoped>
.agent-panel { margin: 0 0 16px; padding: 16px; border: 1px solid var(--el-border-color); border-radius: 12px; background: var(--el-fill-color-extra-light); }.panel-heading,.profile-row,.actions,.traffic-row { display: flex; align-items: center; gap: 12px; }.panel-heading { justify-content: space-between; }.panel-heading h3 { margin: 0 0 4px; }.panel-heading p { margin: 0; color: var(--el-text-color-secondary); }.agent-panel .el-alert,.profile-row,.config-panel,.actions,.operation { margin-top: 12px; }.profile-row { flex-wrap: wrap; }.profile-row .el-select { width: min(460px,100%); }.traffic-row { flex-wrap: wrap; }@media (max-width: 800px) { .panel-heading { align-items: flex-start; flex-direction: column; } }
</style>
