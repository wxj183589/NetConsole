<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import {
  getTracksideApTask,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
} from '../../api/tracksideApBusiness'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import { t } from '../../i18n/runtime'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import type {
  TracksideApBusinessPage,
  TracksideApBusinessRow,
  TracksideApTask,
  TracksideApUpdateRequest,
} from '../../types/tracksideApBusiness'
import { displayInterfaceName } from '../../utils/interfaceName'
import {
  isTracksideApBusinessArtifactTask,
  TRACKSIDE_AP_BUSINESS_EXPORT_ACTION,
} from './tracksideApBusinessArtifact'
import {
  displayLldpStatus,
  displayPowerThreshold,
  displaySwitchVendor,
  displayTracksideValue,
  tracksideOpticalPresentation,
} from './tracksideApBusinessDisplay'

const storageKey = 'netconsole.trackside-ap.last-task'
const activeStates = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'QUEUED', 'CANCELLING'])
const businessTaskActions = new Set(['trackside_ap_optical_update', TRACKSIDE_AP_BUSINESS_EXPORT_ACTION])
const userSelectedExport = useUserSelectedExport()
const initialLoading = ref(false)
const refreshing = ref(false)
const taskSubmitting = ref(false)
const pendingScopeKey = ref('')
const error = ref('')
const taskNotice = ref('')
const taskNoticeType = ref<'success' | 'info' | 'warning' | 'error'>('info')
const page = ref<TracksideApBusinessPage | null>(null)
const task = ref<TracksideApTask | null>(null)
const filters = reactive({ station: '', query: '', optical_anomaly_only: false, page: 1, page_size: 50 })
let pollTimer: number | undefined
let taskNoticeTimer: number | undefined
let loadGeneration = 0

