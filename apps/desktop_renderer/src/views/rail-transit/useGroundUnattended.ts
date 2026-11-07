import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Box, CopyDocument, Delete, Download, FolderOpened, Refresh, SwitchButton, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import {
  deleteGroundArchive, deleteGroundArchives, deleteGroundRunHistory, getGroundArchiveDetail, getGroundProfile, getGroundStatus, getGroundTrain, groundArchiveSummaryDownloadRequest, groundArchiveZipDownloadRequest, listGroundArchives,
  getGroundHealth, listGroundDeepCollectionRecords, listGroundDeepCollections, listGroundPingTargets, listGroundTimeline, listGroundTrains, requestGroundConfigCheck,
  openGroundArchiveDirectory, pauseGroundRun, resumeGroundRun, saveGroundProfile, setGroundTrainPriority, startGroundRun,
  stopAndArchiveGroundRun, stopGroundRun, saveGroundTrainPolicy, syncGroundInventory,
  checkGroundUdpPort, listLocalIpv4Addresses, recommendLocalSourceIp,
  getActiveGroundOperation, getGroundOperation, getGroundPingSeries, getGroundPingSeriesIncremental, getGroundSyslogTransportStatus,
  listGroundRuns, listGroundSyslogRecords,
  previewGroundSyslogDelete, probeGroundRawQueryTransportState, probeGroundSyslogTransportState, submitGroundSyslogDelete, verifyGroundArchive,
} from '../../api/groundUnattended'
import { apiErrorDetail } from '../../api/client'
import { getOnlineMrSession } from '../../api/onlineMr'
import { getOnlineMrControlPresets } from '../../api/onlineMrControl'
import { listVehicleMrControllers } from '../../api/vehicleMrOnline'
import { getAcMeshLinkSummary, getAcMeshRawTail, listAcMeshLinks, listAcMeshMrs, listAcMeshSnapshots, refreshAcMeshLinks } from '../../api/acMeshLink'
import GroundPingChart from '../../components/ground-unattended/GroundPingChart.vue'
import { NcDataTable, type NcTableColumn } from '../../components/table'
import NcMultiValueFilter from '../../components/table/NcMultiValueFilter.vue'
import NcFloatingWindow from '../../components/workspace/NcFloatingWindow.vue'
import NcLogWorkspace from '../../components/workspace/NcLogWorkspace.vue'
import { useAdaptiveTableHeight } from '../../composables/useAdaptiveTableHeight'
import { t } from '../../i18n/runtime'
import { downloadBackendResource } from '../../platform/runtime'
import { useWorkspaceStore } from '../../stores/workspace'
import { LEGACY_SITE_CONTEXT_CHANGED_EVENT, SITE_CONTEXT_CHANGED_EVENT } from '../../workspace/site-switch'
import type {
  GroundActionResponse, GroundArchive, GroundArchiveDetail, GroundDeepCollection, GroundDeepCollectionRecord, GroundDeepCollector, GroundPingSeries, GroundPingTarget, GroundProfile, GroundStatus,
  GroundHealth, GroundOperation, GroundPingSample, GroundQueryDiagnostics, GroundRun, GroundSyslogRecord,
  GroundSyslogDeleteFilters, GroundSyslogDeletePreview,
  GroundSyslogTransportStatus, GroundTimelineEvent, GroundTrain, LocalIpv4Address, SourceIpRecommendation, UdpPortCheck,
} from '../../types/groundUnattended'
import type { OnlineMrPingPreset } from '../../types/onlineMrControl'
import type { VehicleMrController } from '../../types/vehicleMrOnline'
import type { AcMeshLinkRecord, AcMeshLinkSummary, AcMeshMrStatus, AcMeshRawTail, AcMeshSnapshot } from '../../types/acMeshLink'
import {
  groundDisplayNameSourceLabel, groundEventLabel, groundOperationStageLabel, groundRunModeLabel, groundSeverityLabel,
  groundStopTriggerLabel,
  groundSourceLabel, groundStatusLabel, groundTransitionContextLabel,
} from './groundUnattendedLabels'
import { inject, provide, type InjectionKey } from 'vue'

// The workspace owns shared requests and lifecycle; pages consume one typed context.
export interface LoadIssue {
  key: string
  label: string
  message: string
  code?: string
  requestId?: string
  attemptedAt?: string
  backendState?: 'ONLINE' | 'OFFLINE' | 'UNKNOWN'
}

