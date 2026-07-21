<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowRight, Delete, Document, Download, Hide, Lock, Refresh, Unlock, View } from '@element-plus/icons-vue'

import MeshChannelBusyChart from '../../components/mesh-analysis/MeshChannelBusyChart.vue'
import MeshRssiChart from '../../components/mesh-analysis/MeshRssiChart.vue'
import { visibleMeshSamples, type MeshChartHandle, type MeshChartViewport } from '../../components/mesh-analysis/meshChartViewport'
import { buildMeshTimeGroupClasses } from '../../components/mesh-analysis/timeGrouping'
import NcDataTable from '../../components/table/NcDataTable.vue'
import { useConfirm } from '../../components/feedback/useConfirm'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { useAvailablePanelHeight } from '../../composables/useAvailablePanelHeight'
import {
  applyMeshBundleImport, createMeshProfile, deleteMeshArtifact, exportMeshLinkDetails, getMeshActivePathChart, getMeshAnalysisParamsTemplate, getMeshAnalysisSession, getMeshAnalysisSummary, getMeshPeerSegmentChart, getMeshRawTail,
  listMeshActiveBuildOrder, listMeshAnalysisSessions,
  listMeshArtifacts, listMeshLinks, listMeshProfiles, listMeshSwitchEvents, meshArtifactDownloadRequest, previewMeshImport, rebuildMeshAnalysis,
  prepareMeshImportContext, saveMeshAnalysisParams,
} from '../../api/meshAnalysis'
import { listVehicleMrs } from '../../api/railTransitBaseData'
import { exportMeshAnalysisReport, getRailTransitTask, recoverRailTransitTasks } from '../../api/railTransitWeb'
import type { MeshAnalysisParamsOverride } from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import type {
  MeshActiveBuildOrder, MeshAnalysisParams, MeshAnalysisSession, MeshAnalysisSummary, MeshArtifact, MeshBundleImportRequest, MeshBundleMapping, MeshBundlePreview,
  MeshChartEvent, MeshLinkDetail, MeshPathChart, MeshProfile, MeshRawSource, MeshRawTail, MeshSessionDetail, MeshSwitchEvent,
} from '../../types/meshAnalysis'
import type { VehicleMr } from '../../types/railTransitBaseData'
import type { RailTransitTask } from '../../types/railTransitWeb'
import { downloadBackendResource } from '../../platform/runtime'
import { loadUiPreference, saveUiPreference } from '../../platform/uiPreferences'

const router = useRouter()
const { confirm } = useConfirm()
const loading = ref(false)
const detailLoading = ref(false)
const detailSectionError = ref('')
const error = ref('')
const summary = ref<MeshAnalysisSummary | null>(null)
const sessions = ref<MeshAnalysisSession[]>([])
const total = ref(0)
const selected = ref<MeshSessionDetail | null>(null)
const buildOrders = ref<MeshActiveBuildOrder[]>([])
const buildOrderVisits = ref<MeshActiveBuildOrder[]>([])
const buildOrderTotal = ref(0)
const links = ref<MeshLinkDetail[]>([])
const linkTotal = ref(0)
const switches = ref<MeshSwitchEvent[]>([])
const rssiActivePath = ref<MeshPathChart | null>(null)
const rssiPeerPath = ref<MeshPathChart | null>(null)
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
const profileLoadError = ref('')
const vehicleMrLoadError = ref('')
const selectedFiles = ref<File[]>([])
const newProfileName = ref('')
const linkedMrId = ref('')
const profileNotes = ref('')
const task = ref<RailTransitTask | null>(null)
const taskLoading = ref(false)
const buildOrderTableHost = ref<HTMLElement | null>(null)
const linkTableHost = ref<HTMLElement | null>(null)
const rssiChartHost = ref<HTMLElement | null>(null)
const busyChartHost = ref<HTMLElement | null>(null)
const rssiChartRef = ref<MeshChartHandle | null>(null)
const busyChartRef = ref<MeshChartHandle | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const activeTab = ref('build-order')
const rssiMode = ref<'peer' | 'active'>('active')
const busyMode = ref<'active' | 'peer'>('active')
const showRssiPeer = ref(false)
const showSwitchLines = ref(false)
const showSwitchPoints = ref(true)
const showLocationBand = ref(true)
const meshPreferenceReady = ref(false)
const showBusyPeer = ref(false)
const visiblePoints = ref(600)
const chartRadio = ref<number | null>(null)
const selectedSegment = ref<MeshActiveBuildOrder | null>(null)
const allPeerVisits = ref(false)
const selectedChartEvent = ref<MeshChartEvent | null>(null)
const focusTimestamp = ref('')
const rssiViewport = ref<MeshChartViewport | null>(null)
const busyViewport = ref<MeshChartViewport | null>(null)
interface MeshLockedAnalysisRange extends MeshChartViewport {
  session_id: string
  source_file_id: number
  radio: number | null
  mode: 'active' | 'peer'
  anchor_link_id: number | null
  all_visits: boolean
  first_sample_time: string | null
  last_sample_time: string | null
  sample_count: number
  created_at: string
}
const lockedAnalysisRange = ref<MeshLockedAnalysisRange | null>(null)
const sessionExpandedKey = 'netconsole.mesh-analysis.session-expanded'
const sessionExpanded = ref(true)
const loadedTabs = reactive<Record<string, boolean>>({})
const warningsExpanded = ref(false)
const bundlePreview = ref<MeshBundlePreview | null>(null)
const bundleMappings = reactive<Record<string, Omit<MeshBundleMapping, 'role'> & { role: '' | 'CT' | 'CW'; confirmed: boolean }>>({})
const bundlePreviewLoading = ref(false)
const filters = reactive({ query: '', mr_role: '', has_warning: '' as '' | 'true' | 'false', page: 1, page_size: 50 })
const buildOrderFilters = reactive({ page: 1, page_size: 100, sort_order: 'desc', radio: '', peer: '', station: '', build_result: '', pingpong_only: false })
const linkFilters = reactive({ query: '', link_role: '', page: 1, page_size: 100, sort_order: 'asc' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let failureCount = 0
let taskTimer: ReturnType<typeof setTimeout> | null = null
let detailGeneration = 0
let rssiChartGeneration = 0
let busyChartGeneration = 0
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const restorableTaskStates = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'FAILED'])
const taskStorageKey = 'netconsole.mesh-analysis.last-task'
const buildOrderPanel = useAvailablePanelHeight(buildOrderTableHost, { minHeight: 420, bottomGap: 72 })
const linkPanel = useAvailablePanelHeight(linkTableHost, { minHeight: 420, bottomGap: 72 })
const rssiPanel = useAvailablePanelHeight(rssiChartHost, { minHeight: 360, bottomGap: 96 })
const busyPanel = useAvailablePanelHeight(busyChartHost, { minHeight: 360, bottomGap: 48 })