const businessColumns: NcTableColumn<TracksideApBusinessRow>[] = [
  { key: 'site', label: '站点', valueType: 'name', fixed: 'left' },
  { key: 'device_name', label: '车站交换机', valueType: 'name', fixed: 'left' },
  { key: 'switch_vendor', label: '交换机厂商', valueType: 'name', displayValue: (row) => displaySwitchVendor(row.switch_vendor) },
  { key: 'interface_name', label: '接口', valueType: 'port', displayValue: (row) => displayTracksideValue(displayInterfaceName(row.interface_name)) },
  { key: 'lldp_match_status', label: 'LLDP 状态', valueType: 'status', displayValue: (row) => displayLldpStatus(row.lldp_match_status) },
  { key: 'link_status', label: '链路', valueType: 'status' },
  { key: 'port_type', label: '端口类型', valueType: 'status', width: 100 },
  { key: 'description', label: '描述', valueType: 'description', width: 90, maxWidth: 120, align: 'center', headerAlign: 'center', stretch: 'none', showOverflowTooltip: true },
  { key: 'pvid', label: 'PVID', valueType: 'number', displayValue: (row) => displayTracksideValue(row.pvid) },
  { key: 'vlan', label: 'VLAN', displayValue: (row) => displayTracksideValue(row.vlan) },
  { key: 'switch_rx_power', label: '本端 Rx (dBm)', valueType: 'number' },
  { key: 'switch_tx_power', label: '本端 Tx (dBm)', valueType: 'number' },
  { key: 'switch_rx_low_alarm', label: 'Rx 门限', displayValue: (row) => displayPowerThreshold(row.switch_rx_low_alarm, row.switch_rx_high_alarm) },
  { key: 'switch_tx_low_alarm', label: 'Tx 门限', displayValue: (row) => displayPowerThreshold(row.switch_tx_low_alarm, row.switch_tx_high_alarm) },
  { key: 'switch_optical_status', label: '模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac', stretch: 'priority' },
  { key: 'ap_name', label: '当前轨旁 AP', valueType: 'name' },
  { key: 'ap_rx_power', label: '对端 Rx (dBm)', valueType: 'number' },
  { key: 'ap_tx_power', label: '对端 Tx (dBm)', valueType: 'number' },
  { key: 'ap_optical_status', label: 'AP 模块状态', valueType: 'status', cellKind: 'tag' },
  { key: 'optical_severity', label: '综合', valueType: 'status', cellKind: 'tag' },
  { key: 'updated_at', label: '更新时间', valueType: 'datetime' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['更新站点', '更新 AP'] },
]
const updateTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === 'trackside_ap_optical_update')
const exportTaskRunning = computed(() => isActiveTask(task.value) && task.value?.action === TRACKSIDE_AP_BUSINESS_EXPORT_ACTION)
const updateFeatureEnabled = computed(() => isFeatureEnabled('web.rail_trackside_ap_business_update') && isFeatureEnabled('web.rail_task_control'))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function clearTaskNotice(): void {
  if (taskNoticeTimer !== undefined) window.clearTimeout(taskNoticeTimer)
  taskNoticeTimer = undefined
  taskNotice.value = ''
  taskNoticeType.value = 'info'
}
function setTaskNotice(message: string, type: 'success' | 'info' | 'warning' | 'error' = 'info', autoHideMs = 0): void {
  clearTaskNotice()
  taskNotice.value = message
  taskNoticeType.value = type
  if (autoHideMs > 0) taskNoticeTimer = window.setTimeout(clearTaskNotice, autoHideMs)
}
function rememberTask(value: TracksideApTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function isActiveTask(value: TracksideApTask | null): boolean { return Boolean(value && activeStates.has(value.status)) }
function cleanIdentity(value: string): string { return String(value || '').trim() }
function handleStationChange(): void { filters.page = 1; void loadRows() }
function singleApUpdatePayload(row: TracksideApBusinessRow): TracksideApUpdateRequest | null {
  const apUuid = cleanIdentity(row.ap_uuid)
  if (apUuid) return { ap_uuid: apUuid }
  const apMac = cleanIdentity(row.ap_mac)
  if (apMac) return { ap_mac: apMac }
  const apName = cleanIdentity(row.ap_name)
  if (apName) return { ap_name: apName }
  return null
}
function hasApIdentity(row: TracksideApBusinessRow): boolean { return singleApUpdatePayload(row) !== null }
function summaryCount(summary: Record<string, unknown>, key: string): number {
  const value = Number(summary[key] ?? 0)
  return Number.isFinite(value) ? Math.max(0, value) : 0
}
function updateReasonLabel(value: string): string {
  const labels: Record<string, string> = {
    connection_incomplete: t('trackside.result.reason.connection_incomplete', '连接信息不完整'),
    no_device_connection: t('trackside.result.reason.no_device_connection', '未配置设备连接'),
    vendor_not_supported: t('trackside.result.reason.vendor_not_supported', '厂商暂不支持光衰采集'),
    unsupported_vendor: t('trackside.result.reason.vendor_not_supported', '厂商暂不支持光衰采集'),
    fit_ap_resource_failed: t('trackside.result.reason.fit_ap_resource_failed', 'FIT-AP 资源刷新失败'),
    cancelled: t('trackside.result.reason.cancelled', '采集已取消'),
    device_collection_failed: t('trackside.result.reason.device_collection_failed', '交换机采集失败'),
    fit_ap_collection_failed: t('trackside.result.reason.fit_ap_collection_failed', 'AP 光衰采集失败'),
  }
  return labels[value] || value
}
function resultMessage(key: string, fallback: string, values: Record<string, number | string> = {}): string {
  return Object.entries(values).reduce(
    (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)),
    t(key, fallback),
  )
}
function primaryFailureReason(summary: Record<string, unknown>): string {
  for (const key of ['failure_reason_counts', 'skipped_reason_counts']) {
    const counts = summary[key]
    if (!counts || typeof counts !== 'object' || Array.isArray(counts)) continue
    const reason = Object.entries(counts as Record<string, unknown>)
      .filter(([code, count]) => code !== 'no_station_switches' && Number.isFinite(Number(count)) && Number(count) > 0)
      .sort((left, right) => Number(right[1]) - Number(left[1]))[0]?.[0]
    if (reason) return updateReasonLabel(reason)
  }
  return ''
}
function updateFinishedNotice(value: TracksideApTask): { message: string; type: 'success' | 'info' | 'warning' | 'error'; autoHideMs: number } {
  const summary = value.result_summary || {}
  const status = String(summary.status || value.status || '').toUpperCase()
  const successCount = summaryCount(summary, 'success_count')
  const failedCount = summaryCount(summary, 'failed_count')
  const actionableSkippedCount = summaryCount(summary, 'actionable_skipped_count')
  const ignoredSkippedCount = summaryCount(summary, 'ignored_skipped_count')
  if (value.status === 'FAILED' || status === 'FAILED') {
    const notExecuted = actionableSkippedCount
      ? resultMessage('trackside.result.notice.not_executed_suffix', '，{count} 个目标未执行', { count: actionableSkippedCount })
      : ''
    const reason = primaryFailureReason(summary)
    const reasonText = reason
      ? resultMessage('trackside.result.notice.reason_suffix', '；主要原因：{reason}', { reason })
      : ''
    return { message: resultMessage('trackside.result.notice.failed', '轨旁 AP 光衰更新失败：成功 {success}，失败 {failed}{not_executed}{reason}，请在任务中心查看详情', { success: successCount, failed: failedCount, not_executed: notExecuted, reason: reasonText }), type: 'error', autoHideMs: 0 }
  }
  if (value.status === 'CANCELLED' || status === 'CANCELLED') return { message: t('trackside.result.notice.cancelled', '轨旁 AP 光衰更新已取消，请在任务中心查看详情'), type: 'warning', autoHideMs: 0 }
  if (status === 'NO_TARGET') return { message: t('trackside.result.notice.no_target', '轨旁 AP 光衰更新未找到目标，请在任务中心查看详情'), type: 'info', autoHideMs: 4000 }
  if (failedCount > 0) return { message: resultMessage('trackside.result.notice.partial_failed', '轨旁 AP 光衰数据已刷新：成功 {success}，失败 {failed}，请在任务中心查看详情', { success: successCount, failed: failedCount }), type: 'warning', autoHideMs: 0 }
  if (actionableSkippedCount > 0) return { message: resultMessage('trackside.result.notice.not_executed', '轨旁 AP 光衰数据已刷新：成功 {success}，{not_executed} 个目标未执行，请在任务中心查看详情', { success: successCount, not_executed: actionableSkippedCount }), type: 'warning', autoHideMs: 0 }
  if (status === 'PARTIAL_SUCCESS') return { message: resultMessage('trackside.result.notice.partial', '轨旁 AP 光衰数据已刷新：成功 {success}，业务结果为部分成功，请在任务中心查看详情', { success: successCount }), type: 'warning', autoHideMs: 0 }
  const ignored = ignoredSkippedCount
    ? resultMessage('trackside.result.notice.ignored_suffix', '；另有 {count} 项不适用或已忽略', { count: ignoredSkippedCount })
    : ''
  return { message: resultMessage('trackside.result.notice.success', '轨旁 AP 光衰数据已刷新：成功 {success}，失败 0{ignored}', { success: successCount, ignored }), type: 'success', autoHideMs: 4000 }
}
function handleTerminalTask(value: TracksideApTask | null): void {
  if (!value) return
  if (value.action === 'trackside_ap_optical_update') {
    const notice = updateFinishedNotice(value)
    if (value.status === 'COMPLETED') {
      void loadRows().then((succeeded) => {
        if (succeeded) setTaskNotice(notice.message, notice.type, notice.autoHideMs)
      })
      return
    }
    if (!isActiveTask(value)) setTaskNotice(notice.message, notice.type, notice.autoHideMs)
    return
  }
  if (isTracksideApBusinessArtifactTask(value)) {
    if (value.status === 'COMPLETED') {
      setTaskNotice('轨旁 AP 业务表格已生成，正在写入用户预选位置', 'success', 4000)
      return
    }
    if (value.status === 'FAILED') setTaskNotice('轨旁 AP 业务导出失败，请在任务中心查看原因', 'error')
    else if (value.status === 'CANCELLED') setTaskNotice('轨旁 AP 业务导出已取消，请在任务中心查看详情', 'warning')
  }
}

