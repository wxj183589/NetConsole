<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Box, Delete, Download, FolderOpened, Refresh, SwitchButton, VideoPause, VideoPlay } from '@element-plus/icons-vue'

import {
  deleteGroundArchive, getGroundArchive, getGroundProfile, getGroundStatus, getGroundTrain, groundArchiveSummaryDownloadRequest, listGroundArchives,
  getGroundHealth, listGroundDeepCollections, listGroundPingTargets, listGroundTimeline, listGroundTrains, requestGroundConfigCheck,
  openGroundArchiveDirectory, pauseGroundRun, resumeGroundRun, saveGroundProfile, setGroundTrainPriority, startGroundRun,
  stopAndArchiveGroundRun, stopGroundRun, saveGroundTrainPolicy, syncGroundInventory,
  checkGroundUdpPort, listLocalIpv4Addresses, recommendLocalSourceIp,
  getGroundPingSeries, getLatestGroundOperation, listGroundSyslogRecords,
} from '../../api/groundUnattended'
import GroundPingChart from '../../components/ground-unattended/GroundPingChart.vue'
import { NcDataTable, type NcTableColumn } from '../../components/table'
import { t } from '../../i18n/runtime'
import { downloadBackendResource } from '../../platform/runtime'
import type {
  GroundActionResponse, GroundArchive, GroundDeepCollection, GroundPingSeries, GroundPingTarget, GroundProfile, GroundStatus,
  GroundHealth, GroundOperation, GroundSyslogRecord, GroundTimelineEvent, GroundTrain,
  LocalIpv4Address, SourceIpRecommendation, UdpPortCheck,
} from '../../types/groundUnattended'
import {
  groundEventLabel, groundOperationStageLabel, groundRunModeLabel, groundSeverityLabel,
  groundSourceLabel, groundStatusLabel, groundTransitionContextLabel,
} from './groundUnattendedLabels'

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
const currentOperation = ref<GroundOperation | null>(null)
const pingSeries = ref<GroundPingSeries | null>(null)
const selectedPingTarget = ref<GroundPingTarget | null>(null)
const pingSeriesLoading = ref(false)
const includeWarmup = ref(false)
const pingRange = ref<'5m' | '30m' | '1h' | 'custom'>('30m')
const pingCustomRange = ref<[Date, Date] | null>(null)
const pingAutoRefresh = ref(true)
const syslogRecords = ref<GroundSyslogRecord[]>([])
const syslogTotal = ref(0)
const syslogLoading = ref(false)
const syslogFilter = reactive({ trainId: '', mrName: '', sourceIp: '', severity: '', keyword: '', page: 1, pageSize: 100 })
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
const timelineFilter = reactive({ query: '', eventType: '' })
let pollTimer: number | undefined
let disposed = false

interface LoadIssue {
  key: string
  label: string
  message: string
}

const loadIssues = ref<LoadIssue[]>([])
const loadIssueDescription = computed(() => loadIssues.value.map((item) => `${item.label}：${item.message}`).join('；'))
const profileLoadError = computed(() => loadIssues.value.find((item) => item.key === 'profile')?.message || '')

