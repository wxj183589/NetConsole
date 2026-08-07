<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Document, Guide, Refresh } from '@element-plus/icons-vue'

import {
  listTracksideWpsTargets,
  migrateTracksideWpsLegacyBinding,
  probeTracksideWpsSheetOrder,
  probeTracksideWpsTarget,
  revalidateTracksideWpsDeployment,
  syncTestTracksideWpsTarget,
  testTracksideWpsTarget,
  updateTracksideWpsTarget,
} from '../../api/tracksideApBusiness'
import { useConfirm } from '../../components/feedback/useConfirm'
import type {
  WpsTracksideDiagnostic,
  WpsTracksideTarget,
  WpsTracksideTargetCode,
} from '../../types/tracksideApBusiness'
import { getPlatformAdapter } from '../../platform/runtime'
import { openWpsDocumentUrl } from './wpsDocumentLink'
import { wpsAirScriptSource, type WpsAirScriptKind } from './wpsAirScriptSources'

const props = defineProps<{
  modelValue: boolean
  targets: WpsTracksideTarget[]
}>()
const { confirm } = useConfirm()

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

interface RuntimeCapabilityItem {
  key: string
  label: string
  passed: boolean
  optional: boolean
}

const runtimeCapabilityLabels: Record<string, string> = {
  worksheet_enum: 'Sheet 枚举',
  worksheet_item: 'Sheet 定位',
  worksheet_create: 'Sheet 创建',
  scalar_value2: '单值写入与读回',
  matrix_value2: '二维数据写入与读回',
  used_range: '已用区域读取',
  clear_contents: '内容清除',
  entire_row_insert: '顶部整行插入',
  sheet_visibility: '系统 Sheet 隐藏',
}

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const localTargets = ref<WpsTracksideTarget[]>([])
const drafts = ref<TargetDraft[]>([])
const savingCode = ref<WpsTracksideTargetCode | ''>('')
const testingCode = ref<WpsTracksideTargetCode | ''>('')
const probingCode = ref<WpsTracksideTargetCode | ''>('')
const syncTestingCode = ref<WpsTracksideTargetCode | ''>('')
const sheetOrderProbingCode = ref<WpsTracksideTargetCode | ''>('')
const revalidatingCode = ref<WpsTracksideTargetCode | ''>('')
const upgradingBindingCode = ref<WpsTracksideTargetCode | ''>('')
const errorMessage = ref('')
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

function targetByCode(code: WpsTracksideTargetCode): WpsTracksideTarget | undefined {
  return localTargets.value.find((item) => item.target_code === code)
}

function targetDraftDirty(target: WpsTracksideTarget, draft: TargetDraft): boolean {
  return Boolean(
    draft.token.trim()
    || draft.enabled !== target.enabled
    || draft.timeout_seconds !== target.timeout_seconds
    || draft.document_open_url.trim() !== target.document_open_url
    || draft.webhook_url.trim() !== target.webhook_url
  )
}

function remoteIdentityMatches(target: WpsTracksideTarget): boolean {
  return Boolean(
    target.remote_identity_verified_at
    && target.remote_script_version === target.expected_script_version
    && target.remote_deployment_id === target.expected_deployment_id
    && target.remote_script_id === target.expected_script_id
  )
}

function diagnosticItems(target: WpsTracksideTarget): Array<{
  label: string
  diagnostic: WpsTracksideDiagnostic
}> {
  return [
    { label: '连接测试', diagnostic: target.connection_diagnostic || {} },
    { label: '写入核心能力', diagnostic: target.runtime_probe_diagnostic || {} },
    { label: '同步测试 Sheet', diagnostic: target.sync_test_diagnostic || {} },
    { label: 'Sheet 排序', diagnostic: target.sheet_order_probe_diagnostic || {} },
  ]
}

function runtimeCapabilityItems(diagnostic: WpsTracksideDiagnostic): RuntimeCapabilityItem[] {
  const core = diagnostic.core_capabilities || {}
  const optional = diagnostic.optional_capabilities || {}
  const legacy = Object.keys(core).length || Object.keys(optional).length ? {} : (diagnostic.capabilities || {})
  return Object.keys(runtimeCapabilityLabels).flatMap((key) => {
    const source = key in core ? core : key in optional ? optional : legacy
    if (!(key in source)) return []
    return [{
      key,
      label: runtimeCapabilityLabels[key],
      passed: Boolean(source[key]),
      optional: key in optional || key === 'sheet_visibility',
    }]
  })
}