function poll(): void {
  stopPolling()
  if (!task.value || !isActiveTask(task.value)) {
    handleTerminalTask(task.value)
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getTracksideApTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '轨旁 AP 任务状态读取失败') }
  }, 1000)
}

async function loadRows(reset = false): Promise<boolean> {
  if (reset) filters.page = 1
  const generation = ++loadGeneration
  const selectedStation = cleanIdentity(filters.station)
  const firstLoad = page.value === null
  if (firstLoad) initialLoading.value = true
  else refreshing.value = true
  error.value = ''
  let succeeded = false
  try {
    const nextPage = await listTracksideApBusiness({ ...filters })
    if (generation === loadGeneration) {
      page.value = nextPage
      succeeded = true
    }
  } catch (reason) {
    if (generation === loadGeneration) error.value = failure(reason, '轨旁 AP 业务加载失败')
  } finally {
    if (generation === loadGeneration) {
      initialLoading.value = false
      refreshing.value = false
    }
  }
  if (succeeded && selectedStation && !(page.value?.station_options || []).includes(selectedStation)) {
    filters.station = ''
    filters.page = 1
    void loadRows(true)
  }
  return succeeded
}

async function startTask(factory: () => Promise<TracksideApTask>, fallback: string, scopeKey: string, notice = '任务已提交，可通过顶部任务入口查看进度'): Promise<void> {
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true; error.value = ''; clearTaskNotice()
  try {
    const started = await factory()
    rememberTask(started)
    setTaskNotice(notice, 'info')
    poll()
  }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { taskSubmitting.value = false; pendingScopeKey.value = '' }
}

