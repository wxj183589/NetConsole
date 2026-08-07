<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  listTracksideWpsTargets,
  testTracksideWpsTarget,
  updateTracksideWpsTarget,
} from '../../api/tracksideApBusiness'
import type {
  WpsTracksideTarget,
  WpsTracksideTargetCode,
} from '../../types/tracksideApBusiness'
import { openWpsDocumentUrl } from './wpsDocumentLink'

const props = defineProps<{
  modelValue: boolean
  targets: WpsTracksideTarget[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'targets-updated': [value: WpsTracksideTarget[]]
}>()

interface TargetDraft {
  target_code: WpsTracksideTargetCode
  enabled: boolean
  timeout_seconds: number
  document_open_url: string
  webhook_url: string
  token: string
}

interface ConnectionDiagnostic {
  phase: string
  http_status?: number
  remote_error_code?: string
  remote_message?: string
  suggestion?: string
}

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const localTargets = ref<WpsTracksideTarget[]>([])
const drafts = ref<TargetDraft[]>([])
const savingCode = ref<WpsTracksideTargetCode | ''>('')
const testingCode = ref<WpsTracksideTargetCode | ''>('')
const errorMessage = ref('')
const testMessages = ref<Partial<Record<WpsTracksideTargetCode, string>>>({})
const testDiagnostics = ref<Partial<Record<WpsTracksideTargetCode, ConnectionDiagnostic>>>({})
const targetRows = computed(() => localTargets.value.flatMap((target) => {
  const draft = targetDraft(target.target_code)
  return draft ? [{ target, draft }] : []
}))

watch(
  () => props.targets,
  (value) => applyTargets(value, visible.value),
  { deep: true, immediate: true },
)

watch(visible, (value) => {
  if (!value) clearSensitiveInput()
})

function applyTargets(value: WpsTracksideTarget[], preserveDrafts = false): void {
  const existingDrafts = new Map(drafts.value.map((draft) => [draft.target_code, draft]))
  localTargets.value = value.map((target) => ({ ...target }))
  drafts.value = value.map((target) => {
    const existing = preserveDrafts ? existingDrafts.get(target.target_code) : undefined
    return existing || {
      target_code: target.target_code,
      enabled: target.enabled,
      timeout_seconds: target.timeout_seconds,
      document_open_url: target.document_open_url,
      webhook_url: target.webhook_url,
      token: '',
    }
  })
}

function targetDraft(code: WpsTracksideTargetCode): TargetDraft | undefined {
  return drafts.value.find((item) => item.target_code === code)
}

function targetTypeLabel(target: WpsTracksideTarget): string {
  return target.target_type === 'WPS_SMART_SHEET' ? '智能表格' : '普通在线表格'
}

function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

function statusLabel(status: string): string {
  if (status === 'SUCCESS') return '成功'
  if (status === 'FAILED') return '失败'
  return '未执行'
}

function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    LOCAL_CONFIGURATION: '本地配置',
    DNS_CONNECT: 'DNS/连接',
    TLS_CONNECT: 'TLS 连接',
    HTTP_AUTH: 'WPS HTTP 鉴权',
    SCRIPT_EXECUTION: '脚本执行',
    PROTOCOL_HANDSHAKE: '协议校验',
    DOCUMENT_IDENTITY: '文档身份',
    SUCCESS: '成功',
  }
  return labels[phase] || phase || '未知'
}

function clearSensitiveInput(): void {
  for (const draft of drafts.value) draft.token = ''
}

async function reloadTargets(preserveDrafts = false): Promise<WpsTracksideTarget[]> {
  const targets = await listTracksideWpsTargets()
  applyTargets(targets, preserveDrafts)
  emit('targets-updated', targets)
  return targets
}