export function createGroundContext() {
const activeTab = ref('overview')

const pageVisible = ref(!document.hidden)

const pageActivated = ref(true)

const quickContextRevision = ref(0)

const router = useRouter()

const workspace = useWorkspaceStore()

const loading = ref(false)

const saving = ref(false)

const action = ref('')

const status = ref<GroundStatus | null>(null)

const profile = ref<GroundProfile | null>(null)

const pingPresets = ref<OnlineMrPingPreset[]>([])

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
const selectedArchives = ref<GroundArchive[]>([])

const health = ref<GroundHealth | null>(null)

const acMeshSummary = ref<AcMeshLinkSummary | null>(null)

const acMeshLinks = ref<AcMeshLinkRecord[]>([])

const acMeshMrs = ref<AcMeshMrStatus[]>([])

const acMeshSnapshots = ref<AcMeshSnapshot[]>([])

const acMeshRawTail = ref<AcMeshRawTail | null>(null)

const acMeshLoading = ref(false)
const acMeshQuery = reactive({ query: '', station: '', section: '', carEnd: '', dataStatus: '', matchStatus: '', multiplePeers: false, abnormalOnly: false, page: 1, pageSize: 50, mrPage: 1, snapshotPage: 1 })
const acMeshTotals = reactive({ links: 0, mrs: 0, snapshots: 0 })

const acControllers = ref<VehicleMrController[]>([])

const selectedAcControllerId = ref('')

const acControllersLoading = ref(false)

const acControllersError = ref(false)

const selectedAcController = computed(() => acControllers.value.find((item) => item.controller_id === selectedAcControllerId.value) ?? null)

const acRefreshReady = computed(() => Boolean(selectedAcController.value?.connection_ready))

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
const syslogStatistics = ref<Record<string, number | string | null>>({})
const syslogSortOrder = ref<'asc' | 'desc'>('desc')

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
  trainId: '', mrName: '', mrRole: [] as string[], sourceIp: '', systemName: '', facility: '', severity: [] as string[],
  identityStatus: [] as string[], eventType: [] as string[], eventFamily: [] as string[], commandSource: [] as string[], physicalState: [] as string[],
  correlationStatus: [] as string[], correlationConfidence: [] as string[], peerName: '', dataSource: [] as string[], keyword: '',
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

const timelineFilter = reactive({ query: '', eventType: '', trainId: '', mrId: '', mrRole: '', range: [] as string[] })

const timelinePage = ref(1)

const timelinePageSize = ref(100)

const timelineTotal = ref(0)

let pollTimer: number | undefined

// Keep the page's background refreshes on one lane. Ground status and
// heartbeat queries are synchronous backend work, so a burst of independent
// polls can otherwise queue behind the backend thread pool.
let pollInFlight = false
let loadAllInFlight = false

let disposed = false

let siteContextReloadPending = false

const requestControllers = new Map<string, AbortController>()

const requestFingerprints = new Map<string, string>()

const requestPromises = new Map<string, Promise<boolean>>()

const requestSequences = new Map<string, number>()

const requestFailureCounts = new Map<string, number>()

const requestNotifySequences = new Map<string, number>()

const lastPollAt = new Map<string, number>()

const dismissedTerminalOperationIds = new Set<string>()

let completedOperationTimer: number | undefined

const loadIssues = ref<LoadIssue[]>([])

const generalLoadIssues = computed(() => loadIssues.value.filter((item) => (
  item.key !== 'syslog' && !item.key.startsWith('ping-series')
)))

const syslogIssue = computed(() => loadIssues.value.find((item) => item.key === 'syslog') ?? null)

const pingIssue = computed(() => loadIssues.value.find((item) => item.key.startsWith('ping-series')) ?? null)

const loadIssueDescription = computed(() => generalLoadIssues.value.map((item) => `${item.label}：${item.message}`).join('；'))

const profileLoadError = computed(() => loadIssues.value.find((item) => item.key === 'profile')?.message || '')

const running = computed(() => Boolean(status.value && ['STARTING', 'RUNNING', 'PAUSED', 'STOPPING', 'FINALIZING', 'ARCHIVING'].includes(status.value.state)))
// Device inventory is useful in every state, but run-scoped heartbeat data is
// live only after the backend has confirmed RUNNING.
const monitoringRunning = computed(() => status.value?.state === 'RUNNING')

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

function hasSyslogFilterValue(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some((item) => String(item ?? '').trim().length > 0)
  }
  return String(value ?? '').trim().length > 0
}

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
].filter(hasSyslogFilterValue).length)

const syslogHasActiveFilters = computed(() => Object.values(
  currentSyslogDeleteFilters(),
).some(hasSyslogFilterValue))

const runScopedTab = computed(() => ['heartbeat', 'deep', 'timeline', 'syslog'].includes(activeTab.value))

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

const filteredTimeline = computed(() => timeline.value)

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
  { key: 'fping_health', label: '深采 fping', valueType: 'status', minWidth: 190, displayValue: (row) => row.collectors.map((item) => `${item.mr_role}: ${item.fping_status} / ${item.fping_sample_count}`).join('；') || '尚未创建会话' },
  { key: 'failure_reason', label: t('ground.failure_reason', '失败原因'), valueType: 'error', minWidth: 220 },
  { key: 'updated_at', label: t('ground.updated_at', '更新时间'), valueType: 'datetime' },
]