function updateAll(): void { void startTask(() => startTracksideApUpdate({}), '轨旁 AP 光衰更新启动失败', 'update:all') }
function updateStation(row: TracksideApBusinessRow): void { void startTask(() => startTracksideApUpdate({ station: row.site }), '站点更新启动失败', `update:station:${row.site}`) }
function updateAp(row: TracksideApBusinessRow): void {
  const payload = singleApUpdatePayload(row)
  if (!payload) { error.value = '缺少 AP 身份，无法定向更新'; return }
  const target = cleanIdentity(row.ap_name) || cleanIdentity(row.ap_mac) || cleanIdentity(row.ap_uuid)
  const scopeValue = payload.ap_uuid || payload.ap_mac || payload.ap_name || target
  void startTask(
    () => startTracksideApUpdate(payload),
    'AP 更新启动失败',
    `update:ap:${scopeValue}`,
  )
}
async function exportBusiness(): Promise<void> {
  const scopeKey = 'export:business'
  if (pendingScopeKey.value === scopeKey) return
  pendingScopeKey.value = scopeKey
  taskSubmitting.value = true
  error.value = ''
  clearTaskNotice()
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.trackside_business',
      suggestedName: `轨旁AP业务-${exportTimestamp()}.xlsx`,
      submit: startTracksideApBusinessExport,
    })
    if (result.status === 'cancelled') return
    rememberTask(result.task)
    setTaskNotice('导出任务已提交，完成后将写入所选位置', 'info')
    poll()
  } catch (reason) {
    error.value = failure(reason, '轨旁 AP 业务导出启动失败')
  } finally {
    taskSubmitting.value = false
    pendingScopeKey.value = ''
  }
}