const cards = computed(() => summary.value ? [
  ['分析会话', summary.value.session_count], ['列车 / MR', `${summary.value.train_count} / ${summary.value.mr_count}`],
  ['链路记录', display(summary.value.link_record_count)], ['主 / 备链路', `${display(summary.value.active_link_count)} / ${display(summary.value.standby_link_count)}`],
  ['切换事件', display(summary.value.switch_event_count)], ['短时建链', display(summary.value.short_link_count)],
  ['乒乓切换', display(summary.value.pingpong_count)], ['未匹配 AP', display(summary.value.unmatched_ap_count)],
] : [])
const taskActive = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const taskProgress = computed(() => task.value?.status === 'COMPLETED' ? 100 : 0)
const taskSummary = computed(() => {
  if (!task.value) return ''
  if (task.value.error_message) return task.value.error_message
  if (task.value.message) return task.value.message
  const count = Object.keys(task.value.result_summary || {}).length
  return count ? `已生成 ${count} 项结构化结果，完整内容请在任务中心查看。` : '完整日志、结果与 Artifact 请在任务中心查看。'
})
const selectedSource = computed(() => selected.value?.sources[0] || null)
const bundleCanApply = computed(() => Boolean(
  bundlePreview.value
  && bundlePreview.value.items.length > 0
  && Object.values(bundleMappings).length === bundlePreview.value.items.length
  && Object.values(bundleMappings).every((mapping) => mapping.confirmed && mapping.member_id && mapping.train_number.trim() && mapping.role && mapping.profile_id),
))
const bundleValidationMessage = computed(() => {
  if (!bundlePreview.value) return 'ZIP 尚未预览。'
  const unresolved = bundlePreview.value.items.filter((item) => {
    const mapping = bundleMappings[item.safe_name]
    return !mapping?.confirmed || !mapping.train_number.trim() || !mapping.role || !mapping.profile_id
  })
  return unresolved.length ? `还有 ${unresolved.length} 个文件未完成列车号、端位、对应车载 MR 和人工确认。` : '所有文件已确认，可导入并分析。'
})
const linkTimeGroups = computed(() => buildMeshTimeGroupClasses(links.value, (row) => `${row.timestamp}::${row.timestamp_tag || ''}`))
const switchTimeGroups = computed(() => buildMeshTimeGroupClasses(switches.value, (row) => row.timestamp))
const chartData = computed(() => rssiMode.value === 'peer' ? rssiPeerPath.value : rssiActivePath.value)
const busyChartData = computed(() => busyMode.value === 'peer' ? busyPeerPath.value : busyActivePath.value)
const busyValidSampleCount = computed(() => (busyChartData.value?.points || []).filter((point) => (
  point.local_tx_busy != null || point.local_rx_busy != null || point.peer_tx_busy != null || point.peer_rx_busy != null
)).length)
const lockedRangeLabel = computed(() => lockedAnalysisRange.value
  ? `${lockedAnalysisRange.value.start_time} — ${lockedAnalysisRange.value.end_time}`
  : '')
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
  { key: 'actions', label: '操作', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]
const buildOrderColumns: NcTableColumn<MeshActiveBuildOrder>[] = [
  { key: 'sequence', label: '序号', valueType: 'number', width: 75, fixed: 'left', hideable: false },
  { key: 'local_radio', label: 'Radio', valueType: 'number', width: 80, fixed: 'left', hideable: false },
  { key: 'active_peer_mac', label: 'Active PeerMac', valueType: 'mac', minWidth: 150, fixed: 'left', hideable: false },
  { key: 'peer_ap_name', label: '当前 PEER AP 名称', valueType: 'name', minWidth: 175, hideable: false },
  { key: 'peer_ap_mac', label: 'AP MAC', valueType: 'mac', minWidth: 145 },
  { key: 'station', label: '归属站点', minWidth: 120 },
  { key: 'section', label: '归属区间', minWidth: 145 },
  { key: 'peer_radio', label: 'Peer Radio', minWidth: 105 },
  { key: 'peer_radio_mac', label: 'Peer Radio MAC', valueType: 'mac', minWidth: 145 },
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
  { key: 'main_link_switch_time_ms', label: '主链路切换基准(ms)', valueType: 'duration', minWidth: 155, visible: false },
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
  { key: 'timestamp', label: '采样时间', valueType: 'datetime', minWidth: 215, fixed: 'left', hideable: false },
  { key: 'timestamp_tag', label: '采样标识', minWidth: 120, fixed: 'left' },
  { key: 'local_radio', label: 'Radio', valueType: 'number', width: 80, fixed: 'left', hideable: false },
  { key: 'link_role', label: '状态', width: 90, fixed: 'left', hideable: false },
  { key: 'peer_mac', label: 'PeerMac', valueType: 'mac', minWidth: 145, hideable: false },
  { key: 'peer_ap_name', label: '当前 PEER AP 名称', valueType: 'name', minWidth: 175 },
  { key: 'local_rssi_db', label: 'MR 侧 RSSI 差值', valueType: 'number', minWidth: 130 },
  { key: 'peer_rssi_db', label: 'Peer 侧 RSSI 差值', valueType: 'number', minWidth: 140 },
  { key: 'peer_ap_mac', label: 'AP MAC', valueType: 'mac', minWidth: 145 },
  { key: 'station', label: '归属站点', width: 130 },
  { key: 'section', label: '归属区间', width: 150 },
  { key: 'peer_radio', label: 'PEER Radio', minWidth: 105 },
  { key: 'peer_radio_mac', label: 'Peer Radio MAC', valueType: 'mac', minWidth: 145 },
  { key: 'establish_time', label: '建链时间', valueType: 'datetime', minWidth: 210 },
  { key: 'duration_text', label: '链路时长', minWidth: 110 },
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
  { key: 'is_short_link', label: '短时', width: 75, displayValue: (row) => row.is_short_link ? '是' : '否' },
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

async function restoreMeshPreferences(): Promise<void> {
  const [lines, points, band] = await Promise.all([
    loadUiPreference('mesh-analysis-rssi.show-switch-lines', false),
    loadUiPreference('mesh-analysis-rssi.show-switch-points', true),
    loadUiPreference('mesh-analysis-rssi.show-location-band', true),
  ])
  showSwitchLines.value = typeof lines === 'boolean' ? lines : false
  showSwitchPoints.value = typeof points === 'boolean' ? points : true
  showLocationBand.value = typeof band === 'boolean' ? band : true
  meshPreferenceReady.value = true
}

watch([showSwitchLines, showSwitchPoints, showLocationBand], ([lines, points, band]) => {
  if (!meshPreferenceReady.value) return
  void Promise.all([
    saveUiPreference('mesh-analysis-rssi.show-switch-lines', lines),
    saveUiPreference('mesh-analysis-rssi.show-switch-points', points),
    saveUiPreference('mesh-analysis-rssi.show-location-band', band),
  ]).catch(() => ElMessage.warning('RSSI 图显示偏好保存失败，当前设置仅保留在本次运行。'))
})

onMounted(async () => { await Promise.all([restoreMeshPreferences(), refreshOverview(), recoverTask()]); scheduleRefresh() })
onBeforeUnmount(() => { if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = null; stopTaskPolling() })
watch(activeTab, (tab) => {
  if (selected.value) void loadTab(tab)
  refreshDetailPanels()
})
watch(sessionExpanded, refreshDetailPanels)

function scheduleRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(async () => {
    if (document.visibilityState === 'visible') await refreshOverview(true)
    scheduleRefresh()
  }, failureCount >= 3 ? 90_000 : 30_000)
}

