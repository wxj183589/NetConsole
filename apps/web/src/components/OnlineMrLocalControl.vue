<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { forceStopOnlineMrControl, getOnlineMrControlOperation, getOnlineMrControlStatus, recoverOnlineMrControl, startOnlineMrControl, stopOnlineMrControl } from '../api/onlineMrControl'
import type { OnlineMrControlMr, OnlineMrControlOperation, OnlineMrStartConfig } from '../types/onlineMrControl'

const props = defineProps<{ siteId: string; mr: OnlineMrControlMr }>()
const enabled = ref(false)
const loading = ref(false)
const starting = ref(false)
const stopping = ref(false)
const forceStopping = ref(false)
const error = ref('')
const operation = ref<OnlineMrControlOperation | null>(null)
let timer: number | null = null

const config = reactive({
  duration_minutes: 0,
  items: { terminal_monitor: true as const, mesh_link: true, channel_busy: true, ap_radio_statistics: true, switch_history: true, interface_rate: true, wireless_status: true },
  intervals: { mesh_link: 1, channel_busy: 9, ap_radio_statistics: 10, switch_history: 300, interface_rate: 2, wireless_status: 3 },
  radio: { channel_busy_radio: 1, ap_radio_statistics_radio: 1, wireless_status_radio: 1 },
  fping: { enabled: false, target: '', packet_size: 64, interval_ms: 1000, timeout_ms: 4000, loss_warn_percent: 10, latency_warn_ms: 4000 },
  iperf: { enabled: false, server_ip: '', port: 5201, protocol: 'TCP' as 'TCP' | 'UDP', parallel: 1, interval_seconds: 1, udp_bitrate_mbps: null as number | null, tcp_report_threshold_mbps: null as number | null, reverse: false },
})

const active = computed(() => ['preparing', 'starting', 'running', 'stopping'].includes(operation.value?.state || ''))
const canStart = computed(() => enabled.value && !active.value && !starting.value && !stopping.value && !forceStopping.value && props.mr.device_id !== null)
const canStop = computed(() => enabled.value && active.value && operation.value?.state !== 'stopping' && !stopping.value && !forceStopping.value)
const statusLabel = computed(() => ({
  preparing: '正在准备', starting: '正在启动', running: '采集中', stopping: '正在停止并落盘', stopped: '已停止',
  completed_with_warnings: '已完成，有告警', failed: '失败', aborted: '已中断',
} as Record<string, string>)[operation.value?.state || ''] || '未启动')
const statusType = computed(() => ({ preparing: 'primary', starting: 'primary', running: 'success', stopping: 'warning', stopped: 'info', completed_with_warnings: 'warning', failed: 'danger', aborted: 'danger' } as Record<string, string>)[operation.value?.state || ''] || 'info')
const acceptanceCommand = computed(() => operation.value?.session_id ? `python -m scripts.maintenance.check_online_mr_session_state --site "${props.siteId}" --session-id "${operation.value.session_id}"` : '')

function payload(): OnlineMrStartConfig {
  if (props.mr.device_id === null) throw new Error('当前 MR 未绑定正式设备')
  return { site_id: props.siteId, device_id: props.mr.device_id, mr_id: props.mr.mr_id, executor: 'LOCAL', ...JSON.parse(JSON.stringify(config)) }
}
function selectForMr(rows: OnlineMrControlOperation[]): OnlineMrControlOperation | null {
  return rows.find((item) => String(item.device_id) === String(props.mr.device_id) && ['preparing', 'starting', 'running', 'stopping'].includes(item.state))
    || rows.find((item) => String(item.device_id) === String(props.mr.device_id)) || null
}
async function refresh(): Promise<void> {
  if (loading.value || document.hidden) return
  loading.value = true
  try {
    if (operation.value?.operation_id) operation.value = await getOnlineMrControlOperation(operation.value.operation_id)
    else {
      const status = await getOnlineMrControlStatus()
      enabled.value = status.enabled
      operation.value = selectForMr(status.operations)
    }
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Online MR 控制状态刷新失败'
  } finally { loading.value = false; schedule() }
}
async function start(): Promise<void> {
  if (!canStart.value) return
  starting.value = true
  error.value = ''
  try {
    await ElMessageBox.confirm(`确认从本机启动 ${props.mr.train_name} ${props.mr.mr_role} 的 Online MR 采集？`, '启动本地采集', { confirmButtonText: '启动', cancelButtonText: '取消', type: 'warning' })
    operation.value = await startOnlineMrControl(payload())
    ElMessage.success('已创建本地采集任务，正在等待会话启动')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '启动失败'
  } finally { starting.value = false; schedule() }
}
async function stop(): Promise<void> {
  if (!canStop.value || !operation.value) return
  stopping.value = true
  error.value = ''
  try {
    await ElMessageBox.confirm('正常停止将等待 Traffic flush、采集器关闭和原子打包。确认继续？', '正常停止', { confirmButtonText: '停止并落盘', cancelButtonText: '取消', type: 'warning' })
    operation.value = await stopOnlineMrControl(operation.value.operation_id)
    ElMessage.success('本地采集已完成正常停止')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '停止失败'
  } finally { stopping.value = false; schedule() }
}
async function forceStop(): Promise<void> {
  if (!canStop.value || !operation.value) return
  forceStopping.value = true
  error.value = ''
  try {
    await ElMessageBox.confirm('强制停止可能无法完成全部 writer flush；系统会保留原始会话并标记为 partial。仅在正常停止无响应时继续。', '强制停止本地采集', { confirmButtonText: '确认强制停止', cancelButtonText: '取消', type: 'error' })
    operation.value = await forceStopOnlineMrControl(operation.value.operation_id)
    ElMessage.warning('采集已强制停止；请检查数据完整性与原始会话')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '强制停止失败'
  } finally { forceStopping.value = false; schedule() }
}
async function recover(): Promise<void> {
  if (!enabled.value) return
  try {
    const rows = await recoverOnlineMrControl()
    operation.value = selectForMr(rows) || operation.value
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Online MR 重启恢复失败'
  }
}
async function copyAcceptance(): Promise<void> {
  if (!acceptanceCommand.value) return
  await navigator.clipboard.writeText(acceptanceCommand.value)
  ElMessage.success('验收命令已复制')
}
function schedule(): void { clearTimer(); timer = window.setTimeout(refresh, active.value ? 1_500 : 5_000) }
function clearTimer(): void { if (timer !== null) window.clearTimeout(timer); timer = null }
function visibilityChanged(): void { if (document.hidden) clearTimer(); else void refresh() }

