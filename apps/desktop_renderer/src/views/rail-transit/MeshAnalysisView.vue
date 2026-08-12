<script setup lang="ts">
import {
  computed,
  markRaw,
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  reactive,
  ref,
  shallowRef,
  watch,
} from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowRight, Delete, Document, Download, FolderOpened, FullScreen, Hide, Lock, Refresh, Unlock, View, WarningFilled } from '@element-plus/icons-vue'
import { t } from '../../i18n/runtime'

import MeshChannelBusyChart from '../../components/mesh-analysis/MeshChannelBusyChart.vue'
import MeshRssiChart from '../../components/mesh-analysis/MeshRssiChart.vue'
import MeshTracksideSignalChart from '../../components/mesh-analysis/MeshTracksideSignalChart.vue'
import RailRssiComparison from '../../components/rail-timeline/RailRssiComparison.vue'
import { useRailTimelineController } from '../../components/rail-timeline/railTimeline'
import {
  DEFAULT_MESH_RSSI_LAYOUT_MODE,
  DEFAULT_MESH_RSSI_SPLIT_RATIO,
  normalizeMeshRssiLayoutMode,
  normalizeMeshRssiSplitRatio,
  type MeshRssiLayoutMode,
} from '../../components/mesh-analysis/meshRssiLayout'
import {
  acceptMeshSharedViewport,
  createFullMeshViewportFromDomain,
  isFullRssiViewport,
  meshTimestampMillis,
  meshViewportRangeEquals,
  normalizeMeshViewport,
  resolveMeshSharedTimeDomain,
  visibleMeshSamples,
  type MeshChartHandle,
  type MeshChartViewport,
  type MeshSharedPointerChange,
  type MeshSharedTimeDomain,
} from '../../components/mesh-analysis/meshChartViewport'
import { buildMeshTimeGroupClasses } from '../../components/mesh-analysis/timeGrouping'
import {
  buildTracksideSeriesCache,
  disposeTracksideSeriesCache,
  type TracksideSeriesCache,
} from '../../components/mesh-analysis/tracksideSeriesCache'
import NcDataTable from '../../components/table/NcDataTable.vue'
import { useConfirm } from '../../components/feedback/useConfirm'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { useAvailablePanelHeight } from '../../composables/useAvailablePanelHeight'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { ApiRequestError } from '../../api/client'
import {
  applyMeshBundleImport, batchDeleteMeshSources, createMeshProfile, deleteMeshArtifact, exportMeshLinkDetails, getMeshActivePathChart, getMeshAnalysisOverview, getMeshAnalysisParams, getMeshAnalysisParamsTemplate, getMeshAnalysisSession, getMeshImportContext, getMeshPeerSegmentChart, getMeshRawTail, getMeshTracksideSignalChart, listMeshParseIssues,
  listMeshActiveBuildOrder,
  listMeshArtifacts, listMeshLinks, listMeshSwitchEvents, meshArtifactDownloadRequest, previewMeshImport, rebuildMeshAnalysis,
  prepareMeshImportContext, saveMeshAnalysisParams, startMeshLocalScan, startMeshMaintenance, getMeshLocalScan, importMeshLocalScan, ignoreMeshLocalScanCandidates, openMeshLocalScanCandidateDirectory,
  auditMeshApCoverage, exportMeshApCoverage,
} from '../../api/meshAnalysis'
import { exportMeshAnalysisReport, getRailTransitTask, recoverRailTransitTasks } from '../../api/railTransitWeb'
import type { MeshAnalysisParamsOverride } from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import type {
  MeshActiveBuildOrder, MeshAnalysisParams, MeshAnalysisSession, MeshAnalysisSummary, MeshArtifact, MeshBundleImportRequest, MeshBundleMapping, MeshBundlePreview, MeshLocalScanCandidate, MeshLocalScanResult,
  MeshChartEvent, MeshLinkDetail, MeshPathChart, MeshProfile, MeshRawSource, MeshRawTail, MeshSessionDetail, MeshSwitchEvent,
  MeshTracksideSignalChartData, MeshApCoverageAudit, MeshParseIssue, MeshParseIssueSummary,
} from '../../types/meshAnalysis'
import type { VehicleMr } from '../../types/railTransitBaseData'
import type { RailTransitTask } from '../../types/railTransitWeb'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import { loadUiPreference, saveUiPreference } from '../../platform/uiPreferences'
import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import { requestWorkspaceTabTitle } from '../../workspace/runtime'
import { BEFORE_SITE_SWITCH_EVENT } from '../../workspace/site-switch'
import { normalizeMeshSessionIdentifier } from '../../validation/opaqueIdentifier'
import {
  meshAnalysisRuntimeSnapshot,
  registerMeshAnalysisInstance,
  releaseTracksideReservation,
  reserveTracksideCache,
  setMeshDetailRequestActive,
  setTracksideCacheActive,
  setTracksideChartActive,
  setTracksideConflictEdgeCount,
  unregisterMeshAnalysisInstance,
} from './meshAnalysisRuntime'
import type {
  RendererWorkloadPhase,
} from '../../../../desktop_electron/src/shared/bridge'

defineOptions({
  name: 'MeshAnalysisView',
})

const router = useRouter()
const { confirm } = useConfirm()
const userSelectedExport = useUserSelectedExport()
const taskStore = useTaskStore()
const meshRuntimeToken = registerMeshAnalysisInstance()
const taskPollingConsumer = 'mesh-analysis-view'
const pageActive = ref(true)
const pageActivatedOnce = ref(false)
const analysisResultUpdatePending = ref(false)
const analysisResultRefreshError = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const openingSessionId = ref<string | null>(null)
const pendingRequestedSessionId = ref<string | null>(null)
const detailSectionError = ref('')
const error = ref('')
const summary = ref<MeshAnalysisSummary | null>(null)
const sessions = ref<MeshAnalysisSession[]>([])
const total = ref(0)
const selected = ref<MeshSessionDetail | null>(null)
const selectedDeleteSessions = ref<MeshAnalysisSession[]>([])
const apCoverageVisible = ref(false)
const apCoverageLoading = ref(false)
const apCoverage = ref<MeshApCoverageAudit | null>(null)
const sourceDeleteVisible = ref(false)
const sourceDeleteMode = ref<'parsed' | 'all'>('parsed')
const sourceDeleteSubmitting = ref(false)
const sourceDeleteTargets = ref<Array<{ session: MeshAnalysisSession; source: MeshRawSource }>>([])
const parseIssuesVisible = ref(false)
const parseIssuesLoading = ref(false)
const parseIssues = ref<MeshParseIssue[]>([])
const parseIssuesTotal = ref(0)
const parseIssuesPage = ref(1)
const parseIssuesPageSize = 100
const buildOrders = ref<MeshActiveBuildOrder[]>([])
const buildOrderVisits = ref<MeshActiveBuildOrder[]>([])
const buildOrderTotal = ref(0)
const links = ref<MeshLinkDetail[]>([])
const linkTotal = ref(0)
const switches = ref<MeshSwitchEvent[]>([])
const switchTotal = ref(0)
const switchLoading = ref(false)
const rssiActivePath = shallowRef<MeshPathChart | null>(null)
const rssiActiveLoading = ref(false)
const rssiActiveLoaded = ref(false)
const rssiActivePeerLoaded = ref(false)
const rssiActiveError = ref('')
const rssiActivePaintReady = ref(false)
const tracksideSignal = shallowRef<MeshTracksideSignalChartData | null>(null)
const tracksideSeriesCache = shallowRef<TracksideSeriesCache | null>(null)
const tracksideLoading = ref(false)
const tracksideLoaded = ref(false)
const tracksideChartRendered = ref(false)
const tracksideError = ref('')
const tracksideRecoveryBlocked = ref(false)
const tracksideRecoveryReason = ref('')
const busyActivePath = ref<MeshPathChart | null>(null)
const busyPeerPath = ref<MeshPathChart | null>(null)
const artifacts = ref<MeshArtifact[]>([])
const rawTail = ref<MeshRawTail | null>(null)
const profiles = ref<MeshProfile[]>([])
const baseMrs = ref<VehicleMr[]>([])
const importVisible = ref(false)
const reportVisible = ref(false)
const linkExportVisible = ref(false)
const useTemporaryReportParams = ref(false)
const reportParams = reactive<MeshAnalysisParamsOverride>({
  link_time_window: 4000,
  link_switch_threshold: 10,
  link_hold_rssi: 22,
  link_establish_threshold: 4,
  main_link_switch_time_ms: 4000,
  short_link_tolerance_ms: 500,
  pingpong_tolerance_ms: 500,
  pingpong_return_window_ms: 500,
  merge_same_physical_ap_dual_radio: true,
  include_log_boundary_segments: false,
  sample_interval_ms: null,
  service_type: 'PIS',
  wifi_type: 'WiFi6',
})
const linkExportParams = reactive<MeshAnalysisParams>({ ...reportParams })
const importContextLoading = ref(false)
const importContextError = ref('')
const importContextWarnings = ref<string[]>([])
const importPreviewError = ref('')
const localScanVisible = ref(false)
const localScanLoading = ref(false)
const localScanImporting = ref(false)
const localScanError = ref('')
const localScanId = ref('')
const localScanResult = ref<MeshLocalScanResult | null>(null)
const localScanSelected = ref<string[]>([])
const localScanMappings = reactive<Record<string, string>>({})
const profileLoadError = ref('')
const vehicleMrLoadError = ref('')
const selectedFiles = ref<File[]>([])
const newProfileName = ref('')
const linkedMrId = ref('')
const lastAutoFilledProfileName = ref('')
const profileNotes = ref('')
const task = ref<RailTransitTask | null>(null)
const taskLoading = ref(false)
const buildOrderTableHost = ref<HTMLElement | null>(null)
const linkTableHost = ref<HTMLElement | null>(null)
const switchTableHost = ref<HTMLElement | null>(null)
const rssiWorkspaceHost = ref<HTMLElement | null>(null)
const tracksideChartHost = ref<HTMLElement | null>(null)
const busyChartHost = ref<HTMLElement | null>(null)
const rssiChartRef = ref<MeshChartHandle | null>(null)
const tracksideChartRef = ref<MeshChartHandle | null>(null)
const busyChartRef = ref<MeshChartHandle | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const activeTab = ref('build-order')
const busyMode = ref<'active' | 'peer'>('active')
const showRssiPeer = ref(false)
const showSwitchLines = ref(false)
const showSwitchPoints = ref(true)
const showLocationBand = ref(true)
const meshPreferenceReady = ref(false)
const rssiLayoutMode = ref<MeshRssiLayoutMode>(DEFAULT_MESH_RSSI_LAYOUT_MODE)
const rssiCompareSplitRatio = ref(DEFAULT_MESH_RSSI_SPLIT_RATIO)
const rssiImmersive = ref(false)
const rssiCompactSessionExpanded = ref(false)
const showBusyPeer = ref(false)
const showBusySwitchLines = ref(false)
const showBusySwitchPoints = ref(false)
const visiblePoints = ref(2000)
const rssiResolutionMode = ref<'full' | 'high' | 'overview'>('full')
const chartRadio = ref<number | null>(null)
const selectedSegment = ref<MeshActiveBuildOrder | null>(null)
const allPeerVisits = ref(false)
const selectedChartEvent = ref<MeshChartEvent | null>(null)
const focusTimestamp = ref('')
const rssiFocusLabel = ref('')
// preview 跟随本地缩放；committed 只在双图窗口结果成组发布后更新。
const railTimeline = useRailTimelineController()
const rssiViewport = railTimeline.viewport
const committedRssiViewport = ref<MeshChartViewport | null>(null)
const pendingRssiQueryViewport = ref<MeshChartViewport | null>(null)
const rssiViewportInteracting = ref(false)
const rssiWindowLoading = ref(false)
const sharedPointerTime = railTimeline.cursorTime
const sharedPointerSource = railTimeline.cursorSource
const selectedAnalysisTime = railTimeline.selectedTime
const tracksideChartVisible = ref(typeof IntersectionObserver === 'undefined')
const busyViewport = ref<MeshChartViewport | null>(null)
interface MeshChartWindowRange extends MeshChartViewport {
  radio: number | null
  mode?: 'active' | 'peer'
  anchor_link_id?: number | null
  all_visits?: boolean
}

interface MeshLockedAnalysisRange extends MeshChartWindowRange {
  session_id: string
  source_file_id: number
  mode: 'active' | 'peer'
  anchor_link_id: number | null
  all_visits: boolean
  first_sample_time: string | null
  last_sample_time: string | null
  sample_count: number
  created_at: string
}

interface RssiWindowRequest {
  key: string
  sessionId: string
  radio: number | null
  startTime: string
  endTime: string
  generation: number
  viewport: MeshChartViewport
}
const lockedAnalysisRange = ref<MeshLockedAnalysisRange | null>(null)
const sessionExpandedKey = 'netconsole.mesh-analysis.session-expanded'
const sessionExpanded = ref(true)
const loadedTabs = reactive<Record<string, boolean>>({})
const bundlePreview = ref<MeshBundlePreview | null>(null)
const bundleMappings = reactive<Record<string, Omit<MeshBundleMapping, 'role'> & { role: '' | 'CT' | 'CW'; confirmed: boolean }>>({})
const batchLinkedMrId = ref('')
const batchMappingConfirmed = ref(false)
const bundlePreviewLoading = ref(false)
const importPreviewStage = ref('')
const filters = reactive({ query: '', mr_role: '', has_warning: '' as '' | 'true' | 'false', page: 1, page_size: 50 })
const warningPopoverWidth = computed(() => (
  typeof window === 'undefined'
    ? 420
    : Math.min(420, Math.max(240, window.innerWidth - 32))
))
const maintenanceWarnings = computed(() => (selected.value?.warnings || []).filter((warning) => warning.code !== 'parse_issues'))
const parseIssueSummary = computed<MeshParseIssueSummary>(() => selected.value?.parse_issue_summary ?? {
  available: true,
  total_count: 0,
  info_count: 0,
  warning_count: 0,
  error_count: 0,
  message: '',
  groups: [],
})
const buildOrderFilters = reactive({ page: 1, page_size: 100, sort_order: 'desc', radio: '', peer: '', station: '', build_result: '', pingpong_only: false })
const linkFilters = reactive({ query: '', link_role: '', page: 1, page_size: 100, sort_order: 'asc' })
const switchFilters = reactive({ page: 1, page_size: 100, radio: '', result: '' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let failureCount = 0
let overviewGeneration = 0
let overviewAbortController: AbortController | null = null
let catalogRefreshTimer: ReturnType<typeof setTimeout> | null = null
let catalogRefreshGeneration = 0
let taskTimer: ReturnType<typeof setTimeout> | null = null
let detailGeneration = 0
let activeSessionOpenController: AbortController | null = null
let activeSessionOpenId: string | null = null
let activeSessionOpenPromise: Promise<void> | null = null
let activeSessionIntentId: string | null = null
let activeSessionIntentPromise: Promise<boolean> | null = null
let rssiChartGeneration = 0
let busyChartGeneration = 0
let rssiViewportRevision = 0
let tracksideObserver: IntersectionObserver | null = null
let tracksideAbortController: AbortController | null = null
let rssiActiveAbortController: AbortController | null = null
let rssiActiveRequestKey = ''
let rssiActiveLoadedKey = ''
let rssiActiveRequestPromise: Promise<void> | null = null
let tracksideRequestKey = ''
let tracksideLoadedKey = ''
let tracksideRequestPromise: Promise<void> | null = null
let rssiWindowReloadTimer: number | null = null
let rssiWindowBatchGeneration = 0
let rssiWindowBatchKey = ''
let rssiWindowBatchPromise: Promise<void> | null = null
let rssiWindowActiveAbortController: AbortController | null = null
let rssiWindowTracksideAbortController: AbortController | null = null
interface RssiWindowCacheEntry {
  active: MeshPathChart
  trackside: MeshTracksideSignalChartData
  seriesCache: TracksideSeriesCache
  viewport: MeshChartViewport
  activeLoadedKey: string
  tracksideLoadedKey: string
  estimatedBytes: number
}
const rssiWindowCache = new Map<string, RssiWindowCacheEntry>()
const RSSI_WINDOW_CACHE_MAX_ENTRIES = 2
const RSSI_WINDOW_CACHE_MAX_BYTES = 16 * 1024 * 1024
let publishedRssiWindowKey = ''
let cancelActivePaintWait: (() => void) | null = null
let cancelTracksideIdleSchedule: (() => void) | null = null
let tracksideRequestGeneration = 0
let tracksideWorkloadCycle = 0
let rendererWorkloadRevision = 0
let rssiLayoutBeforeFocus: MeshRssiLayoutMode = DEFAULT_MESH_RSSI_LAYOUT_MODE
let rssiSplitPreferenceTimer: ReturnType<typeof setTimeout> | null = null
let savedAppMainScrollTop = 0
let scrollRestoreFrame: number | null = null
let pendingCompletedTaskId: string | null = null
let pendingAffectedSessionId: string | null = null
let rendererRecoveryRestored = false
let rendererRecoveryPromise: Promise<void> | null = null
let importContextPromise: Promise<void> | null = null
let importProfilesReadyPromise: Promise<void> | null = null
let importContextGeneration = 0
let profileLoadGeneration = 0
let importPreviewGeneration = 0
let importPreviewController: AbortController | null = null
let profileNameManuallyEdited = false
const reportedWorkloadPhases = new Set<string>()
const processedTerminalTaskIds = new Set<string>()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const restorableTaskStates = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'FAILED'])
const taskStorageKey = 'netconsole.mesh-analysis.last-task'
const localScanStorageKey = 'netconsole.mesh-analysis.last-scan'
const meshCatalogRefreshIntervalMs = 500
const meshCatalogRefreshTimeoutMs = 30_000
const rssiPointerCommitDelayMs = 200
const rssiIdleCommitDelayMs = 450
const buildOrderPanel = useAvailablePanelHeight(buildOrderTableHost, { minHeight: 420, bottomGap: 72 })
const linkPanel = useAvailablePanelHeight(linkTableHost, { minHeight: 420, bottomGap: 72 })
const switchPanel = useAvailablePanelHeight(switchTableHost, { minHeight: 260, bottomGap: 72 })
const rssiPanel = useAvailablePanelHeight(rssiWorkspaceHost, { minHeight: 320, bottomGap: 16 })
const busyPanel = useAvailablePanelHeight(busyChartHost, { minHeight: 360, bottomGap: 48 })

const cards = computed(() => summary.value ? [
  ['分析会话', summary.value.session_count], ['列车 / MR', `${summary.value.train_count} / ${summary.value.mr_count}`],
  ['链路记录', display(summary.value.link_record_count)], ['主 / 备链路', `${display(summary.value.active_link_count)} / ${display(summary.value.standby_link_count)}`],
  ['切换事件', display(summary.value.switch_event_count)], ['短时建链', display(summary.value.short_link_count)],
  ['乒乓切换', display(summary.value.pingpong_count)], ['未匹配 AP', display(summary.value.unmatched_ap_count)],
] : [])
const taskCard = computed<TaskItem | null>(() => {
  const taskId = task.value?.task_id
  return taskId ? taskStore.tasks.find((item) => item.id === taskId) || null : null
})
const taskActive = computed(() => Boolean(taskCard.value && !terminalStates.has(taskCard.value.status)))
const taskProgress = computed(() => taskCard.value?.progress ?? 0)
const taskProgressKnown = computed(() => typeof taskCard.value?.progress === 'number' && Number.isFinite(taskCard.value.progress))
const taskSummary = computed(() => {
  if (!taskCard.value) return ''
  if (taskCard.value.error_summary) return taskCard.value.error_summary
  if (taskCard.value.message) return taskCard.value.message
  const count = Object.keys(taskCard.value.details || {}).length
  return count ? `已生成 ${count} 项结构化结果，完整内容请在任务中心查看。` : '完整日志、结果与 Artifact 请在任务中心查看。'
})
const selectedSource = computed(() => selected.value?.sources[0] || null)
const identityMappingStale = computed(() => (
  selected.value?.session.parsed_status === 'ready'
  && selectedSource.value?.identity_mapping_status === 'identity_stale'
))
const parsedMaintenanceOutdated = computed(() => {
  const state = selected.value?.maintenance_state
  return Boolean(state && (
    state.schema_status === 'outdated'
    || state.parser_status === 'outdated'
    || state.derived_analysis_status === 'outdated'
  ) && state.allowed_actions.includes('parser_rebuild'))
})
const identityRefreshActive = computed(() => Boolean(
  task.value
  && !terminalStates.has(task.value.status)
  && ['mesh_analysis_maintenance', 'mesh_identity_projection_refresh'].includes(task.value.action),
))
const switchTableHeight = computed(() => Math.min(
  switchPanel.height.value,
  Math.max(180, 54 + switches.value.length * 42),
))
const canOpenSelectedSourceLocation = computed(() => (
  getPlatformAdapter().hostType === 'electron'
  && Boolean(selected.value && selectedSource.value)
  && isFeatureEnabled('capability.mesh.source_open_location')
))
const bundleCanApply = computed(() => Boolean(
  bundlePreview.value
  && bundlePreview.value.items.length > 0
  && bundlePreview.value.items.every((item) => Boolean(bundleMappings[item.member_id]))
  && bundlePreview.value.items.some((item) => previewImportState(item)?.duplicate_status === 'new')
  && batchMappingConfirmed.value
  && bundlePreview.value.items.every((item) => bundleItemReady(item)),
))
const bundleSubmitLabel = computed(() => (
  bundlePreview.value?.items.length
  && bundlePreview.value.items.every(
    (item) => previewImportState(item)?.duplicate_status === 'duplicate_same_mr',
  )
    ? '全部已导入'
    : '确认导入并分析'
))
const bundleValidationMessage = computed(() => {
  if (!bundlePreview.value) return 'ZIP 尚未预览。'
  const blocked = bundlePreview.value.items.filter((item) => {
    const status = previewImportState(item)?.duplicate_status
    return status === 'duplicate_other_mr' || !batchDuplicateMappingMatches(item)
  })
  if (blocked.length) return `有 ${blocked.length} 个文件内容已归属其他 MR 或批次内映射冲突，请检查 MR 映射。`
  const unresolved = bundlePreview.value.items.filter((item) => !bundleItemReady(item))
  if (unresolved.length) return `还有 ${unresolved.length} 个文件未完成列车号、端位或对应车载 MR。`
  if (!batchMappingConfirmed.value) return '请核对批量映射结果并完成一次确认。'
  const newCount = bundlePreview.value.items.filter((item) => previewImportState(item)?.duplicate_status === 'new').length
  return newCount ? `可导入 ${newCount} 个新日志；重复内容将自动跳过且不占用序号。` : '所选日志均已导入，本次不会重复保存或分析。'
})
const localScanCandidates = computed(() => localScanResult.value?.candidates || [])
const localScanImportable = computed(() => localScanCandidates.value.filter((item) => (
  ['unregistered', 'needs_metadata', 'failed', 'parse_failed', 'repair_failed'].includes(item.scan_status)
)))
const localScanCanImport = computed(() => Boolean(
  localScanSelected.value.length
  && localScanSelected.value.every((candidateId) => Boolean(localScanMappings[candidateId])),
))
const linkTimeGroups = computed(() => buildMeshTimeGroupClasses(links.value, (row) => `${row.timestamp}::${row.timestamp_tag || ''}`))
const switchTimeGroups = computed(() => buildMeshTimeGroupClasses(switches.value, (row) => row.timestamp))
const chartData = computed(() => rssiActivePath.value)
const sharedRssiTimeDomain = computed<MeshSharedTimeDomain | null>(() => resolveMeshSharedTimeDomain(
  selected.value?.session.first_sample_time,
  selected.value?.session.last_sample_time,
  [
    chartData.value?.summary.earliest_sample_time,
    chartData.value?.summary.first_sample_time,
    chartData.value?.summary.latest_sample_time,
    chartData.value?.summary.last_sample_time,
    chartData.value?.rssi_line?.points[0]?.[0],
    chartData.value?.rssi_line?.points[(chartData.value?.rssi_line?.points.length || 0) - 1]?.[0],
    tracksideSignal.value?.time_range.start,
    tracksideSignal.value?.time_range.end,
  ].filter((value): value is string => Boolean(value)),
))
function formatChartCount(value: number | null | undefined): string {
  return Math.max(0, Number(value || 0)).toLocaleString('zh-CN')
}

function formatPayloadBytes(value: number | null | undefined): string {
  const bytes = Math.max(0, Number(value || 0))
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
}

function isWindowDetail(start: string | null | undefined, end: string | null | undefined): boolean {
  const domain = sharedRssiTimeDomain.value
  const startMillis = meshTimestampMillis(start)
  const endMillis = meshTimestampMillis(end)
  const fullStartMillis = meshTimestampMillis(domain?.full_start_time)
  const fullEndMillis = meshTimestampMillis(domain?.full_end_time)
  if (startMillis === null || endMillis === null || fullStartMillis === null || fullEndMillis === null) return false
  return startMillis > fullStartMillis || endMillis < fullEndMillis
}

function rssiViewModeForViewport(
  viewport: Pick<MeshChartViewport, 'start_time' | 'end_time' | 'full_start_time' | 'full_end_time'>,
): 'overview' | 'window' {
  return isFullRssiViewport(viewport) ? 'overview' : 'window'
}

function rssiViewModeForRange(range: MeshChartWindowRange | null): 'overview' | 'window' {
  return range ? rssiViewModeForViewport(range) : 'overview'
}

function chartLodLabel(
  lodLevel: number | null | undefined,
  start: string | null | undefined,
  end: string | null | undefined,
  viewMode: 'overview' | 'window' | null | undefined,
): string {
  const mode = viewMode === 'overview' || viewMode === 'window'
    ? viewMode
    : isWindowDetail(start, end) ? 'window' : 'overview'
  return `${mode === 'window' ? 'Window Detail' : 'Overview'} · LOD ${Math.max(0, Number(lodLevel || 0))}`
}

function chartWindowLabel(start: string | null | undefined, end: string | null | undefined): string {
  return start && end ? `${start} — ${end}` : '全量时间范围'
}

function degradedChartNotice(degraded: boolean | null | undefined): string {
  return degraded ? '数据量较大，已使用概览模式。缩放时间范围可查看更完整数据。' : ''
}

const activeChartWindow = computed(() => ({
  start: chartData.value?.requested_time_from || chartData.value?.effective_time_from || chartData.value?.time_from,
  end: chartData.value?.requested_time_to || chartData.value?.effective_time_to || chartData.value?.time_to,
}))
const tracksideChartWindow = computed(() => ({
  start: tracksideSignal.value?.time_range.start,
  end: tracksideSignal.value?.time_range.end,
}))
const rssiLoadStage = computed<{ step: string; label: string } | null>(() => {
  if (detailLoading.value && !selected.value) return { step: '1/4', label: '读取来源元数据' }
  if (rssiWindowLoading.value && rssiActiveLoading.value && tracksideLoading.value) {
    return { step: '2-3/4', label: '并行加载当前窗口的主链 RSSI 与轨旁 AP 数据' }
  }
  if (rssiActiveLoading.value || (rssiActiveLoaded.value && !rssiActivePaintReady.value && !rssiActiveError.value)) {
    return { step: '2/4', label: '加载主链 RSSI' }
  }
  if (tracksideLoading.value) return { step: '3/4', label: '加载轨旁 AP' }
  if (tracksideLoaded.value && tracksideChartVisible.value && !tracksideChartRendered.value) {
    return { step: '4/4', label: '绘制图表' }
  }
  return null
})
const busyChartData = computed(() => busyMode.value === 'peer' ? busyPeerPath.value : busyActivePath.value)
const busyValidSampleCount = computed(() => (busyChartData.value?.points || []).filter((point) => (
  point.local_tx_busy != null || point.local_rx_busy != null || point.peer_tx_busy != null || point.peer_rx_busy != null
)).length)
const lockedRangeLabel = computed(() => lockedAnalysisRange.value
  ? `${lockedAnalysisRange.value.start_time} — ${lockedAnalysisRange.value.end_time}`
  : '')