async function refreshOverview(silent = false): Promise<void> {
  if (loading.value) return
  loading.value = !silent
  try {
    const [nextSummary, page] = await Promise.all([
      getMeshAnalysisSummary(),
      listMeshAnalysisSessions({ ...filters, has_warning: filters.has_warning === '' ? null : filters.has_warning === 'true' }),
    ])
    summary.value = nextSummary
    sessions.value = page.items
    total.value = page.total
    error.value = ''
    failureCount = 0
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Mesh 分析结果加载失败'
    failureCount += 1
  } finally { loading.value = false }
}

async function openSession(row: MeshAnalysisSession): Promise<void> {
  const generation = ++detailGeneration
  detailLoading.value = true
  selected.value = null; buildOrders.value = []; buildOrderVisits.value = []; buildOrderTotal.value = 0; links.value = []; linkTotal.value = 0; switches.value = []
  rssiActivePath.value = null; rssiPeerPath.value = null; busyActivePath.value = null; busyPeerPath.value = null
  selectedSegment.value = null; focusTimestamp.value = ''; chartRadio.value = null; rssiViewport.value = null; busyViewport.value = null
  lockedAnalysisRange.value = null; allPeerVisits.value = false; selectedChartEvent.value = null; rssiChartGeneration += 1; busyChartGeneration += 1
  artifacts.value = []; rawTail.value = null; detailSectionError.value = ''
  for (const key of Object.keys(loadedTabs)) delete loadedTabs[key]
  activeTab.value = 'build-order'
  try {
    const id = row.session_id
    const detail = await getMeshAnalysisSession(id)
    if (generation !== detailGeneration) return
    selected.value = detail
    restoreSessionExpansionForDetail()
    await loadBuildOrders(generation)
    refreshDetailPanels()
    error.value = ''
  } catch (reason) { if (generation === detailGeneration) error.value = reason instanceof Error ? reason.message : '分析详情加载失败' }
  finally { if (generation === detailGeneration) detailLoading.value = false }
}

function setSessionExpanded(value: boolean): void {
  sessionExpanded.value = value
  sessionStorage.setItem(sessionExpandedKey, String(value))
}

function restoreSessionExpansionForDetail(): void {
  const preference = sessionStorage.getItem(sessionExpandedKey)
  sessionExpanded.value = preference === null ? false : preference === 'true'
}

