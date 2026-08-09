<script setup lang="ts">
import { computed, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Box, CopyDocument, Delete, Download, FolderOpened, Refresh, SwitchButton, VideoPause, VideoPlay } from '@element-plus/icons-vue'

import {
  deleteGroundArchive, deleteGroundRunHistory, getGroundArchiveDetail, getGroundProfile, getGroundStatus, getGroundTrain, groundArchiveSummaryDownloadRequest, groundArchiveZipDownloadRequest, listGroundArchives,
  getGroundHealth, listGroundDeepCollectionRecords, listGroundDeepCollections, listGroundPingTargets, listGroundTimeline, listGroundTrains, requestGroundConfigCheck,
  openGroundArchiveDirectory, pauseGroundRun, resumeGroundRun, saveGroundProfile, setGroundTrainPriority, startGroundRun,
  stopAndArchiveGroundRun, stopGroundRun, saveGroundTrainPolicy, syncGroundInventory,
  checkGroundUdpPort, listLocalIpv4Addresses, recommendLocalSourceIp,
  getActiveGroundOperation, getGroundOperation, getGroundPingSeries, getGroundPingSeriesIncremental, getGroundSyslogTransportStatus,
  listGroundRuns, listGroundSyslogRecords, previewGroundSyslogDelete, probeGroundRawQueryTransportState, probeGroundSyslogTransportState, submitGroundSyslogDelete, verifyGroundArchive,
} from '../../api/groundUnattended'
import { apiErrorDetail } from '../../api/client'
import { getOnlineMrSession } from '../../api/onlineMr'
import GroundPingChart from '../../components/ground-unattended/GroundPingChart.vue'
import { NcDataTable, type NcTableColumn } from '../../components/table'
import NcFloatingWindow from '../../components/workspace/NcFloatingWindow.vue'
import NcLogWorkspace from '../../components/workspace/NcLogWorkspace.vue'
import { useAdaptiveTableHeight } from '../../composables/useAdaptiveTableHeight'
import { t } from '../../i18n/runtime'
import { downloadBackendResource } from '../../platform/runtime'
import { useWorkspaceStore } from '../../stores/workspace'
import type {
  GroundActionResponse, GroundArchive, GroundArchiveDetail, GroundDeepCollection, GroundDeepCollectionRecord, GroundDeepCollector, GroundPingSeries, GroundPingTarget, GroundProfile, GroundStatus,
  GroundHealth, GroundOperation, GroundPingSample, GroundQueryDiagnostics, GroundRun, GroundSyslogRecord,
  GroundSyslogDeleteFilters, GroundSyslogDeletePreview,
  GroundSyslogTransportStatus, GroundTimelineEvent, GroundTrain, LocalIpv4Address, SourceIpRecommendation, UdpPortCheck,
} from '../../types/groundUnattended'
import {
  groundDisplayNameSourceLabel, groundEventLabel, groundOperationStageLabel, groundRunModeLabel, groundSeverityLabel,
  groundSourceLabel, groundStatusLabel, groundTransitionContextLabel,
} from './groundUnattendedLabels'

const activeTab = ref('overview')
const router = useRouter()
const workspace = useWorkspaceStore()
const loading = ref(false)
const saving = ref(false)
const action = ref('')
const status = ref<GroundStatus | null>(null)
const profile = ref<GroundProfile | null>(null)
const trains = ref<GroundTrain[]>([])
const pingTargets = ref<GroundPingTarget[]>([])
const deepCollections = ref<GroundDeepCollection[]>([])
const selectedDeepCollector = ref<GroundDeepCollector | null>(null)
const deepRecords = ref<GroundDeepCollectionRecord[]>([])
const deepWindowOpen = ref(false)
const deepRecordsLoading = ref(false)
const deepCursor = ref('')
const deepCategory = ref('ALL')
const deepKeyword = ref('')
const deepPaused = ref(false)
const deepAutoRefresh = ref(true)
const timeline = ref<GroundTimelineEvent[]>([])
const archives = ref<GroundArchive[]>([])
const health = ref<GroundHealth | null>(null)
const activeOperation = ref<GroundOperation | null>(null)
const latestTerminalOperation = ref<GroundOperation | null>(null)
const runs = ref<GroundRun[]>([])
const selectedRunId = ref('')
const runHistoryDeleteLoading = ref(false)
const pingSeries = ref<GroundPingSeries | null>(null)
const selectedPingTarget = ref<GroundPingTarget | null>(null)
const pingWindowOpen = ref(false)
const pingSeriesLoading = ref(false)
const pingIncrementalLoading = ref(false)
const includeWarmup = ref(false)
const pingRange = ref<'run' | '5m' | '30m' | '1h' | 'custom'>('30m')
const pingCustomRange = ref<[Date, Date] | null>(null)
const pingAutoRefresh = ref(true)
const pingPaused = ref(false)
const pingFollowLatest = ref(true)
const pingCursor = ref('')
const pingInitialLoadSucceeded = ref(false)
const pingBackendState = ref<'ONLINE' | 'OFFLINE' | 'UNKNOWN'>('UNKNOWN')
const pingRequestId = ref('')
const pingErrorCode = ref('')
const pingLastAttemptAt = ref('')
const pingSeenSamples = new Set<string>()
const syslogRecords = ref<GroundSyslogRecord[]>([])
const syslogTotal = ref(0)
const syslogLoading = ref(false)
const syslogAutoRefresh = ref(true)
const syslogDiagnostics = ref<GroundQueryDiagnostics | null>(null)
const syslogTotalExact = ref(true)
const syslogBackendState = ref<'ONLINE' | 'OFFLINE' | 'UNKNOWN'>('UNKNOWN')
const syslogRequestId = ref('')
const syslogLastAttemptAt = ref('')
const syslogFailureCount = ref(0)
const syslogErrorCode = ref('')
const selectedSyslogRecord = ref<GroundSyslogRecord | null>(null)
const selectedSyslogRecords = ref<GroundSyslogRecord[]>([])
const syslogDetailDrawer = ref(false)
const syslogAdvancedFiltersOpen = ref(false)
const syslogDeleteDerived = ref(true)
const syslogDeleteLoading = ref(false)
const syslogDeletePreview = ref<GroundSyslogDeletePreview | null>(null)
const syslogTimeRange = ref<[Date, Date] | null>(null)
const syslogFilter = reactive({
  trainId: '', mrName: '', mrRole: '', sourceIp: '', systemName: '', facility: '', severity: '',
  identityStatus: '', eventType: '', eventFamily: '', commandSource: '', physicalState: '',
  correlationStatus: '', correlationConfidence: '', peerName: '', dataSource: '', keyword: '',
  startTime: '', endTime: '', page: 1, pageSize: 100,
})
const localIpv4Addresses = ref<LocalIpv4Address[]>([])
const sourceRecommendation = ref<SourceIpRecommendation | null>(null)
const udpPortCheck = ref<UdpPortCheck | null>(null)
const syslogTransport = ref<GroundSyslogTransportStatus | null>(null)
const syslogTransportLoading = ref(false)
const networkLoading = ref(false)
const showAllAddresses = ref(false)
const selectedArchive = ref<GroundArchiveDetail | null>(null)
const archiveDetailTab = ref('overview')
const selectedTrain = ref<GroundTrain | null>(null)
const archiveDialog = ref(false)
const trainDialog = ref(false)
const openingSessionId = ref('')
const trainFilter = ref('')
const pingFilter = reactive({ query: '', endpoint: '', station: '', section: '', minLoss: 0 })
const timelineFilter = reactive({ query: '', eventType: '' })
const timelinePage = ref(1)
const timelinePageSize = ref(100)
const timelineTotal = ref(0)
let pollTimer: number | undefined
let disposed = false
const requestControllers = new Map<string, AbortController>()
const requestFingerprints = new Map<string, string>()
const requestPromises = new Map<string, Promise<boolean>>()
const requestSequences = new Map<string, number>()
const requestFailureCounts = new Map<string, number>()
const requestNotifySequences = new Map<string, number>()
const lastPollAt = new Map<string, number>()
const dismissedTerminalOperationIds = new Set<string>()
let completedOperationTimer: number | undefined

interface LoadIssue {
  key: string
  label: string
  message: string
  code?: string
  requestId?: string
  attemptedAt?: string
  backendState?: 'ONLINE' | 'OFFLINE' | 'UNKNOWN'
}

const loadIssues = ref<LoadIssue[]>([])
const generalLoadIssues = computed(() => loadIssues.value.filter((item) => (
  item.key !== 'syslog' && !item.key.startsWith('ping-series')
)))
const syslogIssue = computed(() => loadIssues.value.find((item) => item.key === 'syslog') ?? null)
const pingIssue = computed(() => loadIssues.value.find((item) => item.key.startsWith('ping-series')) ?? null)
const loadIssueDescription = computed(() => generalLoadIssues.value.map((item) => `${item.label}：${item.message}`).join('；'))
const profileLoadError = computed(() => loadIssues.value.find((item) => item.key === 'profile')?.message || '')

const running = computed(() => Boolean(status.value && ['STARTING', 'RUNNING', 'PAUSED', 'STOPPING', 'FINALIZING', 'ARCHIVING'].includes(status.value.state)))
const operationActive = computed(() => Boolean(activeOperation.value && ['PENDING', 'RUNNING'].includes(activeOperation.value.operation_state)))
const visibleOperation = computed(() => activeOperation.value ?? latestTerminalOperation.value)
const selectedRun = computed(() => runs.value.find((row) => row.run_id === selectedRunId.value) ?? null)
const historicalRun = computed(() => Boolean(selectedRunId.value && selectedRunId.value !== status.value?.active_run_id))
const runHistoryDeleteBlocked = computed(() => (
  !selectedRun.value
  || !historicalRun.value
  || ['STARTING', 'RUNNING', 'PAUSED', 'STOPPING', 'FINALIZING', 'ARCHIVING'].includes(selectedRun.value.state)
))
const selectedPingHistorical = computed(() => Boolean(selectedPingTarget.value?.run_id && selectedPingTarget.value.run_id !== status.value?.active_run_id))
const syslogDeleteBlocked = computed(() => (
  !selectedRun.value
  || ['STARTING', 'RUNNING', 'PAUSED', 'STOPPING', 'FINALIZING', 'ARCHIVING', 'ERROR'].includes(selectedRun.value.state)
))
const syslogAdvancedFilterCount = computed(() => [
  syslogFilter.systemName,
  syslogFilter.facility,
  syslogFilter.severity,
  syslogFilter.identityStatus,
  syslogFilter.eventFamily,
  syslogFilter.commandSource,
  syslogFilter.physicalState,
  syslogFilter.correlationStatus,
  syslogFilter.correlationConfidence,
  syslogFilter.dataSource,
  syslogFilter.keyword,
].filter(Boolean).length)
const syslogHasActiveFilters = computed(() => Object.values(
  currentSyslogDeleteFilters(),
).some(Boolean))
const runScopedTab = computed(() => ['ping', 'deep', 'timeline', 'syslog'].includes(activeTab.value))
const archiveRecordCount = computed(() => selectedArchive.value?.files.reduce((total, row) => total + row.record_count, 0) ?? 0)
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
const trainTableHost = ref<HTMLElement | null>(null)
const pingTableHost = ref<HTMLElement | null>(null)
const deepTableHost = ref<HTMLElement | null>(null)
const archiveTableHost = ref<HTMLElement | null>(null)
const trainTableHeight = useAdaptiveTableHeight(trainTableHost, computed(() => filteredTrains.value.length), { maxVisibleRows: 18 })
const pingTableHeight = useAdaptiveTableHeight(pingTableHost, computed(() => filteredPing.value.length), { maxVisibleRows: 20 })
const deepTableHeight = useAdaptiveTableHeight(deepTableHost, computed(() => deepCollections.value.length), { maxVisibleRows: 18 })
const archiveTableHeight = useAdaptiveTableHeight(archiveTableHost, computed(() => archives.value.length), { maxVisibleRows: 18 })
const trainTableMaxHeight = trainTableHeight.maxHeight
const pingTableMaxHeight = pingTableHeight.maxHeight
const deepTableMaxHeight = deepTableHeight.maxHeight
const archiveTableMaxHeight = archiveTableHeight.maxHeight
const visibleIpv4Addresses = computed(() => localIpv4Addresses.value.filter((row) => showAllAddresses.value || !row.is_virtual))
const localIpv4Values = computed(() => new Set(localIpv4Addresses.value.map((row) => row.ipv4)))
const returnAddressIsLocal = computed(() => Boolean(profile.value?.syslog_server_ip && localIpv4Values.value.has(profile.value.syslog_server_ip)))
const listenAddressIsLocal = computed(() => Boolean(profile.value && (profile.value.udp_listen_host === '0.0.0.0' || localIpv4Values.value.has(profile.value.udp_listen_host))))
const startBlockedReason = computed(() => {
  const transport = syslogTransport.value
  if (!profile.value?.enabled) return ''
  if (!transport) return '正在检查 MR 日志回传地址，请稍候。'
  if (transport.return_address_status === 'NOT_LOCAL') {
    return `MR 日志回传地址 ${transport.configured_return_ip}:${transport.configured_return_port} 当前不属于本机。请前往设置选择本机地址，或确认使用外部/NAT 地址。`
  }
  if (transport.return_address_status === 'EMPTY') return '尚未配置 MR 日志回传地址，请前往设置。'
  if (transport.return_address_status === 'INVALID') return 'MR 日志回传地址无效，请前往设置。'
  return ''
})
const pingAvailability = computed(() => (
  pingSeries.value?.diagnostics.data_availability
  || selectedPingTarget.value?.data_availability
  || 'MISSING'
))
const pingEmptyDescription = computed(() => {
  if (pingIssue.value) return pingIssue.value.message
  if (pingAvailability.value === 'SUMMARY_ONLY') return '本次运行仅保留汇总，无法生成逐包曲线。'
  if (pingAvailability.value === 'CORRUPT') return '逐包原始文件或 READY 归档损坏，已停止读取曲线数据。'
  if (pingAvailability.value === 'MISSING') return '本次运行缺少逐包原始数据，请查看文件诊断。'
  if (pingSeries.value?.active) return '当前目标尚未产生 Ping 样本，窗口将继续等待新增样本。'
  if (pingRange.value !== 'run') return '当前时间范围内没有样本，可切换到完整运行时段。'
  return '本次运行时段内没有逐包 Ping 样本。'
})
const pingLiveStats = computed(() => {
  const series = pingSeries.value
  const points = pingSeries.value?.points ?? []
  const latest = points.at(-1)
  return {
    success: series?.success_count ?? 0,
    loss: series?.loss_count ?? 0,
    lossRate: series?.effective_sample_count
      ? (series.loss_count / series.effective_sample_count) * 100
      : 0,
    currentRtt: series?.current_rtt_ms ?? null,
    averageRtt: series?.average_rtt_ms ?? null,
    maxRtt: series?.max_rtt_ms ?? null,
    currentAp: latest?.current_ap_name || selectedPingTarget.value?.current_ap_name || '',
    station: latest?.station || selectedPingTarget.value?.station || '',
    section: latest?.section || selectedPingTarget.value?.section || '',
    latestAt: latest?.ts || pingSeries.value?.latest_timestamp || '',
  }
})
const locationStats = computed(() => ({
  ap: trains.value.filter((row) => String(row.location_match_level || '').startsWith('AP_')).length,
  station: trains.value.filter((row) => String(row.location_match_level || '').startsWith('STATION_')).length,
  unmatched: trains.value.filter((row) => row.eligibility_status === 'AP_UNMATCHED').length,
  excluded: trains.value.filter((row) => ['DEPOT', 'PARKING_LOT', 'STORAGE_TRACK'].includes(row.eligibility_status)).length,
}))