const timelineColumns: NcTableColumn<GroundTimelineEvent>[] = [
  { key: 'device_time', label: t('ground.device_time', '设备时间'), valueType: 'datetime', width: 180 },
  { key: 'received_at', label: t('ground.received_at', '接收时间'), valueType: 'datetime', width: 180 },
  { key: 'event_at', label: t('ground.event_time', '事件时间'), valueType: 'datetime', fixed: 'left', displayValue: (row) => row.event_at || row.ts },
  { key: 'event_type', label: t('ground.event_type', '事件类型'), valueType: 'status', displayValue: (row) => groundEventLabel(row.event_type) },
  { key: 'train_no', label: t('ground.train', '列车'), valueType: 'name', displayValue: (row) => row.train_no ? `列车 ${row.train_no}` : row.train_name || '未知列车' },
  { key: 'mr_name', label: t('ground.mr', 'MR 设备'), valueType: 'text' },
  { key: 'title', label: t('ground.event', '事件'), valueType: 'name' },
  { key: 'message', label: t('ground.message', '说明'), valueType: 'description', minWidth: 260 },
  { key: 'resolution_status', label: 'AP 解析', valueType: 'status', displayValue: (row) => groundStatusLabel(row.resolution_status) },
  { key: 'severity', label: t('ground.severity', '级别'), valueType: 'status', displayValue: (row) => groundSeverityLabel(row.severity) },
  { key: 'actions', label: t('ground.details', '详情'), valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]

const archiveColumns: NcTableColumn<GroundArchive>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 48, fixed: 'left', hideable: false },
  { key: 'run_date', label: t('ground.run_date', '运行日期'), valueType: 'datetime', fixed: 'left' },
  { key: 'actual_started_at', label: t('ground.actual_start', '实际开始'), valueType: 'datetime' },
  { key: 'actual_ended_at', label: t('ground.actual_end', '实际结束'), valueType: 'datetime' },
  { key: 'mainline_train_count', label: t('ground.mainline_trains', '正线车辆'), valueType: 'number' },
  { key: 'ping_target_count', label: t('ground.ping_targets', 'Ping 目标'), valueType: 'number' },
  { key: 'ping_sample_count', label: t('ground.ping_samples', 'Ping 样本'), valueType: 'number' },
  { key: 'covered_train_count', label: t('ground.covered_trains', '深度覆盖'), valueType: 'number' },
  { key: 'session_count', label: t('ground.run_sessions', '运行会话'), valueType: 'number' },
  { key: 'syslog_record_count', label: t('ground.syslog_records', 'Syslog'), valueType: 'number' },
  { key: 'complete_session_count', label: t('ground.complete_sessions', '完整会话'), valueType: 'number' },
  { key: 'partial_session_count', label: t('ground.partial_sessions', '部分会话'), valueType: 'number' },
  { key: 'archive_size_bytes', label: t('ground.archive_size', '归档大小'), valueType: 'number', displayValue: (row) => bytes(row.archive_size_bytes) },
  { key: 'integrity_status', label: t('ground.integrity', '完整性'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.integrity_status) },
  { key: 'archive_status', label: t('ground.archive_status', '归档状态'), valueType: 'status', displayValue: (row) => groundStatusLabel(row.archive_status) },
  { key: 'retention_until', label: t('ground.retention_until', '保留截止'), valueType: 'datetime' },
  { key: 'actions', label: t('ground.actions', '操作'), valueType: 'actions', fixed: 'right', width: 230, hideable: false },
]

