<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getActiveSite, getSiteSSHRelay, testSiteSSHRelay, updateSiteSSHRelay, type SiteSSHRelay } from '../../api/siteStorage'
import { ApiRequestError } from '../../api/client'
import { LEGACY_SITE_CONTEXT_CHANGED_EVENT, SITE_CONTEXT_CHANGED_EVENT } from '../../workspace/site-switch'

const relay = ref<SiteSSHRelay | null>(null)
const siteId = ref('')
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const password = ref('')
const form = reactive({ enabled: false, host: '', port: 22, username: '' })

const runtimeLabel = computed(() => {
  switch (relay.value?.runtime_status) {
    case 'RUNNING': return '已连接'
    case 'CONNECTING':
    case 'STARTING': return '连接中'
    case 'JUMP_AUTH_FAILED': return '认证失败'
    case 'JUMP_CONNECT_FAILED': return '连接失败'
    case 'CREDENTIAL_UNAVAILABLE':
    case 'SSH_RELAY_CREDENTIAL_UNAVAILABLE': return '凭据不可用'
    case 'JUMP_HOSTKEY_FAILED': return '主机密钥维护失败'
    case 'CONFIG_INCOMPLETE': return '配置不完整'
    case 'DISABLED': return '未启用'
    default: return relay.value?.runtime_status || '未连接'
  }
})

const runtimeTagType = computed(() => relay.value?.runtime_status === 'RUNNING' ? 'success' : relay.value?.enabled ? 'warning' : 'info')

const hostKeyLabel = computed(() => {
  const status = relay.value?.host_key_status
  if (status === 'HOST_KEY_AUTO_ADDED') return '已自动登记'
  if (status === 'HOST_KEY_AUTO_UPDATED') return '已自动更新'
  if (status === 'HOST_KEY_VERIFIED') return '已验证'
  return relay.value?.enabled ? '待连接' : '未启用'
})

onMounted(() => {
  window.addEventListener(SITE_CONTEXT_CHANGED_EVENT, reload)
  window.addEventListener(LEGACY_SITE_CONTEXT_CHANGED_EVENT, reload)
  void reload()
})
onBeforeUnmount(() => {
  window.removeEventListener(SITE_CONTEXT_CHANGED_EVENT, reload)
  window.removeEventListener(LEGACY_SITE_CONTEXT_CHANGED_EVENT, reload)
})

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const active = await getActiveSite()
    siteId.value = active.site_id
    relay.value = await getSiteSSHRelay(active.site_id)
    form.enabled = relay.value.enabled
    form.host = relay.value.host
    form.port = relay.value.port
    form.username = relay.value.username
    password.value = ''
  } catch (cause) {
    error.value = message(cause, 'SSH 中转设置加载失败')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!siteId.value) return
  saving.value = true
  error.value = ''
  try {
    const payload: { enabled: boolean; host: string; port: number; username: string; password?: string } = { ...form }
    if (password.value) payload.password = password.value
    relay.value = await updateSiteSSHRelay(siteId.value, payload)
    password.value = ''
    form.enabled = relay.value.enabled
    if (relay.value.runtime_status === 'RUNNING') {
      ElMessage.success('SSH 中转设置已保存并启动')
    } else {
      ElMessage.warning(`SSH 中转设置已保存，但当前未运行：${runtimeLabel.value}`)
    }
  } catch (cause) {
    error.value = message(cause, 'SSH 中转设置保存失败')
  } finally {
    saving.value = false
  }
}

async function test(): Promise<void> {
  if (!siteId.value) return
  testing.value = true
  error.value = ''
  try {
    const result = await testSiteSSHRelay(siteId.value)
    ElMessage.success(`${result.message}（${result.duration_ms} ms；${result.host_key_status || 'HOST_KEY_VERIFIED'}）`)
  } catch (cause) {
    error.value = message(cause, 'SSH 中转服务器连接测试失败')
  } finally {
    testing.value = false
  }
}

