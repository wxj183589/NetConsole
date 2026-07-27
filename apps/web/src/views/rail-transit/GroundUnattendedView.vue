<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Box, Delete, Download, FolderOpened, Refresh, SwitchButton, VideoPause, VideoPlay } from '@element-plus/icons-vue'

import {
  deleteGroundArchive, getGroundArchive, getGroundProfile, getGroundStatus, getGroundTrain, groundArchiveSummaryDownloadRequest, listGroundArchives,
  getGroundHealth, listGroundDeepCollections, listGroundPingTargets, listGroundTimeline, listGroundTrains, requestGroundConfigCheck,
  openGroundArchiveDirectory, pauseGroundRun, resumeGroundRun, saveGroundProfile, setGroundTrainPriority, startGroundRun,
  stopAndArchiveGroundRun, stopGroundRun, saveGroundTrainPolicy, syncGroundInventory,
  checkGroundUdpPort, listLocalIpv4Addresses, recommendLocalSourceIp,
} from '../../api/groundUnattended'
import { NcDataTable, type NcTableColumn } from '../../components/table'
import { t } from '../../i18n/runtime'
import { downloadBackendResource } from '../../platform/runtime'
import type {
  GroundArchive, GroundDeepCollection, GroundPingTarget, GroundProfile, GroundStatus,
  GroundHealth, GroundTimelineEvent, GroundTrain,
  LocalIpv4Address, SourceIpRecommendation, UdpPortCheck,
} from '../../types/groundUnattended'

const activeTab = ref('overview')
const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const action = ref('')
const status = ref<GroundStatus | null>(null)
const profile = ref<GroundProfile | null>(null)
const trains = ref<GroundTrain[]>([])
const pingTargets = ref<GroundPingTarget[]>([])
const deepCollections = ref<GroundDeepCollection[]>([])
const timeline = ref<GroundTimelineEvent[]>([])
const archives = ref<GroundArchive[]>([])
const health = ref<GroundHealth | null>(null)
const localIpv4Addresses = ref<LocalIpv4Address[]>([])
const sourceRecommendation = ref<SourceIpRecommendation | null>(null)
const udpPortCheck = ref<UdpPortCheck | null>(null)
const networkLoading = ref(false)
const showAllAddresses = ref(false)
const selectedArchive = ref<GroundArchive | null>(null)
const selectedTrain = ref<GroundTrain | null>(null)
const archiveDialog = ref(false)
const trainDialog = ref(false)
const trainFilter = ref('')
const pingFilter = reactive({ query: '', endpoint: '', station: '', section: '', minLoss: 0 })
const timelineFilter = reactive({ trainId: '', eventType: '' })
let pollTimer: number | undefined
let disposed = false

const running = computed(() => Boolean(status.value && ['STARTING', 'RUNNING', 'PAUSED', 'STOPPING', 'FINALIZING', 'ARCHIVING'].includes(status.value.state)))
const filteredTrains = computed(() => {
  const needle = trainFilter.value.trim().toLocaleLowerCase()
  return needle ? trains.value.filter((row) => `${row.train_no} ${row.train_name} ${row.current_ap_name} ${row.station} ${row.section}`.toLocaleLowerCase().includes(needle)) : trains.value
})
const filteredPing = computed(() => pingTargets.value.filter((row) => {
  const needle = pingFilter.query.trim().toLocaleLowerCase()
  return (!needle || `${row.train_no} ${row.target_ip} ${row.current_ap_name}`.toLocaleLowerCase().includes(needle))
    && (!pingFilter.endpoint || row.mr_position_code === pingFilter.endpoint)
    && (!pingFilter.station || row.station.includes(pingFilter.station))
    && (!pingFilter.section || row.section.includes(pingFilter.section))
    && row.loss_rate_percent >= pingFilter.minLoss
}))
const selectedTrainCollection = computed(() => deepCollections.value.find((row) => row.train_id === selectedTrain.value?.train_id) ?? null)
const visibleIpv4Addresses = computed(() => localIpv4Addresses.value.filter((row) => showAllAddresses.value || !row.is_virtual))
const localIpv4Values = computed(() => new Set(localIpv4Addresses.value.map((row) => row.ipv4)))
const returnAddressIsLocal = computed(() => Boolean(profile.value?.syslog_server_ip && localIpv4Values.value.has(profile.value.syslog_server_ip)))
const listenAddressIsLocal = computed(() => Boolean(profile.value && (profile.value.udp_listen_host === '0.0.0.0' || localIpv4Values.value.has(profile.value.udp_listen_host))))
const locationStats = computed(() => ({
  ap: trains.value.filter((row) => String(row.location_match_level || '').startsWith('AP_')).length,
  station: trains.value.filter((row) => String(row.location_match_level || '').startsWith('STATION_')).length,
  unmatched: trains.value.filter((row) => row.location_match_level === 'UNMATCHED').length,
  excluded: trains.value.filter((row) => ['DEPOT', 'PARKING_LOT', 'STORAGE_TRACK'].includes(row.eligibility_status)).length,
}))