const isRssiWorkspaceMode = computed(() => activeTab.value === 'rssi')
const sessionDetailsExpanded = computed(() => (
  !selected.value || (isRssiWorkspaceMode.value ? rssiCompactSessionExpanded.value : sessionExpanded.value)
))
const activePaneAlertMessages = computed(() => [...new Set([
  rssiFocusLabel.value,
  rssiActiveError.value ? `主链 RSSI 数据加载失败：${rssiActiveError.value}` : '',
  lockedAnalysisRange.value
    ? `已锁定 ${lockedRangeLabel.value} · Radio ${lockedAnalysisRange.value.radio ?? '全部'} · RSSI 可见采样 ${lockedAnalysisRange.value.sample_count} 点`
    : '',
  chartData.value?.downsample_warning || '',
  degradedChartNotice(chartData.value?.response_budget?.degraded),
  ...(chartData.value?.response_budget?.degrade_reasons || []),
])].filter(Boolean))
const activePaneAlertSummary = computed(() => {
  if (rssiActiveError.value) return `主链 RSSI 数据加载失败：${rssiActiveError.value}`
  if (rssiWindowLoading.value) return '正在加载当前时间窗口…'
  if (rssiActiveLoading.value) return '正在加载主链 RSSI 数据…'
  return chartData.value?.downsample_warning || activePaneAlertMessages.value[0] || ''
})
const buildOrderOptions = computed(() => {
  const rows = buildOrderVisits.value.length ? buildOrderVisits.value : buildOrders.value
  const selectedRow = selectedSegment.value
  if (!selectedRow || rows.some((row) => row.anchor_link_id === selectedRow.anchor_link_id)) return rows
  return [selectedRow, ...rows]
})
const availableChartRadios = computed(() => [...new Set([
  ...(selected.value?.available_radios || []),
  ...buildOrderOptions.value.map((row) => row.local_radio).filter((value): value is number => value !== null),
])].sort((left, right) => left - right))
const selectedVisitValue = computed(() => allPeerVisits.value ? 'all-visits' : selectedSegment.value?.anchor_link_id)
const sessionColumns: NcTableColumn<MeshAnalysisSession>[] = [
  { key: 'selection', label: '', type: 'selection', width: 48, fixed: 'left', hideable: false },
  { key: 'analysis_time', label: '分析时间', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'train_name', label: '列车', minWidth: 100 },
  { key: 'mr_name', label: 'MR', valueType: 'name', minWidth: 145 },
  { key: 'mr_role', label: '角色', width: 70 },
  { key: 'source_type', label: '来源', width: 125 },
  { key: 'original_filename', label: '原始日志', align: 'left', alignmentReason: 'path', minWidth: 260, showOverflowTooltip: true },
  { key: 'link_record_count', label: '链路记录', valueType: 'number', width: 110 },
  { key: 'link_roles', label: '主 / 备', width: 125, displayValue: (row) => `${display(row.active_link_count)} / ${display(row.standby_link_count)}` },
  { key: 'event_count', label: '事件', valueType: 'number', width: 90 },
  { key: 'parsed_status', label: '解析状态', valueType: 'status', width: 105 },
  { key: 'data_integrity', label: '完整性', valueType: 'status', width: 95 },
  { key: 'warnings', label: '告警', valueType: 'status', width: 80 },
  { key: 'report_count', label: '报告', valueType: 'number', width: 75 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 145, fixed: 'right', hideable: false },
]
const coverageColumns: NcTableColumn<NonNullable<MeshApCoverageAudit['connected']>[number]>[] = [
  { key: 'ap_name', label: 'AP 名称', valueType: 'name', minWidth: 160 },
  { key: 'physical_ap_mac', label: '物理 AP MAC', valueType: 'mac', minWidth: 155 },
  { key: 'radio_mac', label: 'Peer Radio MAC', valueType: 'mac', minWidth: 155 },
  { key: 'station', label: '所属站点', minWidth: 130 },
  { key: 'section', label: '所属区间', minWidth: 160 },
  { key: 'fit_ap_status', label: 'FIT-AP 状态', width: 115 },
  { key: 'seen_in_source_a', label: '来源 A', width: 90, displayValue: (row) => row.seen_in_source_a ? '是' : '否' },
  { key: 'seen_in_source_b', label: '来源 B', width: 90, displayValue: (row) => row.seen_in_source_b ? '是' : '否' },
  { key: 'active_count', label: 'ACTIVE', valueType: 'number', width: 95 },
  { key: 'standby_count', label: 'STANDBY', valueType: 'number', width: 105 },
  { key: 'first_seen', label: '首次出现', valueType: 'datetime', minWidth: 190 },
  { key: 'last_seen', label: '最后出现', valueType: 'datetime', minWidth: 190 },
  { key: 'exclude_reason', label: '排除原因', minWidth: 145 },
  { key: 'description', label: '说明', minWidth: 200 },
]
const buildOrderColumns: NcTableColumn<MeshActiveBuildOrder>[] = [
  { key: 'sequence', label: '序号', valueType: 'number', width: 75, fixed: 'left', hideable: false },
  { key: 'local_radio', label: 'Radio', valueType: 'number', width: 80, fixed: 'left', hideable: false },
  { key: 'peer_mac_raw', label: '原始 Peer MAC', valueType: 'mac', minWidth: 150, fixed: 'left', hideable: false, displayValue: (row) => row.peer_mac_raw || row.active_peer_mac },
  { key: 'active_peer_mac', label: '规范 Peer MAC', valueType: 'mac', minWidth: 150, visible: false },
  { key: 'peer_ap_name', label: '解析 AP 名称', valueType: 'name', minWidth: 175, hideable: false, displayValue: (row) => row.peer_ap_name || '未关联' },
  { key: 'peer_ap_mac', label: '物理 AP MAC', valueType: 'mac', minWidth: 145 },
  { key: 'station', label: '归属站点', minWidth: 120 },
  { key: 'section', label: '归属区间', minWidth: 145 },
  { key: 'peer_radio', label: 'Peer Radio', minWidth: 105 },
  { key: 'peer_radio_mac', label: 'Peer Radio MAC', valueType: 'mac', minWidth: 145 },
  { key: 'identity_source', label: '身份来源', minWidth: 155 },
  { key: 'identity_rule', label: '匹配规则', minWidth: 175, visible: false },
  { key: 'build_start_time', label: '建链开始时间', valueType: 'datetime', minWidth: 215, sortable: 'custom', hideable: false },
  { key: 'build_end_time', label: '建链结束时间', valueType: 'datetime', minWidth: 215, hideable: false },
  { key: 'main_link_duration_seconds', label: '主链路持续(s)', valueType: 'duration', minWidth: 125, hideable: false },
  { key: 'reported_duration_seconds', label: '日志上报时长(s)', valueType: 'duration', minWidth: 135 },
  { key: 'sample_count', label: '采样点数', valueType: 'number', width: 100 },
  { key: 'avg_mr_rssi', label: 'MR 平均 RSSI', valueType: 'number', minWidth: 120 },
  { key: 'min_mr_rssi', label: '最小 RSSI', valueType: 'number', width: 105 },
  { key: 'max_mr_rssi', label: '最大 RSSI', valueType: 'number', width: 105 },
  { key: 'p10_mr_rssi', label: 'P10 RSSI', valueType: 'number', width: 100 },
  { key: 'avg_tx_busy', label: '平均 TxBusy', valueType: 'percentage', minWidth: 115 },
  { key: 'avg_rx_busy', label: '平均 RxBusy', valueType: 'percentage', minWidth: 115 },
  { key: 'link_establishment_accepted', label: '建链门限', valueType: 'status', minWidth: 105, displayValue: (row) => row.link_establishment_accepted ? '通过' : '未通过' },
  { key: 'link_establishment_reason', label: '建链门限原因', align: 'left', alignmentReason: 'long-text', minWidth: 320 },
  { key: 'build_result', label: '建链结果', valueType: 'status', minWidth: 125 },
  { key: 'judge_reason', label: '判定原因', align: 'left', alignmentReason: 'long-text', minWidth: 260 },
  { key: 'pingpong_type', label: '乒乓类型', minWidth: 120 },
  { key: 'source_file', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 240, showOverflowTooltip: true },
  { key: 'avg_peer_tx_busy', label: 'Peer 平均 TxBusy', valueType: 'percentage', minWidth: 135, visible: false },
  { key: 'avg_peer_rx_busy', label: 'Peer 平均 RxBusy', valueType: 'percentage', minWidth: 135, visible: false },
  { key: 'main_link_switch_time_ms', label: '切换稳定基准(ms)', valueType: 'duration', minWidth: 155, visible: false },
  { key: 'short_threshold_seconds', label: '短时阈值(s)', valueType: 'duration', minWidth: 110, visible: false },
  { key: 'is_same_physical_ap_radio_switch', label: '同 AP 双射频', width: 120, visible: false, displayValue: (row) => row.is_same_physical_ap_radio_switch ? '是' : '否' },
  { key: 'pingpong_group_id', label: '乒乓 Group', minWidth: 130, visible: false },
  { key: 'middle_ap_dwell_ms', label: '中间 AP 驻留(ms)', valueType: 'duration', minWidth: 145, visible: false },
  { key: 'pingpong_return_duration_ms', label: '返回时间(ms)', valueType: 'duration', minWidth: 120, visible: false },
  { key: 'previous_ap', label: 'previous AP', minWidth: 140, visible: false },
  { key: 'middle_ap', label: 'middle AP', minWidth: 140, visible: false },
  { key: 'return_ap', label: 'return AP', minWidth: 140, visible: false },
  { key: 'actions', label: '操作', valueType: 'actions', width: 105, fixed: 'right', hideable: false },
]
const linkColumns: NcTableColumn<MeshLinkDetail>[] = [
  { key: 'record_id', label: '序号', valueType: 'number', width: 75, fixed: 'left', hideable: false },
  { key: 'timestamp', label: '采样时间', valueType: 'datetime', width: 215, hideable: false },
  { key: 'timestamp_tag', label: '采样标识', width: 120 },
  { key: 'local_radio', label: 'Radio', valueType: 'number', width: 80, hideable: false },
  { key: 'link_role', label: '状态', width: 90, hideable: false },
  { key: 'peer_mac_raw', label: '原始 Peer MAC', valueType: 'mac', minWidth: 145, hideable: false, displayValue: (row) => row.peer_mac_raw || row.peer_mac },
  { key: 'peer_mac', label: '规范 Peer MAC', valueType: 'mac', minWidth: 145, visible: false },
  { key: 'peer_ap_name', label: '解析 AP 名称', valueType: 'name', minWidth: 175, displayValue: (row) => row.peer_ap_name || '未关联' },
  { key: 'local_rssi_db', label: 'MR 侧 RSSI 差值', valueType: 'number', minWidth: 130 },
  { key: 'peer_rssi_db', label: 'Peer 侧 RSSI 差值', valueType: 'number', minWidth: 140 },
  { key: 'peer_ap_mac', label: '物理 AP MAC', valueType: 'mac', minWidth: 145 },
  { key: 'station', label: '归属站点', width: 130 },
  { key: 'section', label: '归属区间', width: 190 },
  { key: 'peer_radio', label: 'PEER Radio', minWidth: 105 },
  { key: 'peer_radio_mac', label: 'Peer Radio MAC', valueType: 'mac', minWidth: 145 },
  { key: 'identity_source', label: '身份来源', minWidth: 155 },
  { key: 'identity_rule', label: '匹配规则', minWidth: 175, visible: false },
  { key: 'identity_reason', label: '身份说明', align: 'left', alignmentReason: 'long-text', minWidth: 260, visible: false },
  { key: 'establish_time', label: '建链时间', valueType: 'datetime', width: 210 },
  { key: 'duration_text', label: '链路时长', width: 140 },
  { key: 'link_count', label: 'LinkCnt', valueType: 'number', width: 90 },
  { key: 'local_noise_dbm', label: 'MR 侧底噪', valueType: 'number', minWidth: 105 },
  { key: 'peer_noise_dbm', label: 'Peer 侧底噪', valueType: 'number', minWidth: 115 },
  { key: 'local_signal_dbm', label: 'MR 接收信号', valueType: 'number', minWidth: 115 },
  { key: 'peer_signal_dbm', label: 'Peer 接收信号', valueType: 'number', minWidth: 125 },
  { key: 'local_rate_raw', label: 'MR 侧协商速率原始值', minWidth: 170 },
  { key: 'peer_rate_raw', label: 'Peer 侧协商速率原始值', minWidth: 180 },
  { key: 'local_tx_busy', label: 'L_TxBusy', valueType: 'percentage', width: 100 },
  { key: 'peer_tx_busy', label: 'P_TxBusy', valueType: 'percentage', width: 100 },
  { key: 'local_rx_busy', label: 'L_RxBusy', valueType: 'percentage', width: 100 },
  { key: 'peer_rx_busy', label: 'P_RxBusy', valueType: 'percentage', width: 100 },
  { key: 'mileage', label: '里程', valueType: 'mileage', width: 120 },
  { key: 'line_side', label: '方向', width: 95 },
  { key: 'source_file', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 240, showOverflowTooltip: true },
  { key: 'source_line_number', label: '行号', valueType: 'number', width: 90 },
  { key: 'local_cpu_percent', label: 'MR CPU', valueType: 'percentage', width: 100, visible: false },
  { key: 'peer_cpu_percent', label: 'Peer CPU', valueType: 'percentage', width: 100, visible: false },
  { key: 'local_mem_percent', label: 'MR 内存', valueType: 'percentage', width: 100, visible: false },
  { key: 'peer_mem_percent', label: 'Peer 内存', valueType: 'percentage', width: 105, visible: false },
  { key: 'local_tx_des_free_cnt', label: 'Local TxDesFreeCnt', valueType: 'number', minWidth: 145, visible: false },
  { key: 'peer_tx_des_free_cnt', label: 'Peer TxDesFreeCnt', valueType: 'number', minWidth: 145, visible: false },
  { key: 'local_tx', label: 'LocalTx', valueType: 'number', width: 95, visible: false },
  { key: 'peer_tx', label: 'PeerTx', valueType: 'number', width: 95, visible: false },
  { key: 'local_rx', label: 'LocalRx', valueType: 'number', width: 95, visible: false },
  { key: 'peer_rx', label: 'PeerRx', valueType: 'number', width: 95, visible: false },
  { key: 'local_retry', label: 'LocalRetry', valueType: 'number', minWidth: 105, visible: false },
  { key: 'peer_retry', label: 'PeerRetry', valueType: 'number', minWidth: 105, visible: false },
  { key: 'local_err', label: 'LocalErr', valueType: 'number', width: 100, visible: false },
  { key: 'peer_err', label: 'PeerErr', valueType: 'number', width: 100, visible: false },
  { key: 'local_tx_garp', label: 'Local Tx GARP', valueType: 'number', minWidth: 120, visible: false },
  { key: 'peer_rx_garp', label: 'Peer Rx GARP', valueType: 'number', minWidth: 120, visible: false },
  { key: 'local_tx_mul_join', label: 'Local Multicast Join', valueType: 'number', minWidth: 150, visible: false },
  { key: 'peer_rx_mul_join', label: 'Peer Multicast Join', valueType: 'number', minWidth: 150, visible: false },
  { key: 'match_method', label: '匹配方式', minWidth: 160, visible: false },
  { key: 'raw_line_start', label: '原始起始行', valueType: 'number', minWidth: 110, visible: false },
  { key: 'raw_line_end', label: '原始结束行', valueType: 'number', minWidth: 110, visible: false },
]
const switchColumns: NcTableColumn<MeshSwitchEvent>[] = [
  { key: 'timestamp', label: '切换时间', valueType: 'datetime', widthMode: 'content', minWidth: 215, hideable: false },
  { key: 'local_radio', label: 'Radio', valueType: 'number', width: 80, hideable: false },
  { key: 'from_ap_name', label: '原 AP', valueType: 'name', minWidth: 150 },
  { key: 'from_peer_mac', label: '原 AP MAC', valueType: 'mac', minWidth: 145 },
  { key: 'to_ap_name', label: '目标 AP', valueType: 'name', minWidth: 150 },
  { key: 'to_peer_mac', label: '目标 AP MAC', valueType: 'mac', minWidth: 145 },
  { key: 'rssi_change', label: 'RSSI 前 / 后', width: 135, displayValue: (row) => `${display(row.before_rssi)} / ${display(row.after_rssi)}` },
  { key: 'new_active_duration_ms', label: '新主链持续', valueType: 'duration', minWidth: 120 },
  { key: 'stability_threshold_ms', label: '基准时间', valueType: 'duration', minWidth: 110 },
  { key: 'switch_result', label: '切换判定', width: 125, displayValue: (row) => buildResultLabel(row.switch_result || (row.is_short_link ? 'short' : 'normal')) },
  { key: 'is_pingpong', label: '乒乓', width: 75, displayValue: (row) => row.is_pingpong ? '是' : '否' },
  { key: 'station', label: '归属站点', width: 130 },
  { key: 'section', label: '归属区间', width: 150 },
]
const artifactColumns: NcTableColumn<MeshArtifact>[] = [
  { key: 'artifact_type', label: '类型', width: 140 },
  { key: 'name', label: '文件名', align: 'left', alignmentReason: 'path', minWidth: 260 },
  { key: 'size_bytes', label: '大小', valueType: 'number', width: 110, displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '生成时间', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 140, hideable: false },
]
const sourceColumns: NcTableColumn<MeshRawSource>[] = [
  { key: 'name', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 260 },
  { key: 'source_type', label: '来源类型', width: 150 },
  { key: 'exists', label: '状态', valueType: 'status', width: 100, displayValue: (row) => row.exists ? '可用' : '缺失' },
  { key: 'size_bytes', label: '大小', valueType: 'number', width: 110, displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'tail', label: '日志片段', valueType: 'actions', width: 110, hideable: false },
]
const parseIssueColumns: NcTableColumn<MeshParseIssue>[] = [
  { key: 'severity', label: '级别', width: 90 },
  { key: 'code', label: '类型', width: 180 },
  { key: 'message', label: '说明', align: 'left', alignmentReason: 'long-text', minWidth: 360, showOverflowTooltip: true },
  { key: 'source_file', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 180, showOverflowTooltip: true },
  { key: 'line_number', label: '行号', valueType: 'number', width: 90 },
  { key: 'field_name', label: '字段', width: 140 },
]

async function restoreMeshPreferences(): Promise<void> {
  const [lines, points, band, busyLines, busyPoints, layoutMode, splitRatio] = await Promise.all([
    loadUiPreference('mesh-analysis-rssi.show-switch-lines', false),
    loadUiPreference('mesh-analysis-rssi.show-switch-points', true),
    loadUiPreference('mesh-analysis-rssi.show-location-band', true),
    loadUiPreference('mesh-analysis-airload.show-switch-lines', false),
    loadUiPreference('mesh-analysis-airload.show-switch-points', false),
    loadUiPreference('mesh-analysis-rssi.layout-mode', DEFAULT_MESH_RSSI_LAYOUT_MODE),
    loadUiPreference('mesh-analysis-rssi.compare-split-ratio', DEFAULT_MESH_RSSI_SPLIT_RATIO),
  ])
  showSwitchLines.value = typeof lines === 'boolean' ? lines : false
  showSwitchPoints.value = typeof points === 'boolean' ? points : true
  showLocationBand.value = typeof band === 'boolean' ? band : true
  showBusySwitchLines.value = typeof busyLines === 'boolean' ? busyLines : false
  showBusySwitchPoints.value = typeof busyPoints === 'boolean' ? busyPoints : false
  rssiLayoutMode.value = normalizeMeshRssiLayoutMode(layoutMode)
  rssiCompareSplitRatio.value = normalizeMeshRssiSplitRatio(splitRatio)
  meshPreferenceReady.value = true
}

watch([showSwitchLines, showSwitchPoints, showLocationBand, showBusySwitchLines, showBusySwitchPoints], ([lines, points, band, busyLines, busyPoints]) => {
  if (!meshPreferenceReady.value) return
  void Promise.all([
    saveUiPreference('mesh-analysis-rssi.show-switch-lines', lines),
    saveUiPreference('mesh-analysis-rssi.show-switch-points', points),
    saveUiPreference('mesh-analysis-rssi.show-location-band', band),
    saveUiPreference('mesh-analysis-airload.show-switch-lines', busyLines),
    saveUiPreference('mesh-analysis-airload.show-switch-points', busyPoints),
  ]).catch(() => ElMessage.warning('图表显示偏好保存失败，当前设置仅保留在本次运行。'))
})

watch(showRssiPeer, (enabled) => {
  if (!meshPreferenceReady.value || !selected.value || !enabled || rssiActivePeerLoaded.value) return
  void loadRssiPeerSeries()
}, { flush: 'sync' })

watch(showBusyPeer, () => {
  if (!meshPreferenceReady.value || !selected.value || activeTab.value !== 'busy') return
  void reloadCurrentChart()
}, { flush: 'sync' })

watch(rssiLayoutMode, (mode) => {
  if (meshPreferenceReady.value) {
    void saveUiPreference('mesh-analysis-rssi.layout-mode', mode)
      .catch(() => ElMessage.warning('RSSI 布局偏好保存失败，当前设置仅保留在本次运行。'))
  }
  if (mode !== 'active-focus') void nextTick(observeTracksideChart)
  resizeVisibleRssiCharts()
})

watch(rssiCompareSplitRatio, (ratio) => {
  if (!meshPreferenceReady.value) return
  if (rssiSplitPreferenceTimer) clearTimeout(rssiSplitPreferenceTimer)
  rssiSplitPreferenceTimer = setTimeout(() => {
    rssiSplitPreferenceTimer = null
    void saveUiPreference('mesh-analysis-rssi.compare-split-ratio', ratio)
      .catch(() => ElMessage.warning('RSSI 分隔比例保存失败，当前设置仅保留在本次运行。'))
  }, 180)
})

function setRssiLayoutMode(mode: MeshRssiLayoutMode): void {
  if (mode === rssiLayoutMode.value) return
  if (mode !== 'compare') rssiImmersive.value = false
  if (mode === 'compare') {
    rssiLayoutBeforeFocus = DEFAULT_MESH_RSSI_LAYOUT_MODE
  } else {
    rssiLayoutBeforeFocus = rssiLayoutMode.value
  }
  rssiLayoutMode.value = mode
}

function updateRssiSplitRatio(ratio: number): void {
  rssiCompareSplitRatio.value = normalizeMeshRssiSplitRatio(ratio)
}

function toggleRssiFocus(mode: Exclude<MeshRssiLayoutMode, 'compare'>): void {
  setRssiLayoutMode(rssiLayoutMode.value === mode ? 'compare' : mode)
}

function toggleRssiImmersive(): void {
  if (!rssiImmersive.value) setRssiLayoutMode('compare')
  rssiImmersive.value = !rssiImmersive.value
  void nextTick(() => {
    rssiPanel.refresh()
    resizeVisibleRssiCharts()
  })
}

function handleRssiLayoutKeydown(event: KeyboardEvent): void {
  if (!pageActive.value || event.defaultPrevented || event.key !== 'Escape' || activeTab.value !== 'rssi') return
  if (rssiImmersive.value) {
    rssiImmersive.value = false
    void nextTick(() => {
      rssiPanel.refresh()
      resizeVisibleRssiCharts()
    })
    return
  }
  if (rssiLayoutMode.value === 'compare') return
  const previous = normalizeMeshRssiLayoutMode(rssiLayoutBeforeFocus)
  rssiLayoutBeforeFocus = DEFAULT_MESH_RSSI_LAYOUT_MODE
  rssiLayoutMode.value = previous === rssiLayoutMode.value
    ? DEFAULT_MESH_RSSI_LAYOUT_MODE
    : previous
}

function resizeVisibleRssiCharts(): void {
  if (!pageActive.value) return
  void nextTick(() => {
    if (!pageActive.value || activeTab.value !== 'rssi') return
    const viewport = rssiViewport.value
    if (rssiLayoutMode.value !== 'trackside-focus') {
      rssiChartRef.value?.resize()
      if (viewport) rssiChartRef.value?.applyViewport(viewport)
    }
    if (
      rssiLayoutMode.value !== 'active-focus'
      && tracksideChartVisible.value
    ) {
      tracksideChartRef.value?.resize()
      if (viewport) tracksideChartRef.value?.applyViewport(viewport)
    }
  })
}

function meshChartRevisionKey(): string {
  const source = selectedSource.value
  if (!source) return 'no-source'
  return [
    source.source_file_id,
    source.raw_sha256,
    source.modified_at,
    source.identity_index_revision,
    source.identity_current_revision,
    source.identity_mapped_at,
  ].join(':')
}

function meshChartRequestKey(
  endpoint: 'active-path' | 'trackside-signal',
  sessionId: string,
  values: Record<string, string | number | boolean | null | undefined>,
): string {
  return JSON.stringify([
    endpoint,
    sessionId,
    meshChartRevisionKey(),
    values.radio ?? null,
    values.max_points ?? null,
    values.view_mode ?? null,
    values.time_from ?? null,
    values.time_to ?? null,
    values.include_peer ?? null,
    values.include_events ?? null,
    values.include_station_band ?? null,
    values.include_standby_context ?? null,
    values.include_standby ?? null,
  ])
}

function stopRssiWindowBatch(): void {
  const wasLoading = Boolean(
    rssiWindowBatchPromise
    || rssiWindowActiveAbortController
    || rssiWindowTracksideAbortController,
  )
  rssiWindowActiveAbortController?.abort()
  rssiWindowTracksideAbortController?.abort()
  rssiWindowActiveAbortController = null
  rssiWindowTracksideAbortController = null
  rssiWindowBatchPromise = null
  rssiWindowBatchKey = ''
  rssiWindowLoading.value = false
  if (wasLoading) {
    rssiActiveLoading.value = false
    tracksideLoading.value = false
  }
}

function invalidateRssiWindowBatch(): void {
  rssiWindowBatchGeneration += 1
  stopRssiWindowBatch()
}

function cancelDeferredRssiChartWork(): void {
  cancelActivePaintWait?.()
  cancelActivePaintWait = null
  cancelTracksideIdleSchedule?.()
  cancelTracksideIdleSchedule = null
  if (rssiWindowReloadTimer !== null) window.clearTimeout(rssiWindowReloadTimer)
  rssiWindowReloadTimer = null
}

function cancelInFlightRssiChartRequests(): void {
  invalidateRssiWindowBatch()
  rssiActiveAbortController?.abort()
  rssiActiveAbortController = null
  rssiActiveRequestPromise = null
  rssiActiveRequestKey = ''
  rssiActiveLoading.value = false
  tracksideAbortController?.abort()
  tracksideAbortController = null
  tracksideRequestPromise = null
  tracksideRequestKey = ''
  tracksideLoading.value = false
}

async function waitForActiveRssiFirstPaint(generation: number): Promise<boolean> {
  cancelActivePaintWait?.()
  await nextTick()
  if (
    generation !== detailGeneration
    || !pageActive.value
    || activeTab.value !== 'rssi'
    || !rssiActiveLoaded.value
    || rssiActiveError.value
  ) return false

  return new Promise<boolean>((resolve) => {
    let firstFrame: number | null = null
    let secondFrame: number | null = null
    let settled = false
    const finish = (painted: boolean) => {
      if (settled) return
      settled = true
      cancelActivePaintWait = null
      resolve(painted)
    }
    cancelActivePaintWait = () => {
      if (firstFrame !== null) cancelAnimationFrame(firstFrame)
      if (secondFrame !== null) cancelAnimationFrame(secondFrame)
      finish(false)
    }
    firstFrame = requestAnimationFrame(() => {
      firstFrame = null
      if (generation !== detailGeneration || !pageActive.value || activeTab.value !== 'rssi') {
        finish(false)
        return
      }
      secondFrame = requestAnimationFrame(() => {
        secondFrame = null
        finish(
          generation === detailGeneration
          && pageActive.value
          && activeTab.value === 'rssi'
          && rssiActiveLoaded.value
          && !rssiActiveError.value,
        )
      })
    })
  })
}

function scheduleTracksideAfterActivePaint(
  generation = detailGeneration,
  force = false,
): void {
  cancelTracksideIdleSchedule?.()
  cancelTracksideIdleSchedule = null
  if (
    generation !== detailGeneration
    || !pageActive.value
    || activeTab.value !== 'rssi'
    || !rssiActivePaintReady.value
    || !rssiActiveLoaded.value
    || Boolean(rssiActiveError.value)
    || !tracksideChartVisible.value
    || tracksideRecoveryBlocked.value
  ) return

  let active = true
  let idleHandle: number | null = null
  let timerHandle: number | null = null
  let frameHandle: number | null = null
  const run = () => {
    if (!active) return
    active = false
    cancelTracksideIdleSchedule = null
    if (
      generation === detailGeneration
      && pageActive.value
      && activeTab.value === 'rssi'
      && rssiActivePaintReady.value
      && !rssiActiveError.value
    ) void loadTracksideSignal(generation, force)
  }
  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number
    cancelIdleCallback?: (handle: number) => void
  }
  cancelTracksideIdleSchedule = () => {
    active = false
    if (idleHandle !== null) idleWindow.cancelIdleCallback?.(idleHandle)
    if (timerHandle !== null) window.clearTimeout(timerHandle)
    if (frameHandle !== null) cancelAnimationFrame(frameHandle)
  }
  if (idleWindow.requestIdleCallback) {
    idleHandle = idleWindow.requestIdleCallback(run, { timeout: 750 })
    return
  }
  timerHandle = window.setTimeout(() => {
    timerHandle = null
    frameHandle = requestAnimationFrame(run)
  }, 0)
}

function observeTracksideChart(): void {
  if (!pageActive.value || tracksideChartVisible.value || activeTab.value !== 'rssi') return
  if (typeof IntersectionObserver === 'undefined') {
    tracksideChartVisible.value = true
    return
  }
  const host = tracksideChartHost.value
  if (!host) return
  const rect = host.getBoundingClientRect()
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight
  if (
    (rect.width > 0 || rect.height > 0)
    && rect.top <= viewportHeight + 600
    && rect.bottom >= -600
  ) {
    tracksideChartVisible.value = true
    return
  }
  tracksideObserver?.disconnect()
  tracksideObserver = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return
    tracksideChartVisible.value = true
    tracksideObserver?.disconnect()
    tracksideObserver = null
  }, { rootMargin: '600px 0px' })
  tracksideObserver.observe(host)
}

function reportRendererWorkload(phase: RendererWorkloadPhase): void {
  const bridge = window.netconsoleDesktop
  if (!bridge) return
  const sessionId = selected.value?.session.session_id
  const sourceFileId = selectedSource.value?.source_file_id
  const phaseKey = `${sessionId ?? 'none'}:${sourceFileId ?? 'none'}:${chartRadio.value ?? 'none'}:${tracksideWorkloadCycle}:${phase}`
  if (reportedWorkloadPhases.has(phaseKey)) return
  reportedWorkloadPhases.add(phaseKey)
  const memory = (performance as Performance & {
    memory?: {
      usedJSHeapSize: number
      totalJSHeapSize: number
      jsHeapSizeLimit: number
    }
  }).memory
  const runtime = meshAnalysisRuntimeSnapshot()
  bridge.reportRendererWorkload?.({
    module: 'mesh-analysis',
    route: '/rail-transit/mesh-analysis',
    phase,
    ...(sessionId ? { sessionId } : {}),
    ...(sourceFileId == null ? {} : { sourceFileId }),
    radio: chartRadio.value,
    ...(tracksideSignal.value ? {
      totalFrames: tracksideSignal.value.total_frames,
      returnedFrames: tracksideSignal.value.returned_frames,
      totalLinkPoints: tracksideSignal.value.total_link_points,
      returnedLinkPoints: tracksideSignal.value.returned_link_points,
      seriesCount: tracksideSeriesCache.value?.series.length
        ?? tracksideSignal.value.returned_series,
    } : {}),
    pointCount: tracksideSeriesCache.value?.totalRenderedPoints ?? 0,
    metadataCount: tracksideSeriesCache.value?.pointMetaById.size ?? 0,
    conflictEdgeCount: runtime.conflictEdgeCount,
    echartsInstanceCount: document.querySelectorAll('[_echarts_instance_]').length,
    canvasCount: document.querySelectorAll('canvas').length,
    meshInstanceCount: runtime.meshInstanceCount,
    tracksideCacheCount: runtime.tracksideCacheCount,
    tracksideChartCount: runtime.tracksideChartCount,
    activeDetailRequests: runtime.activeDetailRequests,
    tracksideCacheBuildCount: runtime.tracksideCacheBuildCount,
    tracksideCacheDisposeCount: runtime.tracksideCacheDisposeCount,
    chartInitCount: runtime.chartInitCount,
    chartDisposeCount: runtime.chartDisposeCount,
    ...(rssiViewport.value?.start_time ? { viewportStart: rssiViewport.value.start_time } : {}),
    ...(rssiViewport.value?.end_time ? { viewportEnd: rssiViewport.value.end_time } : {}),
    ...(memory ? {
      heapUsedBytes: memory.usedJSHeapSize,
      heapTotalBytes: memory.totalJSHeapSize,
      heapLimitBytes: memory.jsHeapSizeLimit,
    } : {}),
    reportRevision: ++rendererWorkloadRevision,
  })
}

function releaseTracksideResources(reportDisposed = true): void {
  invalidateRssiWindowBatch()
  cancelTracksideIdleSchedule?.()
  cancelTracksideIdleSchedule = null
  tracksideAbortController?.abort()
  tracksideAbortController = null
  tracksideRequestKey = ''
  tracksideLoadedKey = ''
  tracksideRequestPromise = null
  tracksideRequestGeneration += 1
  const hadTracksideResources = Boolean(tracksideSeriesCache.value || tracksideSignal.value)
  disposeTracksideSeriesCache(tracksideSeriesCache.value)
  for (const entry of rssiWindowCache.values()) {
    disposeTracksideSeriesCache(entry.seriesCache)
  }
  rssiWindowCache.clear()
  publishedRssiWindowKey = ''
  tracksideSeriesCache.value = null
  tracksideSignal.value = null
  tracksideLoaded.value = false
  tracksideChartRendered.value = false
  tracksideError.value = ''
  setTracksideCacheActive(meshRuntimeToken, false)
  setTracksideChartActive(meshRuntimeToken, false)
  releaseTracksideReservation(meshRuntimeToken)
  if (reportDisposed && hadTracksideResources) reportRendererWorkload('chart-disposed')
}

function routeRequestedSessionId(): string | null {
  const currentRoute = router.currentRoute?.value
  if (currentRoute?.name && currentRoute.name !== 'mesh-analysis') return null
  return normalizeMeshSessionIdentifier(currentRoute?.query.session_id)
}