function capabilityStatusType(item: RuntimeCapabilityItem): 'success' | 'warning' | 'danger' {
  if (item.passed) return 'success'
  return item.optional ? 'warning' : 'danger'
}

function capabilityStatusLabel(item: RuntimeCapabilityItem): string {
  if (item.passed) return '通过'
  return item.optional ? '告警' : '失败'
}

function targetTypeLabel(target: WpsTracksideTarget): string {
  return target.target_type === 'WPS_SMART_SHEET' ? '智能表格' : '普通在线表格'
}

function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'SUCCESS_WITH_WARNINGS') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

function statusLabel(status: string): string {
  if (status === 'SUCCESS') return '成功'
  if (status === 'SUCCESS_WITH_WARNINGS') return '通过（有警告）'
  if (status === 'FAILED') return '失败'
  return '未执行'
}

function bindingStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    UNBOUND: '未绑定',
    BOUND: '已绑定',
    LEGACY_BINDING_ID_MISMATCH: '旧版绑定标识',
    MISMATCH: '身份不一致',
    UNKNOWN: '未确认',
  }
  return labels[status] || status || '未确认'
}

function bindingStatusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'BOUND') return 'success'
  if (status === 'LEGACY_BINDING_ID_MISMATCH' || status === 'UNBOUND') return 'warning'
  if (status === 'MISMATCH') return 'danger'
  return 'info'
}

function matchStatusType(value: boolean | undefined): 'success' | 'danger' | 'info' {
  if (value === true) return 'success'
  if (value === false) return 'danger'
  return 'info'
}

function matchStatusLabel(value: boolean | undefined): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '未确认'
}

function identityMatch(
  target: WpsTracksideTarget,
  currentKey: keyof WpsTracksideDiagnostic,
  legacyKey?: keyof WpsTracksideDiagnostic,
): boolean | undefined {
  const diagnostic = target.connection_diagnostic || {}
  const current = diagnostic[currentKey]
  if (typeof current === 'boolean') return current
  const legacy = legacyKey ? diagnostic[legacyKey] : undefined
  return typeof legacy === 'boolean' ? legacy : undefined
}

function remoteIdentityValue(
  target: WpsTracksideTarget,
  key: keyof WpsTracksideDiagnostic,
  fallback = '未确认',
): string {
  const value = target.connection_diagnostic?.[key]
  return typeof value === 'string' && value ? value : fallback
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
    const result = await getPlatformAdapter().writeClipboardText(wpsAirScriptSource(code, kind))
    if (!result.success) throw new Error(result.error || '系统剪贴板不可用')
    ElMessage.success(kind === 'probe' ? '只读连接探针已复制' : '正式同步脚本已复制')
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '复制失败，请检查剪贴板权限')
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
  const target = targetByCode(code)
  if (savingCode.value || testingCode.value || sheetOrderProbingCode.value || revalidatingCode.value || upgradingBindingCode.value || !draft || !target) return false
  if (!targetDraftDirty(target, draft)) {
    if (!silent) ElMessage.info('当前配置没有变化')
    return true
  }
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
  if (testingCode.value || savingCode.value || sheetOrderProbingCode.value || revalidatingCode.value || upgradingBindingCode.value) return
  errorMessage.value = ''
  const saved = await saveTargetConfiguration(code, true)
  if (!saved) return
  const target = targetByCode(code)
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
    await reloadTargets()
    ElMessage.success(`${targetTypeLabel(target)}连接测试通过：${documentName}，脚本 ${scriptVersion}`)
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : '连接测试失败'
    errorMessage.value = message
    await reloadTargets().catch(() => undefined)
  } finally {
    testingCode.value = ''
  }
}

async function runtimeWriteProbe(code: WpsTracksideTargetCode): Promise<void> {
  if (probingCode.value || savingCode.value || testingCode.value || sheetOrderProbingCode.value || revalidatingCode.value || upgradingBindingCode.value) return
  probingCode.value = code
  errorMessage.value = ''
  try {
    const response = await probeTracksideWpsTarget(code)
    await reloadTargets()
    ElMessage.success(String(response.result.message || '运行时写入探针通过'))
  } catch (reason) {
    errorMessage.value = reason instanceof Error ? reason.message : '运行时写入探针失败'
    await reloadTargets().catch(() => undefined)
  } finally {
    probingCode.value = ''
  }
}