const trainColumns: NcTableColumn<GroundTrain>[] = [
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', fixed: 'left' },
  { key: 'eligibility_status', label: t('ground.eligibility', '正线判断'), valueType: 'status' },
  { key: 'location_match_level', label: '匹配等级', valueType: 'status', width: 130 },
  { key: 'exclusion_reason', label: t('ground.exclusion_reason', '排除原因'), valueType: 'description', minWidth: 220 },
  { key: 'raw_peer_ap_name', label: '原始 AP', valueType: 'name' },
  { key: 'resolved_ap_name', label: '解析后 AP', valueType: 'name' },
  { key: 'canonical_station_name', label: '规范站点', valueType: 'text' },
  { key: 'section', label: t('ground.section', '归属区间'), valueType: 'text' },
  { key: 'same_ap_duration_seconds', label: t('ground.same_ap_duration', '同 AP 停留'), valueType: 'duration', displayValue: (row) => duration(row.same_ap_duration_seconds) },
  { key: 'ct_status', label: 'CT 在线', valueType: 'status', displayValue: (row) => endpoint(row, 'CT')?.online_status },
  { key: 'cw_status', label: 'CW 在线', valueType: 'status', displayValue: (row) => endpoint(row, 'CW')?.online_status },
  { key: 'ct_ping', label: 'CT Ping', valueType: 'status', displayValue: (row) => endpoint(row, 'CT')?.ping_active ? 'PINGING' : 'STOPPED' },
  { key: 'cw_ping', label: 'CW Ping', valueType: 'status', displayValue: (row) => endpoint(row, 'CW')?.ping_active ? 'PINGING' : 'STOPPED' },
  { key: 'coverage_status', label: t('ground.coverage', '今日深度采集'), valueType: 'status' },
  { key: 'enabled', label: t('ground.enabled', '启用'), valueType: 'status', displayValue: (row) => row.enabled ? 'ENABLED' : 'DISABLED' },
  { key: 'syslog', label: 'WMESH Syslog', valueType: 'status', displayValue: (row) => `${endpoint(row, 'CT')?.syslog_status || 'WAITING'} / ${endpoint(row, 'CW')?.syslog_status || 'WAITING'}` },
  { key: 'updated_at', label: t('ground.updated_at', '最近更新时间'), valueType: 'datetime' },
  { key: 'actions', label: t('ground.actions', '操作'), valueType: 'actions', fixed: 'right', width: 154, hideable: false },
]
const pingColumns: NcTableColumn<GroundPingTarget>[] = [
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', fixed: 'left' },
  { key: 'mr_position_code', label: t('ground.mr_endpoint', 'MR 端点'), valueType: 'status' },
  { key: 'target_ip', label: t('ground.management_ip', '管理 IP'), valueType: 'ip' },
  { key: 'started_at', label: t('ground.started_at', '开始时间'), valueType: 'datetime' },
  { key: 'sent_count', label: t('ground.sent', '发送'), valueType: 'number' },
  { key: 'success_count', label: t('ground.success', '成功'), valueType: 'number' },
  { key: 'loss_count', label: t('ground.loss', '丢失'), valueType: 'number' },
  { key: 'loss_rate_percent', label: t('ground.loss_rate', '丢包率'), valueType: 'percentage', displayValue: (row) => `${row.loss_rate_percent.toFixed(2)}%` },
  { key: 'avg_rtt_ms', label: t('ground.avg_rtt', '平均 RTT'), valueType: 'number', displayValue: (row) => metric(row.avg_rtt_ms, 'ms') },
  { key: 'max_rtt_ms', label: t('ground.max_rtt', '最大 RTT'), valueType: 'number', displayValue: (row) => metric(row.max_rtt_ms, 'ms') },
  { key: 'continuous_loss_max_seconds', label: t('ground.longest_loss', '最长连续丢包'), valueType: 'duration', displayValue: (row) => `${row.continuous_loss_max_count} / ${row.continuous_loss_max_seconds.toFixed(1)}s` },
  { key: 'current_ap_name', label: t('ground.current_ap', '当前 AP'), valueType: 'name' },
  { key: 'station', label: t('ground.station', '站点'), valueType: 'text' },
  { key: 'section', label: t('ground.section', '区间'), valueType: 'text' },
  { key: 'updated_at', label: t('ground.updated_at', '更新时间'), valueType: 'datetime' },
]
const deepColumns: NcTableColumn<GroundDeepCollection>[] = [
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', fixed: 'left' },
  { key: 'status', label: t('ground.status', '完成状态'), valueType: 'status' },
  { key: 'queue_position', label: t('ground.queue_position', '队列位置'), valueType: 'number' },
  { key: 'scheduling_priority', label: t('ground.scheduling_priority', '调度优先级'), valueType: 'number' },
  { key: 'selection_reason', label: t('ground.selection_reason', '选择原因'), valueType: 'description', minWidth: 220 },
  { key: 'attempt_count', label: t('ground.attempts', '采集次数'), valueType: 'number' },
  { key: 'covered_rounds', label: t('ground.covered_rounds', '完成轮次'), valueType: 'number' },
  { key: 'started_at', label: t('ground.started_at', '采集开始'), valueType: 'datetime' },
  { key: 'valid_duration_minutes', label: t('ground.valid_duration', '有效时长'), valueType: 'duration', displayValue: (row) => `${row.valid_duration_minutes.toFixed(1)} min` },
  { key: 'ct_session_id', label: 'CT Session', valueType: 'text' },
  { key: 'cw_session_id', label: 'CW Session', valueType: 'text' },
  { key: 'failure_reason', label: t('ground.failure_reason', '失败原因'), valueType: 'error', minWidth: 220 },
  { key: 'updated_at', label: t('ground.updated_at', '更新时间'), valueType: 'datetime' },
]
const timelineColumns: NcTableColumn<GroundTimelineEvent>[] = [
  { key: 'ts', label: t('ground.time', '时间'), valueType: 'datetime', fixed: 'left' },
  { key: 'event_type', label: t('ground.event_type', '事件类型'), valueType: 'status' },
  { key: 'train_id', label: t('ground.train', '列车'), valueType: 'name' },
  { key: 'mr_id', label: t('ground.mr', 'MR'), valueType: 'text' },
  { key: 'title', label: t('ground.event', '事件'), valueType: 'name' },
  { key: 'message', label: t('ground.message', '说明'), valueType: 'description', minWidth: 260 },
  { key: 'severity', label: t('ground.severity', '级别'), valueType: 'status' },
]
const archiveColumns: NcTableColumn<GroundArchive>[] = [
  { key: 'run_date', label: t('ground.run_date', '运行日期'), valueType: 'datetime', fixed: 'left' },
  { key: 'actual_started_at', label: t('ground.actual_start', '实际开始'), valueType: 'datetime' },
  { key: 'actual_ended_at', label: t('ground.actual_end', '实际结束'), valueType: 'datetime' },
  { key: 'mainline_train_count', label: t('ground.mainline_trains', '正线车辆'), valueType: 'number' },
  { key: 'ping_target_count', label: t('ground.ping_targets', 'Ping 目标'), valueType: 'number' },
  { key: 'ping_sample_count', label: t('ground.ping_samples', 'Ping 样本'), valueType: 'number' },
  { key: 'covered_train_count', label: t('ground.covered_trains', '深度覆盖'), valueType: 'number' },
  { key: 'complete_session_count', label: t('ground.complete_sessions', '完整 Session'), valueType: 'number' },
  { key: 'partial_session_count', label: t('ground.partial_sessions', '部分 Session'), valueType: 'number' },
  { key: 'archive_size_bytes', label: t('ground.archive_size', '归档大小'), valueType: 'number', displayValue: (row) => bytes(row.archive_size_bytes) },
  { key: 'archive_status', label: t('ground.archive_status', '归档状态'), valueType: 'status' },
  { key: 'retention_until', label: t('ground.retention_until', '保留截止'), valueType: 'datetime' },
  { key: 'actions', label: t('ground.actions', '操作'), valueType: 'actions', fixed: 'right', width: 190, hideable: false },
]