function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}

async function recoverTasks(): Promise<void> {
  if (!isFeatureEnabled('web.rail_task_control')) return
  try {
    const rows = (await recoverTracksideApTasks()).filter((item) => businessTaskActions.has(item.action))
    const saved = localStorage.getItem(storageKey) || ''
    const savedTask = rows.find((item) => item.task_id === saved)
    const activeUpdate = rows.find((item) => item.action === 'trackside_ap_optical_update' && isActiveTask(item))
    const activeAny = rows.find((item) => isActiveTask(item))
    const recovered = savedTask && isActiveTask(savedTask) ? savedTask : activeUpdate || activeAny || null
    rememberTask(recovered)
    if (recovered) setTaskNotice('检测到正在运行的轨旁 AP 任务，可通过顶部任务入口查看进度', 'info')
    else clearTaskNotice()
    poll()
  } catch (reason) { error.value = failure(reason, '轨旁 AP 任务恢复失败') }
}

onMounted(() => { void Promise.all([loadRows(), recoverTasks()]) })
onBeforeUnmount(() => { stopPolling(); clearTaskNotice() })
</script>

<template>
  <section class="trackside-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · TRACKSIDE AP</p><h1>轨旁 AP 业务</h1><p>交换机端口、当前 AP、光功率与异常状态来自正式设备事实和轨旁业务维护规则。</p></div>
      <div class="actions">
        <el-button :loading="refreshing" :disabled="initialLoading" @click="loadRows()">刷新</el-button>
        <el-button
          type="primary"
          :loading="taskSubmitting"
          :disabled="updateTaskRunning || !updateFeatureEnabled"
          @click="updateAll"
        >更新全部光衰</el-button>
        <el-button
          :loading="taskSubmitting"
          :disabled="exportTaskRunning || !isFeatureEnabled('web.rail_trackside_ap_business_export') || !isFeatureEnabled('web.rail_task_control')"
          @click="exportBusiness"
        >导出表格</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="true" @close="error = ''"><el-button link @click="recoverTasks">恢复任务</el-button></el-alert>
    <el-alert v-if="taskNotice" :title="taskNotice" :type="taskNoticeType" show-icon :closable="taskNoticeType === 'error'" @close="clearTaskNotice" />
    <div v-if="page" class="summary-grid">
      <article><span>站点交换机</span><strong>{{ page.device_count }}</strong></article><article><span>候选 AP 端口</span><strong>{{ page.candidate_interface_count }}</strong></article><article><span>光衰异常</span><strong>{{ page.optical_abnormal_count }}</strong></article><article><span>FIT-AP 资源</span><strong>{{ page.fit_ap_resource_count }}</strong></article><article><span>查询 / 构建</span><strong>{{ page.query_ms }} / {{ page.build_ms }} ms</strong></article>
    </div>
    <div class="content-card">
      <div class="toolbar">
        <el-input v-model="filters.query" clearable placeholder="交换机、接口、AP、MAC" @keyup.enter="loadRows(true)" />
        <el-select
          v-model="filters.station"
          class="station-select"
          clearable
          filterable
          placeholder="全部站点"
          :title="filters.station || '全部站点'"
          @change="handleStationChange"
        >
          <el-option
            v-for="station in page?.station_options || []"
            :key="station"
            :label="station"
            :value="station"
            :title="station"
          />
        </el-select>
        <el-checkbox v-model="filters.optical_anomaly_only">仅光衰异常</el-checkbox>
        <el-button type="primary" :loading="refreshing" :disabled="initialLoading" @click="loadRows(true)">查询</el-button>
        <span v-if="refreshing" class="refresh-indicator">正在刷新，当前数据保持显示</span>
        <span class="suspended-filter-hint">已自动隐藏暂停使用设备</span>
      </div>
      <div class="business-table-host">
        <NcDataTable
          v-loading="initialLoading"
          table-id="trackside-ap-business"
          route-key="/rail-transit/trackside-ap-business"
          :data="page?.items || []"
          :columns="businessColumns"
          class="business-table"
          height="100%"
          :empty-text="page?.empty_reason || '暂无轨旁 AP 业务数据'"
        >
          <template #cell-switch_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_rx_power) }}</span></template>
          <template #cell-switch_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ displayTracksideValue(row.switch_tx_power) }}</span></template>
          <template #cell-switch_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.switch_optical_status).tagType" :class="tracksideOpticalPresentation(row.switch_optical_status).className">{{ tracksideOpticalPresentation(row.switch_optical_status).label }}</el-tag></template>
          <template #cell-ap_rx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_rx_power) }}</span></template>
          <template #cell-ap_tx_power="{ row }"><span :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ displayTracksideValue(row.ap_tx_power) }}</span></template>
          <template #cell-ap_optical_status="{ row }"><el-tag :type="tracksideOpticalPresentation(row.ap_optical_status).tagType" :class="tracksideOpticalPresentation(row.ap_optical_status).className">{{ tracksideOpticalPresentation(row.ap_optical_status).label }}</el-tag></template>
          <template #cell-optical_severity="{ row }"><el-tag :type="tracksideOpticalPresentation(row.optical_severity).tagType" :class="tracksideOpticalPresentation(row.optical_severity).className">{{ tracksideOpticalPresentation(row.optical_severity).label }}</el-tag></template>
          <template #cell-actions="{ row }"><el-button link type="primary" :disabled="updateTaskRunning || !row.site || !updateFeatureEnabled" @click="updateStation(row)">更新站点</el-button><el-button link type="primary" :title="hasApIdentity(row) ? '' : '缺少 AP 身份，无法定向更新'" :disabled="updateTaskRunning || !hasApIdentity(row) || !updateFeatureEnabled" @click="updateAp(row)">更新 AP</el-button></template>
        </NcDataTable>
      </div>
      <div class="pagination"><span>共 {{ page?.total || 0 }} 条</span><el-pagination :current-page="page?.page || filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="page?.total || 0" @current-change="(value: number) => { filters.page = value; loadRows() }" /></div>
    </div>
  </section>