async function loadBuildOrders(generation = detailGeneration, page = buildOrderFilters.page): Promise<void> {
  if (!selected.value) return
  buildOrderFilters.page = page
  const result = await listMeshActiveBuildOrder(selected.value.session.session_id, {
    ...buildOrderFilters,
    radio: buildOrderFilters.radio || null,
    peer: buildOrderFilters.peer || null,
    station: buildOrderFilters.station || null,
    build_result: buildOrderFilters.build_result || null,
    pingpong_only: buildOrderFilters.pingpong_only || null,
  })
  if (generation !== detailGeneration) return
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

async function loadTab(tab: string): Promise<void> {
  if (tab === 'busy' && selected.value && lockedAnalysisRange.value) {
    applyLockedBusyContext(lockedAnalysisRange.value)
    await loadCurrentMetricChart('busy', lockedAnalysisRange.value)
    loadedTabs.busy = true
    return
  }
  if (!selected.value || loadedTabs[tab]) {
    if (tab === 'rssi' && !(rssiMode.value === 'peer' ? rssiPeerPath.value : rssiActivePath.value)) await loadCurrentMetricChart('rssi')
    if (tab === 'busy' && !(busyMode.value === 'peer' ? busyPeerPath.value : busyActivePath.value)) await loadCurrentMetricChart('busy', lockedAnalysisRange.value)
    return
  }
  const generation = detailGeneration
  detailLoading.value = true
  detailSectionError.value = ''
  try {
    const id = selected.value.session.session_id
    if (tab === 'build-order') await loadBuildOrders(generation)
    else if (tab === 'links') await reloadLinks(1, generation)
    else if (tab === 'rssi') await loadCurrentMetricChart('rssi', null, generation)
    else if (tab === 'busy') await loadCurrentMetricChart('busy', lockedAnalysisRange.value, generation)
    else if (tab === 'switches') {
      const result = await listMeshSwitchEvents(id, { page: 1, page_size: 500 })
      if (generation === detailGeneration) switches.value = result.items
    } else if (tab === 'artifacts') {
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

type MeshChartMetric = 'rssi' | 'busy'

function nextChartGeneration(metric: MeshChartMetric): number {
  if (metric === 'rssi') return ++rssiChartGeneration
  return ++busyChartGeneration
}

function isLatestChartRequest(metric: MeshChartMetric, generation: number): boolean {
  return generation === (metric === 'rssi' ? rssiChartGeneration : busyChartGeneration)
}

async function loadActivePath(
  metric: MeshChartMetric,
  range: MeshLockedAnalysisRange | null = null,
  generation = detailGeneration,
): Promise<void> {
  if (!selected.value) return
  const requestGeneration = nextChartGeneration(metric)
  const result = await getMeshActivePathChart(selected.value.session.session_id, {
    max_points: visiblePoints.value,
    radio: range?.radio ?? chartRadio.value,
    time_from: range?.start_time,
    time_to: range?.end_time,
  })
  if (generation !== detailGeneration || !isLatestChartRequest(metric, requestGeneration)) return
  if (metric === 'rssi') rssiActivePath.value = result
  else busyActivePath.value = result
}

async function loadPeerPath(
  metric: MeshChartMetric,
  anchorLinkId = selectedSegment.value?.anchor_link_id,
  range: MeshLockedAnalysisRange | null = null,
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
  if (metric === 'rssi') rssiPeerPath.value = result
  else busyPeerPath.value = result
}

async function loadCurrentMetricChart(
  metric: MeshChartMetric,
  range: MeshLockedAnalysisRange | null = null,
  generation = detailGeneration,
): Promise<void> {
  const mode = range?.mode ?? (metric === 'rssi' ? rssiMode.value : busyMode.value)
  if (mode === 'peer') await loadPeerPath(metric, range?.anchor_link_id ?? selectedSegment.value?.anchor_link_id, range, generation)
  else await loadActivePath(metric, range, generation)
}

async function reloadCurrentChart(): Promise<void> {
  const metric: MeshChartMetric = activeTab.value === 'busy' ? 'busy' : 'rssi'
  await loadCurrentMetricChart(metric, metric === 'busy' ? lockedAnalysisRange.value : null)
}

function resetCurrentChartViewport(): void {
  if (activeTab.value === 'busy') busyChartRef.value?.resetViewport()
  else rssiChartRef.value?.resetViewport()
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
  rssiViewport.value = viewport
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
  const samples = visibleMeshSamples(chartData.value?.points || [], viewport)
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
    mode: rssiMode.value,
    anchor_link_id: rssiMode.value === 'peer' ? selectedSegment.value?.anchor_link_id ?? null : null,
    all_visits: rssiMode.value === 'peer' && allPeerVisits.value,
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
  void nextTick(() => { if (rssiViewport.value) rssiChartRef.value?.applyViewport(rssiViewport.value) })
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
  rssiPeerPath.value = null
  busyPeerPath.value = null
  if (value === 'all-visits') {
    if (!selectedSegment.value && buildOrderOptions.value[0]) selectedSegment.value = buildOrderOptions.value[0]
    allPeerVisits.value = true
    await loadPeerPath(activeTab.value === 'busy' ? 'busy' : 'rssi')
    return
  }
  const row = buildOrderOptions.value.find((item) => item.anchor_link_id === Number(value))
  if (!row) return
  selectedSegment.value = row
  allPeerVisits.value = false
  chartRadio.value = row.local_radio
  focusTimestamp.value = row.build_start_time
  await loadPeerPath(activeTab.value === 'busy' ? 'busy' : 'rssi', row.anchor_link_id)
}

async function changeRssiMode(value: string | number): Promise<void> {
  clearTimeLock()
  rssiViewport.value = null
  if (value !== 'peer') { await loadActivePath('rssi'); return }
  await loadBuildOrderVisits()
  if (!selectedSegment.value && buildOrderOptions.value[0]) selectedSegment.value = buildOrderOptions.value[0]
  allPeerVisits.value = false
  await loadPeerPath('rssi')
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
  clearTimeLock()
  rssiViewport.value = null
  busyViewport.value = null
  rssiActivePath.value = null
  busyActivePath.value = null
  await reloadCurrentChart()
}

async function selectBuildOrder(row: MeshActiveBuildOrder, showChart = false): Promise<void> {
  clearTimeLock()
  selectedSegment.value = row
  allPeerVisits.value = false
  chartRadio.value = row.local_radio
  focusTimestamp.value = row.build_start_time
  if (!showChart) return
  rssiMode.value = 'peer'
  activeTab.value = 'rssi'
  await loadBuildOrderVisits()
  await loadPeerPath('rssi', row.anchor_link_id)
  await nextTick()
  document.querySelector('.detail-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function showLinkChart(row: MeshLinkDetail): Promise<void> {
  clearTimeLock()
  focusTimestamp.value = row.timestamp
  allPeerVisits.value = false
  chartRadio.value = row.local_radio
  rssiMode.value = 'peer'
  activeTab.value = 'rssi'
  await loadBuildOrderVisits()
  await loadPeerPath('rssi', row.record_id)
}

function selectChartSwitch(event: MeshChartEvent): void {
  selectedChartEvent.value = event
  focusTimestamp.value = event.timestamp
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
  profileLoadError.value = ''
  vehicleMrLoadError.value = ''
  const loadMeshProfiles = async (): Promise<void> => {
    try {
      profiles.value = await listMeshProfiles()
    } catch (reason) {
      profileLoadError.value = reason instanceof Error ? reason.message : 'MESH Profile 加载失败'
    }
  }
  const loadVehicleMrs = async (): Promise<void> => {
    try {
      const rows: VehicleMr[] = []
      let page = 1
      while (true) {
        const result = await listVehicleMrs({ page, page_size: 200 })
        rows.push(...result.items)
        if (rows.length >= result.total || result.items.length === 0) break
        page += 1
      }
      baseMrs.value = rows
    } catch (reason) {
      vehicleMrLoadError.value = reason instanceof Error ? reason.message : '当前局点车载 MR 加载失败'
    }
  }
  await Promise.allSettled([loadMeshProfiles(), loadVehicleMrs()])
}
async function openImportDialog(): Promise<void> {
  importVisible.value = true
  importContextLoading.value = true
  importContextError.value = ''
  profileLoadError.value = ''
  vehicleMrLoadError.value = ''
  try {
    await prepareMeshImportContext()
  } catch (reason) {
    importContextError.value = reason instanceof Error ? reason.message : '车载 MR 与内部 MESH 归属同步失败'
  } finally {
    await loadProfiles()
    importContextLoading.value = false
  }
}
async function createProfile(): Promise<void> {
  if (!newProfileName.value.trim()) return
  taskLoading.value = true; error.value = ''
  try {
    const profile = await createMeshProfile({ display_name: newProfileName.value.trim(), linked_mr_id: linkedMrId.value, notes: profileNotes.value.trim() })
    await loadProfiles(); newProfileName.value = ''; linkedMrId.value = ''; profileNotes.value = ''
    ElMessage.success('内部 MESH 归属已创建')
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '内部 MESH 归属创建失败' }
  finally { taskLoading.value = false }
}
function isSafeRelativePath(value: string): boolean {
  const normalized = value.replaceAll('\\', '/')
  return !normalized.startsWith('/') && !/^[A-Za-z]:\//.test(normalized) && !normalized.split('/').includes('..')
}
function chooseFiles(event: Event): void {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  selectedFiles.value = files.filter((file) => {
    const name = file.name.toLowerCase()
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || name
    return ['.zip', '.log', '.txt', '.gz'].some((suffix) => name.endsWith(suffix)) && isSafeRelativePath(relative)
  })
  bundlePreview.value = null
  for (const key of Object.keys(bundleMappings)) delete bundleMappings[key]
  if (selectedFiles.value.length) void previewImportFiles()
}
async function previewImportFiles(): Promise<void> {
  bundlePreviewLoading.value = true
  error.value = ''
  try {
    const preview = await previewMeshImport(selectedFiles.value)
    bundlePreview.value = preview
    for (const item of preview.items) {
      const firstCandidate = item.selected_profile_id || item.candidates[0]?.profile_id || ''
      bundleMappings[item.safe_name] = {
        member_id: item.member_id,
        train_number: item.train_number,
        role: item.role === 'CT' || item.role === 'CW' ? item.role : '',
        profile_id: firstCandidate,
        confirmed: item.match_status === 'matched' && Boolean(firstCandidate) && Boolean(item.train_number) && Boolean(item.role),
      }
    }
  } catch (reason) {
    bundlePreview.value = null
    error.value = reason instanceof Error ? reason.message : 'MESH ZIP 预览失败'
  } finally { bundlePreviewLoading.value = false }
}
function profileCandidates(item: MeshBundlePreview['items'][number]): Array<{ profile_id: string; display_name: string }> {
  return item.candidates.length ? item.candidates : profiles.value.map((profile) => ({ profile_id: profile.mr_id, display_name: profile.display_name }))
}
function rememberTask(value: RailTransitTask | null): void {
  task.value = value
  if (value && !terminalStates.has(value.status)) localStorage.setItem(taskStorageKey, value.task_id)
  else localStorage.removeItem(taskStorageKey)
}
function stopTaskPolling(): void { if (taskTimer) clearTimeout(taskTimer); taskTimer = null }
async function afterTask(): Promise<void> {
  if (task.value?.status !== 'COMPLETED') return
  await refreshOverview()
  if (['mesh_log_import', 'mesh_bundle_import', 'mesh_schema_rebuild', 'mesh_source_rebuild'].includes(task.value.action)) await loadProfiles()
  const created = Array.isArray(task.value.result_summary.created_session_ids)
    ? task.value.result_summary.created_session_ids.filter((item): item is string => typeof item === 'string')
    : []
  const targetId = created[0]
  if (targetId) {
    const target = sessions.value.find((item) => item.session_id === targetId) || { session_id: targetId } as MeshAnalysisSession
    await openSession(target)
    activeTab.value = 'build-order'
    requestAnimationFrame(() => document.querySelector('.detail-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    return
  }
  if (selected.value) {
    const selectedId = selected.value.session.session_id
    const next = sessions.value.find((item) => item.session_id === selectedId)
    if (['mesh_schema_rebuild', 'mesh_source_rebuild'].includes(task.value.action) && next) await openSession(next)
    else artifacts.value = await listMeshArtifacts(selectedId)
  }
}
function pollTask(): void {
  stopTaskPolling()
  if (!task.value || terminalStates.has(task.value.status)) { void afterTask(); return }
  taskTimer = setTimeout(async () => {
    try { rememberTask(await getRailTransitTask(task.value!.task_id)); pollTask() }
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
function startBundleImport(): void {
  if (!bundlePreview.value || !bundleCanApply.value) return
  const payload: MeshBundleImportRequest = {
    preview_id: bundlePreview.value.preview_id,
    mappings: Object.values(bundleMappings).map(({ confirmed: _confirmed, ...mapping }) => ({ ...mapping, role: mapping.role as 'CT' | 'CW' })),
    explicit_confirmation: true,
  }
  void startTask(() => applyMeshBundleImport(payload), 'MESH ZIP 导入启动失败')
  importVisible.value = false
}
function assignAnalysisParams(target: MeshAnalysisParams, value: MeshAnalysisParams): void {
  Object.assign(target, value)
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

function openReportDialog(): void {
  if (!selected.value) return
  assignAnalysisParams(reportParams, selected.value.analysis_params)
  useTemporaryReportParams.value = false
  reportVisible.value = true
}

function generateReport(): void {
  if (!selected.value) return
  const override = useTemporaryReportParams.value ? { ...reportParams } : undefined
  reportVisible.value = false
  void startTask(() => exportMeshAnalysisReport(selected.value!.session.session_id, override), 'MESH 分析报告生成启动失败')
}
function openLinkExportDialog(): void {
  if (!selected.value) return
  assignAnalysisParams(linkExportParams, selected.value.analysis_params)
  linkExportVisible.value = true
}

function exportLinkDetails(): void {
  const sourceFileId = selectedSource.value?.source_file_id
  if (!selected.value || typeof sourceFileId !== 'number' || !Number.isInteger(sourceFileId) || sourceFileId <= 0) {
    ElMessage.error('当前来源缺少正式 source_file_id，请刷新或重新解析后再试。')
    return
  }
  linkExportVisible.value = false
  ElMessage.info('正在提交链路明细导出任务')
  void startTask(
    () => exportMeshLinkDetails(selected.value!.session.session_id, sourceFileId, { ...linkExportParams }),
    'MESH 链路明细导出启动失败',
  ).then((created) => {
    if (created) ElMessage.success(`链路明细导出任务已创建：${created.task_id}`)
  })
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
async function recoverTask(): Promise<void> {
  try {
    const saved = localStorage.getItem(taskStorageKey) || ''
    const rows = await recoverRailTransitTasks()
    const meshRows = rows.filter((item) => ['mesh_log_import', 'mesh_bundle_import', 'mesh_schema_rebuild', 'mesh_source_rebuild', 'mesh_analysis_report', 'mesh_link_detail_export'].includes(item.action))
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
  void nextTick(() => {
    buildOrderPanel.refresh()
    linkPanel.refresh()
    rssiPanel.refresh()
    busyPanel.refresh()
  })
}

function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function formatBytes(value: number): string { if (!value) return '0 B'; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 ** 2).toFixed(1)} MB` }
function severityType(value: string): 'error' | 'warning' | 'info' { return value === 'error' || value === 'critical' ? 'error' : value === 'warning' ? 'warning' : 'info' }
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
  return ({ normal: '正常', short: '短时建链', same_ap_radio_switch: '同 AP 双射频切换', pingpong_abnormal: 'AP 乒乓切换异常', critical_return: '临界回切', boundary: '边界区段' } as Record<string, string>)[value] || value
}
</script>

<template>
  <section class="mesh-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · OFFLINE MESH ANALYSIS</p><h1>Mesh 原始日志分析</h1><p>选择日志后自动匹配当前局点车载 MR，并完成归档、解析、分析和报告交付。</p></div>
      <div class="jump-actions"><el-button :loading="importContextLoading" :disabled="!isFeatureEnabled('web.mesh_analysis_import')" @click="openImportDialog">导入原始 MESH 日志</el-button><el-button :icon="Download" :loading="taskLoading" :disabled="!selected || !selectedSource || selected.session.parsed_status !== 'ready' || !isFeatureEnabled('web.mesh_analysis_report_export')" @click="openLinkExportDialog">导出链路明细</el-button><el-button :icon="Document" type="primary" :loading="taskLoading" :disabled="!selected || ['missing','unreadable'].includes(selected.session.parsed_status) || !isFeatureEnabled('web.mesh_analysis_report_export')" @click="openReportDialog">生成分析报告</el-button><el-button :loading="loading" @click="refreshOverview()">刷新结果</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <el-dialog v-model="importVisible" title="MESH 原始日志导入" width="min(1180px, 96vw)">
      <el-form label-position="top">
        <el-alert v-if="importContextError" :title="`导入上下文准备失败：${importContextError}`" type="error" :closable="false" show-icon />
        <el-alert v-if="profileLoadError" :title="`内部 MESH 归属加载失败：${profileLoadError}`" type="error" :closable="false" show-icon />
        <el-alert v-if="vehicleMrLoadError" :title="`车载 MR 加载失败：${vehicleMrLoadError}`" type="error" :closable="false" show-icon />
        <el-alert v-if="!importContextLoading && !vehicleMrLoadError && baseMrs.length === 0" title="当前局点没有可识别的车载 MR，请先在设备管理的“车载-MR”分组登记设备。" type="warning" :closable="false" show-icon />
        <el-form-item label="选择原始日志或 ZIP">
          <div class="jump-actions"><el-button @click="fileInput?.click()">选择 ZIP / LOG / GZ 文件</el-button><el-button @click="folderInput?.click()">选择文件夹</el-button><span>已选择 {{ selectedFiles.length }} 个文件</span></div>
          <input ref="fileInput" class="hidden-input" type="file" multiple accept=".zip,.log,.txt,.gz" @change="chooseFiles"><input ref="folderInput" class="hidden-input" type="file" multiple webkitdirectory @change="chooseFiles">
        </el-form-item>
        <el-alert v-if="bundlePreviewLoading" title="正在识别日志并匹配当前局点车载 MR…" type="info" :closable="false" show-icon />
        <template v-if="bundlePreview">
          <el-divider content-position="left">日志自动映射</el-divider>
          <el-alert :title="bundleValidationMessage" :type="bundleCanApply ? 'success' : 'warning'" :closable="false" show-icon />
          <div class="bundle-table-wrap">
            <table class="bundle-table"><thead><tr><th>日志文件</th><th>列车号</th><th>端位</th><th>对应车载 MR</th><th>状态</th><th>确认</th></tr></thead><tbody>
              <tr v-for="item in bundlePreview.items" :key="item.safe_name">
                <td><strong>{{ item.safe_name }}</strong><small>{{ item.size_bytes }} B · {{ item.sha256.slice(0, 12) }}…</small></td>
                <td><el-input v-model="bundleMappings[item.safe_name].train_number" size="small" @input="bundleMappings[item.safe_name].confirmed = false" /></td>
                <td><el-select v-model="bundleMappings[item.safe_name].role" size="small" @change="bundleMappings[item.safe_name].confirmed = false"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select></td>
                <td><el-select v-model="bundleMappings[item.safe_name].profile_id" filterable size="small" @change="bundleMappings[item.safe_name].confirmed = false"><el-option v-for="candidate in profileCandidates(item)" :key="candidate.profile_id" :label="candidate.display_name" :value="candidate.profile_id" /></el-select></td>
                <td><el-tag :type="item.match_status === 'matched' ? 'success' : 'warning'">{{ item.match_status }}</el-tag></td>
                <td><el-checkbox v-model="bundleMappings[item.safe_name].confirmed" :disabled="!bundleMappings[item.safe_name].train_number.trim() || !bundleMappings[item.safe_name].role || !bundleMappings[item.safe_name].profile_id">人工确认</el-checkbox></td>
              </tr>
            </tbody></table>
          </div>
        </template>
        <el-collapse><el-collapse-item title="高级：无法匹配时创建内部归属" name="advanced-profile"><div class="profile-grid"><el-form-item label="显示名称"><el-input v-model="newProfileName" placeholder="例如：列车01-MR-CT" /></el-form-item><el-form-item label="关联基础资料 MR（可选）"><el-select v-model="linkedMrId" clearable filterable><el-option v-for="mr in baseMrs" :key="mr.id" :label="`${mr.train_no} · ${mr.role} · ${mr.name}`" :value="mr.id" /></el-select></el-form-item><el-form-item label="备注"><el-input v-model="profileNotes" /></el-form-item></div><el-button :loading="taskLoading" :disabled="!newProfileName.trim()" @click="createProfile">创建内部归属</el-button></el-collapse-item></el-collapse>
      </el-form>
      <template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :loading="taskLoading" :disabled="!bundleCanApply" @click="startBundleImport">确认导入并分析</el-button></template>
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
            <el-form-item label="主链路切换基准 (ms)"><el-input-number v-model="reportParams.main_link_switch_time_ms" :min="1" :max="600000" /></el-form-item>
            <el-form-item label="短时建链容差 (ms)"><el-input-number v-model="reportParams.short_link_tolerance_ms" :min="0" :max="600000" /></el-form-item>
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
        <el-alert title="链路明细与综合报告使用同一链路分析参数；本次覆盖不会修改来源快照。" type="info" :closable="false" show-icon />
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

    <section class="content-card sessions-panel" v-loading="loading">
      <button class="sessions-toggle" type="button" :aria-expanded="sessionExpanded" @click="setSessionExpanded(!sessionExpanded)">
        <el-icon><ArrowDown v-if="sessionExpanded" /><ArrowRight v-else /></el-icon>
        <strong>分析会话 · {{ total }} 个来源 · {{ summary?.train_count ?? 0 }} 列车 / {{ summary?.mr_count ?? 0 }} MR</strong>
        <span v-if="selected">当前：{{ selected.session.mr_name }} · {{ selected.session.original_filename }}</span>
        <el-tag v-if="task" size="small">任务 {{ task.status }}</el-tag>
      </button>
      <template v-if="sessionExpanded">
        <div v-if="task" class="task-card">
          <div class="task-line">
            <div class="task-copy"><strong>{{ task.action }}</strong><span>{{ task.task_id }}</span></div>
            <el-tag>{{ task.status }}</el-tag>
            <el-button link type="primary" @click="openTaskWindow()">打开任务中心</el-button>
          </div>
          <el-progress v-if="taskActive" :percentage="taskProgress" :indeterminate="true" :duration="2" :show-text="false" />
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
        </div>
        <NcDataTable table-id="mesh-analysis-sessions:v2" route-key="/rail-transit/mesh-analysis" :data="sessions" :columns="sessionColumns" border height="340" empty-text="暂无已持久化 Mesh 分析来源" @row-dblclick="openSession">
          <template #cell-warnings="{ row }"><el-tag :type="row.warning_count ? 'warning' : 'success'">{{ row.warning_count }}</el-tag></template>
          <template #cell-actions="{ row }"><el-button link type="primary" @click="openSession(row)">查看</el-button></template>
        </NcDataTable>
        <div class="pagination"><span>共 {{ total }} 个来源</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="total" @current-change="(page: number) => { filters.page = page; refreshOverview() }" /></div>
      </template>
    </section>

    <div v-if="selected" class="content-card detail-card" v-loading="detailLoading">
      <div class="detail-heading">
        <div><h2>{{ selected.session.mr_name }}</h2><p>{{ selected.session.original_filename }} · {{ selected.session.first_sample_time }} — {{ selected.session.last_sample_time }}</p></div>
        <div class="jump-actions">
          <el-button :loading="taskLoading" :disabled="!selectedSource || ['raw_missing','task_running','unsupported'].includes(selectedSource.rebuild_capability) || !isFeatureEnabled('web.mesh_analysis_import')" @click="rebuildSelected">{{ selectedSource?.rebuild_capability === 'recoverable_from_bundle' ? '恢复原始日志并重新解析' : selected.session.parsed_status === 'ready' ? '重新解析当前日志' : '升级解析结果' }}</el-button>
          <el-button @click="openTaskWindow()">打开任务窗口</el-button>
          <el-button @click="router.push({ path: '/rail-transit/train-communication', query: { train: selected?.session.train_name } })">在线列车通信</el-button>
          <el-button @click="router.push('/rail-transit/online-mr')">Online MR</el-button>
          <el-button @click="router.push('/rail-transit/train-online')">列车在线情况</el-button>
        </div>
      </div>
      <div v-if="selected.warnings.length" class="warning-summary">
        <el-alert :title="`数据告警 ${selected.warnings.length} 条`" :type="severityType(selected.warnings[0]?.severity || 'warning')" :closable="false" show-icon>
          <template #default><el-button link type="primary" @click="warningsExpanded = !warningsExpanded">{{ warningsExpanded ? '收起详情' : '查看全部' }}</el-button></template>
        </el-alert>
        <div v-if="warningsExpanded" class="warning-list"><el-alert v-for="warning in selected.warnings" :key="warning.code" :title="warning.message" :type="severityType(warning.severity)" :closable="false" show-icon /></div>
      </div>
      <el-alert v-if="selectedSource && !selectedSource.exists" :title="selectedSource.missing_reason" :type="selectedSource.recoverable ? 'warning' : 'error'" :closable="false" show-icon />
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
            <NcDataTable table-id="mesh-analysis-active-build-order:v2" route-key="/rail-transit/mesh-analysis" :data="buildOrders" :columns="buildOrderColumns" :stripe="false" :row-class-name="buildOrderRowClass" border height="100%" @sort-change="sortBuildOrders" @row-click="selectBuildOrder" @row-dblclick="(row: MeshActiveBuildOrder) => selectBuildOrder(row, true)">
              <template #cell-build_result="{ row }"><el-tag :type="buildResultType(row.build_result)">{{ buildResultLabel(row.build_result) }}</el-tag></template>
              <template #cell-actions="{ row }"><el-button link type="primary" @click.stop="selectBuildOrder(row, true)">查看动态图</el-button></template>
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
          <el-tabs v-model="rssiMode" class="analysis-subtabs" @tab-change="changeRssiMode">
            <el-tab-pane label="单 AP / 分时段" name="peer" />
            <el-tab-pane label="全部 ACTIVE 主链路" name="active" />
          </el-tabs>
          <div class="chart-toolbar">
            <el-select v-if="rssiMode === 'peer'" :model-value="selectedVisitValue" filterable placeholder="选择 AP / 经过时段" @change="selectSegmentByAnchor">
              <el-option v-if="selectedSegment" label="全部经过时段（各区段断开）" value="all-visits" />
              <el-option v-for="row in buildOrderOptions" :key="row.anchor_link_id" :label="`第 ${row.sequence} 次 · Radio ${row.local_radio ?? '—'} · ${row.peer_ap_name || row.active_peer_mac} · ${row.build_start_time} — ${row.build_end_time}`" :value="row.anchor_link_id" />
            </el-select>
            <el-select v-if="rssiMode === 'active'" v-model="chartRadio" placeholder="选择 Radio" @change="changeChartRadio"><el-option v-for="radio in availableChartRadios" :key="radio" :label="`Radio ${radio}`" :value="radio" /></el-select>
            <el-select v-model="visiblePoints" @change="reloadCurrentChart"><el-option label="目标 120 点" :value="120" /><el-option label="目标 300 点" :value="300" /><el-option label="目标 600 点" :value="600" /><el-option label="目标 1200 点" :value="1200" /><el-option label="目标 2000 点（关键点优先）" :value="2000" /></el-select>
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
          <el-alert v-if="lockedAnalysisRange" :title="`已锁定 ${lockedRangeLabel} · Radio ${lockedAnalysisRange.radio ?? '全部'} · RSSI 可见采样 ${lockedAnalysisRange.sample_count} 点`" type="info" :closable="false" show-icon />
          <el-alert v-if="chartData?.downsample_warning" :title="chartData.downsample_warning" type="warning" :closable="false" show-icon />
          <div class="mini-summary"><span>当前 PeerMac <strong>{{ chartData?.summary.current_peer_mac || '—' }}</strong></span><span>当前 AP <strong>{{ chartData?.summary.current_peer_ap_name || '—' }}</strong></span><span>Radio <strong>{{ chartData?.summary.current_radio ?? '—' }}</strong></span><span>估算采样间隔 <strong>{{ display(chartData?.summary.estimated_interval_seconds, ' s') }}</strong></span><span>采样点 <strong>{{ chartData?.summary.sample_count ?? 0 }}</strong></span><span>ACTIVE <strong>{{ chartData?.summary.active_count ?? 0 }}</strong></span><span>STANDBY 上下文 <strong>{{ chartData?.summary.standby_context_count ?? 0 }}</strong></span><span>切换 <strong>{{ chartData?.summary.switch_count ?? 0 }}</strong></span><span>最早 <strong>{{ chartData?.summary.first_sample_time || '—' }}</strong></span><span>最新 <strong>{{ chartData?.summary.last_sample_time || '—' }}</strong></span></div>
          <div ref="rssiChartHost" class="chart-host" :style="{ height: `${rssiPanel.height.value}px` }">
            <MeshRssiChart ref="rssiChartRef" :points="chartData?.points || []" :events="chartData?.events || []" :location-segments="chartData?.location_segments || []" :show-peer="showRssiPeer" :show-switch-lines="showSwitchLines" :show-switch-points="showSwitchPoints" :show-location-band="showLocationBand" :scope="rssiMode" :active="activeTab === 'rssi'" :focus-timestamp="focusTimestamp" :initial-viewport="rssiViewport" @viewport-change="updateRssiViewport" @viewport-ready="updateRssiViewport" @select-switch="selectChartSwitch" />
          </div>
          <div v-if="selectedChartEvent" class="selected-switch"><span>切换：{{ selectedChartEvent.from_ap_name || selectedChartEvent.from_peer_mac || '—' }} → {{ selectedChartEvent.to_ap_name || selectedChartEvent.to_peer_mac || '—' }} · {{ selectedChartEvent.timestamp }}</span><el-button link type="primary" @click="showSwitchInBuildOrder">查看建链顺序</el-button></div>
          <p class="hint">{{ chartData?.downsampled ? `后端从 ${chartData.total_points} 点按关键点优先返回 ${chartData.returned_points} 点（请求 ${chartData.requested_max_points}，有效上限 ${chartData.effective_max_points}）` : `展示后端返回的 ${chartData?.returned_points ?? 0} 个真实结构化样本` }}；不同经过时段和无 ACTIVE 处保持断线，同采样点备链已预载到 Tooltip。</p>
        </div>

        <div v-show="activeTab === 'busy'" id="pane-busy" class="chart-pane">
          <el-tabs v-model="busyMode" class="analysis-subtabs" @tab-change="changeBusyMode"><el-tab-pane label="全部 ACTIVE 链路信道负载" name="active" /><el-tab-pane label="单 AP / 分时段信道负载" name="peer" /></el-tabs>
          <div class="chart-toolbar">
            <el-select v-if="busyMode === 'peer'" :model-value="selectedVisitValue" filterable placeholder="选择 AP / 经过时段" @change="selectSegmentByAnchor"><el-option v-if="selectedSegment" label="全部经过时段（各区段断开）" value="all-visits" /><el-option v-for="row in buildOrderOptions" :key="row.anchor_link_id" :label="`第 ${row.sequence} 次 · Radio ${row.local_radio ?? '—'} · ${row.peer_ap_name || row.active_peer_mac} · ${row.build_start_time} — ${row.build_end_time}`" :value="row.anchor_link_id" /></el-select>
            <el-select v-if="busyMode === 'active'" v-model="chartRadio" placeholder="选择 Radio" @change="changeChartRadio"><el-option v-for="radio in availableChartRadios" :key="radio" :label="`Radio ${radio}`" :value="radio" /></el-select>
            <el-select v-model="visiblePoints" @change="reloadCurrentChart"><el-option label="目标 120 点" :value="120" /><el-option label="目标 300 点" :value="300" /><el-option label="目标 600 点" :value="600" /><el-option label="目标 1200 点" :value="1200" /><el-option label="目标 2000 点（关键点优先）" :value="2000" /></el-select>
            <el-checkbox v-model="showBusyPeer">显示 Peer 侧 Tx/Rx Busy</el-checkbox><el-button @click="resetCurrentChartViewport">重置视图</el-button>
            <template v-if="lockedAnalysisRange">
              <el-button @click="returnToRssi">返回 RSSI</el-button>
              <el-button :icon="Refresh" @click="updateLockedRangeFromBusy">使用当前空口范围更新锁定</el-button>
              <el-button :icon="Unlock" @click="unlockAndShowAll">解除锁定并查看全部</el-button>
            </template>
          </div>
          <el-alert v-if="lockedAnalysisRange" :title="`已使用 RSSI 锁定时间 ${lockedRangeLabel} · RSSI 可见采样 ${lockedAnalysisRange.sample_count} 点 · 空口有效采样 ${busyValidSampleCount} 点`" type="info" :closable="false" show-icon />
          <el-alert v-if="lockedAnalysisRange && busyChartData && busyValidSampleCount === 0" title="当前 RSSI 锁定时间范围内没有有效 TxBusy/RxBusy 样本。" type="warning" :closable="false" show-icon />
          <div ref="busyChartHost" class="chart-host" :style="{ height: `${busyPanel.height.value}px` }">
            <MeshChannelBusyChart ref="busyChartRef" :points="busyChartData?.points || []" :events="busyChartData?.events || []" :location-segments="busyChartData?.location_segments || []" :show-peer="showBusyPeer" :show-location-band="showLocationBand" :scope="busyMode" :active="activeTab === 'busy'" :initial-viewport="busyViewport" :locked-viewport="lockedAnalysisRange" @viewport-change="updateBusyViewport" @viewport-ready="updateBusyViewport" @select-switch="selectChartSwitch" />
          </div>
          <p class="hint">默认仅显示 MR 侧 TxBusy / RxBusy 两条真实曲线；启用 Peer 后最多四条，不伪造 CtlBusy。</p>
        </div>

        <div v-show="activeTab === 'switches'" id="pane-switches"><NcDataTable table-id="mesh-analysis-switch-events:v3" route-key="/rail-transit/mesh-analysis" :data="switches" :columns="switchColumns" :stripe="false" :row-class-name="switchRowClass" border height="430" /></div>

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
@media(max-width:700px){.report-params-grid{grid-template-columns:1fr}}
.selected-switch{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:8px 0;padding:8px 12px;border:1px solid var(--nc-border-light);border-radius:6px;background:var(--nc-bg-page)}
.mesh-page{display:flex;min-height:0;min-width:0;flex-direction:column;gap:16px}.page-heading,.detail-heading,.jump-actions,.toolbar,.pagination,.mini-summary,.chart-toolbar,.task-line{display:flex;align-items:center;gap:12px}.page-heading,.detail-heading,.pagination{justify-content:space-between}.page-heading h1,.detail-heading h2{margin:2px 0 6px}.page-heading p,.detail-heading p,.hint{margin:0;color:var(--nc-text-secondary)}.eyebrow{color:var(--nc-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(8,minmax(105px,1fr));gap:10px}.metric-card,.content-card{background:var(--nc-bg-card);border:1px solid var(--nc-border-light);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--nc-text-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.sessions-panel{padding-top:10px}.sessions-toggle{display:flex;width:100%;min-height:42px;align-items:center;gap:10px;padding:6px 4px;color:var(--nc-text-primary);background:transparent;border:0;cursor:pointer;text-align:left}.sessions-toggle>span:not(.el-tag){min-width:0;overflow:hidden;color:var(--nc-text-secondary);text-overflow:ellipsis;white-space:nowrap}.sessions-toggle .el-tag{margin-left:auto}.sessions-toolbar{margin-top:14px}.task-card{max-height:140px;margin:8px 0 14px;padding:10px 12px;overflow:hidden;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:8px}.task-line{min-width:0}.task-copy{display:flex;min-width:0;flex:1;flex-direction:column}.task-copy span,.task-summary{overflow:hidden;color:var(--nc-text-secondary);font-size:12px;text-overflow:ellipsis;white-space:nowrap}.task-line>.el-button{margin-left:auto}.task-card :deep(.el-progress){margin-top:8px}.task-summary{margin:7px 0 0}.toolbar,.jump-actions,.mini-summary,.chart-toolbar{flex-wrap:wrap}.toolbar{margin-bottom:12px}.toolbar .el-input{width:240px}.toolbar .el-select{width:145px}.chart-toolbar{padding:10px 0 4px}.chart-toolbar .el-select:first-child{width:min(620px,100%)}.pagination{flex:none;padding-top:12px;color:var(--nc-text-secondary)}.detail-card{display:flex;min-height:0;flex-direction:column}.detail-tabs{min-height:0;flex:none;scroll-margin-top:12px}.detail-card :deep(.detail-tabs>.el-tabs__content){display:none}.detail-tab-content{min-height:0;flex:1}.analysis-subtabs :deep(.el-tabs__content){display:none}.table-pane,.chart-pane{min-height:0}.table-pane{display:flex;flex-direction:column}.table-host,.chart-host{min-height:0;min-width:0;flex:none}.chart-host{width:100%;min-height:360px}.detail-card .el-alert,.task-card .el-alert{margin:10px 0}.warning-summary .el-alert{margin:10px 0}.warning-list{display:flex;flex-direction:column;gap:8px}.mini-summary{padding:10px 0}.mini-summary span{padding:9px 12px;border-radius:8px;background:var(--nc-bg-page)}.hint{font-size:12px}.hidden-input{display:none}.profile-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.bundle-table-wrap{overflow-x:auto;margin-top:12px}.bundle-table{width:100%;border-collapse:collapse;min-width:900px}.bundle-table th,.bundle-table td{padding:9px;border-bottom:1px solid var(--nc-border-light);text-align:left;vertical-align:middle}.bundle-table th{color:var(--nc-text-secondary);font-size:12px}.bundle-table td small{display:block;color:var(--nc-text-secondary);margin-top:4px}.mesh-role-active{color:var(--nc-success);font-weight:600}.mesh-role-standby{color:var(--nc-text-secondary)}.nc-data-table :deep(.mesh-time-group-0 > td.el-table__cell){background:var(--nc-bg-card)}.nc-data-table :deep(.mesh-time-group-1 > td.el-table__cell){background:var(--nc-bg-page)}.nc-data-table :deep(.mesh-row-active > td.el-table__cell){color:var(--nc-success)}.nc-data-table :deep(.mesh-build-selected > td.el-table__cell){background:color-mix(in srgb,var(--nc-primary) 14%,var(--nc-bg-card))}.nc-data-table :deep(.mesh-time-group-0:hover > td.el-table__cell),.nc-data-table :deep(.mesh-time-group-1:hover > td.el-table__cell),.nc-data-table :deep(.mesh-build-selected:hover > td.el-table__cell){background:var(--nc-table-hover-bg)}h3{margin:16px 0 8px}pre{max-height:360px;overflow:auto;padding:12px;background:var(--nc-bg-code);color:var(--nc-text-code);border-radius:8px;font:12px/1.6 Consolas,monospace}@media(max-width:1450px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}}@media(max-width:900px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.page-heading,.detail-heading{align-items:flex-start;flex-direction:column}.profile-grid{grid-template-columns:1fr}.sessions-toggle>span:not(.el-tag){display:none}}
</style>
