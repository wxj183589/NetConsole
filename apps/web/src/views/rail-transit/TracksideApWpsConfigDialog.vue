<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Document, Guide } from '@element-plus/icons-vue'

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
import { wpsAirScriptSource, type WpsAirScriptKind } from './wpsAirScriptSources'

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
  remote_script_version?: string
  remote_deployment_id?: string
  remote_target_code?: string
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
const deploymentOpen = ref<Partial<Record<WpsTracksideTargetCode, boolean>>>({})
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

function webhookScriptIdSummary(value: string): string {
  const match = value.match(/\/script\/([^/]+)\/sync_task(?:$|[?#])/i)
  const scriptId = match?.[1] || ''
  if (!scriptId) return '未配置'
  if (scriptId.length <= 8) return `${scriptId.slice(0, 2)}...${scriptId.slice(-2)}`
  return `${scriptId.slice(0, 4)}...${scriptId.slice(-4)}`
}

async function copyAirScript(
  code: WpsTracksideTargetCode,
  kind: WpsAirScriptKind,
): Promise<void> {
  try {
    await navigator.clipboard.writeText(wpsAirScriptSource(code, kind))
    ElMessage.success(kind === 'probe' ? '只读连接探针已复制' : '正式同步脚本已复制')
  } catch {
    ElMessage.error('复制失败，请检查剪贴板权限')
  }
}

function toggleDeploymentSteps(code: WpsTracksideTargetCode): void {
  deploymentOpen.value = {
    ...deploymentOpen.value,
    [code]: !deploymentOpen.value[code],
  }
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
    testDiagnostics.value = {
      ...testDiagnostics.value,
      [code]: {
        phase: 'SUCCESS',
        remote_script_version: String(result.script_version || ''),
        remote_deployment_id: String(result.deployment_id || ''),
        remote_target_code: String(result.target_code || ''),
      },
    }
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
        ...(details.remote_script_version ? { remote_script_version: String(details.remote_script_version) } : {}),
        ...(details.remote_deployment_id ? { remote_deployment_id: String(details.remote_deployment_id) } : {}),
        ...(details.remote_target_code ? { remote_target_code: String(details.remote_target_code) } : {}),
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

        <el-alert
          v-if="row.target.runtime_capability !== 'VERIFIED'"
          :title="row.target.target_type === 'WPS_SMART_SHEET'
            ? '智能表格正式写入接口尚未完成 WPS 运行时验收，默认关闭；只读连接探针可独立验证。'
            : '普通表格正式写入仍需在目标 WPS 文档完成运行时验收；连接探针不会写入文档。'"
          type="warning"
          :closable="false"
          show-icon
        />

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
            <span>预期文档 ID</span>
            <code>{{ row.target.expected_document_id }}</code>
          </div>
        </div>

        <div class="script-identity">
          <span>本地期望脚本版本 <code>{{ row.target.expected_script_version || '未返回' }}</code></span>
          <span>本地期望部署 ID <code>{{ row.target.expected_deployment_id || '未返回' }}</code></span>
          <span>webhook 脚本 ID <code>{{ webhookScriptIdSummary(row.draft.webhook_url) }}</code></span>
          <span v-if="testDiagnostics[row.target.target_code]?.remote_script_version">WPS 返回脚本版本 <code>{{ testDiagnostics[row.target.target_code]?.remote_script_version }}</code></span>
          <span v-if="testDiagnostics[row.target.target_code]?.remote_deployment_id">WPS 返回部署 ID <code>{{ testDiagnostics[row.target.target_code]?.remote_deployment_id }}</code></span>
          <span v-if="testDiagnostics[row.target.target_code]?.remote_target_code">WPS 返回目标代码 <code>{{ testDiagnostics[row.target.target_code]?.remote_target_code }}</code></span>
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

        <div class="deployment-actions">
          <el-button :icon="CopyDocument" @click="copyAirScript(row.target.target_code, 'probe')">复制连接测试脚本</el-button>
          <el-button :icon="CopyDocument" @click="copyAirScript(row.target.target_code, 'sync')">复制正式同步脚本</el-button>
          <el-button :icon="Guide" @click="toggleDeploymentSteps(row.target.target_code)">查看部署步骤</el-button>
        </div>

        <div v-if="deploymentOpen[row.target.target_code]" class="deployment-steps">
          <strong>部署步骤</strong>
          <ol>
            <li>打开此目标对应的 WPS 文档和 AirScript 编辑器。</li>
            <li>在“文档共享脚本”中新建 AirScript 2.0 脚本，先粘贴只读连接探针并保存。</li>
            <li>在编辑器内运行探针，确认返回成功且文档 ID、目标类型、脚本版本和部署 ID 一致。</li>
            <li>在同一个脚本中换成正式同步脚本并保存；智能表格正式写入仍须等待运行时能力验收。</li>
            <li>从刚才同一个脚本的“...”菜单复制 webhook，返回 NetConsole 替换 webhook 并保存。</li>
            <li>点击“测试连接”，核对 WPS 返回的脚本版本、部署 ID 和目标代码。</li>
          </ol>
          <p>新建脚本会生成新的 script_id，旧 webhook 随之失效。普通表格与智能表格必须使用各自文档、各自脚本和各自 webhook，不能交叉复用。</p>
        </div>

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
          <el-button link type="primary" :icon="Document" @click="openDocument(row.target)">打开文档</el-button>
        </div>
      </section>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.wps-config{display:grid;gap:16px;max-height:70vh;overflow:auto;padding-right:4px}.wps-config :deep(.el-form-item){margin-bottom:14px}.wps-target{display:grid;gap:12px;border-top:1px solid var(--el-border-color-lighter);padding-top:16px}.target-heading,.target-actions,.target-status,.deployment-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.target-heading{justify-content:space-between}.target-heading>div{display:grid;gap:4px}.target-heading span,.target-status,.target-fields span,.script-identity{color:var(--el-text-color-secondary);font-size:12px}.target-fields{display:grid;grid-template-columns:150px 220px minmax(180px,1fr);gap:16px}.target-fields>label,.target-fields>div{display:grid;align-content:start;gap:7px}.script-identity{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 16px}.connection-fields{display:grid;grid-template-columns:1fr;gap:0}.deployment-actions{justify-content:flex-start}.deployment-steps{display:grid;gap:8px;padding:12px;border:1px solid var(--el-border-color-lighter);background:var(--el-fill-color-light);font-size:13px}.deployment-steps ol{margin:0;padding-left:22px}.deployment-steps li{margin:5px 0}.deployment-steps p{margin:0;color:var(--el-text-color-secondary)}.target-status{flex-wrap:wrap}.target-status>span:nth-of-type(2){margin-left:12px}.test-message{margin:0;color:var(--el-text-color-regular);font-size:13px}.test-diagnostic{display:grid;gap:4px;margin:0;padding:8px 10px;background:var(--el-fill-color-light);color:var(--el-text-color-regular);font-size:12px}.target-actions{justify-content:flex-end}code{overflow-wrap:anywhere}@media(max-width:720px){.target-fields,.script-identity{grid-template-columns:1fr}.target-heading{align-items:flex-start;flex-direction:column}.target-actions{justify-content:flex-start}}
</style>