function isAbortError(reason: unknown): boolean {
  return (reason instanceof Error && reason.name === 'AbortError')
    || (reason instanceof ApiRequestError && reason.code === 'REQUEST_ABORTED')
}

function meshOverviewErrorMessage(reason: unknown): string {
  if (!(reason instanceof ApiRequestError)) {
    return reason instanceof Error ? reason.message : 'MESH 来源查询失败'
  }
  if (reason.code === 'REQUEST_TIMEOUT') {
    const timeoutMs = Number(reason.details.timeout_ms || 0)
    return timeoutMs > 0
      ? `MESH 来源查询超时（${timeoutMs} ms）。`
      : 'MESH 来源查询超时。'
  }
  if (reason.status > 0) {
    const diagnostics = [
      reason.code || 'HTTP_ERROR',
      reason.details.request_id ? `request_id：${String(reason.details.request_id)}` : '',
    ].filter(Boolean).join('；')
    return `MESH 来源查询失败，Backend 仍在线：${reason.message}${diagnostics ? `（${diagnostics}）` : ''}`
  }
  if (reason.code === 'BACKEND_RESTARTED') return 'Backend 正在恢复，请稍后重试。'
  return 'Backend 已停止或当前不可达，正在尝试恢复。'
}

async function restoreRendererRecovery(): Promise<void> {
  const recovery = await window.netconsoleDesktop?.getRendererRecoveryState?.()
  const recoverySessionId = normalizeMeshSessionIdentifier(recovery?.sessionId)
  if (!recovery || recovery.module !== 'mesh-analysis' || !recoverySessionId) return
  tracksideRecoveryReason.value = recovery.previousReason
  tracksideRecoveryBlocked.value = recovery.mode === 'safe'
  await requestMeshAnalysisSession(recoverySessionId, { preserveRecovery: true })
  chartRadio.value = recovery.radio ?? chartRadio.value
  if (recovery.mode === 'normal') {
    loadedTabs.rssi = true
    activeTab.value = 'rssi'
    await loadFullRssiCharts()
  }
}

async function restoreRendererRecoveryOnce(): Promise<void> {
  if (rendererRecoveryRestored) return
  if (routeRequestedSessionId()) {
    rendererRecoveryRestored = true
    return
  }
  if (!rendererRecoveryPromise) {
    rendererRecoveryPromise = restoreRendererRecovery()
      .then(() => { rendererRecoveryRestored = true })
      .finally(() => { rendererRecoveryPromise = null })
  }
  await rendererRecoveryPromise
}

const tracksideRecoveryMessage = computed(() => (
  tracksideRecoveryReason.value === 'oom'
    ? '上次轨旁图因渲染进程内存不足退出，已使用安全恢复模式。点击后才会重新加载轨旁图。'
    : '上次渲染轨旁图时页面异常退出，已使用安全恢复模式。点击后才会重新加载轨旁图。'
))
const tracksidePaneAlertMessages = computed(() => [...new Set([
  tracksideRecoveryBlocked.value ? tracksideRecoveryMessage.value : '',
  tracksideError.value ? `轨旁AP信号图加载失败：${tracksideError.value}` : '',
  degradedChartNotice(tracksideSignal.value?.response_budget?.degraded),
  ...(tracksideSignal.value?.response_budget?.degrade_reasons || []),
  ...(tracksideSignal.value?.warnings || []),
])].filter(Boolean))
const tracksidePaneAlertSummary = computed(() => {
  if (tracksideRecoveryBlocked.value) return tracksideRecoveryMessage.value
  if (tracksideError.value) return `轨旁AP信号图加载失败：${tracksideError.value}`
  if (rssiWindowLoading.value) return '正在加载当前时间窗口…'
  if (tracksideLoading.value) return '正在加载轨旁AP信号图…'
  if (!rssiActivePaintReady.value) return '等待主链 RSSI 图完成首帧绘制'
  if (!tracksideLoaded.value) return tracksideChartVisible.value ? '轨旁AP信号图尚未加载' : '轨旁AP信号图将在滚动到可见区域后加载'
  const data = tracksideSignal.value
  if (!data) return ''
  if (data.response_budget?.degraded && !data.warnings.length) {
    return `轨旁图已使用 ${chartLodLabel(data.response_budget?.lod_level, data.time_range.start, data.time_range.end, data.view_mode)}`
  }
  if (!data.warnings.length) return ''
  return `轨旁图已保留关键采样：${data.returned_frames}/${data.total_frames} 时刻，${data.returned_link_points}/${data.total_link_points} 链路点`
})

function stopOverviewRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
  stopCatalogRefresh()
}

function stopCatalogRefresh(): void {
  catalogRefreshGeneration += 1
  if (catalogRefreshTimer) clearTimeout(catalogRefreshTimer)
  catalogRefreshTimer = null
}

function catalogIndexNeedsRefresh(): boolean {
  return ['pending', 'discovering', 'enriching'].includes(summary.value?.index_status || '')
}

function scheduleCatalogRefresh(): void {
  stopCatalogRefresh()
  if (!pageActive.value || !catalogIndexNeedsRefresh()) return
  const generation = ++catalogRefreshGeneration
  const deadline = Date.now() + meshCatalogRefreshTimeoutMs
  const refresh = async (): Promise<void> => {
    catalogRefreshTimer = null
    if (generation !== catalogRefreshGeneration || !pageActive.value) return
    await refreshOverview(true, true)
    if (
      generation !== catalogRefreshGeneration
      || !pageActive.value
      || !catalogIndexNeedsRefresh()
      || Date.now() >= deadline
    ) return
    catalogRefreshTimer = setTimeout(() => { void refresh() }, meshCatalogRefreshIntervalMs)
  }
  catalogRefreshTimer = setTimeout(() => { void refresh() }, 0)
}

function scheduleCatalogRefreshIfIdle(): void {
  if (
    catalogIndexNeedsRefresh()
    && (!task.value || terminalStates.has(task.value.status))
  ) scheduleCatalogRefresh()
}

function cancelScrollRestore(): void {
  if (scrollRestoreFrame !== null) cancelAnimationFrame(scrollRestoreFrame)
  scrollRestoreFrame = null
}

function savePageScrollPosition(): void {
  savedAppMainScrollTop = document.querySelector<HTMLElement>('.app-main')?.scrollTop ?? 0
}

function restorePageScrollPosition(): void {
  cancelScrollRestore()
  scrollRestoreFrame = requestAnimationFrame(() => {
    scrollRestoreFrame = requestAnimationFrame(() => {
      scrollRestoreFrame = null
      if (!pageActive.value) return
      const appMain = document.querySelector<HTMLElement>('.app-main')
      if (appMain) appMain.scrollTop = savedAppMainScrollTop
    })
  })
}

function pauseMeshAnalysisPage(): void {
  savePageScrollPosition()
  pageActive.value = false
  rssiViewportInteracting.value = false
  pendingRssiQueryViewport.value = null
  overviewAbortController?.abort()
  overviewAbortController = null
  overviewGeneration += 1
  rssiActiveAbortController?.abort()
  rssiActiveAbortController = null
  cancelDeferredRssiChartWork()
  cancelInFlightRssiChartRequests()
  rssiActiveLoading.value = false
  if (activeSessionOpenId) {
    pendingRequestedSessionId.value = activeSessionOpenId
    activeSessionOpenController?.abort()
    activeSessionOpenController = null
    activeSessionOpenId = null
    activeSessionOpenPromise = null
    detailGeneration += 1
    detailLoading.value = false
    setMeshDetailRequestActive(meshRuntimeToken, false)
  }
  stopOverviewRefresh()
  stopTaskPolling()
  taskStore.releasePolling(taskPollingConsumer)
  tracksideObserver?.disconnect()
  tracksideObserver = null
  sharedPointerTime.value = null
  sharedPointerSource.value = null
  cancelScrollRestore()
}

async function resumeMeshAnalysisPage(): Promise<void> {
  pageActive.value = true
  taskStore.acquirePolling(taskPollingConsumer)
  await nextTick()
  const requestedSessionId = pendingRequestedSessionId.value || routeRequestedSessionId()
  if (requestedSessionId) await applyRequestedSession(requestedSessionId)
  if (task.value && !terminalStates.has(task.value.status)) {
    try {
      rememberTask(await getRailTransitTask(task.value.task_id))
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : 'MESH 任务状态读取失败'
    }
  }
  if (task.value && terminalStates.has(task.value.status)) await afterTask()
  await restoreRendererRecoveryOnce()
  if (!pageActive.value) return
  if (activeTab.value === 'rssi' && selected.value) {
    if (!rssiActiveLoaded.value || !rssiActivePaintReady.value) {
      await loadFullRssiCharts(detailGeneration)
    } else {
      observeTracksideChart()
      scheduleTracksideAfterActivePaint()
    }
  }
  refreshDetailPanels()
  resizeVisibleRssiCharts()
  observeTracksideChart()
  restorePageScrollPosition()
  scheduleRefresh()
  if (task.value && !terminalStates.has(task.value.status)) pollTask()
  void refreshOverview(true, true).then(scheduleCatalogRefreshIfIdle)
}

function disposeMeshAnalysisPage(): void {
  pageActive.value = false
  rssiViewportInteracting.value = false
  pendingRssiQueryViewport.value = null
  overviewAbortController?.abort()
  overviewAbortController = null
  overviewGeneration += 1
  activeSessionOpenController?.abort()
  activeSessionOpenController = null
  activeSessionOpenId = null
  activeSessionOpenPromise = null
  activeSessionIntentId = null
  activeSessionIntentPromise = null
  rssiActiveAbortController?.abort()
  rssiActiveAbortController = null
  cancelDeferredRssiChartWork()
  cancelInFlightRssiChartRequests()
  detailGeneration += 1
  window.removeEventListener('keydown', handleRssiLayoutKeydown)
  window.removeEventListener('pointerup', endRssiViewportInteraction, true)
  window.removeEventListener('pointercancel', endRssiViewportInteraction, true)
  window.removeEventListener(BEFORE_SITE_SWITCH_EVENT, disposeMeshAnalysisPage)
  stopOverviewRefresh()
  cancelScrollRestore()
  if (rssiSplitPreferenceTimer) {
    clearTimeout(rssiSplitPreferenceTimer)
    if (meshPreferenceReady.value) {
      void saveUiPreference(
        'mesh-analysis-rssi.compare-split-ratio',
        rssiCompareSplitRatio.value,
      ).catch(() => undefined)
    }
  }
  rssiSplitPreferenceTimer = null
  tracksideObserver?.disconnect()
  tracksideObserver = null
  releaseTracksideResources()
  setMeshDetailRequestActive(meshRuntimeToken, false)
  unregisterMeshAnalysisInstance(meshRuntimeToken)
  stopTaskPolling()
  taskStore.releasePolling(taskPollingConsumer)
}

onMounted(async () => {
  window.addEventListener('keydown', handleRssiLayoutKeydown)
  window.addEventListener('pointerup', endRssiViewportInteraction, true)
  window.addEventListener('pointercancel', endRssiViewportInteraction, true)
  window.addEventListener(BEFORE_SITE_SWITCH_EVENT, disposeMeshAnalysisPage)
  taskStore.acquirePolling(taskPollingConsumer)
  await Promise.all([restoreMeshPreferences(), restoreLocalScanResult(), refreshOverview(), recoverTask()])
  const requestedSessionId = routeRequestedSessionId()
  if (requestedSessionId) await applyRequestedSession(requestedSessionId)
  if (!pageActive.value) return
  await restoreRendererRecoveryOnce()
  if (pageActive.value) {
    scheduleRefresh()
    scheduleCatalogRefreshIfIdle()
  }
})
onActivated(() => {
  if (!pageActivatedOnce.value) {
    pageActivatedOnce.value = true
    return
  }
  void resumeMeshAnalysisPage()
})
onDeactivated(pauseMeshAnalysisPage)
onBeforeUnmount(disposeMeshAnalysisPage)
watch(activeTab, (tab) => {
  if (selected.value) void loadTab(tab)
  if (tab === 'rssi') {
    void nextTick(observeTracksideChart)
    scheduleTracksideAfterActivePaint()
    resizeVisibleRssiCharts()
  } else {
    cancelDeferredRssiChartWork()
    cancelInFlightRssiChartRequests()
    rssiImmersive.value = false
  }
  refreshDetailPanels()
})
watch(
  () => router.currentRoute?.value?.fullPath,
  () => {
    const requestedSessionId = routeRequestedSessionId()
    if (!requestedSessionId) return
    pendingRequestedSessionId.value = requestedSessionId
    if (pageActive.value) void applyRequestedSession(requestedSessionId)
  },
)
watch(tracksideChartVisible, (visible) => {
  if (!visible) return
  resizeVisibleRssiCharts()
  if (
    activeTab.value === 'rssi'
    && selected.value
    && !tracksideSignal.value
    && !tracksideLoading.value
    && !tracksideRecoveryBlocked.value
  ) scheduleTracksideAfterActivePaint()
})
watch(sessionExpanded, refreshDetailPanels)
watch([linkedMrId, baseMrs], applyLinkedMrProfileName)
watch(
  () => taskStore.tasks.map((item) => item.id),
  (visibleTaskIds) => {
    if (
      task.value
      && terminalStates.has(task.value.status)
      && !visibleTaskIds.includes(task.value.task_id)
    ) rememberTask(null)
  },
)

function scheduleRefresh(): void {
  stopOverviewRefresh()
  if (!pageActive.value) return
  refreshTimer = setTimeout(async () => {
    refreshTimer = null
    if (pageActive.value && document.visibilityState === 'visible') await refreshOverview(true)
    if (pageActive.value) scheduleRefresh()
  }, failureCount >= 3 ? 90_000 : 30_000)
}

async function refreshOverview(silent = false, force = false): Promise<void> {
  if (loading.value && !force) return
  const generation = ++overviewGeneration
  overviewAbortController?.abort()
  const controller = new AbortController()
  overviewAbortController = controller
  loading.value = !silent
  try {
    const overview = await getMeshAnalysisOverview({
      ...filters,
      has_warning: filters.has_warning === '' ? null : filters.has_warning === 'true',
    }, controller.signal)
    if (generation !== overviewGeneration || controller.signal.aborted || !pageActive.value) return
    summary.value = overview.summary
    sessions.value = overview.sessions.items
    total.value = overview.sessions.total
    error.value = ''
    failureCount = 0
  } catch (reason) {
    if (isAbortError(reason) || controller.signal.aborted || generation !== overviewGeneration) return
    error.value = meshOverviewErrorMessage(reason)
    failureCount += 1
  } finally {
    if (overviewAbortController === controller) overviewAbortController = null
    if (generation === overviewGeneration) loading.value = false
  }
}

interface SessionRequestOptions {
  force?: boolean
  navigate?: boolean
  preserveRecovery?: boolean
  preserveView?: boolean
}

async function openMeshAnalysisSession(row: MeshAnalysisSession): Promise<void> {
  const id = normalizeMeshSessionIdentifier(row.session_id)
  if (!id) {
    error.value = '分析会话标识无效'
    return
  }
  if (activeSessionIntentId === id && activeSessionIntentPromise) {
    await activeSessionIntentPromise
    return
  }
  openingSessionId.value = id
  const intentPromise = requestMeshAnalysisSession(id)
  activeSessionIntentId = id
  activeSessionIntentPromise = intentPromise
  try {
    await intentPromise
  } finally {
    if (activeSessionIntentPromise === intentPromise) {
      activeSessionIntentId = null
      activeSessionIntentPromise = null
    }
    if (openingSessionId.value === id) openingSessionId.value = null
  }
}

async function requestMeshAnalysisSession(
  id: string,
  options: SessionRequestOptions = {},
): Promise<boolean> {
  pendingRequestedSessionId.value = id
  const currentRoute = router.currentRoute?.value
  if (options.navigate !== false && currentRoute?.query.session_id !== id) {
    await router.replace({
      name: 'mesh-analysis',
      query: { ...(currentRoute?.query || {}), session_id: id },
    })
  }
  if (options.navigate !== false && routeRequestedSessionId() !== id) return false
  return applyRequestedSession(id, options)
}

async function applyRequestedSession(
  requestedSessionId: string | null,
  options: SessionRequestOptions = {},
): Promise<boolean> {
  const id = normalizeMeshSessionIdentifier(requestedSessionId)
  if (!id) return false
  const routedSessionId = routeRequestedSessionId()
  if (options.navigate !== false && routedSessionId && routedSessionId !== id) return false
  pendingRequestedSessionId.value = id
  if (!pageActive.value) return false
  if (!options.force && selected.value?.session.session_id === id) {
    if (pendingRequestedSessionId.value === id) pendingRequestedSessionId.value = null
    return true
  }
  if (!options.force && activeSessionOpenId === id && activeSessionOpenPromise) {
    await activeSessionOpenPromise
    return selected.value?.session.session_id === id && pendingRequestedSessionId.value !== id
  }

  activeSessionOpenController?.abort()
  const controller = new AbortController()
  const generation = ++detailGeneration
  activeSessionOpenController = controller
  activeSessionOpenId = id
  setMeshDetailRequestActive(meshRuntimeToken, true)
  const promise = openSessionById(id, {
    generation,
    signal: controller.signal,
    preserveRecovery: options.preserveRecovery === true,
    preserveView: options.preserveView === true,
  }).catch(async (reason: unknown) => {
    if (isAbortError(reason) || controller.signal.aborted || generation !== detailGeneration) return
    if (
      reason instanceof ApiRequestError
      && reason.status === 404
      && selected.value?.session.session_id === id
    ) {
      await closeSelectedMeshSession()
      error.value = '当前 MESH 分析来源已不存在，已关闭详情并刷新来源列表'
      return
    }
    error.value = reason instanceof Error ? reason.message : '分析详情加载失败'
    if (selected.value?.session.session_id !== id) {
      pendingRequestedSessionId.value = null
      const currentRoute = router.currentRoute?.value
      if (currentRoute?.query.session_id === id) {
        const query = { ...currentRoute.query }
        delete query.session_id
        await router.replace({ name: 'mesh-analysis', query })
      }
      requestWorkspaceTabTitle('MR 原始 MESH 日志分析')
    }
  }).finally(() => {
    if (generation !== detailGeneration) return
    activeSessionOpenController = null
    activeSessionOpenId = null
    activeSessionOpenPromise = null
    detailLoading.value = false
    setMeshDetailRequestActive(meshRuntimeToken, false)
  })
  activeSessionOpenPromise = promise
  await promise
  return Boolean(
    generation === detailGeneration
    && !controller.signal.aborted
    && selected.value?.session.session_id === id
    && pendingRequestedSessionId.value !== id
    && !detailSectionError.value,
  )
}

interface PreservedSessionView {
  activeTab: string
  chartRadio: number | null
  buildOrderPage: number
  linkPage: number
  switchPage: number
}

function rememberPublishedRssiWindow(): void {
  if (
    !publishedRssiWindowKey
    || !rssiActivePath.value
    || !tracksideSignal.value
    || !tracksideSeriesCache.value
    || !committedRssiViewport.value
  ) return
  const previous = rssiWindowCache.get(publishedRssiWindowKey)
  if (previous && previous.seriesCache !== tracksideSeriesCache.value) {
    disposeTracksideSeriesCache(previous.seriesCache)
  }
  rssiWindowCache.delete(publishedRssiWindowKey)
  rssiWindowCache.set(publishedRssiWindowKey, {
    active: rssiActivePath.value,
    trackside: tracksideSignal.value,
    seriesCache: tracksideSeriesCache.value,
    viewport: { ...committedRssiViewport.value },
    activeLoadedKey: rssiActiveLoadedKey,
    tracksideLoadedKey,
    estimatedBytes: Math.max(0, rssiActivePath.value.payload_bytes || 0)
      + Math.max(0, tracksideSignal.value.payload_bytes || 0),
  })
  let estimatedBytes = [...rssiWindowCache.values()]
    .reduce((totalBytes, entry) => totalBytes + entry.estimatedBytes, 0)
  while (
    rssiWindowCache.size > RSSI_WINDOW_CACHE_MAX_ENTRIES
    || estimatedBytes > RSSI_WINDOW_CACHE_MAX_BYTES
  ) {
    const oldest = rssiWindowCache.entries().next().value as
      | [string, RssiWindowCacheEntry]
      | undefined
    if (!oldest) break
    rssiWindowCache.delete(oldest[0])
    estimatedBytes -= oldest[1].estimatedBytes
    disposeTracksideSeriesCache(oldest[1].seriesCache)
  }
}

async function restoreRssiWindowFromCache(
  key: string,
  entry: RssiWindowCacheEntry,
): Promise<void> {
  rssiWindowCache.delete(key)
  rememberPublishedRssiWindow()
  rssiActivePath.value = entry.active
  tracksideSignal.value = entry.trackside
  tracksideSeriesCache.value = entry.seriesCache
  rssiViewport.value = { ...entry.viewport }
  committedRssiViewport.value = { ...entry.viewport }
  rssiActiveLoadedKey = entry.activeLoadedKey
  tracksideLoadedKey = entry.tracksideLoadedKey
  rssiActiveLoaded.value = true
  tracksideLoaded.value = true
  tracksideChartRendered.value = false
  rssiActiveError.value = ''
  tracksideError.value = ''
  publishedRssiWindowKey = key
  reportRendererWorkload('trackside-cache-ready')
  await nextTick()
  rssiChartRef.value?.applyViewport(entry.viewport)
  tracksideChartRef.value?.applyViewport(entry.viewport)
  observeTracksideChart()
}

function resetSessionDetailState(
  activeTabValue: string,
  chartRadioValue: number | null,
  preserveRecovery: boolean,
): void {
  cancelDeferredRssiChartWork()
  rssiActiveAbortController?.abort()
  rssiActiveAbortController = null
  rssiActiveRequestKey = ''
  rssiActiveLoadedKey = ''
  rssiActiveRequestPromise = null
  rssiActivePaintReady.value = false
  rssiActivePeerLoaded.value = false
  releaseTracksideResources()
  tracksideWorkloadCycle += 1
  reportedWorkloadPhases.clear()
  if (!preserveRecovery) {
    tracksideRecoveryBlocked.value = false
    tracksideRecoveryReason.value = ''
  }
  selected.value = null; buildOrders.value = []; buildOrderVisits.value = []; buildOrderTotal.value = 0; links.value = []; linkTotal.value = 0; switches.value = []; switchTotal.value = 0; switchFilters.page = 1
  rssiActivePath.value = null; rssiActiveLoading.value = false; rssiActiveLoaded.value = false; rssiActiveError.value = ''; busyActivePath.value = null; busyPeerPath.value = null
  selectedSegment.value = null; focusTimestamp.value = ''; rssiFocusLabel.value = ''; chartRadio.value = chartRadioValue; rssiViewport.value = null; busyViewport.value = null
  committedRssiViewport.value = null; pendingRssiQueryViewport.value = null; rssiViewportInteracting.value = false
  sharedPointerTime.value = null; sharedPointerSource.value = null; rssiViewportRevision = 0; tracksideChartVisible.value = typeof IntersectionObserver === 'undefined'
  tracksideObserver?.disconnect(); tracksideObserver = null
  lockedAnalysisRange.value = null; allPeerVisits.value = false; selectedChartEvent.value = null; rssiChartGeneration += 1; busyChartGeneration += 1
  artifacts.value = []; rawTail.value = null; detailSectionError.value = ''
  for (const key of Object.keys(loadedTabs)) delete loadedTabs[key]
  activeTab.value = activeTabValue
}

async function openSessionById(
  id: string,
  options: { generation: number; signal: AbortSignal; preserveRecovery: boolean; preserveView: boolean },
): Promise<void> {
  const { generation, signal, preserveRecovery, preserveView } = options
  const preservedView: PreservedSessionView | null = preserveView ? {
    activeTab: activeTab.value,
    chartRadio: chartRadio.value,
    buildOrderPage: buildOrderFilters.page,
    linkPage: linkFilters.page,
    switchPage: switchFilters.page,
  } : null
  detailLoading.value = true
  if (!preservedView) {
    analysisResultUpdatePending.value = false
    analysisResultRefreshError.value = ''
    pendingAffectedSessionId = null
    resetSessionDetailState('build-order', null, preserveRecovery)
    await nextTick()
  }
  const detail = await getMeshAnalysisSession(id, signal)
  if (generation !== detailGeneration || signal.aborted || pendingRequestedSessionId.value !== id) return
  if (preservedView) {
    const preservedRadio = preservedView.chartRadio !== null
      && (detail.available_radios || []).includes(preservedView.chartRadio)
      ? preservedView.chartRadio
      : null
    resetSessionDetailState(preservedView.activeTab, preservedRadio, preserveRecovery)
    await nextTick()
    if (generation !== detailGeneration || signal.aborted || pendingRequestedSessionId.value !== id) return
  }
  selected.value = detail
  requestWorkspaceTabTitle(`MESH：${detail.session.mr_name || detail.session.train_name}`)
  reportRendererWorkload('session-selected')
  ensureSharedRssiViewport()
  restoreSessionExpansionForDetail()
  await loadBuildOrders(generation, preservedView?.buildOrderPage ?? 1, signal)
  if (generation !== detailGeneration || signal.aborted || pendingRequestedSessionId.value !== id) return
  if (preservedView && preservedView.activeTab !== 'build-order') {
    await loadTab(preservedView.activeTab, { linkPage: preservedView.linkPage, switchPage: preservedView.switchPage })
    if (generation !== detailGeneration || signal.aborted || pendingRequestedSessionId.value !== id) return
  }
  pendingRequestedSessionId.value = null
  if (!detailSectionError.value) {
    analysisResultUpdatePending.value = false
    analysisResultRefreshError.value = ''
    if (pendingAffectedSessionId === id) pendingAffectedSessionId = null
  }
  refreshDetailPanels()
  error.value = ''
}

async function refreshIdentityProjection(): Promise<void> {
  const sessionId = selected.value?.session.session_id
  if (!sessionId || !identityMappingStale.value || identityRefreshActive.value) return
  const created = await startTask(
    () => startMeshMaintenance(sessionId, { kind: 'identity_projection_refresh' }),
    'AP 身份映射刷新任务提交失败',
  )
  if (created) ElMessage.success('AP 身份映射刷新任务已提交，请在任务中心查看进度')
}

async function rebuildParserProjection(): Promise<void> {
  const sessionId = selected.value?.session.session_id
  if (!sessionId || !parsedMaintenanceOutdated.value || taskLoading.value) return
  const created = await startTask(
    () => startMeshMaintenance(sessionId, { kind: 'parser_rebuild' }),
    'MESH 解析结果升级任务提交失败',
  )
  if (created) ElMessage.success('MESH 解析结果升级任务已提交，请在任务中心查看进度')
}

function setSessionExpanded(value: boolean): void {
  sessionExpanded.value = value
  sessionStorage.setItem(sessionExpandedKey, String(value))
}

function toggleSessionDetails(): void {
  if (isRssiWorkspaceMode.value) {
    rssiCompactSessionExpanded.value = !rssiCompactSessionExpanded.value
    refreshDetailPanels()
    return
  }
  setSessionExpanded(!sessionExpanded.value)
}

function restoreSessionExpansionForDetail(): void {
  const preference = sessionStorage.getItem(sessionExpandedKey)
  sessionExpanded.value = preference === null ? false : preference === 'true'
}

async function loadBuildOrders(
  generation = detailGeneration,
  page = buildOrderFilters.page,
  signal?: AbortSignal,
): Promise<void> {
  if (!selected.value) return
  buildOrderFilters.page = page
  const result = await listMeshActiveBuildOrder(selected.value.session.session_id, {
    ...buildOrderFilters,
    radio: buildOrderFilters.radio || null,
    peer: buildOrderFilters.peer || null,
    station: buildOrderFilters.station || null,
    build_result: buildOrderFilters.build_result || null,
    pingpong_only: buildOrderFilters.pingpong_only || null,
  }, signal)
  if (generation !== detailGeneration || signal?.aborted) return
  buildOrders.value = result.items
  buildOrderTotal.value = result.total
  if (chartRadio.value === null) chartRadio.value = result.items.find((item) => item.local_radio !== null)?.local_radio ?? null
  loadedTabs['build-order'] = true
}

async function loadBuildOrderVisits(generation = detailGeneration): Promise<void> {
  if (!selected.value || buildOrderVisits.value.length) return
  const id = selected.value.session.session_id
  const rows: MeshActiveBuildOrder[] = []
  let page = 1
  let totalRows = 0
  do {
    const result = await listMeshActiveBuildOrder(id, { page, page_size: 1000, sort_order: 'asc' })
    if (generation !== detailGeneration) return
    if (!result.items.length) break
    rows.push(...result.items)
    totalRows = result.total
    page += 1
  } while (rows.length < totalRows)
  buildOrderVisits.value = rows
}

function sortBuildOrders(payload: { order: 'ascending' | 'descending' | null }): void {
  buildOrderFilters.sort_order = payload.order === 'ascending' ? 'asc' : 'desc'
  void loadBuildOrders(detailGeneration, 1)
}

async function loadTab(tab: string, options: { linkPage?: number; switchPage?: number } = {}): Promise<void> {
  if (tab === 'busy' && selected.value && lockedAnalysisRange.value) {
    applyLockedBusyContext(lockedAnalysisRange.value)
    await loadCurrentMetricChart('busy', lockedAnalysisRange.value)
    loadedTabs.busy = true
    return
  }
  if (!selected.value || loadedTabs[tab]) {
    if (tab === 'rssi' && (!rssiActivePath.value || (!tracksideSignal.value && !tracksideRecoveryBlocked.value))) {
      if (tracksideRecoveryBlocked.value) await loadActivePath('rssi')
      else await loadCurrentMetricChart('rssi')
    }
    if (tab === 'busy' && !(busyMode.value === 'peer' ? busyPeerPath.value : busyActivePath.value)) await loadCurrentMetricChart('busy', lockedAnalysisRange.value)
    return
  }
  const generation = detailGeneration
  detailLoading.value = true
  detailSectionError.value = ''
  try {
    const id = selected.value.session.session_id
    if (tab === 'build-order') await loadBuildOrders(generation)
    else if (tab === 'links') await reloadLinks(options.linkPage ?? 1, generation)
    else if (tab === 'rssi') {
      if (tracksideRecoveryBlocked.value) await loadActivePath('rssi', null, generation)
      else await loadCurrentMetricChart('rssi', null, generation)
    }
    else if (tab === 'busy') await loadCurrentMetricChart('busy', lockedAnalysisRange.value, generation)
    else if (tab === 'switches') await reloadSwitches(options.switchPage ?? switchFilters.page, generation)
    else if (tab === 'artifacts') {
      const result = await listMeshArtifacts(id)
      if (generation === detailGeneration) artifacts.value = result
    }
    if (generation === detailGeneration) loadedTabs[tab] = true
  } catch (reason) {
    if (generation === detailGeneration) detailSectionError.value = reason instanceof Error ? reason.message : '当前分析区域加载失败'
  } finally {
    if (generation === detailGeneration) detailLoading.value = false
  }
}