async function saveTargetConfiguration(
  code: WpsTracksideTargetCode,
  silent = false,
): Promise<boolean> {
  const draft = targetDraft(code)
  if (savingCode.value || testingCode.value || !draft) return false
  savingCode.value = code
  errorMessage.value = ''
  try {
    const token = draft.token.trim()
    await updateTracksideWpsTarget(code, {
      enabled: draft.enabled,
      timeout_seconds: draft.timeout_seconds,
      document_open_url: draft.document_open_url.trim(),
      webhook_url: draft.webhook_url.trim(),
      ...(token ? { token } : {}),
    })
    draft.token = ''
    await reloadTargets(true)
    if (!silent) ElMessage.success('当前 WPS 云文档连接配置已保存')
    return true
  } catch (reason) {
    errorMessage.value = reason instanceof Error ? reason.message : 'WPS 配置保存失败'
    return false
  } finally {
    savingCode.value = ''
  }
}

async function testConnection(code: WpsTracksideTargetCode): Promise<void> {
  if (testingCode.value || savingCode.value) return
  errorMessage.value = ''
  const saved = await saveTargetConfiguration(code, true)
  if (!saved) return
  const target = localTargets.value.find((item) => item.target_code === code)
  if (!target?.token_configured) {
    errorMessage.value = '请先输入脚本令牌并保存配置'
    return
  }
  testingCode.value = code
  try {
    const response = await testTracksideWpsTarget(code)
    const result = response.result
    const documentName = String(result.document_name || target.target_name)
    const scriptVersion = String(result.script_version || '未知')
    testMessages.value = {
      ...testMessages.value,
      [code]: `连接成功：${documentName}，脚本 ${scriptVersion}`,
    }
    const nextDiagnostics = { ...testDiagnostics.value }
    delete nextDiagnostics[code]
    testDiagnostics.value = nextDiagnostics
    await reloadTargets()
    ElMessage.success(`${targetTypeLabel(target)}连接测试通过`)
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : '连接测试失败'
    testMessages.value = { ...testMessages.value, [code]: message }
    const details = (reason && typeof reason === 'object' && 'details' in reason)
      ? (reason as { details?: Record<string, unknown> }).details || {}
      : {}
    testDiagnostics.value = {
      ...testDiagnostics.value,
      [code]: {
        phase: String(details.phase || 'HTTP_AUTH'),
        ...(details.http_status === undefined ? {} : { http_status: Number(details.http_status) }),
        ...(details.remote_error_code ? { remote_error_code: String(details.remote_error_code) } : {}),
        ...(details.remote_message ? { remote_message: String(details.remote_message) } : {}),
        ...(details.suggestion ? { suggestion: String(details.suggestion) } : {}),
      },
    }
    await reloadTargets().catch(() => undefined)
  } finally {
    testingCode.value = ''
  }
}

