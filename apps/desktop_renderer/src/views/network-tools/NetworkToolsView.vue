<script setup lang="ts">
import { ref } from 'vue'
import { diagnoseHost } from '../../api/networkTools'
import { t } from '../../i18n/runtime'
import NetworkToolboxPanel from '../../components/network-tools/NetworkToolboxPanel.vue'

const kind = ref<'traceroute' | 'dns'>('traceroute')
const target = ref('')
const output = ref('')
const error = ref('')
const running = ref(false)

async function diagnose(): Promise<void> {
  if (running.value || !target.value.trim()) return
  running.value = true
  output.value = ''
  error.value = ''
  try {
    output.value = (await diagnoseHost(kind.value, target.value.trim())).output
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('network.diagnostic_failed', '诊断失败')
  } finally {
    running.value = false
  }
}
</script>

<template>
  <section class="network-tools-page">
    <header><h1>小工具与连通性检测</h1><p>IP 计算与 Ping 任务统一走 Python Application Service 和任务中心。</p></header>
    <NetworkToolboxPanel />
    <form class="host-diagnostic" @submit.prevent="diagnose">
      <el-select v-model="kind" :disabled="running" :aria-label="t('network.diagnostic_type', '诊断类型')">
        <el-option label="Traceroute" value="traceroute" />
        <el-option :label="t('network.dns_lookup', 'DNS 查询')" value="dns" />
      </el-select>
      <el-input v-model="target" maxlength="255" :disabled="running" :placeholder="kind === 'traceroute' ? 'IPv4 / IPv6' : 'example.com'" :aria-label="t('network.diagnostic_target', '诊断目标')" />
      <el-button native-type="submit" :loading="running" :disabled="!target.trim()">{{ t('network.diagnostic_run', '执行诊断') }}</el-button>
    </form>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <pre v-if="output" class="diagnostic-output">{{ output }}</pre>
  </section>
</template>

<style scoped>
.network-tools-page { display: flex; flex-direction: column; gap: 16px; }
header h1 { margin: 0 0 4px; }
header p { color: var(--el-text-color-secondary); margin: 0; }
.host-diagnostic { display: flex; flex-wrap: wrap; gap: 8px; }
.host-diagnostic .el-select { width: 140px; }
.host-diagnostic .el-input { width: min(280px, 100%); }
.diagnostic-output { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 25rem; overflow: auto; }
</style>