async function reloadSwitches(
  page = switchFilters.page,
  generation = detailGeneration,
): Promise<void> {
  if (!selected.value) return
  switchFilters.page = page
  switchLoading.value = true
  try {
    const result = await listMeshSwitchEvents(selected.value.session.session_id, {
      page: switchFilters.page,
      page_size: switchFilters.page_size,
      radio: switchFilters.radio || null,
      result_filter: switchFilters.result || null,
    })
    if (generation !== detailGeneration) return
    switches.value = result.items
    switchTotal.value = result.total
    switchFilters.page = result.page || page
    switchFilters.page_size = result.page_size || switchFilters.page_size
    switchPanel.refresh()
  } finally {
    if (generation === detailGeneration) switchLoading.value = false
  }
}

function changeSwitchPage(page: number): void {
  detailSectionError.value = ''
  void reloadSwitches(page).catch((reason) => {
    detailSectionError.value = reason instanceof Error ? reason.message : '切换事件加载失败'
  })
}

function changeSwitchPageSize(pageSize: number): void {
  switchFilters.page_size = pageSize
  changeSwitchPage(1)
}

function changeSwitchFilters(): void {
  changeSwitchPage(1)
}

type MeshChartMetric = 'rssi' | 'busy'

function nextChartGeneration(metric: MeshChartMetric): number {
  if (metric === 'rssi') return ++rssiChartGeneration
  return ++busyChartGeneration
}

function isLatestChartRequest(metric: MeshChartMetric, generation: number): boolean {
  return generation === (metric === 'rssi' ? rssiChartGeneration : busyChartGeneration)
}

function loadTracksideSignal(
  generation = detailGeneration,
  force = false,
  range: MeshChartWindowRange | null = null,
): Promise<void> {
  if (!selected.value) return Promise.resolve()
  const sessionId = selected.value.session.session_id
  const values = {
    max_points: visiblePoints.value,
    radio: chartRadio.value,
    time_from: range?.start_time,
    time_to: range?.end_time,
    view_mode: rssiViewModeForRange(range),
  }
  const requestKey = meshChartRequestKey(
    'trackside-signal',
    sessionId,
    { ...values, include_standby: true },
  )
  if (tracksideRequestPromise && tracksideRequestKey === requestKey) {
    return tracksideRequestPromise
  }
  if (!force && tracksideLoaded.value && tracksideLoadedKey === requestKey) {
    return Promise.resolve()
  }
  releaseTracksideResources()
  if (!reserveTracksideCache(meshRuntimeToken, 2)) {
    ElMessage.warning('当前已有 2 个轨旁图处于加载或缓存状态，请先关闭一个 MESH 标签或释放其图表。')
    return Promise.resolve()
  }
  const requestGeneration = ++tracksideRequestGeneration
  const controller = new AbortController()
  tracksideAbortController = controller
  tracksideRequestKey = requestKey
  tracksideWorkloadCycle += 1
  tracksideLoading.value = true
  reportRendererWorkload('trackside-request-started')
  let requestPromise!: Promise<void>
  requestPromise = (async () => {
    await nextTick()
    try {
      const result = markRaw(await getMeshTracksideSignalChart(
        sessionId,
        values,
        controller.signal,
      ))
      if (
        generation !== detailGeneration
        || requestGeneration !== tracksideRequestGeneration
        || controller.signal.aborted
      ) return
      tracksideSignal.value = result
      reportRendererWorkload('trackside-response-received')
      reportRendererWorkload('trackside-cache-building')
      const cache = markRaw(buildTracksideSeriesCache(result.series))
      if (
        generation !== detailGeneration
        || requestGeneration !== tracksideRequestGeneration
        || controller.signal.aborted
      ) {
        disposeTracksideSeriesCache(cache)
        return
      }
      tracksideSignal.value = markRaw({ ...result, series: [] })
      tracksideSeriesCache.value = cache
      tracksideLoaded.value = true
      tracksideChartRendered.value = false
      tracksideLoadedKey = requestKey
      tracksideError.value = ''
      setTracksideCacheActive(meshRuntimeToken, true)
      reportRendererWorkload('trackside-cache-ready')
      await nextTick()
      observeTracksideChart()
    } catch (reason) {
      if (isAbortError(reason) || controller.signal.aborted || generation !== detailGeneration) return
      if (
        reason instanceof DOMException
        && reason.name === 'AbortError'
      ) return
      if (
        controller.signal.aborted
        || generation !== detailGeneration
        || requestGeneration !== tracksideRequestGeneration
      ) return
      tracksideLoaded.value = false
      tracksideError.value = reason instanceof Error ? reason.message : '轨旁AP信号图加载失败，请重试'
    } finally {
      if (!tracksideSeriesCache.value) releaseTracksideReservation(meshRuntimeToken)
      if (tracksideRequestPromise === requestPromise) {
        tracksideRequestPromise = null
        tracksideRequestKey = ''
      }
      if (requestGeneration === tracksideRequestGeneration) {
        tracksideAbortController = null
        tracksideLoading.value = false
      }
    }
  })()
  tracksideRequestPromise = requestPromise
  return requestPromise
}

function currentTracksideWindow(): MeshChartWindowRange | null {
  const viewport = pendingRssiQueryViewport.value || rssiViewport.value || committedRssiViewport.value
  if (!viewport?.start_time || !viewport.end_time) return null
  return {
    ...viewport,
    radio: chartRadio.value,
    mode: 'active',
  }
}

async function loadTracksideForCurrentWindow(): Promise<void> {
  if (tracksideRecoveryBlocked.value) tracksideRecoveryBlocked.value = false
  await loadTracksideSignal(detailGeneration, true, currentTracksideWindow())
}

function handleTracksideWorkloadPhase(phase: RendererWorkloadPhase): void {
  if (phase === 'echarts-init') setTracksideChartActive(meshRuntimeToken, true)
  if (phase === 'echarts-set-option') tracksideChartRendered.value = true
  if (phase === 'chart-disposed') setTracksideChartActive(meshRuntimeToken, false)
  reportRendererWorkload(phase)
}

function handleTracksideWorkloadProfile(profile: { conflictEdgeCount: number }): void {
  setTracksideConflictEdgeCount(meshRuntimeToken, profile.conflictEdgeCount)
}

function rssiWindowRequest(viewport: MeshChartViewport): RssiWindowRequest | null {
  const sessionId = selected.value?.session.session_id
  if (!sessionId) return null
  return {
    key: JSON.stringify([
      sessionId,
      meshChartRevisionKey(),
      chartRadio.value,
      visiblePoints.value,
      rssiResolutionMode.value,
      showRssiPeer.value,
      viewport.start_time,
      viewport.end_time,
    ]),
    sessionId,
    radio: chartRadio.value,
    startTime: viewport.start_time,
    endTime: viewport.end_time,
    generation: rssiWindowBatchGeneration + 1,
    viewport: { ...viewport },
  }
}

function rssiWindowFailure(
  source: 'active' | 'trackside',
  reason: unknown,
): { source: 'active' | 'trackside'; reason: unknown } {
  return { source, reason }
}

function loadRssiWindowBatch(viewport: MeshChartViewport): Promise<void> {
  const candidate = rssiWindowRequest(viewport)
  if (!candidate) return Promise.resolve()
  if (rssiWindowBatchPromise && rssiWindowBatchKey === candidate.key) return rssiWindowBatchPromise
  const cached = rssiWindowCache.get(candidate.key)
  if (cached && !cached.seriesCache.disposed) {
    stopRssiWindowBatch()
    return restoreRssiWindowFromCache(candidate.key, cached)
  }
  if (!reserveTracksideCache(meshRuntimeToken, 2)) {
    ElMessage.warning('当前已有 2 个轨旁图处于加载或缓存状态，请先关闭一个 MESH 标签或释放其图表。')
    return Promise.resolve()
  }

  stopRssiWindowBatch()
  const request: RssiWindowRequest = {
    ...candidate,
    generation: ++rssiWindowBatchGeneration,
  }
  const detailRequestGeneration = detailGeneration
  const activeController = new AbortController()
  const tracksideController = new AbortController()
  rssiWindowActiveAbortController = activeController
  rssiWindowTracksideAbortController = tracksideController
  rssiWindowBatchKey = request.key
  rssiWindowLoading.value = true
  rssiActiveLoading.value = true
  tracksideLoading.value = true
  rssiActiveError.value = ''
  tracksideError.value = ''
  tracksideWorkloadCycle += 1
  reportRendererWorkload('trackside-request-started')

  rssiActiveAbortController?.abort()
  rssiActiveAbortController = null
  rssiActiveRequestPromise = null
  rssiActiveRequestKey = ''
  nextChartGeneration('rssi')
  tracksideAbortController?.abort()
  tracksideAbortController = null
  tracksideRequestPromise = null
  tracksideRequestKey = ''
  tracksideRequestGeneration += 1

  const values = {
    max_points: visiblePoints.value,
    radio: request.radio,
    time_from: request.startTime,
    time_to: request.endTime,
    view_mode: rssiViewModeForViewport(viewport),
  }
  const activeValues = {
    ...values,
    resolution_mode: rssiResolutionMode.value,
    include_peer: showRssiPeer.value,
    include_standby_context: true,
    include_events: true,
    include_station_band: true,
  }
  const activeRequestKey = meshChartRequestKey('active-path', request.sessionId, {
    ...activeValues,
  })
  const tracksideWindowRequestKey = meshChartRequestKey('trackside-signal', request.sessionId, {
    ...values,
    include_standby: true,
  })

  let promise!: Promise<void>
  promise = (async () => {
    try {
      const [activeResult, tracksideResult] = await Promise.all([
        getMeshActivePathChart(request.sessionId, activeValues, activeController.signal)
          .catch((reason) => { throw rssiWindowFailure('active', reason) }),
        getMeshTracksideSignalChart(request.sessionId, values, tracksideController.signal)
          .catch((reason) => { throw rssiWindowFailure('trackside', reason) }),
      ])
      if (
        request.generation !== rssiWindowBatchGeneration
        || detailRequestGeneration !== detailGeneration
        || activeController.signal.aborted
        || tracksideController.signal.aborted
      ) return

      reportRendererWorkload('trackside-response-received')
      reportRendererWorkload('trackside-cache-building')
      const cache = markRaw(buildTracksideSeriesCache(tracksideResult.series))
      if (
        request.generation !== rssiWindowBatchGeneration
        || detailRequestGeneration !== detailGeneration
        || activeController.signal.aborted
        || tracksideController.signal.aborted
      ) {
        disposeTracksideSeriesCache(cache)
        return
      }

      rememberPublishedRssiWindow()
      const publishedViewport = { ...request.viewport }
      rssiViewport.value = publishedViewport
      committedRssiViewport.value = publishedViewport
      if (meshViewportRangeEquals(pendingRssiQueryViewport.value, publishedViewport)) {
        pendingRssiQueryViewport.value = null
      }
      rssiActivePath.value = markRaw(activeResult)
      rssiActivePeerLoaded.value = Boolean(activeValues.include_peer)
      tracksideSignal.value = markRaw({ ...tracksideResult, series: [] })
      tracksideSeriesCache.value = cache
      rssiActiveLoaded.value = true
      tracksideLoaded.value = true
      tracksideChartRendered.value = false
      rssiActiveLoadedKey = activeRequestKey
      tracksideLoadedKey = tracksideWindowRequestKey
      publishedRssiWindowKey = request.key
      rssiActiveError.value = ''
      tracksideError.value = ''
      setTracksideCacheActive(meshRuntimeToken, true)
      reportRendererWorkload('trackside-cache-ready')

      await nextTick()
      rssiChartRef.value?.applyViewport(publishedViewport)
      tracksideChartRef.value?.applyViewport(publishedViewport)
      observeTracksideChart()
    } catch (failure) {
      const item = failure as { source?: 'active' | 'trackside'; reason?: unknown }
      const reason = item.reason ?? failure
      if (
        request.generation !== rssiWindowBatchGeneration
        || detailRequestGeneration !== detailGeneration
        || activeController.signal.aborted
        || tracksideController.signal.aborted
        || isAbortError(reason)
      ) return
      const message = reason instanceof Error ? reason.message : '当前时间窗口加载失败，请重试'
      if (item.source === 'trackside') tracksideError.value = message
      else rssiActiveError.value = message
      activeController.abort()
      tracksideController.abort()
    } finally {
      if (rssiWindowBatchPromise === promise) {
        rssiWindowBatchPromise = null
        rssiWindowBatchKey = ''
      }
      if (rssiWindowActiveAbortController === activeController) {
        rssiWindowActiveAbortController = null
      }
      if (rssiWindowTracksideAbortController === tracksideController) {
        rssiWindowTracksideAbortController = null
      }
      if (request.generation === rssiWindowBatchGeneration) {
        rssiWindowLoading.value = false
        rssiActiveLoading.value = false
        tracksideLoading.value = false
      }
      if (!tracksideSeriesCache.value) releaseTracksideReservation(meshRuntimeToken)
    }
  })()
  rssiWindowBatchPromise = promise
  return promise
}

async function loadActivePath(
  metric: MeshChartMetric,
  range: MeshChartWindowRange | null = null,
  generation = detailGeneration,
  force = false,
  preserveTrackside = false,
): Promise<void> {
  if (!selected.value) return
  const effectiveRange = range ?? (metric === 'busy' ? defaultChartWindowRange(metric) : null)
  const values: Record<string, string | number | boolean | null | undefined> = {
    max_points: visiblePoints.value,
    radio: effectiveRange?.radio ?? chartRadio.value,
    include_peer: metric === 'busy' ? showBusyPeer.value : showRssiPeer.value,
    include_standby_context: true,
    include_events: true,
    include_station_band: true,
  }
  if (metric === 'rssi') {
    values.view_mode = rssiViewModeForRange(effectiveRange)
    values.resolution_mode = rssiResolutionMode.value
  }
  if (metric === 'busy') {
    values.time_from = effectiveRange?.start_time
    values.time_to = effectiveRange?.end_time
  }
  if (metric === 'rssi' && effectiveRange?.start_time && effectiveRange?.end_time) {
    values.time_from = effectiveRange.start_time
    values.time_to = effectiveRange.end_time
  }
  if (metric === 'busy') {
    const requestGeneration = nextChartGeneration(metric)
    const result = await getMeshActivePathChart(selected.value.session.session_id, values)
    if (generation === detailGeneration && isLatestChartRequest(metric, requestGeneration)) {
      busyActivePath.value = result
    }
    return
  }

  const sessionId = selected.value.session.session_id
  const requestKey = meshChartRequestKey('active-path', sessionId, {
    ...values,
  })
  if (rssiActiveRequestPromise && rssiActiveRequestKey === requestKey) {
    await rssiActiveRequestPromise
    return
  }
  if (
    !force
    && rssiActiveLoaded.value
    && rssiActivePath.value
    && rssiActiveLoadedKey === requestKey
  ) return

  if (!preserveTrackside) {
    cancelDeferredRssiChartWork()
    rssiActivePaintReady.value = false
    releaseTracksideResources()
  }
  rssiActiveAbortController?.abort()
  const requestGeneration = nextChartGeneration(metric)
  const controller = new AbortController()
  rssiActiveAbortController = controller
  rssiActiveRequestKey = requestKey
  rssiActiveLoading.value = true
  rssiActiveError.value = ''
  let requestPromise!: Promise<void>
  requestPromise = (async () => {
    try {
      const result = await getMeshActivePathChart(sessionId, values, controller.signal)
      if (
        generation !== detailGeneration
        || !isLatestChartRequest(metric, requestGeneration)
        || controller.signal.aborted
      ) return
      rssiActivePath.value = markRaw(result)
      rssiActiveLoaded.value = true
      rssiActivePeerLoaded.value = Boolean(values.include_peer)
      rssiActiveLoadedKey = requestKey
      rssiActiveError.value = ''
    } catch (reason) {
      if (
        controller.signal.aborted
        || isAbortError(reason)
        || generation !== detailGeneration
        || !isLatestChartRequest(metric, requestGeneration)
      ) return
      rssiActiveError.value = reason instanceof Error ? reason.message : '主链 RSSI 数据加载失败，请重试'
      rssiActiveLoaded.value = false
      rssiActivePaintReady.value = false
      cancelTracksideIdleSchedule?.()
      cancelTracksideIdleSchedule = null
    } finally {
      if (rssiActiveRequestPromise === requestPromise) {
        rssiActiveRequestPromise = null
        rssiActiveRequestKey = ''
      }
      if (rssiActiveAbortController === controller) {
        rssiActiveAbortController = null
        rssiActiveLoading.value = false
      }
    }
  })()
  rssiActiveRequestPromise = requestPromise
  await requestPromise
}

async function loadFullRssiCharts(generation = detailGeneration, forceRefresh = false): Promise<void> {
  await loadActivePath('rssi', null, generation, forceRefresh)
  if (generation === detailGeneration) ensureSharedRssiViewport()
  if (
    generation === detailGeneration
    && rssiActiveLoaded.value
    && !rssiActiveError.value
    && !tracksideRecoveryBlocked.value
  ) {
    if (!rssiActivePaintReady.value) {
      rssiActivePaintReady.value = await waitForActiveRssiFirstPaint(generation)
    }
    if (!rssiActivePaintReady.value) return
    observeTracksideChart()
    scheduleTracksideAfterActivePaint(generation, forceRefresh)
  }
}

async function loadRssiPeerSeries(): Promise<void> {
  const chart = rssiActivePath.value
  if (!chart || rssiActivePeerLoaded.value) return
  const timeFrom = chart.requested_time_from || chart.time_from
  const timeTo = chart.requested_time_to || chart.time_to
  const range = timeFrom && timeTo
    ? {
        ...(rssiViewport.value || {
          start_time: timeFrom,
          end_time: timeTo,
          start_percent: 0,
          end_percent: 100,
          full_start_time: timeFrom,
          full_end_time: timeTo,
          source: 'programmatic' as const,
          source_chart: 'programmatic' as const,
          revision: rssiViewportRevision,
        }),
        start_time: timeFrom,
        end_time: timeTo,
        radio: chartRadio.value,
      }
    : null
  await loadActivePath('rssi', range, detailGeneration, false, true)
}

async function retryRssiActivePath(): Promise<void> {
  const viewport = pendingRssiQueryViewport.value || rssiViewport.value || committedRssiViewport.value
  if (rssiResolutionMode.value === 'full') {
    await loadActivePath('rssi', null, detailGeneration, true, true)
    if (viewport) await loadTracksideSignal(detailGeneration, true, { ...viewport, radio: chartRadio.value })
    return
  }
  if (viewport && rssiActivePath.value && tracksideSeriesCache.value) {
    if (isFullRssiViewport(viewport)) {
      await loadFullRssiCharts(detailGeneration, true)
      return
    }
    await loadRssiWindowBatch(viewport)
    return
  }
  await loadFullRssiCharts(detailGeneration, true)
}

function reloadRssiOverviewIfNeeded(): void {
  if (!selected.value) return
  const activeOverviewLoaded = Boolean(
    rssiActiveLoaded.value
    && rssiActivePath.value?.view_mode === 'overview',
  )
  const tracksideOverviewLoaded = Boolean(
    tracksideLoaded.value
    && tracksideSignal.value?.view_mode === 'overview',
  )
  if (activeOverviewLoaded && tracksideOverviewLoaded) return
  if (activeOverviewLoaded) {
    void loadTracksideForCurrentWindow()
  } else {
    void loadFullRssiCharts(detailGeneration, true)
  }
}

function ensureSharedRssiViewport(): void {
  const domain = sharedRssiTimeDomain.value
  if (!domain) return
  if (!rssiViewport.value) {
    rssiViewport.value = createFullMeshViewportFromDomain(
      domain,
      'initial',
      'programmatic',
      ++rssiViewportRevision,
    )
    committedRssiViewport.value = rssiViewport.value ? { ...rssiViewport.value } : null
    return
  }
  const normalized = normalizeMeshViewport(rssiViewport.value, [], rssiViewport.value.source, {
    boundaryMode: 'absolute',
    fullDomain: domain,
    sourceChart: rssiViewport.value.source_chart,
    revision: rssiViewport.value.revision,
  })
  if (normalized && !meshViewportRangeEquals(normalized, rssiViewport.value)) {
    rssiViewport.value = { ...normalized, revision: ++rssiViewportRevision }
  }
}

async function loadPeerPath(
  metric: 'busy',
  anchorLinkId = selectedSegment.value?.anchor_link_id,
  range: MeshChartWindowRange | null = null,
  generation = detailGeneration,
): Promise<void> {
  if (!selected.value || !anchorLinkId) return
  const requestGeneration = nextChartGeneration(metric)
  const segment = selectedSegment.value?.anchor_link_id === anchorLinkId ? selectedSegment.value : null
  const allVisits = range?.all_visits ?? allPeerVisits.value
  const result = await getMeshPeerSegmentChart(selected.value.session.session_id, {
    anchor_link_id: anchorLinkId,
    max_points: visiblePoints.value,
    all_visits: allVisits || null,
    time_from: range?.start_time ?? (allVisits ? null : segment?.build_start_time),
    time_to: range?.end_time ?? (allVisits ? null : segment?.build_end_time),
  })
  if (generation !== detailGeneration || !isLatestChartRequest(metric, requestGeneration)) return
  busyPeerPath.value = result
}

async function loadCurrentMetricChart(
  metric: MeshChartMetric,
  range: MeshChartWindowRange | null = null,
  generation = detailGeneration,
): Promise<void> {
  if (metric === 'rssi') {
    await loadFullRssiCharts(generation)
    return
  }
  const mode = range?.mode ?? busyMode.value
  if (mode === 'peer') await loadPeerPath(metric, range?.anchor_link_id ?? selectedSegment.value?.anchor_link_id, range, generation)
  else await loadActivePath(metric, range, generation)
}

