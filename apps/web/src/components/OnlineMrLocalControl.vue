<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useConfirm } from './feedback/useConfirm'

import { forceStopOnlineMrControl, getOnlineMrControlOperation, getOnlineMrControlPresets, getOnlineMrControlStatus, recoverOnlineMrControl, startOnlineMrControl, stopOnlineMrControl } from '../api/onlineMrControl'
import type { OnlineMrControlMr, OnlineMrControlOperation, OnlineMrControlPresets, OnlineMrPingPreset, OnlineMrStartConfig, OnlineMrTrafficPreset } from '../types/onlineMrControl'

const props = defineProps<{ siteId: string; mr: OnlineMrControlMr }>()
const emit = defineEmits<{ refresh: [] }>()
const { confirm } = useConfirm()
const enabled = ref(false)
const loading = ref(false)
const starting = ref(false)
const stopping = ref(false)
const forceStopping = ref(false)
const error = ref('')
const operation = ref<OnlineMrControlOperation | null>(null)
const realDeviceTest = ref(false)
const presets = ref<OnlineMrControlPresets>({ ping: [], traffic: [] })
const pingPresetKey = ref('custom')
const trafficPresetKey = ref('custom')
let applyingPreset = false
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

const active = computed(() => ['preparing', 'starting', 'running', 'stopping'].includes(operation.value?.state || ''))
const canStart = computed(() => enabled.value && !active.value && !starting.value && !stopping.value && !forceStopping.value && props.mr.device_id !== null)
const canStop = computed(() => enabled.value && active.value && operation.value?.state !== 'stopping' && !stopping.value && !forceStopping.value)
const statusLabel = computed(() => ({
  preparing: '正在准备', starting: '正在启动', running: '采集中', stopping: '正在停止并落盘', stopped: '已停止',
  completed_with_warnings: '已完成，有告警', failed: '失败', aborted: '已中断',
} as Record<string, string>)[operation.value?.state || ''] || '未启动')
const statusType = computed(() => ({ preparing: 'primary', starting: 'primary', running: 'success', stopping: 'warning', stopped: 'info', completed_with_warnings: 'warning', failed: 'danger', aborted: 'danger' } as Record<string, string>)[operation.value?.state || ''] || 'info')
const acceptanceCommand = computed(() => operation.value?.session_id ? `python -m scripts.maintenance.check_online_mr_session_state --site "${props.siteId}" --session-id "${operation.value.session_id}"` : '')
const radioAdvanced = computed({
  get: () => config.radio.radio_mode === 'per_collector',
  set: (value: boolean) => {
    config.radio.radio_mode = value ? 'per_collector' : 'unified'
    if (value) syncCollectorRadioIds()
    else applyUnifiedRadio()
  },
})