async function loadAll(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const [nextStatus, nextProfile, nextTrains, nextPing, nextDeep, nextTimeline, nextArchives, nextHealth] = await Promise.all([
      getGroundStatus(), getGroundProfile(), listGroundTrains(), listGroundPingTargets(),
      listGroundDeepCollections(), listGroundTimeline(timelineFilter.trainId, timelineFilter.eventType), listGroundArchives(), getGroundHealth(),
    ])
    if (disposed) return
    status.value = nextStatus
    profile.value = nextProfile
    trains.value = nextTrains.items
    pingTargets.value = nextPing.items
    deepCollections.value = nextDeep.items
    timeline.value = nextTimeline.items
    archives.value = nextArchives.items
    health.value = nextHealth
  } catch (reason) {
    if (!silent) ElMessage.error(errorText(reason, t('ground.load_failed', '地面无人值守数据加载失败')))
  } finally {
    if (!silent) loading.value = false
  }
}
function schedulePoll(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(async () => {
    if (!document.hidden) await loadAll(true)
    if (!disposed) schedulePoll()
  }, 5000)
}
async function saveProfile(message = t('ground.profile_saved', '无人值守配置已保存，运行中配置在下一次调度周期生效')): Promise<void> {
  if (!profile.value) return
  saving.value = true
  try {
    if (profile.value.enabled && !profile.value.syslog_server_ip.trim()) throw new Error('启用无人值守前必须选择具体的 MR 日志回传地址')
    if (!listenAddressIsLocal.value) throw new Error('本机监听地址已失效，请刷新地址列表后重新选择')
    const external = Boolean(profile.value.syslog_server_ip && !returnAddressIsLocal.value)
    if (external && !profile.value.allow_external_syslog_address) throw new Error('MR 日志回传地址不属于本机；如确为外部 NAT 地址，请启用高级选项')
    let confirmation = false
    if (external) {
      await ElMessageBox.confirm(
        '该地址不属于本机。仅在现场已配置外部 NAT/映射时使用；保存不会自动下发到 MR。确认继续？',
        '确认外部日志回传地址',
        { type: 'warning', confirmButtonText: '确认使用', cancelButtonText: '取消' },
      )
      confirmation = true
    }
    profile.value = await saveGroundProfile({
      ...profile.value,
      external_syslog_address_confirmation: confirmation,
    })
    ElMessage.success(message)
    await loadAll(true)
  } catch (reason) { ElMessage.error(errorText(reason, t('ground.profile_save_failed', '配置保存失败'))) }
  finally { saving.value = false }
}
async function loadLocalAddresses(): Promise<void> {
  networkLoading.value = true
  try {
    localIpv4Addresses.value = (await listLocalIpv4Addresses()).items
  } catch (reason) {
    ElMessage.error(errorText(reason, '读取本机 IPv4 失败'))
  } finally {
    networkLoading.value = false
  }
}
async function recommendSourceAddress(): Promise<void> {
  networkLoading.value = true
  try {
    const targets = trains.value.flatMap((train) => train.endpoints.map((item) => item.management_ip)).filter(Boolean)
    sourceRecommendation.value = await recommendLocalSourceIp(targets, profile.value?.syslog_server_ip || '')
    localIpv4Addresses.value = sourceRecommendation.value.candidates
    if (!sourceRecommendation.value.recommended_ip) ElMessage.warning(sourceRecommendation.value.recommendation_reason)
  } catch (reason) {
    ElMessage.error(errorText(reason, '系统路由推荐失败'))
  } finally {
    networkLoading.value = false
  }
}
function applyRecommendedAddress(): void {
  if (profile.value && sourceRecommendation.value?.recommended_ip) profile.value.syslog_server_ip = sourceRecommendation.value.recommended_ip
}
async function checkUdpPort(): Promise<void> {
  if (!profile.value) return
  networkLoading.value = true
  try {
    udpPortCheck.value = await checkGroundUdpPort(profile.value.udp_listen_host, profile.value.udp_listen_port)
  } catch (reason) {
    ElMessage.error(errorText(reason, 'UDP 端口检查失败'))
  } finally {
    networkLoading.value = false
  }
}
async function runAction(key: string, callback: () => Promise<unknown>): Promise<void> {
  action.value = key
  try { await callback(); await loadAll(true) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.action_failed', '无人值守操作失败'))) }
  finally { action.value = '' }
}
async function togglePriority(row: GroundTrain): Promise<void> {
  try { await setGroundTrainPriority(row.train_id, !row.priority); await loadAll(true) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.priority_failed', '置顶状态保存失败'))) }
}
async function syncInventory(): Promise<void> {
  try { const result = await syncGroundInventory(); ElMessage.success(`已同步 ${result.discovered_train_count} 辆列车`); await loadAll(true) }
  catch (reason) { ElMessage.error(errorText(reason, '设备清单同步失败')) }
}
async function updatePolicy(row: GroundTrain, changes: Partial<GroundTrain>): Promise<void> {
  try {
    await saveGroundTrainPolicy(row.train_id, {
      enabled: changes.enabled ?? row.enabled, priority: changes.priority ?? row.priority,
      scheduling_priority: changes.scheduling_priority ?? row.scheduling_priority,
      deep_collection_enabled: changes.deep_collection_enabled ?? row.deep_collection_enabled,
      monitor_only: changes.monitor_only ?? row.monitor_only, remark: changes.remark ?? row.remark,
    })
    await loadAll(true)
  } catch (reason) { ElMessage.error(errorText(reason, '列车策略保存失败')) }
}
async function checkConfigs(deviceUuid = '', allowTargetPortChange = false): Promise<void> {
  try { await requestGroundConfigCheck(deviceUuid, allowTargetPortChange); ElMessage.success('配置检查请求已提交'); await loadAll(true) }
  catch (reason) { ElMessage.error(errorText(reason, '配置检查提交失败')) }
}
async function confirmTargetPortChange(deviceUuid: string): Promise<void> {
  if (!deviceUuid || !profile.value) return
  await ElMessageBox.confirm(
    `设备已存在 ${profile.value.syslog_server_ip} 的其他端口。继续将修改该 IP 的日志目标为 ${profile.value.syslog_server_port}，原端口接收程序可能停止收到日志；其他 IP 的 loghost 会保留。确认修改？`,
    '高风险：修改 MR 日志目标端口',
    { type: 'warning', confirmButtonText: '确认修改此 MR', cancelButtonText: '保持只读' },
  )
  await checkConfigs(deviceUuid, true)
}
async function showTrain(row: GroundTrain): Promise<void> {
  try { selectedTrain.value = await getGroundTrain(row.train_id); trainDialog.value = true }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.train_load_failed', '列车详情读取失败'))) }
}
function showTrainPing(row: GroundTrain): void {
  pingFilter.query = row.train_no || row.train_id
  activeTab.value = 'ping'
  trainDialog.value = false
}
async function showTrainTimeline(row: GroundTrain): Promise<void> {
  timelineFilter.trainId = row.train_id
  activeTab.value = 'timeline'
  trainDialog.value = false
  await loadAll(true)
}
async function openDeepSession(sessionId: string): Promise<void> {
  if (!sessionId) return
  trainDialog.value = false
  await router.push({ name: 'online-mr-analysis', query: { session_id: sessionId } })
}
async function showArchive(row: GroundArchive): Promise<void> {
  try { selectedArchive.value = await getGroundArchive(row.archive_id); archiveDialog.value = true }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_load_failed', '归档汇总读取失败'))) }
}
async function removeArchive(row: GroundArchive): Promise<void> {
  await ElMessageBox.confirm(t('ground.archive_delete_confirm', `确认删除 ${row.run_date} 的无人值守归档？该操作不会作用于正在使用的当日数据。`), t('ground.archive_delete_title', '删除历史归档'), { type: 'warning', confirmButtonText: t('common.delete', '删除'), cancelButtonText: t('common.cancel', '取消') })
  try { await deleteGroundArchive(row.archive_id); ElMessage.success(t('ground.archive_delete_queued', '归档删除请求已提交')); await loadAll(true) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_delete_failed', '归档删除失败'))) }
}
async function downloadArchiveSummary(row: GroundArchive): Promise<void> {
  try { await downloadBackendResource(groundArchiveSummaryDownloadRequest(row)) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_download_failed', '归档汇总下载失败'))) }
}
async function openArchiveDirectory(): Promise<void> {
  try { const result = await openGroundArchiveDirectory(); if (!result.success) throw new Error(result.message) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_open_failed', '归档目录打开失败'))) }
}
function endpoint(row: GroundTrain, code: 'CT' | 'CW') { return row.endpoints.find((item) => item.endpoint === code) }
function duration(seconds: number): string { const minutes = Math.floor(seconds / 60); return `${minutes}m ${seconds % 60}s` }
function metric(value: number | null, unit: string): string { return value == null ? '—' : `${value.toFixed(2)} ${unit}` }
function bytes(value: number): string { if (!value) return '0 B'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024))); return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}` }
function errorText(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' { if (['RUNNING', 'COVERED', 'READY', 'FRESH', 'MAINLINE'].includes(value)) return 'success'; if (['PAUSED', 'PARTIAL', 'STALE', 'MAINLINE_STATIONARY', 'WARNING'].includes(value)) return 'warning'; if (['ERROR', 'FAILED', 'CRITICAL'].includes(value)) return 'danger'; return 'info' }

onMounted(() => { void loadAll(); void loadLocalAddresses(); schedulePoll() })
onBeforeUnmount(() => { disposed = true; if (pollTimer !== undefined) window.clearTimeout(pollTimer) })
</script>

<template>
  <main v-loading="loading" class="ground-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ t('ground.section', '轨道交通') }}</p>
        <h1>{{ t('ground.title', '地面无人值守') }}</h1>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" circle :title="t('common.refresh', '刷新')" @click="loadAll()" />
        <el-button :icon="Refresh" :loading="action === 'sync'" @click="runAction('sync', syncInventory)">同步设备</el-button>
        <el-button :loading="action === 'config'" :disabled="!running || !profile?.syslog_server_ip" @click="runAction('config', () => checkConfigs())">检查 MR 配置</el-button>
        <el-button :icon="VideoPlay" type="primary" :loading="action === 'start'" :disabled="running || !profile?.enabled" @click="runAction('start', startGroundRun)">{{ t('ground.start_now', '立即开始') }}</el-button>
        <el-button :icon="VideoPause" :loading="action === 'pause'" :disabled="status?.state !== 'RUNNING'" @click="runAction('pause', pauseGroundRun)">{{ t('ground.pause', '暂停调度') }}</el-button>
        <el-button :icon="VideoPlay" :loading="action === 'resume'" :disabled="status?.state !== 'PAUSED'" @click="runAction('resume', resumeGroundRun)">{{ t('ground.resume', '继续调度') }}</el-button>
        <el-button :icon="SwitchButton" :loading="action === 'stop'" :disabled="!running" @click="runAction('stop', stopGroundRun)">{{ t('ground.stop', '正常停止') }}</el-button>
        <el-button :icon="Box" type="danger" plain :loading="action === 'archive'" :disabled="!running" @click="runAction('archive', stopAndArchiveGroundRun)">{{ t('ground.stop_archive', '停止并归档') }}</el-button>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="ground-tabs">
      <el-tab-pane :label="t('ground.overview', '运行概览')" name="overview">
        <section class="overview-band">
          <div class="status-line">
            <span>{{ t('ground.current_site', '当前局点') }} <b>{{ status?.site_id || '—' }}</b></span>
            <el-tag :type="statusType(status?.state || '')">{{ status?.state || 'DISABLED' }}</el-tag>
            <el-switch v-if="profile" v-model="profile.enabled" :active-text="t('ground.enabled', '启用无人值守')" @change="saveProfile()" />
            <span class="muted">{{ t('ground.pause_note', '暂停调度时 AC 轮询与长 Ping 继续') }}</span>
          </div>
          <div class="metric-grid">
            <article><span>{{ t('ground.window', '配置运行时间') }}</span><strong>{{ status?.schedule_start_time }} - {{ status?.schedule_end_time }}</strong></article>
            <article><span>{{ t('ground.next_start', '下一次启动') }}</span><strong>{{ status?.next_start_at || '—' }}</strong></article>
            <article><span>{{ t('ground.next_end', '下一次结束') }}</span><strong>{{ status?.next_end_at || '—' }}</strong></article>
            <article><span>{{ t('ground.ac_updated', 'AC 最近更新') }}</span><strong>{{ status?.ac_last_updated_at || '—' }}</strong></article>
            <article><span>{{ t('ground.mainline_trains', '正线列车') }}</span><strong>{{ status?.mainline_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.ping_mrs', 'Ping 中 MR') }}</span><strong>{{ status?.ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.active_deep', '当前深度采集车辆') }}</span><strong>{{ status?.active_deep_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.covered_today', '今日已完成 / 未完成') }}</span><strong>{{ status?.covered_train_count ?? 0 }} / {{ status?.incomplete_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.disk_usage', '当前占用 / 磁盘剩余') }}</span><strong>{{ bytes(status?.disk_used_bytes ?? 0) }} / {{ bytes(status?.disk_free_bytes ?? 0) }}</strong><el-tag size="small" :type="statusType(status?.disk_status || '')">{{ status?.disk_status }}</el-tag></article>
            <article><span>{{ t('ground.latest_archive', '最近归档') }}</span><strong>{{ status?.latest_archive_status || '—' }}</strong><small>{{ status?.latest_archive_message }}</small></article>
            <article><span>Syslog 活跃 / 配置异常</span><strong>{{ status?.syslog_active_mr_count ?? 0 }} / {{ status?.config_abnormal_count ?? 0 }}</strong></article>
            <article><span>UDP 队列 / 丢弃</span><strong>{{ health?.udp_queue_length ?? 0 }} / {{ health?.udp_dropped_count ?? 0 }}</strong><small>{{ health?.udp_listen_address || '未监听' }}</small></article>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.trains', '正线车辆')" name="trains">
        <div class="toolbar"><el-input v-model="trainFilter" clearable :placeholder="t('ground.train_filter', '筛选列车、AP、站点或区间')" /></div>
        <div class="coverage-strip">
          <span>轨旁 AP 匹配 <b>{{ locationStats.ap }}</b></span>
          <span>站点级匹配 <b>{{ locationStats.station }}</b></span>
          <span>未匹配 <b>{{ locationStats.unmatched }}</b></span>
          <span>车辆段 / 停车场 / 存车线排除 <b>{{ locationStats.excluded }}</b></span>
        </div>
        <div class="table-frame"><NcDataTable :data="filteredTrains" :columns="trainColumns" table-id="ground-trains" route-key="rail-ground-unattended" row-key="train_id" compact>
          <template #cell-eligibility_status="{ row }"><el-tag size="small" :type="statusType(row.eligibility_status)">{{ row.eligibility_status }}</el-tag></template>
          <template #cell-coverage_status="{ row }"><el-tag size="small" :type="statusType(row.coverage_status)">{{ row.coverage_status }}</el-tag></template>
          <template #cell-actions="{ row }"><div class="row-actions"><el-button size="small" text type="primary" @click="showTrain(row)">{{ t('common.view', '查看') }}</el-button><el-button size="small" text type="primary" @click="togglePriority(row)">{{ row.priority ? t('ground.unpin', '取消置顶') : t('ground.pin', '置顶') }}</el-button><el-button size="small" text @click="updatePolicy(row, { enabled: !row.enabled })">{{ row.enabled ? '停用' : '启用' }}</el-button></div></template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.long_ping', '长 Ping')" name="ping">
        <div class="toolbar">
          <el-input v-model="pingFilter.query" clearable :placeholder="t('ground.ping_filter', '列车、管理 IP 或 AP')" />
          <el-select v-model="pingFilter.endpoint" clearable :placeholder="t('ground.mr_endpoint', 'MR 端点')"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select>
          <el-input v-model="pingFilter.station" clearable :placeholder="t('ground.station', '站点')" />
          <el-input v-model="pingFilter.section" clearable :placeholder="t('ground.section', '区间')" />
          <span>{{ t('ground.min_loss', '最低丢包率') }}</span><el-input-number v-model="pingFilter.minLoss" :min="0" :max="100" :controls="false" />
        </div>
        <div class="table-frame"><NcDataTable :data="filteredPing" :columns="pingColumns" table-id="ground-ping" route-key="rail-ground-unattended" row-key="target_ip" compact /></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.deep_collection', '深度采集')" name="deep">
        <div class="coverage-strip"><span v-for="value in ['COLLECTING','WAITING','NOT_SEEN','PARTIAL','COVERED','EXCLUDED']" :key="value"><b>{{ deepCollections.filter((row) => row.status === value).length }}</b>{{ value }}</span></div>
        <div class="table-frame"><NcDataTable :data="deepCollections" :columns="deepColumns" table-id="ground-deep" route-key="rail-ground-unattended" row-key="train_id" compact>
          <template #cell-status="{ row }"><el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag></template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.timeline', '时间轴')" name="timeline">
        <div class="toolbar"><el-input v-model="timelineFilter.trainId" clearable :placeholder="t('ground.train_id', '列车 ID')" /><el-input v-model="timelineFilter.eventType" clearable :placeholder="t('ground.event_type', '事件类型')" /><el-button :icon="Refresh" @click="loadAll()">{{ t('common.query', '查询') }}</el-button></div>
        <div class="table-frame"><NcDataTable :data="timeline" :columns="timelineColumns" table-id="ground-timeline" route-key="rail-ground-unattended" row-key="event_id" compact /></div>
      </el-tab-pane>

      <el-tab-pane label="系统健康" name="health">
        <section class="health-grid">
          <article><span>UDP 接收速率</span><strong>{{ health?.udp_receive_rate_per_second ?? 0 }} /s</strong></article>
          <article><span>未知来源</span><strong>{{ health?.udp_unidentified_count ?? 0 }}</strong></article>
          <article><span>原始写入</span><strong>{{ health?.raw_records_written ?? 0 }}</strong><small>{{ bytes(health?.raw_bytes_written ?? 0) }}</small></article>
          <article><span>数据库待写 / 耗时</span><strong>{{ health?.database_pending_count ?? 0 }} / {{ health?.database_last_batch_duration_ms?.toFixed(1) ?? 0 }} ms</strong></article>
          <article><span>Ping 目标 / 分片</span><strong>{{ health?.ping_target_count ?? 0 }} / {{ health?.ping_process_count ?? 0 }}</strong></article>
          <article><span>最近系统错误</span><strong>{{ health?.last_error || '—' }}</strong></article>
        </section>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.archives', '历史归档')" name="archives">
        <div class="toolbar"><el-button :icon="FolderOpened" @click="openArchiveDirectory">{{ t('ground.open_archive_directory', '打开归档目录') }}</el-button></div>
        <div class="table-frame"><NcDataTable :data="archives" :columns="archiveColumns" table-id="ground-archives" route-key="rail-ground-unattended" row-key="archive_id" compact>
          <template #cell-archive_status="{ row }"><el-tag size="small" :type="statusType(row.archive_status)">{{ row.archive_status }}</el-tag></template>
          <template #cell-actions="{ row }"><div class="row-actions"><el-button size="small" text type="primary" @click="showArchive(row)">{{ t('common.view', '查看') }}</el-button><el-button :icon="Download" size="small" text circle :title="t('common.download', '下载汇总')" @click="downloadArchiveSummary(row)" /><el-button :icon="Delete" size="small" text type="danger" circle :title="t('common.delete', '删除')" @click="removeArchive(row)" /></div></template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.settings', '设置')" name="settings">
        <el-form v-if="profile" :model="profile" label-position="top" class="settings-form">
          <section><h2>{{ t('ground.schedule', '运行时间与 AC') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.start_time', '开始时间')"><el-time-select v-model="profile.schedule_start_time" start="00:00" step="00:05" end="23:55" /></el-form-item>
            <el-form-item :label="t('ground.end_time', '结束时间')"><el-time-select v-model="profile.schedule_end_time" start="00:00" step="00:05" end="23:55" /></el-form-item>
            <el-form-item :label="t('ground.timezone', '时区')"><el-input v-model="profile.timezone" /></el-form-item>
            <el-form-item :label="t('ground.ac_poll', 'AC 轮询间隔（秒）')"><el-input-number v-model="profile.ac_poll_interval_seconds" :min="3" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.stationary', '同 AP 静止阈值（分钟）')"><el-input-number v-model="profile.stationary_exclusion_minutes" :min="1" :max="180" /></el-form-item>
            <el-form-item :label="t('ground.ac_grace', 'AC 异常 Ping 宽限（秒）')"><el-input-number v-model="profile.ac_stale_grace_seconds" :min="0" :max="3600" /></el-form-item>
            <el-form-item :label="t('ground.correlation_tolerance', 'AC/Ping 关联偏差（秒）')"><el-input-number v-model="profile.ac_ping_correlation_tolerance_seconds" :min="1" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.switch_window', 'AP 切换前 / 后窗口（秒）')"><div class="inline-numbers"><el-input-number v-model="profile.ap_switch_before_seconds" :min="0" :max="60" /><el-input-number v-model="profile.ap_switch_after_seconds" :min="0" :max="60" /></div></el-form-item>
          </div></section>
          <section><h2>{{ t('ground.deep_budget', '深度采集预算') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.max_trains', '最大活动列车')"><el-input-number v-model="profile.max_active_trains" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.max_mrs', '最大活动 MR')"><el-input-number v-model="profile.max_active_mrs" :min="1" :max="16" /></el-form-item>
            <el-form-item :label="t('ground.max_starting', '最大启动中 MR')"><el-input-number v-model="profile.max_starting_mrs" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.max_finalizing', '最大最终化 MR')"><el-input-number v-model="profile.max_finalizing_mrs" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.minimum_duration', '最低有效时长（分钟）')"><el-input-number v-model="profile.minimum_valid_collection_minutes" :min="1" :max="720" /></el-form-item>
            <el-form-item :label="t('ground.preferred_duration', '建议采集时长（分钟）')"><el-input-number v-model="profile.preferred_collection_minutes" :min="1" :max="720" /></el-form-item>
            <el-form-item :label="t('ground.maximum_duration', '最大采集时长（分钟）')"><el-input-number v-model="profile.maximum_collection_minutes" :min="1" :max="1440" /></el-form-item>
            <el-form-item :label="t('ground.start_jitter', '启动错峰（秒）')"><el-input-number v-model="profile.start_jitter_seconds" :min="0" :max="60" /></el-form-item>
            <el-form-item :label="t('ground.start_batch', '每批启动 MR 数')"><el-input-number v-model="profile.start_batch_size" :min="1" :max="4" /></el-form-item>
          </div></section>
          <section><h2>{{ t('ground.ping_and_storage', '长 Ping 与存储') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.ping_interval', 'Ping 间隔（ms）')"><el-input-number v-model="profile.fleet_ping_interval_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item :label="t('ground.ping_timeout', 'Ping 超时（ms）')"><el-input-number v-model="profile.fleet_ping_timeout_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item :label="t('ground.packet_size', '包大小（字节）')"><el-input-number v-model="profile.fleet_ping_packet_size" :min="1" :max="65507" /></el-form-item>
            <el-form-item :label="t('ground.shard_size', '每个 fping 分片目标数')"><el-input-number v-model="profile.fleet_ping_shard_size" :min="2" :max="32" /></el-form-item>
            <el-form-item :label="t('ground.detail_retention', '详细数据保留天数')"><el-select v-model="profile.detail_retention_days"><el-option v-for="day in [7,15,30,60,90,180]" :key="day" :label="`${day} 天`" :value="day" /></el-select></el-form-item>
            <el-form-item :label="t('ground.summary_retention', '汇总保留天数')"><el-input-number v-model="profile.summary_retention_days" :min="profile.detail_retention_days" :max="3650" /></el-form-item>
            <el-form-item :label="t('ground.warning_space', '空间预警阈值（GB）')"><el-input-number v-model="profile.storage_warning_free_gb" :min="0.1" :max="1024" /></el-form-item>
            <el-form-item :label="t('ground.critical_space', '严重空间阈值（GB）')"><el-input-number v-model="profile.storage_critical_free_gb" :min="0.1" :max="1024" /></el-form-item>
          </div><p class="muted">{{ t('ground.storage_path', '存储路径：当前局点 / files / rail_transit / ground_unattended。深度 Session ZIP 仍保存在既有 Online MR 目录，每日归档只保存引用。') }}</p></section>
          <section><h2>UDP Syslog 与上电检查</h2>
            <el-alert title="本机监听地址只控制 NetConsole 在哪些网卡接收 UDP；MR 日志回传地址会用于 info-center loghost。监听 0.0.0.0 时仍必须明确选择一个具体回传地址。" type="info" :closable="false" show-icon />
            <div class="network-actions">
              <el-button :icon="Refresh" :loading="networkLoading" @click="loadLocalAddresses">刷新本机地址</el-button>
              <el-button :loading="networkLoading" @click="recommendSourceAddress">检测到 MR 网络的推荐地址</el-button>
              <el-button :loading="networkLoading" @click="checkUdpPort">检查 UDP 端口占用</el-button>
              <el-checkbox v-model="showAllAddresses">显示虚拟与其他地址</el-checkbox>
            </div>
            <div class="form-grid">
            <el-form-item label="本机监听地址">
              <el-select v-model="profile.udp_listen_host" filterable allow-create>
                <el-option label="0.0.0.0 · 监听全部本机网卡" value="0.0.0.0" />
                <el-option v-for="row in visibleIpv4Addresses" :key="`listen:${row.adapter_id}:${row.ipv4}`" :value="row.ipv4" :label="`${row.ipv4} · ${row.adapter_name} · /${row.prefix_length}`" />
              </el-select>
              <span :class="listenAddressIsLocal ? 'network-ok' : 'network-error'">{{ listenAddressIsLocal ? '监听地址有效' : '监听地址已不属于本机' }}</span>
            </el-form-item>
            <el-form-item label="UDP 监听端口"><el-input-number v-model="profile.udp_listen_port" :min="1" :max="65535" /></el-form-item>
            <el-form-item label="MR 日志回传地址">
              <el-select v-model="profile.syslog_server_ip" filterable allow-create clearable placeholder="选择或输入具体 IPv4">
                <el-option v-for="row in visibleIpv4Addresses" :key="`${row.adapter_id}:${row.ipv4}`" :value="row.ipv4" :label="`${row.ipv4} · ${row.adapter_name} · /${row.prefix_length}${row.recommended ? ' · 推荐' : ''}`" />
              </el-select>
              <span v-if="profile.syslog_server_ip" :class="returnAddressIsLocal ? 'network-ok' : 'network-error'">{{ returnAddressIsLocal ? '当前地址属于本机' : '当前地址不属于本机' }}</span>
            </el-form-item>
            <el-form-item label="Syslog 服务器端口"><el-input-number v-model="profile.syslog_server_port" :min="1" :max="65535" /></el-form-item>
            <el-form-item label="UDP 队列容量"><el-input-number v-model="profile.udp_queue_capacity" :min="100" :max="500000" /></el-form-item>
            <el-form-item label="批量事件数"><el-input-number v-model="profile.event_batch_size" :min="1" :max="5000" /></el-form-item>
            <el-form-item label="配置检查冷却（秒）"><el-input-number v-model="profile.config_check_cooldown_seconds" :min="30" :max="86400" /></el-form-item>
            <el-form-item label="上电时间误差（秒）"><el-input-number v-model="profile.boot_time_tolerance_seconds" :min="10" :max="900" /></el-form-item>
          </div>
          <div v-if="sourceRecommendation" class="network-status">
            <span>系统路由推荐：<b>{{ sourceRecommendation.recommended_ip || '无可靠推荐' }}</b></span>
            <span>{{ sourceRecommendation.recommendation_reason }}</span>
            <el-button v-if="sourceRecommendation.recommended_ip" size="small" @click="applyRecommendedAddress">采用推荐</el-button>
          </div>
          <div v-if="udpPortCheck" class="network-status"><el-tag :type="udpPortCheck.available ? 'success' : 'danger'">{{ udpPortCheck.message }}</el-tag><span>{{ udpPortCheck.listen_host }}:{{ udpPortCheck.listen_port }}</span></div>
          <el-checkbox v-model="profile.allow_external_syslog_address">高级：使用外部 NAT 日志回传地址（保存时需再次确认）</el-checkbox>
          <p class="muted">保存 Profile 不会在当前请求中直接连接 MR；后台检查只补齐安全缺项。同 IP 端口冲突始终保持只读，必须在单台 MR 详情中再次确认后才允许修改；不会执行 save、undo、reboot、reset 或 delete。</p></section>
          <section><h2>{{ t('ground.priority_trains', '置顶列车') }}</h2><div class="priority-grid"><el-checkbox v-for="row in trains" :key="row.train_id" :model-value="row.priority" @change="togglePriority(row)">{{ row.train_no || row.train_name }}</el-checkbox><span v-if="!trains.length" class="muted">{{ t('ground.no_priority_candidates', '暂无列车基础资料或 AC 在线状态') }}</span></div></section>
          <div class="form-actions"><el-button type="primary" :loading="saving" @click="saveProfile()">{{ t('common.save', '保存设置') }}</el-button><span class="muted">{{ t('ground.profile_effective', '运行中修改默认从下一次调度周期生效') }}</span></div>
        </el-form>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="archiveDialog" :title="t('ground.archive_summary', '无人值守归档汇总')" width="min(720px, 92vw)">
      <el-descriptions v-if="selectedArchive" :column="2" border>
        <el-descriptions-item :label="t('ground.run_date', '运行日期')">{{ selectedArchive.run_date }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.archive_status', '归档状态')">{{ selectedArchive.archive_status }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.ping_samples', 'Ping 样本')">{{ selectedArchive.ping_sample_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.covered_trains', '覆盖列车')">{{ selectedArchive.covered_train_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.complete_sessions', '完整 Session')">{{ selectedArchive.complete_session_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.partial_sessions', '部分 Session')">{{ selectedArchive.partial_session_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.archive_size', '归档大小')">{{ bytes(selectedArchive.archive_size_bytes) }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.retention_until', '保留截止')">{{ selectedArchive.retention_until }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog v-model="trainDialog" :title="t('ground.train_detail', '列车无人值守详情')" width="min(820px, 94vw)">
      <template v-if="selectedTrain">
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('ground.train', '列车')">{{ selectedTrain.train_no || selectedTrain.train_name }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.eligibility', '正线判断')"><el-tag :type="statusType(selectedTrain.eligibility_status)">{{ selectedTrain.eligibility_status }}</el-tag></el-descriptions-item>
          <el-descriptions-item :label="t('ground.current_ap', '当前 AP')">{{ selectedTrain.current_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="位置匹配等级">{{ selectedTrain.location_match_level || 'UNMATCHED' }}</el-descriptions-item>
          <el-descriptions-item label="原始 AP 名称">{{ selectedTrain.raw_peer_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原始 AP MAC">{{ selectedTrain.raw_peer_ap_mac || '—' }}</el-descriptions-item>
          <el-descriptions-item label="解析后 AP">{{ selectedTrain.resolved_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="规范站点">{{ selectedTrain.canonical_station_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="匹配依据" :span="2">{{ selectedTrain.location_match_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.same_ap_duration', '同 AP 停留')">{{ duration(selectedTrain.same_ap_duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.exclusion_reason', '排除原因')" :span="2">{{ selectedTrain.exclusion_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT Session">{{ selectedTrainCollection?.ct_session_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CW Session">{{ selectedTrainCollection?.cw_session_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT Syslog">{{ endpoint(selectedTrain, 'CT')?.syslog_status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CW Syslog">{{ endpoint(selectedTrain, 'CW')?.syslog_status || '—' }}</el-descriptions-item>
        </el-descriptions>
        <section v-for="mrEndpoint in selectedTrain.endpoints" :key="`loghost:${mrEndpoint.mr_id || mrEndpoint.endpoint}`" class="loghost-section">
          <div class="network-status">
            <b>{{ mrEndpoint.endpoint }} · 设备现有日志主机</b>
            <span>NetConsole 管理目标：{{ mrEndpoint.managed_target_ip || profile?.syslog_server_ip || '—' }}:{{ mrEndpoint.managed_target_port || profile?.syslog_server_port || '—' }}</span>
            <el-tag v-for="item in mrEndpoint.managed_target_statuses" :key="item" :type="item === 'TARGET_PRESENT' ? 'success' : item === 'TARGET_PORT_CONFLICT' ? 'danger' : 'info'">{{ item }}</el-tag>
          </div>
          <el-table :data="mrEndpoint.configured_log_hosts" size="small" empty-text="尚未执行配置检查">
            <el-table-column prop="ip" label="IP" min-width="130" />
            <el-table-column prop="port" label="端口" width="90" />
            <el-table-column prop="facility" label="Facility" width="100" />
            <el-table-column label="归属" min-width="160"><template #default="{ row }">{{ row.is_managed_target ? 'NetConsole 管理目标' : '设备已有配置' }}</template></el-table-column>
            <el-table-column label="判断" min-width="170"><template #default="{ row }">{{ row.same_ip_different_port ? '同 IP 端口冲突' : row.is_managed_target ? '目标一致' : '保留，不处理' }}</template></el-table-column>
          </el-table>
          <el-alert
            v-if="mrEndpoint.managed_target_statuses.includes('TARGET_PORT_CONFLICT')"
            :title="`设备已存在 ${mrEndpoint.managed_target_ip} 的其他端口；默认配置检查保持只读，不会进入 system-view。`"
            type="error"
            :closable="false"
            show-icon
          />
          <div class="boot-evidence">
            <span>估算上电时间：{{ mrEndpoint.estimated_boot_time || '—' }}</span>
            <span>误差：±{{ mrEndpoint.boot_time_uncertainty_seconds || 0 }} 秒</span>
            <span>原因：{{ mrEndpoint.reboot_reason || '—' }}</span>
            <span>设备时区：{{ mrEndpoint.timezone_name || '—' }}</span>
            <span>时间质量：{{ mrEndpoint.device_time_quality || '—' }}</span>
          </div>
          <el-button
            v-if="mrEndpoint.managed_target_statuses.includes('TARGET_PORT_CONFLICT')"
            type="danger"
            plain
            @click="confirmTargetPortChange(mrEndpoint.mr_id)"
          >确认修改此 MR 的目标端口</el-button>
        </section>
        <div class="dialog-actions">
          <el-button @click="showTrainPing(selectedTrain)">{{ t('ground.view_ping', '查看长 Ping') }}</el-button>
          <el-button @click="showTrainTimeline(selectedTrain)">{{ t('ground.view_timeline', '查看事件时间轴') }}</el-button>
          <el-button :disabled="!running" @click="checkConfigs(endpoint(selectedTrain, 'CT')?.mr_id || '')">检查 CT 配置</el-button>
          <el-button :disabled="!selectedTrainCollection?.ct_session_id" @click="openDeepSession(selectedTrainCollection?.ct_session_id || '')">{{ t('ground.open_ct_session', '打开 CT Session') }}</el-button>
          <el-button :disabled="!selectedTrainCollection?.cw_session_id" @click="openDeepSession(selectedTrainCollection?.cw_session_id || '')">{{ t('ground.open_cw_session', '打开 CW Session') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped>
.ground-page{display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0}.page-heading,.heading-actions,.status-line,.toolbar,.coverage-strip,.row-actions,.form-actions,.inline-numbers,.dialog-actions,.network-actions,.network-status,.boot-evidence{display:flex;align-items:center;gap:10px}.page-heading{justify-content:space-between;flex-wrap:wrap}.page-heading h1{margin:2px 0 0;font-size:24px;letter-spacing:0}.eyebrow{margin:0;color:var(--el-color-primary);font-size:12px;font-weight:700;letter-spacing:0}.heading-actions,.toolbar,.dialog-actions,.network-actions,.network-status,.boot-evidence{flex-wrap:wrap}.ground-tabs{min-width:0}.overview-band{padding:2px 0}.status-line{min-height:42px;flex-wrap:wrap;border-bottom:1px solid var(--el-border-color-lighter)}.metric-grid,.health-grid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:1px;margin-top:12px;background:var(--el-border-color-lighter);border:1px solid var(--el-border-color-lighter)}.metric-grid article,.health-grid article{min-width:0;padding:12px;background:var(--el-bg-color)}.metric-grid span,.metric-grid small,.health-grid span,.health-grid small{display:block;color:var(--el-text-color-secondary);font-size:12px}.metric-grid strong,.health-grid strong{display:block;min-height:24px;margin:6px 0 3px;font-size:18px;letter-spacing:0;overflow-wrap:anywhere}.toolbar{min-height:42px}.toolbar .el-input{width:210px}.toolbar .el-select{width:130px}.toolbar .el-input-number{width:110px}.table-frame{height:clamp(360px,calc(100vh - 310px),680px);min-width:0;overflow:hidden;border-top:1px solid var(--el-border-color-lighter)}.coverage-strip{flex-wrap:wrap;margin-bottom:8px}.coverage-strip span{display:flex;align-items:center;gap:5px;padding:5px 8px;background:var(--el-fill-color-light);border-radius:4px;color:var(--el-text-color-secondary);font-size:12px}.coverage-strip b{color:var(--el-text-color-primary);font-size:16px}.settings-form{display:flex;flex-direction:column;gap:18px;max-width:1180px}.settings-form section{padding-bottom:16px;border-bottom:1px solid var(--el-border-color-lighter)}.settings-form h2{margin:0 0 12px;font-size:16px;letter-spacing:0}.form-grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:0 16px}.form-grid :deep(.el-input-number),.form-grid :deep(.el-select),.form-grid :deep(.el-input){width:100%}.inline-numbers{width:100%}.priority-grid{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:8px}.muted{color:var(--el-text-color-secondary);font-size:12px}.network-actions{margin:12px 0}.network-status{margin:10px 0;padding:8px;background:var(--el-fill-color-light)}.network-ok{color:var(--el-color-success);font-size:12px}.network-error{color:var(--el-color-danger);font-size:12px}.loghost-section{margin-top:14px;padding-top:8px;border-top:1px solid var(--el-border-color-lighter)}.boot-evidence{margin:8px 0;color:var(--el-text-color-secondary);font-size:12px}.form-actions{position:sticky;bottom:0;padding:10px 0;background:var(--el-bg-color)}.dialog-actions{justify-content:flex-end;margin-top:14px}@media(max-width:1300px){.metric-grid,.health-grid{grid-template-columns:repeat(3,minmax(150px,1fr))}.form-grid{grid-template-columns:repeat(3,minmax(170px,1fr))}.priority-grid{grid-template-columns:repeat(4,minmax(110px,1fr))}}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}.metric-grid,.health-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.form-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}.priority-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}.table-frame{height:clamp(340px,calc(100vh - 350px),620px)}}@media(max-width:620px){.metric-grid,.health-grid,.form-grid{grid-template-columns:1fr}.priority-grid{grid-template-columns:repeat(2,minmax(100px,1fr))}.heading-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.heading-actions .el-button{margin:0}.toolbar .el-input,.toolbar .el-select{width:100%}}
</style>