const running = computed(() => Boolean(status.value && ['STARTING', 'RUNNING', 'PAUSED', 'STOPPING', 'FINALIZING', 'ARCHIVING'].includes(status.value.state)))
const operationActive = computed(() => Boolean(currentOperation.value && ['PENDING', 'RUNNING'].includes(currentOperation.value.operation_state)))
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
const filteredTimeline = computed(() => {
  const needle = timelineFilter.query.trim().toLocaleLowerCase()
  if (!needle) return timeline.value
  return timeline.value.filter((row) => (
    `${row.train_no} ${row.train_name} ${row.mr_name} ${row.mr_position_code} ${row.title} ${row.message}`
      .toLocaleLowerCase()
      .includes(needle)
  ))
})
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
  { key: 'eligibility_status', label: t('ground.eligibility', '正线判断'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.eligibility_status) },
  { key: 'location_match_level', label: '匹配等级', valueType: 'status', width: 130, displayValue: (row) => groundStatusLabel(row.location_match_level) },
  { key: 'exclusion_reason', label: t('ground.exclusion_reason', '排除原因'), valueType: 'description', minWidth: 220 },
  { key: 'raw_peer_ap_name', label: '原始 AP', valueType: 'name' },
  { key: 'resolved_ap_name', label: '解析后 AP', valueType: 'name' },
  { key: 'canonical_station_name', label: '规范站点', valueType: 'text' },
  { key: 'section', label: t('ground.section', '归属区间'), valueType: 'text' },
  { key: 'same_ap_duration_seconds', label: t('ground.same_ap_duration', '同 AP 停留'), valueType: 'duration', displayValue: (row) => duration(row.same_ap_duration_seconds) },
  { key: 'ct_status', label: 'CT 在线', valueType: 'status', displayValue: (row) => groundStatusLabel(endpoint(row, 'CT')?.online_status) },
  { key: 'cw_status', label: 'CW 在线', valueType: 'status', displayValue: (row) => groundStatusLabel(endpoint(row, 'CW')?.online_status) },
  { key: 'ct_ping', label: 'CT Ping', valueType: 'status', displayValue: (row) => groundStatusLabel(endpoint(row, 'CT')?.ping_active ? 'PINGING' : 'STOPPED') },
  { key: 'cw_ping', label: 'CW Ping', valueType: 'status', displayValue: (row) => groundStatusLabel(endpoint(row, 'CW')?.ping_active ? 'PINGING' : 'STOPPED') },
  { key: 'coverage_status', label: t('ground.coverage', '今日深度采集'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.coverage_status) },
  { key: 'enabled', label: t('ground.enabled', '启用'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.enabled ? 'ENABLED' : 'DISABLED') },
  { key: 'syslog', label: 'WMESH Syslog', valueType: 'status', displayValue: (row) => `${groundStatusLabel(endpoint(row, 'CT')?.syslog_status || 'WAITING')} / ${groundStatusLabel(endpoint(row, 'CW')?.syslog_status || 'WAITING')}` },
  { key: 'updated_at', label: t('ground.updated_at', '最近更新时间'), valueType: 'datetime' },
  { key: 'actions', label: t('ground.actions', '操作'), valueType: 'actions', fixed: 'right', width: 154, hideable: false },
]
const pingColumns: NcTableColumn<GroundPingTarget>[] = [
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', fixed: 'left' },
  { key: 'mr_position_code', label: t('ground.mr_endpoint', 'MR 端点'), valueType: 'status' },
  { key: 'target_ip', label: t('ground.management_ip', '管理 IP'), valueType: 'ip' },
  { key: 'started_at', label: t('ground.started_at', '开始时间'), valueType: 'datetime' },
  { key: 'raw_sample_count', label: '原始发送', valueType: 'number' },
  { key: 'effective_sample_count', label: '有效发送', valueType: 'number' },
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
  { key: 'actions', label: '操作', valueType: 'actions', fixed: 'right', width: 110, hideable: false },
]
const deepColumns: NcTableColumn<GroundDeepCollection>[] = [
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', fixed: 'left' },
  { key: 'status', label: t('ground.status', '完成状态'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.status) },
  { key: 'queue_position', label: t('ground.queue_position', '队列位置'), valueType: 'number' },
  { key: 'scheduling_priority', label: t('ground.scheduling_priority', '调度优先级'), valueType: 'number' },
  { key: 'selection_reason', label: t('ground.selection_reason', '选择原因'), valueType: 'description', minWidth: 220 },
  { key: 'attempt_count', label: t('ground.attempts', '采集次数'), valueType: 'number' },
  { key: 'covered_rounds', label: t('ground.covered_rounds', '完成轮次'), valueType: 'number' },
  { key: 'started_at', label: t('ground.started_at', '采集开始'), valueType: 'datetime' },
  { key: 'valid_duration_minutes', label: t('ground.valid_duration', '有效时长'), valueType: 'duration', displayValue: (row) => `${row.valid_duration_minutes.toFixed(1)} 分钟` },
  { key: 'ct_session_id', label: 'CT 会话', valueType: 'text' },
  { key: 'cw_session_id', label: 'CW 会话', valueType: 'text' },
  { key: 'failure_reason', label: t('ground.failure_reason', '失败原因'), valueType: 'error', minWidth: 220 },
  { key: 'updated_at', label: t('ground.updated_at', '更新时间'), valueType: 'datetime' },
]
const timelineColumns: NcTableColumn<GroundTimelineEvent>[] = [
  { key: 'ts', label: t('ground.time', '时间'), valueType: 'datetime', fixed: 'left' },
  { key: 'event_type', label: t('ground.event_type', '事件类型'), valueType: 'status', displayValue: (row) => groundEventLabel(row.event_type) },
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', displayValue: (row) => row.train_no ? `列车 ${row.train_no}` : row.train_name || '未知列车' },
  { key: 'mr_name', label: t('ground.mr', 'MR 设备'), valueType: 'text' },
  { key: 'title', label: t('ground.event', '事件'), valueType: 'name' },
  { key: 'message', label: t('ground.message', '说明'), valueType: 'description', minWidth: 260 },
  { key: 'severity', label: t('ground.severity', '级别'), valueType: 'status', displayValue: (row) => groundSeverityLabel(row.severity) },
]
const archiveColumns: NcTableColumn<GroundArchive>[] = [
  { key: 'run_date', label: t('ground.run_date', '运行日期'), valueType: 'datetime', fixed: 'left' },
  { key: 'actual_started_at', label: t('ground.actual_start', '实际开始'), valueType: 'datetime' },
  { key: 'actual_ended_at', label: t('ground.actual_end', '实际结束'), valueType: 'datetime' },
  { key: 'mainline_train_count', label: t('ground.mainline_trains', '正线车辆'), valueType: 'number' },
  { key: 'ping_target_count', label: t('ground.ping_targets', 'Ping 目标'), valueType: 'number' },
  { key: 'ping_sample_count', label: t('ground.ping_samples', 'Ping 样本'), valueType: 'number' },
  { key: 'covered_train_count', label: t('ground.covered_trains', '深度覆盖'), valueType: 'number' },
  { key: 'complete_session_count', label: t('ground.complete_sessions', '完整会话'), valueType: 'number' },
  { key: 'partial_session_count', label: t('ground.partial_sessions', '部分会话'), valueType: 'number' },
  { key: 'archive_size_bytes', label: t('ground.archive_size', '归档大小'), valueType: 'number', displayValue: (row) => bytes(row.archive_size_bytes) },
  { key: 'archive_status', label: t('ground.archive_status', '归档状态'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.archive_status) },
  { key: 'retention_until', label: t('ground.retention_until', '保留截止'), valueType: 'datetime' },
  { key: 'actions', label: t('ground.actions', '操作'), valueType: 'actions', fixed: 'right', width: 190, hideable: false },
]
const syslogColumns: NcTableColumn<GroundSyslogRecord>[] = [
  { key: 'receive_time', label: '接收时间', valueType: 'datetime', fixed: 'left', width: 180 },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', width: 180 },
  { key: 'train_no', label: '列车', valueType: 'name', displayValue: (row) => row.train_no || '未识别' },
  { key: 'mr_name', label: 'MR 设备', valueType: 'text', displayValue: (row) => row.mr_name || '未知 MR' },
  { key: 'mr_role', label: '端点', valueType: 'status' },
  { key: 'source_ip', label: '来源 IP', valueType: 'ip' },
  { key: 'system_name', label: '设备系统名', valueType: 'text' },
  { key: 'severity', label: '级别', valueType: 'status', displayValue: (row) => groundSeverityLabel(row.severity) },
  { key: 'identity_status', label: '身份状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.identity_status) },
  { key: 'clock_offset_ms', label: '时间差', valueType: 'number', displayValue: (row) => metric(row.clock_offset_ms, 'ms') },
  { key: 'raw_file_status', label: '文件状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.raw_file_status) },
  { key: 'raw_text', label: '原始内容', valueType: 'description', minWidth: 420 },
]

async function loadAll(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const results = await Promise.allSettled([
      getGroundStatus(), getGroundProfile(), listGroundTrains(), listGroundPingTargets(),
      listGroundDeepCollections(), listGroundTimeline('', timelineFilter.eventType), listGroundArchives(), getGroundHealth(), getLatestGroundOperation(),
    ])
    if (disposed) return
    const issues: LoadIssue[] = []
    function accept<T>(
      result: PromiseSettledResult<T>,
      key: string,
      label: string,
      apply: (value: T) => void,
    ): void {
      if (result.status === 'fulfilled') apply(result.value)
      else issues.push({ key, label, message: errorText(result.reason, '请求失败') })
    }
    accept(results[0], 'status', '运行状态', (value) => { status.value = value })
    accept(results[1], 'profile', '无人值守配置', (value) => { profile.value = value })
    accept(results[2], 'trains', '正线车辆', (value) => { trains.value = value.items })
    accept(results[3], 'ping', '长 Ping', (value) => { pingTargets.value = value.items })
    accept(results[4], 'deep', '深度采集', (value) => { deepCollections.value = value.items })
    accept(results[5], 'timeline', '时间轴', (value) => { timeline.value = value.items })
    accept(results[6], 'archives', '历史归档', (value) => { archives.value = value.items })
    accept(results[7], 'health', '系统健康', (value) => { health.value = value })
    accept(results[8], 'operation', '运行操作', (value) => { currentOperation.value = value })
    loadIssues.value = issues
    if (!silent && issues.length) {
      ElMessage.error(issues.length === results.length ? '地面无人值守数据加载失败' : `部分数据加载失败（${issues.length} 项）`)
    }
  } finally {
    if (!silent) loading.value = false
  }
}
function schedulePoll(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(async () => {
    if (!document.hidden) await loadAll(true)
    if (!document.hidden && activeTab.value === 'syslog') await loadSyslog()
    if (
      !document.hidden
      && activeTab.value === 'ping'
      && selectedPingTarget.value
      && pingAutoRefresh.value
      && !pingSeriesLoading.value
    ) {
      await showPingSeries(selectedPingTarget.value, true)
    }
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
  try {
    const result = await callback()
    if (isActionResponse(result)) {
      ElMessage.success(result.message)
      if (result.operation_id) currentOperation.value = await getLatestGroundOperation()
    }
    await loadAll(true)
  }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.action_failed', '无人值守操作失败'))) }
  finally { action.value = '' }
}
async function submitStop(archive: boolean): Promise<void> {
  const message = archive
    ? '将先正常停止并关闭全部活动文件，再创建正式归档。仅在 ZIP 生成和完整性校验成功后清理已归档 active 数据；归档失败时保留原始数据。'
    : '将停止新的调度、长 Ping 和 UDP 接收，清空内存队列并关闭原始文件，保存汇总但不执行归档。'
  await ElMessageBox.confirm(message, archive ? '确认停止并归档' : '确认正常停止', {
    type: 'warning',
    confirmButtonText: archive ? '停止并归档' : '正常停止',
    cancelButtonText: '取消',
  })
  await runAction(archive ? 'archive' : 'stop', archive ? stopAndArchiveGroundRun : stopGroundRun)
}
async function showPingSeries(row: GroundPingTarget, silent = false): Promise<void> {
  const range = pingTimeRange()
  if (pingRange.value === 'custom' && !range.start_time) {
    if (!silent) ElMessage.warning('请选择自定义开始和结束时间')
    return
  }
  selectedPingTarget.value = row
  if (!silent) pingSeriesLoading.value = true
  try {
    pingSeries.value = await getGroundPingSeries({
      run_id: status.value?.run_id || undefined,
      target_ip: row.target_ip,
      include_warmup: includeWarmup.value,
      max_points: 3000,
      ...range,
    })
  } catch (reason) {
    if (!silent) ElMessage.error(errorText(reason, '长 Ping 逐包数据读取失败'))
  } finally {
    if (!silent) pingSeriesLoading.value = false
  }
}
async function loadSyslog(): Promise<void> {
  syslogLoading.value = true
  try {
    const result = await listGroundSyslogRecords({
      run_id: status.value?.run_id || undefined,
      train_id: syslogFilter.trainId,
      mr_name: syslogFilter.mrName,
      source_ip: syslogFilter.sourceIp,
      severity: syslogFilter.severity,
      keyword: syslogFilter.keyword,
      page: syslogFilter.page,
      page_size: syslogFilter.pageSize,
    })
    syslogRecords.value = result.items
    syslogTotal.value = result.total
  } catch (reason) {
    ElMessage.error(errorText(reason, 'Syslog 日志读取失败'))
  } finally {
    syslogLoading.value = false
  }
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
  const target = pingTargets.value.find((item) => item.train_id === row.train_id)
  if (target) void showPingSeries(target)
}
async function showTrainTimeline(row: GroundTrain): Promise<void> {
  timelineFilter.query = row.train_no || row.train_name
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
function pingTimeRange(): { start_time?: string; end_time?: string } {
  const end = new Date()
  if (pingRange.value === 'custom') {
    const [startValue, endValue] = pingCustomRange.value || []
    return startValue && endValue
      ? { start_time: startValue.toISOString(), end_time: endValue.toISOString() }
      : {}
  }
  const durationMs = pingRange.value === '5m' ? 5 * 60_000 : pingRange.value === '1h' ? 60 * 60_000 : 30 * 60_000
  return {
    start_time: new Date(end.getTime() - durationMs).toISOString(),
    end_time: end.toISOString(),
  }
}
function duration(seconds: number): string { const minutes = Math.floor(seconds / 60); return `${minutes} 分 ${seconds % 60} 秒` }
function metric(value: number | null, unit: string): string { return value == null ? '—' : `${value.toFixed(2)} ${unit}` }
function bytes(value: number): string { if (!value) return '0 B'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024))); return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}` }
function errorText(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function isActionResponse(value: unknown): value is GroundActionResponse {
  return Boolean(value && typeof value === 'object' && 'accepted' in value && 'message' in value)
}
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' { if (['RUNNING', 'COVERED', 'READY', 'FRESH', 'MAINLINE'].includes(value)) return 'success'; if (['PAUSED', 'PARTIAL', 'STALE', 'MAINLINE_STATIONARY', 'WARNING'].includes(value)) return 'warning'; if (['ERROR', 'FAILED', 'CRITICAL'].includes(value)) return 'danger'; return 'info' }

onMounted(() => { void loadAll(); void loadLocalAddresses(); schedulePoll() })
watch(activeTab, (value) => { if (value === 'syslog' && !syslogRecords.value.length) void loadSyslog() })
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
        <el-button :icon="SwitchButton" :loading="action === 'stop'" :disabled="!running || operationActive" @click="submitStop(false)">{{ t('ground.stop', '正常停止') }}</el-button>
        <el-button :icon="Box" type="danger" plain :loading="action === 'archive'" :disabled="!running || operationActive" @click="submitStop(true)">{{ t('ground.stop_archive', '停止并归档') }}</el-button>
      </div>
    </header>

    <section v-if="currentOperation" class="operation-band" :class="`operation-${currentOperation.operation_state.toLocaleLowerCase()}`">
      <div class="operation-heading">
        <div>
          <b>{{ currentOperation.operation_type === 'STOP_AND_ARCHIVE' ? '停止并归档' : '正常停止' }}</b>
          <span>{{ groundOperationStageLabel(currentOperation.operation_stage) }}</span>
        </div>
        <el-tag :type="currentOperation.operation_state === 'FAILED' ? 'danger' : currentOperation.operation_state === 'COMPLETED' ? 'success' : 'warning'">
          {{ groundStatusLabel(currentOperation.operation_state) }}
        </el-tag>
      </div>
      <el-progress :percentage="currentOperation.progress_percent" :status="currentOperation.operation_state === 'FAILED' ? 'exception' : currentOperation.operation_state === 'COMPLETED' ? 'success' : undefined" />
      <p>{{ currentOperation.message }}<span v-if="currentOperation.failure_reason">：{{ currentOperation.failure_reason }}</span></p>
      <small>操作编号 {{ currentOperation.operation_id }} · 最后更新 {{ currentOperation.updated_at }}</small>
    </section>

    <section v-if="loadIssues.length" class="load-warning">
      <el-alert
        title="地面无人值守部分数据未加载"
        :description="loadIssueDescription"
        type="error"
        :closable="false"
        show-icon
      />
      <el-button :icon="Refresh" :loading="loading" @click="loadAll()">重新加载</el-button>
    </section>

    <el-tabs v-model="activeTab" class="ground-tabs">
      <el-tab-pane :label="t('ground.overview', '运行概览')" name="overview">
        <section class="overview-band">
          <div class="status-line">
            <span>{{ t('ground.current_site', '当前局点') }} <b>{{ status?.site_id || '—' }}</b></span>
            <el-tag :type="status ? statusType(status.state) : 'danger'">{{ status ? groundStatusLabel(status.state) : '状态未加载' }}</el-tag>
            <el-switch v-if="profile" v-model="profile.enabled" :active-text="t('ground.enabled', '启用无人值守')" @change="saveProfile()" />
            <span class="muted">{{ t('ground.pause_note', '暂停调度时 AC 轮询与长 Ping 继续') }}</span>
          </div>
          <div class="metric-grid">
            <article><span>当前运行模式</span><strong>{{ status ? groundRunModeLabel(status.running_mode) : '—' }}</strong><small>{{ !status ? '等待运行状态加载' : status.running_mode === 'LIGHTWEIGHT' ? '不启动 SSH 深度 MR 采集' : '包含深度 MR 采集' }}</small></article>
            <article><span>{{ t('ground.window', '配置运行时间') }}</span><strong>{{ status?.schedule_start_time }} - {{ status?.schedule_end_time }}</strong></article>
            <article><span>{{ t('ground.next_start', '下一次启动') }}</span><strong>{{ status?.next_start_at || '—' }}</strong></article>
            <article><span>{{ t('ground.next_end', '下一次结束') }}</span><strong>{{ status?.next_end_at || '—' }}</strong></article>
            <article><span>{{ t('ground.ac_updated', 'AC 最近更新') }}</span><strong>{{ status?.ac_last_updated_at || '—' }}</strong></article>
            <article><span>{{ t('ground.mainline_trains', '正线列车') }}</span><strong>{{ status?.mainline_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.ping_mrs', 'Ping 中 MR') }}</span><strong>{{ status?.ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.active_deep', '当前深度采集车辆') }}</span><strong>{{ status?.active_deep_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.covered_today', '今日已完成 / 未完成') }}</span><strong>{{ status?.covered_train_count ?? 0 }} / {{ status?.incomplete_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.disk_usage', '当前占用 / 磁盘剩余') }}</span><strong>{{ bytes(status?.disk_used_bytes ?? 0) }} / {{ bytes(status?.disk_free_bytes ?? 0) }}</strong><el-tag size="small" :type="statusType(status?.disk_status || '')">{{ groundStatusLabel(status?.disk_status) }}</el-tag></article>
            <article><span>{{ t('ground.latest_archive', '最近归档') }}</span><strong>{{ status?.latest_archive_status ? groundStatusLabel(status.latest_archive_status) : '—' }}</strong><small>{{ status?.latest_archive_message }}</small></article>
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
          <template #cell-eligibility_status="{ row }"><el-tag size="small" :type="statusType(row.eligibility_status)">{{ groundStatusLabel(row.eligibility_status) }}</el-tag></template>
          <template #cell-coverage_status="{ row }"><el-tag size="small" :type="statusType(row.coverage_status)">{{ groundStatusLabel(row.coverage_status) }}</el-tag></template>
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
        <div class="table-frame ping-table"><NcDataTable :data="filteredPing" :columns="pingColumns" table-id="ground-ping" route-key="rail-ground-unattended" row-key="target_ip" compact>
          <template #cell-actions="{ row }"><el-button size="small" text type="primary" @click="showPingSeries(row)">查看曲线</el-button></template>
        </NcDataTable></div>
        <section v-if="selectedPingTarget" v-loading="pingSeriesLoading" class="ping-detail">
          <div class="detail-heading">
            <div><h2>{{ selectedPingTarget.train_no }} · {{ selectedPingTarget.mr_name || selectedPingTarget.mr_position_code }} · {{ selectedPingTarget.target_ip }}</h2><p>逐包位置使用采样时快照，丢包点在降采样时优先保留。</p></div>
          </div>
          <div class="toolbar">
            <el-select v-model="pingRange" aria-label="长 Ping 时间范围" @change="showPingSeries(selectedPingTarget)">
              <el-option label="最近 5 分钟" value="5m" />
              <el-option label="最近 30 分钟" value="30m" />
              <el-option label="最近 1 小时" value="1h" />
              <el-option label="自定义时间" value="custom" />
            </el-select>
            <el-date-picker
              v-if="pingRange === 'custom'"
              v-model="pingCustomRange"
              type="datetimerange"
              start-placeholder="开始时间"
              end-placeholder="结束时间"
              @change="showPingSeries(selectedPingTarget)"
            />
            <el-checkbox v-model="includeWarmup" @change="showPingSeries(selectedPingTarget)">显示预热样本</el-checkbox>
            <el-checkbox v-model="pingAutoRefresh">自动刷新</el-checkbox>
            <el-button :icon="Refresh" @click="showPingSeries(selectedPingTarget)">刷新曲线</el-button>
          </div>
          <div class="coverage-strip">
            <span>原始样本 <b>{{ pingSeries?.raw_sample_count ?? 0 }}</b></span>
            <span>有效样本 <b>{{ pingSeries?.effective_sample_count ?? 0 }}</b></span>
            <span>预热忽略 <b>{{ pingSeries?.ignored_sample_count ?? 0 }}</b></span>
            <span>丢包区段 <b>{{ pingSeries?.loss_windows.length ?? 0 }}</b></span>
          </div>
          <GroundPingChart :series="pingSeries" />
          <h3>丢包区段</h3>
          <el-table :data="pingSeries?.loss_windows || []" size="small" max-height="260" empty-text="暂无丢包区段">
            <el-table-column prop="started_at" label="开始时间" min-width="180" />
            <el-table-column prop="ended_at" label="结束时间" min-width="180" />
            <el-table-column prop="duration_seconds" label="持续时间（秒）" width="130" />
            <el-table-column prop="loss_count" label="丢包数" width="90" />
            <el-table-column prop="mr_name" label="MR" min-width="150" />
            <el-table-column prop="current_ap_name" label="AP" min-width="150" />
            <el-table-column prop="station" label="站点" min-width="130" />
            <el-table-column prop="section" label="区间" min-width="130" />
            <el-table-column prop="ap_transition_context" label="AP 切换前后" min-width="140"><template #default="{ row }">{{ groundTransitionContextLabel(row.ap_transition_context) }}</template></el-table-column>
            <el-table-column prop="position_quality" label="位置质量" min-width="110"><template #default="{ row }">{{ groundStatusLabel(row.position_quality) }}</template></el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.deep_collection', '深度采集')" name="deep">
        <el-alert v-if="profile && !profile.deep_collection_master_enabled" title="当前为轻量模式：深度采集已关闭，历史记录仍可查看。" type="info" :closable="false" show-icon />
        <div class="coverage-strip"><span v-for="value in ['COLLECTING','WAITING','NOT_SEEN','PARTIAL','COVERED','EXCLUDED']" :key="value"><b>{{ deepCollections.filter((row) => row.status === value).length }}</b>{{ groundStatusLabel(value) }}</span></div>
        <div class="table-frame"><NcDataTable :data="deepCollections" :columns="deepColumns" table-id="ground-deep" route-key="rail-ground-unattended" row-key="train_id" compact>
          <template #cell-status="{ row }"><el-tag size="small" :type="statusType(row.status)">{{ groundStatusLabel(row.status) }}</el-tag></template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.timeline', '时间轴')" name="timeline">
        <div class="toolbar">
          <el-input v-model="timelineFilter.query" clearable placeholder="设备名称、列车号或 CT/CW" />
          <el-select v-model="timelineFilter.eventType" clearable placeholder="事件类型">
            <el-option v-for="value in ['ap_transition', 'mesh_linkup', 'mesh_linkdown', 'mesh_activelink_switch', 'ifnet_phy_updown', 'ping_loss_pattern', 'run_started', 'run_completed', 'stop_failed']" :key="value" :label="groundEventLabel(value)" :value="value" />
          </el-select>
          <el-button :icon="Refresh" @click="loadAll()">{{ t('common.query', '查询') }}</el-button>
        </div>
        <div class="table-frame"><NcDataTable :data="filteredTimeline" :columns="timelineColumns" table-id="ground-timeline" route-key="rail-ground-unattended" row-key="event_id" compact /></div>
      </el-tab-pane>

      <el-tab-pane label="Syslog 日志" name="syslog">
        <div class="toolbar">
          <el-input v-model="syslogFilter.trainId" clearable placeholder="列车 ID" />
          <el-input v-model="syslogFilter.mrName" clearable placeholder="MR 设备名称" />
          <el-input v-model="syslogFilter.sourceIp" clearable placeholder="来源 IP" />
          <el-select v-model="syslogFilter.severity" clearable placeholder="严重级别">
            <el-option label="提示" value="info" /><el-option label="警告" value="warning" /><el-option label="错误" value="error" />
          </el-select>
          <el-input v-model="syslogFilter.keyword" clearable placeholder="原始内容关键字" />
          <el-button :icon="Refresh" :loading="syslogLoading" @click="syslogFilter.page = 1; loadSyslog()">查询</el-button>
        </div>
        <div class="table-frame"><NcDataTable :data="syslogRecords" :columns="syslogColumns" table-id="ground-syslog" route-key="rail-ground-unattended" row-key="global_receive_sequence" compact /></div>
        <el-pagination
          v-model:current-page="syslogFilter.page"
          v-model:page-size="syslogFilter.pageSize"
          :total="syslogTotal"
          :page-sizes="[50, 100, 200, 500]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadSyslog"
          @size-change="syslogFilter.page = 1; loadSyslog()"
        />
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
          <template #cell-archive_status="{ row }"><el-tag size="small" :type="statusType(row.archive_status)">{{ groundStatusLabel(row.archive_status) }}</el-tag></template>
          <template #cell-actions="{ row }"><div class="row-actions"><el-button size="small" text type="primary" @click="showArchive(row)">{{ t('common.view', '查看') }}</el-button><el-button :icon="Download" size="small" text circle :title="t('common.download', '下载汇总')" @click="downloadArchiveSummary(row)" /><el-button :icon="Delete" size="small" text type="danger" circle :title="t('common.delete', '删除')" @click="removeArchive(row)" /></div></template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.settings', '设置')" name="settings">
        <el-empty v-if="!profile" class="settings-empty" description="无人值守配置未加载">
          <p class="muted">{{ profileLoadError || '请确认 Backend 已完成无人值守服务初始化。' }}</p>
          <el-button :icon="Refresh" :loading="loading" type="primary" @click="loadAll()">重新加载配置</el-button>
        </el-empty>
        <el-form v-else :model="profile" label-position="top" class="settings-form">
          <section><h2>{{ t('ground.schedule', '运行时间与 AC') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.start_time', '开始时间')"><el-time-select v-model="profile.schedule_start_time" start="00:00" step="00:05" end="23:55" /></el-form-item>
            <el-form-item :label="t('ground.end_time', '结束时间')"><el-time-select v-model="profile.schedule_end_time" start="00:00" step="00:05" end="23:55" /></el-form-item>
            <el-form-item :label="t('ground.timezone', '时区')">
              <el-select v-model="profile.timezone" filterable allow-create>
                <el-option label="北京时间（Asia/Shanghai）" value="Asia/Shanghai" />
                <el-option label="协调世界时（UTC）" value="UTC" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('ground.ac_poll', 'AC 轮询间隔（秒）')"><el-input-number v-model="profile.ac_poll_interval_seconds" :min="3" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.stationary', '同 AP 静止阈值（分钟）')"><el-input-number v-model="profile.stationary_exclusion_minutes" :min="1" :max="180" /></el-form-item>
            <el-form-item :label="t('ground.ac_grace', 'AC 异常 Ping 宽限（秒）')"><el-input-number v-model="profile.ac_stale_grace_seconds" :min="0" :max="3600" /></el-form-item>
            <el-form-item :label="t('ground.correlation_tolerance', 'AC/Ping 关联偏差（秒）')"><el-input-number v-model="profile.ac_ping_correlation_tolerance_seconds" :min="1" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.switch_window', 'AP 切换前 / 后窗口（秒）')"><div class="inline-numbers"><el-input-number v-model="profile.ap_switch_before_seconds" :min="0" :max="60" /><el-input-number v-model="profile.ap_switch_after_seconds" :min="0" :max="60" /></div></el-form-item>
          </div></section>
          <section><h2>{{ t('ground.deep_budget', '深度采集预算') }}</h2>
            <div class="mode-switch">
              <el-switch v-model="profile.deep_collection_master_enabled" active-text="启用深度采集" />
              <span>{{ profile.deep_collection_master_enabled ? '标准模式：运行 AC 轮询、长 Ping、Syslog 和深度 MR 采集。' : '轻量模式：仅运行 AC 轮询、长 Ping、Syslog 和位置关联，不启动 SSH 深度 MR 采集。' }}</span>
            </div>
            <div class="form-grid" :class="{ 'budget-disabled': !profile.deep_collection_master_enabled }">
            <el-form-item :label="t('ground.max_trains', '最大活动列车')"><el-input-number v-model="profile.max_active_trains" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.max_mrs', '最大活动 MR')"><el-input-number v-model="profile.max_active_mrs" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="16" /></el-form-item>
            <el-form-item :label="t('ground.max_starting', '最大启动中 MR')"><el-input-number v-model="profile.max_starting_mrs" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.max_finalizing', '最大最终化 MR')"><el-input-number v-model="profile.max_finalizing_mrs" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.minimum_duration', '最低有效时长（分钟）')"><el-input-number v-model="profile.minimum_valid_collection_minutes" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="720" /></el-form-item>
            <el-form-item :label="t('ground.preferred_duration', '建议采集时长（分钟）')"><el-input-number v-model="profile.preferred_collection_minutes" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="720" /></el-form-item>
            <el-form-item :label="t('ground.maximum_duration', '最大采集时长（分钟）')"><el-input-number v-model="profile.maximum_collection_minutes" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="1440" /></el-form-item>
            <el-form-item :label="t('ground.start_jitter', '启动错峰（秒）')"><el-input-number v-model="profile.start_jitter_seconds" :disabled="!profile.deep_collection_master_enabled" :min="0" :max="60" /></el-form-item>
            <el-form-item :label="t('ground.start_batch', '每批启动 MR 数')"><el-input-number v-model="profile.start_batch_size" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="4" /></el-form-item>
          </div></section>
          <section><h2>{{ t('ground.ping_and_storage', '长 Ping 与存储') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.ping_interval', 'Ping 间隔（ms）')"><el-input-number v-model="profile.fleet_ping_interval_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item :label="t('ground.ping_timeout', 'Ping 超时（ms）')"><el-input-number v-model="profile.fleet_ping_timeout_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item :label="t('ground.packet_size', '包大小（字节）')"><el-input-number v-model="profile.fleet_ping_packet_size" :min="1" :max="65507" /></el-form-item>
            <el-form-item :label="t('ground.shard_size', '每个 fping 分片目标数')"><el-input-number v-model="profile.fleet_ping_shard_size" :min="2" :max="32" /></el-form-item>
            <el-form-item label="启动预热忽略时间（秒）"><el-input-number v-model="profile.fleet_ping_warmup_seconds" :min="0" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.detail_retention', '详细数据保留天数')"><el-select v-model="profile.detail_retention_days"><el-option v-for="day in [7,15,30,60,90,180]" :key="day" :label="`${day} 天`" :value="day" /></el-select></el-form-item>
            <el-form-item :label="t('ground.summary_retention', '汇总保留天数')"><el-input-number v-model="profile.summary_retention_days" :min="profile.detail_retention_days" :max="3650" /></el-form-item>
            <el-form-item :label="t('ground.warning_space', '空间预警阈值（GB）')"><el-input-number v-model="profile.storage_warning_free_gb" :min="0.1" :max="1024" /></el-form-item>
            <el-form-item :label="t('ground.critical_space', '严重空间阈值（GB）')"><el-input-number v-model="profile.storage_critical_free_gb" :min="0.1" :max="1024" /></el-form-item>
          </div><p class="muted">{{ t('ground.storage_path', '存储路径：当前局点 / files / rail_transit / ground_unattended。深度会话 ZIP 仍保存在既有 Online MR 目录，每日归档只保存引用。') }}</p></section>
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
        <el-descriptions-item :label="t('ground.archive_status', '归档状态')">{{ groundStatusLabel(selectedArchive.archive_status) }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.ping_samples', 'Ping 样本')">{{ selectedArchive.ping_sample_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.covered_trains', '覆盖列车')">{{ selectedArchive.covered_train_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.complete_sessions', '完整会话')">{{ selectedArchive.complete_session_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.partial_sessions', '部分会话')">{{ selectedArchive.partial_session_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.archive_size', '归档大小')">{{ bytes(selectedArchive.archive_size_bytes) }}</el-descriptions-item>
        <el-descriptions-item :label="t('ground.retention_until', '保留截止')">{{ selectedArchive.retention_until }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog v-model="trainDialog" :title="t('ground.train_detail', '列车无人值守详情')" width="min(820px, 94vw)">
      <template v-if="selectedTrain">
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('ground.train', '列车')">{{ selectedTrain.train_no || selectedTrain.train_name }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.eligibility', '正线判断')"><el-tag :type="statusType(selectedTrain.eligibility_status)">{{ groundStatusLabel(selectedTrain.eligibility_status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item :label="t('ground.current_ap', '当前 AP')">{{ selectedTrain.current_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="位置匹配等级">{{ groundStatusLabel(selectedTrain.location_match_level) }}</el-descriptions-item>
          <el-descriptions-item label="原始 AP 名称">{{ selectedTrain.raw_peer_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原始 AP MAC">{{ selectedTrain.raw_peer_ap_mac || '—' }}</el-descriptions-item>
          <el-descriptions-item label="解析后 AP">{{ selectedTrain.resolved_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="规范站点">{{ selectedTrain.canonical_station_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="匹配依据" :span="2">{{ selectedTrain.location_match_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.same_ap_duration', '同 AP 停留')">{{ duration(selectedTrain.same_ap_duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.exclusion_reason', '排除原因')" :span="2">{{ selectedTrain.exclusion_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT 会话">{{ selectedTrainCollection?.ct_session_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CW 会话">{{ selectedTrainCollection?.cw_session_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT Syslog">{{ groundStatusLabel(endpoint(selectedTrain, 'CT')?.syslog_status) }}</el-descriptions-item>
          <el-descriptions-item label="CW Syslog">{{ groundStatusLabel(endpoint(selectedTrain, 'CW')?.syslog_status) }}</el-descriptions-item>
        </el-descriptions>
        <section v-for="mrEndpoint in selectedTrain.endpoints" :key="`loghost:${mrEndpoint.mr_id || mrEndpoint.endpoint}`" class="loghost-section">
          <div class="network-status">
            <b>{{ mrEndpoint.endpoint }} · 设备现有日志主机</b>
            <span>NetConsole 管理目标：{{ mrEndpoint.managed_target_ip || profile?.syslog_server_ip || '—' }}:{{ mrEndpoint.managed_target_port || profile?.syslog_server_port || '—' }}</span>
            <el-tag v-for="item in mrEndpoint.managed_target_statuses" :key="item" :type="item === 'TARGET_PRESENT' ? 'success' : item === 'TARGET_PORT_CONFLICT' ? 'danger' : 'info'">{{ groundStatusLabel(item) }}</el-tag>
          </div>
          <el-table :data="mrEndpoint.configured_log_hosts" size="small" empty-text="尚未执行配置检查">
            <el-table-column prop="ip" label="IP" min-width="130" />
            <el-table-column prop="port" label="端口" width="90" />
            <el-table-column prop="facility" label="Facility" width="100" />
            <el-table-column label="归属" min-width="160"><template #default="{ row }">{{ groundSourceLabel(row.source) }}</template></el-table-column>
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
          <el-button :disabled="!selectedTrainCollection?.ct_session_id" @click="openDeepSession(selectedTrainCollection?.ct_session_id || '')">{{ t('ground.open_ct_session', '打开 CT 会话') }}</el-button>
          <el-button :disabled="!selectedTrainCollection?.cw_session_id" @click="openDeepSession(selectedTrainCollection?.cw_session_id || '')">{{ t('ground.open_cw_session', '打开 CW 会话') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped>
.ground-page{display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0}.page-heading,.heading-actions,.status-line,.toolbar,.coverage-strip,.row-actions,.form-actions,.inline-numbers,.dialog-actions,.network-actions,.network-status,.boot-evidence,.operation-heading,.detail-heading,.mode-switch,.load-warning{display:flex;align-items:center;gap:10px}.page-heading,.operation-heading,.detail-heading{justify-content:space-between;flex-wrap:wrap}.page-heading h1{margin:2px 0 0;font-size:24px;letter-spacing:0}.eyebrow{margin:0;color:var(--el-color-primary);font-size:12px;font-weight:700;letter-spacing:0}.heading-actions,.toolbar,.dialog-actions,.network-actions,.network-status,.boot-evidence{flex-wrap:wrap}.operation-band{padding:12px 14px;border:1px solid var(--el-border-color);border-left:4px solid var(--el-color-warning);background:var(--el-fill-color-light)}.operation-band.operation-completed{border-left-color:var(--el-color-success)}.operation-band.operation-failed{border-left-color:var(--el-color-danger)}.operation-heading>div{display:flex;gap:12px;align-items:center}.operation-band p{margin:8px 0;color:var(--el-text-color-primary)}.operation-band small{color:var(--el-text-color-secondary)}.load-warning{align-items:flex-start}.load-warning :deep(.el-alert){min-width:0;flex:1}.ground-tabs{min-width:0}.overview-band{padding:2px 0}.status-line{min-height:42px;flex-wrap:wrap;border-bottom:1px solid var(--el-border-color-lighter)}.metric-grid,.health-grid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:1px;margin-top:12px;background:var(--el-border-color-lighter);border:1px solid var(--el-border-color-lighter)}.metric-grid article,.health-grid article{min-width:0;padding:12px;background:var(--el-bg-color)}.metric-grid span,.metric-grid small,.health-grid span,.health-grid small{display:block;color:var(--el-text-color-secondary);font-size:12px}.metric-grid strong,.health-grid strong{display:block;min-height:24px;margin:6px 0 3px;font-size:18px;letter-spacing:0;overflow-wrap:anywhere}.toolbar{min-height:42px}.toolbar .el-input{width:210px}.toolbar .el-select{width:130px}.toolbar .el-input-number{width:110px}.table-frame{height:clamp(360px,calc(100vh - 310px),680px);min-width:0;overflow:hidden;border-top:1px solid var(--el-border-color-lighter)}.ping-table{height:360px}.ping-detail{margin-top:16px;padding-top:14px;border-top:1px solid var(--el-border-color-lighter)}.ping-detail h2,.ping-detail h3{margin:0 0 8px}.ping-detail p{margin:0;color:var(--el-text-color-secondary);font-size:12px}.coverage-strip{flex-wrap:wrap;margin-bottom:8px}.coverage-strip span{display:flex;align-items:center;gap:5px;padding:5px 8px;background:var(--el-fill-color-light);border-radius:4px;color:var(--el-text-color-secondary);font-size:12px}.coverage-strip b{color:var(--el-text-color-primary);font-size:16px}.settings-empty{padding:48px 16px}.settings-empty .muted{max-width:720px;margin:0 auto 12px;overflow-wrap:anywhere}.settings-form{display:flex;flex-direction:column;gap:18px;max-width:1180px}.settings-form section{padding-bottom:16px;border-bottom:1px solid var(--el-border-color-lighter)}.settings-form h2{margin:0 0 12px;font-size:16px;letter-spacing:0}.form-grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:0 16px}.form-grid :deep(.el-input-number),.form-grid :deep(.el-select),.form-grid :deep(.el-input){width:100%}.mode-switch{align-items:flex-start;margin-bottom:12px}.mode-switch span{color:var(--el-text-color-secondary);font-size:12px}.budget-disabled{opacity:.66}.inline-numbers{width:100%}.priority-grid{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:8px}.muted{color:var(--el-text-color-secondary);font-size:12px}.network-actions{margin:12px 0}.network-status{margin:10px 0;padding:8px;background:var(--el-fill-color-light)}.network-ok{color:var(--el-color-success);font-size:12px}.network-error{color:var(--el-color-danger);font-size:12px}.loghost-section{margin-top:14px;padding-top:8px;border-top:1px solid var(--el-border-color-lighter)}.boot-evidence{margin:8px 0;color:var(--el-text-color-secondary);font-size:12px}.form-actions{position:sticky;bottom:0;padding:10px 0;background:var(--el-bg-color)}.dialog-actions{justify-content:flex-end;margin-top:14px}@media(max-width:1300px){.metric-grid,.health-grid{grid-template-columns:repeat(3,minmax(150px,1fr))}.form-grid{grid-template-columns:repeat(3,minmax(170px,1fr))}.priority-grid{grid-template-columns:repeat(4,minmax(110px,1fr))}}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}.metric-grid,.health-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.form-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}.priority-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}.table-frame{height:clamp(340px,calc(100vh - 350px),620px)}.ping-table{height:340px}}@media(max-width:620px){.metric-grid,.health-grid,.form-grid{grid-template-columns:1fr}.priority-grid{grid-template-columns:repeat(2,minmax(100px,1fr))}.heading-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.heading-actions .el-button{margin:0}.load-warning{flex-direction:column}.toolbar .el-input,.toolbar .el-select{width:100%}}
</style>