</template>

<style scoped>
.trackside-page{display:flex;height:100%;min-height:0;min-width:0;flex-direction:column;gap:16px}.page-heading,.actions,.toolbar,.pagination{display:flex;align-items:center;gap:12px}.page-heading,.pagination{flex:none;justify-content:space-between}.page-heading h1{margin:2px 0 6px}.page-heading p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:0}.actions,.toolbar{flex-wrap:wrap}.summary-grid{display:grid;flex:none;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.summary-grid article,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.summary-grid article{padding:13px}.summary-grid span{color:var(--el-text-color-secondary);font-size:12px}.summary-grid strong{display:block;margin-top:6px;font-size:22px}.content-card{display:flex;min-height:0;min-width:0;flex:1;flex-direction:column;padding:14px 16px;overflow:hidden}.business-table-host{min-height:0;min-width:0;flex:1}.toolbar{flex:none;margin-bottom:12px}.toolbar .el-input{width:230px}.station-select{width:260px}.refresh-indicator{color:var(--el-color-primary);font-size:13px}.suspended-filter-hint{color:var(--el-text-color-secondary);font-size:12px}.pagination{padding-top:12px}.optical-normal{color:var(--el-color-success)}.optical-notice,.optical-warning{color:var(--el-color-warning)}.optical-alarm,.optical-link-abnormal,.optical-link-down,.optical-no-light,.optical-offline{color:var(--el-color-danger);font-weight:600}.optical-no-module,.optical-missing,.optical-skipped,.optical-not-collected,.optical-unknown{color:var(--el-text-color-secondary)}@media(max-width:1000px){.page-heading{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,minmax(130px,1fr))}}
</style>