function formatMeshTimestamp(value: number): string {
  const date = new Date(value)
  const pad = (number: number, size = 2): string => String(number).padStart(size, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`
}

function buildRssiWindowRange(startTime: string, endTime: string | null, radio: number | null): MeshChartWindowRange | null {
  const start = meshTimestampMillis(startTime)
  const end = endTime ? meshTimestampMillis(endTime) : null
  if (start === null || (endTime && end === null) || (end !== null && end <= start)) return null
  const duration = end === null ? null : end - start
  const buffer = end === null
    ? 15_000
    : Math.min(15_000, Math.max(5_000, Math.round((duration || 0) * 0.2)))
  const windowStart = start - buffer
  const windowEnd = end === null ? start + buffer : end + buffer
  const domain = sharedRssiTimeDomain.value || {
    full_start_time: formatMeshTimestamp(windowStart),
    full_end_time: formatMeshTimestamp(windowEnd),
  }
  const normalized = normalizeMeshViewport({
    start_time: formatMeshTimestamp(windowStart),
    end_time: formatMeshTimestamp(windowEnd),
    start_percent: 0,
    end_percent: 100,
    full_start_time: domain.full_start_time,
    full_end_time: domain.full_end_time,
    source: 'programmatic',
    source_chart: 'programmatic',
    revision: rssiViewportRevision + 1,
  }, [], 'programmatic', {
    boundaryMode: 'absolute',
    fullDomain: domain,
    sourceChart: 'programmatic',
    revision: rssiViewportRevision + 1,
  })
  return normalized ? { ...normalized, radio } : null
}

function defaultChartWindowRange(metric: MeshChartMetric): MeshChartWindowRange | null {
  const viewport = metric === 'busy' ? busyViewport.value : rssiViewport.value
  if (viewport?.start_time && viewport.end_time) {
    return {
      ...viewport,
      radio: (viewport as MeshChartWindowRange).radio ?? chartRadio.value,
      mode: metric === 'busy' ? busyMode.value : 'active',
    }
  }
  const segment = selectedSegment.value || buildOrders.value[0]
  if (segment?.build_start_time) {
    return buildRssiWindowRange(
      segment.build_start_time,
      segment.build_end_time || null,
      chartRadio.value ?? segment.local_radio ?? null,
    )
  }
  const firstSampleTime = selected.value?.session.first_sample_time || ''
  return firstSampleTime ? buildRssiWindowRange(firstSampleTime, null, chartRadio.value) : null
}

async function reloadCurrentChart(): Promise<void> {
  const metric: MeshChartMetric = activeTab.value === 'busy' ? 'busy' : 'rssi'
  const viewport = metric === 'rssi' ? rssiViewport.value : null
  if (metric === 'rssi') {
    await loadFullRssiCharts(detailGeneration, true)
  } else {
    await loadCurrentMetricChart(metric, lockedAnalysisRange.value)
  }
  if (metric === 'rssi' && viewport) {
    updateRssiViewport(viewport)
  }
}

async function changeRssiResolutionMode(): Promise<void> {
  if (rssiResolutionMode.value === 'high') visiblePoints.value = 4000
  else if (rssiResolutionMode.value === 'overview' && visiblePoints.value > 2000) visiblePoints.value = 2000
  await reloadCurrentChart()
}

function resetCurrentChartViewport(): void {
  if (activeTab.value === 'busy') busyChartRef.value?.resetViewport()
  else {
    const domain = sharedRssiTimeDomain.value
    if (!domain) return
    const viewport = createFullMeshViewportFromDomain(
      domain,
      'programmatic',
      'programmatic',
      ++rssiViewportRevision,
    )
    if (!viewport) return
    if (meshViewportRangeEquals(rssiViewport.value, viewport)) {
      rssiViewport.value = viewport
      rssiChartRef.value?.applyViewport(viewport)
      tracksideChartRef.value?.applyViewport(viewport)
      return
    }
    pendingRssiQueryViewport.value = viewport
    rssiViewport.value = viewport
    committedRssiViewport.value = { ...viewport }
    invalidateRssiWindowBatch()
    scheduleRssiWindowReload(viewport, 0)
    rssiChartRef.value?.applyViewport(viewport)
    tracksideChartRef.value?.applyViewport(viewport)
  }
}

function clearTimeLock(): void {
  if (lockedAnalysisRange.value) {
    busyActivePath.value = null
    busyPeerPath.value = null
    busyViewport.value = null
  }
  lockedAnalysisRange.value = null
}

function updateRssiViewport(viewport: MeshChartViewport): void {
  const domain = sharedRssiTimeDomain.value
  if (!domain) return
  const accepted = acceptMeshSharedViewport(
    rssiViewport.value,
    viewport,
    domain,
    rssiViewportRevision + 1,
  )
  if (!accepted || accepted === rssiViewport.value) return
  rssiViewportRevision += 1
  rssiViewport.value = accepted
  if (isFullRssiViewport(accepted)) {
    pendingRssiQueryViewport.value = null
    invalidateRssiWindowBatch()
    if (accepted.source === 'user_zoom') {
      reloadRssiOverviewIfNeeded()
    }
    rssiChartRef.value?.applyViewport(accepted)
    tracksideChartRef.value?.applyViewport(accepted)
    return
  }
  if (accepted.source === 'user_zoom' && accepted.start_time && accepted.end_time) {
    pendingRssiQueryViewport.value = accepted
    if (!rssiViewportInteracting.value) {
      invalidateRssiWindowBatch()
      scheduleRssiWindowReload(accepted, rssiIdleCommitDelayMs)
    }
  }
}

function beginRssiViewportInteraction(): void {
  if (rssiViewportInteracting.value) return
  rssiViewportInteracting.value = true
  if (rssiWindowReloadTimer !== null) window.clearTimeout(rssiWindowReloadTimer)
  rssiWindowReloadTimer = null
  pendingRssiQueryViewport.value = null
  invalidateRssiWindowBatch()
}

function endRssiViewportInteraction(): void {
  if (!rssiViewportInteracting.value) return
  rssiViewportInteracting.value = false
  const viewport = pendingRssiQueryViewport.value
  if (viewport) scheduleRssiWindowReload(viewport, rssiPointerCommitDelayMs)
}

function scheduleRssiWindowReload(
  viewport: MeshChartViewport,
  delayMs = rssiIdleCommitDelayMs,
): void {
  pendingRssiQueryViewport.value = { ...viewport }
  if (rssiWindowReloadTimer !== null) window.clearTimeout(rssiWindowReloadTimer)
  rssiWindowReloadTimer = null
  if (rssiViewportInteracting.value) return
  if (isFullRssiViewport(viewport)) {
    reloadRssiOverviewIfNeeded()
    return
  }
  if (rssiResolutionMode.value === 'full') {
    rssiWindowReloadTimer = window.setTimeout(() => {
      rssiWindowReloadTimer = null
      if (!rssiViewportInteracting.value) void loadTracksideSignal(detailGeneration, true, { ...viewport, radio: chartRadio.value })
    }, Math.max(0, delayMs))
    return
  }
  rssiWindowReloadTimer = window.setTimeout(() => {
    rssiWindowReloadTimer = null
    if (rssiViewportInteracting.value) return
    const pending = pendingRssiQueryViewport.value
    if (!pending || !meshViewportRangeEquals(pending, viewport)) return
    void loadRssiWindowBatch(pending)
  }, Math.max(0, delayMs))
}

function updateSharedPointer(pointer: MeshSharedPointerChange): void {
  if (sharedPointerTime.value === pointer.time && sharedPointerSource.value === pointer.source_chart) return
  railTimeline.setCursor(pointer)
}

function selectAnalysisTime(time: string): void {
  railTimeline.selectTime(time)
}

function updateBusyViewport(viewport: MeshChartViewport): void {
  busyViewport.value = viewport
}

function lockCurrentRssiRange(): void {
  if (!selected.value || !selectedSource.value?.source_file_id) return
  const viewport = rssiChartRef.value?.getVisibleTimeRange()
  if (!viewport) {
    ElMessage.warning('当前 RSSI 图没有可锁定的时间范围')
    return
  }
  const fullLine = chartData.value?.rssi_line?.points || []
  const startMillis = meshTimestampMillis(viewport.start_time)
  const endMillis = meshTimestampMillis(viewport.end_time)
  const samples = fullLine.length && startMillis !== null && endMillis !== null
    ? fullLine
        .filter(([timestamp]) => {
          const value = meshTimestampMillis(timestamp)
          return value !== null && value >= startMillis && value <= endMillis
        })
        .map(([timestamp]) => ({ timestamp }))
    : visibleMeshSamples(chartData.value?.points || [], viewport)
  if (samples.length < 2) {
    ElMessage.warning('请至少选择包含两个真实采样点的时间范围')
    return
  }
  rssiViewport.value = viewport
  lockedAnalysisRange.value = {
    ...viewport,
    session_id: selected.value.session.session_id,
    source_file_id: selectedSource.value.source_file_id,
    radio: chartRadio.value,
    mode: 'active',
    anchor_link_id: null,
    all_visits: false,
    first_sample_time: samples[0]?.timestamp || null,
    last_sample_time: samples.at(-1)?.timestamp || null,
    sample_count: samples.length,
    created_at: new Date().toISOString(),
  }
  ElMessage.success('已锁定当前 RSSI 时间范围')
}

function applyLockedBusyContext(range: MeshLockedAnalysisRange): void {
  busyMode.value = range.mode
  chartRadio.value = range.radio
  allPeerVisits.value = range.all_visits
  if (range.anchor_link_id) {
    selectedSegment.value = buildOrderOptions.value.find((item) => item.anchor_link_id === range.anchor_link_id) || selectedSegment.value
  }
}

function openLockedBusyRange(): void {
  const range = lockedAnalysisRange.value
  if (!range) return
  applyLockedBusyContext(range)
  busyActivePath.value = null
  busyPeerPath.value = null
  activeTab.value = 'busy'
}

function returnToRssi(): void {
  activeTab.value = 'rssi'
}

async function updateLockedRangeFromBusy(): Promise<void> {
  const current = lockedAnalysisRange.value
  const viewport = busyChartRef.value?.getVisibleTimeRange()
  if (!current || !viewport) return
  const samples = visibleMeshSamples(busyChartData.value?.points || [], viewport)
  if (samples.length < 2) {
    ElMessage.warning('当前空口视图不足两个真实采样点，无法更新锁定范围')
    return
  }
  lockedAnalysisRange.value = {
    ...current,
    ...viewport,
    first_sample_time: samples[0]?.timestamp || null,
    last_sample_time: samples.at(-1)?.timestamp || null,
    sample_count: samples.length,
    created_at: new Date().toISOString(),
  }
  await loadCurrentMetricChart('busy', lockedAnalysisRange.value)
}

async function unlockAndShowAll(): Promise<void> {
  clearTimeLock()
  busyViewport.value = null
  busyActivePath.value = null
  busyPeerPath.value = null
  await loadCurrentMetricChart('busy')
}

async function selectSegmentByAnchor(value: string | number): Promise<void> {
  clearTimeLock()
  busyPeerPath.value = null
  if (value === 'all-visits') {
    if (!selectedSegment.value && buildOrderOptions.value[0]) selectedSegment.value = buildOrderOptions.value[0]
    allPeerVisits.value = true
    await loadPeerPath('busy')
    return
  }
  const row = buildOrderOptions.value.find((item) => item.anchor_link_id === Number(value))
  if (!row) return
  selectedSegment.value = row
  allPeerVisits.value = false
  chartRadio.value = row.local_radio
  focusTimestamp.value = row.build_start_time
  await loadPeerPath('busy', row.anchor_link_id)
}

async function changeBusyMode(value: string | number): Promise<void> {
  if (lockedAnalysisRange.value && value === lockedAnalysisRange.value.mode) {
    await loadCurrentMetricChart('busy', lockedAnalysisRange.value)
    return
  }
  clearTimeLock()
  busyViewport.value = null
  if (value !== 'peer') { await loadActivePath('busy'); return }
  await loadBuildOrderVisits()
  if (!selectedSegment.value && buildOrderOptions.value[0]) selectedSegment.value = buildOrderOptions.value[0]
  allPeerVisits.value = false
  await loadPeerPath('busy')
}

async function changeChartRadio(): Promise<void> {
  cancelDeferredRssiChartWork()
  cancelInFlightRssiChartRequests()
  clearTimeLock()
  rssiViewport.value = null
  committedRssiViewport.value = null
  pendingRssiQueryViewport.value = null
  rssiViewportInteracting.value = false
  sharedPointerTime.value = null
  sharedPointerSource.value = null
  busyViewport.value = null
  rssiActivePath.value = null
  rssiActiveLoaded.value = false
  rssiActiveLoadedKey = ''
  rssiActivePaintReady.value = false
  rssiActivePeerLoaded.value = false
  rssiActiveError.value = ''
  releaseTracksideResources()
  busyActivePath.value = null
  await reloadCurrentChart()
}

function selectBuildOrderRow(row: MeshActiveBuildOrder): void {
  clearTimeLock()
  selectedSegment.value = row
  allPeerVisits.value = false
  chartRadio.value = row.local_radio
  focusTimestamp.value = row.build_start_time
}

async function openBuildOrderRssi(row: MeshActiveBuildOrder): Promise<void> {
  selectBuildOrderRow(row)
  activeTab.value = 'rssi'
  const range = buildRssiWindowRange(row.build_start_time, row.build_end_time || null, row.local_radio)
  if (!range) {
    ElMessage.warning('当前建链时间无效，无法打开动态图')
    return
  }
  updateRssiViewport(range)
  rssiFocusLabel.value = `已定位：主链路建链顺序 #${row.sequence} · ${row.build_start_time} — ${row.build_end_time}`
  await nextTick()
  document.querySelector('.detail-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function showLinkChart(row: MeshLinkDetail): Promise<void> {
  clearTimeLock()
  focusTimestamp.value = row.timestamp
  allPeerVisits.value = false
  chartRadio.value = row.local_radio
  activeTab.value = 'rssi'
  const range = buildRssiWindowRange(row.timestamp, null, row.local_radio)
  if (!range) {
    ElMessage.warning('当前链路时间无效，无法打开动态图')
    return
  }
  updateRssiViewport(range)
  rssiFocusLabel.value = `已定位：链路明细 #${row.record_id} · ${row.timestamp}`
  await nextTick()
}

function selectChartSwitch(event: MeshChartEvent): void {
  selectedChartEvent.value = event
  focusTimestamp.value = event.timestamp
  railTimeline.selectTime(event.timestamp)
  const range = buildRssiWindowRange(event.timestamp, null, event.local_radio)
  if (range) updateRssiViewport(range)
}

async function showSwitchInBuildOrder(): Promise<void> {
  if (!selected.value || !selectedChartEvent.value) return
  const event = selectedChartEvent.value
  const result = await listMeshActiveBuildOrder(selected.value.session.session_id, {
    page: 1,
    page_size: 100,
    sort_order: 'asc',
    radio: event.local_radio,
    time_from: event.timestamp,
    time_to: event.timestamp,
  })
  if (!result.items.length) return
  buildOrders.value = result.items
  buildOrderTotal.value = result.total
  selectedSegment.value = result.items.find((row) => row.sequence === event.segment_sequence) || result.items[0]
  activeTab.value = 'build-order'
  await nextTick()
  document.querySelector('.detail-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function reloadLinks(page = linkFilters.page, generation = detailGeneration): Promise<void> {
  if (!selected.value) return
  linkFilters.page = page
  const result = await listMeshLinks(selected.value.session.session_id, linkFilters)
  if (generation !== detailGeneration) return
  links.value = result.items; linkTotal.value = result.total; loadedTabs.links = true
}

async function loadRawTail(sourceActionId: string, available: boolean): Promise<void> {
  if (!selected.value || !available) return
  rawTail.value = await getMeshRawTail(selected.value.session.session_id, sourceActionId)
}

async function downloadArtifact(artifact: MeshArtifact): Promise<void> {
  if (!selected.value) return
  try {
    const result = await downloadBackendResource(meshArtifactDownloadRequest(
      selected.value.session.session_id,
      artifact.artifact_id,
      artifact.name,
    ))
    if (result.status === 'failed') ElMessage.error(result.error || 'Artifact 下载失败')
    else if (result.status === 'saved') ElMessage.success('Artifact 已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载')
  } catch {
    ElMessage.error('Artifact 下载失败')
  }
}

async function loadProfiles(): Promise<void> {
  const generation = ++profileLoadGeneration
  profileLoadError.value = ''
  vehicleMrLoadError.value = ''
  const [contextResult] = await Promise.allSettled([getMeshImportContext()])
  if (generation !== profileLoadGeneration) return
  if (contextResult.status === 'fulfilled') {
    profiles.value = contextResult.value.profiles
    baseMrs.value = contextResult.value.vehicle_mrs
  } else {
    const message = contextResult.reason instanceof Error
      ? contextResult.reason.message
      : 'MESH 导入上下文加载失败'
    profileLoadError.value = message
    vehicleMrLoadError.value = message
  }
  applyLinkedMrProfileName()
}

async function scanLocalLogs(): Promise<void> {
  if (localScanLoading.value) return
  localScanLoading.value = true
  localScanError.value = ''
  try {
    const started = await startMeshLocalScan()
    localScanId.value = started.scan_id
    localScanResult.value = null
    localScanSelected.value = []
    for (const key of Object.keys(localScanMappings)) delete localScanMappings[key]
    localStorage.setItem(localScanStorageKey, started.scan_id)
    localScanVisible.value = true
    rememberTask(started.task)
    pollTask()
    ElMessage.success('本地 MESH 日志扫描任务已提交')
  } catch (reason) {
    localScanError.value = reason instanceof Error ? reason.message : '本地 MESH 日志扫描启动失败'
  } finally {
    localScanLoading.value = false
  }
}

async function loadLocalScanResult(scanId = localScanId.value): Promise<boolean> {
  if (!scanId) return false
  localScanError.value = ''
  try {
    const result = await getMeshLocalScan(scanId)
    localScanId.value = result.scan_id
    localScanResult.value = result
    const importable = result.candidates.filter((item) => ['unregistered', 'needs_metadata', 'failed', 'parse_failed', 'repair_failed'].includes(item.scan_status))
    localScanSelected.value = importable.map((item) => item.candidate_id)
    for (const item of result.candidates) {
      if (item.profile_id) localScanMappings[item.candidate_id] = item.profile_id
    }
    if (!profiles.value.length) await loadProfiles()
    return true
  } catch (reason) {
    localScanError.value = reason instanceof Error ? reason.message : '本地扫描结果读取失败'
    return false
  }
}

async function restoreLocalScanResult(): Promise<void> {
  const scanId = localStorage.getItem(localScanStorageKey) || ''
  if (!scanId) return
  localScanId.value = scanId
  if (!await loadLocalScanResult(scanId)) {
    localStorage.removeItem(localScanStorageKey)
    localScanId.value = ''
  }
}

function toggleLocalScanCandidate(candidate: MeshLocalScanCandidate, checked: boolean): void {
  const next = new Set(localScanSelected.value)
  if (checked) next.add(candidate.candidate_id)
  else next.delete(candidate.candidate_id)
  localScanSelected.value = [...next]
}

async function importSelectedLocalScan(): Promise<void> {
  if (!localScanId.value || !localScanCanImport.value || localScanImporting.value) return
  localScanImporting.value = true
  localScanError.value = ''
  try {
    const created = await importMeshLocalScan(
      localScanId.value,
      localScanSelected.value.map((candidateId) => ({
        candidate_id: candidateId,
        profile_id: localScanMappings[candidateId] || '',
      })),
    )
    rememberTask(created)
    pollTask()
    ElMessage.success(created.action === 'mesh_derived_data_repair'
      ? '检测到分析数据库需要升级，系统正在自动修复并将在完成后继续导入。'
      : '已提交所选本地 MESH 日志导入任务')
  } catch (reason) {
    localScanError.value = reason instanceof Error ? reason.message : '本地 MESH 日志导入启动失败'
  } finally {
    localScanImporting.value = false
  }
}

function selectAllLocalScanCandidates(): void {
  localScanSelected.value = localScanImportable.value.map((item) => item.candidate_id)
}

async function ignoreSelectedLocalScan(): Promise<void> {
  if (!localScanId.value || !localScanSelected.value.length) return
  try {
    localScanResult.value = await ignoreMeshLocalScanCandidates(localScanId.value, localScanSelected.value)
    localScanSelected.value = []
  } catch (reason) {
    localScanError.value = reason instanceof Error ? reason.message : '忽略本地日志失败'
  }
}

async function openLocalScanDirectory(candidate: MeshLocalScanCandidate): Promise<void> {
  if (!localScanId.value) return
  try {
    const result = await openMeshLocalScanCandidateDirectory(localScanId.value, candidate.candidate_id)
    if (!result.success) throw new Error(result.message || '当前宿主不支持打开本地目录')
    ElMessage.success('已打开所在目录')
  } catch (reason) {
    localScanError.value = reason instanceof Error ? reason.message : '打开所在目录失败'
  }
}

function localScanStatusText(status: MeshLocalScanCandidate['scan_status']): string {
  return {
    unregistered: '未导入',
    imported: '已导入',
    duplicate: '重复内容',
    invalid: '无效文件',
    needs_metadata: '待补充信息',
    failed: '导入失败，可重试',
    waiting_repair: '等待分析数据库升级',
    repairing: '正在自动修复',
    queued: '等待自动导入',
    parsing: '正在解析',
    repair_failed: '自动修复失败，可重试',
    parse_failed: '日志解析失败，可重试',
    ignored: '已忽略',
  }[status]
}

function openImportDialog(): void {
  importVisible.value = true
  if (!importProfilesReadyPromise) {
    const promise = loadProfiles()
    importProfilesReadyPromise = promise
    void promise.finally(() => {
      if (importProfilesReadyPromise === promise) importProfilesReadyPromise = null
    })
  }
}

async function prepareImportContext(): Promise<void> {
  if (importContextPromise) {
    await importContextPromise
    return
  }
  const generation = ++importContextGeneration
  importContextError.value = ''
  importContextWarnings.value = []
  profileLoadError.value = ''
  vehicleMrLoadError.value = ''
  importContextLoading.value = true
  const promise = (async () => {
    try {
      const result = await prepareMeshImportContext()
      if (generation === importContextGeneration) {
        importContextWarnings.value = result.warnings || []
      }
    } catch (reason) {
      if (generation === importContextGeneration) {
        importContextError.value = meshImportContextErrorMessage(reason)
      }
    } finally {
      await loadProfiles()
      if (generation === importContextGeneration) importContextLoading.value = false
    }
  })()
  importContextPromise = promise
  importProfilesReadyPromise = promise
  try {
    await promise
  } finally {
    if (importContextPromise === promise) importContextPromise = null
  }
}

function meshImportContextErrorMessage(reason: unknown): string {
  if (
    (
      reason instanceof ApiRequestError
      && [
        'BACKEND_UNREACHABLE',
        'BACKEND_CONNECTION_INTERRUPTED',
        'CONNECTION_RESET',
        'BACKEND_RESTARTED',
      ].includes(reason.code)
    )
    || (reason instanceof TypeError && /failed to fetch/i.test(reason.message))
  ) {
    return t(
      'mesh.import.backend_interrupted',
      'Backend 连接中断，导入上下文未完成。现有内部归属仍可继续使用，请重试或查看 Backend 日志。',
    )
  }
  if (reason instanceof ApiRequestError && reason.code) return `${reason.message}（${reason.code}）`
  return reason instanceof Error ? reason.message : '车载 MR 与内部 MESH 归属同步失败'
}

function normalizeVehicleMrRole(mr: VehicleMr): 'CT' | 'CW' | '' {
  for (const value of [mr.mr_position_code, mr.role, mr.name]) {
    const normalized = String(value || '').trim().toUpperCase().replaceAll('_', '-')
    const matched = normalized.match(/(?:^|-)(?:MR-)*(CT|CW)(?:$|-)/)
    if (matched?.[1] === 'CT' || matched?.[1] === 'CW') return matched[1]
  }
  return ''
}

function autoProfileNameForMr(mr: VehicleMr): string {
  const explicit = String(mr.name || '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/^(?:列车\s*){2,}/, '列车')
    .replace(/(?:MR[\s_-]*){2,}(CT|CW)\b/gi, 'MR-$1')
  if (explicit) return explicit
  const trainNo = String(mr.train_no || '').trim().replace(/^列车\s*/i, '').replace(/\s+/g, '')
  const role = normalizeVehicleMrRole(mr)
  return trainNo && role ? `列车${trainNo}-MR-${role}` : ''
}

function vehicleMrOptionLabel(mr: VehicleMr): string {
  return [
    String(mr.train_no || '').trim(),
    normalizeVehicleMrRole(mr),
    autoProfileNameForMr(mr),
  ].filter(Boolean).join(' · ')
}

function applyLinkedMrProfileName(): void {
  const previousAutoName = lastAutoFilledProfileName.value
  const selectedMr = baseMrs.value.find((mr) => mr.id === linkedMrId.value)
  if (!selectedMr) {
    if (newProfileName.value.trim() === previousAutoName) newProfileName.value = ''
    lastAutoFilledProfileName.value = ''
    profileNameManuallyEdited = false
    return
  }
  const autoName = autoProfileNameForMr(selectedMr)
  if (!autoName) return
  const currentName = newProfileName.value.trim()
  if (!currentName || currentName === previousAutoName || !profileNameManuallyEdited) {
    newProfileName.value = autoName
    lastAutoFilledProfileName.value = autoName
    profileNameManuallyEdited = false
  }
}

function applyBatchMrMapping(): void {
  batchMappingConfirmed.value = false
  const mr = baseMrs.value.find((item) => item.id === batchLinkedMrId.value)
  if (!mr || !bundlePreview.value) return
  const profile = profiles.value.find((item) => (
    item.linked_device_uuid === mr.id
    || (mr.device_id !== null && item.linked_device_id === mr.device_id)
  ))
  const role = normalizeVehicleMrRole(mr)
  const trainNumber = String(mr.train_no || '').trim().replace(/^列车\s*/i, '')
  if (!profile || !role || !trainNumber) {
    ElMessage.warning('所选 MR 缺少内部归属、列车号或 CT/CW 端位，请先准备导入上下文。')
    return
  }
  for (const item of bundlePreview.value.items) {
    bundleMappings[item.member_id] = {
      member_id: item.member_id,
      train_number: trainNumber,
      role,
      profile_id: profile.mr_id,
      confirmed: false,
    }
  }
}

function markProfileNameEdited(value: string): void {
  profileNameManuallyEdited = String(value || '').trim() !== lastAutoFilledProfileName.value
}

function linkedMeshProfile(): MeshProfile | undefined {
  const selectedMr = baseMrs.value.find((mr) => mr.id === linkedMrId.value)
  if (!selectedMr) return undefined
  return profiles.value.find((profile) => (
    profile.linked_device_uuid === selectedMr.id
    || (
      selectedMr.device_id !== null
      && profile.linked_device_id === selectedMr.device_id
    )
  ))
}

async function createProfile(): Promise<void> {
  if (!newProfileName.value.trim()) return
  const existing = linkedMeshProfile()
  if (existing) {
    newProfileName.value = existing.display_name
    lastAutoFilledProfileName.value = existing.display_name
    profileNameManuallyEdited = false
    ElMessage.info(`已选用现有内部归属：${existing.display_name}`)
    return
  }
  taskLoading.value = true; error.value = ''
  try {
    await createMeshProfile({ display_name: newProfileName.value.trim(), linked_mr_id: linkedMrId.value, notes: profileNotes.value.trim() })
    await loadProfiles()
    newProfileName.value = ''
    linkedMrId.value = ''
    lastAutoFilledProfileName.value = ''
    profileNameManuallyEdited = false
    profileNotes.value = ''
    ElMessage.success('内部 MESH 归属已创建')
  } catch (reason) {
    if (reason instanceof ApiRequestError && reason.code === 'PROFILE_ALREADY_LINKED') {
      await loadProfiles()
      const displayName = String(reason.details.display_name || linkedMeshProfile()?.display_name || '')
      if (displayName) newProfileName.value = displayName
      ElMessage.info(displayName ? `已选用现有内部归属：${displayName}` : reason.message)
    } else {
      error.value = reason instanceof Error ? reason.message : '内部 MESH 归属创建失败'
    }
  }
  finally { taskLoading.value = false }
}
function isSafeRelativePath(value: string): boolean {
  const normalized = value.replaceAll('\\', '/')
  return !normalized.startsWith('/') && !/^[A-Za-z]:\//.test(normalized) && !normalized.split('/').includes('..')
}
function chooseFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  selectedFiles.value = files.filter((file) => {
    const name = file.name.toLowerCase()
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || name
    return ['.zip', '.log', '.txt', '.gz'].some((suffix) => name.endsWith(suffix)) && isSafeRelativePath(relative)
  })
  importPreviewGeneration += 1
  importPreviewController?.abort()
  importPreviewController = null
  importPreviewStage.value = selectedFiles.value.length ? '等待预览' : ''
  importPreviewError.value = ''
  bundlePreview.value = null
  batchLinkedMrId.value = ''
  batchMappingConfirmed.value = false
  for (const key of Object.keys(bundleMappings)) delete bundleMappings[key]
  input.value = ''
  if (selectedFiles.value.length) void previewImportFiles()
}
async function previewImportFiles(): Promise<void> {
  const generation = ++importPreviewGeneration
  const files = [...selectedFiles.value]
  if (!files.length) return
  bundlePreviewLoading.value = true
  importPreviewController?.abort()
  const controller = new AbortController()
  importPreviewController = controller
  importPreviewStage.value = '正在上传并校验文件'
  importPreviewError.value = ''
  bundlePreview.value = null
  batchMappingConfirmed.value = false
  for (const key of Object.keys(bundleMappings)) delete bundleMappings[key]
  error.value = ''
  try {
    await importProfilesReadyPromise
    if (generation !== importPreviewGeneration) return
    const preview = await previewMeshImport(files, controller.signal)
    if (generation !== importPreviewGeneration) return
    bundlePreview.value = preview
    importPreviewStage.value = '预览完成'
    for (const item of preview.items) {
      const firstCandidate = item.selected_profile_id || item.candidates[0]?.profile_id || ''
      bundleMappings[item.member_id] = {
        member_id: item.member_id,
        train_number: item.train_number,
        role: item.role === 'CT' || item.role === 'CW' ? item.role : '',
        profile_id: firstCandidate,
        confirmed: item.match_status === 'matched' && Boolean(firstCandidate) && Boolean(item.train_number) && Boolean(item.role),
      }
    }
  } catch (reason) {
    if (generation !== importPreviewGeneration) return
    if (controller.signal.aborted) {
      importPreviewStage.value = '已取消'
      return
    }
    bundlePreview.value = null
    importPreviewError.value = reason instanceof ApiRequestError && reason.code
      ? `${reason.code}：${reason.message}`
      : reason instanceof Error
        ? reason.message
        : 'MESH 日志预览失败'
  } finally {
    if (generation === importPreviewGeneration) {
      bundlePreviewLoading.value = false
      if (importPreviewController === controller) importPreviewController = null
    }
  }
}

function cancelImportPreview(): void {
  importPreviewGeneration += 1
  importPreviewController?.abort()
  importPreviewController = null
  bundlePreviewLoading.value = false
  importPreviewStage.value = '已取消'
}
function profileCandidates(item: MeshBundlePreview['items'][number]): Array<{ profile_id: string; display_name: string }> {
  return item.candidates.length ? item.candidates : profiles.value.map((profile) => ({ profile_id: profile.mr_id, display_name: profile.display_name }))
}
function previewImportState(item: MeshBundlePreview['items'][number]) {
  const profileId = bundleMappings[item.member_id]?.profile_id || item.selected_profile_id
  return (item.profile_import_states || []).find((state) => state.profile_id === profileId) || {
    profile_id: profileId,
    profile_name: item.selected_profile_name,
    stored_filename: item.stored_filename || item.safe_name,
    daily_sequence: item.daily_sequence,
    rename_status: item.rename_status || '',
    rename_warning: item.rename_warning || '',
    duplicate_status: item.duplicate_status || 'new',
    import_allowed: item.import_allowed !== false,
    existing_source_id: item.existing_source_id,
    existing_stored_filename: item.existing_stored_filename || '',
    existing_session_id: item.existing_session_id || '',
    existing_profile_id: item.existing_profile_id || '',
    existing_profile_name: item.existing_profile_name || '',
  }
}
function batchDuplicateMappingMatches(item: MeshBundlePreview['items'][number]): boolean {
  if (!item.batch_duplicate_of || !bundlePreview.value) return true
  const original = bundlePreview.value.items.find((candidate) => candidate.member_id === item.batch_duplicate_of)
  if (!original) return false
  return Boolean(
    bundleMappings[item.member_id]?.profile_id
    && bundleMappings[item.member_id]?.profile_id === bundleMappings[original.member_id]?.profile_id,
  )
}
function bundleItemReady(item: MeshBundlePreview['items'][number]): boolean {
  const mapping = bundleMappings[item.member_id]
  if (!mapping?.member_id || !mapping.train_number.trim() || !mapping.role || !mapping.profile_id) return false
  if (!batchDuplicateMappingMatches(item)) return false
  if (item.batch_duplicate_of) return true
  const state = previewImportState(item)
  if (state?.duplicate_status === 'duplicate_other_mr') return false
  if (state?.duplicate_status === 'duplicate_same_mr') return true
  return true
}
function previewDuplicateLabel(item: MeshBundlePreview['items'][number]): string {
  if (item.batch_duplicate_of) return '批次内重复'
  const status = previewImportState(item)?.duplicate_status || item.duplicate_status
  if (status === 'duplicate_same_mr') return '已导入，自动跳过'
  if (status === 'duplicate_other_mr') return '内容属于其他 MR'
  return '新日志'
}
function previewStoredFilename(item: MeshBundlePreview['items'][number]): string {
  return previewImportState(item)?.stored_filename || item.stored_filename || item.safe_name
}
function clearImportSelection(): void {
  importPreviewGeneration += 1
  importPreviewController?.abort()
  importPreviewController = null
  importPreviewStage.value = ''
  selectedFiles.value = []
  bundlePreview.value = null
  batchLinkedMrId.value = ''
  batchMappingConfirmed.value = false
  importPreviewError.value = ''
  for (const key of Object.keys(bundleMappings)) delete bundleMappings[key]
  if (fileInput.value) fileInput.value.value = ''
  if (folderInput.value) folderInput.value.value = ''
}
function rememberTask(value: RailTransitTask | null): void {
  const previousTaskId = task.value?.task_id || ''
  task.value = value
  if (value && value.task_id !== previousTaskId) processedTerminalTaskIds.clear()
  if (value && !terminalStates.has(value.status)) localStorage.setItem(taskStorageKey, value.task_id)
  else localStorage.removeItem(taskStorageKey)
  if (value && value.task_id !== previousTaskId) void taskStore.refresh()
}
function stopTaskPolling(): void { if (taskTimer) clearTimeout(taskTimer); taskTimer = null }

function affectedSessionId(completedTask: RailTransitTask): string | null {
  const resultSummary = completedTask.result_summary || {}
  const direct = normalizeMeshSessionIdentifier(resultSummary.session_id)
  if (direct) return direct
  const created = Array.isArray(resultSummary.created_session_ids)
    ? resultSummary.created_session_ids
      .map(normalizeMeshSessionIdentifier)
      .filter((item): item is string => Boolean(item))
    : []
  const selectedId = selected.value?.session.session_id || ''
  if (selectedId && created.includes(selectedId)) return selectedId
  if (created.length === 1) return created[0]
  if (created.length > 1) return null
  return normalizeMeshSessionIdentifier(selectedId)
}

function queuePendingTaskCompletion(completedTask: RailTransitTask): void {
  if (completedTask.status !== 'COMPLETED') return
  pendingCompletedTaskId = completedTask.task_id
  pendingAffectedSessionId = affectedSessionId(completedTask)
  if (
    pendingAffectedSessionId
    && selected.value?.session.session_id === pendingAffectedSessionId
    && ['mesh_schema_rebuild', 'mesh_source_rebuild', 'mesh_analysis_maintenance', 'mesh_identity_projection_refresh'].includes(completedTask.action)
  ) analysisResultUpdatePending.value = true
}

function identityRemapCompletionMessage(resultSummary: Record<string, unknown>): string {
  const remap = resultSummary.identity_remap
  if (!remap || typeof remap !== 'object' || Array.isArray(remap)) {
    return 'AP 身份映射已更新，当前分析结果已刷新'
  }
  const values = remap as Record<string, unknown>
  const mapped = Number(values.matched_mapping_count)
  const projected = Number(values.updated_link_row_count)
  if (
    'matched_mapping_count' in values
    && 'updated_link_row_count' in values
    && Number.isFinite(mapped)
    && Number.isFinite(projected)
  ) {
    return `${mapped} 个 Peer 已映射，${projected} 条链路身份投影已更新`
  }
  return 'AP 身份映射已更新，当前分析结果已刷新'
}

async function refreshAnalysisResults(options: {
  sessionId?: string | null
  notify?: boolean
} = {}): Promise<boolean> {
  const selectedAtStart = selected.value?.session.session_id || null
  const sessionId = normalizeMeshSessionIdentifier(options.sessionId ?? selectedAtStart)
  savePageScrollPosition()
  await refreshOverview(true, true)
  if (!sessionId || !selectedAtStart) {
    restorePageScrollPosition()
    return true
  }
  if (selected.value?.session.session_id !== selectedAtStart || selectedAtStart !== sessionId) {
    restorePageScrollPosition()
    return true
  }
  const refreshed = await requestMeshAnalysisSession(sessionId, {
    force: true,
    navigate: false,
    preserveView: true,
  })
  if (selected.value?.session.session_id === sessionId) {
    if (refreshed) {
      analysisResultUpdatePending.value = false
      analysisResultRefreshError.value = ''
      if (pendingAffectedSessionId === sessionId) pendingAffectedSessionId = null
      if (options.notify) ElMessage.success('AP 身份映射已更新，当前分析结果已刷新')
    } else {
      analysisResultUpdatePending.value = true
      pendingAffectedSessionId = sessionId
      analysisResultRefreshError.value = 'AP 身份映射已完成，但当前页面刷新失败，请点击“刷新结果”重试'
    }
  }
  restorePageScrollPosition()
  return refreshed
}

async function applyDeletedSessionsImmediately(sessionIds: string[]): Promise<void> {
  const deleted = new Set(sessionIds.map((value) => String(value || '').trim()).filter(Boolean))
  if (!deleted.size) return
  overviewGeneration += 1
  overviewAbortController?.abort()
  overviewAbortController = null
  loading.value = false
  const visibleDeletedCount = sessions.value.reduce(
    (count, row) => count + Number(deleted.has(row.session_id)),
    0,
  )
  sessions.value = sessions.value.filter((row) => !deleted.has(row.session_id))
  total.value = Math.max(0, total.value - visibleDeletedCount)
  if (summary.value) {
    const nextSummary = { ...summary.value, session_count: total.value }
    if (total.value === 0) {
      nextSummary.train_count = 0
      nextSummary.mr_count = 0
      nextSummary.link_record_count = 0
      nextSummary.active_link_count = 0
      nextSummary.standby_link_count = 0
      nextSummary.switch_event_count = 0
      nextSummary.short_link_count = 0
      nextSummary.pingpong_count = 0
      nextSummary.rssi_anomaly_count = 0
      nextSummary.channel_busy_anomaly_count = 0
      nextSummary.unmatched_ap_count = 0
      nextSummary.warning_session_count = 0
      nextSummary.latest_analysis_time = null
    }
    summary.value = nextSummary
  }
  selectedDeleteSessions.value = selectedDeleteSessions.value.filter((row) => !deleted.has(row.session_id))
  sourceDeleteTargets.value = sourceDeleteTargets.value.filter(({ session }) => !deleted.has(session.session_id))
  error.value = ''
  detailSectionError.value = ''
  if (selected.value && deleted.has(selected.value.session.session_id)) {
    await closeSelectedMeshSession()
  }
}

interface MeshBatchDeleteResultItem {
  session_id: string
  status: 'deleted' | 'parsed_deleted' | 'already_missing' | 'failed' | string
  success: boolean
  message?: string
  delete_raw_archive?: boolean
}

function meshBatchDeleteItems(resultSummary: Record<string, unknown>): MeshBatchDeleteResultItem[] {
  if (!Array.isArray(resultSummary.items)) return []
  return resultSummary.items.flatMap((value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return []
    const item = value as Record<string, unknown>
    const sessionId = normalizeMeshSessionIdentifier(item.session_id)
    if (!sessionId) return []
    return [{
      session_id: sessionId,
      status: String(item.status || ''),
      success: item.success === true,
      message: typeof item.message === 'string' ? item.message : undefined,
      delete_raw_archive: typeof item.delete_raw_archive === 'boolean' ? item.delete_raw_archive : undefined,
    }]
  })
}

async function handleBatchDeleteCompletion(completedTask: RailTransitTask): Promise<void> {
  const resultSummary = completedTask.result_summary || {}
  const items = meshBatchDeleteItems(resultSummary)
  const deleteRawArchive = resultSummary.delete_raw_archive === true
  const rawDeleted = items.filter((item) => (
    item.success
    && (item.delete_raw_archive ?? deleteRawArchive)
    && ['deleted', 'already_missing'].includes(item.status)
  )).map((item) => item.session_id)
  const parsedOnly = items.filter((item) => (
    item.success
    && !(item.delete_raw_archive ?? deleteRawArchive)
    && ['parsed_deleted', 'already_missing'].includes(item.status)
  ))
  const failed = items.filter((item) => !item.success || item.status === 'failed')

  await refreshOverview(true, true)
  if (rawDeleted.length) await applyDeletedSessionsImmediately(rawDeleted)
  const selectedId = selected.value?.session.session_id || ''
  if (selectedId && parsedOnly.some((item) => item.session_id === selectedId)) {
    await requestMeshAnalysisSession(selectedId, { force: true, preserveView: true })
  }
  if (failed.length) {
    const firstMessage = failed.find((item) => item.message)?.message
    ElMessage.warning(`MESH 来源批量删除完成，${failed.length} 个来源未处理${firstMessage ? `：${firstMessage}` : ''}`)
  } else if (items.length) {
    ElMessage.success(`MESH 来源批量删除完成，共处理 ${items.length} 个来源`)
  }
}

async function afterTask(): Promise<void> {
  const completedTask = task.value
  if (!completedTask || !terminalStates.has(completedTask.status)) return
  if (!pageActive.value) {
    queuePendingTaskCompletion(completedTask)
    return
  }
  if (processedTerminalTaskIds.has(completedTask.task_id)) return
  processedTerminalTaskIds.add(completedTask.task_id)
  if (pendingCompletedTaskId === completedTask.task_id) pendingCompletedTaskId = null
  if (completedTask.action === 'mesh_analysis_sources_delete') {
    await handleBatchDeleteCompletion(completedTask)
    return
  }
  if (completedTask.status !== 'COMPLETED') {
    if (['mesh_local_scan', 'mesh_local_scan_import', 'mesh_derived_data_repair'].includes(completedTask.action)) {
      localScanImporting.value = false
      const scanId = String(completedTask.result_summary?.scan_id || localScanId.value || '')
      if (scanId) await loadLocalScanResult(scanId)
    }
    if (completedTask.action === 'mesh_analysis_source_delete') await refreshOverview(true, true)
    return
  }
  const resultSummary = completedTask.result_summary || {}
  if (completedTask.action === 'mesh_local_scan') {
    const scanId = String(resultSummary.scan_id || localScanId.value || '')
    if (scanId) {
      localScanVisible.value = true
      await loadLocalScanResult(scanId)
    }
    return
  }
  if (completedTask.action === 'mesh_local_scan_import') {
    localScanImporting.value = false
    const scanId = String(resultSummary.scan_id || localScanId.value || '')
    if (scanId) await loadLocalScanResult(scanId)
  }
  if (completedTask.action === 'mesh_derived_data_repair') {
    localScanImporting.value = false
    if (localScanId.value) await loadLocalScanResult(localScanId.value)
    await refreshOverview(true, true)
    scheduleCatalogRefresh()
    await loadProfiles()
    return
  }
  if (completedTask.action === 'mesh_analysis_source_delete') {
    await refreshOverview(true, true)
    const deletedSessionId = String(resultSummary.session_id || '')
    if (selected.value?.session.session_id === deletedSessionId) {
      if (resultSummary.delete_raw_archive === true) {
        await closeSelectedMeshSession()
      } else {
        await requestMeshAnalysisSession(deletedSessionId, { force: true })
      }
    }
    return
  }
  if (['mesh_schema_rebuild', 'mesh_source_rebuild', 'mesh_analysis_maintenance', 'mesh_identity_projection_refresh'].includes(completedTask.action)) {
    const affectedId = affectedSessionId(completedTask)
    if (affectedId && selected.value?.session.session_id === affectedId) {
      pendingAffectedSessionId = affectedId
      analysisResultUpdatePending.value = true
      const refreshed = await refreshAnalysisResults({ sessionId: affectedId })
      if (refreshed) ElMessage.success(identityRemapCompletionMessage(resultSummary))
    } else {
      await refreshOverview(true, true)
    }
    scheduleCatalogRefresh()
    await loadProfiles()
    return
  }
  await refreshOverview(true, true)
  if (['mesh_log_import', 'mesh_bundle_import', 'mesh_local_scan_import'].includes(completedTask.action)) {
    scheduleCatalogRefresh()
    await loadProfiles()
  }
  const created = Array.isArray(resultSummary.created_session_ids)
    ? resultSummary.created_session_ids.filter((item): item is string => typeof item === 'string')
    : []
  const targetId = created[0]
  if (targetId) {
    await requestMeshAnalysisSession(targetId)
    activeTab.value = 'build-order'
    requestAnimationFrame(() => document.querySelector('.detail-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    return
  }
  if (selected.value) {
    const selectedId = selected.value.session.session_id
    artifacts.value = await listMeshArtifacts(selectedId)
  }
}
function pollTask(): void {
  stopTaskPolling()
  if (!pageActive.value) return
  if (!task.value || terminalStates.has(task.value.status)) { void afterTask(); return }
  taskTimer = setTimeout(async () => {
    try {
      const updated = await getRailTransitTask(task.value!.task_id)
      rememberTask(updated)
      if (!pageActive.value && terminalStates.has(updated.status)) {
        queuePendingTaskCompletion(updated)
        return
      }
      pollTask()
    }
    catch (reason) { error.value = reason instanceof Error ? reason.message : 'MESH 任务状态读取失败' }
  }, 1000)
}
async function startTask(factory: () => Promise<RailTransitTask>, fallback: string): Promise<RailTransitTask | null> {
  taskLoading.value = true; error.value = ''
  try {
    const created = await factory()
    rememberTask(created); pollTask(); void openTaskWindow(created.task_id)
    return created
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : fallback
    return null
  }
  finally { taskLoading.value = false }
}

async function deleteArtifact(artifact: MeshArtifact): Promise<void> {
  if (!selected.value || !artifact.deletable) return
  const accepted = await confirm({
    type: 'DESTRUCTIVE',
    title: '删除分析报告',
    message: `确认删除该分析报告？\n\n文件：${artifact.name}\n\n删除后不可恢复；原始导入日志不会删除。`,
    confirmText: '确认删除',
  })
  if (!accepted) return
  try {
    await deleteMeshArtifact(selected.value.session.session_id, artifact.artifact_id)
    artifacts.value = await listMeshArtifacts(selected.value.session.session_id)
    ElMessage.success('分析报告已删除，原始导入日志已保留')
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '分析报告删除失败')
  }
}

async function prepareSourceDelete(rows: MeshAnalysisSession[]): Promise<void> {
  const unique = [...new Map(rows.map((row) => [row.session_id, row])).values()]
  if (!unique.length || sourceDeleteSubmitting.value) return
  sourceDeleteSubmitting.value = true
  try {
    const details = await Promise.all(unique.map(async (session) => {
      const current = selected.value?.session.session_id === session.session_id
        ? selected.value
        : await getMeshAnalysisSession(session.session_id)
      const source = current?.sources[0]
      if (!source) throw new Error(`来源“${session.original_filename}”缺少可删除的归档记录`)
      return { session, source }
    }))
    sourceDeleteTargets.value = details
    sourceDeleteMode.value = 'parsed'
    sourceDeleteVisible.value = true
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : 'MESH 来源删除范围加载失败')
  } finally {
    sourceDeleteSubmitting.value = false
  }
}

async function confirmSourceDelete(): Promise<void> {
  if (!sourceDeleteTargets.value.length || sourceDeleteSubmitting.value) return
  const deleteRawArchive = sourceDeleteMode.value === 'all'
  const names = sourceDeleteTargets.value.map(({ session }) => session.original_filename).join('、')
  const accepted = await confirm({
    type: 'DESTRUCTIVE',
    title: deleteRawArchive ? '确认删除归档及全部分析结果' : '确认仅删除解析结果',
    message: deleteRawArchive
      ? `将删除 ${sourceDeleteTargets.value.length} 个 NetConsole 归档来源、解析数据库、映射缓存和关联报告。\n\n${names}\n\n不会删除用户最初选择的外部文件；完成后同一日志可重新导入。`
      : `将删除 ${sourceDeleteTargets.value.length} 个来源的解析数据库和映射缓存，归档原始日志保持不变。\n\n${names}\n\n完成后可直接重新解析。`,
    confirmText: deleteRawArchive ? '确认全部删除' : '确认删除解析结果',
  })
  if (!accepted) return
  sourceDeleteSubmitting.value = true
  try {
    const sessionIds = sourceDeleteTargets.value.map(({ session }) => session.session_id)
    const created = await batchDeleteMeshSources(
      sessionIds,
      {
        deleteRawArchive,
        deleteParsedData: true,
        deleteGeneratedReports: true,
      },
    )
    sourceDeleteVisible.value = false
    selectedDeleteSessions.value = []
    sourceDeleteTargets.value = []
    rememberTask(created)
    pollTask()
    void openTaskWindow(created.task_id)
    ElMessage.success(`已提交 1 个 MESH 来源批量删除任务，共 ${sessionIds.length} 个来源`)
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : 'MESH 来源删除任务提交失败')
  } finally {
    sourceDeleteSubmitting.value = false
  }
}

async function closeSelectedMeshSession(): Promise<void> {
  cancelDeferredRssiChartWork()
  cancelInFlightRssiChartRequests()
  activeSessionOpenController?.abort()
  activeSessionOpenController = null
  activeSessionOpenId = null
  activeSessionOpenPromise = null
  pendingRequestedSessionId.value = null
  detailLoading.value = false
  setMeshDetailRequestActive(meshRuntimeToken, false)
  rssiActiveAbortController?.abort()
  rssiActiveAbortController = null
  detailGeneration += 1
  releaseTracksideResources()
  selected.value = null
  buildOrders.value = []
  buildOrderVisits.value = []
  buildOrderTotal.value = 0
  links.value = []
  linkTotal.value = 0
  switches.value = []
  switchTotal.value = 0
  switchFilters.page = 1
  rssiActivePath.value = null
  rssiActiveLoading.value = false
  rssiActiveLoaded.value = false
  rssiActiveLoadedKey = ''
  rssiActivePaintReady.value = false
  rssiActivePeerLoaded.value = false
  rssiActiveError.value = ''
  rssiViewport.value = null
  committedRssiViewport.value = null
  pendingRssiQueryViewport.value = null
  rssiViewportInteracting.value = false
  busyActivePath.value = null
  busyPeerPath.value = null
  artifacts.value = []
  rawTail.value = null
  const currentRoute = router.currentRoute?.value
  if (currentRoute?.query.session_id) {
    const query = { ...currentRoute.query }
    delete query.session_id
    await router.replace({ name: 'mesh-analysis', query })
  }
  requestWorkspaceTabTitle('MR 原始 MESH 日志分析')
}
async function startBundleImport(): Promise<void> {
  if (!bundlePreview.value || !bundleCanApply.value) return
  const payload: MeshBundleImportRequest = {
    preview_id: bundlePreview.value.preview_id,
    mappings: bundlePreview.value.items.map((item) => {
      const { confirmed: _confirmed, ...mapping } = bundleMappings[item.member_id]
      return { ...mapping, role: mapping.role as 'CT' | 'CW' }
    }),
    explicit_confirmation: true,
  }
  const created = await startTask(() => applyMeshBundleImport(payload), 'MESH ZIP 导入启动失败')
  if (!created) return
  clearImportSelection()
  importVisible.value = false
}
function assignAnalysisParams(target: MeshAnalysisParams, value: MeshAnalysisParams): void {
  Object.assign(target, value)
}

async function hydrateSiteAnalysisParams(target: MeshAnalysisParams): Promise<void> {
  assignAnalysisParams(target, await getMeshAnalysisParams())
}

async function applyAnalysisTemplate(target: MeshAnalysisParams, serviceType: string): Promise<void> {
  try {
    assignAnalysisParams(target, await getMeshAnalysisParamsTemplate(serviceType))
    ElMessage.success(`${serviceType} 参数模板已载入`)
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '参数模板加载失败')
  }
}

async function saveSiteAnalysisParams(target: MeshAnalysisParams): Promise<void> {
  try {
    const saved = await saveMeshAnalysisParams({ ...target })
    assignAnalysisParams(target, saved)
    if (selected.value) assignAnalysisParams(selected.value.analysis_params, saved)
    ElMessage.success('已保存为当前局点默认参数')
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '局点参数保存失败')
  }
}

