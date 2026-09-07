<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
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
    ElMessage.success('SSH 中转设置已保存')
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
    ElMessage.success(`${result.message}（${result.duration_ms} ms）`)
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
  </section>
</template>

<style scoped>
.ssh-relay-panel p{margin:0;color:var(--nc-text-secondary);font-size:13px}.ssh-relay-form{max-width:720px;display:grid;grid-template-columns:repeat(2,minmax(240px,1fr));gap:0 18px}.ssh-relay-form :deep(.el-form-item:last-child){grid-column:1/-1}@media(max-width:800px){.ssh-relay-form{grid-template-columns:1fr}.ssh-relay-form :deep(.el-form-item:last-child){grid-column:auto}}
</style>