const syslogColumns: NcTableColumn<GroundSyslogRecord>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 48, fixed: 'left', hideable: false },
  { key: 'receive_time', label: '接收时间', valueType: 'datetime', fixed: 'left', width: 180, sortable: 'custom' },
  { key: 'device_time', label: '设备时间', valueType: 'datetime', width: 180 },
  { key: 'train_no', label: '列车', valueType: 'name', displayValue: (row) => row.train_no || '未识别' },
  { key: 'mr_name', label: 'MR 设备', valueType: 'text', displayValue: (row) => row.mr_name || '未知 MR' },
  { key: 'source_ip', label: '来源 IP', valueType: 'ip' },
  { key: 'system_name', visible: false, label: '设备系统名', valueType: 'text' },
  { key: 'facility', visible: false, label: 'Facility', valueType: 'text' },
  { key: 'severity', visible: false, label: '级别', valueType: 'status', displayValue: (row) => groundSeverityLabel(row.severity) },
  { key: 'event_family', visible: false, label: '事件族', valueType: 'status' },
  { key: 'event_type', label: '事件', valueType: 'status', displayValue: (row) => groundEventLabel(row.event_type) },
  { key: 'peer_name', label: '当前 AP', valueType: 'name', displayValue: (row) => row.peer_name || row.peer_mac || '—' },
  { key: 'previous_peer_name', label: '原 AP', valueType: 'name', displayValue: (row) => row.previous_peer_name || row.previous_peer_mac || '—' },
  { key: 'rssi', label: 'RSSI', valueType: 'number', displayValue: (row) => row.rssi == null ? '—' : String(row.rssi) },
  { key: 'reason_text', label: '原因', valueType: 'description', minWidth: 180 },
  { key: 'interface_name', visible: false, label: '射频接口', valueType: 'text' },
  { key: 'physical_state', label: '接口状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.physical_state) },
  { key: 'cfg_event_index', visible: false, label: 'CFG EventIndex', valueType: 'text' },
  { key: 'cfg_command_source', visible: false, label: '命令来源', valueType: 'status', displayValue: (row) => groundControlSourceLabel(row.cfg_command_source) },
  { key: 'correlation_confidence', visible: false, label: '关联置信度', valueType: 'status', displayValue: (row) => groundStatusLabel(row.correlation_confidence) },
  { key: 'correlation_delta_ms', visible: false, label: '关联时间差', valueType: 'number', displayValue: (row) => metric(row.correlation_delta_ms, 'ms') },
  { key: 'composite_event_type', label: '综合事件', valueType: 'status', displayValue: (row) => row.composite_event_type ? groundEventLabel(row.composite_event_type) : '—' },
  { key: 'data_source', label: '数据来源', valueType: 'status', displayValue: (row) => groundSourceLabel(row.data_source) },
  { key: 'identity_status', label: '身份状态', valueType: 'status', displayValue: (row) => groundStatusLabel(row.identity_status) },
  { key: 'resolution_status', label: 'AP 解析', valueType: 'status', visible: false, displayValue: (row) => groundStatusLabel(row.resolution_status) },
  { key: 'clock_offset_ms', label: '时间差', valueType: 'number', visible: false, displayValue: (row) => metric(row.clock_offset_ms, 'ms') },
  { key: 'raw_file_status', label: '文件状态', valueType: 'status', visible: false, displayValue: (row) => groundStatusLabel(row.raw_file_status) },
  { key: 'raw_text', visible: false, label: '原始内容', valueType: 'description', minWidth: 420 },
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

const loadStatus = (silent = true) => {
  lastPollAt.set('status', Date.now())
  return latestRequest('status', '运行状态', (signal) => getGroundStatus({ signal }), (value) => {
  status.value = value
  if (!selectedRunId.value) selectedRunId.value = value.active_run_id || value.latest_run_id
  }, silent)
}

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

const loadPingTargets = (silent = true) => latestRequest('ping', t('ground.heartbeat', '心跳检测'), (signal) => listGroundPingTargets(selectedRunId.value, { signal }), (value) => { pingTargets.value = value.items }, silent)

const loadDeep = (silent = true) => latestRequest('deep', '深度采集', (signal) => listGroundDeepCollections(selectedRunId.value, { signal }), (value) => { deepCollections.value = value.items }, silent)

const loadTimelineData = (silent = true) => latestRequest(
  'timeline',
  '时间轴',
  (signal) => listGroundTimeline(
    timelineFilter.trainId,
    timelineFilter.eventType,
    selectedRunId.value,
    { signal },
    timelinePage.value,
    timelinePageSize.value,
    timelineFilter.query,
    { mrId: timelineFilter.mrId, mrRole: timelineFilter.mrRole, startAt: timelineFilter.range[0], endAt: timelineFilter.range[1] },
  ),
  (value) => {
    timeline.value = value.items
    timelineTotal.value = value.total
  },
  silent,
)

const loadArchives = (silent = true) => latestRequest('archives', '历史归档', (signal) => listGroundArchives({ signal }), (value) => { archives.value = value.items }, silent)

const loadHealth = (silent = true) => latestRequest('health', '系统健康', (signal) => getGroundHealth({ signal }), (value) => { health.value = value }, silent)

const loadAcMesh = (silent = true) => latestRequest('ac-mesh', 'AC-Mesh-Link', async (signal) => {
  const [summary, links, mrs, snapshots, rawTail] = await Promise.all([
    getAcMeshLinkSummary({ signal }),
    listAcMeshLinks({ query: acMeshQuery.query, station: acMeshQuery.station, page: acMeshQuery.page, page_size: acMeshQuery.pageSize }, { signal }),
    listAcMeshMrs({ query: acMeshQuery.query, station: acMeshQuery.station, section: acMeshQuery.section, car_end: acMeshQuery.carEnd, data_status: acMeshQuery.dataStatus, match_status: acMeshQuery.matchStatus, multiple_peers: acMeshQuery.multiplePeers, abnormal_only: acMeshQuery.abnormalOnly, page: acMeshQuery.mrPage, page_size: acMeshQuery.pageSize }, { signal }),
    listAcMeshSnapshots(acMeshQuery.snapshotPage, acMeshQuery.pageSize, { signal }),
    getAcMeshRawTail(undefined, 100, { signal }),
  ])
  return { summary, links, mrs, snapshots, rawTail }
}, (value) => {
  acMeshSummary.value = value.summary
  acMeshLinks.value = value.links.items
  acMeshMrs.value = value.mrs.items
  acMeshSnapshots.value = value.snapshots.items
  acMeshRawTail.value = value.rawTail
  acMeshTotals.links = value.links.total
  acMeshTotals.mrs = value.mrs.total
  acMeshTotals.snapshots = value.snapshots.total
}, silent)

async function loadAcControllers(silent = true): Promise<void> {
  acControllersLoading.value = true
  const loaded = await latestRequest('ac-controllers', '无线控制器 AC', () => listVehicleMrControllers(), (controllers) => {
    acControllers.value = controllers
    if (!controllers.some((item) => item.controller_id === selectedAcControllerId.value)) {
      selectedAcControllerId.value = controllers.length === 1 ? controllers[0].controller_id : ''
    }
  }, silent)
  acControllersError.value = !loaded
  if (!loaded) { acControllers.value = []; selectedAcControllerId.value = '' }
  acControllersLoading.value = false
}

async function refreshAcMesh(): Promise<void> {
  if (!acControllers.value.length) { ElMessage.warning('未配置无线控制器 AC，无法刷新 Mesh-Link'); return }
  if (!selectedAcControllerId.value) { ElMessage.warning('请选择要刷新的无线控制器 AC'); return }
  if (!acRefreshReady.value) { ElMessage.warning('当前无线控制器 AC 未配置可用连接，无法刷新'); return }
  acMeshLoading.value = true
  try {
    await refreshAcMeshLinks({ controller_id: selectedAcControllerId.value })
    await loadAcMesh(false)
    ElMessage.success('AC-Mesh-Link 刷新任务已提交')
  } catch (reason) {
    ElMessage.error(errorText(reason, 'AC-Mesh-Link 刷新失败'))
  } finally {
    acMeshLoading.value = false
  }
}

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
  // HeartbeatPage owns the durable heartbeat projection and its refresh
  // cadence. Keep the stopped-state inventory read for the shared context,
  // but avoid duplicate train/Ping reads while active sampling is displayed.
  else if (activeTab.value === 'heartbeat') {
    if (!monitoringRunning.value) await loadTrains(silent)
  }
  else if (activeTab.value === 'quick-ping') await loadTrains(silent)
  else if (activeTab.value === 'deep') await loadDeep(silent)
  else if (activeTab.value === 'timeline') await loadTimelineData(silent)
  else if (activeTab.value === 'syslog') await loadSyslog(silent)
  else if (activeTab.value === 'health') await loadHealth(silent)
  else if (activeTab.value === 'archives') await loadArchives(silent)
  else if (activeTab.value === 'settings') await Promise.all([loadProfile(silent), loadTrains(silent)])
  else if (activeTab.value === 'ac-mesh-link') await Promise.all([loadAcMesh(silent), loadAcControllers(silent)])
}

