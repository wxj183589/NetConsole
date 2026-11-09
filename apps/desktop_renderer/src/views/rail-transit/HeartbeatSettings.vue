<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getHeartbeatConfig, getHeartbeatRuntime, updateHeartbeatConfig } from '../../api/groundUnattended'
import type { HeartbeatConfig, HeartbeatRuntime } from '../../types/groundUnattended'
import { useGroundContext } from './useGroundUnattended'
import { isFeatureEnabled } from '../../features'

const { t, activeTab, pageVisible, pageActivated } = useGroundContext()
const config = ref<HeartbeatConfig>()
const runtime = ref<HeartbeatRuntime>()
const error = ref('')
const saving = ref(false)
const mounted = ref(false)
const active = computed(() => mounted.value && pageVisible.value && pageActivated.value && activeTab.value === 'settings')
let controller: AbortController | undefined
let timer: ReturnType<typeof setTimeout> | undefined
function stopPolling(): void {
  controller?.abort()
  if (timer) clearTimeout(timer)
  timer = undefined
}
async function poll(signal: AbortSignal): Promise<void> {
  try {
    const result = await getHeartbeatRuntime({ signal })
    if (!signal.aborted) runtime.value = result
  }
  catch (reason) { if (!signal.aborted) error.value = String(reason) }
  finally { if (!signal.aborted) timer = setTimeout(() => { void poll(signal) }, 3000) }
}
async function save(): Promise<void> {
  const signal = controller?.signal
  if (!config.value || saving.value || !signal || signal.aborted) return
  saving.value = true; error.value = ''
  try {
    const result = await updateHeartbeatConfig(config.value, { signal })
    if (!signal.aborted) config.value = result
  }
  catch (reason) { if (!signal.aborted) error.value = String(reason) }
  finally { saving.value = false }
}
async function load(signal: AbortSignal): Promise<void> {
  try {
    const result = await getHeartbeatConfig({ signal })
    if (!signal.aborted) config.value = result
  }
  catch (reason) { if (!signal.aborted) error.value = String(reason) }
  if (!signal.aborted) void poll(signal)
}
watch(active, (visible) => {
  stopPolling()
  if (visible) {
    controller = new AbortController()
    void load(controller.signal)
  }
})
onMounted(() => { mounted.value = true })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="heartbeat-settings">
    <h2>{{ t('ground.resident.title', '常驻 Heartbeat') }}</h2>
    <p>{{ t('ground.resident.note', 'Backend 启动后按此配置持续监测，独立于无人值守任务和页面；目标来自 MR 库存，不受 AC 位置、正线或车辆段分类影响。') }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form v-if="config" label-position="top">
      <div class="form-grid">
        <el-form-item :label="t('ground.resident.enabled', '启用常驻监测')"><el-switch v-model="config.enabled" /></el-form-item>
        <el-form-item :label="t('ground.ping_interval', 'Ping 间隔（ms）')"><el-input-number v-model="config.interval_ms" :min="100" :max="60000" /></el-form-item>
        <el-form-item :label="t('ground.ping_timeout', 'Ping 超时（ms）')"><el-input-number v-model="config.timeout_ms" :min="100" :max="60000" /></el-form-item>
        <el-form-item :label="t('ground.packet_size', '包大小（字节）')"><el-input-number v-model="config.packet_size" :min="1" :max="65507" /></el-form-item>
        <el-form-item :label="t('ground.shard_size', '每个 fping 分片目标数')"><el-input-number v-model="config.shard_size" :min="2" :max="32" /></el-form-item>
        <el-form-item :label="t('ground.v2.settings_warmup', '启动预热忽略时间（秒）')"><el-input-number v-model="config.warmup_seconds" :min="0" :max="300" /></el-form-item>
        <el-form-item :label="t('ground.resident.backup', '主备 IP 策略')"><el-select v-model="config.backup_policy"><el-option value="MONITOR" :label="t('ground.resident.both', '按设备策略监测主备 IP')" /><el-option value="PRIMARY_ONLY" :label="t('ground.resident.primary', '仅监测主用 IP')" /></el-select></el-form-item>
      </div>
      <el-button type="primary" :loading="saving" :disabled="!isFeatureEnabled('capability.ground_unattended.heartbeat_inventory_manage')" @click="save">{{ t('ground.resident.save', '保存心跳配置') }}</el-button>
    </el-form>
    <el-descriptions v-if="runtime" :column="2" border>
      <el-descriptions-item :label="t('ground.resident.state', '运行状态')">{{ t(`ground.resident.state_${runtime.state}`, runtime.state) }}</el-descriptions-item>
      <el-descriptions-item :label="t('ground.resident.targets', '目标数 / 分片数')">{{ runtime.target_count }} / {{ runtime.process_count }}</el-descriptions-item>
      <el-descriptions-item :label="t('ground.resident.last_probe', '最后检测时间')">{{ runtime.last_sample_at || '—' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ground.resident.last_success', '最后成功时间')">{{ runtime.last_success_at || '—' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ground.resident.error', '最近错误')">{{ runtime.last_error || '—' }}</el-descriptions-item>
    </el-descriptions>
  </section>
</template>

<style scoped>
.heartbeat-settings { padding: 16px 0; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.el-descriptions { margin-top: 16px; }
</style>