function payload(): OnlineMrStartConfig {
  if (props.mr.device_id === null) throw new Error('当前 MR 未绑定正式设备')
  syncRadioPayload()
  return { site_id: props.siteId, device_id: props.mr.device_id, mr_id: props.mr.mr_id, executor: 'LOCAL', ...JSON.parse(JSON.stringify(config)) }
}
function applyUnifiedRadio(): void {
  const radioId = Math.max(1, Math.min(3, Number(config.radio.unified_radio_id || 1)))
  config.radio.unified_radio_id = radioId
  config.radio.channel_busy_radio = radioId
  config.radio.ap_radio_statistics_radio = radioId
  config.radio.wireless_status_radio = radioId
  syncCollectorRadioIds()
}
function syncCollectorRadioIds(): void {
  config.radio.collector_radio_ids = {
    channel_busy: config.radio.channel_busy_radio,
    ap_radio_statistics: config.radio.ap_radio_statistics_radio,
    wireless_status: config.radio.wireless_status_radio,
  }
}
function syncRadioPayload(): void {
  if (config.radio.radio_mode === 'per_collector') syncCollectorRadioIds()
  else applyUnifiedRadio()
}
function selectForMr(rows: OnlineMrControlOperation[]): OnlineMrControlOperation | null {
  return rows.find((item) => String(item.device_id) === String(props.mr.device_id) && ['preparing', 'starting', 'running', 'stopping'].includes(item.state)) || null
}
function applyRealDeviceLimits(): void {
  if (!realDeviceTest.value) return
  config.fping.enabled = true
  config.fping.interval_ms = 1000
  config.fping.timeout_ms = 4000
  pingPresetKey.value = 'custom'
  config.iperf.enabled = true
  config.iperf.server_ip = '127.0.0.1'
  config.iperf.protocol = 'TCP'
  config.iperf.parallel = 1
  config.iperf.tcp_rate_limit_mbps = 2
  config.iperf.packet_length = null
  config.iperf.reverse = false
  trafficPresetKey.value = 'custom'
}
async function loadPresets(): Promise<void> {
  if (presets.value.ping.length || presets.value.traffic.length) return
  presets.value = await getOnlineMrControlPresets()
  const defaultPing = presets.value.ping.find((item) => item.key === 'pis_high_ping_acceptance') || presets.value.ping[0]
  if (defaultPing) applyPingPreset(defaultPing.key)
}
function applyPingPreset(key: string): void {
  pingPresetKey.value = key
  if (key === 'custom') return
  const preset = presets.value.ping.find((item) => item.key === key)
  if (!preset) return
  applyingPreset = true
  config.fping.enabled = true
  config.fping.packet_size = preset.packet_size_bytes
  config.fping.interval_ms = preset.interval_ms
  config.fping.timeout_ms = preset.timeout_ms
  config.fping.loss_warn_percent = preset.loss_warn_percent
  config.fping.latency_warn_ms = preset.latency_warn_ms
  applyingPreset = false
}
function applyTrafficPreset(key: string): void {
  trafficPresetKey.value = key
  if (key === 'custom') return
  const preset = presets.value.traffic.find((item) => item.key === key)
  if (!preset) return
  applyingPreset = true
  config.iperf.enabled = true
  config.iperf.port = preset.port
  config.iperf.protocol = preset.protocol
  config.iperf.parallel = preset.parallel
  config.iperf.interval_seconds = preset.interval_sec
  config.iperf.tcp_report_threshold_mbps = preset.report_threshold_mbps
  config.iperf.tcp_rate_limit_mbps = null
  config.iperf.udp_bitrate_mbps = preset.udp_bitrate_mbps
  config.iperf.packet_length = preset.packet_length
  config.iperf.reverse = preset.reverse
  applyingPreset = false
}
function markPingCustom(): void { if (!applyingPreset) pingPresetKey.value = 'custom' }
function markTrafficCustom(): void { if (!applyingPreset) trafficPresetKey.value = 'custom' }
function presetName<T extends OnlineMrPingPreset | OnlineMrTrafficPreset>(rows: T[], key: string): string {
  return rows.find((item) => item.key === key)?.name || '自定义'
}
async function refresh(): Promise<void> {
  if (loading.value || document.hidden) return
  loading.value = true
  try {
    await loadPresets()
    if (operation.value?.operation_id) {
      const detail = await getOnlineMrControlOperation(operation.value.operation_id)
      operation.value = ['preparing', 'starting', 'running', 'stopping'].includes(detail.state) ? detail : null
    }
    else {
      const status = await getOnlineMrControlStatus()
      enabled.value = status.enabled
      realDeviceTest.value = status.real_device_test
      applyRealDeviceLimits()
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
    const realLimits = realDeviceTest.value
      ? ' 真实设备保护：仅宁波12号线01车；fping 1000/4000 ms；iPerf 127.0.0.1 TCP 2M。'
      : ''
    if (!await confirm({ type: 'WARNING', title: '启动本地采集', message: `确认从本机启动 ${props.mr.train_name} ${props.mr.mr_role} 的 Online MR 采集？${realLimits}`, confirmText: '启动' })) return
    operation.value = await startOnlineMrControl(payload())
    emit('refresh')
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
    if (!await confirm({ type: 'WARNING', title: '正常停止', message: '正常停止将等待 Traffic flush、采集器关闭和原子打包。确认继续？', confirmText: '停止并落盘' })) return
    operation.value = await stopOnlineMrControl(operation.value.operation_id)
    ElMessage.success('本地采集已完成正常停止')
    operation.value = null
    emit('refresh')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '停止失败'
  } finally { stopping.value = false; schedule() }
}
async function forceStop(): Promise<void> {
  if (!canStop.value || !operation.value) return
  forceStopping.value = true
  error.value = ''
  try {
    if (!await confirm({ type: 'DESTRUCTIVE', title: '强制停止本地采集', message: '强制停止可能无法完成全部 writer flush；系统会保留原始会话并标记为 partial。仅在正常停止无响应时继续。', confirmText: '确认强制停止' })) return
    operation.value = await forceStopOnlineMrControl(operation.value.operation_id)
    ElMessage.warning('采集已强制停止；请检查数据完整性与原始会话')
    operation.value = null
    emit('refresh')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = cause instanceof Error ? cause.message : '强制停止失败'
  } finally { forceStopping.value = false; schedule() }
}
async function recover(): Promise<void> {
  if (!enabled.value) return
  try {
    const rows = await recoverOnlineMrControl()
    operation.value = selectForMr(rows) || operation.value
    emit('refresh')
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
    <el-alert
      v-if="realDeviceTest"
      title="真实设备保护模式：仅允许宁波12号线01车；fping 固定 1000/4000 ms；iPerf 固定 127.0.0.1、TCP、2M。历史数据只追加，不清理或覆盖。"
      type="warning"
      show-icon
      :closable="false"
    />
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
              <el-form-item label="Radio ID"><div class="inline-fields"><el-input-number v-model="config.radio.unified_radio_id" :min="1" :max="3" :disabled="radioAdvanced" @change="applyUnifiedRadio" /><el-checkbox v-model="radioAdvanced">分别设置 Radio</el-checkbox></div></el-form-item>
            </div>
            <el-form-item v-if="radioAdvanced" label="高级：分别设置 Radio"><div class="inline-fields intervals"><label>空口 <el-input-number v-model="config.radio.channel_busy_radio" :min="1" :max="3" @change="syncCollectorRadioIds" /></label><label>Radio 统计 <el-input-number v-model="config.radio.ap_radio_statistics_radio" :min="1" :max="3" @change="syncCollectorRadioIds" /></label><label>无线状态 <el-input-number v-model="config.radio.wireless_status_radio" :min="1" :max="3" @change="syncCollectorRadioIds" /></label></div></el-form-item>
            <el-form-item label="采集项"><el-checkbox v-model="config.items.terminal_monitor" disabled>terminal monitor（必选）</el-checkbox><el-checkbox v-model="config.items.mesh_link">mesh-link</el-checkbox><el-checkbox v-model="config.items.channel_busy">channel busy</el-checkbox><el-checkbox v-model="config.items.ap_radio_statistics">radio statistics</el-checkbox><el-checkbox v-model="config.items.switch_history">switch history</el-checkbox><el-checkbox v-model="config.items.interface_rate">interface rate</el-checkbox><el-checkbox v-model="config.items.wireless_status">wireless status</el-checkbox></el-form-item>
            <el-form-item label="采集间隔（秒）"><div class="inline-fields intervals"><label>Mesh <el-input-number v-model="config.intervals.mesh_link" :min="1" /></label><label>空口 <el-input-number v-model="config.intervals.channel_busy" :min="1" /></label><label>Radio <el-input-number v-model="config.intervals.ap_radio_statistics" :min="1" /></label><label>切换 <el-input-number v-model="config.intervals.switch_history" :min="10" /></label><label>接口 <el-input-number v-model="config.intervals.interface_rate" :min="1" /></label><label>无线状态 <el-input-number v-model="config.intervals.wireless_status" :min="1" /></label></div></el-form-item>
            <el-divider content-position="left">fping</el-divider><div class="subpanel-head"><el-switch v-model="config.fping.enabled" active-text="启用 fping" :disabled="realDeviceTest" @change="markPingCustom" /><span class="secondary-text">模板：{{ presetName(presets.ping, pingPresetKey) }}</span></div>
            <div v-if="config.fping.enabled" class="form-grid"><el-form-item label="测试模板"><el-select v-model="pingPresetKey" :disabled="realDeviceTest" @change="applyPingPreset"><el-option label="自定义" value="custom" /><el-option v-for="item in presets.ping" :key="item.key" :label="item.name" :value="item.key" /></el-select></el-form-item><el-form-item label="目标 IP"><el-input v-model="config.fping.target" /></el-form-item><el-form-item label="间隔 / 超时（ms）"><div class="inline-fields"><el-input-number v-model="config.fping.interval_ms" :min="10" :disabled="realDeviceTest" @change="markPingCustom" /><el-input-number v-model="config.fping.timeout_ms" :min="1" :disabled="realDeviceTest" @change="markPingCustom" /></div></el-form-item><el-form-item label="包大小"><el-input-number v-model="config.fping.packet_size" :min="1" :max="65535" @change="markPingCustom" /></el-form-item></div>
            <el-divider content-position="left">iPerf Client</el-divider><el-switch v-model="config.iperf.enabled" active-text="启用 iPerf Client" :disabled="realDeviceTest" />
            <div v-if="config.iperf.enabled" class="form-grid"><el-form-item label="测试模板"><el-select v-model="trafficPresetKey" :disabled="realDeviceTest" @change="applyTrafficPreset"><el-option label="自定义" value="custom" /><el-option v-for="item in presets.traffic" :key="item.key" :label="item.name" :value="item.key" /></el-select></el-form-item><el-form-item label="服务端 IP"><el-input v-model="config.iperf.server_ip" :disabled="realDeviceTest" /></el-form-item><el-form-item label="端口"><el-input-number v-model="config.iperf.port" :min="1" :max="65535" @change="markTrafficCustom" /></el-form-item><el-form-item label="协议"><el-select v-model="config.iperf.protocol" :disabled="realDeviceTest" @change="markTrafficCustom"><el-option label="TCP" value="TCP" /><el-option label="UDP" value="UDP" /></el-select></el-form-item><el-form-item label="并发流"><el-input-number v-model="config.iperf.parallel" :min="1" :max="32" :disabled="realDeviceTest" @change="markTrafficCustom" /></el-form-item><el-form-item v-if="config.iperf.protocol === 'UDP'" label="UDP 带宽 Mbps"><el-input-number v-model="config.iperf.udp_bitrate_mbps" :min="0.1" @change="markTrafficCustom" /></el-form-item><el-form-item v-if="config.iperf.protocol === 'UDP'" label="UDP 包长"><el-input-number v-model="config.iperf.packet_length" :min="1" :max="65507" @change="markTrafficCustom" /></el-form-item><el-form-item v-if="config.iperf.protocol === 'TCP'" label="TCP 限速 Mbps"><el-input-number v-model="config.iperf.tcp_rate_limit_mbps" :min="0" :disabled="realDeviceTest" controls-position="right" placeholder="空或 0 不限速" @change="markTrafficCustom" /></el-form-item><el-form-item label="TCP 验收阈值 Mbps"><el-input-number v-model="config.iperf.tcp_report_threshold_mbps" :min="0" @change="markTrafficCustom" /></el-form-item><el-form-item label="方向"><el-switch v-model="config.iperf.reverse" active-text="Reverse" :disabled="realDeviceTest" @change="markTrafficCustom" /></el-form-item></div>
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
.control-panel { margin: 0 0 16px; padding: 16px; border: 1px solid var(--el-border-color); border-radius: 12px; background: var(--el-fill-color-extra-light); }.control-heading,.control-actions,.inline-fields,.acceptance,.subpanel-head { display: flex; align-items: center; gap: 12px; }.control-heading { justify-content: space-between; }.control-heading h3 { margin: 0 0 4px; }.control-heading p,.secondary-text { margin: 0; color: var(--el-text-color-secondary); }.control-panel .el-alert,.control-config,.control-actions,.operation-detail,.acceptance { margin-top: 12px; }.subpanel-head { flex-wrap: wrap; margin-bottom: 8px; }.form-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px; }.inline-fields { flex-wrap: wrap; }.intervals label { display: flex; align-items: center; gap: 6px; color: var(--el-text-color-secondary); }.acceptance { justify-content: space-between; padding: 10px 12px; border-radius: 8px; background: var(--el-fill-color-light); }.acceptance code { overflow-wrap: anywhere; }@media (max-width: 900px) { .form-grid { grid-template-columns: 1fr; }.control-heading { align-items: flex-start; flex-direction: column; } }
</style>