async function openReportDialog(): Promise<void> {
  if (!selected.value) return
  try {
    await hydrateSiteAnalysisParams(reportParams)
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '局点默认参数加载失败')
    return
  }
  useTemporaryReportParams.value = false
  reportVisible.value = true
}

async function generateReport(): Promise<void> {
  if (!selected.value) return
  const sessionId = selected.value.session.session_id
  const suggestedName = `${safeExportPart(selected.value.session.mr_name || 'MESH')}-分析报告-${exportTimestamp()}.xlsx`
  const override = useTemporaryReportParams.value ? { ...reportParams } : undefined
  taskLoading.value = true
  error.value = ''
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.mesh_report',
      suggestedName,
      context: { sessionId },
      submit: () => exportMeshAnalysisReport(sessionId, override),
    })
    if (result.status === 'cancelled') return
    reportVisible.value = false
    rememberTask(result.task)
    pollTask()
    void openTaskWindow(result.task.task_id)
    ElMessage.success('MESH 分析报告任务已提交，完成后将写入所选位置')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'MESH 分析报告生成启动失败'
  } finally {
    taskLoading.value = false
  }
}
async function openLinkExportDialog(): Promise<void> {
  if (!selected.value) return
  try {
    await hydrateSiteAnalysisParams(linkExportParams)
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '局点默认参数加载失败')
    return
  }
  linkExportVisible.value = true
}

async function exportLinkDetails(): Promise<void> {
  const sourceFileId = selectedSource.value?.source_file_id
  if (!selected.value || typeof sourceFileId !== 'number' || !Number.isInteger(sourceFileId) || sourceFileId <= 0) {
    ElMessage.error('当前来源缺少正式 source_file_id，请刷新或重新解析后再试。')
    return
  }
  const sessionId = selected.value.session.session_id
  const suggestedName = `${safeExportPart(selected.value.session.mr_name || 'MESH')}-链路明细-${exportTimestamp()}.xlsx`
  taskLoading.value = true
  error.value = ''
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.mesh_link_details',
      suggestedName,
      context: { sessionId, sourceFileId },
      submit: () => exportMeshLinkDetails(sessionId, sourceFileId, { ...linkExportParams }),
    })
    if (result.status === 'cancelled') return
    linkExportVisible.value = false
    rememberTask(result.task)
    pollTask()
    void openTaskWindow(result.task.task_id)
    ElMessage.success('链路明细导出任务已提交，完成后将写入所选位置')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'MESH 链路明细导出启动失败'
  } finally {
    taskLoading.value = false
  }
}

async function openApCoverageAudit(): Promise<void> {
  if (selectedDeleteSessions.value.length !== 2) {
    ElMessage.warning('请选择两个 MESH 来源进行 AP 覆盖核查。')
    return
  }
  apCoverageLoading.value = true
  apCoverage.value = null
  try {
    apCoverage.value = await auditMeshApCoverage(selectedDeleteSessions.value.map((item) => item.session_id))
    apCoverageVisible.value = true
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : 'AP 覆盖核查失败')
  } finally {
    apCoverageLoading.value = false
  }
}

async function exportApCoverageAudit(): Promise<void> {
  if (selectedDeleteSessions.value.length !== 2) return
  const suggestedName = `MESH-AP覆盖核查-${exportTimestamp()}.xlsx`
  taskLoading.value = true
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.mesh_ap_coverage',
      suggestedName,
      context: { sourceA: selectedDeleteSessions.value[0].session_id, sourceB: selectedDeleteSessions.value[1].session_id },
      submit: () => exportMeshApCoverage(selectedDeleteSessions.value.map((item) => item.session_id)),
    })
    if (result.status === 'cancelled') return
    rememberTask(result.task)
    pollTask()
    void openTaskWindow(result.task.task_id)
    ElMessage.success('AP 覆盖核查导出任务已提交，完成后将写入所选位置')
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : 'AP 覆盖核查导出启动失败')
  } finally {
    taskLoading.value = false
  }
}
async function rebuildSelected(): Promise<void> {
  if (!selected.value) return
  const accepted = await confirm({
    type: 'WARNING',
    title: '重建 MESH 解析结果',
    message: selectedSource.value?.rebuild_capability === 'recoverable_from_bundle'
      ? '当前原始日志将从受保护 ZIP 归档恢复，并仅重新解析当前来源；同 MR 其他日志不会变化。确认继续？'
      : '将仅从当前原始日志重新生成本来源的结构化结果；同 MR 其他日志不会变化。确认继续？',
    confirmText: '确认重建',
  })
  if (!accepted) return
  void startTask(() => rebuildMeshAnalysis(selected.value!.session.session_id), 'MESH 派生数据库重建启动失败')
}

async function openSelectedSourceLocation(): Promise<void> {
  if (!selected.value || !selectedSource.value) return
  const result = await getPlatformAdapter().openMeshAnalysisSessionLocation(
    selected.value.session.session_id,
  )
  if (!result.success) {
    ElMessage.warning(result.error || '当前原始日志没有可打开的本地目录')
    return
  }
  if (!selectedSource.value.exists) {
    ElMessage.warning('原始日志文件已不存在，已打开其所在目录。')
    return
  }
  ElMessage.success('已在本地目录中定位当前原始日志')
}
async function recoverTask(): Promise<void> {
  try {
    const saved = localStorage.getItem(taskStorageKey) || ''
    const rows = await recoverRailTransitTasks()
    const meshRows = rows.filter((item) => ['mesh_log_import', 'mesh_bundle_import', 'mesh_local_scan', 'mesh_local_scan_import', 'mesh_schema_rebuild', 'mesh_source_rebuild', 'mesh_analysis_maintenance', 'mesh_identity_projection_refresh', 'mesh_analysis_source_delete', 'mesh_analysis_sources_delete', 'mesh_analysis_report', 'mesh_link_detail_export'].includes(item.action))
    const savedTask = meshRows.find((item) => item.task_id === saved && restorableTaskStates.has(item.status))
    rememberTask(savedTask || meshRows.find((item) => restorableTaskStates.has(item.status)) || null)
    pollTask()
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'MESH 任务恢复失败' }
}
async function openTaskWindow(taskId = task.value?.task_id || ''): Promise<void> {
  if (window.netconsoleDesktop) {
    try {
      const result = await window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
      if (result.success) return
      ElMessage.error(result.error || '任务中心加载失败')
    } catch {
      ElMessage.error('任务中心加载失败')
    }
    await router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
    return
  }
  await router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}

function refreshDetailPanels(): void {
  if (!pageActive.value) return
  void nextTick(() => {
    if (!pageActive.value) return
    buildOrderPanel.refresh()
    linkPanel.refresh()
    switchPanel.refresh()
    rssiPanel.refresh()
    busyPanel.refresh()
  })
}