async function syncTestSheet(code: WpsTracksideTargetCode): Promise<void> {
  if (syncTestingCode.value || savingCode.value || testingCode.value || probingCode.value || sheetOrderProbingCode.value || revalidatingCode.value || upgradingBindingCode.value) return
  syncTestingCode.value = code
  errorMessage.value = ''
  try {
    const response = await syncTestTracksideWpsTarget(code)
    await reloadTargets()
    ElMessage.success(String(response.result.message || '同步测试 Sheet 通过'))
  } catch (reason) {
    errorMessage.value = reason instanceof Error ? reason.message : '同步测试 Sheet 失败'
    await reloadTargets().catch(() => undefined)
  } finally {
    syncTestingCode.value = ''
  }
}

async function sheetOrderProbe(code: WpsTracksideTargetCode): Promise<void> {
  if (sheetOrderProbingCode.value || savingCode.value || testingCode.value || probingCode.value || syncTestingCode.value || revalidatingCode.value || upgradingBindingCode.value) return
  sheetOrderProbingCode.value = code
  errorMessage.value = ''
  try {
    const response = await probeTracksideWpsSheetOrder(code)
    await reloadTargets()
    ElMessage.success(String(response.result.message || 'Sheet 排序探针通过'))
  } catch (reason) {
    errorMessage.value = reason instanceof Error ? reason.message : 'Sheet 排序探针失败'
    await reloadTargets().catch(() => undefined)
  } finally {
    sheetOrderProbingCode.value = ''
  }
}

async function revalidateDeployment(code: WpsTracksideTargetCode): Promise<void> {
  if (revalidatingCode.value || savingCode.value || testingCode.value || probingCode.value || syncTestingCode.value || sheetOrderProbingCode.value || upgradingBindingCode.value) return
  errorMessage.value = ''
  const saved = await saveTargetConfiguration(code, true)
  if (!saved) return
  const target = targetByCode(code)
  if (!target?.token_configured) {
    errorMessage.value = '请先输入脚本令牌并保存配置'
    return
  }
  revalidatingCode.value = code
  try {
    await revalidateTracksideWpsDeployment(code)
    await reloadTargets()
    ElMessage.success('当前部署已完成连接、写入能力和同步测试验证')
  } catch (reason) {
    errorMessage.value = reason instanceof Error ? reason.message : '当前部署重新验证失败'
    await reloadTargets().catch(() => undefined)
  } finally {
    revalidatingCode.value = ''
  }
}

