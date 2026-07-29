<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, CopyDocument, Delete } from '@element-plus/icons-vue'

import NcStatusTag from '../../components/NcStatusTag.vue'
import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import { t } from '../../i18n/runtime'
import {
  isTracksideApBusinessArtifactTask,
  saveTracksideApBusinessArtifact,
} from '../../views/rail-transit/tracksideApBusinessArtifact'

const store = useTaskStore()
const router = useRouter()
const props = withDefaults(defineProps<{
  modelValue: boolean
  taskId: string
  source?: 'notification' | 'global-list' | 'floating' | 'native' | 'job-center'
}>(), {
  source: 'global-list',
})
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  closed: []
  'load-error': [taskId: string, message: string]
}>()
const detailVisible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const lastSavedCapability = ref('')
const nativeActionError = ref('')
const followLatestLogs = ref(true)
const logContainer = ref<HTMLElement | null>(null)
let downloadGeneration = 0
let ownsDetailContext = false

function clearSavedCapability(): void {
  downloadGeneration += 1
  lastSavedCapability.value = ''
  nativeActionError.value = ''
}

const artifactDownloadLabel = computed(() => (
  isTracksideApBusinessArtifactTask(store.selected) ? '保存导出表格' : '另存 Artifact'
))
const selectedDetails = computed<Record<string, unknown>>(() => store.selected?.details || {})
const selectedResident = computed(() => isResidentTask(store.selected))
const historicalTextDamaged = computed(() => store.selected?.text_integrity === 'historical_corrupted')
const currentTextDamaged = computed(() => store.selected?.text_integrity === 'current_corrupted')
const unknownTextDamaged = computed(() => store.selected?.text_integrity === 'unknown_corrupted')
const selectedNeedsAcknowledgement = computed(() => Boolean(
  store.selected
  && !store.selected.acknowledged_at
  && (
    store.selected.status === 'FAILED'
    || store.selected.status === 'ABORTED'
    || store.selected.has_warning
  )
))
const selectedCanDismiss = computed(() => Boolean(
  store.selected
  && ['COMPLETED', 'FAILED', 'CANCELLED', 'ABORTED', 'STOPPED'].includes(store.selected.status)
  && !selectedNeedsAcknowledgement.value
))
const showCurrentProcessing = computed(() => {
  const details = selectedDetails.value
  const phase = String(details.phase || '')
  const event = String(details.event || '')
  return phase === 'fit_ap_optical' || event.startsWith('ap_') || Boolean(details.ap_name || details.ap_ip)
})
const currentPhaseLabel = computed(() => phaseLabel(String(selectedDetails.value.phase || store.selected?.stage || '')))
const currentApProgress = computed(() => {
  const completed = numberDetail('fit_ap_completed', numberDetail('completed', 0))
  const total = numberDetail('fit_ap_total', numberDetail('total', 0))
  return total ? `${completed} / ${total}` : '--'
})
const selectedBusinessStatus = computed(() => String(selectedDetails.value.status || '').toUpperCase())
const showTracksideBusinessResult = computed(() => (
  store.selected?.type === 'trackside_ap_optical_update'
  && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(store.selected.status)
  && ['SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'NO_TARGET', 'CANCELLED'].includes(selectedBusinessStatus.value)
))
const showPointTablePreviewResult = computed(() => (
  store.selected?.type === 'car_network_generate_point_table'
  && store.selected.status === 'COMPLETED'
  && Number.isFinite(Number(selectedDetails.value.nodes_count))
))
const businessStatusLabel = computed(() => ({
  SUCCESS: t('job_center.business_result.success', '成功'),
  PARTIAL_SUCCESS: t('job_center.business_result.partial_success', '部分成功'),
  FAILED: t('job_center.business_result.failed', '失败'),
  NO_TARGET: t('job_center.business_result.no_target', '未找到目标'),
  CANCELLED: t('job_center.business_result.cancelled', '已取消'),
}[selectedBusinessStatus.value] || selectedBusinessStatus.value))
const businessReasonRows = computed(() => {
  const rows: Array<{ key: string; label: string; count: number; category: string }> = []
  for (const [field, category] of [
    ['failure_reason_counts', t('job_center.business_result.failure_reason', '失败')],
    ['skipped_reason_counts', t('job_center.business_result.skipped_reason', '跳过')],
  ] as const) {
    const counts = selectedDetails.value[field]
    if (!counts || typeof counts !== 'object' || Array.isArray(counts)) continue
    for (const [key, value] of Object.entries(counts as Record<string, unknown>)) {
      const count = Number(value)
      if (Number.isFinite(count) && count > 0) rows.push({ key, label: reasonLabel(key), count, category })
    }
  }
  return rows
})
function isResidentTask(task: TaskItem | null | undefined): boolean {
  return task?.task_mode === 'resident' || task?.type === 'ac_mesh_link_resident_poll'
}

function residentProgressLabel(task: TaskItem): string {
  const count = Number(task.current || task.details?.poll_count || 0)
  if (['COMPLETED', 'STOPPED'].includes(task.status)) return `已正常停止 · 共完成 ${count} 次轮询`
  if (task.status === 'STOPPING') return `正在停止 · 已完成 ${count} 次轮询`
  return `常驻运行 · 已完成 ${count} 次轮询`
}

watch(
  () => [props.modelValue, props.taskId] as const,
  ([visible, taskId]) => {
    if (!visible) {
      if (ownsDetailContext) store.setDetailVisible(false)
      ownsDetailContext = false
      clearSavedCapability()
      followLatestLogs.value = true
      return
    }
    const normalizedTaskId = taskId.trim()
    if (!normalizedTaskId) return
    ownsDetailContext = true
    store.setDetailVisible(true)
    void store.selectTask(normalizedTaskId).catch((cause) => {
      if (!props.modelValue || props.taskId.trim() !== normalizedTaskId) return
      const message = cause instanceof Error ? cause.message : '任务详情加载失败'
      emit('load-error', normalizedTaskId, message)
    })
  },
  { immediate: true },
)
watch(() => store.selected?.id, clearSavedCapability)
watch(() => store.logs.at(-1)?.sequence, () => {
  if (!followLatestLogs.value) return
  void nextTick(() => {
    const target = logContainer.value
    if (target) target.scrollTop = target.scrollHeight
  })
})

onBeforeUnmount(() => {
  clearSavedCapability()
  if (ownsDetailContext) store.setDetailVisible(false)
})

function formatTime(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainder = total % 60
  return hours ? `${hours}h ${minutes}m ${remainder}s` : minutes ? `${minutes}m ${remainder}s` : `${remainder}s`
}

async function copyText(value: string, success: string): Promise<void> {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success(success)
  } catch {
    ElMessage.error('复制失败，请手工选择文本')
  }
}