function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function formatBytes(value: number): string { if (!value) return '0 B'; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 ** 2).toFixed(1)} MB` }
function severityType(value: string): 'error' | 'warning' | 'info' { return value === 'error' || value === 'critical' ? 'error' : value === 'warning' ? 'warning' : 'info' }

async function loadParseIssues(page = 1): Promise<void> {
  if (!selected.value) return
  parseIssuesLoading.value = true
  try {
    const result = await listMeshParseIssues(selected.value.session.session_id, { page, page_size: parseIssuesPageSize })
    parseIssues.value = result.items
    parseIssuesTotal.value = result.total
    parseIssuesPage.value = result.page
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '解析异常明细加载失败')
  } finally {
    parseIssuesLoading.value = false
  }
}

function openParseIssues(): void {
  parseIssuesVisible.value = true
  void loadParseIssues(1)
}
function buildOrderRowClass(params: { row: MeshActiveBuildOrder }): string { return selectedSegment.value?.anchor_link_id === params.row.anchor_link_id ? 'mesh-build-selected' : '' }
function linkRowClass(params: { row: MeshLinkDetail }): string { return `${linkTimeGroups.value.get(params.row) || ''} ${params.row.link_role === 'ACTIVE' ? 'mesh-row-active' : ''}`.trim() }
function switchRowClass(params: { row: MeshSwitchEvent }): string { return switchTimeGroups.value.get(params.row) || '' }
function roleClass(value: string): string { return value === 'ACTIVE' ? 'mesh-role-active' : value === 'STANDBY' ? 'mesh-role-standby' : '' }
function buildResultType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'normal') return 'success'
  if (value === 'short' || value.includes('critical')) return 'warning'
  if (value.includes('pingpong') || value.includes('abnormal')) return 'danger'
  return 'info'
}
function buildResultLabel(value: string): string {
  return ({ stable: '稳定主链（非切换）', normal: '正常切换', short: '短时建链', same_ap_radio_switch: '同 AP 双射频切换', pingpong_abnormal: 'AP 乒乓切换异常', critical_return: '临界回切', boundary: '边界区段' } as Record<string, string>)[value] || value
}
function safeExportPart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || 'MESH'
}
function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}
</script>

<template>
  <section
    class="mesh-page"
    :class="{
      'is-rssi-workspace': isRssiWorkspaceMode,
      'is-rssi-immersive': rssiImmersive,
    }"
  >
    <header class="page-heading">
      <div class="page-heading__copy">
        <p class="eyebrow">RAIL TRANSIT · OFFLINE MESH ANALYSIS</p>
        <h1>{{ isRssiWorkspaceMode ? 'MR 原始 MESH 日志分析' : 'Mesh 原始日志分析' }}</h1>
        <p class="page-heading__description">选择日志后自动匹配当前局点车载 MR，并完成归档、解析、分析和报告交付。</p>
        <p v-if="isRssiWorkspaceMode && selected" class="page-heading__current-log">
          当前日志：{{ selected.session.mr_name }} · Radio {{ chartRadio ?? '全部' }} · {{ selected.session.original_filename }}
        </p>
      </div>
      <div class="jump-actions"><el-button :loading="importContextLoading" :disabled="!isFeatureEnabled('capability.mesh.import')" @click="openImportDialog">导入原始 MESH 日志</el-button><el-button :loading="localScanLoading" :disabled="!isFeatureEnabled('capability.mesh.import')" @click="scanLocalLogs">扫描本地日志</el-button><el-button v-if="localScanResult" @click="localScanVisible = true">查看扫描结果</el-button><el-button :icon="Download" :loading="taskLoading" :disabled="!selected || !selectedSource || selected.session.parsed_status !== 'ready' || !isFeatureEnabled('capability.mesh.report_export')" @click="openLinkExportDialog">导出链路明细</el-button><el-button :icon="Document" type="primary" :loading="taskLoading" :disabled="!selected || ['missing','unreadable'].includes(selected.session.parsed_status) || !isFeatureEnabled('capability.mesh.report_export')" @click="openReportDialog">生成分析报告</el-button><el-button :loading="loading || detailLoading" @click="refreshAnalysisResults()">刷新结果</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <el-dialog v-model="parseIssuesVisible" title="解析异常明细" width="min(1100px, 94vw)" :close-on-click-modal="false">
      <NcDataTable v-loading="parseIssuesLoading" table-id="mesh-analysis-parse-issues:v1" route-key="/rail-transit/mesh-analysis" :data="parseIssues" :columns="parseIssueColumns" border height="520" empty-text="暂无解析异常" />
      <div class="pagination"><span>共 {{ parseIssuesTotal }} 条</span><el-pagination :current-page="parseIssuesPage" :page-size="parseIssuesPageSize" layout="prev, pager, next" :total="parseIssuesTotal" @current-change="loadParseIssues" /></div>
    </el-dialog>
    <el-dialog v-model="localScanVisible" title="扫描本地 MESH 日志" width="min(1280px, 96vw)" :close-on-click-modal="false">
      <el-alert v-if="localScanError" :title="localScanError" type="error" :closable="false" show-icon />
      <el-alert v-if="!localScanResult" title="扫描任务完成后将在此显示当前局点 raw 目录中的新增日志。" type="info" :closable="false" show-icon />
      <template v-if="localScanResult">
        <div class="jump-actions local-scan-stats">
          <el-tag effect="plain">发现 {{ localScanResult.stats.found_count }}</el-tag>
          <el-tag type="warning" effect="plain">未导入 {{ localScanResult.stats.unregistered_count }}</el-tag>
          <el-tag type="success" effect="plain">已导入 {{ localScanResult.stats.imported_count }}</el-tag>
          <el-tag type="info" effect="plain">重复 {{ localScanResult.stats.duplicate_count }}</el-tag>
          <el-tag type="danger" effect="plain">无效 {{ localScanResult.stats.invalid_count }}</el-tag>
          <el-tag effect="plain">待补充 {{ localScanResult.stats.needs_metadata_count }}</el-tag>
          <el-tag v-if="localScanResult.stats.waiting_repair_count" type="warning" effect="plain">等待升级 {{ localScanResult.stats.waiting_repair_count }}</el-tag>
          <el-tag v-if="localScanResult.stats.repairing_count" type="warning" effect="plain">正在修复 {{ localScanResult.stats.repairing_count }}</el-tag>
        </div>
        <div class="jump-actions local-scan-toolbar">
          <el-button @click="selectAllLocalScanCandidates">导入全部未登记文件</el-button>
          <el-button :disabled="!localScanSelected.length" @click="ignoreSelectedLocalScan">忽略选中</el-button>
          <span>已选择 {{ localScanSelected.length }} 个文件</span>
        </div>
        <div class="bundle-table-wrap local-scan-table-wrap">
          <table class="bundle-table"><thead><tr><th>选择</th><th>文件</th><th>指纹 / 修改时间</th><th>列车 / MR</th><th>状态</th><th>操作</th></tr></thead><tbody>
            <tr v-for="candidate in localScanCandidates" :key="candidate.candidate_id">
              <td><el-checkbox :model-value="localScanSelected.includes(candidate.candidate_id)" :disabled="!['unregistered', 'needs_metadata', 'failed', 'parse_failed', 'repair_failed'].includes(candidate.scan_status)" @change="(value: string | number | boolean) => toggleLocalScanCandidate(candidate, Boolean(value))" /></td>
              <td><strong>{{ candidate.file_name }}</strong><small>{{ candidate.relative_path }} · {{ candidate.file_size }} B</small></td>
              <td><code>{{ candidate.sha256.slice(0, 16) }}…</code><small>{{ candidate.modified_at }}</small></td>
              <td>
                <el-select v-model="localScanMappings[candidate.candidate_id]" clearable filterable placeholder="选择 MR" :disabled="!['unregistered', 'needs_metadata', 'failed', 'parse_failed', 'repair_failed'].includes(candidate.scan_status)">
                  <el-option v-for="profile in localScanResult.profiles" :key="profile.profile_id" :label="profile.display_name" :value="profile.profile_id" />
                </el-select>
                <small>{{ candidate.train_no ? `列车${candidate.train_no}` : '列车待识别' }} · {{ candidate.mr_role || '角色待识别' }}</small>
              </td>
              <td><el-tag :type="['invalid', 'failed', 'parse_failed', 'repair_failed'].includes(candidate.scan_status) ? 'danger' : candidate.scan_status === 'imported' ? 'success' : 'info'">{{ localScanStatusText(candidate.scan_status) }}</el-tag><small v-if="candidate.error_message">{{ candidate.error_message }}</small></td>
              <td><el-button link type="primary" @click="openLocalScanDirectory(candidate)">打开所在目录</el-button></td>
            </tr>
          </tbody></table>
        </div>
      </template>
      <template #footer><el-button @click="localScanVisible = false">关闭</el-button><el-button type="primary" :loading="localScanImporting" :disabled="!localScanCanImport" @click="importSelectedLocalScan">导入选中</el-button></template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="MESH 原始日志导入" width="min(1180px, 96vw)">
      <el-form label-position="top">
        <div v-if="importContextError" class="jump-actions import-context-retry">
          <el-alert :title="`导入上下文准备失败：${importContextError}`" type="error" :closable="false" show-icon />
          <el-button :loading="importContextLoading" @click="prepareImportContext">重新准备导入上下文</el-button>
        </div>
        <el-alert v-for="warning in importContextWarnings" :key="warning" :title="warning" type="warning" :closable="false" show-icon />
        <el-alert v-if="profileLoadError" :title="`内部 MESH 归属加载失败：${profileLoadError}`" type="error" :closable="false" show-icon />
        <el-alert v-if="vehicleMrLoadError" :title="`车载 MR 加载失败：${vehicleMrLoadError}`" type="error" :closable="false" show-icon />
        <el-alert v-if="!importContextLoading && !vehicleMrLoadError && baseMrs.length === 0" title="当前局点没有可识别的车载 MR，请先在设备管理的“车载-MR”分组登记设备。" type="warning" :closable="false" show-icon />
        <el-form-item label="选择原始日志或 ZIP">
          <div class="jump-actions"><el-button @click="fileInput?.click()">选择 ZIP / LOG / GZ 文件</el-button><el-button @click="folderInput?.click()">选择文件夹</el-button><span>已选择 {{ selectedFiles.length }} 个文件</span></div>
          <input ref="fileInput" class="hidden-input" type="file" multiple accept=".zip,.log,.txt,.gz" @change="chooseFiles"><input ref="folderInput" class="hidden-input" type="file" multiple webkitdirectory @change="chooseFiles">
        </el-form-item>
        <div v-if="selectedFiles.length && !bundlePreview" class="bundle-table-wrap">
          <table class="bundle-table"><thead><tr><th>待预览文件</th><th>大小</th><th>状态</th></tr></thead><tbody>
            <tr v-for="file in selectedFiles" :key="`${file.name}:${file.size}:${file.lastModified}`"><td>{{ file.name }}</td><td>{{ file.size }} B</td><td>{{ importPreviewStage }}</td></tr>
          </tbody></table>
          <el-button v-if="bundlePreviewLoading" size="small" @click="cancelImportPreview">取消预览</el-button>
        </div>
        <div v-if="importPreviewError" class="jump-actions import-context-retry">
          <el-alert :title="`日志预览失败：${importPreviewError}`" type="error" :closable="false" show-icon />
          <el-button :icon="Refresh" :loading="bundlePreviewLoading" :disabled="selectedFiles.length === 0" @click="previewImportFiles">重新预览</el-button>
        </div>
        <el-alert v-if="bundlePreviewLoading" :title="`${importPreviewStage}；正在识别日志并匹配当前局点车载 MR…`" type="info" :closable="false" show-icon />
        <template v-if="bundlePreview">
          <el-divider content-position="left">日志自动映射</el-divider>
          <el-form-item label="批量归属到车载 MR">
            <el-select v-model="batchLinkedMrId" filterable clearable placeholder="选择一次，自动应用列车号、端位和内部归属" @change="applyBatchMrMapping">
              <el-option v-for="mr in baseMrs" :key="mr.id" :label="vehicleMrOptionLabel(mr)" :value="mr.id" />
            </el-select>
          </el-form-item>
          <el-alert :title="bundleValidationMessage" :type="bundleCanApply ? 'success' : 'warning'" :closable="false" show-icon />
          <div class="bundle-table-wrap">
            <table class="bundle-table"><thead><tr><th>原始文件 / 内容指纹</th><th>首条日志时间</th><th>预计归档文件名</th><th>自动映射</th><th>重复状态</th></tr></thead><tbody>
              <tr v-for="(item, itemIndex) in bundlePreview.items" :key="item.member_id">
                <td><strong>{{ item.original_name }}</strong><small v-if="item.original_relative_path">{{ item.original_relative_path }}</small><small>成员 {{ itemIndex + 1 }} · {{ item.member_id.slice(-8) }} · {{ item.size_bytes }} B · {{ (item.content_sha256 || item.sha256).slice(0, 12) }}…</small></td>
                <td>{{ item.first_log_timestamp || '未识别' }}<small>{{ item.log_date || 'unknown_date' }}</small></td>
                <td><strong>{{ previewStoredFilename(item) }}</strong><small v-if="previewImportState(item)?.rename_warning || item.rename_warning">{{ previewImportState(item)?.rename_warning || item.rename_warning }}</small></td>
                <td>{{ bundleMappings[item.member_id]?.train_number || '—' }} · {{ bundleMappings[item.member_id]?.role || '—' }}<small>{{ profiles.find((profile) => profile.mr_id === bundleMappings[item.member_id]?.profile_id)?.display_name || '未选择 MR' }}</small></td>
                <td><el-tag :type="previewDuplicateLabel(item) === '新日志' ? 'success' : previewDuplicateLabel(item) === '内容属于其他 MR' ? 'danger' : 'warning'">{{ previewDuplicateLabel(item) }}</el-tag><small v-if="previewImportState(item)?.existing_stored_filename">已有：{{ previewImportState(item)?.existing_stored_filename }} · {{ previewImportState(item)?.existing_profile_name }}</small></td>
              </tr>
            </tbody></table>
            <p class="hint">预计归档文件名可能因并发导入在正式保存时自动顺延。</p>
          </div>
          <el-checkbox v-model="batchMappingConfirmed">我已核对以上文件的列车号、端位和车载 MR 归属</el-checkbox>
          <el-collapse>
            <el-collapse-item title="高级：逐文件修正映射" name="advanced-mapping">
              <div v-for="item in bundlePreview.items" :key="`mapping-${item.member_id}`" class="profile-grid">
                <el-form-item :label="`${item.original_name} · 列车号`"><el-input v-model="bundleMappings[item.member_id].train_number" @input="batchMappingConfirmed = false" /></el-form-item>
                <el-form-item label="端位"><el-select v-model="bundleMappings[item.member_id].role" @change="batchMappingConfirmed = false"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select></el-form-item>
                <el-form-item label="对应车载 MR"><el-select v-model="bundleMappings[item.member_id].profile_id" filterable @change="batchMappingConfirmed = false"><el-option v-for="candidate in profileCandidates(item)" :key="candidate.profile_id" :label="candidate.display_name" :value="candidate.profile_id" /></el-select></el-form-item>
              </div>
            </el-collapse-item>
          </el-collapse>
        </template>
        <el-collapse><el-collapse-item title="高级：无法匹配时创建内部归属" name="advanced-profile"><div class="profile-grid"><el-form-item label="显示名称"><el-input v-model="newProfileName" placeholder="例如：列车01-MR-CT" @input="markProfileNameEdited" /></el-form-item><el-form-item label="关联基础资料 MR（可选）"><el-select v-model="linkedMrId" clearable filterable><el-option v-for="mr in baseMrs" :key="mr.id" :label="vehicleMrOptionLabel(mr)" :value="mr.id" /></el-select></el-form-item><el-form-item label="备注"><el-input v-model="profileNotes" /></el-form-item></div><el-button :loading="taskLoading" :disabled="!newProfileName.trim()" @click="createProfile">创建内部归属</el-button></el-collapse-item></el-collapse>
      </el-form>
      <template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :loading="taskLoading" :disabled="!bundleCanApply" @click="startBundleImport">{{ bundleSubmitLabel }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="reportVisible" title="生成 MESH 分析报告" width="min(720px, 94vw)">
      <el-form label-position="top">
        <el-form-item><el-checkbox v-model="useTemporaryReportParams">本次报告使用临时分析参数</el-checkbox></el-form-item>
        <template v-if="useTemporaryReportParams">
          <div class="report-params-grid">
            <el-form-item label="业务模板"><el-select :model-value="reportParams.service_type" @change="(value: string) => applyAnalysisTemplate(reportParams, value)"><el-option label="PIS" value="PIS" /><el-option label="CBTC（待现场标定）" value="CBTC" /></el-select></el-form-item>
            <el-form-item label="基准时间 (ms)"><el-input-number v-model="reportParams.link_time_window" :min="1" :max="600000" /></el-form-item>
            <el-form-item label="切换阈值 (RSSI)"><el-input-number v-model="reportParams.link_switch_threshold" :min="0" :max="200" /></el-form-item>
            <el-form-item label="维持链路阈值 (RSSI)"><el-input-number v-model="reportParams.link_hold_rssi" :min="0" :max="200" /></el-form-item>
            <el-form-item label="发现链路阈值 (RSSI)"><el-input-number v-model="reportParams.link_establish_threshold" :min="0" :max="200" /></el-form-item>
            <el-form-item label="乒乓容差 (ms)"><el-input-number v-model="reportParams.pingpong_tolerance_ms" :min="0" :max="600000" /></el-form-item>
            <el-form-item label="乒乓返回窗口 (ms)"><el-input-number v-model="reportParams.pingpong_return_window_ms" :min="1" :max="3600000" clearable /></el-form-item>
            <el-form-item label="无线类型"><el-select v-model="reportParams.wifi_type"><el-option label="WiFi 5" value="WiFi5" /><el-option label="WiFi 6" value="WiFi6" /><el-option label="其他" value="其他" /></el-select></el-form-item>
          </div>
          <el-checkbox v-model="reportParams.merge_same_physical_ap_dual_radio">合并同一物理 AP 双射频</el-checkbox>
          <el-checkbox v-model="reportParams.include_log_boundary_segments">包含日志边界区段</el-checkbox>
        </template>
      </el-form>
      <template #footer><el-button @click="reportVisible = false">取消</el-button><el-button @click="saveSiteAnalysisParams(reportParams)">保存为局点默认</el-button><el-button type="primary" :loading="taskLoading" @click="generateReport">开始生成</el-button></template>
    </el-dialog>

    <el-dialog v-model="linkExportVisible" title="导出链路明细：分析参数" width="min(720px, 94vw)">
      <div v-if="linkExportVisible">
      <el-form label-position="top">
        <el-alert title="链路明细与综合报告使用同一局点默认；本次导出会冻结当前参数快照。" type="info" :closable="false" show-icon />
        <div class="report-params-grid">
          <el-form-item label="业务模板"><el-select :model-value="linkExportParams.service_type" @change="(value: string) => applyAnalysisTemplate(linkExportParams, value)"><el-option label="PIS" value="PIS" /><el-option label="CBTC（待现场标定）" value="CBTC" /></el-select></el-form-item>
          <el-form-item label="基准时间 (ms)"><el-input-number v-model="linkExportParams.link_time_window" :min="1" :max="600000" /></el-form-item>
          <el-form-item label="切换阈值 (RSSI)"><el-input-number v-model="linkExportParams.link_switch_threshold" :min="0" :max="200" /></el-form-item>
          <el-form-item label="维持链路阈值 (RSSI)"><el-input-number v-model="linkExportParams.link_hold_rssi" :min="0" :max="200" /></el-form-item>
          <el-form-item label="发现链路阈值 (RSSI)"><el-input-number v-model="linkExportParams.link_establish_threshold" :min="0" :max="200" /></el-form-item>
          <el-form-item label="无线类型"><el-select v-model="linkExportParams.wifi_type"><el-option label="WiFi 5" value="WiFi5" /><el-option label="WiFi 6" value="WiFi6" /><el-option label="其他" value="其他" /></el-select></el-form-item>
        </div>
        <p class="hint">建链信号阈值 = {{ linkExportParams.link_hold_rssi + linkExportParams.link_establish_threshold }}；第一个主链路忽略信号阈值。</p>
      </el-form>
      </div>
      <template #footer><el-button @click="linkExportVisible = false">取消</el-button><el-button @click="saveSiteAnalysisParams(linkExportParams)">保存为局点默认</el-button><el-button type="primary" :loading="taskLoading" @click="exportLinkDetails">开始导出</el-button></template>
    </el-dialog>

    <el-dialog v-model="apCoverageVisible" title="AP 覆盖核查" width="min(1280px, 96vw)" top="4vh">
      <template v-if="apCoverage">
        <p class="hint">来源 A：{{ apCoverage.sources[0]?.mr_name }} · {{ apCoverage.sources[0]?.original_filename }} · Peer Radio {{ apCoverage.sources[0]?.distinct_peer_radio_count ?? 0 }} · 物理 AP {{ apCoverage.sources[0]?.distinct_canonical_ap_count ?? 0 }}<br>时间范围：{{ apCoverage.sources[0]?.first_sample_time || '—' }} — {{ apCoverage.sources[0]?.last_sample_time || '—' }}<br>来源 B：{{ apCoverage.sources[1]?.mr_name }} · {{ apCoverage.sources[1]?.original_filename }} · Peer Radio {{ apCoverage.sources[1]?.distinct_peer_radio_count ?? 0 }} · 物理 AP {{ apCoverage.sources[1]?.distinct_canonical_ap_count ?? 0 }}<br>时间范围：{{ apCoverage.sources[1]?.first_sample_time || '—' }} — {{ apCoverage.sources[1]?.last_sample_time || '—' }}</p>
        <el-alert :title="apCoverage.summary.route_scope_mode === 'observed_route' ? '默认按所选日志实际经过的正线范围统计；同时保留全正线口径。' : '未能从已观测 AP 形成可用经过范围，当前默认按全正线统计。'" type="info" :closable="false" show-icon />
        <p class="hint">Identity：scope {{ apCoverage.identity_summary.identity_scope }} · revision {{ apCoverage.identity_summary.identity_revision }} · 索引 {{ apCoverage.identity_summary.index_status }} · Peer Radio {{ apCoverage.identity_summary.mesh_distinct_peer_radio_count }} · 物理 AP {{ apCoverage.identity_summary.mesh_distinct_canonical_ap_count }} · 已持久化命中 {{ apCoverage.identity_summary.persisted_matched_count }} · fallback {{ apCoverage.identity_summary.fallback_matched_count }} / {{ apCoverage.identity_summary.fallback_requested_count }} · fallback 未匹配 {{ apCoverage.identity_summary.fallback_unmatched_count }}</p>
        <div class="summary-grid coverage-summary-grid">
          <article class="metric-card"><span>本次范围正线 FIT-AP</span><strong>{{ apCoverage.summary.expected_route_scope_count }}</strong></article>
          <article class="metric-card"><span>已连接</span><strong>{{ apCoverage.summary.connected_count }}</strong></article>
          <article class="metric-card"><span>未连接</span><strong>{{ apCoverage.summary.unconnected_count }}</strong></article>
          <article class="metric-card"><span>资料未匹配</span><strong>{{ apCoverage.summary.unmatched_observed_count }}</strong></article>
          <article class="metric-card"><span>已排除非正线</span><strong>{{ apCoverage.summary.excluded_count }}</strong></article>
          <article class="metric-card"><span>覆盖率</span><strong>{{ apCoverage.summary.coverage_percent.toFixed(2) }}%</strong></article>
        </div>
        <el-tabs>
          <el-tab-pane :label="`未连接 AP (${apCoverage.unconnected.length})`">
            <NcDataTable table-id="mesh-ap-coverage-unconnected:v1" route-key="/rail-transit/mesh-analysis" :data="apCoverage.unconnected" :columns="coverageColumns" row-key="physical_ap_mac" height="360" />
          </el-tab-pane>
          <el-tab-pane :label="`已连接 AP (${apCoverage.connected.length})`">
            <NcDataTable table-id="mesh-ap-coverage-connected:v1" route-key="/rail-transit/mesh-analysis" :data="apCoverage.connected" :columns="coverageColumns" row-key="physical_ap_mac" height="360" />
          </el-tab-pane>
          <el-tab-pane :label="`资料未匹配 (${apCoverage.unmatched.length})`">
            <NcDataTable table-id="mesh-ap-coverage-unmatched:v1" route-key="/rail-transit/mesh-analysis" :data="apCoverage.unmatched" :columns="coverageColumns" row-key="radio_mac" height="360" />
          </el-tab-pane>
          <el-tab-pane :label="`已排除 (${apCoverage.excluded.length})`">
            <NcDataTable table-id="mesh-ap-coverage-excluded:v1" route-key="/rail-transit/mesh-analysis" :data="apCoverage.excluded" :columns="coverageColumns" row-key="physical_ap_mac" height="360" />
          </el-tab-pane>
        </el-tabs>
      </template>
      <template #footer><el-button @click="apCoverageVisible = false">关闭</el-button><el-button type="primary" :loading="taskLoading" @click="exportApCoverageAudit">导出核查结果</el-button></template>
    </el-dialog>

    <el-dialog v-model="sourceDeleteVisible" title="删除 MESH 来源" width="min(760px, 94vw)" :close-on-click-modal="false">
      <div class="source-delete-list">
        <div v-for="target in sourceDeleteTargets" :key="target.session.session_id" class="source-delete-item">
          <strong>{{ target.session.original_filename }}</strong>
          <span>{{ target.session.train_name || '未知列车' }} · {{ target.session.mr_name }}</span>
          <span>归档大小 {{ formatBytes(target.source.size_bytes) }} · 解析记录 {{ display(target.session.link_record_count) }} · 报告 {{ target.session.report_count }}</span>
        </div>
      </div>
      <el-radio-group v-model="sourceDeleteMode" class="source-delete-options">
        <el-radio value="parsed">
          <span><strong>仅删除解析结果</strong><small>保留 NetConsole 归档原始日志，删除解析数据库、映射和缓存，随后可重新解析。</small></span>
        </el-radio>
        <el-radio value="all">
          <span><strong>删除归档原始文件及全部解析结果</strong><small>同时删除归档副本、重复导入指纹和关联报告；不会删除用户最初选择的外部文件。</small></span>
        </el-radio>
      </el-radio-group>
      <el-alert title="删除任务会在任务中心执行；有导入、解析、重建或报告任务运行时将拒绝提交。" type="warning" :closable="false" show-icon />
      <template #footer>
        <el-button :disabled="sourceDeleteSubmitting" @click="sourceDeleteVisible = false">取消</el-button>
        <el-button type="danger" :icon="Delete" :loading="sourceDeleteSubmitting" @click="confirmSourceDelete">继续并二次确认</el-button>
      </template>
    </el-dialog>

    <section class="content-card sessions-panel">
      <button class="sessions-toggle" type="button" :aria-expanded="sessionDetailsExpanded" @click="toggleSessionDetails">
        <el-icon><ArrowDown v-if="sessionDetailsExpanded" /><ArrowRight v-else /></el-icon>
        <strong>分析会话 · {{ total }} 个来源 · {{ summary?.train_count ?? 0 }} 列车 / {{ summary?.mr_count ?? 0 }} MR</strong>
        <span v-if="selected">当前：{{ selected.session.mr_name }} · {{ selected.session.original_filename }}</span>
        <el-tag v-if="taskCard" size="small">任务 {{ taskCard.status }}</el-tag>
      </button>
      <template v-if="sessionDetailsExpanded">
        <el-alert
          v-if="summary && summary.index_status !== 'ready'"
          :title="summary.index_status === 'failed' ? '来源目录更新失败，当前显示最近一次可用结果。' : `正在后台整理来源目录，已索引 ${summary.indexed_session_count} 个来源，尚有 ${summary.pending_session_count} 个明细统计待补齐。`"
          :type="summary.index_status === 'failed' ? 'warning' : 'info'"
          :closable="false"
          show-icon
        />
        <el-skeleton v-if="loading && !sessions.length" :rows="5" animated />
        <div v-if="taskCard" class="task-card">
          <div class="task-line">
            <div class="task-copy"><strong>{{ taskCard.name || taskCard.type }}</strong><span>{{ taskCard.id }}</span></div>
            <el-tag>{{ taskCard.status }}</el-tag>
            <el-button link type="primary" @click="openTaskWindow()">打开任务中心</el-button>
          </div>
          <el-progress v-if="taskActive" :percentage="taskProgress" :indeterminate="!taskProgressKnown" :duration="2" :show-text="false" />
          <p class="task-summary">{{ taskSummary }}</p>
        </div>
        <div class="summary-grid">
          <article v-for="card in cards" :key="String(card[0])" class="metric-card"><span>{{ card[0] }}</span><strong>{{ card[1] }}</strong></article>
        </div>
        <div class="toolbar sessions-toolbar">
          <el-input v-model="filters.query" clearable placeholder="搜索列车、MR 或来源文件" @keyup.enter="filters.page = 1; refreshOverview()" />
          <el-select v-model="filters.mr_role" clearable placeholder="MR 角色"><el-option label="CT" value="CT" /><el-option label="TC" value="TC" /><el-option label="CW" value="CW" /></el-select>
          <el-select v-model="filters.has_warning" clearable placeholder="数据告警"><el-option label="有告警" value="true" /><el-option label="无告警" value="false" /></el-select>
          <el-button type="primary" @click="filters.page = 1; refreshOverview()">查询</el-button>
          <el-button :loading="apCoverageLoading" :disabled="selectedDeleteSessions.length !== 2 || !isFeatureEnabled('capability.mesh.coverage_audit')" @click="openApCoverageAudit">核查 AP 覆盖</el-button>
          <el-button type="danger" plain :icon="Delete" :loading="sourceDeleteSubmitting" :disabled="!selectedDeleteSessions.length" @click="prepareSourceDelete(selectedDeleteSessions)">删除选中</el-button>
        </div>
        <NcDataTable table-id="mesh-analysis-sessions:v3" route-key="/rail-transit/mesh-analysis" :data="sessions" :columns="sessionColumns" row-key="session_id" border height="340" empty-text="暂无已持久化 Mesh 分析来源" @selection-change="(rows: MeshAnalysisSession[]) => selectedDeleteSessions = rows">
          <template #cell-warnings="{ row }"><el-tag :type="row.actionable_warning_count ? 'warning' : 'success'">{{ row.actionable_warning_count }}</el-tag></template>
          <template #cell-actions="{ row }"><el-button link type="primary" :loading="openingSessionId === row.session_id" @click.stop="openMeshAnalysisSession(row)">查看</el-button><el-button link type="danger" :icon="Delete" :loading="sourceDeleteSubmitting" @click.stop="prepareSourceDelete([row])">删除</el-button></template>
        </NcDataTable>
        <div class="pagination"><span>共 {{ total }} 个来源</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="total" @current-change="(page: number) => { filters.page = page; refreshOverview() }" /></div>
      </template>
    </section>

    <div v-if="selected" class="content-card detail-card">
      <div class="detail-heading">
        <div class="detail-heading__copy">
          <div class="detail-title-line">
            <h2>{{ selected.session.mr_name }}</h2>
            <el-popover
              v-if="maintenanceWarnings.length || parseIssueSummary.total_count"
              placement="bottom-start"
              :width="warningPopoverWidth"
              trigger="click"
            >
              <template #reference>
                <el-button
                  class="warning-summary-trigger"
                  link
                  type="warning"
                  :aria-label="`查看 ${maintenanceWarnings.length + parseIssueSummary.total_count} 条数据告警`"
                >
                  <el-icon aria-hidden="true"><WarningFilled /></el-icon>
                  <span>数据告警 {{ maintenanceWarnings.length + parseIssueSummary.total_count }}</span>
                </el-button>
              </template>
              <div class="warning-popover-content">
                <div class="warning-popover-heading">
                  <span>数据告警</span>
                  <strong>{{ maintenanceWarnings.length + parseIssueSummary.total_count }} 条</strong>
                </div>
                <div class="warning-list">
                  <div v-if="parseIssueSummary.total_count" class="parse-issue-summary">
                    <div class="parse-issue-summary__heading"><strong>解析异常</strong><span>{{ parseIssueSummary.total_count }} 条（错误 {{ parseIssueSummary.error_count }} · 告警 {{ parseIssueSummary.warning_count }} · 信息 {{ parseIssueSummary.info_count }}）</span></div>
                    <el-alert v-if="parseIssueSummary.message" :title="parseIssueSummary.message" :type="parseIssueSummary.available ? 'warning' : 'info'" :closable="false" show-icon />
                    <div v-for="group in parseIssueSummary.groups" :key="`${group.code}:${group.severity}`" class="parse-issue-group"><span>{{ group.code }} · {{ group.severity }} · {{ group.count }} 条</span><small>{{ group.message || group.examples[0] }}</small></div>
                    <el-button v-if="parseIssueSummary.available" link type="primary" @click="openParseIssues">查看全部异常</el-button>
                  </div>
                  <el-alert v-for="warning in maintenanceWarnings" :key="warning.code" :title="warning.message" :type="severityType(warning.severity)" :closable="false" show-icon />
                </div>
              </div>
            </el-popover>
          </div>
          <p>{{ selected.session.original_filename }} · {{ selected.session.first_sample_time }} — {{ selected.session.last_sample_time }}</p>
        </div>
        <div class="jump-actions">
          <el-button :loading="taskLoading" :disabled="!selectedSource || ['raw_missing','task_running','unsupported'].includes(selectedSource.rebuild_capability) || !isFeatureEnabled('capability.mesh.import')" @click="rebuildSelected">{{ selectedSource?.rebuild_capability === 'recoverable_from_bundle' ? '恢复原始日志并重新解析' : selected.session.parsed_status === 'ready' ? '重新解析当前日志' : '升级解析结果' }}</el-button>
          <el-button v-if="canOpenSelectedSourceLocation" :icon="FolderOpened" @click="openSelectedSourceLocation">打开本地目录</el-button>
          <el-button type="danger" plain :icon="Delete" :loading="sourceDeleteSubmitting" @click="prepareSourceDelete([selected.session])">删除当前来源</el-button>
          <el-button @click="openTaskWindow()">打开任务中心</el-button>
          <el-button @click="router.push({ path: '/rail-transit/train-communication', query: { train: selected?.session.train_name } })">在线列车通信</el-button>
          <el-button @click="router.push('/rail-transit/online-mr')">Online MR</el-button>
          <el-button @click="router.push('/rail-transit/train-online')">列车在线情况</el-button>
        </div>
      </div>
      <el-alert v-if="selectedSource && !selectedSource.exists" :title="selectedSource.missing_reason" :type="selectedSource.recoverable ? 'warning' : 'error'" :closable="false" show-icon />
      <el-alert
        v-if="identityMappingStale"
        title="AP 身份索引已更新，当前来源仍使用旧的身份映射。"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #default>
          <el-button
            link
            type="primary"
            :loading="taskLoading || identityRefreshActive"
            :disabled="taskLoading || identityRefreshActive"
            @click="refreshIdentityProjection"
          >立即刷新身份映射</el-button>
          <span class="hint">也可以稍后处理；打开页面不会自动提交任务。</span>
        </template>
      </el-alert>
      <el-alert
        v-if="parsedMaintenanceOutdated"
        :title="`发现较新的 MESH 解析版本（当前 ${selected.maintenance_state.parser_current}，最新 ${selected.maintenance_state.parser_latest}）`"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #default>
          <el-button link type="primary" :loading="taskLoading" :disabled="taskLoading" @click="rebuildParserProjection">立即升级</el-button>
          <span class="hint">也可以稍后处理；打开页面只检测版本，不会自动升级。</span>
        </template>
      </el-alert>
      <el-alert
        v-if="analysisResultUpdatePending"
        :title="analysisResultRefreshError || '分析结果已在后台更新，正在刷新当前会话。'"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #default><el-button link type="primary" @click="refreshAnalysisResults()">立即重试</el-button></template>
      </el-alert>
      <el-alert v-if="detailSectionError" :title="detailSectionError" type="warning" :closable="false" show-icon />

      <el-tabs v-model="activeTab" class="detail-tabs">
        <el-tab-pane label="主链路建链顺序" name="build-order" />
        <el-tab-pane label="链路明细" name="links" />
        <el-tab-pane label="RSSI 分析" name="rssi" />
        <el-tab-pane label="空口负载" name="busy" />
        <el-tab-pane label="切换事件" name="switches" />
        <el-tab-pane label="报告与来源" name="artifacts" />
      </el-tabs>
      <div class="detail-tab-content">
        <div v-show="activeTab === 'build-order'" id="pane-build-order" class="table-pane">
          <div class="toolbar">
            <el-select v-model="buildOrderFilters.radio" clearable placeholder="Radio"><el-option label="Radio 1" value="1" /><el-option label="Radio 2" value="2" /></el-select>
            <el-input v-model="buildOrderFilters.peer" clearable placeholder="Peer / AP" />
            <el-input v-model="buildOrderFilters.station" clearable placeholder="归属站点" />
            <el-select v-model="buildOrderFilters.build_result" clearable placeholder="建链结果"><el-option label="正常" value="normal" /><el-option label="短时" value="short" /><el-option label="同 AP 双射频" value="same_ap_radio_switch" /></el-select>
            <el-checkbox v-model="buildOrderFilters.pingpong_only">仅乒乓</el-checkbox>
            <el-button type="primary" @click="loadBuildOrders(detailGeneration, 1)">查询</el-button>
          </div>
          <div ref="buildOrderTableHost" class="table-host" :style="{ height: `${buildOrderPanel.height.value}px` }">
            <NcDataTable table-id="mesh-analysis-active-build-order:v2" route-key="/rail-transit/mesh-analysis" :data="buildOrders" :columns="buildOrderColumns" :stripe="false" :row-class-name="buildOrderRowClass" border height="100%" @sort-change="sortBuildOrders" @row-click="selectBuildOrderRow">
              <template #cell-build_result="{ row }"><el-tag :type="buildResultType(row.build_result)">{{ buildResultLabel(row.build_result) }}</el-tag></template>
              <template #cell-actions="{ row }"><el-button link type="primary" @click.stop="openBuildOrderRssi(row)">查看动态图</el-button></template>
            </NcDataTable>
          </div>
          <div class="pagination"><span>共 {{ buildOrderTotal }} 个主链路区段</span><el-pagination v-model:page-size="buildOrderFilters.page_size" :page-sizes="[100, 500, 1000]" :current-page="buildOrderFilters.page" layout="sizes, prev, pager, next" :total="buildOrderTotal" @size-change="() => loadBuildOrders(detailGeneration, 1)" @current-change="(page: number) => loadBuildOrders(detailGeneration, page)" /></div>
        </div>

        <div v-show="activeTab === 'links'" id="pane-links" class="table-pane">
          <div class="toolbar"><el-input v-model="linkFilters.query" clearable placeholder="Peer AP / MAC / 站点" /><el-select v-model="linkFilters.link_role" clearable placeholder="链路角色"><el-option label="主链路" value="ACTIVE" /><el-option label="备份链路" value="STANDBY" /></el-select><el-button @click="reloadLinks(1)">筛选</el-button></div>
          <div ref="linkTableHost" class="table-host" :style="{ height: `${linkPanel.height.value}px` }">
            <NcDataTable table-id="mesh-analysis-link-details:v3" route-key="/rail-transit/mesh-analysis" :data="links" :columns="linkColumns" :stripe="false" :row-class-name="linkRowClass" border height="100%" @row-dblclick="showLinkChart"><template #cell-link_role="{ row }"><span :class="roleClass(row.link_role)">{{ row.link_role }}</span></template></NcDataTable>
          </div>
          <div class="pagination"><span>共 {{ linkTotal }} 条</span><el-pagination v-model:page-size="linkFilters.page_size" :page-sizes="[100, 500, 1000]" :current-page="linkFilters.page" layout="sizes, prev, pager, next" :total="linkTotal" @size-change="() => reloadLinks(1)" @current-change="reloadLinks" /></div>
        </div>

        <div v-show="activeTab === 'rssi'" id="pane-rssi" class="chart-pane">
          <div class="chart-toolbar rssi-chart-toolbar">
            <div class="rssi-chart-toolbar__row">
              <div class="rssi-layout-switch" role="group" aria-label="RSSI 图表布局">
                <el-button
                  :class="{ 'is-current': rssiLayoutMode === 'compare' }"
                  title="上下对比"
                  @click="setRssiLayoutMode('compare')"
                >
                  对比
                </el-button>
                <el-button
                  :class="{ 'is-current': rssiLayoutMode === 'active-focus' }"
                  title="仅看主用链路信号"
                  @click="setRssiLayoutMode('active-focus')"
                >
                  主链
                </el-button>
                <el-button
                  :class="{ 'is-current': rssiLayoutMode === 'trackside-focus' }"
                  title="仅看轨旁AP信号图"
                  @click="setRssiLayoutMode('trackside-focus')"
                >
                  轨旁
                </el-button>
              </div>
              <el-button :icon="FullScreen" :type="rssiImmersive ? 'primary' : undefined" @click="toggleRssiImmersive">
                {{ rssiImmersive ? '退出沉浸' : '沉浸对比' }}
              </el-button>
              <el-select v-model="chartRadio" placeholder="选择 Radio" @change="changeChartRadio"><el-option v-for="radio in availableChartRadios" :key="radio" :label="`Radio ${radio}`" :value="radio" /></el-select>
              <span class="toolbar-label">主链 RSSI 精度</span>
              <el-select v-model="rssiResolutionMode" @change="changeRssiResolutionMode"><el-option label="全量（默认）" value="full" /><el-option label="高精度" value="high" /><el-option label="概览" value="overview" /></el-select>
              <span class="toolbar-label">业务叠加精度</span>
              <el-select v-model="visiblePoints" @change="reloadCurrentChart"><el-option label="600 点" :value="600" /><el-option label="1200 点" :value="1200" /><el-option label="2000 点" :value="2000" /><el-option label="4000 点（高精度）" :value="4000" /></el-select>
            </div>
            <div class="rssi-chart-toolbar__row">
              <el-checkbox v-model="showRssiPeer">显示 Peer 侧 RSSI</el-checkbox>
              <el-button :icon="showSwitchLines ? View : Hide" @click="showSwitchLines = !showSwitchLines">显示切换时刻线</el-button>
              <el-button :icon="showSwitchPoints ? View : Hide" @click="showSwitchPoints = !showSwitchPoints">显示切换节点</el-button>
              <el-button :icon="showLocationBand ? View : Hide" @click="showLocationBand = !showLocationBand">显示站点/区间</el-button>
              <el-button @click="resetCurrentChartViewport">重置视图</el-button>
              <el-button v-if="!lockedAnalysisRange" :icon="Lock" type="primary" plain @click="lockCurrentRssiRange">锁定当前时间范围</el-button>
              <template v-else>
                <el-button :icon="Refresh" @click="lockCurrentRssiRange">更新锁定范围</el-button>
                <el-button :icon="Unlock" @click="clearTimeLock">解除时间锁定</el-button>
                <el-button type="primary" @click="openLockedBusyRange">查看同期空口负载</el-button>
              </template>
            </div>
          </div>
          <div v-if="rssiLoadStage" class="rssi-load-stage" role="status" aria-live="polite">
            <strong>步骤 {{ rssiLoadStage.step }}</strong>
            <span>{{ rssiLoadStage.label }}</span>
          </div>
          <div
            ref="rssiWorkspaceHost"
            class="rssi-workspace-host"
            :style="{ height: `${rssiPanel.height.value}px` }"
          >
            <RailRssiComparison
              :mode="rssiLayoutMode"
              :split-ratio="rssiCompareSplitRatio"
              :workspace-height="rssiPanel.height.value"
              @update:split-ratio="updateRssiSplitRatio"
              @resize="resizeVisibleRssiCharts"
            >
              <template #active>
                <div class="rssi-pane-content">
                  <header class="rssi-pane-heading">
                    <h3>主用链路信号</h3>
                    <el-button link type="primary" @click="toggleRssiFocus('active-focus')">
                      {{ rssiLayoutMode === 'active-focus' ? '返回对比' : '专注' }}
                    </el-button>
                  </header>
                  <div v-if="activePaneAlertSummary" class="rssi-pane-alert">
                    <span class="rssi-pane-alert__text" :title="activePaneAlertSummary">提示：{{ activePaneAlertSummary }}</span>
                    <el-popover placement="bottom-start" :width="520" trigger="click">
                      <template #reference><el-button link type="primary">详情</el-button></template>
                      <div class="rssi-pane-alert__details">
                        <p v-for="message in activePaneAlertMessages" :key="message">{{ message }}</p>
                      </div>
                    </el-popover>
                  </div>
                  <div v-if="rssiActiveLoading || rssiActiveError || !rssiActiveLoaded" class="rssi-pane-state">
                    <span v-if="rssiActiveLoading">正在加载主链 RSSI 数据…</span>
                    <span v-else-if="rssiActiveError">主链 RSSI 数据加载失败：{{ rssiActiveError }}</span>
                    <span v-else>主链 RSSI 数据尚未加载</span>
                    <el-button v-if="rssiActiveError" link type="warning" :loading="rssiActiveLoading" @click="retryRssiActivePath">重试主链 RSSI</el-button>
                  </div>
                  <div v-else-if="chartData" class="mini-summary rssi-pane-summary"><span>当前 PeerMac <strong>{{ chartData.summary.current_peer_mac || '—' }}</strong></span><span>当前 AP <strong>{{ chartData.summary.current_peer_ap_name || '—' }}</strong></span><span>Radio <strong>{{ chartData.summary.current_radio ?? '—' }}</strong></span><span>估算采样间隔 <strong>{{ display(chartData.summary.estimated_interval_seconds, ' s') }}</strong></span><span>采样点 <strong>{{ chartData.summary.sample_count }}</strong></span><span>ACTIVE <strong>{{ chartData.summary.active_count }}</strong></span><span>STANDBY 上下文 <strong>{{ chartData.summary.standby_context_count }}</strong></span><span>△ 三角链路 <strong>{{ chartData.summary.triangle_link_point_count ?? 0 }}</strong></span><span><strong>{{ chartData.rssi_line?.resolution_mode === 'full' ? '主链 RSSI 全量' : '主链 RSSI' }} {{ formatChartCount(chartData.rssi_line?.returned_points ?? chartData.returned_points) }} / {{ formatChartCount(chartData.rssi_line?.total_points ?? chartData.total_points) }}</strong></span><span>业务叠加点 <strong>{{ formatChartCount(chartData.response_budget?.returned_points) }} / {{ formatChartCount(chartData.response_budget?.total_points) }}</strong></span><span>切换事件 Overlay <strong>{{ formatChartCount(chartData.response_budget?.returned_events) }} / {{ formatChartCount(chartData.response_budget?.total_events) }}</strong></span><span>Overlay LOD <strong>{{ chartLodLabel(chartData.response_budget?.lod_level, activeChartWindow.start, activeChartWindow.end, chartData.view_mode) }}</strong></span><span>Payload <strong>{{ formatPayloadBytes(chartData.payload_bytes) }}</strong></span><span>当前窗口 <strong>{{ chartWindowLabel(activeChartWindow.start, activeChartWindow.end) }}</strong></span><span>最早 <strong>{{ chartData.summary.first_sample_time || '—' }}</strong></span><span>最新 <strong>{{ chartData.summary.last_sample_time || '—' }}</strong></span></div>
                  <div class="rssi-pane-chart-host">
                    <MeshRssiChart v-if="rssiActiveLoaded && chartData" ref="rssiChartRef" :points="chartData.points" :rssi-line="chartData.rssi_line" :events="chartData?.events || []" :location-segments="chartData.location_segments" :show-peer="showRssiPeer" :show-switch-lines="showSwitchLines" :show-switch-points="showSwitchPoints" :show-location-band="showLocationBand" scope="active" :active="pageActive && activeTab === 'rssi' && rssiLayoutMode !== 'trackside-focus'" :focus-timestamp="focusTimestamp" :initial-viewport="rssiViewport" :sync-viewport="rssiViewport" :shared-time-domain="sharedRssiTimeDomain" :sync-pointer-time="sharedPointerTime || selectedAnalysisTime" :sync-pointer-source="sharedPointerTime ? sharedPointerSource : 'programmatic'" :selected-time="selectedAnalysisTime" @viewport-change="updateRssiViewport" @viewport-interaction-start="beginRssiViewportInteraction" @viewport-interaction-end="endRssiViewportInteraction" @pointer-change="updateSharedPointer" @select-time="selectAnalysisTime" @select-switch="selectChartSwitch" />
                    <el-empty v-else-if="rssiActiveLoaded && !rssiActiveLoading" description="当前范围没有 RSSI 数据" :image-size="60" />
                  </div>
                </div>
              </template>

              <template #trackside>
                <div class="rssi-pane-content">
                  <header class="rssi-pane-heading">
                    <h3>轨旁AP信号图</h3>
                    <el-button
                      v-if="!tracksideLoaded && !tracksideLoading"
                      link
                      :type="tracksideRecoveryBlocked || tracksideError ? 'warning' : 'primary'"
                      @click="loadTracksideForCurrentWindow"
                    >{{ tracksideRecoveryBlocked || tracksideError ? '重新加载轨旁AP信号图' : '加载当前窗口' }}</el-button>
                    <el-button link type="primary" @click="toggleRssiFocus('trackside-focus')">
                      {{ rssiLayoutMode === 'trackside-focus' ? '返回对比' : '专注' }}
                    </el-button>
                  </header>
                  <div v-if="tracksidePaneAlertSummary" class="rssi-pane-alert">
                    <span class="rssi-pane-alert__text" :title="tracksidePaneAlertSummary">提示：{{ tracksidePaneAlertSummary }}</span>
                    <el-popover placement="bottom-start" :width="520" trigger="click">
                      <template #reference><el-button link type="primary">详情</el-button></template>
                      <div class="rssi-pane-alert__details">
                        <p v-for="message in tracksidePaneAlertMessages" :key="message">{{ message }}</p>
                      </div>
                    </el-popover>
                  </div>
                  <div v-if="tracksideSignal && tracksideLoaded" class="mini-summary rssi-pane-summary">
                    <span>采样时刻 <strong>{{ tracksideSignal.returned_frames }} / {{ tracksideSignal.total_frames }}</strong></span>
                    <span>ACTIVE 链路点 <strong>{{ tracksideSignal.returned_active_link_points }} / {{ tracksideSignal.active_link_points }}</strong></span>
                    <span>STANDBY 链路点 <strong>{{ tracksideSignal.returned_standby_link_points }} / {{ tracksideSignal.standby_link_points }}</strong></span>
                    <span>△ 三角链路 <strong>{{ tracksideSignal.returned_triangle_link_points ?? 0 }} / {{ tracksideSignal.triangle_link_points ?? 0 }}</strong></span>
                    <span>总链路点 <strong>{{ tracksideSignal.returned_link_points }} / {{ tracksideSignal.total_link_points }}</strong></span>
                    <span>AP/Radio 序列 <strong>{{ tracksideSignal.returned_series }} / {{ tracksideSignal.total_series }}</strong></span>
                    <span>链路存在区段 <strong>{{ tracksideSignal.total_link_runs }}</strong></span>
                    <span>角色切换 <strong>{{ tracksideSignal.role_switch_count }}</strong></span>
                    <span>缺失轨旁信号跳过 <strong>{{ tracksideSignal.skipped_missing_signal_points }}</strong></span>
                    <span>查询行 <strong>{{ formatChartCount(tracksideSignal.response_budget?.selected_rows) }} / {{ formatChartCount(tracksideSignal.response_budget?.source_rows) }}</strong></span>
                    <span>事件 <strong>{{ formatChartCount(tracksideSignal.response_budget?.returned_events) }} / {{ formatChartCount(tracksideSignal.response_budget?.total_events) }}</strong></span>
                    <span>LOD <strong>{{ chartLodLabel(tracksideSignal.response_budget?.lod_level, tracksideChartWindow.start, tracksideChartWindow.end, tracksideSignal.view_mode) }}</strong></span>
                    <span>Payload <strong>{{ formatPayloadBytes(tracksideSignal.payload_bytes) }}</strong></span>
                    <span>当前窗口 <strong>{{ chartWindowLabel(tracksideChartWindow.start, tracksideChartWindow.end) }}</strong></span>
                  </div>
                  <div ref="tracksideChartHost" class="rssi-pane-chart-host">
                    <MeshTracksideSignalChart v-if="tracksideSeriesCache" ref="tracksideChartRef" :series-cache="tracksideSeriesCache" :events="chartData?.events || []" :location-segments="chartData?.location_segments || []" :continuity-gap-seconds="tracksideSignal?.continuity_gap_seconds" :show-switch-lines="showSwitchLines" :show-switch-points="showSwitchPoints" :show-location-band="showLocationBand" :active="pageActive && activeTab === 'rssi' && tracksideChartVisible && rssiLayoutMode !== 'active-focus'" :workspace-visible="activeTab === 'rssi'" :initial-viewport="rssiViewport" :sync-viewport="rssiViewport" :shared-time-domain="sharedRssiTimeDomain" :sync-pointer-time="sharedPointerTime || selectedAnalysisTime" :sync-pointer-source="sharedPointerTime ? sharedPointerSource : 'programmatic'" :selected-time="selectedAnalysisTime" @viewport-change="updateRssiViewport" @viewport-interaction-start="beginRssiViewportInteraction" @viewport-interaction-end="endRssiViewportInteraction" @pointer-change="updateSharedPointer" @select-time="selectAnalysisTime" @select-switch="selectChartSwitch" @workload-phase="handleTracksideWorkloadPhase" @workload-profile="handleTracksideWorkloadProfile" />
                    <el-empty v-else-if="tracksideLoaded && !tracksideLoading" description="当前范围没有轨旁AP信号数据" :image-size="60" />
                    <el-empty v-else-if="!tracksideRecoveryBlocked && !tracksideLoading" :description="rssiActivePaintReady ? '轨旁AP信号图尚未加载' : '等待主链 RSSI 图加载完成'" :image-size="60" />
                  </div>
                </div>
              </template>
            </RailRssiComparison>
          </div>
          <div v-if="selectedChartEvent" class="selected-switch"><span>切换：{{ selectedChartEvent.from_ap_name || selectedChartEvent.from_peer_mac || '—' }} → {{ selectedChartEvent.to_ap_name || selectedChartEvent.to_peer_mac || '—' }} · {{ selectedChartEvent.timestamp }}</span><el-button link type="primary" @click="showSwitchInBuildOrder">查看建链顺序</el-button></div>
          <p class="hint">{{ chartData?.rssi_line ? `主链 RSSI 使用 ${chartData.rssi_line.returned_points} / ${chartData.rssi_line.total_points} 个真实有效 ACTIVE 样本；业务 Overlay 独立按预算返回` : (chartData?.downsampled ? `主链 RSSI 从 ${chartData.total_points} 点按所选精度返回 ${chartData.returned_points} 点` : `主链 RSSI 展示 ${chartData?.returned_points ?? 0} 个真实结构化样本`) }}；轨旁图继续按窗口与 LOD 加载，Full 模式缩放不会重新请求主线。</p>
        </div>

        <div v-show="activeTab === 'busy'" id="pane-busy" class="chart-pane">
          <el-tabs v-model="busyMode" class="analysis-subtabs" @tab-change="changeBusyMode"><el-tab-pane label="全部 ACTIVE 链路信道负载" name="active" /><el-tab-pane label="单 AP / 分时段信道负载" name="peer" /></el-tabs>
          <div class="chart-toolbar">
            <el-select v-if="busyMode === 'peer'" :model-value="selectedVisitValue" filterable placeholder="选择 AP / 经过时段" @change="selectSegmentByAnchor"><el-option v-if="selectedSegment" label="全部经过时段（各区段断开）" value="all-visits" /><el-option v-for="row in buildOrderOptions" :key="row.anchor_link_id" :label="`第 ${row.sequence} 次 · Radio ${row.local_radio ?? '—'} · ${row.peer_ap_name || row.active_peer_mac} · ${row.build_start_time} — ${row.build_end_time}`" :value="row.anchor_link_id" /></el-select>
            <el-select v-if="busyMode === 'active'" v-model="chartRadio" placeholder="选择 Radio" @change="changeChartRadio"><el-option v-for="radio in availableChartRadios" :key="radio" :label="`Radio ${radio}`" :value="radio" /></el-select>
            <el-select v-model="visiblePoints" @change="reloadCurrentChart"><el-option label="概览精度 600 点" :value="600" /><el-option label="概览精度 1200 点" :value="1200" /><el-option label="概览精度 2000 点" :value="2000" /><el-option label="概览精度 4000 点（高精度）" :value="4000" /></el-select>
            <el-checkbox v-model="showBusyPeer">显示 Peer 侧 Tx/Rx Busy</el-checkbox>
            <el-button :icon="showBusySwitchLines ? View : Hide" @click="showBusySwitchLines = !showBusySwitchLines">显示切换时刻线</el-button>
            <el-button :icon="showBusySwitchPoints ? View : Hide" @click="showBusySwitchPoints = !showBusySwitchPoints">显示切换节点</el-button>
            <el-button :icon="showLocationBand ? View : Hide" @click="showLocationBand = !showLocationBand">显示站点/区间</el-button>
            <el-button @click="resetCurrentChartViewport">重置视图</el-button>
            <template v-if="lockedAnalysisRange">
              <el-button @click="returnToRssi">返回 RSSI</el-button>
              <el-button :icon="Refresh" @click="updateLockedRangeFromBusy">使用当前空口范围更新锁定</el-button>
              <el-button :icon="Unlock" @click="unlockAndShowAll">解除锁定并查看全部</el-button>
            </template>
          </div>
          <el-alert v-if="lockedAnalysisRange" :title="`已使用 RSSI 锁定时间 ${lockedRangeLabel} · RSSI 可见采样 ${lockedAnalysisRange.sample_count} 点 · 空口有效采样 ${busyValidSampleCount} 点`" type="info" :closable="false" show-icon />
          <el-alert v-if="lockedAnalysisRange && busyChartData && busyValidSampleCount === 0" title="当前 RSSI 锁定时间范围内没有有效 TxBusy/RxBusy 样本。" type="warning" :closable="false" show-icon />
          <div ref="busyChartHost" class="chart-host" :style="{ height: `${busyPanel.height.value}px` }">
            <MeshChannelBusyChart ref="busyChartRef" :points="busyChartData?.points || []" :events="busyChartData?.events || []" :location-segments="busyChartData?.location_segments || []" :show-peer="showBusyPeer" :show-switch-lines="showBusySwitchLines" :show-switch-points="showBusySwitchPoints" :show-location-band="showLocationBand" :scope="busyMode" :active="pageActive && activeTab === 'busy'" :initial-viewport="busyViewport" :locked-viewport="lockedAnalysisRange" @viewport-change="updateBusyViewport" @viewport-ready="updateBusyViewport" @select-switch="selectChartSwitch" />
          </div>
          <p class="hint">默认仅显示 MR 侧 TxBusy / RxBusy 两条真实曲线；启用 Peer 后最多四条，不伪造 CtlBusy。</p>
        </div>

        <div v-show="activeTab === 'switches'" id="pane-switches" class="table-pane" v-loading="switchLoading">
          <div class="toolbar">
            <el-select v-model="switchFilters.radio" clearable placeholder="Radio" @change="changeSwitchFilters">
              <el-option label="Radio 1" value="1" />
              <el-option label="Radio 2" value="2" />
            </el-select>
            <el-select v-model="switchFilters.result" clearable placeholder="切换分类" @change="changeSwitchFilters">
              <el-option label="正常切换" value="normal" />
              <el-option label="短时建链" value="short" />
              <el-option label="乒乓切换" value="pingpong" />
            </el-select>
          </div>
          <div ref="switchTableHost" class="table-host" :style="{ height: `${switchTableHeight}px` }">
            <NcDataTable table-id="mesh-analysis-switch-events:v3" route-key="/rail-transit/mesh-analysis" :data="switches" :columns="switchColumns" :stripe="false" :row-class-name="switchRowClass" border :height="switchTableHeight" />
          </div>
          <div class="pagination">
            <span>共 {{ switchTotal }} 条切换事件</span>
            <el-pagination
              :current-page="switchFilters.page"
              :page-size="switchFilters.page_size"
              :page-sizes="[50, 100, 200]"
              layout="sizes, prev, pager, next"
              :total="switchTotal"
              @current-change="changeSwitchPage"
              @size-change="changeSwitchPageSize"
            />
          </div>
        </div>

        <div v-show="activeTab === 'artifacts'" id="pane-artifacts">
          <h3>已有报告与文件</h3><NcDataTable table-id="mesh-analysis-artifacts:v2" route-key="/rail-transit/mesh-analysis" :data="artifacts" :columns="artifactColumns" border><template #cell-actions="{ row }"><el-button v-if="row.downloadable" link type="primary" @click="downloadArtifact(row)">下载</el-button><el-button v-if="row.deletable" link type="danger" :icon="Delete" @click="deleteArtifact(row)">删除</el-button><span v-if="!row.deletable" class="hint">原始日志保留</span></template></NcDataTable>
          <h3>原始数据来源</h3><NcDataTable table-id="mesh-analysis-sources:v2" route-key="/rail-transit/mesh-analysis" :data="selected.sources" :columns="sourceColumns" border><template #cell-tail="{ row }"><el-button link type="primary" :disabled="!row.tail_available" @click="loadRawTail(row.source_action_id, row.tail_available)">查看 tail</el-button></template></NcDataTable>
          <el-alert v-if="rawTail?.message" :title="rawTail.message" type="info" :closable="false" /><pre v-if="rawTail?.available">{{ rawTail.lines.join('\n') }}</pre>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.report-params-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}
.source-delete-list{display:flex;max-height:260px;flex-direction:column;gap:8px;overflow:auto}.source-delete-item{display:grid;grid-template-columns:minmax(180px,1.5fr) minmax(130px,1fr) minmax(260px,1.5fr);gap:12px;padding:9px 0;border-bottom:1px solid var(--nc-border-light)}.source-delete-item span{color:var(--nc-text-secondary)}.source-delete-options{display:flex;margin:16px 0;flex-direction:column;align-items:stretch;gap:10px}.source-delete-options :deep(.el-radio){height:auto;margin-right:0;padding:10px;border:1px solid var(--nc-border-light);border-radius:6px;white-space:normal}.source-delete-options :deep(.el-radio__label span){display:flex;flex-direction:column;gap:4px}.source-delete-options small{color:var(--nc-text-secondary);line-height:1.5}
@media(max-width:700px){.report-params-grid,.source-delete-item{grid-template-columns:1fr}}
.selected-switch{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:8px 0;padding:8px 12px;border:1px solid var(--nc-border-light);border-radius:6px;background:var(--nc-bg-page)}
.rssi-layout-switch{display:inline-flex;align-items:center}.rssi-layout-switch .el-button{margin-left:0;border-radius:0}.rssi-layout-switch .el-button:first-child{border-radius:6px 0 0 6px}.rssi-layout-switch .el-button:last-child{border-radius:0 6px 6px 0}.rssi-layout-switch .el-button+.el-button{margin-left:-1px}.rssi-layout-switch .el-button.is-current{position:relative;z-index:1;color:var(--nc-primary);border-color:var(--nc-primary);background:color-mix(in srgb,var(--nc-primary) 12%,var(--nc-bg-card))}
.rssi-load-stage{display:flex;min-height:28px;align-items:center;gap:10px;padding:4px 8px;color:var(--nc-text-secondary);background:var(--nc-bg-page);border-left:3px solid var(--nc-primary);font-size:12px}.rssi-load-stage strong{color:var(--nc-primary);white-space:nowrap}.rssi-workspace-host{width:100%;min-width:0;min-height:240px;overflow:hidden}.rssi-pane-content{display:flex;width:100%;height:100%;min-width:0;min-height:0;flex-direction:column;overflow-y:auto}.rssi-pane-heading{display:flex;min-height:36px;flex:none;align-items:center;justify-content:space-between;gap:12px;padding:2px 4px}.rssi-pane-heading h3{margin:0}.rssi-pane-alerts{max-height:104px;flex:none;overflow-y:auto}.rssi-pane-alerts:empty{display:none}.rssi-pane-summary{flex:none;flex-wrap:nowrap!important;overflow-x:auto;overflow-y:hidden;scrollbar-width:thin}.rssi-pane-summary span{flex:none;white-space:nowrap}.rssi-pane-chart-host{width:100%;min-width:0;min-height:240px;flex:1 0 240px}
.mesh-page{display:flex;min-height:0;min-width:0;flex-direction:column;gap:16px}.page-heading,.detail-heading,.jump-actions,.toolbar,.pagination,.mini-summary,.chart-toolbar,.task-line{display:flex;align-items:center;gap:12px}.page-heading,.detail-heading,.pagination{justify-content:space-between}.page-heading h1,.detail-heading h2{margin:2px 0 6px}.page-heading p,.detail-heading p,.hint{margin:0;color:var(--nc-text-secondary)}.eyebrow{color:var(--nc-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(8,minmax(105px,1fr));gap:10px}.metric-card,.content-card{background:var(--nc-bg-card);border:1px solid var(--nc-border-light);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--nc-text-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.sessions-panel{padding-top:10px}.sessions-toggle{display:flex;width:100%;min-height:42px;align-items:center;gap:10px;padding:6px 4px;color:var(--nc-text-primary);background:transparent;border:0;cursor:pointer;text-align:left}.sessions-toggle>span:not(.el-tag){min-width:0;overflow:hidden;color:var(--nc-text-secondary);text-overflow:ellipsis;white-space:nowrap}.sessions-toggle .el-tag{margin-left:auto}.sessions-toolbar{margin-top:14px}.task-card{max-height:140px;margin:8px 0 14px;padding:10px 12px;overflow:hidden;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:8px}.task-line{min-width:0}.task-copy{display:flex;min-width:0;flex:1;flex-direction:column}.task-copy span,.task-summary{overflow:hidden;color:var(--nc-text-secondary);font-size:12px;text-overflow:ellipsis;white-space:nowrap}.task-line>.el-button{margin-left:auto}.task-card :deep(.el-progress){margin-top:8px}.task-summary{margin:7px 0 0}.toolbar,.jump-actions,.mini-summary,.chart-toolbar{flex-wrap:wrap}.toolbar{margin-bottom:12px}.toolbar .el-input{width:240px}.toolbar .el-select{width:145px}.chart-toolbar{padding:10px 0 4px}.chart-toolbar .el-select:first-child{width:min(620px,100%)}.pagination{flex:none;padding-top:12px;color:var(--nc-text-secondary)}.detail-card{display:flex;min-height:0;flex-direction:column}.detail-tabs{min-height:0;flex:none;scroll-margin-top:12px}.detail-card :deep(.detail-tabs>.el-tabs__content){display:none}.detail-tab-content{min-height:0;flex:1}.analysis-subtabs :deep(.el-tabs__content){display:none}.table-pane,.chart-pane{min-height:0}.table-pane{display:flex;flex-direction:column}.table-host,.chart-host{min-height:0;min-width:0;flex:none}.chart-host{width:100%;min-height:360px}.detail-card .el-alert,.task-card .el-alert{margin:10px 0}.warning-summary .el-alert{margin:10px 0}.warning-list{display:flex;flex-direction:column;gap:8px}.mini-summary{padding:10px 0}.mini-summary span{padding:9px 12px;border-radius:8px;background:var(--nc-bg-page)}.hint{font-size:12px}.hidden-input{display:none}.profile-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.bundle-table-wrap{overflow-x:auto;margin-top:12px}.bundle-table{width:100%;border-collapse:collapse;min-width:900px}.bundle-table th,.bundle-table td{padding:9px;border-bottom:1px solid var(--nc-border-light);text-align:left;vertical-align:middle}.bundle-table th{color:var(--nc-text-secondary);font-size:12px}.bundle-table td small{display:block;color:var(--nc-text-secondary);margin-top:4px}.mesh-role-active{color:var(--nc-success);font-weight:600}.mesh-role-standby{color:var(--nc-text-secondary)}.nc-data-table :deep(.mesh-time-group-0 > td.el-table__cell){background:var(--nc-bg-card)}.nc-data-table :deep(.mesh-time-group-1 > td.el-table__cell){background:var(--nc-bg-page)}.nc-data-table :deep(.mesh-row-active > td.el-table__cell){color:var(--nc-success)}.nc-data-table :deep(.mesh-build-selected > td.el-table__cell){background:color-mix(in srgb,var(--nc-primary) 14%,var(--nc-bg-card))}.nc-data-table :deep(.mesh-time-group-0:hover > td.el-table__cell),.nc-data-table :deep(.mesh-time-group-1:hover > td.el-table__cell),.nc-data-table :deep(.mesh-build-selected:hover > td.el-table__cell){background:var(--nc-table-hover-bg)}h3{margin:16px 0 8px}pre{max-height:360px;overflow:auto;padding:12px;background:var(--nc-bg-code);color:var(--nc-text-code);border-radius:8px;font:12px/1.6 Consolas,monospace}@media(max-width:1450px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}}@media(max-width:900px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.page-heading,.detail-heading{align-items:flex-start;flex-direction:column}.profile-grid{grid-template-columns:1fr}.sessions-toggle>span:not(.el-tag){display:none}}
.mesh-page.is-rssi-workspace{gap:8px}
.is-rssi-workspace .page-heading{min-height:36px;gap:12px}
.is-rssi-workspace .page-heading__copy{display:flex;min-width:0;align-items:center;gap:12px}
.is-rssi-workspace .page-heading__copy .eyebrow,
.is-rssi-workspace .page-heading__description{display:none}
.is-rssi-workspace .page-heading h1{flex:none;margin:0;font-size:18px;line-height:28px}
.page-heading__current-log{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.is-rssi-workspace .page-heading>.jump-actions{min-width:0;flex:none;flex-wrap:nowrap;overflow-x:auto}
.is-rssi-workspace .page-heading>.jump-actions :deep(.el-button){flex:none}
.is-rssi-workspace .sessions-panel{padding:0 10px}
.is-rssi-workspace .sessions-toggle{min-height:36px;padding:3px 0}
.is-rssi-workspace .detail-card{padding:7px 12px}
.is-rssi-workspace .detail-heading{min-height:34px;gap:12px}
.is-rssi-workspace .detail-heading>div:first-child{display:flex;min-width:0;align-items:center;gap:10px}
.is-rssi-workspace .detail-heading h2{flex:none;margin:0;font-size:16px}
.is-rssi-workspace .detail-heading p{min-width:0;overflow:hidden;font-size:12px;text-overflow:ellipsis;white-space:nowrap}
.is-rssi-workspace .detail-heading>.jump-actions{min-width:0;flex-wrap:nowrap;overflow-x:auto}
.is-rssi-workspace .detail-heading>.jump-actions :deep(.el-button){flex:none}
.is-rssi-workspace .warning-summary{max-height:42px;overflow:hidden}
.is-rssi-workspace .warning-summary .el-alert{margin:3px 0}
.is-rssi-workspace .detail-tabs :deep(.el-tabs__header){margin:0}
.rssi-chart-toolbar{display:flex;min-width:0;flex-direction:column;align-items:stretch;gap:4px;padding:4px 0}
.rssi-chart-toolbar__row{display:flex;min-height:32px;min-width:0;align-items:center;gap:8px;overflow-x:auto;overflow-y:hidden;white-space:nowrap;scrollbar-width:thin}
.rssi-chart-toolbar__row>*{flex:none}
.rssi-chart-toolbar__row .el-select{width:180px}
.rssi-workspace-host{min-height:320px}
.rssi-pane-content{overflow:hidden}
.rssi-pane-heading{min-height:28px;height:28px;padding:0 4px}
.rssi-pane-heading h3{margin:0;font-size:14px;line-height:28px}
.rssi-pane-alert{display:flex;height:26px;min-width:0;flex:none;align-items:center;gap:6px;padding:0 6px;color:var(--nc-warning);background:color-mix(in srgb,var(--nc-warning) 9%,var(--nc-bg-card));font-size:12px}
.rssi-pane-alert__text{min-width:0;overflow:hidden;flex:1;text-overflow:ellipsis;white-space:nowrap}
.rssi-pane-alert__details p{margin:0 0 8px;line-height:1.5}
.rssi-pane-alert__details p:last-child{margin-bottom:0}
.mesh-page .rssi-pane-summary{min-height:26px;max-height:26px;padding:0;gap:6px;scrollbar-width:none}
.mesh-page .rssi-pane-summary::-webkit-scrollbar{display:none}
.mesh-page .rssi-pane-summary span{height:24px;padding:2px 8px;line-height:20px}
.rssi-pane-chart-host{min-height:240px;flex:1 0 240px}
.rssi-pane-state{display:flex;min-height:36px;align-items:center;gap:8px;padding:6px 8px;color:var(--nc-text-secondary);font-size:12px}
.is-rssi-workspace #pane-rssi>.hint{display:none}
.mesh-page.is-rssi-immersive{gap:0}
.is-rssi-immersive>.page-heading,
.is-rssi-immersive>.sessions-panel,
.is-rssi-immersive .detail-heading,
.is-rssi-immersive .warning-summary,
.is-rssi-immersive .detail-card>.el-alert,
.is-rssi-immersive .detail-tabs{display:none}
.is-rssi-immersive .detail-card{padding:4px 8px;border-radius:0}
.is-rssi-immersive .rssi-chart-toolbar{padding-top:0}
.detail-heading__copy{display:flex;min-width:0;flex:1;flex-direction:column}
.detail-title-line{display:flex;min-width:0;align-items:center;gap:10px}
.detail-title-line h2{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.warning-summary-trigger{flex:none;margin-left:2px;padding:4px 8px!important}
.warning-summary-trigger .el-icon{margin-right:4px}
.warning-popover-content{display:flex;max-height:min(360px,calc(100vh - 180px));flex-direction:column;gap:10px;overflow:auto}
.warning-popover-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--nc-text-primary);font-size:13px}
.warning-popover-heading strong{color:var(--nc-warning);font-weight:600}
.warning-popover-content .warning-list{gap:6px}
.warning-popover-content .el-alert{margin:0}
.is-rssi-workspace .detail-title-line{gap:8px}
.is-rssi-workspace .warning-summary-trigger{padding:2px 6px!important;font-size:12px}
</style>

<style scoped>
.local-scan-stats { margin: 10px 0; }
.local-scan-toolbar { justify-content: flex-start; margin-top: 12px; }
.local-scan-table-wrap { max-height: min(58vh, 680px); overflow: auto; }
.local-scan-table-wrap .el-select { min-width: 180px; }
</style>