async function migrateLegacyBinding(code: WpsTracksideTargetCode): Promise<void> {
  if (upgradingBindingCode.value || savingCode.value || testingCode.value || probingCode.value || syncTestingCode.value || sheetOrderProbingCode.value || revalidatingCode.value) return
  errorMessage.value = ''
  const saved = await saveTargetConfiguration(code, true)
  if (!saved) return
  const target = targetByCode(code)
  if (!target?.token_configured) {
    errorMessage.value = '请先输入脚本令牌并保存配置'
    return
  }
  if (target.binding_status !== 'LEGACY_BINDING_ID_MISMATCH') {
    errorMessage.value = '请先执行连接测试，只有业务身份全部一致的旧版 Binding ID 才能迁移'
    return
  }
  const accepted = await confirm({
    type: 'WARNING',
    title: '升级旧版绑定标识',
    message: [
      `当前文档：${target.target_name}（${target.expected_document_id}）`,
      `当前局点：${target.remote_site_name || target.remote_site_id || target.site_id}`,
      '业务：轨旁 AP 业务',
      `旧 Binding ID：${target.remote_binding_id || '未确认'}`,
      `新 Binding ID：${target.binding_id || '未生成'}`,
    ].join('\n'),
    detail: '仅更新 _NetConsoleSyncMeta.binding_id，不会创建、清空、移动或写入任何业务 Sheet。迁移后会自动执行连接测试、写入核心能力和同步测试 Sheet。',
    confirmText: '确认升级绑定标识',
    cancelText: '取消',
    width: '680px',
  })
  if (!accepted) return
  upgradingBindingCode.value = code
  try {
    const response = await migrateTracksideWpsLegacyBinding(code)
    await reloadTargets()
    ElMessage.success(String(response.result.message || '旧版绑定标识已迁移并完成三个部署验证'))
  } catch (reason) {
    errorMessage.value = reason instanceof Error ? reason.message : '旧版绑定标识迁移失败'
    await reloadTargets().catch(() => undefined)
  } finally {
    upgradingBindingCode.value = ''
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
            <span>当前局点：{{ row.target.site_id }} · 远端绑定：<el-tag size="small" :type="bindingStatusType(row.target.binding_status || 'UNKNOWN')">{{ bindingStatusLabel(row.target.binding_status || 'UNKNOWN') }}</el-tag></span>
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

        <el-alert
          v-if="row.target.binding_status === 'LEGACY_BINDING_ID_MISMATCH'"
          title="当前 WPS 文档仍使用 NetConsole 旧版绑定标识，业务归属与当前局点一致，可以安全升级绑定标识。"
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
          <span>当前远端脚本版本 <code>{{ row.target.remote_script_version || '未确认' }}</code></span>
          <span>当前远端部署 ID <code>{{ row.target.remote_deployment_id || '未确认' }}</code></span>
          <span>当前远端脚本 ID <code>{{ row.target.remote_script_id || '未确认' }}</code></span>
          <span>部署身份匹配 <el-tag size="small" :type="remoteIdentityMatches(row.target) ? 'success' : 'warning'">{{ remoteIdentityMatches(row.target) ? '是' : '否' }}</el-tag></span>
          <span>远端绑定局点 <code>{{ row.target.remote_site_name || row.target.remote_site_id || '未绑定' }}</code></span>
          <span>webhook 脚本 ID <code>{{ webhookScriptIdSummary(row.draft.webhook_url) }}</code></span>
          <span>本地 Binding ID <code>{{ row.target.binding_id || '未生成' }}</code></span>
          <span>远端 Binding ID <code>{{ row.target.remote_binding_id || '未绑定' }}</code></span>
          <span>远端文档 ID <code>{{ remoteIdentityValue(row.target, 'remote_document_id') }}</code></span>
          <span>远端业务 <code>{{ remoteIdentityValue(row.target, 'remote_business_key') }}</code></span>
          <span>远端目标代码 <code>{{ remoteIdentityValue(row.target, 'remote_target_code') }}</code></span>
          <span>远端目标类型 <code>{{ remoteIdentityValue(row.target, 'remote_target_type') }}</code></span>
          <span>Binding ID 匹配 <el-tag size="small" :type="matchStatusType(identityMatch(row.target, 'binding_id_match'))">{{ matchStatusLabel(identityMatch(row.target, 'binding_id_match')) }}</el-tag></span>
          <span>文档身份匹配 <el-tag size="small" :type="matchStatusType(identityMatch(row.target, 'document_identity_match', 'document_match'))">{{ matchStatusLabel(identityMatch(row.target, 'document_identity_match', 'document_match')) }}</el-tag></span>
          <span>局点身份匹配 <el-tag size="small" :type="matchStatusType(identityMatch(row.target, 'site_identity_match', 'site_match'))">{{ matchStatusLabel(identityMatch(row.target, 'site_identity_match', 'site_match')) }}</el-tag></span>
          <span>业务身份匹配 <el-tag size="small" :type="matchStatusType(identityMatch(row.target, 'business_identity_match', 'business_match'))">{{ matchStatusLabel(identityMatch(row.target, 'business_identity_match', 'business_match')) }}</el-tag></span>
          <span>目标代码匹配 <el-tag size="small" :type="matchStatusType(identityMatch(row.target, 'target_code_match'))">{{ matchStatusLabel(identityMatch(row.target, 'target_code_match')) }}</el-tag></span>
          <span>目标类型匹配 <el-tag size="small" :type="matchStatusType(identityMatch(row.target, 'target_type_match'))">{{ matchStatusLabel(identityMatch(row.target, 'target_type_match')) }}</el-tag></span>
          <span v-if="row.target.runtime_probe_script_id">最近探针脚本 ID <code>{{ row.target.runtime_probe_script_id }}</code></span>
          <span v-if="row.target.runtime_probe_script_version">最近探针脚本版本 <code>{{ row.target.runtime_probe_script_version }}</code></span>
          <span v-if="row.target.runtime_probe_deployment_id">最近探针部署 ID <code>{{ row.target.runtime_probe_deployment_id }}</code></span>
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
          <el-button v-if="row.target.target_type === 'WPS_STANDARD_SPREADSHEET'" :loading="probingCode === row.target.target_code" :disabled="Boolean(probingCode) || Boolean(sheetOrderProbingCode) || Boolean(savingCode) || Boolean(testingCode) || Boolean(revalidatingCode) || Boolean(upgradingBindingCode)" @click="runtimeWriteProbe(row.target.target_code)">测试写入能力</el-button>
          <el-button v-if="row.target.target_type === 'WPS_STANDARD_SPREADSHEET'" :loading="syncTestingCode === row.target.target_code" :disabled="Boolean(syncTestingCode) || Boolean(probingCode) || Boolean(sheetOrderProbingCode) || Boolean(savingCode) || Boolean(testingCode) || Boolean(revalidatingCode) || Boolean(upgradingBindingCode)" @click="syncTestSheet(row.target.target_code)">测试同步 Sheet</el-button>
          <el-button v-if="row.target.target_type === 'WPS_STANDARD_SPREADSHEET'" :loading="sheetOrderProbingCode === row.target.target_code" :disabled="Boolean(sheetOrderProbingCode) || Boolean(syncTestingCode) || Boolean(probingCode) || Boolean(savingCode) || Boolean(testingCode) || Boolean(revalidatingCode) || Boolean(upgradingBindingCode)" @click="sheetOrderProbe(row.target.target_code)">测试 Sheet 排序</el-button>
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
        <div class="operation-diagnostics">
          <div v-for="item in diagnosticItems(row.target)" :key="item.label" class="operation-diagnostic">
            <div class="diagnostic-heading">
              <strong>{{ item.label }}</strong>
              <el-tag size="small" :type="statusType(item.diagnostic.status || '')">{{ statusLabel(item.diagnostic.status || '') }}</el-tag>
              <span>{{ item.diagnostic.executed_at || '未执行' }}</span>
            </div>
            <span v-if="item.diagnostic.operation">操作：<code>{{ item.diagnostic.operation }}</code></span>
            <span v-if="item.diagnostic.script_version">脚本版本：<code>{{ item.diagnostic.script_version }}</code></span>
            <span v-if="item.diagnostic.deployment_id">部署 ID：<code>{{ item.diagnostic.deployment_id }}</code></span>
            <span v-if="item.diagnostic.script_id">脚本 ID：<code>{{ item.diagnostic.script_id }}</code></span>
            <span v-if="item.diagnostic.phase">阶段：{{ phaseLabel(item.diagnostic.phase) }}</span>
            <span v-if="item.diagnostic.http_status">HTTP 状态：{{ item.diagnostic.http_status }}</span>
            <span v-if="item.diagnostic.remote_error_code">WPS 错误码：{{ item.diagnostic.remote_error_code }}</span>
            <span v-if="item.diagnostic.message">{{ item.diagnostic.message }}</span>
            <span v-if="item.diagnostic.remote_message">原因：{{ item.diagnostic.remote_message }}</span>
            <span v-if="item.diagnostic.suggestion">建议：{{ item.diagnostic.suggestion }}</span>
            <div v-if="runtimeCapabilityItems(item.diagnostic).length" class="runtime-capabilities">
              <div v-for="capability in runtimeCapabilityItems(item.diagnostic)" :key="capability.key">
                <span>{{ capability.label }}</span>
                <el-tag size="small" :type="capabilityStatusType(capability)">{{ capabilityStatusLabel(capability) }}</el-tag>
              </div>
            </div>
            <span v-if="typeof item.diagnostic.full_replace_ready === 'boolean'">全量替换：{{ item.diagnostic.full_replace_ready ? '就绪' : '不可用' }}</span>
            <span v-if="typeof item.diagnostic.prepend_snapshot_ready === 'boolean'">顶部追加快照：{{ item.diagnostic.prepend_snapshot_ready ? '就绪' : '不可用' }}</span>
            <span v-if="typeof item.diagnostic.sheet_order_verified === 'boolean'">业务 Sheet 顺序：{{ item.diagnostic.sheet_order_verified ? '已验证' : '未通过' }}</span>
            <span v-if="item.diagnostic.expected_sheet_order?.length">预期顺序：{{ item.diagnostic.expected_sheet_order.join(' → ') }}</span>
            <span v-if="item.diagnostic.actual_sheet_order?.length">实际顺序：{{ item.diagnostic.actual_sheet_order.join(' → ') }}</span>
            <span v-for="warning in item.diagnostic.warnings || []" :key="`${warning.capability || 'warning'}:${warning.message || ''}`" class="capability-warning">
              告警：{{ warning.message || warning.capability }}
            </span>
          </div>
        </div>

        <div class="target-actions">
          <el-button
            v-if="row.target.target_type === 'WPS_STANDARD_SPREADSHEET' && row.target.binding_status === 'LEGACY_BINDING_ID_MISMATCH'"
            type="warning"
            :loading="upgradingBindingCode === row.target.target_code"
            :disabled="Boolean(upgradingBindingCode) || Boolean(revalidatingCode) || Boolean(savingCode) || Boolean(testingCode) || Boolean(probingCode) || Boolean(syncTestingCode) || Boolean(sheetOrderProbingCode)"
            @click="migrateLegacyBinding(row.target.target_code)"
          >升级旧版绑定标识</el-button>
          <el-button
            v-if="row.target.target_type === 'WPS_STANDARD_SPREADSHEET'"
            :icon="Refresh"
            :loading="revalidatingCode === row.target.target_code"
            :disabled="Boolean(revalidatingCode) || Boolean(savingCode) || Boolean(testingCode) || Boolean(probingCode) || Boolean(syncTestingCode) || Boolean(sheetOrderProbingCode) || Boolean(upgradingBindingCode)"
            @click="revalidateDeployment(row.target.target_code)"
          >重新验证当前部署</el-button>
          <el-button
            type="primary"
            :loading="savingCode === row.target.target_code"
            :disabled="Boolean(savingCode) || Boolean(testingCode) || Boolean(sheetOrderProbingCode) || Boolean(revalidatingCode) || Boolean(upgradingBindingCode)"
            @click="saveTargetConfiguration(row.target.target_code)"
          >保存此目标</el-button>
          <el-button
            :loading="testingCode === row.target.target_code"
            :disabled="Boolean(testingCode) || Boolean(savingCode) || Boolean(sheetOrderProbingCode) || Boolean(revalidatingCode) || Boolean(upgradingBindingCode)"
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
.wps-config{display:grid;gap:16px;max-height:70vh;overflow:auto;padding-right:4px}.wps-config :deep(.el-form-item){margin-bottom:14px}.wps-target{display:grid;gap:12px;border-top:1px solid var(--el-border-color-lighter);padding-top:16px}.target-heading,.target-actions,.target-status,.deployment-actions,.diagnostic-heading{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.target-heading{justify-content:space-between}.target-heading>div{display:grid;gap:4px}.target-heading span,.target-status,.target-fields span,.script-identity{color:var(--el-text-color-secondary);font-size:12px}.target-fields{display:grid;grid-template-columns:150px 220px minmax(180px,1fr);gap:16px}.target-fields>label,.target-fields>div{display:grid;align-content:start;gap:7px}.script-identity{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 16px}.connection-fields{display:grid;grid-template-columns:1fr;gap:0}.deployment-actions{justify-content:flex-start}.deployment-steps{display:grid;gap:8px;padding:12px;border:1px solid var(--el-border-color-lighter);background:var(--el-fill-color-light);font-size:13px}.deployment-steps ol{margin:0;padding-left:22px}.deployment-steps li{margin:5px 0}.deployment-steps p{margin:0;color:var(--el-text-color-secondary)}.target-status{flex-wrap:wrap}.target-status>span:nth-of-type(2){margin-left:12px}.operation-diagnostics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.operation-diagnostic{display:grid;align-content:start;gap:4px;padding:8px 10px;border:1px solid var(--el-border-color-lighter);color:var(--el-text-color-regular);font-size:12px}.diagnostic-heading>span{color:var(--el-text-color-secondary)}.runtime-capabilities{display:grid;gap:4px;margin-top:4px;padding-top:6px;border-top:1px solid var(--el-border-color-lighter)}.runtime-capabilities>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.capability-warning{color:var(--el-color-warning-dark-2)}.target-actions{justify-content:flex-end}code{overflow-wrap:anywhere}@media(max-width:720px){.target-fields,.script-identity,.operation-diagnostics{grid-template-columns:1fr}.target-heading{align-items:flex-start;flex-direction:column}.target-actions{justify-content:flex-start}}
</style>