function acceptanceCommand(task: TaskItem): string {
  return `python -m scripts.maintenance.check_online_mr_session_state --task-id "${task.id}"`
}

function openOnlineMr(task: TaskItem): void {
  void router.push({ name: 'online-mr-analysis', query: { session_id: task.session_id } })
}

async function cancelSelected(): Promise<void> {
  clearSavedCapability()
  try { await store.requestCancel(); ElMessage.success('已请求停止任务') }
  catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : '停止任务失败') }
}

async function downloadArtifact(): Promise<void> {
  if (!store.selected?.artifact_download) return
  const taskId = store.selected.id
  clearSavedCapability()
  const generation = downloadGeneration
  const tracksideArtifact = isTracksideApBusinessArtifactTask(store.selected)
  const artifact = store.selected.artifact_download
  const result = tracksideArtifact
    ? await saveTracksideApBusinessArtifact(store.selected)
    : await downloadBackendResource({
      apiPath: artifact.api_path,
      query: artifact.query,
      suggestedName: artifact.display_name,
      ...(artifact.size_bytes >= 0 && /^[0-9a-f]{64}$/i.test(artifact.sha256 || '')
        ? {
            expectedSizeBytes: artifact.size_bytes,
            expectedSha256: artifact.sha256,
          }
        : {}),
    })
  if (generation !== downloadGeneration || store.selected?.id !== taskId || !detailVisible.value) return
  if (result.status === 'saved') {
    lastSavedCapability.value = result.capabilityId || ''
    if (!tracksideArtifact) ElMessage.success('Artifact 已保存')
  } else if (result.status === 'cancelled' && !tracksideArtifact) {
    ElMessage.warning('Artifact 已生成，但尚未保存到本地。')
  } else if (result.status === 'started' && !tracksideArtifact) {
    ElMessage.info('文件已交由浏览器下载，请在浏览器下载记录中查看。')
  } else if (result.status === 'failed' && !tracksideArtifact) ElMessage.error(result.error || 'Artifact 下载失败')
}