function message(cause: unknown, fallback: string): string {
  if (cause instanceof ApiRequestError) return cause.message || fallback
  return cause instanceof Error ? cause.message : fallback
}
</script>

<template>
  <section class="settings-band ssh-relay-panel">
    <div class="section-heading">
      <div><h2>SSH 中转</h2><p v-if="form.enabled">当前局点所有设备 SSH 连接将通过该 Jump Host；不代理 Ping、SNMP 或 UDP。</p><p v-else>开启后，当前局点所有设备 SSH 连接将通过该 Jump Host；不代理 Ping、SNMP 或 UDP。</p></div>
      <el-button size="small" :loading="loading" @click="reload">重新读取</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form v-if="siteId" label-width="130px" class="ssh-relay-form" @submit.prevent="save">
      <el-form-item label="启用 SSH 中转"><el-switch v-model="form.enabled" /></el-form-item>
      <el-form-item label="中转服务器 IP"><el-input v-model="form.host" placeholder="例如 10.81.40.10" /></el-form-item>
      <el-form-item label="SSH 端口"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
      <el-form-item label="用户名"><el-input v-model="form.username" autocomplete="username" /></el-form-item>
      <el-form-item label="密码"><el-input v-model="password" type="password" show-password autocomplete="new-password" placeholder="留空表示保持已保存密码" /></el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" :disabled="loading" @click="save">保存设置</el-button>
        <el-button :loading="testing" :disabled="!relay?.complete || saving" @click="test">测试连接</el-button>
        <el-tag v-if="relay" :type="relay.enabled ? 'success' : 'info'">{{ relay.enabled ? '已启用' : '未启用' }}</el-tag>
      </el-form-item>
    </el-form>
    <div v-if="relay" class="relay-status-grid">
      <div><span>运行状态</span><el-tag size="small" :type="runtimeTagType">● {{ runtimeLabel }}</el-tag></div>
      <div><span>自动运行</span><b>{{ relay.enabled ? '已开启' : '未开启' }}</b></div>
      <div><span>中转服务器</span><b>{{ relay.host ? `${relay.host}:${relay.port}` : '—' }}</b></div>
      <div><span>主机指纹</span><b class="fingerprint" :title="`来源：Paramiko SSH Host Key；管理策略：自动`">{{ relay.host_key_fingerprint_sha256 || '尚未登记' }}</b></div>
      <div><span>指纹管理</span><b :title="'Jump Host 使用 AUTO_REPLACE；首次自动登记，变化自动替换并继续连接。其他 SSH consumer 保持原策略。'">{{ hostKeyLabel }}</b></div>
      <div><span>凭据</span><b>{{ relay.password_configured ? '密码已保存' : '未保存' }}</b></div>
    </div>
    <el-alert
      v-if="relay?.enabled && relay.runtime_status && relay.runtime_status !== 'RUNNING'"
      :title="relay.runtime_message || `SSH 中转当前状态：${runtimeLabel}`"
      type="warning"
      :closable="false"
      class="relay-runtime-alert"
    />
  </section>
</template>

<style scoped>
.ssh-relay-panel p{margin:0;color:var(--nc-text-secondary);font-size:13px}.ssh-relay-form{max-width:720px;display:grid;grid-template-columns:repeat(2,minmax(240px,1fr));gap:0 18px}.ssh-relay-form :deep(.el-form-item:last-child){grid-column:1/-1}.relay-status-grid{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:8px 18px;margin:4px 0 8px;padding:10px 12px;border:1px solid var(--nc-border-color);border-radius:6px;background:var(--nc-surface-muted)}.relay-status-grid>div{display:flex;gap:8px;min-width:0;align-items:center;font-size:13px}.relay-status-grid span{color:var(--nc-text-secondary);white-space:nowrap}.relay-status-grid b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fingerprint{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.relay-runtime-alert{margin-top:8px}@media(max-width:800px){.ssh-relay-form{grid-template-columns:1fr}.ssh-relay-form :deep(.el-form-item:last-child){grid-column:auto}.relay-status-grid{grid-template-columns:1fr}}
</style>