const trainColumns: NcTableColumn<GroundTrain>[] = [
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', fixed: 'left' },
  { key: 'location_class', label: '位置类型', valueType: 'status', displayValue: (row) => groundStatusLabel(row.location_class) },
  { key: 'eligibility_status', label: t('ground.eligibility', '正线判断'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.eligibility_status) },
  { key: 'participates_in_mainline', label: '是否正线', valueType: 'status', displayValue: (row) => row.participates_in_mainline ? '是' : '否' },
  { key: 'ping_reason', label: 'Ping 纳入原因', valueType: 'description', minWidth: 220, displayValue: (row) => row.ping_reason_text || '未评估' },
  { key: 'deep_state', label: '深采资格', valueType: 'status', minWidth: 180, displayValue: (row) => row.deep_collection_reason_text || '未评估' },
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
  { key: 'ct_radio', label: 'CT 射频', valueType: 'status', displayValue: (row) => groundStatusLabel(endpoint(row, 'CT')?.radio_overall_state || 'UNKNOWN') },
  { key: 'cw_radio', label: 'CW 射频', valueType: 'status', displayValue: (row) => groundStatusLabel(endpoint(row, 'CW')?.radio_overall_state || 'UNKNOWN') },
  { key: 'ct_control', label: 'CT 控制来源', valueType: 'status', displayValue: (row) => groundControlSourceLabel(endpoint(row, 'CT')?.cfg_command_source) },
  { key: 'cw_control', label: 'CW 控制来源', valueType: 'status', displayValue: (row) => groundControlSourceLabel(endpoint(row, 'CW')?.cfg_command_source) },
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
  { key: 'location_class', label: '位置类型', valueType: 'status', displayValue: (row) => groundStatusLabel(row.location_class) },
  { key: 'ping_inclusion_reason', label: 'Ping 纳入原因', valueType: 'description', minWidth: 190 },
  { key: 'mainline_eligible', label: '正线', valueType: 'status', displayValue: (row) => row.mainline_eligible ? '是' : '否' },
  { key: 'deep_collection_eligible', label: '深采资格', valueType: 'status', displayValue: (row) => row.deep_collection_eligible ? '符合资格' : '不具备资格' },
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
  { key: 'deep_state', label: '深采运行状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.deep_state) },
  { key: 'deep_state_reason', label: '状态说明', valueType: 'description', minWidth: 220 },
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
  { key: 'collector_data', label: '实时证据', valueType: 'description', minWidth: 180, displayValue: (row) => row.collectors.map((item) => `${item.mr_role}: ${bytes(item.bytes_written)} / ${item.last_record_at || '暂无记录'}`).join('；') || '尚未创建会话' },
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
  { key: 'resolution_status', label: 'AP 解析', valueType: 'status', displayValue: (row) => groundStatusLabel(row.resolution_status) },
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
  { key: 'actions', label: t('ground.actions', '操作'), valueType: 'actions', fixed: 'right', width: 230, hideable: false },
]
const syslogColumns: NcTableColumn<GroundSyslogRecord>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 48, fixed: 'left', hideable: false },
  { key: 'receive_time', label: '接收时间', valueType: 'datetime', fixed: 'left', width: 180 },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', width: 180 },
  { key: 'train_no', label: '列车', valueType: 'name', displayValue: (row) => row.train_no || '未识别' },
  { key: 'mr_name', label: 'MR 设备', valueType: 'text', displayValue: (row) => row.mr_name || '未知 MR' },
  { key: 'mr_role', label: '端点', valueType: 'status' },
  { key: 'source_ip', label: '来源 IP', valueType: 'ip' },
  { key: 'system_name', label: '设备系统名', valueType: 'text' },
  { key: 'facility', label: 'Facility', valueType: 'text' },
  { key: 'severity', label: '级别', valueType: 'status', displayValue: (row) => groundSeverityLabel(row.severity) },
  { key: 'event_family', label: '事件族', valueType: 'status' },
  { key: 'event_type', label: '事件', valueType: 'status', displayValue: (row) => groundEventLabel(row.event_type) },
  { key: 'peer_name', label: '当前 AP', valueType: 'name', displayValue: (row) => row.peer_name || row.peer_mac || '—' },
  { key: 'peer_mac', label: 'Peer MAC', valueType: 'mac' },
  { key: 'previous_peer_name', label: '原 AP', valueType: 'name', displayValue: (row) => row.previous_peer_name || row.previous_peer_mac || '—' },
  { key: 'rssi', label: 'RSSI', valueType: 'number', displayValue: (row) => row.rssi == null ? '—' : String(row.rssi) },
  { key: 'reason_text', label: '原因', valueType: 'description', minWidth: 180 },
  { key: 'interface_name', label: '射频接口', valueType: 'text' },
  { key: 'physical_state', label: '接口状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.physical_state) },
  { key: 'cfg_event_index', label: 'CFG EventIndex', valueType: 'text' },
  { key: 'cfg_command_source', label: '命令来源', valueType: 'status', displayValue: (row) => groundControlSourceLabel(row.cfg_command_source) },
  { key: 'correlation_confidence', label: '关联置信度', valueType: 'status', displayValue: (row) => groundStatusLabel(row.correlation_confidence) },
  { key: 'correlation_delta_ms', label: '关联时间差', valueType: 'number', displayValue: (row) => metric(row.correlation_delta_ms, 'ms') },
  { key: 'composite_event_type', label: '综合事件', valueType: 'status', displayValue: (row) => row.composite_event_type ? groundEventLabel(row.composite_event_type) : '—' },
  { key: 'data_source', label: '数据来源', valueType: 'status', displayValue: (row) => groundSourceLabel(row.data_source) },
  { key: 'identity_status', label: '身份状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.identity_status) },
  { key: 'resolution_status', label: 'AP 解析', valueType: 'status', visible: false, displayValue: (row) => groundStatusLabel(row.resolution_status) },
  { key: 'clock_offset_ms', label: '时间差', valueType: 'number', visible: false, displayValue: (row) => metric(row.clock_offset_ms, 'ms') },
  { key: 'raw_file_status', label: '文件状态', valueType: 'status', visible: false, displayValue: (row) => groundStatusLabel(row.raw_file_status) },
  { key: 'raw_text', label: '原始内容', valueType: 'description', minWidth: 420 },
  { key: 'actions', label: '操作', valueType: 'actions', fixed: 'right', width: 90, hideable: false },
]

async function latestRequest<T>(
  key: string,
  label: string,
  request: (signal: AbortSignal) => Promise<T>,
  apply: (value: T) => void,
  silent = true,
  fingerprint = '',
  mapError?: (reason: unknown) => Promise<LoadIssue>,
): Promise<boolean> {
  const current = requestPromises.get(key)
  const currentController = requestControllers.get(key)
  if (
    fingerprint
    && current
    && currentController
    && !currentController.signal.aborted
    && requestFingerprints.get(key) === fingerprint
  ) {
    if (!silent) {
      requestNotifySequences.set(key, requestSequences.get(key) ?? 0)
    }
    return current
  }
  if (current) currentController?.abort()
  const controller = new AbortController()
  requestControllers.set(key, controller)
  requestFingerprints.set(key, fingerprint)
  const sequence = (requestSequences.get(key) ?? 0) + 1
  requestSequences.set(key, sequence)
  if (!silent) requestNotifySequences.set(key, sequence)
  let promise!: Promise<boolean>
  promise = (async () => {
    try {
      const value = await request(controller.signal)
      if (disposed || controller.signal.aborted || requestSequences.get(key) !== sequence) return false
      apply(value)
      requestFailureCounts.set(key, 0)
      loadIssues.value = loadIssues.value.filter((item) => item.key !== key)
      return true
    } catch (reason) {
      if (reason instanceof Error && reason.name === 'AbortError') return false
      if (requestSequences.get(key) !== sequence) return false
      requestFailureCounts.set(key, (requestFailureCounts.get(key) ?? 0) + 1)
      const issue = mapError
        ? await mapError(reason)
        : { key, label, message: errorText(reason, '请求失败') }
      if (
        disposed
        || controller.signal.aborted
        || requestSequences.get(key) !== sequence
      ) return false
      if (key === 'syslog') {
        syslogBackendState.value = issue.backendState ?? 'UNKNOWN'
        syslogRequestId.value = issue.requestId ?? ''
        syslogErrorCode.value = issue.code ?? 'UNKNOWN_ERROR'
        syslogFailureCount.value += 1
      } else if (key.startsWith('ping-series')) {
        pingBackendState.value = issue.backendState ?? 'UNKNOWN'
        pingRequestId.value = issue.requestId ?? ''
        pingErrorCode.value = issue.code ?? 'UNKNOWN_ERROR'
      }
      loadIssues.value = [...loadIssues.value.filter((item) => item.key !== key), issue]
      if (!silent || requestNotifySequences.get(key) === sequence) {
        ElMessage.error(`${label}加载失败：${issue.message}`)
      }
      return false
    } finally {
      if (requestControllers.get(key) === controller) requestControllers.delete(key)
      window.setTimeout(() => {
        if (requestPromises.get(key) === promise) {
          requestPromises.delete(key)
          if (requestNotifySequences.get(key) === sequence) {
            requestNotifySequences.delete(key)
          }
        }
      }, 0)
    }
  })()
  requestPromises.set(key, promise)
  return promise
}
const loadStatus = (silent = true) => latestRequest('status', '运行状态', (signal) => getGroundStatus({ signal }), (value) => {
  status.value = value
  if (!selectedRunId.value) selectedRunId.value = value.active_run_id || value.latest_run_id
}, silent)
const loadProfile = (silent = true) => latestRequest('profile', '无人值守配置', (signal) => getGroundProfile({ signal }), (value) => { profile.value = value }, silent)
const loadRuns = (silent = true) => latestRequest('runs', '运行历史', (signal) => listGroundRuns({ signal }), (value) => {
  runs.value = value.items
  if (!value.items.some((row) => row.run_id === selectedRunId.value)) {
    selectedRunId.value = status.value
      ? status.value.active_run_id || value.items[0]?.run_id || ''
      : ''
  }
}, silent)
const loadTrains = (silent = true) => latestRequest('trains', '正线车辆', (signal) => listGroundTrains({ signal }), (value) => { trains.value = value.items }, silent)
const loadPingTargets = (silent = true) => latestRequest('ping', '长 Ping', (signal) => listGroundPingTargets(selectedRunId.value, { signal }), (value) => { pingTargets.value = value.items }, silent)
const loadDeep = (silent = true) => latestRequest('deep', '深度采集', (signal) => listGroundDeepCollections(selectedRunId.value, { signal }), (value) => { deepCollections.value = value.items }, silent)
const loadTimelineData = (silent = true) => latestRequest(
  'timeline',
  '时间轴',
  (signal) => listGroundTimeline(
    '',
    timelineFilter.eventType,
    selectedRunId.value,
    { signal },
    timelinePage.value,
    timelinePageSize.value,
    timelineFilter.query,
  ),
  (value) => {
    timeline.value = value.items
    timelineTotal.value = value.total
  },
  silent,
)
const loadArchives = (silent = true) => latestRequest('archives', '历史归档', (signal) => listGroundArchives({ signal }), (value) => { archives.value = value.items }, silent)
const loadHealth = (silent = true) => latestRequest('health', '系统健康', (signal) => getGroundHealth({ signal }), (value) => { health.value = value }, silent)
const loadSyslogTransport = async (silent = true) => {
  if (!silent) syslogTransportLoading.value = true
  await latestRequest(
    'syslog-transport',
    'UDP Syslog 运行状态',
    (signal) => getGroundSyslogTransportStatus({ signal }),
    (value) => { syslogTransport.value = value },
    silent,
  )
  syslogTransportLoading.value = false
}
async function loadOperation(silent = true): Promise<void> {
  await latestRequest('operation', '运行操作', async (signal) => {
    const active = await getActiveGroundOperation({ signal })
    if (active) return { active, terminal: null }
    const operationId = status.value?.latest_operation_id
    if (
      !operationId
      || dismissedTerminalOperationIds.has(operationId)
      || !['COMPLETED', 'FAILED'].includes(status.value?.latest_operation_state || '')
    ) return { active: null, terminal: null }
    if (latestTerminalOperation.value?.operation_id === operationId) {
      return { active: null, terminal: latestTerminalOperation.value }
    }
    return { active: null, terminal: await getGroundOperation(operationId, { signal }) }
  }, applyOperation, silent)
}
function applyOperation(value: { active: GroundOperation | null; terminal: GroundOperation | null }): void {
  if (completedOperationTimer !== undefined) window.clearTimeout(completedOperationTimer)
  activeOperation.value = value.active
  if (value.active) {
    latestTerminalOperation.value = null
    return
  }
  const terminal = value.terminal
  if (!terminal || dismissedTerminalOperationIds.has(terminal.operation_id)) {
    latestTerminalOperation.value = null
    return
  }
  if (terminal.operation_state === 'COMPLETED') {
    const updated = new Date(terminal.completed_at || terminal.updated_at).getTime()
    const remaining = Math.max(0, 12_000 - Math.max(0, Date.now() - updated))
    if (!remaining) {
      dismissedTerminalOperationIds.add(terminal.operation_id)
      latestTerminalOperation.value = null
      return
    }
    latestTerminalOperation.value = terminal
    void loadRuns(true)
    if (terminal.operation_type === 'STOP_AND_ARCHIVE' && activeTab.value === 'archives') void loadArchives(true)
    completedOperationTimer = window.setTimeout(() => {
      dismissedTerminalOperationIds.add(terminal.operation_id)
      if (latestTerminalOperation.value?.operation_id === terminal.operation_id) latestTerminalOperation.value = null
    }, remaining)
    return
  }
  latestTerminalOperation.value = terminal
}
function dismissOperation(): void {
  const operation = latestTerminalOperation.value
  if (!operation) return
  dismissedTerminalOperationIds.add(operation.operation_id)
  latestTerminalOperation.value = null
}
async function loadActiveTab(silent = true): Promise<void> {
  if (activeTab.value === 'overview') await Promise.all([loadHealth(silent), loadSyslogTransport(silent)])
  else if (activeTab.value === 'trains') await loadTrains(silent)
  else if (activeTab.value === 'ping') await loadPingTargets(silent)
  else if (activeTab.value === 'deep') await loadDeep(silent)
  else if (activeTab.value === 'timeline') await loadTimelineData(silent)
  else if (activeTab.value === 'syslog') await loadSyslog(silent)
  else if (activeTab.value === 'health') await loadHealth(silent)
  else if (activeTab.value === 'archives') await loadArchives(silent)
  else if (activeTab.value === 'settings') await Promise.all([loadProfile(silent), loadTrains(silent)])
}
async function loadAll(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const staticRequests = [loadStatus(silent), loadRuns(silent)]
    if (!profile.value || activeTab.value === 'settings') staticRequests.push(loadProfile(silent))
    await Promise.allSettled(staticRequests)
    if (!selectedRunId.value) {
      selectedRunId.value = status.value?.active_run_id || status.value?.latest_run_id || runs.value[0]?.run_id || ''
    }
    await Promise.allSettled([loadOperation(silent), loadActiveTab(silent)])
  } finally {
    if (!silent) loading.value = false
  }
}
function pollDue(key: string, intervalMs: number, callback: () => Promise<unknown>): void {
  if (requestControllers.has(key)) return
  const now = Date.now()
  const failures = Math.min(requestFailureCounts.get(key) ?? 0, 5)
  const effectiveInterval = Math.min(intervalMs * (2 ** failures), 120_000)
  if (now - (lastPollAt.get(key) ?? 0) < effectiveInterval) return
  lastPollAt.set(key, now)
  void callback()
}
function schedulePoll(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(() => {
    if (!document.hidden) {
      pollDue('status', running.value ? 5_000 : 20_000, () => loadStatus())
      if (operationActive.value || status.value?.active_operation_id) {
        pollDue('operation', 2_000, () => loadOperation())
      } else if (
        status.value?.latest_operation_id
        && !dismissedTerminalOperationIds.has(status.value.latest_operation_id)
        && latestTerminalOperation.value?.operation_id !== status.value.latest_operation_id
      ) {
        pollDue('operation', 2_000, () => loadOperation())
      }
      if (running.value) {
        if (activeTab.value === 'overview') {
          pollDue('health', 5_000, () => loadHealth())
          pollDue('syslog-transport', 5_000, () => loadSyslogTransport())
        } else if (activeTab.value === 'health') pollDue('health', 5_000, () => loadHealth())
        else if (activeTab.value === 'trains') pollDue('trains', 8_000, () => loadTrains())
        else if (activeTab.value === 'ping') pollDue('ping', 8_000, () => loadPingTargets())
        else if (activeTab.value === 'deep') pollDue('deep', 4_000, () => loadDeep())
        else if (activeTab.value === 'syslog' && syslogAutoRefresh.value && !historicalRun.value) pollDue('syslog', 8_000, () => loadSyslog(true))
      }
      if (activeTab.value === 'syslog' && syslogAutoRefresh.value && historicalRun.value) {
        pollDue('syslog', 30_000, () => loadSyslog(true))
      }
      if (
        pingWindowOpen.value
        && selectedPingTarget.value
        && pingSeries.value
        && pingInitialLoadSucceeded.value
        && pingAutoRefresh.value
        && !pingPaused.value
        && !selectedPingHistorical.value
      ) {
        pollDue('ping-series-incremental', 1_800, loadPingIncremental)
      }
      if (deepWindowOpen.value && selectedDeepCollector.value && deepAutoRefresh.value && !deepPaused.value) {
        pollDue('deep-records', 1_800, () => loadDeepRecords(false))
      }
    }
    if (!disposed) schedulePoll()
  }, 1_000)
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
async function refreshSyslogAddresses(): Promise<void> {
  await loadLocalAddresses()
  await loadSyslogTransport(false)
}
async function copyReturnTarget(): Promise<void> {
  const transport = syslogTransport.value
  if (!transport?.configured_return_ip) return
  try {
    await navigator.clipboard.writeText(`${transport.configured_return_ip}:${transport.configured_return_port}`)
    ElMessage.success('MR 日志回传目标已复制')
  } catch {
    ElMessage.error('无法访问剪贴板')
  }
}
async function runAction(key: string, callback: () => Promise<unknown>): Promise<void> {
  action.value = key
  try {
    const result = await callback()
    if (isActionResponse(result)) {
      ElMessage.success(result.message)
      if (result.operation_id) {
        const operation = await getGroundOperation(result.operation_id)
        applyOperation({
          active: ['PENDING', 'RUNNING'].includes(operation.operation_state) ? operation : null,
          terminal: ['COMPLETED', 'FAILED'].includes(operation.operation_state) ? operation : null,
        })
      }
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
async function showPingSeries(row: GroundPingTarget, notifyFailure = false): Promise<void> {
  const targetRunId = row.run_id || selectedRunId.value
  if (!pingWindowOpen.value) {
    pingRange.value = targetRunId && targetRunId !== status.value?.active_run_id ? 'run' : '30m'
    pingWindowOpen.value = true
  }
  const range = pingTimeRange(row, targetRunId)
  if (pingRange.value === 'custom' && !range.start_time) {
    if (notifyFailure) ElMessage.warning('请选择自定义开始和结束时间')
    return
  }
  const previousIdentity = selectedPingTarget.value?.query_identity
  if (previousIdentity !== row.query_identity) {
    pingSeries.value = null
    pingSeenSamples.clear()
  }
  selectedPingTarget.value = row
  pingPaused.value = false
  pingFollowLatest.value = true
  pingInitialLoadSucceeded.value = false
  pingCursor.value = ''
  pingRequestId.value = ''
  pingErrorCode.value = ''
  pingBackendState.value = 'UNKNOWN'
  pingLastAttemptAt.value = new Date().toISOString()
  pingSeriesLoading.value = true
  const succeeded = await latestRequest(
    'ping-series',
    '长 Ping 逐包数据',
    (signal) => getGroundPingSeries({
      run_id: targetRunId || undefined,
      query_identity: row.query_identity || undefined,
      train_id: row.train_id || undefined,
      mr_id: row.mr_id || undefined,
      target_ip: row.target_ip,
      include_warmup: includeWarmup.value,
      max_points: pingRange.value === 'run' ? 10_000 : 3_000,
      ...range,
    }, { signal }),
    (value) => {
      mergePingSeries(value, true)
      pingInitialLoadSucceeded.value = true
      pingBackendState.value = 'ONLINE'
      pingRequestId.value = value.diagnostics.request_id
      pingErrorCode.value = ''
    },
    !notifyFailure,
    JSON.stringify({
      query_identity: row.query_identity,
      run_id: targetRunId,
      target_ip: row.target_ip,
      ...range,
      include_warmup: includeWarmup.value,
    }),
    mapPingLoadIssue,
  )
  if (!succeeded) pingInitialLoadSucceeded.value = false
  if (!requestControllers.has('ping-series')) pingSeriesLoading.value = false
}

function pingSampleIdentity(point: GroundPingSample): string {
  return point.sample_id || `${point.target_ip}|${point.ts}|${point.seq ?? ''}`
}

function mergeRecordList<T>(
  current: T[],
  incoming: T[],
  key: (row: T) => string,
): T[] {
  const seen = new Set<string>()
  return [...current, ...incoming].filter((row) => {
    const identity = key(row)
    if (seen.has(identity)) return false
    seen.add(identity)
    return true
  })
}

function mergePingSeries(value: GroundPingSeries, reset: boolean): void {
  if (reset) pingSeenSamples.clear()
  const existing = reset ? [] : pingSeries.value?.points ?? []
  existing.forEach((point) => pingSeenSamples.add(pingSampleIdentity(point)))
  let duplicateEffectiveCount = 0
  let duplicateIgnoredCount = 0
  const additions = value.points.filter((point) => {
    const identity = pingSampleIdentity(point)
    if (pingSeenSamples.has(identity)) {
      if (point.warmup_ignored) duplicateIgnoredCount += 1
      else duplicateEffectiveCount += 1
      return false
    }
    pingSeenSamples.add(identity)
    return true
  })
  const addedEffective = additions.filter((point) => !point.warmup_ignored)
  const addedSuccesses = addedEffective.filter((point) => point.ok)
  const addedLosses = addedEffective.length - addedSuccesses.length
  const addedRtts = addedSuccesses.flatMap((point) => (
    point.rtt_ms == null ? [] : [point.rtt_ms]
  ))
  const limit = pingRange.value === 'run' ? 10_000 : 3_000
  const points = [...existing, ...additions]
    .sort((left, right) => (
      left.ts.localeCompare(right.ts)
      || (left.seq ?? -1) - (right.seq ?? -1)
      || pingSampleIdentity(left).localeCompare(pingSampleIdentity(right))
    ))
    .slice(-limit)
  const retained = new Set(points.map(pingSampleIdentity))
  for (const identity of pingSeenSamples) {
    if (!retained.has(identity)) pingSeenSamples.delete(identity)
  }
  const previous = pingSeries.value
  const rttSampleCount = reset
    ? value.rtt_sample_count
    : (previous?.rtt_sample_count ?? 0) + addedRtts.length
  const rttSumMs = reset
    ? value.rtt_sum_ms
    : (previous?.rtt_sum_ms ?? 0) + addedRtts.reduce((total, rtt) => total + rtt, 0)
  const latestAddedRtt = [...addedSuccesses]
    .sort((left, right) => (
      left.ts.localeCompare(right.ts)
      || (left.seq ?? -1) - (right.seq ?? -1)
    ))
    .at(-1)?.rtt_ms ?? null
  const mergedMaxRtt = Math.max(
    previous?.max_rtt_ms ?? Number.NEGATIVE_INFINITY,
    ...addedRtts,
  )
  pingSeries.value = {
    ...value,
    raw_sample_count: reset ? value.raw_sample_count : (previous?.raw_sample_count ?? 0) + Math.max(0, value.raw_sample_count - duplicateEffectiveCount - duplicateIgnoredCount),
    effective_sample_count: reset ? value.effective_sample_count : (previous?.effective_sample_count ?? 0) + Math.max(0, value.effective_sample_count - duplicateEffectiveCount),
    ignored_sample_count: reset ? value.ignored_sample_count : (previous?.ignored_sample_count ?? 0) + Math.max(0, value.ignored_sample_count - duplicateIgnoredCount),
    success_count: reset ? value.success_count : (previous?.success_count ?? 0) + addedSuccesses.length,
    loss_count: reset ? value.loss_count : (previous?.loss_count ?? 0) + addedLosses,
    rtt_sample_count: rttSampleCount,
    rtt_sum_ms: rttSumMs,
    current_rtt_ms: reset
      ? value.current_rtt_ms
      : latestAddedRtt ?? previous?.current_rtt_ms ?? null,
    average_rtt_ms: rttSampleCount ? rttSumMs / rttSampleCount : null,
    max_rtt_ms: reset
      ? value.max_rtt_ms
      : mergedMaxRtt === Number.NEGATIVE_INFINITY ? null : mergedMaxRtt,
    points,
    loss_windows: mergeRecordList(
      reset ? [] : previous?.loss_windows ?? [],
      value.loss_windows,
      (row) => `${row.target_ip ?? ''}|${row.started_at ?? ''}|${row.ended_at ?? ''}`,
    ).slice(-limit),
    ap_transitions: mergeRecordList(
      reset ? [] : previous?.ap_transitions ?? [],
      value.ap_transitions,
      (row) => String(row.syslog_event_id ?? '') || [
        row.train_id ?? '', row.mr_id ?? '', row.mr_role ?? '', row.ts ?? '', row.context ?? '',
      ].join('|'),
    ).slice(-limit),
    position_segments: mergeRecordList(
      reset ? [] : previous?.position_segments ?? [],
      value.position_segments,
      (row) => `${row.target_ip ?? ''}|${row.started_at ?? ''}|${row.current_ap_identity ?? ''}`,
    )
      .sort((left, right) => (
        String(left.started_at ?? '').localeCompare(String(right.started_at ?? ''))
      ))
      .filter((row, index, rows) => (
        index === 0
        || [
          'target_ip',
          'current_ap_identity',
          'current_ap_name',
          'station',
          'section',
          'position_quality',
        ].some((field) => row[field] !== rows[index - 1]?.[field])
      ))
      .slice(-limit),
  }
  pingCursor.value = value.next_cursor
}

async function mapPingLoadIssue(reason: unknown, key = 'ping-series'): Promise<LoadIssue> {
  const transport = await probeGroundRawQueryTransportState(reason)
  const messages: Record<string, string> = {
    BACKEND_UNREACHABLE: '无法连接本机 Backend，请重试或查看 Backend 日志。',
    BACKEND_CONNECTION_INTERRUPTED: '长 Ping 查询连接中断，Backend 仍在线，请重试。',
    CONNECTION_RESET: '长 Ping 查询连接中断，Backend 仍在线，请重试。',
    BACKEND_RESTARTED: '长 Ping 查询期间 Backend 发生重启，当前已恢复在线，请重试。',
    RAW_QUERY_TIMEOUT: '长 Ping 查询超时，请缩小时间范围后重试。',
    PING_TARGET_NOT_FOUND: '未找到该目标的逐包 Ping 记录。',
    PING_IDENTITY_MISMATCH: '汇总目标与稳定查询身份不一致，请刷新汇总列表后重试。',
    PING_TARGET_IDENTITY_CONFLICT: '同一运行内该目标 IP 对应多个列车或 MR 端位，已拒绝任意选取。',
    RAW_FILE_MISSING: '原始文件已有登记，但物理文件缺失。',
    RAW_ARCHIVE_CORRUPT: 'READY 归档损坏，已停止读取。',
    SUMMARY_ONLY: '本次运行仅保留汇总，无法生成逐包曲线。',
  }
  const message = messages[transport.code]
    || (transport.backendState === 'ONLINE'
      ? errorText(reason, '长 Ping 查询失败，Backend 仍在线。')
      : errorText(reason, '长 Ping 查询失败。'))
  return {
    key,
    label: '长 Ping 逐包数据',
    message,
    code: transport.code,
    requestId: transport.requestId,
    attemptedAt: pingLastAttemptAt.value,
    backendState: transport.backendState,
  }
}

async function loadPingIncremental(): Promise<void> {
  const row = selectedPingTarget.value
  const runId = row?.run_id || selectedRunId.value
  if (
    !row
    || !runId
    || !pingSeries.value
    || !pingInitialLoadSucceeded.value
    || !pingWindowOpen.value
    || !pingAutoRefresh.value
    || pingPaused.value
    || selectedPingHistorical.value
    || document.hidden
  ) return
  pingIncrementalLoading.value = true
  await latestRequest(
    'ping-series-incremental',
    '长 Ping 实时增量',
    (signal) => getGroundPingSeriesIncremental({
      run_id: runId,
      query_identity: row.query_identity || pingSeries.value?.query_identity || undefined,
      train_id: row.train_id || undefined,
      mr_id: row.mr_id || undefined,
      target_ip: row.target_ip,
      cursor: pingCursor.value || undefined,
      after_sequence: pingSeries.value?.latest_sequence,
      after_timestamp: pingSeries.value?.latest_timestamp,
      include_warmup: includeWarmup.value,
      max_points: 200,
    }, { signal }),
    (value) => {
      mergePingSeries(value, false)
      pingBackendState.value = 'ONLINE'
      pingRequestId.value = value.diagnostics.request_id || pingRequestId.value
      pingErrorCode.value = ''
    },
    true,
    '',
    (reason) => mapPingLoadIssue(reason, 'ping-series-incremental'),
  )
  pingIncrementalLoading.value = false
}
function currentSyslogDeleteFilters(): GroundSyslogDeleteFilters {
  const [startValue, endValue] = syslogTimeRange.value || []
  return {
    train_id: syslogFilter.trainId,
    mr_name: syslogFilter.mrName,
    mr_role: syslogFilter.mrRole,
    source_ip: syslogFilter.sourceIp,
    system_name: syslogFilter.systemName,
    facility: syslogFilter.facility,
    severity: syslogFilter.severity,
    identity_status: syslogFilter.identityStatus,
    event_type: syslogFilter.eventType,
    event_family: syslogFilter.eventFamily,
    cfg_command_source: syslogFilter.commandSource,
    physical_state: syslogFilter.physicalState,
    correlation_status: syslogFilter.correlationStatus,
    correlation_confidence: syslogFilter.correlationConfidence,
    peer_name: syslogFilter.peerName,
    data_source: syslogFilter.dataSource,
    keyword: syslogFilter.keyword,
    start_time: startValue?.toISOString(),
    end_time: endValue?.toISOString(),
  }
}
async function loadSyslog(silent = false): Promise<void> {
  if (!silent) syslogLoading.value = true
  const filters = currentSyslogDeleteFilters()
  const params = {
      run_id: selectedRunId.value || undefined,
      ...filters,
      page: syslogFilter.page,
      page_size: syslogFilter.pageSize,
    }
  const fingerprint = JSON.stringify(params)
  const hadIssue = loadIssues.value.some((item) => item.key === 'syslog')
  let recovered = false
  const succeeded = await latestRequest('syslog', 'Syslog 日志', (signal) => {
    syslogLastAttemptAt.value = new Date().toISOString()
    return listGroundSyslogRecords(params, { signal })
  }, (result) => {
    syslogRecords.value = result.items
    syslogTotal.value = result.total
    syslogTotalExact.value = result.total_exact ?? true
    syslogDiagnostics.value = result.diagnostics ?? null
    syslogBackendState.value = 'ONLINE'
    syslogRequestId.value = ''
    syslogErrorCode.value = ''
    syslogFailureCount.value = 0
    recovered = hadIssue
  }, silent, fingerprint, mapSyslogLoadIssue)
  if (succeeded && recovered) ElMessage.success(t('ground.syslog.recovered', 'Syslog 日志已恢复'))
  if (!silent) syslogLoading.value = false
}
async function mapSyslogLoadIssue(reason: unknown): Promise<LoadIssue> {
  const attemptedAt = syslogLastAttemptAt.value
  const transport = await probeGroundSyslogTransportState(reason)
  const message = transport.code === 'BACKEND_UNREACHABLE'
    ? t('ground.syslog.backend_unreachable', '无法连接本机 Backend，请重试或查看 Backend 日志。')
    : transport.backendState === 'ONLINE' && transport.code === 'RAW_QUERY_TIMEOUT'
    ? t('ground.syslog.timeout_online', 'Syslog 查询超时，Backend 仍在线，请缩小时间范围或增加筛选条件后重试。')
    : transport.backendState === 'ONLINE' && transport.code === 'BACKEND_RESTARTED'
    ? t('ground.syslog.restarted_online', 'Syslog 查询期间 Backend 发生重启，当前已恢复在线，请重试。')
    : transport.backendState === 'ONLINE' && ['BACKEND_CONNECTION_INTERRUPTED', 'CONNECTION_RESET'].includes(transport.code)
    ? t('ground.syslog.connection_interrupted_online', 'Syslog 查询连接中断，Backend 仍在线，请重试。')
    : errorText(reason, '请求失败')
  return {
    key: 'syslog',
    label: 'Syslog 日志',
    message,
    code: transport.code,
    requestId: transport.requestId,
    attemptedAt,
    backendState: transport.backendState,
  }
}
function openBackendLogs(): void {
  void router.push({ name: 'logs', query: { keyword: syslogRequestId.value || 'GROUND_SYSLOG_QUERY' } })
}
function openPingBackendLogs(): void {
  void router.push({ name: 'logs', query: { keyword: pingRequestId.value || 'GROUND_PING_QUERY' } })
}
function showSyslogRecord(row: GroundSyslogRecord): void {
  selectedSyslogRecord.value = row
  syslogDetailDrawer.value = true
}
function syslogRowKey(row: GroundSyslogRecord): string {
  return [
    row.raw_file_id,
    row.global_receive_sequence ?? '',
    row.source_receive_sequence ?? '',
    row.raw_line_number ?? '',
  ].join(':')
}
function handleSyslogSelection(rows: GroundSyslogRecord[]): void {
  selectedSyslogRecords.value = rows
}
async function deleteSyslog(
  mode: 'SELECTED' | 'FILTERED' | 'RUN_ALL',
): Promise<void> {
  if (!selectedRunId.value) {
    ElMessage.warning('请先选择需要清理的运行')
    return
  }
  const recordKeys = mode === 'SELECTED'
    ? selectedSyslogRecords.value.map((row) => ({
      raw_file_id: row.raw_file_id,
      global_receive_sequence: row.global_receive_sequence,
      source_receive_sequence: row.source_receive_sequence,
      raw_line_number: row.raw_line_number,
    }))
    : []
  syslogDeleteLoading.value = true
  try {
    const preview = await previewGroundSyslogDelete({
      run_id: selectedRunId.value,
      mode,
      record_keys: recordKeys,
      filters: mode === 'FILTERED' ? currentSyslogDeleteFilters() : {},
      include_derived_events: syslogDeleteDerived.value,
    })
    syslogDeletePreview.value = preview
    if (preview.blocked_reasons.length) {
      await ElMessageBox.alert(
        preview.blocked_reasons.join('\n'),
        '当前范围禁止记录级删除',
        { type: 'warning', confirmButtonText: '知道了' },
      )
      return
    }
    if (!preview.preview_token || !preview.matched_record_count) {
      ElMessage.info(preview.warnings[0] || '当前范围没有可删除的 Syslog 记录')
      return
    }
    const eventDescription = syslogDeleteDerived.value
      ? `同时删除 ${preview.affected_event_count} 个 WMESH 事件和 ${preview.affected_timeline_count} 个 Syslog 时间轴事件`
      : `保留 ${preview.affected_event_count + preview.affected_timeline_count} 个派生事件，并标记原始来源已删除`
    const result = await ElMessageBox.prompt(
      [
        `将删除 ${preview.matched_record_count} 条 Syslog 原始记录，影响 ${preview.affected_file_count} 个文件（${bytes(preview.total_bytes)}）。`,
        eventDescription,
        '该操作不可恢复；READY 归档不会被修改。',
        `请输入：${preview.confirmation_hint}`,
      ].join('\n'),
      '确认删除 Syslog 日志',
      {
        type: 'warning',
        confirmButtonText: '提交删除任务',
        cancelButtonText: '取消',
        inputPlaceholder: preview.confirmation_hint,
        inputValidator: (value) => (
          value === preview.confirmation_hint
          || value === status.value?.site_id
          || '确认文本不匹配'
        ),
      },
    )
    const accepted = await submitGroundSyslogDelete({
      preview_token: preview.preview_token,
      explicit_confirmation: true,
      confirmation_text: result.value,
      include_derived_events: syslogDeleteDerived.value,
    })
    selectedSyslogRecords.value = []
    ElMessage.success(`${accepted.message}（任务 ${accepted.task_id}）`)
    await loadSyslog(true)
  } catch (reason) {
    if (!isDialogCancellation(reason)) {
      ElMessage.error(errorText(reason, 'Syslog 删除任务提交失败'))
    }
  } finally {
    syslogDeleteLoading.value = false
  }
}
function isDialogCancellation(reason: unknown): boolean {
  const text = reason instanceof Error ? reason.message : String(reason || '')
  return ['cancel', 'close'].includes(text.toLocaleLowerCase())
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
  const normalized = sessionId.trim()
  if (!normalized || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(normalized)) {
    ElMessage.error('会话 ID 无效')
    return
  }
  if (openingSessionId.value) return
  openingSessionId.value = normalized
  try {
    await getOnlineMrSession(normalized)
    await workspace.openOrActivateRoute(
      `/rail-transit/online-mr-analysis?session_id=${encodeURIComponent(normalized)}`,
    )
    trainDialog.value = false
  } catch (reason) {
    const detail = apiErrorDetail(
      reason,
      `/api/online-mr/sessions/${encodeURIComponent(normalized)}`,
    )
    if (detail.status === 404 || detail.code.includes('NOT_FOUND')) {
      ElMessage.error('会话不存在或已被清理')
    } else {
      const request = detail.requestId ? `，request_id: ${detail.requestId}` : ''
      ElMessage.error(`${detail.message}（error_code: ${detail.code}${request}）`)
    }
  } finally {
    openingSessionId.value = ''
  }
}
async function showArchive(row: GroundArchive): Promise<void> {
  try {
    selectedArchive.value = await getGroundArchiveDetail(row.archive_id)
    archiveDetailTab.value = 'overview'
    archiveDialog.value = true
  }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_load_failed', '归档汇总读取失败'))) }
}
async function removeArchive(row: GroundArchive): Promise<void> {
  await ElMessageBox.confirm(t('ground.archive_delete_confirm', `确认删除 ${row.run_date} 的无人值守归档？该操作不会作用于正在使用的当日数据。`), t('ground.archive_delete_title', '删除历史归档'), { type: 'warning', confirmButtonText: t('common.delete', '删除'), cancelButtonText: t('common.cancel', '取消') })
  try { await deleteGroundArchive(row.archive_id); ElMessage.success(t('ground.archive_delete_queued', '归档删除请求已提交')); await loadAll(true) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_delete_failed', '归档删除失败'))) }
}
async function deleteSelectedRunHistory(): Promise<void> {
  const row = selectedRun.value
  if (!row) {
    ElMessage.warning('请先选择需要删除的运行历史')
    return
  }
  if (runHistoryDeleteBlocked.value) {
    ElMessage.warning('只能删除非活动的历史运行')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除 ${row.run_date || row.run_id} 的运行历史？该操作会移除长 Ping、时间轴、Syslog 等查询索引；正式归档 ZIP 仍在“历史归档”中管理。`,
      '删除运行历史',
      { type: 'warning', confirmButtonText: t('common.delete', '删除'), cancelButtonText: t('common.cancel', '取消') },
    )
    runHistoryDeleteLoading.value = true
    await deleteGroundRunHistory(row.run_id)
    if (selectedPingTarget.value?.run_id === row.run_id) {
      pingWindowOpen.value = false
      handlePingWindowClosed()
    }
    selectedSyslogRecords.value = []
    syslogRecords.value = []
    pingTargets.value = []
    deepCollections.value = []
    timeline.value = []
    ElMessage.success('运行历史已删除')
    await Promise.allSettled([loadStatus(true), loadRuns(true)])
    await loadActiveTab(true)
  } catch (reason) {
    if (!isDialogCancellation(reason)) {
      ElMessage.error(errorText(reason, '运行历史删除失败'))
    }
  } finally {
    runHistoryDeleteLoading.value = false
  }
}
async function downloadArchiveSummary(row: GroundArchive): Promise<void> {
  try {
    const result = await downloadBackendResource(groundArchiveSummaryDownloadRequest(row))
    if (result.status === 'failed') throw new Error(result.error || '归档汇总下载失败')
    if (result.status === 'started') ElMessage.info('浏览器已开始下载归档汇总；开发模式无法验证本地落盘')
    else if (result.status === 'saved') ElMessage.success(`归档汇总已保存：${result.fileName || '用户选择的文件'}`)
  }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_download_failed', '归档汇总下载失败'))) }
}
async function downloadArchiveZip(row: GroundArchive): Promise<void> {
  try {
    const result = await downloadBackendResource(groundArchiveZipDownloadRequest(row))
    if (result.status === 'failed') throw new Error(result.error || '原始归档 ZIP 下载失败')
    if (result.status === 'started') ElMessage.info('浏览器已开始下载原始归档 ZIP；开发模式无法验证本地落盘')
    else if (result.status === 'saved') ElMessage.success(`原始归档 ZIP 已保存：${result.fileName || '用户选择的文件'}`)
  }
  catch (reason) { ElMessage.error(errorText(reason, '原始归档 ZIP 下载失败')) }
}
async function verifyArchive(): Promise<void> {
  if (!selectedArchive.value) return
  try {
    selectedArchive.value = await verifyGroundArchive(selectedArchive.value.archive.archive_id)
    ElMessage.success('归档完整性校验通过')
  } catch (reason) {
    ElMessage.error(errorText(reason, '归档完整性校验失败'))
  }
}
async function openArchiveDirectory(): Promise<void> {
  try { const result = await openGroundArchiveDirectory(); if (!result.success) throw new Error(result.message) }
  catch (reason) { ElMessage.error(errorText(reason, t('ground.archive_open_failed', '归档目录打开失败'))) }
}
function endpoint(row: GroundTrain, code: 'CT' | 'CW') { return row.endpoints.find((item) => item.endpoint === code) }
function groundControlSourceLabel(value: unknown): string {
  const source = String(value || '').trim().toLocaleLowerCase()
  if (source === 'snmp') return 'SNMP'
  if (source === 'cli') return 'CLI'
  if (source === 'netconf') return 'NETCONF'
  return source ? source.toLocaleUpperCase() : '未知'
}
function endpointRadioTooltip(row: GroundTrain, code: 'CT' | 'CW'): string {
  const target = endpoint(row, code)
  const radio = target?.radio_interfaces?.[0]
  return [
    `接口：${radio?.interface_name || '未知'}`,
    `最近变化：${radio?.last_changed_at || target?.last_radio_event_at || '—'}`,
    `DOWN：${radio?.last_down_at || '—'}`,
    `UP：${radio?.last_up_at || '—'}`,
    `中断：${radio?.latest_outage_duration_ms == null ? '—' : `${radio.latest_outage_duration_ms} ms`}`,
    `CFG EventIndex：${target?.cfg_event_index || radio?.last_cfg_event_index || '—'}`,
    `控制来源：${groundControlSourceLabel(target?.cfg_command_source || radio?.last_command_source)}`,
    `关联：${groundStatusLabel(target?.correlation_confidence || radio?.correlation_confidence || 'UNCONFIRMED')}`,
  ].join('\n')
}
function pingTimeRange(row: GroundPingTarget, runId: string): { start_time?: string; end_time?: string } {
  if (pingRange.value === 'run') {
    const run = runs.value.find((item) => item.run_id === runId)
    const start = row.first_sample_at || run?.actual_started_at || run?.scheduled_start_at
    const end = row.last_sample_at || run?.actual_ended_at || run?.scheduled_end_at
    return start && end ? { start_time: start, end_time: end } : {}
  }
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
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (['RUNNING', 'COVERED', 'READY', 'FRESH', 'MAINLINE', 'LOCAL_ADDRESS', 'LISTENING', 'NETCONSOLE_LISTENING', 'AVAILABLE', 'UP', 'RADIO_RECOVERED', 'HIGH', 'CORRELATED'].includes(value)) return 'success'
  if (['PAUSED', 'PARTIAL', 'STALE', 'MAINLINE_STATIONARY', 'WARNING', 'EXTERNAL_CONFIRMED', 'STARTING', 'FLAPPING', 'FREQUENT_SWITCHING', 'MEDIUM'].includes(value)) return 'warning'
  if (['ERROR', 'FAILED', 'CRITICAL', 'NOT_LOCAL', 'INVALID', 'OCCUPIED_BY_OTHER', 'ADDRESS_NOT_LOCAL', 'DOWN', 'RADIO_DOWN'].includes(value)) return 'danger'
  return 'info'
}
function abortRequests(): void {
  requestControllers.forEach((controller) => controller.abort())
  requestControllers.clear()
  requestFingerprints.clear()
  requestNotifySequences.clear()
}
function handleVisibilityChange(): void {
  if (document.hidden) abortRequests()
  else {
    lastPollAt.clear()
    void loadAll(true)
    if (
      pingWindowOpen.value
      && selectedPingTarget.value
      && pingInitialLoadSucceeded.value
    ) void loadPingIncremental()
    if (deepWindowOpen.value && selectedDeepCollector.value && !deepPaused.value) void loadDeepRecords(false)
  }
}
function useFullPingRange(): void {
  if (!selectedPingTarget.value) return
  pingRange.value = 'run'
  void showPingSeries(selectedPingTarget.value)
}
function togglePingPaused(): void {
  pingPaused.value = !pingPaused.value
  if (!pingPaused.value && pingInitialLoadSucceeded.value) {
    lastPollAt.delete('ping-series-incremental')
    void loadPingIncremental()
  }
}
function returnPingToLive(): void {
  pingFollowLatest.value = true
  pingPaused.value = false
  if (!pingInitialLoadSucceeded.value) return
  lastPollAt.delete('ping-series-incremental')
  void loadPingIncremental()
}
async function copyPingDiagnostics(): Promise<void> {
  try {
    await navigator.clipboard.writeText(JSON.stringify({
      query: {
        run_id: selectedPingTarget.value?.run_id || selectedRunId.value,
        target_ip: selectedPingTarget.value?.target_ip,
        mr_name: selectedPingTarget.value?.mr_name,
        mr_position_code: selectedPingTarget.value?.mr_position_code,
        query_identity: selectedPingTarget.value?.query_identity || pingSeries.value?.query_identity,
      },
      request_id: pingRequestId.value,
      error_code: pingErrorCode.value,
      backend_state: pingBackendState.value,
      attempted_at: pingLastAttemptAt.value,
      diagnostics: pingSeries.value?.diagnostics ?? null,
    }, null, 2))
    ElMessage.success('Ping 文件诊断已复制')
  } catch {
    ElMessage.error('无法访问剪贴板')
  }
}
function handlePingWindowClosed(): void {
  requestControllers.get('ping-series')?.abort()
  requestControllers.get('ping-series-incremental')?.abort()
  selectedPingTarget.value = null
  pingSeries.value = null
  pingCursor.value = ''
  pingInitialLoadSucceeded.value = false
  pingBackendState.value = 'UNKNOWN'
  pingRequestId.value = ''
  pingErrorCode.value = ''
  pingLastAttemptAt.value = ''
  loadIssues.value = loadIssues.value.filter((item) => !item.key.startsWith('ping-series'))
  pingSeenSamples.clear()
  pingSeriesLoading.value = false
  pingIncrementalLoading.value = false
  pingPaused.value = false
  pingFollowLatest.value = true
}
const handlePingDialogClosed = handlePingWindowClosed

async function showDeepCollector(collector: GroundDeepCollector): Promise<void> {
  selectedDeepCollector.value = collector
  deepWindowOpen.value = true
  deepCursor.value = ''
  deepRecords.value = []
  deepPaused.value = false
  await loadDeepRecords(true)
}

async function loadDeepRecords(reset: boolean): Promise<void> {
  const collector = selectedDeepCollector.value
  if (!collector || !collector.collector_session_id || deepPaused.value && !reset) return
  if (reset) {
    deepCursor.value = ''
    deepRecords.value = []
  }
  const requestCursor = reset ? '' : deepCursor.value
  const filterIdentity = JSON.stringify({
    sessionId: collector.collector_session_id,
    category: deepCategory.value,
    keyword: deepKeyword.value.trim(),
    cursor: requestCursor,
  })
  deepRecordsLoading.value = true
  await latestRequest(
    'deep-records',
    '深度采集实时记录',
    (signal) => listGroundDeepCollectionRecords({
      run_id: collector.run_id || selectedRunId.value,
      train_id: collector.train_id,
      mr_id: collector.mr_id,
      mr_role: collector.mr_role,
      category: deepCategory.value,
      keyword: deepKeyword.value,
      cursor: requestCursor,
      limit: 250,
    }, { signal }),
    (page) => {
      selectedDeepCollector.value = page.collector
      deepCursor.value = page.next_cursor
      const seen = new Set(reset ? [] : deepRecords.value.map((row) => `${row.source}:${row.sequence}`))
      deepRecords.value = reset
        ? page.records
        : [...deepRecords.value, ...page.records.filter((row) => !seen.has(`${row.source}:${row.sequence}`))].slice(-2_000)
    },
    true,
    filterIdentity,
  )
  if (!requestControllers.has('deep-records')) deepRecordsLoading.value = false
}

function toggleDeepPaused(): void {
  deepPaused.value = !deepPaused.value
  if (!deepPaused.value) void loadDeepRecords(false)
}

function handleDeepWindowClosed(): void {
  requestControllers.get('deep-records')?.abort()
  selectedDeepCollector.value = null
  deepRecords.value = []
  deepCursor.value = ''
  deepPaused.value = false
}

async function copyDeepRecords(): Promise<void> {
  try {
    await navigator.clipboard.writeText(deepRecords.value.map((item) => item.text).join('\n'))
    ElMessage.success('已复制当前深采记录')
  } catch {
    ElMessage.error('无法访问剪贴板')
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  void loadAll()
  void loadLocalAddresses()
  schedulePoll()
})
watch(activeTab, () => {
  requestControllers.forEach((controller, key) => {
    if (
      !['status', 'operation'].includes(key)
      && !(pingWindowOpen.value && ['ping-series', 'ping-series-incremental'].includes(key))
    ) controller.abort()
  })
  void loadActiveTab(true)
})
watch(selectedRunId, () => {
  if (selectedPingTarget.value?.run_id !== selectedRunId.value) {
    pingWindowOpen.value = false
    handlePingWindowClosed()
  }
  syslogRecords.value = []
  selectedSyslogRecords.value = []
  syslogFilter.page = 1
  timelinePage.value = 1
  if (historicalRun.value) syslogAutoRefresh.value = false
  if (runScopedTab.value) void loadActiveTab(true)
})
onDeactivated(() => {
  pingWindowOpen.value = false
  handlePingWindowClosed()
})
onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  abortRequests()
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  if (completedOperationTimer !== undefined) window.clearTimeout(completedOperationTimer)
})
</script>

<template>
  <main v-loading="loading" :class="['ground-page', { 'ground-page--log-view': ['timeline', 'syslog'].includes(activeTab) }]">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ t('ground.section', '轨道交通') }}</p>
        <h1>{{ t('ground.title', '地面无人值守') }}</h1>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" circle :title="t('common.refresh', '刷新')" @click="loadAll()" />
        <el-button :icon="Refresh" :loading="action === 'sync'" @click="runAction('sync', syncInventory)">同步设备</el-button>
        <el-button :loading="action === 'config'" :disabled="!running || !profile?.syslog_server_ip" @click="runAction('config', () => checkConfigs())">检查 MR 配置</el-button>
        <span :title="startBlockedReason">
          <el-button
            :icon="VideoPlay"
            type="primary"
            :loading="action === 'start'"
            :disabled="running || !profile?.enabled || Boolean(startBlockedReason)"
            @click="runAction('start', startGroundRun)"
          >{{ t('ground.start_now', '立即开始') }}</el-button>
        </span>
        <el-button :icon="VideoPause" :loading="action === 'pause'" :disabled="status?.state !== 'RUNNING'" @click="runAction('pause', pauseGroundRun)">{{ t('ground.pause', '暂停调度') }}</el-button>
        <el-button :icon="VideoPlay" :loading="action === 'resume'" :disabled="status?.state !== 'PAUSED'" @click="runAction('resume', resumeGroundRun)">{{ t('ground.resume', '继续调度') }}</el-button>
        <el-button :icon="SwitchButton" :loading="action === 'stop'" :disabled="!running || operationActive" @click="submitStop(false)">{{ t('ground.stop', '正常停止') }}</el-button>
        <el-button :icon="Box" type="danger" plain :loading="action === 'archive'" :disabled="!running || operationActive" @click="submitStop(true)">{{ t('ground.stop_archive', '停止并归档') }}</el-button>
      </div>
    </header>

    <section v-if="visibleOperation" class="operation-band" :class="`operation-${visibleOperation.operation_state.toLocaleLowerCase()}`">
      <div class="operation-heading">
        <div>
          <b>{{ visibleOperation.operation_type === 'STOP_AND_ARCHIVE' ? '停止并归档' : '正常停止' }}</b>
          <span>{{ groundOperationStageLabel(visibleOperation.operation_stage) }}</span>
        </div>
        <div class="row-actions">
          <el-tag :type="visibleOperation.operation_state === 'FAILED' ? 'danger' : visibleOperation.operation_state === 'COMPLETED' ? 'success' : 'warning'">
            {{ groundStatusLabel(visibleOperation.operation_state) }}
          </el-tag>
          <el-button v-if="!operationActive" text @click="dismissOperation">关闭</el-button>
        </div>
      </div>
      <el-progress :percentage="visibleOperation.progress_percent" :status="visibleOperation.operation_state === 'FAILED' ? 'exception' : visibleOperation.operation_state === 'COMPLETED' ? 'success' : undefined" />
      <p>{{ visibleOperation.message }}<span v-if="visibleOperation.failure_reason">：{{ visibleOperation.failure_reason }}</span></p>
      <small>操作编号 {{ visibleOperation.operation_id }} · 最后更新 {{ visibleOperation.updated_at }}</small>
    </section>

    <section v-if="generalLoadIssues.length" class="load-warning">
      <el-alert
        title="地面无人值守部分数据未加载"
        :description="loadIssueDescription"
        type="error"
        :closable="false"
        show-icon
      />
      <el-button :icon="Refresh" :loading="loading" @click="loadAll()">重新加载</el-button>
    </section>

    <section v-if="runScopedTab" class="run-context-bar">
      <div>
        <b>数据运行上下文</b>
        <span>Ping、深度采集、时间轴与 Syslog 使用同一个运行筛选，不再隐式跟随“最近一次”。</span>
      </div>
      <el-select v-model="selectedRunId" filterable placeholder="选择运行日期">
        <el-option
          v-for="row in runs"
          :key="row.run_id"
          :value="row.run_id"
          :label="`${row.run_date} · ${groundStatusLabel(row.state)} · ${groundStatusLabel(row.data_availability)}`"
        />
      </el-select>
      <el-tag :type="historicalRun ? 'info' : 'success'">{{ historicalRun ? '历史运行' : '当前活动运行' }}</el-tag>
      <el-button
        :icon="Delete"
        type="danger"
        plain
        :loading="runHistoryDeleteLoading"
        :disabled="runHistoryDeleteBlocked"
        @click="deleteSelectedRunHistory"
      >删除历史记录</el-button>
      <span class="muted">{{ selectedRun?.actual_started_at || selectedRun?.scheduled_start_at || '—' }} 至 {{ selectedRun?.actual_ended_at || '进行中' }}</span>
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
            <article><span>当前活动运行</span><strong>{{ status?.active_run_date || '无' }}</strong><small>{{ status?.active_run_id || '当前没有正在执行的运行' }}</small></article>
            <article><span>最近历史运行</span><strong>{{ status?.latest_run_date || '—' }}</strong><small>{{ status?.latest_run_state ? groundStatusLabel(status.latest_run_state) : '暂无历史运行' }}</small></article>
            <article><span>{{ t('ground.window', '配置运行时间') }}</span><strong>{{ status?.schedule_start_time }} - {{ status?.schedule_end_time }}</strong></article>
            <article><span>{{ t('ground.next_start', '下一次启动') }}</span><strong>{{ status?.next_start_at || '—' }}</strong></article>
            <article><span>{{ t('ground.next_end', '下一次结束') }}</span><strong>{{ status?.next_end_at || '—' }}</strong></article>
            <article><span>{{ t('ground.ac_updated', 'AC 最近更新') }}</span><strong>{{ status?.ac_last_updated_at || '—' }}</strong></article>
            <article><span>{{ t('ground.mainline_trains', '正线列车') }}</span><strong>{{ status?.mainline_train_count ?? 0 }}</strong></article>
            <article><span>正线 Ping MR</span><strong>{{ status?.mainline_ping_target_count ?? 0 }}</strong></article>
            <article><span>车辆段 Ping MR</span><strong>{{ status?.depot_ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.ping_mrs', 'Ping 总目标') }}</span><strong>{{ status?.ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.active_deep', '当前深度采集车辆') }}</span><strong>{{ status?.active_deep_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.covered_today', '今日已完成 / 未完成') }}</span><strong>{{ status?.covered_train_count ?? 0 }} / {{ status?.incomplete_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.disk_usage', '当前占用 / 磁盘剩余') }}</span><strong>{{ bytes(status?.disk_used_bytes ?? 0) }} / {{ bytes(status?.disk_free_bytes ?? 0) }}</strong><el-tag size="small" :type="statusType(status?.disk_status || '')">{{ groundStatusLabel(status?.disk_status) }}</el-tag></article>
            <article><span>{{ t('ground.latest_archive', '最近归档') }}</span><strong>{{ status?.latest_archive_status ? groundStatusLabel(status.latest_archive_status) : '—' }}</strong><small>{{ status?.latest_archive_message }}</small></article>
            <article><span>Syslog 活跃 / 配置异常</span><strong>{{ status?.syslog_active_mr_count ?? 0 }} / {{ status?.config_abnormal_count ?? 0 }}</strong></article>
            <article><span>射频口关闭 MR</span><strong>{{ status?.radio_down_mr_count ?? 0 }}</strong></article>
            <article><span>今日射频短暂中断</span><strong>{{ status?.radio_bounce_today_count ?? 0 }}</strong></article>
            <article><span>今日 SNMP 射频控制</span><strong>{{ status?.snmp_radio_control_today_count ?? 0 }}</strong></article>
            <article><span>SNMP 控制后未恢复</span><strong>{{ status?.snmp_unrecovered_count ?? 0 }}</strong></article>
            <article><span>射频频繁切换 MR</span><strong>{{ status?.radio_flapping_mr_count ?? 0 }}</strong></article>
            <article><span>最近 SNMP 射频操作</span><strong>{{ status?.last_snmp_radio_control_at || '—' }}</strong></article>
            <article><span>UDP 队列 / 丢弃</span><strong>{{ health?.udp_queue_length ?? 0 }} / {{ health?.udp_dropped_count ?? 0 }}</strong><small>{{ health?.udp_listen_address || '未监听' }}</small></article>
          </div>
          <section class="syslog-transport-band" v-loading="syslogTransportLoading">
            <div class="transport-heading">
              <div>
                <h2>UDP Syslog 与 MR 日志回传</h2>
                <p>MR 目标地址与 NetConsole 本机监听是两条独立配置。</p>
              </div>
              <div class="row-actions">
                <el-button :icon="Refresh" @click="refreshSyslogAddresses">刷新地址</el-button>
                <el-button @click="loadSyslogTransport(false)">检查端口</el-button>
                <el-button @click="activeTab = 'settings'">前往设置</el-button>
                <el-button :icon="CopyDocument" :disabled="!syslogTransport?.configured_return_ip" @click="copyReturnTarget">复制回传目标</el-button>
              </div>
            </div>
            <el-alert
              v-if="syslogTransport && ['NOT_LOCAL', 'INVALID', 'EMPTY'].includes(syslogTransport.return_address_status)"
              :title="syslogTransport.return_address_status === 'NOT_LOCAL' ? `MR 日志回传地址 ${syslogTransport.configured_return_ip}:${syslogTransport.configured_return_port} 当前不属于本机` : groundStatusLabel(syslogTransport.return_address_status)"
              :description="syslogTransport.return_address_status === 'NOT_LOCAL' ? '不会自动采用推荐地址；请前往设置选择本机地址，或明确确认外部/NAT 地址。' : '请前往设置完成有效配置。'"
              type="error"
              :closable="false"
              show-icon
            />
            <el-alert
              v-else-if="syslogTransport?.return_address_status === 'EXTERNAL_CONFIRMED'"
              title="当前使用已确认的外部/NAT 日志回传地址"
              description="启动允许继续，但本机监听端口状态不代表外部映射可达。"
              type="warning"
              :closable="false"
              show-icon
            />
            <div class="transport-grid">
              <article>
                <span>MR 日志回传地址</span>
                <strong>{{ syslogTransport?.configured_return_ip ? `${syslogTransport.configured_return_ip}:${syslogTransport.configured_return_port}` : '尚未配置' }}</strong>
                <el-tag size="small" :type="statusType(syslogTransport?.return_address_status || '')">{{ groundStatusLabel(syslogTransport?.return_address_status) }}</el-tag>
              </article>
              <article>
                <span>系统推荐地址</span>
                <strong>{{ syslogTransport?.recommended_local_ip || '无可靠推荐' }}</strong>
                <small>{{ syslogTransport?.recommended_adapter_name || '未匹配网卡' }} · 仅展示，不自动覆盖</small>
              </article>
              <article>
                <span>本机监听地址</span>
                <strong>{{ syslogTransport ? `${syslogTransport.listen_host}:${syslogTransport.listen_port}` : '—' }}</strong>
                <small>{{ syslogTransport?.listen_host === '0.0.0.0' ? '监听全部本机网卡' : syslogTransport?.actual_listen_address || '指定网卡地址' }}</small>
              </article>
              <article>
                <span>UDP Receiver</span>
                <strong>{{ groundStatusLabel(syslogTransport?.receiver_state) }}</strong>
                <small>{{ syslogTransport?.actual_listen_address || '当前未监听' }}</small>
              </article>
              <article>
                <span>本机监听端口</span>
                <strong>{{ groundStatusLabel(syslogTransport?.port_state) }}</strong>
                <small>{{ syslogTransport?.port_message || '尚未检测' }}</small>
              </article>
              <article>
                <span>MR 目标端口 / 本地端口</span>
                <strong>{{ syslogTransport ? `${syslogTransport.configured_return_port} / ${syslogTransport.listen_port}` : '—' }}</strong>
                <small>{{ syslogTransport?.target_port_message || '尚未检测' }}</small>
              </article>
              <article>
                <span>最近接收 / 已接收</span>
                <strong>{{ syslogTransport?.last_received_at || '尚无记录' }}</strong>
                <small>{{ syslogTransport?.received_count ?? 0 }} 条 · 活跃 MR {{ syslogTransport?.active_mr_count ?? 0 }}</small>
              </article>
              <article>
                <span>身份质量</span>
                <strong>{{ syslogTransport?.unidentified_count ?? 0 }} / {{ syslogTransport?.identity_conflict_count ?? 0 }}</strong>
                <small>未识别来源 / 身份冲突</small>
              </article>
              <article>
                <span>UDP 队列 / 丢弃</span>
                <strong>{{ syslogTransport?.queue_length ?? 0 }} / {{ syslogTransport?.queue_capacity ?? 0 }}</strong>
                <small>已丢弃 {{ syslogTransport?.dropped_count ?? 0 }} 条</small>
              </article>
            </div>
          </section>
        </section>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.trains', '正线车辆')" name="trains">
        <div class="toolbar"><el-input v-model="trainFilter" clearable :placeholder="t('ground.train_filter', '筛选列车、AP、站点或区间')" /></div>
        <div class="coverage-strip">
          <span>轨旁 AP 匹配 <b>{{ locationStats.ap }}</b></span>
          <span>站点文本诊断 <b>{{ locationStats.station }}</b></span>
          <span>AP 未匹配 <b>{{ locationStats.unmatched }}</b></span>
          <span>车辆段 / 停车场 / 存车线 <b>{{ locationStats.excluded }}</b></span>
        </div>
        <div ref="trainTableHost" class="table-frame"><NcDataTable :data="filteredTrains" :columns="trainColumns" table-id="ground-trains" route-key="rail-ground-unattended" row-key="train_id" :max-height="trainTableMaxHeight" auto-height compact>
          <template #cell-eligibility_status="{ row }"><el-tag size="small" :type="statusType(row.eligibility_status)">{{ groundStatusLabel(row.eligibility_status) }}</el-tag></template>
          <template #cell-coverage_status="{ row }"><el-tag size="small" :type="statusType(row.coverage_status)">{{ groundStatusLabel(row.coverage_status) }}</el-tag></template>
          <template #cell-ct_radio="{ row }"><el-tooltip :content="endpointRadioTooltip(row, 'CT')" placement="top"><el-tag size="small" :type="statusType(endpoint(row, 'CT')?.radio_overall_state || 'UNKNOWN')">{{ groundStatusLabel(endpoint(row, 'CT')?.radio_overall_state || 'UNKNOWN') }}</el-tag></el-tooltip></template>
          <template #cell-cw_radio="{ row }"><el-tooltip :content="endpointRadioTooltip(row, 'CW')" placement="top"><el-tag size="small" :type="statusType(endpoint(row, 'CW')?.radio_overall_state || 'UNKNOWN')">{{ groundStatusLabel(endpoint(row, 'CW')?.radio_overall_state || 'UNKNOWN') }}</el-tag></el-tooltip></template>
          <template #cell-ct_control="{ row }"><el-tooltip :content="endpointRadioTooltip(row, 'CT')" placement="top"><span>{{ groundControlSourceLabel(endpoint(row, 'CT')?.cfg_command_source) }}</span></el-tooltip></template>
          <template #cell-cw_control="{ row }"><el-tooltip :content="endpointRadioTooltip(row, 'CW')" placement="top"><span>{{ groundControlSourceLabel(endpoint(row, 'CW')?.cfg_command_source) }}</span></el-tooltip></template>
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
        <div ref="pingTableHost" class="table-frame ping-table"><NcDataTable :data="filteredPing" :columns="pingColumns" table-id="ground-ping" route-key="rail-ground-unattended" row-key="target_ip" :max-height="pingTableMaxHeight" auto-height compact>
          <template #cell-actions="{ row }">
            <el-button
              size="small"
              text
              type="primary"
              :title="row.data_availability === 'SUMMARY_ONLY' ? '仅保留汇总，没有逐包原始数据' : row.data_availability === 'CORRUPT' ? '原始数据或归档校验失败' : row.data_availability === 'MISSING' ? '本运行没有逐包原始数据' : '查看逐包曲线'"
              @click="showPingSeries(row)"
            >查看曲线</el-button>
          </template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.deep_collection', '深度采集')" name="deep">
        <el-alert v-if="profile && !profile.deep_collection_master_enabled" title="当前为轻量模式：深度采集已关闭，历史记录仍可查看。" type="info" :closable="false" show-icon />
        <div class="coverage-strip"><span v-for="value in ['INELIGIBLE','ELIGIBLE','QUEUED','STARTING','RUNNING','STOPPING','STOPPED','FAILED']" :key="value"><b>{{ deepCollections.filter((row) => row.deep_state === value).length }}</b>{{ groundStatusLabel(value) }}</span></div>
        <div ref="deepTableHost" class="table-frame"><NcDataTable :data="deepCollections" :columns="deepColumns" table-id="ground-deep" route-key="rail-ground-unattended" row-key="train_id" :max-height="deepTableMaxHeight" auto-height compact>
          <template #cell-status="{ row }"><el-tag size="small" :type="statusType(row.status)">{{ groundStatusLabel(row.status) }}</el-tag></template>
          <template #cell-deep_state="{ row }"><el-tag size="small" :type="statusType(row.deep_state)">{{ groundStatusLabel(row.deep_state) }}</el-tag></template>
          <template #cell-collector_data="{ row }"><div class="row-actions"><el-button v-for="collector in row.collectors" :key="collector.mr_role || collector.mr_id" size="small" text type="primary" :disabled="!collector.collector_session_id" @click="showDeepCollector(collector)">{{ collector.mr_role || collector.mr_id }} {{ collector.state }}</el-button><span v-if="!row.collectors.length" class="muted">尚未创建会话</span></div></template>
        </NcDataTable></div>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.timeline', '时间轴')" name="timeline" class="log-console-pane">
        <NcLogWorkspace>
          <template #header>
            <div class="toolbar log-filter-grid timeline-filter-grid">
              <el-input v-model="timelineFilter.query" clearable placeholder="设备名称、列车号或 CT/CW" />
              <el-select v-model="timelineFilter.eventType" clearable placeholder="事件类型">
                <el-option v-for="value in ['ap_transition', 'mesh_linkup', 'mesh_linkdown', 'mesh_activelink_switch', 'ifnet_phy_updown', 'radio_interface_down', 'radio_interface_up', 'radio_interface_recovered', 'radio_interface_bounce', 'radio_interface_flapping', 'cfgman_snmp_change', 'radio_snmp_down', 'radio_snmp_up', 'radio_snmp_bounce', 'radio_snmp_flapping', 'ping_loss_pattern', 'run_started', 'run_completed', 'stop_failed']" :key="value" :label="groundEventLabel(value)" :value="value" />
              </el-select>
              <el-button :icon="Refresh" @click="timelinePage = 1; loadTimelineData(false)">{{ t('common.query', '查询') }}</el-button>
            </div>
          </template>
          <NcDataTable
            :data="filteredTimeline"
            :columns="timelineColumns"
            table-id="ground-timeline"
            route-key="rail-ground-unattended"
            row-key="event_id"
            fill-remaining-height
            compact
          />
          <template #pagination>
            <el-pagination
              v-model:current-page="timelinePage"
              v-model:page-size="timelinePageSize"
              :total="timelineTotal"
              :page-sizes="[50, 100, 200, 500]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadTimelineData(false)"
              @size-change="timelinePage = 1; loadTimelineData(false)"
            />
          </template>
        </NcLogWorkspace>
      </el-tab-pane>

      <el-tab-pane label="Syslog 日志" name="syslog" class="log-console-pane">
        <NcLogWorkspace :loading="syslogLoading">
          <template #header>
            <div class="toolbar log-filter-grid syslog-common-filters">
              <el-input v-model="syslogFilter.trainId" clearable placeholder="列车 ID" />
              <el-input v-model="syslogFilter.mrName" clearable placeholder="MR 设备名称" />
              <el-select v-model="syslogFilter.mrRole" clearable placeholder="CT/CW"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select>
              <el-input v-model="syslogFilter.sourceIp" clearable placeholder="来源 IP" />
              <el-select v-model="syslogFilter.eventType" clearable placeholder="原始事件">
                <el-option v-for="value in ['MESH_LINKUP', 'MESH_LINKDOWN', 'MESH_ACTIVELINK_SWITCH', 'IFNET_PHY_UPDOWN', 'CFGMAN_CFGCHANGED']" :key="value" :label="groundEventLabel(value)" :value="value" />
              </el-select>
              <el-input v-model="syslogFilter.peerName" clearable placeholder="AP 名称或 MAC" />
              <el-date-picker v-model="syslogTimeRange" type="datetimerange" start-placeholder="开始时间" end-placeholder="结束时间" />
              <el-button @click="syslogAdvancedFiltersOpen = !syslogAdvancedFiltersOpen">
                高级筛选（{{ syslogAdvancedFilterCount }} 个条件）
              </el-button>
              <el-checkbox v-model="syslogAutoRefresh">自动刷新{{ historicalRun ? t('ground.syslog.auto_refresh_30', '（30 秒）') : '' }}</el-checkbox>
              <el-button type="primary" :icon="Refresh" :loading="syslogLoading" @click="syslogFilter.page = 1; loadSyslog()">查询</el-button>
            </div>
            <el-collapse-transition>
              <div v-show="syslogAdvancedFiltersOpen" class="toolbar log-filter-grid syslog-advanced-filters">
                <el-input v-model="syslogFilter.systemName" clearable placeholder="system_name" />
                <el-input v-model="syslogFilter.facility" clearable placeholder="Facility" />
                <el-select v-model="syslogFilter.severity" clearable placeholder="严重级别">
                  <el-option label="提示" value="info" /><el-option label="警告" value="warning" /><el-option label="错误" value="error" />
                </el-select>
                <el-select v-model="syslogFilter.identityStatus" clearable placeholder="身份状态">
                  <el-option label="身份已确认" value="VERIFIED" /><el-option label="来源未识别" value="UNIDENTIFIED" /><el-option label="身份冲突" value="IDENTITY_CONFLICT" />
                </el-select>
                <el-select v-model="syslogFilter.eventFamily" clearable placeholder="事件族">
                  <el-option label="WMESH" value="WMESH" /><el-option label="IFNET" value="IFNET" /><el-option label="CFGMAN" value="CFGMAN" />
                </el-select>
                <el-select v-model="syslogFilter.commandSource" clearable placeholder="控制来源">
                  <el-option label="SNMP" value="snmp" /><el-option label="CLI" value="cli" /><el-option label="NETCONF" value="netconf" />
                </el-select>
                <el-select v-model="syslogFilter.physicalState" clearable placeholder="射频状态">
                  <el-option label="开启" value="UP" /><el-option label="关闭" value="DOWN" />
                </el-select>
                <el-select v-model="syslogFilter.correlationStatus" clearable placeholder="关联状态">
                  <el-option label="已关联" value="CORRELATED" /><el-option label="未关联" value="UNCORRELATED" />
                </el-select>
                <el-select v-model="syslogFilter.correlationConfidence" clearable placeholder="关联置信度">
                  <el-option label="高置信度" value="HIGH" /><el-option label="中置信度" value="MEDIUM" />
                </el-select>
                <el-select v-model="syslogFilter.dataSource" clearable placeholder="数据来源">
                  <el-option label="活动原始文件" value="ACTIVE" /><el-option label="READY 归档" value="ARCHIVE" />
                </el-select>
                <el-input v-model="syslogFilter.keyword" clearable placeholder="原始内容关键字" />
              </div>
            </el-collapse-transition>
          </template>
          <template #summary>
            <section v-if="syslogIssue" class="syslog-failure">
          <el-alert
            :title="t('ground.syslog.failure_title', 'Syslog 日志暂时无法加载')"
            :description="syslogIssue.message"
            type="error"
            :closable="false"
            show-icon
          />
          <div class="coverage-strip">
            <span>{{ t('ground.syslog.backend_status', 'Backend 状态') }} <b>{{ groundStatusLabel(syslogBackendState) }}</b></span>
            <span>{{ t('ground.syslog.error_type', '错误类型') }} <b>{{ syslogErrorCode || 'UNKNOWN_ERROR' }}</b></span>
            <span>{{ t('ground.syslog.failure_count', '失败次数') }} <b>{{ syslogFailureCount }}</b></span>
            <span>{{ t('ground.syslog.last_attempt', '最近尝试') }} <b>{{ syslogLastAttemptAt || '—' }}</b></span>
            <span v-if="syslogRequestId">{{ t('ground.syslog.request_id', '请求编号') }} <b>{{ syslogRequestId }}</b></span>
          </div>
          <div class="row-actions">
            <el-button :icon="Refresh" :loading="syslogLoading" type="primary" @click="loadSyslog()">{{ t('ground.syslog.retry', '重新查询') }}</el-button>
            <el-button @click="openBackendLogs">{{ t('ground.syslog.open_backend_logs', '查看 Backend 日志') }}</el-button>
          </div>
            </section>
            <el-alert
              v-else-if="syslogDiagnostics?.truncated"
              :title="t('ground.syslog.truncated', '日志量较大，本次已返回最近的数据。请设置时间范围或增加筛选条件。')"
              type="warning"
              :closable="false"
              show-icon
            />
            <div v-if="syslogDiagnostics" class="coverage-strip">
              <span>数据来源 <b>{{ groundSourceLabel(syslogDiagnostics.source_kind) }}</b></span>
              <span>可用性 <b>{{ groundStatusLabel(syslogDiagnostics.data_availability) }}</b></span>
              <span>扫描文件 <b>{{ syslogDiagnostics.files_scanned }}</b></span>
              <span>扫描记录 <b>{{ syslogDiagnostics.records_scanned }}</b></span>
              <span>匹配记录 <b>{{ syslogTotal }}{{ syslogTotalExact ? '' : '+' }}</b></span>
              <span>接收器 <b>{{ health?.udp_running ? '正在监听' : '未监听' }}</b></span>
              <span v-if="syslogDiagnostics.no_data_reason">{{ groundStatusLabel(syslogDiagnostics.no_data_reason) }}</span>
            </div>
          </template>
          <template #actions>
            <div class="syslog-bulk-actions">
              <span>已选择 {{ selectedSyslogRecords.length }} 条（表头复选框可全选当前页）</span>
              <el-checkbox v-model="syslogDeleteDerived">同时删除派生 WMESH/时间轴事件</el-checkbox>
              <el-button :icon="Delete" :loading="syslogDeleteLoading" :disabled="syslogDeleteBlocked || !selectedSyslogRecords.length" @click="deleteSyslog('SELECTED')">删除选中日志</el-button>
              <el-button :icon="Delete" :loading="syslogDeleteLoading" :disabled="syslogDeleteBlocked || !syslogHasActiveFilters" @click="deleteSyslog('FILTERED')">删除当前筛选范围</el-button>
              <el-button type="danger" plain :icon="Delete" :loading="syslogDeleteLoading" :disabled="syslogDeleteBlocked" @click="deleteSyslog('RUN_ALL')">删除当前运行全部 Syslog</el-button>
              <span v-if="syslogDeleteBlocked" class="muted">活动运行、ERROR 状态、OPEN 文件与最终化阶段禁止删除</span>
            </div>
          </template>
          <NcDataTable
            :data="syslogRecords"
            :columns="syslogColumns"
            table-id="ground-syslog:v2"
            route-key="rail-ground-unattended"
            :row-key="syslogRowKey"
            fill-remaining-height
            compact
            @selection-change="handleSyslogSelection"
          >
          <template #cell-actions="{ row }"><el-button size="small" text type="primary" @click="showSyslogRecord(row)">详情</el-button></template>
          </NcDataTable>
          <template #pagination>
            <el-pagination
              v-model:current-page="syslogFilter.page"
              v-model:page-size="syslogFilter.pageSize"
              :total="syslogTotal"
              :page-sizes="[50, 100, 200, 500]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadSyslog"
              @size-change="syslogFilter.page = 1; loadSyslog()"
            />
          </template>
        </NcLogWorkspace>
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
        <section class="content-card ac-poller-health">
          <div class="section-heading">
            <div><h2>AC 常驻轮询</h2><p>每台控制器一个常驻 Task 和一个活动 SSH 会话；重连保持同一 Task。</p></div>
          </div>
          <el-empty v-if="!health?.ac_pollers?.length" description="当前没有活动 AC 常驻轮询" />
          <div v-else class="ac-poller-grid">
            <article v-for="poller in health.ac_pollers" :key="poller.task_id || poller.controller_id">
              <header><strong>{{ poller.controller_name || poller.controller_id }}</strong><el-tag size="small">{{ poller.status }}</el-tag></header>
              <p>{{ poller.connection_state }} · {{ poller.poll_interval_seconds }} 秒</p>
              <small>轮询 {{ poller.poll_count }} · 成功 {{ poller.success_count }} · 失败 {{ poller.failure_count }} · 重连 {{ poller.reconnect_count }}</small>
              <small>最近成功 {{ poller.last_success_at || '—' }} · 下次 {{ poller.next_poll_at || '—' }}</small>
              <small>心跳年龄 {{ poller.heartbeat_age_seconds == null ? '—' : `${poller.heartbeat_age_seconds.toFixed(1)} 秒` }}</small>
              <small v-if="poller.last_error" class="health-error">{{ poller.last_error }}</small>
            </article>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane :label="t('ground.archives', '历史归档')" name="archives">
        <div class="toolbar"><el-button :icon="FolderOpened" @click="openArchiveDirectory">{{ t('ground.open_archive_directory', '打开归档目录') }}</el-button></div>
        <div ref="archiveTableHost" class="table-frame"><NcDataTable :data="archives" :columns="archiveColumns" table-id="ground-archives" route-key="rail-ground-unattended" row-key="archive_id" :max-height="archiveTableMaxHeight" auto-height compact>
          <template #cell-archive_status="{ row }"><el-tag size="small" :type="statusType(row.archive_status)">{{ groundStatusLabel(row.archive_status) }}</el-tag></template>
          <template #cell-actions="{ row }"><div class="row-actions"><el-button size="small" text type="primary" @click="showArchive(row)">{{ t('common.view', '查看') }}</el-button><el-button :icon="Download" size="small" text circle title="下载原始 ZIP" @click="downloadArchiveZip(row)" /><el-button size="small" text @click="downloadArchiveSummary(row)">JSON</el-button><el-button :icon="Delete" size="small" text type="danger" circle :title="t('common.delete', '删除')" @click="removeArchive(row)" /></div></template>
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
            <el-form-item label="Ping 车辆段/停车场列车">
              <div class="switch-with-description">
                <el-switch v-model="profile.ping_depot_trains_enabled" />
                <span>启用后，对当前位于车辆段、停车场或存车线的在线列车执行 CT/CW 长 Ping。该设置不会将车辆计入正线，也不会自动启动深度 MR 采集。</span>
              </div>
            </el-form-item>
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
            <el-form-item label="自动补齐 MR Syslog 临时配置">
              <el-switch v-model="profile.syslog_auto_repair_enabled" />
              <small>无人值守启动或检测到 MR 新上电周期时，自动检查并补齐 Profile v2 临时配置；不会保存设备配置，也不会由 CFGMAN 事件触发。</small>
            </el-form-item>
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

    <NcFloatingWindow
      v-model="pingWindowOpen"
      :title="selectedPingTarget ? `${selectedPingTarget.train_no || selectedPingTarget.train_id} · ${selectedPingTarget.mr_name || selectedPingTarget.mr_position_code} · ${selectedPingTarget.target_ip}` : '长 Ping 逐包曲线'"
      :subtitle="selectedPingTarget ? `运行日期 ${selectedPingTarget.run_date || selectedRun?.run_date || '—'} · ${selectedPingHistorical ? '历史静态数据' : !pingInitialLoadSucceeded ? '首次查询未完成' : pingPaused ? '实时刷新已暂停' : '实时增量'} · ${groundStatusLabel(pingAvailability)}` : ''"
      window-id="ground-ping-series"
      route-key="rail-ground-unattended"
      @close="handlePingDialogClosed"
    >
      <section v-if="selectedPingTarget" class="ping-floating-content">
        <div class="toolbar">
          <el-select v-model="pingRange" aria-label="长 Ping 时间范围" @change="showPingSeries(selectedPingTarget)">
            <el-option label="完整运行时段" value="run" />
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
          <el-checkbox v-model="pingAutoRefresh" :disabled="selectedPingHistorical || !pingInitialLoadSucceeded">实时增量</el-checkbox>
          <el-checkbox v-model="pingFollowLatest">跟随最新</el-checkbox>
          <el-button v-if="!selectedPingHistorical" :icon="pingPaused ? VideoPlay : VideoPause" @click="togglePingPaused">{{ pingPaused ? '继续' : '暂停' }}</el-button>
          <el-button v-if="!pingFollowLatest" type="primary" plain @click="returnPingToLive">回到实时</el-button>
          <el-button @click="useFullPingRange">完整运行</el-button>
          <el-button :icon="Refresh" :loading="pingSeriesLoading || pingIncrementalLoading" @click="showPingSeries(selectedPingTarget, true)">刷新</el-button>
        </div>
        <div class="coverage-strip ping-query-identity">
          <span>运行 <b>{{ selectedPingTarget.run_id || selectedRunId }}</b></span>
          <span>目标 IP <b>{{ selectedPingTarget.target_ip }}</b></span>
          <span>MR <b>{{ selectedPingTarget.mr_name || selectedPingTarget.mr_id || '未知' }}</b></span>
          <span>端位 <b>{{ selectedPingTarget.mr_position_code || '未知' }}</b></span>
        </div>
        <div class="coverage-strip">
          <span>原始样本 <b>{{ pingSeries?.raw_sample_count ?? 0 }}</b></span>
          <span>有效样本 <b>{{ pingSeries?.effective_sample_count ?? 0 }}</b></span>
          <span>预热忽略 <b>{{ pingSeries?.ignored_sample_count ?? 0 }}</b></span>
          <span>成功 / 丢包 <b>{{ pingLiveStats.success }} / {{ pingLiveStats.loss }}</b></span>
          <span>丢包率 <b>{{ pingLiveStats.lossRate.toFixed(2) }}%</b></span>
          <span>当前 / 平均 / 最大 RTT <b>{{ metric(pingLiveStats.currentRtt, 'ms') }} / {{ metric(pingLiveStats.averageRtt, 'ms') }} / {{ metric(pingLiveStats.maxRtt, 'ms') }}</b></span>
          <span>最长连续丢包 <b>{{ selectedPingTarget.continuous_loss_max_count ?? 0 }} / {{ (selectedPingTarget.continuous_loss_max_seconds ?? 0).toFixed(1) }}s</b></span>
          <span v-if="pingSeries">来源 <b>{{ groundSourceLabel(pingSeries.diagnostics.source_kind) }}</b></span>
          <span v-if="pingSeries">可用性 <b>{{ groundStatusLabel(pingSeries.diagnostics.data_availability) }}</b></span>
        </div>
        <div class="coverage-strip">
          <span>Registry 文件 <b>{{ pingSeries?.diagnostics.raw_file_registry_hit_count ?? selectedPingTarget.raw_file_count ?? 0 }}</b></span>
          <span>扫描文件 <b>{{ pingSeries?.diagnostics.files_scanned ?? 0 }}</b></span>
          <span>扫描记录 <b>{{ pingSeries?.diagnostics.records_scanned ?? 0 }}</b></span>
          <span>匹配记录 <b>{{ pingSeries?.diagnostics.matched_count ?? 0 }}</b></span>
          <span>当前状态 <b>{{ groundStatusLabel(pingSeries?.target_state || selectedPingTarget.data_availability) }}</b></span>
          <span>当前 AP <b>{{ pingLiveStats.currentAp || '未知' }}</b></span>
          <span>站点 / 区间 <b>{{ pingLiveStats.station || '未知' }} / {{ pingLiveStats.section || '未知' }}</b></span>
          <span>最近样本 <b>{{ pingLiveStats.latestAt || '尚无样本' }}</b></span>
          <span v-if="pingSeries?.diagnostics.truncated">查询预算已截断</span>
          <span v-if="pingIncrementalLoading">正在补拉增量</span>
        </div>
        <el-alert
          v-if="pingIssue"
          class="ping-query-error"
          type="error"
          :closable="false"
          show-icon
          :title="pingIssue.message"
        >
          <template #default>
            <div class="coverage-strip">
              <span>错误码 <b>{{ pingErrorCode || 'UNKNOWN_ERROR' }}</b></span>
              <span>Backend <b>{{ pingBackendState }}</b></span>
              <span v-if="pingRequestId">request_id <b>{{ pingRequestId }}</b></span>
              <span v-if="pingSeries?.diagnostics.no_data_reason">原因 <b>{{ pingSeries.diagnostics.no_data_reason }}</b></span>
            </div>
            <div class="row-actions">
              <el-button type="primary" plain @click="showPingSeries(selectedPingTarget, true)">重试</el-button>
              <el-button :icon="CopyDocument" @click="copyPingDiagnostics">复制诊断信息</el-button>
              <el-button @click="openPingBackendLogs">查看 Backend 日志</el-button>
            </div>
          </template>
        </el-alert>
        <el-skeleton v-if="pingSeriesLoading && !pingSeries" :rows="8" animated />
        <el-empty
          v-else-if="!pingSeries?.points.length"
          class="ping-empty-state"
          :description="pingEmptyDescription"
        >
          <div class="row-actions">
            <el-button v-if="pingRange !== 'run'" @click="useFullPingRange">切换到完整运行时段</el-button>
            <el-button :icon="CopyDocument" @click="copyPingDiagnostics">复制文件诊断</el-button>
            <el-button @click="openPingBackendLogs">查看 Backend 日志</el-button>
          </div>
        </el-empty>
        <div v-else class="ping-chart-workspace">
          <GroundPingChart
            :series="pingSeries"
            :follow-latest="pingFollowLatest"
            @user-zoom="pingFollowLatest = false"
          />
        </div>
        <section v-if="pingSeries?.points.length" class="ping-loss-panel">
          <h3>丢包区段</h3>
          <el-table :data="pingSeries?.loss_windows || []" size="small" max-height="220" empty-text="暂无丢包区段">
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
      </section>
    </NcFloatingWindow>

    <NcFloatingWindow
      v-model="deepWindowOpen"
      :title="selectedDeepCollector ? `${selectedDeepCollector.train_id} · ${selectedDeepCollector.mr_role || selectedDeepCollector.mr_id} · 深度采集实时数据` : '深度采集实时数据'"
      :subtitle="selectedDeepCollector ? `${groundStatusLabel(selectedDeepCollector.state)} · ${selectedDeepCollector.collector_session_id || '尚未创建会话'}` : ''"
      window-id="ground-deep-collection"
      route-key="rail-ground-unattended"
      @close="handleDeepWindowClosed"
    >
      <section v-if="selectedDeepCollector" class="deep-floating-content">
        <div class="coverage-strip">
          <span>运行 <b>{{ selectedDeepCollector.run_id || selectedRunId }}</b></span>
          <span>MR <b>{{ selectedDeepCollector.mr_role || '未知' }} / {{ selectedDeepCollector.management_ip || '未配置' }}</b></span>
          <span>状态 <b>{{ groundStatusLabel(selectedDeepCollector.state) }}</b></span>
          <span>开始 <b>{{ selectedDeepCollector.started_at || '尚未开始' }}</b></span>
          <span>最后记录 <b>{{ selectedDeepCollector.last_record_at || '尚未收到数据' }}</b></span>
          <span>原始数据 <b>{{ bytes(selectedDeepCollector.bytes_written) }}</b></span>
          <span>AP / 站点 <b>{{ selectedDeepCollector.current_ap || '未知' }} / {{ selectedDeepCollector.station || '未知' }}</b></span>
        </div>
        <div class="toolbar">
          <el-select v-model="deepCategory" @change="loadDeepRecords(true)">
            <el-option label="全部" value="ALL" /><el-option label="WMESH" value="WMESH" />
            <el-option label="RSSI" value="RSSI" /><el-option label="Radio" value="RADIO" />
            <el-option label="状态" value="STATUS" /><el-option label="原始输出" value="RAW_OUTPUT" />
          </el-select>
          <el-input v-model="deepKeyword" clearable placeholder="搜索实时记录" @change="loadDeepRecords(true)" />
          <el-checkbox v-model="deepAutoRefresh">自动刷新</el-checkbox>
          <el-button :icon="deepPaused ? VideoPlay : VideoPause" @click="toggleDeepPaused">{{ deepPaused ? '继续显示' : '暂停显示' }}</el-button>
          <el-button :icon="Refresh" :loading="deepRecordsLoading" @click="loadDeepRecords(true)">跳到最新</el-button>
          <el-button :icon="CopyDocument" @click="copyDeepRecords">复制</el-button>
        </div>
        <el-alert v-if="!selectedDeepCollector.collector_session_id" type="info" :closable="false" show-icon :title="selectedDeepCollector.state_reason" />
        <div v-else class="deep-records-container">
          <el-table :data="deepRecords" size="small" height="100%" :empty-text="selectedDeepCollector.state === 'RUNNING' ? 'Collector 已运行，等待原始记录写入' : '暂无可读取的采集记录'">
            <el-table-column prop="timestamp" label="时间" min-width="180" />
            <el-table-column prop="category" label="分类" width="110" />
            <el-table-column prop="source" label="来源" min-width="150" />
            <el-table-column prop="text" label="记录" min-width="540" show-overflow-tooltip />
          </el-table>
        </div>
      </section>
    </NcFloatingWindow>

    <el-dialog v-model="archiveDialog" :title="t('ground.archive_summary', '无人值守归档汇总')" width="min(1100px, 96vw)" top="4vh">
      <el-tabs v-if="selectedArchive" v-model="archiveDetailTab">
        <el-tab-pane label="归档概览" name="overview">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('ground.run_date', '运行日期')">{{ selectedArchive.archive.run_date }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.archive_status', '归档状态')">{{ groundStatusLabel(selectedArchive.archive.archive_status) }}</el-descriptions-item>
            <el-descriptions-item label="实际开始">{{ selectedArchive.archive.actual_started_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="实际结束">{{ selectedArchive.archive.actual_ended_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="运行模式">{{ groundRunModeLabel(selectedArchive.archive.summary.running_mode) }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.mainline_trains', '正线车辆')">{{ selectedArchive.archive.mainline_train_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.ping_targets', 'Ping 目标')">{{ selectedArchive.archive.ping_target_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.ping_samples', 'Ping 样本')">{{ selectedArchive.archive.ping_sample_count }}</el-descriptions-item>
            <el-descriptions-item label="Syslog 记录">{{ selectedArchive.archive.summary.syslog_record_count || 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.covered_trains', '覆盖列车')">{{ selectedArchive.archive.covered_train_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.complete_sessions', '完整会话')">{{ selectedArchive.archive.complete_session_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.partial_sessions', '部分会话')">{{ selectedArchive.archive.partial_session_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.archive_size', '归档大小')">{{ bytes(selectedArchive.archive.archive_size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="归档 SHA-256" :span="2"><code>{{ selectedArchive.archive.sha256 }}</code></el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="文件清单" name="files">
          <el-table :data="selectedArchive.files" size="small" max-height="480" empty-text="归档没有可展示的文件成员">
            <el-table-column prop="path" label="ZIP Entry" min-width="300" fixed />
            <el-table-column prop="data_type" label="数据类型" width="110" />
            <el-table-column prop="train_id" label="列车" width="120" />
            <el-table-column prop="mr_id" label="MR" min-width="150" />
            <el-table-column prop="mr_role" label="CT/CW" width="80" />
            <el-table-column prop="hour" label="小时" width="90" />
            <el-table-column prop="record_count" label="记录数" width="100" />
            <el-table-column label="原始大小" width="120"><template #default="{ row }">{{ bytes(row.size_bytes) }}</template></el-table-column>
            <el-table-column label="压缩大小" width="120"><template #default="{ row }">{{ bytes(row.compressed_size_bytes) }}</template></el-table-column>
            <el-table-column prop="parse_status" label="解析状态" width="110" />
            <el-table-column prop="sha256" label="SHA-256" min-width="260" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="Ping 汇总" name="ping">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Ping 目标">{{ selectedArchive.archive.ping_target_count }}</el-descriptions-item>
            <el-descriptions-item label="Ping 样本">{{ selectedArchive.archive.ping_sample_count }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="Syslog 汇总" name="syslog">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Syslog 记录">{{ selectedArchive.archive.summary.syslog_record_count || 0 }}</el-descriptions-item>
            <el-descriptions-item label="Syslog 文件">{{ selectedArchive.files.filter((row) => row.data_type === 'syslog').length }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="深度会话" name="deep">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="完整会话">{{ selectedArchive.archive.complete_session_count }}</el-descriptions-item>
            <el-descriptions-item label="部分会话">{{ selectedArchive.archive.partial_session_count }}</el-descriptions-item>
            <el-descriptions-item label="覆盖列车">{{ selectedArchive.archive.covered_train_count }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="完整性校验" name="integrity">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="校验状态">{{ groundStatusLabel(selectedArchive.validation.status) }}</el-descriptions-item>
            <el-descriptions-item label="最后校验">{{ selectedArchive.validation.checked_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="清单文件数">{{ selectedArchive.validation.file_count }}</el-descriptions-item>
            <el-descriptions-item label="总记录数">{{ archiveRecordCount }}</el-descriptions-item>
            <el-descriptions-item label="ZIP 大小">{{ bytes(selectedArchive.validation.archive_size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="旧版 Manifest">{{ selectedArchive.validation.legacy_manifest ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="ZIP SHA-256" :span="2"><code>{{ selectedArchive.validation.archive_sha256 }}</code></el-descriptions-item>
            <el-descriptions-item label="Manifest SHA-256" :span="2"><code>{{ selectedArchive.validation.manifest_sha256 }}</code></el-descriptions-item>
            <el-descriptions-item label="校验说明" :span="2">{{ selectedArchive.validation.message }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="保留策略" name="retention">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="保留截止">{{ selectedArchive.archive.retention_until || '未设置' }}</el-descriptions-item>
            <el-descriptions-item label="归档创建">{{ selectedArchive.archive.created_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="最近更新">{{ selectedArchive.archive.updated_at || '—' }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button v-if="selectedArchive" @click="verifyArchive">重新校验</el-button>
        <el-button v-if="selectedArchive" @click="downloadArchiveSummary(selectedArchive.archive)">下载 JSON</el-button>
        <el-button v-if="selectedArchive" type="primary" @click="downloadArchiveZip(selectedArchive.archive)">下载原始 ZIP</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="syslogDetailDrawer" title="Syslog 原始记录详情" size="min(720px, 92vw)" destroy-on-close>
      <template v-if="selectedSyslogRecord">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="运行上下文">{{ selectedRun?.run_date || '—' }} · {{ selectedRunId || '—' }}</el-descriptions-item>
          <el-descriptions-item label="接收 / 设备时间">{{ selectedSyslogRecord.receive_time }} / {{ selectedSyslogRecord.device_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="时间差">{{ selectedSyslogRecord.clock_offset_ms == null ? '—' : `${selectedSyslogRecord.clock_offset_ms} ms` }}</el-descriptions-item>
          <el-descriptions-item label="列车 / MR">{{ selectedSyslogRecord.train_no || '未识别' }}（{{ selectedSyslogRecord.train_id || '—' }}）/ {{ selectedSyslogRecord.mr_name || selectedSyslogRecord.source_ip }}（{{ selectedSyslogRecord.device_uuid || '—' }}）</el-descriptions-item>
          <el-descriptions-item label="来源 / system_name">{{ selectedSyslogRecord.source_ip }}:{{ selectedSyslogRecord.source_port || '—' }} / {{ selectedSyslogRecord.system_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="Facility / 级别">{{ selectedSyslogRecord.facility || '—' }} / {{ groundSeverityLabel(selectedSyslogRecord.severity) }}</el-descriptions-item>
          <el-descriptions-item label="事件族 / 事件">{{ selectedSyslogRecord.event_family || '—' }} / {{ groundEventLabel(selectedSyslogRecord.event_type) }}</el-descriptions-item>
          <el-descriptions-item label="射频接口 / 状态">{{ selectedSyslogRecord.interface_name || '—' }} / {{ groundStatusLabel(selectedSyslogRecord.physical_state) }}</el-descriptions-item>
          <el-descriptions-item label="CFG EventIndex / 来源">{{ selectedSyslogRecord.cfg_event_index || '—' }} / {{ groundControlSourceLabel(selectedSyslogRecord.cfg_command_source) }}</el-descriptions-item>
          <el-descriptions-item label="配置来源 / 目标">{{ selectedSyslogRecord.cfg_source || '—' }} / {{ selectedSyslogRecord.cfg_destination || '—' }}</el-descriptions-item>
          <el-descriptions-item label="预期内部变更">{{ selectedSyslogRecord.expected_internal_change ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="关联状态">{{ groundStatusLabel(selectedSyslogRecord.correlation_status) }} / {{ groundStatusLabel(selectedSyslogRecord.correlation_confidence) }} / {{ selectedSyslogRecord.correlation_delta_ms == null ? '—' : `${selectedSyslogRecord.correlation_delta_ms} ms` }}</el-descriptions-item>
          <el-descriptions-item label="综合事件">{{ selectedSyslogRecord.composite_event_type ? groundEventLabel(selectedSyslogRecord.composite_event_type) : '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联结构化事件 ID">{{ selectedSyslogRecord.correlated_event_ids.length ? selectedSyslogRecord.correlated_event_ids.join(', ') : '—' }}</el-descriptions-item>
          <el-descriptions-item label="AP 切换">{{ selectedSyslogRecord.previous_peer_name || selectedSyslogRecord.previous_peer_mac || '—' }} → {{ selectedSyslogRecord.peer_name || selectedSyslogRecord.peer_mac || '—' }}</el-descriptions-item>
          <el-descriptions-item label="站点 / 区间">{{ selectedSyslogRecord.station || '—' }} / {{ selectedSyslogRecord.section || '—' }}</el-descriptions-item>
          <el-descriptions-item label="AP 解析 / 名称来源">{{ groundStatusLabel(selectedSyslogRecord.resolution_status) }} / {{ groundDisplayNameSourceLabel(selectedSyslogRecord.parsed_details.display_name_source) }}</el-descriptions-item>
          <el-descriptions-item label="身份 / 解析 / 质量">{{ groundStatusLabel(selectedSyslogRecord.identity_status) }} / {{ groundStatusLabel(selectedSyslogRecord.parse_status) }} / {{ groundStatusLabel(selectedSyslogRecord.data_quality) }}</el-descriptions-item>
          <el-descriptions-item label="接收序号">{{ selectedSyslogRecord.global_receive_sequence ?? '—' }} / {{ selectedSyslogRecord.source_receive_sequence ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="数据来源">{{ groundSourceLabel(selectedSyslogRecord.data_source) }}<span v-if="selectedSyslogRecord.archive_entry"> · {{ selectedSyslogRecord.archive_entry }}</span></el-descriptions-item>
          <el-descriptions-item label="原始文件">{{ selectedSyslogRecord.raw_file_id }} · 行 {{ selectedSyslogRecord.raw_line_number ?? '—' }} · {{ groundStatusLabel(selectedSyslogRecord.raw_file_status) }}</el-descriptions-item>
        </el-descriptions>
        <h3>解析字段</h3>
        <pre class="raw-record">{{ JSON.stringify(selectedSyslogRecord.parsed_details, null, 2) }}</pre>
        <h3>原始报文</h3>
        <pre class="raw-record">{{ selectedSyslogRecord.raw_text }}</pre>
      </template>
    </el-drawer>

    <el-dialog v-model="trainDialog" :title="t('ground.train_detail', '列车无人值守详情')" width="min(820px, 94vw)">
      <template v-if="selectedTrain">
        <el-alert
          :title="`AP Identity: ${selectedTrain.ap_identity_diagnostics?.ap_identity_match_status || 'NOT_CHECKED'} / ${selectedTrain.ap_identity_diagnostics?.canonical_current_ap || '—'}`"
          :description="`站点匹配 ${selectedTrain.ap_identity_diagnostics?.station_match_status || 'UNMATCHED'}，依据 ${selectedTrain.ap_identity_diagnostics?.matched_by || 'none'}，主线/Ping 原因码 ${selectedTrain.mainline_reason_code} / ${selectedTrain.ping_reason_code}，决策 r${selectedTrain.decision_revision} ${selectedTrain.decision_source}`"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
        />
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('ground.train', '列车')">{{ selectedTrain.train_no || selectedTrain.train_name }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.eligibility', '正线判断')"><el-tag :type="statusType(selectedTrain.eligibility_status)">{{ groundStatusLabel(selectedTrain.eligibility_status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="位置类型">{{ groundStatusLabel(selectedTrain.location_class) }}</el-descriptions-item>
          <el-descriptions-item label="是否正线">{{ selectedTrain.participates_in_mainline ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="位置判定来源">{{ selectedTrain.location_class_source }}</el-descriptions-item>
          <el-descriptions-item label="Ping 纳入原因" :title="selectedTrain.ping_reason_code">{{ selectedTrain.ping_reason_text || '未评估' }}</el-descriptions-item>
          <el-descriptions-item label="深采资格" :title="selectedTrain.deep_collection_reason_code">{{ selectedTrain.deep_collection_reason_text || '未评估' }}</el-descriptions-item>
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
          <el-descriptions-item label="CT 射频 / 控制来源">{{ groundStatusLabel(endpoint(selectedTrain, 'CT')?.radio_overall_state || 'UNKNOWN') }} / {{ groundControlSourceLabel(endpoint(selectedTrain, 'CT')?.cfg_command_source) }}</el-descriptions-item>
          <el-descriptions-item label="CW 射频 / 控制来源">{{ groundStatusLabel(endpoint(selectedTrain, 'CW')?.radio_overall_state || 'UNKNOWN') }} / {{ groundControlSourceLabel(endpoint(selectedTrain, 'CW')?.cfg_command_source) }}</el-descriptions-item>
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
          <el-button :loading="openingSessionId === selectedTrainCollection?.ct_session_id" :disabled="!selectedTrainCollection?.ct_session_id || Boolean(openingSessionId)" @click="openDeepSession(selectedTrainCollection?.ct_session_id || '')">{{ t('ground.open_ct_session', '打开 CT 会话') }}</el-button>
          <el-button :loading="openingSessionId === selectedTrainCollection?.cw_session_id" :disabled="!selectedTrainCollection?.cw_session_id || Boolean(openingSessionId)" @click="openDeepSession(selectedTrainCollection?.cw_session_id || '')">{{ t('ground.open_cw_session', '打开 CW 会话') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped>
.ground-page{display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0}.page-heading,.heading-actions,.status-line,.toolbar,.coverage-strip,.row-actions,.form-actions,.inline-numbers,.dialog-actions,.network-actions,.network-status,.boot-evidence,.operation-heading,.detail-heading,.mode-switch,.load-warning{display:flex;align-items:center;gap:10px}.page-heading,.operation-heading,.detail-heading{justify-content:space-between;flex-wrap:wrap}.page-heading h1{margin:2px 0 0;font-size:24px;letter-spacing:0}.eyebrow{margin:0;color:var(--el-color-primary);font-size:12px;font-weight:700;letter-spacing:0}.heading-actions,.toolbar,.dialog-actions,.network-actions,.network-status,.boot-evidence{flex-wrap:wrap}.operation-band{padding:12px 14px;border:1px solid var(--el-border-color);border-left:4px solid var(--el-color-warning);background:var(--el-fill-color-light)}.operation-band.operation-completed{border-left-color:var(--el-color-success)}.operation-band.operation-failed{border-left-color:var(--el-color-danger)}.operation-heading>div{display:flex;gap:12px;align-items:center}.operation-band p{margin:8px 0;color:var(--el-text-color-primary)}.operation-band small{color:var(--el-text-color-secondary)}.load-warning{align-items:flex-start}.load-warning :deep(.el-alert){min-width:0;flex:1}.ground-tabs{min-width:0}.ground-tabs :deep(.el-tabs__content),.ground-tabs :deep(.el-tab-pane){min-width:0;min-height:0;overflow:visible}.overview-band{padding:2px 0}.status-line{min-height:42px;flex-wrap:wrap;border-bottom:1px solid var(--el-border-color-lighter)}.metric-grid,.health-grid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:1px;margin-top:12px;background:var(--el-border-color-lighter);border:1px solid var(--el-border-color-lighter)}.metric-grid article,.health-grid article{min-width:0;padding:12px;background:var(--el-bg-color)}.metric-grid span,.metric-grid small,.health-grid span,.health-grid small{display:block;color:var(--el-text-color-secondary);font-size:12px}.metric-grid strong,.health-grid strong{display:block;min-height:24px;margin:6px 0 3px;font-size:18px;letter-spacing:0;overflow-wrap:anywhere}.toolbar{min-height:42px;flex-wrap:wrap}.toolbar .el-input{width:210px}.toolbar .el-select{width:130px}.toolbar .el-input-number{width:110px}.table-frame{height:auto;min-width:0;overflow:visible;border-top:1px solid var(--el-border-color-lighter)}.table-pagination{margin-top:8px}.coverage-strip{flex-wrap:wrap;margin-bottom:8px}.coverage-strip span{display:flex;align-items:center;gap:5px;padding:5px 8px;background:var(--el-fill-color-light);border-radius:4px;color:var(--el-text-color-secondary);font-size:12px}.coverage-strip b{color:var(--el-text-color-primary);font-size:16px}.settings-empty{padding:48px 16px}.settings-empty .muted{max-width:720px;margin:0 auto 12px;overflow-wrap:anywhere}.settings-form{display:flex;flex-direction:column;gap:18px;max-width:1180px}.settings-form section{padding-bottom:16px;border-bottom:1px solid var(--el-border-color-lighter)}.settings-form h2{margin:0 0 12px;font-size:16px;letter-spacing:0}.form-grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:0 16px}.form-grid :deep(.el-input-number),.form-grid :deep(.el-select),.form-grid :deep(.el-input){width:100%}.mode-switch{align-items:flex-start;margin-bottom:12px}.mode-switch span{color:var(--el-text-color-secondary);font-size:12px}.budget-disabled{opacity:.66}.inline-numbers{width:100%}.priority-grid{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:8px}.muted{color:var(--el-text-color-secondary);font-size:12px}.network-actions{margin:12px 0}.network-status{margin:10px 0;padding:8px;background:var(--el-fill-color-light)}.network-ok{color:var(--el-color-success);font-size:12px}.network-error{color:var(--el-color-danger);font-size:12px}.loghost-section{margin-top:14px;padding-top:8px;border-top:1px solid var(--el-border-color-lighter)}.boot-evidence{margin:8px 0;color:var(--el-text-color-secondary);font-size:12px}.form-actions{position:sticky;bottom:0;padding:10px 0;background:var(--el-bg-color)}.dialog-actions{justify-content:flex-end;margin-top:14px}@media(max-width:1300px){.metric-grid,.health-grid{grid-template-columns:repeat(3,minmax(150px,1fr))}.form-grid{grid-template-columns:repeat(3,minmax(170px,1fr))}.priority-grid{grid-template-columns:repeat(4,minmax(110px,1fr))}}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}.metric-grid,.health-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.form-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}.priority-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}}@media(max-width:620px){.metric-grid,.health-grid,.form-grid{grid-template-columns:1fr}.priority-grid{grid-template-columns:repeat(2,minmax(100px,1fr))}.heading-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.heading-actions .el-button{margin:0}.load-warning{flex-direction:column}.toolbar .el-input,.toolbar .el-select{width:100%}}
.ac-poller-health{margin-top:14px}.ac-poller-grid{display:grid;grid-template-columns:repeat(2,minmax(280px,1fr));gap:10px}.ac-poller-grid article{padding:12px;border:1px solid var(--el-border-color);border-radius:6px;background:var(--el-fill-color-extra-light)}.ac-poller-grid header{display:flex;align-items:center;justify-content:space-between;gap:12px}.ac-poller-grid p{margin:8px 0}.ac-poller-grid small{display:block;margin-top:5px;color:var(--el-text-color-secondary);overflow-wrap:anywhere}.ac-poller-grid .health-error{color:var(--el-color-danger)}@media(max-width:900px){.ac-poller-grid{grid-template-columns:1fr}}
.run-context-bar{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 12px;border:1px solid var(--el-border-color-lighter);background:var(--el-fill-color-extra-light)}.run-context-bar>div{display:flex;flex-direction:column;min-width:240px}.run-context-bar>div span{font-size:12px;color:var(--el-text-color-secondary)}.run-context-bar .el-select{width:min(440px,100%)}.ping-floating-content,.deep-floating-content{display:flex;width:100%;height:100%;min-width:720px;min-height:0;flex-direction:column}.ping-floating-content{overflow:auto}.deep-floating-content{overflow:hidden}.ping-floating-content h3,.detail-heading h2{margin:12px 0 8px}.ping-chart-workspace{flex:1;min-height:380px;overflow:hidden}.ping-loss-panel{flex:none}.deep-records-container{flex:1;min-height:0;overflow:hidden}.ping-empty-state{height:210px}.raw-record{max-height:320px;overflow:auto;padding:12px;border:1px solid var(--el-border-color-lighter);background:var(--el-fill-color-extra-light);white-space:pre-wrap;overflow-wrap:anywhere}
.syslog-transport-band{margin-top:14px;padding:14px;border:1px solid var(--el-border-color);background:var(--el-bg-color)}.transport-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.transport-heading h2{margin:0;font-size:16px;letter-spacing:0}.transport-heading p{margin:4px 0 0;color:var(--el-text-color-secondary);font-size:12px}.syslog-transport-band>.el-alert{margin-top:12px}.transport-grid{display:grid;grid-template-columns:repeat(3,minmax(190px,1fr));gap:1px;margin-top:12px;background:var(--el-border-color-lighter);border:1px solid var(--el-border-color-lighter)}.transport-grid article{min-width:0;padding:11px;background:var(--el-bg-color)}.transport-grid span,.transport-grid small{display:block;color:var(--el-text-color-secondary);font-size:12px}.transport-grid strong{display:block;margin:5px 0;overflow-wrap:anywhere;font-size:15px;letter-spacing:0}@media(max-width:1000px){.transport-grid{grid-template-columns:repeat(2,minmax(180px,1fr))}}@media(max-width:620px){.transport-grid{grid-template-columns:1fr}}
.ground-page{height:auto;max-height:none;overflow:visible}
.ground-tabs{min-height:0;overflow:visible}
.ground-tabs :deep(.el-tabs__header){flex:none}
.ground-tabs :deep(.el-tabs__content){height:auto;min-height:0;overflow:visible}
.ground-tabs :deep(.el-tab-pane){height:auto;min-height:0;overflow:visible}
.ground-page--log-view{height:100%;max-height:100%;overflow:hidden}
.ground-page--log-view .ground-tabs{display:flex;flex:1;flex-direction:column;overflow:hidden}
.ground-page--log-view .ground-tabs :deep(.el-tabs__content){flex:1;height:100%;overflow:hidden}
.ground-page--log-view .ground-tabs :deep(.el-tab-pane){height:100%;overflow:auto;overscroll-behavior:contain}
.ground-tabs :deep(.el-tab-pane.log-console-pane){display:flex;overflow:hidden}
.log-filter-grid{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:8px;padding-bottom:8px}
.log-filter-grid :deep(.el-input),.log-filter-grid :deep(.el-select),.log-filter-grid :deep(.el-date-editor){width:100%}
.timeline-filter-grid{grid-template-columns:minmax(240px,2fr) minmax(160px,1fr) auto}
.syslog-common-filters :deep(.el-date-editor){grid-column:span 2}
.syslog-advanced-filters{padding:8px;background:var(--el-fill-color-extra-light);border:1px solid var(--el-border-color-lighter)}
.syslog-failure{padding-bottom:8px}
.syslog-bulk-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;min-height:42px;padding:6px 0;border-top:1px solid var(--el-border-color-lighter)}
.ping-query-error{margin-bottom:10px}
.switch-with-description{display:flex;align-items:flex-start;gap:10px}.switch-with-description span{color:var(--el-text-color-secondary);font-size:12px;line-height:1.5}
@media(max-width:1366px){.log-filter-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}.syslog-common-filters :deep(.el-date-editor){grid-column:span 2}}
@media(max-width:900px){.log-filter-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.timeline-filter-grid{grid-template-columns:1fr 1fr}.timeline-filter-grid .el-button{grid-column:span 2}}
</style>