async function acknowledgeSelected(): Promise<void> {
  if (!store.selected || !selectedNeedsAcknowledgement.value) return
  try {
    await store.acknowledgeHistoryTask(store.selected.id)
    ElMessage.success(t('job_center.acknowledge.done', '任务已标记为已处理'))
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : t('job_center.acknowledge.failed', '标记失败'))
  }
}

async function dismissSelected(): Promise<void> {
  if (!store.selected || !selectedCanDismiss.value) return
  const taskId = store.selected.id
  try {
    await ElMessageBox.confirm(
      t('job_center.cleanup.dismiss_single', '仅从任务中心移除此记录，不会删除日志、采集文件或导出结果。'),
      t('job_center.cleanup.dismiss', '从列表移除'),
      {
        confirmButtonText: t('job_center.cleanup.dismiss_confirm', '移除'),
        cancelButtonText: t('job_center.cleanup.cancel', '取消'),
        type: 'warning',
      },
    )
    await store.dismissHistoryTask(taskId)
    detailVisible.value = false
    ElMessage.success(t('job_center.cleanup.dismissed', '任务记录已从列表移除'))
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '移除失败')
  }
}

function stringDetail(key: string, fallback = '--'): string {
  const value = selectedDetails.value[key]
  const text = value == null ? '' : String(value)
  return text || fallback
}

function numberDetail(key: string, fallback = 0): number {
  const value = Number(selectedDetails.value[key])
  return Number.isFinite(value) ? value : fallback
}

function phaseLabel(value: string): string {
  const labels: Record<string, string> = {
    fit_ap_optical: 'AP 侧光衰采集',
    switch_optical: '交换机侧光模块采集',
    aggregate: '结果聚合',
    persist: '数据库保存',
    'trackside_ap.fit_ap.plan': 'AP 侧目标统计',
    'trackside_ap.fit_ap.collect': 'AP 侧光衰采集',
    'trackside_ap.fit_ap.retry': 'AP 侧光衰重试',
    'trackside_ap.switch.collect': '交换机侧光模块采集',
    'trackside_ap.persist': '数据库保存',
  }
  return labels[value] || value || '--'
}

function reasonLabel(value: unknown): string {
  const code = String(value || '')
  const labels: Record<string, string> = {
    connect_timeout: '连接超时',
    auth_failed: '认证失败',
    command_failed: '命令执行失败',
    parse_failed: '光模块数据解析失败',
    no_optical_data: '未获取到光模块数据',
    offline: 'AP 离线',
    cancelled: '已取消',
    unexpected_error: '未知异常',
    log_write_failed: '日志写入失败',
    connection_incomplete: t('trackside.result.reason.connection_incomplete', '连接信息不完整'),
    no_device_connection: t('trackside.result.reason.no_device_connection', '未配置设备连接'),
    vendor_not_supported: t('trackside.result.reason.vendor_not_supported', '厂商暂不支持光衰采集'),
    unsupported_vendor: t('trackside.result.reason.vendor_not_supported', '厂商暂不支持光衰采集'),
    fit_ap_resource_failed: t('trackside.result.reason.fit_ap_resource_failed', 'FIT-AP 资源刷新失败'),
    no_station_switches: t('trackside.result.reason.no_station_switches', '本次无车站交换机采集目标'),
    device_collection_failed: t('trackside.result.reason.device_collection_failed', '交换机采集失败'),
    fit_ap_collection_failed: t('trackside.result.reason.fit_ap_collection_failed', 'AP 光衰采集失败'),
  }
  return labels[code] || code
}

function logLineClass(line: { level: string; details?: Record<string, unknown> }): string {
  const status = String(line.details?.status || '').toLowerCase()
  const event = String(line.details?.event || '').toLowerCase()
  if (status === 'failed') return 'error'
  if (status === 'success') return 'success'
  if (status === 'retrying' || event === 'ap_retry_started') return 'warning'
  if (line.level.toLowerCase() === 'error') return 'error'
  if (line.level.toLowerCase() === 'warning') return 'warning'
  return 'info'
}