async function loadAll(silent = false): Promise<void> {
  if (!silent) loading.value = true
  loadAllInFlight = true
  try {
    // Status drives the run selection and is relatively expensive. Complete
    // it before loading dependent data so first entry does not create a burst
    // of synchronous backend queries.
    await loadStatus(silent)
    await loadRuns(silent)
    if (!profile.value || activeTab.value === 'settings') await loadProfile(silent)
    if (!selectedRunId.value) {
      selectedRunId.value = status.value?.active_run_id || status.value?.latest_run_id || runs.value[0]?.run_id || ''
    }
    await loadOperation(silent)
    await loadActiveTab(silent)
  } finally {
    loadAllInFlight = false
    if (!silent) loading.value = false
  }
}

function pollDue(key: string, intervalMs: number, callback: () => Promise<unknown>): void {
  if (loadAllInFlight || pollInFlight || requestControllers.size > 0 || requestControllers.has(key)) return
  const now = Date.now()
  const failures = Math.min(requestFailureCounts.get(key) ?? 0, 5)
  const effectiveInterval = Math.min(intervalMs * (2 ** failures), 120_000)
  if (now - (lastPollAt.get(key) ?? 0) < effectiveInterval) return
  lastPollAt.set(key, now)
  pollInFlight = true
  void callback().finally(() => { pollInFlight = false })
}