watch(() => props.mr.mr_id, () => { operation.value = null; config.fping.target = props.mr.management_ip || ''; void refresh() })
onMounted(async () => {
  config.fping.target = props.mr.management_ip || ''
  document.addEventListener('visibilitychange', visibilityChanged)
  await refresh()
  await recover()
})
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', visibilityChanged); clearTimer() })
</script>

<template>
  <section class="control-panel">
    <div class="control-heading">
      <div><h3>本地 Online MR 采集</h3><p>仅控制主程序 LOCAL 执行端；页面关闭只停止轮询，不停止采集。</p></div>
      <el-tag :type="statusType as any">{{ statusLabel }}</el-tag>
    </div>
    <el-alert v-if="!enabled" title="Web 本地控制默认关闭。仅在主程序 WebHost 明确启用安全开关后可操作。" type="info" show-icon :closable="false" />
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <template v-if="enabled">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="列车 / MR">{{ mr.train_name }} · {{ mr.mr_role }} · {{ mr.mr_name }}</el-descriptions-item>
        <el-descriptions-item label="执行端">LOCAL / 本地主程序</el-descriptions-item>
        <el-descriptions-item label="Task / Session">{{ operation?.task_id || '未创建' }} / {{ operation?.session_id || '待生成' }}</el-descriptions-item>
      </el-descriptions>
      <el-collapse v-if="!active" class="control-config">
        <el-collapse-item title="启动配置（凭据由设备库受控读取）" name="config">
          <el-form label-position="top">
            <div class="form-grid">
              <el-form-item label="采集时长（分钟，0 为手动停止）"><el-input-number v-model="config.duration_minutes" :min="0" :max="1440" /></el-form-item>
              <el-form-item label="Mesh Radio"><div class="inline-fields"><el-input-number v-model="config.radio.channel_busy_radio" :min="1" :max="3" /><el-input-number v-model="config.radio.ap_radio_statistics_radio" :min="1" :max="3" /><el-input-number v-model="config.radio.wireless_status_radio" :min="1" :max="3" /></div></el-form-item>
            </div>
            <el-form-item label="采集项"><el-checkbox v-model="config.items.terminal_monitor" disabled>terminal monitor（必选）</el-checkbox><el-checkbox v-model="config.items.mesh_link">mesh-link</el-checkbox><el-checkbox v-model="config.items.channel_busy">channel busy</el-checkbox><el-checkbox v-model="config.items.ap_radio_statistics">radio statistics</el-checkbox><el-checkbox v-model="config.items.switch_history">switch history</el-checkbox><el-checkbox v-model="config.items.interface_rate">interface rate</el-checkbox><el-checkbox v-model="config.items.wireless_status">wireless status</el-checkbox></el-form-item>
            <el-form-item label="采集间隔（秒）"><div class="inline-fields intervals"><label>Mesh <el-input-number v-model="config.intervals.mesh_link" :min="1" /></label><label>空口 <el-input-number v-model="config.intervals.channel_busy" :min="1" /></label><label>Radio <el-input-number v-model="config.intervals.ap_radio_statistics" :min="1" /></label><label>切换 <el-input-number v-model="config.intervals.switch_history" :min="10" /></label><label>接口 <el-input-number v-model="config.intervals.interface_rate" :min="1" /></label><label>无线状态 <el-input-number v-model="config.intervals.wireless_status" :min="1" /></label></div></el-form-item>
            <el-divider content-position="left">fping</el-divider><el-switch v-model="config.fping.enabled" active-text="启用 fping" />
            <div v-if="config.fping.enabled" class="form-grid"><el-form-item label="目标 IP"><el-input v-model="config.fping.target" /></el-form-item><el-form-item label="间隔 / 超时（ms）"><div class="inline-fields"><el-input-number v-model="config.fping.interval_ms" :min="10" /><el-input-number v-model="config.fping.timeout_ms" :min="1" /></div></el-form-item><el-form-item label="包大小"><el-input-number v-model="config.fping.packet_size" :min="1" :max="65535" /></el-form-item></div>
            <el-divider content-position="left">iPerf Client</el-divider><el-switch v-model="config.iperf.enabled" active-text="启用 iPerf Client" />
            <div v-if="config.iperf.enabled" class="form-grid"><el-form-item label="服务端 IP"><el-input v-model="config.iperf.server_ip" /></el-form-item><el-form-item label="端口"><el-input-number v-model="config.iperf.port" :min="1" :max="65535" /></el-form-item><el-form-item label="协议"><el-select v-model="config.iperf.protocol"><el-option label="TCP" value="TCP" /><el-option label="UDP" value="UDP" /></el-select></el-form-item><el-form-item label="并发流"><el-input-number v-model="config.iperf.parallel" :min="1" :max="32" /></el-form-item><el-form-item v-if="config.iperf.protocol === 'UDP'" label="UDP 带宽 Mbps"><el-input-number v-model="config.iperf.udp_bitrate_mbps" :min="0.1" /></el-form-item><el-form-item v-else label="TCP 阈值 Mbps"><el-input-number v-model="config.iperf.tcp_report_threshold_mbps" :min="0" /></el-form-item><el-form-item label="方向"><el-switch v-model="config.iperf.reverse" active-text="Reverse" /></el-form-item></div>
          </el-form>
        </el-collapse-item>
      </el-collapse>
      <div class="control-actions"><el-button type="primary" :loading="starting" :disabled="!canStart" @click="start">启动本地采集</el-button><el-button type="warning" :loading="stopping" :disabled="!canStop" @click="stop">正常停止并落盘</el-button><el-button type="danger" plain :loading="forceStopping" :disabled="!canStop" @click="forceStop">强制停止</el-button><el-button :loading="loading" @click="refresh">刷新状态</el-button><el-button @click="recover">重启恢复</el-button></div>
      <el-alert v-if="operation?.state === 'stopping'" title="正在等待 Traffic flush、SSH collector/writer 关闭、metadata 写入和原子打包。" type="warning" show-icon :closable="false" />
      <el-descriptions v-if="operation" :column="3" border class="operation-detail"><el-descriptions-item label="阶段">{{ operation.phase }}</el-descriptions-item><el-descriptions-item label="Task / Mapping">{{ operation.task_status || '无数据' }} / {{ operation.mapping_status }}</el-descriptions-item><el-descriptions-item label="Session">{{ operation.session_status || '待生成' }}</el-descriptions-item><el-descriptions-item label="fping / iPerf">{{ operation.fping_status }} / {{ operation.iperf_status }}</el-descriptions-item><el-descriptions-item label="数据完整性">{{ operation.data_integrity }}</el-descriptions-item><el-descriptions-item label="采集包">{{ operation.package_path_reference || operation.package_status }}</el-descriptions-item></el-descriptions>
      <div v-if="acceptanceCommand" class="acceptance"><code>{{ acceptanceCommand }}</code><el-button link type="primary" @click="copyAcceptance">复制验收命令</el-button></div>
    </template>
  </section>
</template>

<style scoped>
.control-panel { margin: 0 0 16px; padding: 16px; border: 1px solid var(--el-border-color); border-radius: 12px; background: var(--el-fill-color-extra-light); }.control-heading,.control-actions,.inline-fields,.acceptance { display: flex; align-items: center; gap: 12px; }.control-heading { justify-content: space-between; }.control-heading h3 { margin: 0 0 4px; }.control-heading p { margin: 0; color: var(--el-text-color-secondary); }.control-panel .el-alert,.control-config,.control-actions,.operation-detail,.acceptance { margin-top: 12px; }.form-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px; }.inline-fields { flex-wrap: wrap; }.intervals label { display: flex; align-items: center; gap: 6px; color: var(--el-text-color-secondary); }.acceptance { justify-content: space-between; padding: 10px 12px; border-radius: 8px; background: var(--el-fill-color-light); }.acceptance code { overflow-wrap: anywhere; }@media (max-width: 900px) { .form-grid { grid-template-columns: 1fr; }.control-heading { align-items: flex-start; flex-direction: column; } }
</style>