function logStatusLabel(line: { type: string; details?: Record<string, unknown> }): string {
  const status = String(line.details?.status || '').toLowerCase()
  const event = String(line.details?.event || '').toLowerCase()
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'retrying' || event === 'ap_retry_started') return '重试'
  if (event === 'ap_started') return '开始'
  return line.type
}

function handleLogScroll(): void {
  const target = logContainer.value
  if (!target) return
  followLatestLogs.value = target.scrollHeight - target.scrollTop - target.clientHeight < 24
}

function nativeFailureMessage(action: 'open' | 'reveal', error = ''): string {
  if (error.includes('文件授权已过期')) return '文件授权已过期，请重新下载后再试'
  if (error.includes('文件授权')) return '文件授权已失效，请重新下载后再试'
  return action === 'open'
    ? '系统未能打开文件，请检查文件关联后重试'
    : '系统未能定位文件，请重新下载后再试'
}

async function runSavedAction(action: 'open' | 'reveal'): Promise<void> {
  const capabilityId = lastSavedCapability.value
  if (!capabilityId) return
  const generation = downloadGeneration
  nativeActionError.value = ''
  try {
    const adapter = getPlatformAdapter()
    const result = await (action === 'open'
      ? adapter.openPath(capabilityId)
      : adapter.showItemInFolder(capabilityId))
    if (generation !== downloadGeneration || capabilityId !== lastSavedCapability.value) return
    if (result.success) {
      ElMessage.success(action === 'open' ? '已请求系统打开文件' : '已在文件夹中定位')
      return
    }
    nativeActionError.value = nativeFailureMessage(action, result.error)
  } catch {
    if (generation !== downloadGeneration || capabilityId !== lastSavedCapability.value) return
    nativeActionError.value = nativeFailureMessage(action)
  }
  ElMessage.error(nativeActionError.value)
}

const openSaved = () => runSavedAction('open')
const revealSaved = () => runSavedAction('reveal')

function handleClosed(): void {
  emit('closed')
}
</script>