async function openDocument(target: WpsTracksideTarget): Promise<void> {
  const result = await openWpsDocumentUrl(target.document_open_url)
  if (!result.success) errorMessage.value = result.error || '系统浏览器打开失败'
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="配置 WPS 云文档连接"
    width="min(820px, 94vw)"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <div class="wps-config">
      <el-alert
        title="普通在线表格和智能表格分别保存连接地址、webhook 和受保护令牌。请在各自卡片中单独保存，令牌保存后不会回显。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

      <section
        v-for="row in targetRows"
        :key="row.target.target_code"
        class="wps-target"
      >
        <div class="target-heading">
          <div>
            <strong>{{ targetTypeLabel(row.target) }}</strong>
            <span>{{ row.target.target_name }}</span>
          </div>
          <el-tag :type="row.target.token_configured ? 'success' : 'danger'">
            {{ row.target.token_configured ? `令牌已配置 · ${row.target.token_suffix || '已保护'}` : '令牌未配置' }}
          </el-tag>
        </div>

        <div class="target-fields">
          <label>
            <span>启用目标</span>
            <el-switch v-model="row.draft.enabled" />
          </label>
          <label>
            <span>请求超时（秒）</span>
            <el-input-number
              v-model="row.draft.timeout_seconds"
              :min="5"
              :max="120"
              :step="5"
              controls-position="right"
            />
          </label>
          <div>
            <span>文档标识</span>
            <code>{{ row.target.expected_document_id }}</code>
          </div>
        </div>

        <el-form label-position="top" class="connection-fields">
          <el-form-item label="在线文档连接：">
            <el-input v-model="row.draft.document_open_url" placeholder="https://www.kdocs.cn/l/..." />
          </el-form-item>
          <el-form-item label="webhook地址：">
            <el-input v-model="row.draft.webhook_url" placeholder="https://www.kdocs.cn/api/v3/ide/file/.../sync_task" />
          </el-form-item>
          <el-form-item label="脚本令牌：">
            <el-input
              v-model="row.draft.token"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="留空表示保留该目标现有令牌"
            />
          </el-form-item>
        </el-form>

        <div class="target-status">
          <span>连接测试</span>
          <el-tag size="small" :type="statusType(row.target.last_test_status)">{{ statusLabel(row.target.last_test_status) }}</el-tag>
          <span v-if="row.target.last_test_message">{{ row.target.last_test_message }}</span>
          <span>最近同步</span>
          <el-tag size="small" :type="statusType(row.target.last_sync_status)">{{ statusLabel(row.target.last_sync_status) }}</el-tag>
        </div>
        <p v-if="testMessages[row.target.target_code]" class="test-message">{{ testMessages[row.target.target_code] }}</p>
        <div v-if="testDiagnostics[row.target.target_code]" class="test-diagnostic">
          <span>阶段：{{ phaseLabel(testDiagnostics[row.target.target_code]?.phase || '') }}</span>
          <span v-if="testDiagnostics[row.target.target_code]?.http_status">HTTP 状态：{{ testDiagnostics[row.target.target_code]?.http_status }}</span>
          <span v-if="testDiagnostics[row.target.target_code]?.remote_error_code">WPS 错误码：{{ testDiagnostics[row.target.target_code]?.remote_error_code }}</span>
          <span v-if="testDiagnostics[row.target.target_code]?.remote_message">原因：{{ testDiagnostics[row.target.target_code]?.remote_message }}</span>
          <span v-if="testDiagnostics[row.target.target_code]?.suggestion">建议：{{ testDiagnostics[row.target.target_code]?.suggestion }}</span>
        </div>

        <div class="target-actions">
          <el-button
            type="primary"
            :loading="savingCode === row.target.target_code"
            :disabled="Boolean(savingCode) || Boolean(testingCode)"
            @click="saveTargetConfiguration(row.target.target_code)"
          >保存此目标</el-button>
          <el-button
            :loading="testingCode === row.target.target_code"
            :disabled="Boolean(testingCode) || Boolean(savingCode)"
            @click="testConnection(row.target.target_code)"
          >测试连接</el-button>
          <el-button link type="primary" @click="openDocument(row.target)">打开文档</el-button>
        </div>
      </section>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.wps-config{display:grid;gap:16px;max-height:70vh;overflow:auto;padding-right:4px}.wps-config :deep(.el-form-item){margin-bottom:14px}.wps-target{display:grid;gap:12px;border-top:1px solid var(--el-border-color-lighter);padding-top:16px}.target-heading,.target-actions,.target-status{display:flex;align-items:center;gap:10px}.target-heading{justify-content:space-between}.target-heading>div{display:grid;gap:4px}.target-heading span,.target-status,.target-fields span{color:var(--el-text-color-secondary);font-size:12px}.target-fields{display:grid;grid-template-columns:150px 220px minmax(180px,1fr);gap:16px}.target-fields>label,.target-fields>div{display:grid;align-content:start;gap:7px}.connection-fields{display:grid;grid-template-columns:1fr;gap:0}.target-status{flex-wrap:wrap}.target-status>span:nth-of-type(2){margin-left:12px}.test-message{margin:0;color:var(--el-text-color-regular);font-size:13px}.test-diagnostic{display:grid;gap:4px;margin:0;padding:8px 10px;background:var(--el-fill-color-light);color:var(--el-text-color-regular);font-size:12px}.target-actions{justify-content:flex-end}code{overflow-wrap:anywhere}@media(max-width:720px){.target-fields{grid-template-columns:1fr}.target-heading{align-items:flex-start;flex-direction:column}.target-actions{justify-content:flex-start}}
</style>