function schedulePoll(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(() => {
    if (!document.hidden) {
      pollDue('status', monitoringRunning.value ? 5_000 : 20_000, () => loadStatus())
      if (operationActive.value || status.value?.active_operation_id) {
        pollDue('operation', 2_000, () => loadOperation())
      } else if (
        status.value?.latest_operation_id
        && !dismissedTerminalOperationIds.has(status.value.latest_operation_id)
        && latestTerminalOperation.value?.operation_id !== status.value.latest_operation_id
      ) {
        pollDue('operation', 2_000, () => loadOperation())
      }
      if (monitoringRunning.value) {
        if (activeTab.value === 'overview') {
          pollDue('health', 5_000, () => loadHealth())
          pollDue('syslog-transport', 5_000, () => loadSyslogTransport())
        } else if (activeTab.value === 'health') pollDue('health', 5_000, () => loadHealth())
        else if (activeTab.value === 'heartbeat') {
          pollDue('trains', 8_000, () => loadTrains())
          pollDue('ping', 8_000, () => loadPingTargets())
        } else if (activeTab.value === 'ac-mesh-link') pollDue('ac-mesh', 15_000, () => loadAcMesh())
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
    : t('ground.v2.stop_without_archive_note', '将停止新的调度、心跳检测和 UDP 接收，清空内存队列并关闭原始文件，保存汇总但不执行归档。')
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
    t('ground.v2.heartbeat_packets', '心跳检测逐包数据'),
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
    BACKEND_CONNECTION_INTERRUPTED: t('ground.v2.heartbeat_connection_interrupted', '心跳检测查询连接中断，Backend 仍在线，请重试。'),
    CONNECTION_RESET: t('ground.v2.heartbeat_connection_interrupted', '心跳检测查询连接中断，Backend 仍在线，请重试。'),
    BACKEND_RESTARTED: t('ground.v2.heartbeat_backend_restarted', '心跳检测查询期间 Backend 发生重启，当前已恢复在线，请重试。'),
    RAW_QUERY_TIMEOUT: t('ground.v2.heartbeat_query_timeout', '心跳检测查询超时，请缩小时间范围后重试。'),
    PING_TARGET_NOT_FOUND: '未找到该目标的逐包 Ping 记录。',
    PING_IDENTITY_MISMATCH: '汇总目标与稳定查询身份不一致，请刷新汇总列表后重试。',
    PING_TARGET_IDENTITY_CONFLICT: '同一运行内该目标 IP 对应多个列车或 MR 端位，已拒绝任意选取。',
    RAW_FILE_MISSING: '原始文件已有登记，但物理文件缺失。',
    RAW_ARCHIVE_CORRUPT: 'READY 归档损坏，已停止读取。',
    SUMMARY_ONLY: '本次运行仅保留汇总，无法生成逐包曲线。',
  }
  const message = messages[transport.code]
    || (transport.backendState === 'ONLINE'
      ? errorText(reason, t('ground.v2.heartbeat_query_failed_online', '心跳检测查询失败，Backend 仍在线。'))
      : errorText(reason, t('ground.v2.heartbeat_query_failed', '心跳检测查询失败。')))
  return {
    key,
    label: t('ground.v2.heartbeat_packets', '心跳检测逐包数据'),
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
    t('ground.v2.heartbeat_live_delta', '心跳检测实时增量'),
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
      sort_order: syslogSortOrder.value,
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
    syslogStatistics.value = result.statistics ?? {}
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
  activeTab.value = 'heartbeat'
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

async function removeSelectedArchives(rows: GroundArchive[] = selectedArchives.value): Promise<void> {
  const ids = [...new Set(rows.map((row) => row.archive_id).filter(Boolean))]
  if (!ids.length) { ElMessage.warning('请先选择需要删除的历史归档'); return }
  await ElMessageBox.confirm(`确认批量删除 ${ids.length} 个历史归档？正在使用的当日数据会逐条拒绝。`, '批量删除历史归档', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  try {
    const result = await deleteGroundArchives(ids)
    selectedArchives.value = []
    ElMessage[result.failed_count ? 'warning' : 'success'](`已提交 ${result.accepted_count} 个，失败 ${result.failed_count} 个`)
    await loadAll(true)
  } catch (reason) { ElMessage.error(errorText(reason, '批量归档删除失败')) }
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
      t('ground.v2.delete_run_history_note', '确认删除 {run} 的运行历史？该操作会移除心跳检测、时间轴、Syslog 等查询索引；正式归档 ZIP 仍在“历史归档”中管理。').replace('{run}', row.run_date || row.run_id),
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
  requestPromises.clear()
  requestSequences.forEach((sequence, key) => requestSequences.set(key, sequence + 1))
  requestFailureCounts.clear()
  requestNotifySequences.clear()
  pollInFlight = false
}

function handleVisibilityChange(): void {
  pageVisible.value = !document.hidden
  if (document.hidden) abortRequests()
  else {
    siteContextReloadPending = false
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

function resetPageStateForSiteContext(): void {
  quickContextRevision.value += 1
  abortRequests()
  lastPollAt.clear()
  dismissedTerminalOperationIds.clear()
  if (completedOperationTimer !== undefined) window.clearTimeout(completedOperationTimer)
  completedOperationTimer = undefined
  status.value = null
  profile.value = null
  pingPresets.value = []
  trains.value = []
  pingTargets.value = []
  deepCollections.value = []
  selectedDeepCollector.value = null
  deepRecords.value = []
  deepCursor.value = ''
  timeline.value = []
  timelineTotal.value = 0
  archives.value = []
  health.value = null
  acMeshSummary.value = null
  acMeshLinks.value = []
  acMeshMrs.value = []
  acMeshSnapshots.value = []
  acMeshRawTail.value = null
  acControllers.value = []
  selectedAcControllerId.value = ''
  Object.assign(acMeshQuery, { query: '', station: '', section: '', carEnd: '', dataStatus: '', matchStatus: '', multiplePeers: false, abnormalOnly: false, page: 1, pageSize: 50, mrPage: 1, snapshotPage: 1 })
  Object.assign(acMeshTotals, { links: 0, mrs: 0, snapshots: 0 })
  Object.assign(timelineFilter, { query: '', eventType: '', trainId: '', mrId: '', mrRole: '', range: [] })
  activeOperation.value = null
  latestTerminalOperation.value = null
  runs.value = []
  selectedRunId.value = ''
  pingSeries.value = null
  selectedPingTarget.value = null
  pingWindowOpen.value = false
  pingInitialLoadSucceeded.value = false
  pingBackendState.value = 'UNKNOWN'
  pingRequestId.value = ''
  pingErrorCode.value = ''
  pingLastAttemptAt.value = ''
  pingCursor.value = ''
  pingSeenSamples.clear()
  syslogRecords.value = []
  syslogTotal.value = 0
  syslogDiagnostics.value = null
  syslogStatistics.value = {}
  syslogBackendState.value = 'UNKNOWN'
  syslogRequestId.value = ''
  syslogFailureCount.value = 0
  syslogErrorCode.value = ''
  selectedSyslogRecord.value = null
  selectedSyslogRecords.value = []
  syslogTransport.value = null
  localIpv4Addresses.value = []
  sourceRecommendation.value = null
  udpPortCheck.value = null
  selectedArchive.value = null
  selectedTrain.value = null
  deepWindowOpen.value = false
  deepPaused.value = false
  pingPaused.value = false
  syslogDetailDrawer.value = false
  syslogDeletePreview.value = null
  loadIssues.value = []
}

function handleSiteContextChanged(): void {
  if (disposed) return
  siteContextReloadPending = true
  resetPageStateForSiteContext()
  if (!document.hidden) {
    siteContextReloadPending = false
    void loadAll(true)
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

async function loadPingPresets(): Promise<void> {
  try {
    pingPresets.value = (await getOnlineMrControlPresets()).ping
  } catch {
    pingPresets.value = []
  }
}

function applyDeepPingPreset(key: string): void {
  if (!profile.value) return
  const preset = pingPresets.value.find((item) => item.key === key)
  if (!preset) {
    profile.value.deep_fping.preset_key = ''
    profile.value.deep_fping.preset_name = '自定义'
    return
  }
  Object.assign(profile.value.deep_fping, {
    enabled: true,
    target: '',
    preset_key: preset.key,
    preset_name: preset.name,
    packet_size: preset.packet_size_bytes,
    interval_ms: preset.interval_ms,
    timeout_ms: preset.timeout_ms,
    loss_warn_percent: preset.loss_warn_percent,
    latency_warn_ms: preset.latency_warn_ms,
  })
}

function markDeepPingCustom(): void {
  if (!profile.value) return
  profile.value.deep_fping.preset_key = ''
  profile.value.deep_fping.preset_name = '自定义'
}

function restoreDeepPingDefault(): void {
  const preset = pingPresets.value.find((item) => item.key === 'pis_high_ping_acceptance') || pingPresets.value[0]
  if (preset) applyDeepPingPreset(preset.key)
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener(SITE_CONTEXT_CHANGED_EVENT, handleSiteContextChanged)
  window.addEventListener(LEGACY_SITE_CONTEXT_CHANGED_EVENT, handleSiteContextChanged)
  void loadAll()
  void loadLocalAddresses()
  void loadPingPresets()
  schedulePoll()
})

onActivated(() => {
  pageActivated.value = true
  if (disposed || document.hidden || !siteContextReloadPending) return
  siteContextReloadPending = false
  lastPollAt.clear()
  void loadAll(true)
})

watch(activeTab, () => {
  requestControllers.forEach((controller, key) => {
    if (
      // These reads populate the shared run context, not an individual tab.
      // Cancelling first-entry history here leaves the date selector empty.
      !['status', 'operation', 'runs', 'profile'].includes(key)
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
  pageActivated.value = false
  pingWindowOpen.value = false
  handlePingWindowClosed()
})

onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener(SITE_CONTEXT_CHANGED_EVENT, handleSiteContextChanged)
  window.removeEventListener(LEGACY_SITE_CONTEXT_CHANGED_EVENT, handleSiteContextChanged)
  abortRequests()
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  if (completedOperationTimer !== undefined) window.clearTimeout(completedOperationTimer)
})
return {
computed,
onActivated,
onBeforeUnmount,
onDeactivated,
onMounted,
reactive,
ref,
watch,
useRouter,
ElMessage,
ElMessageBox,
Box,
CopyDocument,
Delete,
Download,
FolderOpened,
Refresh,
SwitchButton,
VideoPause,
VideoPlay,
deleteGroundArchive,
deleteGroundRunHistory,
getGroundArchiveDetail,
getGroundProfile,
getGroundStatus,
getGroundTrain,
groundArchiveSummaryDownloadRequest,
groundArchiveZipDownloadRequest,
listGroundArchives,
getGroundHealth,
listGroundDeepCollectionRecords,
listGroundDeepCollections,
listGroundPingTargets,
listGroundTimeline,
listGroundTrains,
requestGroundConfigCheck,
openGroundArchiveDirectory,
pauseGroundRun,
resumeGroundRun,
saveGroundProfile,
setGroundTrainPriority,
startGroundRun,
stopAndArchiveGroundRun,
stopGroundRun,
saveGroundTrainPolicy,
syncGroundInventory,
checkGroundUdpPort,
listLocalIpv4Addresses,
recommendLocalSourceIp,
getActiveGroundOperation,
getGroundOperation,
getGroundPingSeries,
getGroundPingSeriesIncremental,
getGroundSyslogTransportStatus,
listGroundRuns,
listGroundSyslogRecords,
previewGroundSyslogDelete,
probeGroundRawQueryTransportState,
probeGroundSyslogTransportState,
submitGroundSyslogDelete,
verifyGroundArchive,
apiErrorDetail,
getOnlineMrSession,
getOnlineMrControlPresets,
listVehicleMrControllers,
getAcMeshLinkSummary,
getAcMeshRawTail,
listAcMeshLinks,
listAcMeshMrs,
listAcMeshSnapshots,
refreshAcMeshLinks,
GroundPingChart,
NcDataTable,
NcMultiValueFilter,
NcFloatingWindow,
NcLogWorkspace,
useAdaptiveTableHeight,
t,
downloadBackendResource,
useWorkspaceStore,
LEGACY_SITE_CONTEXT_CHANGED_EVENT,
SITE_CONTEXT_CHANGED_EVENT,
groundDisplayNameSourceLabel,
groundEventLabel,
groundOperationStageLabel,
groundRunModeLabel,
groundSeverityLabel,
groundStopTriggerLabel,
groundSourceLabel,
groundStatusLabel,
groundTransitionContextLabel,
activeTab,
pageVisible,
pageActivated,
quickContextRevision,
router,
workspace,
loading,
saving,
action,
status,
profile,
pingPresets,
trains,
pingTargets,
deepCollections,
selectedDeepCollector,
deepRecords,
deepWindowOpen,
deepRecordsLoading,
deepCursor,
deepCategory,
deepKeyword,
deepPaused,
deepAutoRefresh,
timeline,
archives,
selectedArchives,
health,
acMeshSummary,
acMeshLinks,
acMeshMrs,
acMeshSnapshots,
acMeshRawTail,
acMeshLoading,
acMeshQuery,
acMeshTotals,
acControllers,
selectedAcControllerId,
acControllersLoading,
acControllersError,
selectedAcController,
acRefreshReady,
activeOperation,
latestTerminalOperation,
runs,
selectedRunId,
runHistoryDeleteLoading,
pingSeries,
selectedPingTarget,
pingWindowOpen,
pingSeriesLoading,
pingIncrementalLoading,
includeWarmup,
pingRange,
pingCustomRange,
pingAutoRefresh,
pingPaused,
pingFollowLatest,
pingCursor,
pingInitialLoadSucceeded,
pingBackendState,
pingRequestId,
pingErrorCode,
pingLastAttemptAt,
pingSeenSamples,
syslogRecords,
syslogTotal,
syslogLoading,
syslogAutoRefresh,
syslogDiagnostics,
syslogStatistics,
syslogSortOrder,
syslogTotalExact,
syslogBackendState,
syslogRequestId,
syslogLastAttemptAt,
syslogFailureCount,
syslogErrorCode,
selectedSyslogRecord,
selectedSyslogRecords,
syslogDetailDrawer,
syslogAdvancedFiltersOpen,
syslogDeleteDerived,
syslogDeleteLoading,
syslogDeletePreview,
syslogTimeRange,
syslogFilter,
localIpv4Addresses,
sourceRecommendation,
udpPortCheck,
syslogTransport,
syslogTransportLoading,
networkLoading,
showAllAddresses,
selectedArchive,
archiveDetailTab,
selectedTrain,
archiveDialog,
trainDialog,
openingSessionId,
trainFilter,
pingFilter,
timelineFilter,
timelinePage,
timelinePageSize,
timelineTotal,
pollTimer,
disposed,
siteContextReloadPending,
requestControllers,
requestFingerprints,
requestPromises,
requestSequences,
requestFailureCounts,
requestNotifySequences,
lastPollAt,
dismissedTerminalOperationIds,
completedOperationTimer,
loadIssues,
generalLoadIssues,
syslogIssue,
pingIssue,
loadIssueDescription,
profileLoadError,
running,
monitoringRunning,
operationActive,
visibleOperation,
selectedRun,
historicalRun,
runHistoryDeleteBlocked,
selectedPingHistorical,
syslogDeleteBlocked,
hasSyslogFilterValue,
syslogAdvancedFilterCount,
syslogHasActiveFilters,
runScopedTab,
archiveRecordCount,
filteredTrains,
filteredPing,
selectedTrainCollection,
filteredTimeline,
trainTableHost,
pingTableHost,
deepTableHost,
archiveTableHost,
trainTableHeight,
pingTableHeight,
deepTableHeight,
archiveTableHeight,
trainTableMaxHeight,
pingTableMaxHeight,
deepTableMaxHeight,
archiveTableMaxHeight,
visibleIpv4Addresses,
localIpv4Values,
returnAddressIsLocal,
listenAddressIsLocal,
startBlockedReason,
pingAvailability,
pingEmptyDescription,
pingLiveStats,
locationStats,
trainColumns,
pingColumns,
deepColumns,
timelineColumns,
archiveColumns,
syslogColumns,
latestRequest,
removeSelectedArchives,
loadStatus,
loadProfile,
loadRuns,
loadTrains,
loadPingTargets,
loadDeep,
loadTimelineData,
loadArchives,
loadHealth,
loadAcMesh,
loadAcControllers,
refreshAcMesh,
loadSyslogTransport,
loadOperation,
applyOperation,
dismissOperation,
loadActiveTab,
loadAll,
pollDue,
schedulePoll,
saveProfile,
loadLocalAddresses,
recommendSourceAddress,
applyRecommendedAddress,
checkUdpPort,
refreshSyslogAddresses,
copyReturnTarget,
runAction,
submitStop,
showPingSeries,
pingSampleIdentity,
mergeRecordList,
mergePingSeries,
mapPingLoadIssue,
loadPingIncremental,
currentSyslogDeleteFilters,
loadSyslog,
mapSyslogLoadIssue,
openBackendLogs,
openPingBackendLogs,
showSyslogRecord,
syslogRowKey,
handleSyslogSelection,
deleteSyslog,
isDialogCancellation,
togglePriority,
syncInventory,
updatePolicy,
checkConfigs,
confirmTargetPortChange,
showTrain,
showTrainPing,
showTrainTimeline,
openDeepSession,
showArchive,
removeArchive,
deleteSelectedRunHistory,
downloadArchiveSummary,
downloadArchiveZip,
verifyArchive,
openArchiveDirectory,
endpoint,
groundControlSourceLabel,
endpointRadioTooltip,
pingTimeRange,
duration,
metric,
bytes,
errorText,
isActionResponse,
statusType,
abortRequests,
handleVisibilityChange,
resetPageStateForSiteContext,
handleSiteContextChanged,
useFullPingRange,
togglePingPaused,
returnPingToLive,
copyPingDiagnostics,
handlePingWindowClosed,
handlePingDialogClosed,
showDeepCollector,
loadDeepRecords,
toggleDeepPaused,
handleDeepWindowClosed,
copyDeepRecords,
loadPingPresets,
applyDeepPingPreset,
markDeepPingCustom,
restoreDeepPingDefault
}
}

type GroundContext = ReturnType<typeof createGroundContext>
const groundContextKey: InjectionKey<GroundContext> = Symbol('ground-unattended')
export function provideGroundContext() {
  const context = createGroundContext()
  provide(groundContextKey, context)
  return context
}
export function useGroundContext() {
  const context = inject(groundContextKey)
  if (!context) throw new Error('Ground page requires its workspace context')
  return context
}