<template>
  <el-drawer
    v-model="detailVisible"
    title="任务详情"
    size="min(820px, 94vw)"
    append-to-body
    class="task-detail-drawer"
    data-testid="task-detail-drawer"
    :data-source="props.source"
    @closed="handleClosed"
  >
      <div
        v-if="store.detailLoading"
        v-loading="true"
        class="task-detail-loading"
        data-testid="task-detail-loading"
      >正在加载任务详情…</div>
      <template v-else-if="store.selected">
        <div class="detail-heading">
          <div><h2>{{ store.selected.name }}</h2><p>{{ store.selected.id }}</p></div>
          <div class="detail-status">
            <NcStatusTag :status="store.selected.status" />
            <strong v-if="showTracksideBusinessResult">{{ t('job_center.business_result.label', '业务结果') }}：{{ businessStatusLabel }}</strong>
          </div>
        </div>

        <el-alert v-if="store.detailError" :title="store.detailError" type="error" :closable="false" show-icon />
        <el-alert v-if="store.selected.error_summary" :title="store.selected.error_summary" :type="store.selected.status === 'FAILED' ? 'error' : 'warning'" :closable="false" show-icon class="detail-alert" />
        <el-alert
          v-if="historicalTextDamaged"
          title="该历史日志由旧版本生成，文字已经发生编码损坏；没有原始字节时无法恢复。"
          type="warning"
          :closable="false"
          show-icon
          class="detail-alert"
        />
        <el-alert
          v-if="currentTextDamaged"
          title="当前任务发生文本编码异常，请停止任务并查看应用日志。"
          type="error"
          :closable="false"
          show-icon
          class="detail-alert"
        />
        <el-alert
          v-if="unknownTextDamaged"
          title="该任务包含已损坏文字，但无法确认产生版本。"
          type="warning"
          :closable="false"
          show-icon
          class="detail-alert"
        />

        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务类型">{{ store.selected.type }}</el-descriptions-item>
          <el-descriptions-item label="状态 / 阶段">{{ store.selected.status }} / {{ store.selected.phase || '--' }}</el-descriptions-item>
          <el-descriptions-item label="进度">
            {{ selectedResident ? residentProgressLabel(store.selected) : `${store.selected.progress}%` }}
          </el-descriptions-item>
          <el-descriptions-item label="Owner / 执行端">{{ store.selected.owner || '--' }} / {{ store.selected.executor }}</el-descriptions-item>
          <el-descriptions-item label="局点">{{ store.selected.site_name || '--' }}</el-descriptions-item>
          <el-descriptions-item label="设备">{{ store.selected.device_name || '--' }}（{{ store.selected.device_id || '--' }}）</el-descriptions-item>
          <el-descriptions-item label="MR">{{ store.selected.mr_name || '--' }}</el-descriptions-item>
          <el-descriptions-item label="Agent">{{ store.selected.agent || '--' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(store.selected.started_time) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(store.selected.finished_time) }}</el-descriptions-item>
          <el-descriptions-item label="持续时间">{{ formatDuration(store.selected.duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item label="Mapping">{{ store.selected.mapping_state || '--' }}</el-descriptions-item>
          <el-descriptions-item label="错误码">{{ store.selected.error_code || '--' }}</el-descriptions-item>
          <el-descriptions-item label="消息">{{ store.selected.message || '--' }}</el-descriptions-item>
          <el-descriptions-item label="Session ID" :span="2"><code>{{ store.selected.session_id || '--' }}</code></el-descriptions-item>
          <template v-if="store.selected.type === 'ac_mesh_link_refresh'">
            <el-descriptions-item label="Mesh-Link 快照 ID">{{ store.selected.snapshot_id ?? '--' }}</el-descriptions-item>
            <el-descriptions-item label="链路记录数">{{ store.selected.records_count ?? '--' }}</el-descriptions-item>
            <el-descriptions-item label="Parser">{{ store.selected.parser_version || '--' }}</el-descriptions-item>
          </template>
          <template v-if="selectedResident">
            <el-descriptions-item label="连接状态">{{ stringDetail('connection_state') }}</el-descriptions-item>
            <el-descriptions-item label="轮询间隔">{{ numberDetail('poll_interval_seconds') }} 秒</el-descriptions-item>
            <el-descriptions-item label="轮询 / 成功 / 失败">
              {{ numberDetail('poll_count') }} / {{ numberDetail('success_count') }} / {{ numberDetail('failure_count') }}
            </el-descriptions-item>
            <el-descriptions-item label="重连 / 连续失败">
              {{ numberDetail('reconnect_count') }} / {{ numberDetail('consecutive_failures') }}
            </el-descriptions-item>
            <el-descriptions-item label="最近成功">{{ formatTime(stringDetail('last_success_at', '')) }}</el-descriptions-item>
            <el-descriptions-item label="下次轮询">{{ formatTime(stringDetail('next_poll_at', '')) }}</el-descriptions-item>
            <el-descriptions-item label="最近快照">
              {{ stringDetail('latest_snapshot_id') }} · {{ numberDetail('latest_snapshot_record_count') }} 条
            </el-descriptions-item>
            <el-descriptions-item label="心跳">{{ formatTime(stringDetail('heartbeat_at', '')) }}</el-descriptions-item>
            <el-descriptions-item v-if="selectedDetails.last_error_message" label="最近异常" :span="2">
              {{ stringDetail('last_error_message') }}
            </el-descriptions-item>
          </template>
        </el-descriptions>

        <section v-if="showPointTablePreviewResult" class="business-result">
          <div class="current-heading"><h3>点表预览结果</h3><strong>等待用户保存</strong></div>
          <div class="current-grid">
            <article><span>生成节点数</span><strong>{{ numberDetail('generated_nodes_count', numberDetail('nodes_count')) }}</strong></article>
            <article><span>当前列车</span><strong>{{ stringDetail('target_train_display', stringDetail('target_train')) }}</strong></article>
            <article class="wide"><span>结果说明</span><strong>{{ stringDetail('preview_message', '已生成点表预览，等待用户保存') }}</strong></article>
          </div>
        </section>

        <section v-if="showTracksideBusinessResult" class="business-result">
          <div class="current-heading">
            <h3>{{ t('job_center.business_result.label', '业务结果') }}</h3>
            <strong>{{ t('job_center.business_result.task_state', '任务状态') }}：{{ store.selected.status === 'COMPLETED' ? t('job_center.business_result.task_completed', '已完成') : store.selected.status }} · {{ businessStatusLabel }}</strong>
          </div>
          <div class="current-grid">
            <article><span>{{ t('job_center.business_result.success', '成功') }}</span><strong>{{ numberDetail('success_count') }}</strong></article>
            <article><span>{{ t('job_center.business_result.failed', '失败') }}</span><strong>{{ numberDetail('failed_count') }}</strong></article>
            <article><span>{{ t('job_center.business_result.not_executed', '未执行') }}</span><strong>{{ numberDetail('actionable_skipped_count') }}</strong></article>
            <article><span>{{ t('job_center.business_result.ignored', '不适用 / 已忽略') }}</span><strong>{{ numberDetail('ignored_skipped_count') }}</strong></article>
          </div>
          <ul v-if="businessReasonRows.length" class="business-reasons">
            <li v-for="row in businessReasonRows" :key="`${row.category}:${row.key}`">
              <span>{{ row.category }} · {{ row.label }}</span><strong>{{ row.count }}</strong>
            </li>
          </ul>
        </section>

        <section v-if="showCurrentProcessing" class="current-processing">
          <div class="current-heading">
            <h3>当前处理</h3>
            <NcStatusTag :status="store.selected.status" />
          </div>
          <div class="current-grid">
            <article><span>当前阶段</span><strong>{{ currentPhaseLabel }}</strong></article>
            <article><span>当前 AP</span><strong>{{ stringDetail('ap_name') }}</strong></article>
            <article><span>AP IP</span><strong>{{ stringDetail('ap_ip') }}</strong></article>
            <article><span>归属站点</span><strong>{{ stringDetail('station') }}</strong></article>
            <article><span>当前轮次</span><strong>第 {{ numberDetail('round', 1) }} 轮</strong></article>
            <article><span>AP 进度</span><strong>{{ currentApProgress }}</strong></article>
            <article><span>成功 / 失败</span><strong>{{ numberDetail('success_count') }} / {{ numberDetail('failed_count') }}</strong></article>
            <article><span>并发 / 已运行</span><strong>{{ numberDetail('effective_concurrency') || '--' }} / {{ formatDuration(store.selected.duration_seconds) }}</strong></article>
            <article v-if="selectedDetails.reason_code || selectedDetails.error_message" class="wide danger">
              <span>失败原因</span>
              <strong>{{ reasonLabel(selectedDetails.reason_code) || stringDetail('error_message') }}</strong>
            </article>
          </div>
        </section>

        <div v-if="store.selected.session_id" class="association-actions">
          <el-button type="primary" @click="openOnlineMr(store.selected)">查看 Online MR 收集分析</el-button>
          <el-button :icon="CopyDocument" @click="copyText(store.selected.session_id, 'Session ID 已复制')">复制 Session ID</el-button>
          <el-button :icon="CopyDocument" @click="copyText(acceptanceCommand(store.selected), '验收命令已复制')">复制验收命令</el-button>
        </div>
        <div class="association-actions">
          <el-tooltip :content="store.selected.cancel_reason" :disabled="store.selected.cancellable"><span><el-button type="danger" :disabled="!store.selected.cancellable" @click="cancelSelected">停止 / 取消</el-button></span></el-tooltip>
          <el-tooltip :content="store.selected.retry_reason" :disabled="store.selected.retryable"><span><el-button :disabled="!store.selected.retryable">重试</el-button></span></el-tooltip>
          <el-tooltip :content="store.selected.artifact_reason" :disabled="Boolean(store.selected.artifact_download)"><span><el-button :disabled="!store.selected.artifact_download" @click="downloadArtifact">{{ artifactDownloadLabel }}</el-button></span></el-tooltip>
          <el-button
            v-if="selectedNeedsAcknowledgement"
            :icon="Check"
            @click="acknowledgeSelected"
          >{{ t('job_center.acknowledge.one', '标记为已处理') }}</el-button>
          <el-tooltip
            content="失败或告警任务需先标记为已处理；活动任务不能移除"
            :disabled="selectedCanDismiss"
          >
            <span>
              <el-button
                :icon="Delete"
                :disabled="!selectedCanDismiss"
                @click="dismissSelected"
              >{{ t('job_center.cleanup.dismiss', '从列表移除') }}</el-button>
            </span>
          </el-tooltip>
          <template v-if="lastSavedCapability">
            <el-button @click="openSaved">打开文件</el-button>
            <el-button @click="revealSaved">打开所在目录</el-button>
          </template>
        </div>
        <el-alert v-if="nativeActionError" :title="nativeActionError" type="error" :closable="false" show-icon class="native-action-error" />

        <section class="log-section">
          <div class="log-heading">
            <div><h3>任务日志 tail</h3><p>默认展开；每秒读取最后 300 条结构化事件。</p></div>
            <div class="log-actions">
              <el-switch v-model="followLatestLogs" active-text="跟随最新" inactive-text="暂停跟随" />
              <el-button @click="store.setLogsExpanded(!store.logsExpanded)">{{ store.logsExpanded ? '隐藏日志' : '显示日志' }}</el-button>
            </div>
          </div>
          <template v-if="store.logsExpanded">
            <el-alert v-if="store.logError" :title="store.logError" type="error" :closable="false" show-icon />
            <div ref="logContainer" class="task-log" @scroll="handleLogScroll">
              <div v-for="line in store.logs" :key="line.sequence" :class="['log-line', logLineClass(line)]">
                <time>{{ formatTime(line.time) }}</time><span>{{ logStatusLabel(line) }}</span><p>{{ line.message }}<small v-if="line.details?.reason_code"> · {{ reasonLabel(line.details.reason_code) }}</small></p>
              </div>
              <el-empty v-if="!store.logs.length && !store.logError" description="暂无日志" :image-size="68" />
            </div>
          </template>
        </section>
      </template>
      <el-result
        v-else-if="store.detailError"
        icon="error"
        title="任务详情加载失败"
        :sub-title="store.detailError"
      />
      <el-empty v-else description="未找到任务详情" />
  </el-drawer>
</template>

<style scoped>
.task-detail-loading { display: grid; min-height: 180px; place-items: center; color: var(--nc-text-secondary); }
.detail-heading h2, .log-heading h3 { margin: 0; }
.detail-heading p, .log-heading p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.detail-status { display: flex; align-items: center; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.detail-status strong { color: var(--nc-text-primary); font-size: 13px; }
.detail-alert { margin: 0 0 15px; }
.current-processing, .business-result { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--nc-divider); }
.current-heading, .log-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.current-heading h3 { margin: 0; font-size: 15px; }
.current-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.current-grid article { min-width: 0; padding: 10px 12px; background: var(--nc-bg-muted); border: 1px solid var(--nc-border); border-radius: 8px; }
.current-grid article.wide { grid-column: span 2; }
.current-grid article.danger { border-color: var(--nc-danger); }
.current-grid span { display: block; color: var(--nc-text-secondary); font-size: 12px; }
.current-grid strong { display: block; margin-top: 5px; overflow-wrap: anywhere; color: var(--nc-text-primary); font-size: 13px; font-weight: 600; }
.business-reasons { display: grid; gap: 8px; margin: 12px 0 0; padding: 0; list-style: none; }
.business-reasons li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; background: var(--nc-bg-muted); border: 1px solid var(--nc-border); border-radius: 8px; }
.business-reasons span { color: var(--nc-text-secondary); font-size: 12px; }
.association-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.native-action-error { margin-top: 12px; }
.log-section { margin-top: 22px; }
.log-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.task-log { min-height: 150px; max-height: 360px; padding: 12px; overflow: auto; color: var(--nc-text-code); background: var(--nc-bg-code); border-radius: 8px; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; }
.log-line { display: grid; grid-template-columns: 155px 90px 1fr; gap: 10px; padding: 4px 2px; border-bottom: 1px solid var(--nc-border-code); }
.log-line time, .log-line span { color: var(--nc-text-code-muted); }
.log-line p { margin: 0; overflow-wrap: anywhere; }
.log-line small { color: var(--nc-text-code-muted); }
.log-line.error p { color: var(--nc-text-code-danger); }
.log-line.warning p { color: var(--nc-text-code-warning); }
.log-line.success p { color: var(--nc-success); }
code { overflow-wrap: anywhere; font-family: Consolas, "Microsoft YaHei", monospace; }
@media (max-width: 1200px) {
  .current-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
