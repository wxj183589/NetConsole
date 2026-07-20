<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import MeshChannelBusyChart from '../../components/mesh-analysis/MeshChannelBusyChart.vue'
import MeshCounterDeltaChart from '../../components/mesh-analysis/MeshCounterDeltaChart.vue'
import MeshRateChart from '../../components/mesh-analysis/MeshRateChart.vue'
import MeshRssiChart from '../../components/mesh-analysis/MeshRssiChart.vue'
import MeshSwitchRssiChart from '../../components/mesh-analysis/MeshSwitchRssiChart.vue'
import { buildMeshTimeGroupClasses } from '../../components/mesh-analysis/timeGrouping'
import NcDataTable from '../../components/table/NcDataTable.vue'
import { useConfirm } from '../../components/feedback/useConfirm'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import {
  applyMeshBundleImport, createMeshProfile, getMeshAnalysisSession, getMeshAnalysisSummary, getMeshChannelBusy, getMeshRawTail,
  getMeshCounterDeltas, getMeshRssi, getMeshRateSeries, getMeshTimeline, listMeshAnalysisSessions, listMeshAnomalies, listMeshApStatistics,
  listMeshArtifacts, listMeshLinks, listMeshProfiles, listMeshSwitchEvents, meshArtifactDownloadRequest, previewMeshImport, rebuildMeshAnalysis,
  prepareMeshImportContext,
} from '../../api/meshAnalysis'
import { listVehicleMrs } from '../../api/railTransitBaseData'
import { exportMeshAnalysisReport, getRailTransitTask, recoverRailTransitTasks } from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import type {
  MeshAnalysisSession, MeshAnalysisSummary, MeshAnomaly, MeshApStatistics, MeshArtifact, MeshBundleImportRequest, MeshBundleMapping, MeshBundlePreview,
  MeshChannelBusy, MeshCounterDeltaPage, MeshLinkDetail, MeshProfile, MeshRatePage, MeshRawSource, MeshRawTail, MeshRssi, MeshSessionDetail, MeshSwitchEvent, MeshTimelineItem,
} from '../../types/meshAnalysis'
import type { VehicleMr } from '../../types/railTransitBaseData'
import type { RailTransitTask } from '../../types/railTransitWeb'
import { downloadBackendResource } from '../../platform/runtime'

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
const links = ref<MeshLinkDetail[]>([])
const linkTotal = ref(0)
const timeline = ref<MeshTimelineItem[]>([])
const switches = ref<MeshSwitchEvent[]>([])
const rssi = ref<MeshRssi | null>(null)
const channelBusy = ref<MeshChannelBusy[]>([])
const rateSeries = ref<MeshRatePage>({ items: [], total: 0, downsampled: false })
const counterDeltas = ref<MeshCounterDeltaPage>({ items: [], total: 0, downsampled: false })
const anomalies = ref<MeshAnomaly[]>([])
const anomalyTotal = ref(0)
const apStatistics = ref<MeshApStatistics[]>([])
const artifacts = ref<MeshArtifact[]>([])
const rawTail = ref<MeshRawTail | null>(null)
const profiles = ref<MeshProfile[]>([])
const baseMrs = ref<VehicleMr[]>([])
const importVisible = ref(false)
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
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const activeTab = ref('links')
const warningsExpanded = ref(false)
const bundlePreview = ref<MeshBundlePreview | null>(null)
const bundleMappings = reactive<Record<string, Omit<MeshBundleMapping, 'role'> & { role: '' | 'CT' | 'CW'; confirmed: boolean }>>({})
const bundlePreviewLoading = ref(false)
const filters = reactive({ query: '', mr_role: '', has_warning: '' as '' | 'true' | 'false', page: 1, page_size: 50 })
const linkFilters = reactive({ query: '', link_role: '', page: 1, page_size: 100, sort_order: 'asc' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let failureCount = 0
let taskTimer: ReturnType<typeof setTimeout> | null = null
let detailGeneration = 0
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const taskStorageKey = 'netconsole.mesh-analysis.last-task'

const cards = computed(() => summary.value ? [
  ['分析会话', summary.value.session_count], ['列车 / MR', `${summary.value.train_count} / ${summary.value.mr_count}`],
  ['链路记录', display(summary.value.link_record_count)], ['主 / 备链路', `${display(summary.value.active_link_count)} / ${display(summary.value.standby_link_count)}`],
  ['切换事件', display(summary.value.switch_event_count)], ['短时建链', display(summary.value.short_link_count)],
  ['乒乓切换', display(summary.value.pingpong_count)], ['未匹配 AP', display(summary.value.unmatched_ap_count)],
] : [])
const taskRows = computed(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) })))
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
const linkTimeGroups = computed(() => buildMeshTimeGroupClasses(links.value, (row) => row.timestamp))
const timelineTimeGroups = computed(() => buildMeshTimeGroupClasses(timeline.value, (row) => row.start_time))
const switchTimeGroups = computed(() => buildMeshTimeGroupClasses(switches.value, (row) => row.timestamp))
const busyTimeGroups = computed(() => buildMeshTimeGroupClasses(channelBusy.value, (row) => row.timestamp))
type TaskResultRow = { name: string; value: string }
const taskResultColumns: NcTableColumn<TaskResultRow>[] = [
  { key: 'name', label: '结果项', minWidth: 220 },
  { key: 'value', label: '值', align: 'left', alignmentReason: 'long-text', minWidth: 240 },
]
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
const linkColumns: NcTableColumn<MeshLinkDetail>[] = [
  { key: 'timestamp', label: '时间', valueType: 'datetime', widthMode: 'content', minWidth: 215, fixed: 'left' },
  { key: 'local_radio', label: 'Mesh Radio', valueType: 'number', width: 105 },
  { key: 'peer_ap_name', label: 'Peer AP', valueType: 'name', minWidth: 160 },
  { key: 'peer_ap_mac', label: 'Peer MAC', valueType: 'mac', width: 145 },
  { key: 'link_role', label: '角色', width: 90 },
  { key: 'rssi', label: 'RSSI', valueType: 'number', width: 90, displayValue: (row) => display(row.rssi) },
  { key: 'station', label: '站点', width: 130 },
  { key: 'section', label: '区间', width: 150 },
  { key: 'mileage', label: '里程', valueType: 'mileage', width: 120 },
  { key: 'line_side', label: '方向', width: 95 },
  { key: 'event_type', label: '事件', width: 120 },
  { key: 'duration_ms', label: '上报时长(ms)', valueType: 'duration', width: 130 },
  { key: 'match_method', label: '匹配方式', minWidth: 180 },
  { key: 'warning', label: '数据告警', valueType: 'error', minWidth: 150, alignmentReason: 'long-text' },
]
const timelineColumns: NcTableColumn<MeshTimelineItem>[] = [
  { key: 'start_time', label: '开始', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'end_time', label: '结束', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'duration_seconds', label: '持续(s)', valueType: 'duration', width: 100 },
  { key: 'peer_ap_name', label: 'Peer AP', valueType: 'name', minWidth: 160 },
  { key: 'peer_ap_mac', label: 'Peer MAC', valueType: 'mac', width: 145 },
  { key: 'rssi_range', label: 'RSSI min / avg / max', width: 185, displayValue: (row) => `${display(row.rssi_min)} / ${display(row.rssi_avg)} / ${display(row.rssi_max)}` },
  { key: 'station', label: '站点', width: 130 },
  { key: 'section', label: '区间', minWidth: 150 },
]
const switchColumns: NcTableColumn<MeshSwitchEvent>[] = [
  { key: 'timestamp', label: '时间', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'event_type', label: '事件', width: 130 },
  { key: 'from_ap_name', label: '原 AP', valueType: 'name', minWidth: 150 },
  { key: 'to_ap_name', label: '目标 AP', valueType: 'name', minWidth: 150 },
  { key: 'rssi_change', label: 'RSSI 前 / 后', width: 135, displayValue: (row) => `${display(row.before_rssi)} / ${display(row.after_rssi)}` },
  { key: 'duration_ms', label: '耗时(ms)', valueType: 'duration', width: 100 },
  { key: 'is_short_link', label: '短时', width: 75, displayValue: (row) => row.is_short_link ? '是' : '否' },
  { key: 'is_pingpong', label: '乒乓', width: 75, displayValue: (row) => row.is_pingpong ? '是' : '否' },
  { key: 'station', label: '站点', width: 130 },
]
const busyColumns: NcTableColumn<MeshChannelBusy>[] = [
  { key: 'timestamp', label: '时间', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'local_radio', label: 'Radio', valueType: 'number', width: 80 },
  { key: 'ctl_busy', label: 'CtlBusy', valueType: 'percentage', width: 95, displayValue: (row) => display(row.ctl_busy) },
  { key: 'tx_busy', label: 'TxBusy', valueType: 'percentage', width: 95, displayValue: (row) => display(row.tx_busy) },
  { key: 'rx_busy', label: 'RxBusy', valueType: 'percentage', width: 95, displayValue: (row) => display(row.rx_busy) },
  { key: 'peer_ap_name', label: 'Peer AP', valueType: 'name', minWidth: 160 },
  { key: 'station', label: '站点', width: 140 },
  { key: 'source_type', label: '结构化来源', width: 160 },
]
const anomalyColumns: NcTableColumn<MeshAnomaly>[] = [
  { key: 'severity', label: '级别', valueType: 'status', width: 90 },
  { key: 'anomaly_type', label: '类型', width: 140 },
  { key: 'start_time', label: '开始', valueType: 'datetime', width: 185 },
  { key: 'end_time', label: '结束', valueType: 'datetime', width: 185 },
  { key: 'peer_ap_name', label: 'AP', valueType: 'name', minWidth: 150 },
  { key: 'description', label: '说明', valueType: 'description', minWidth: 260, alignmentReason: 'long-text' },
  { key: 'evidence_reference', label: '证据引用', align: 'left', alignmentReason: 'long-text', minWidth: 160 },
]
const apStatisticColumns: NcTableColumn<MeshApStatistics>[] = [
  { key: 'peer_ap_name', label: 'AP', valueType: 'name', minWidth: 160 },
  { key: 'peer_ap_mac', label: 'MAC', valueType: 'mac', width: 145 },
  { key: 'station', label: '站点', width: 130 },
  { key: 'section', label: '区间', minWidth: 145 },
  { key: 'link_up_count', label: '主链记录', valueType: 'number', width: 105 },
  { key: 'link_down_count', label: '备链记录', valueType: 'number', width: 105 },
  { key: 'switch_in_count', label: '切入', valueType: 'number', width: 75 },
  { key: 'switch_out_count', label: '切出', valueType: 'number', width: 75 },
  { key: 'rssi', label: '平均 / 最小 RSSI', width: 150, displayValue: (row) => `${display(row.avg_rssi)} / ${display(row.min_rssi)}` },
  { key: 'match_status', label: '匹配', valueType: 'status', width: 90 },
]
const artifactColumns: NcTableColumn<MeshArtifact>[] = [
  { key: 'artifact_type', label: '类型', width: 140 },
  { key: 'name', label: '文件名', align: 'left', alignmentReason: 'path', minWidth: 260 },
  { key: 'size_bytes', label: '大小', valueType: 'number', width: 110, displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '生成时间', valueType: 'datetime', widthMode: 'content', minWidth: 215 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 90, hideable: false },
]
const sourceColumns: NcTableColumn<MeshRawSource>[] = [
  { key: 'name', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 260 },
  { key: 'source_type', label: '来源类型', width: 150 },
  { key: 'exists', label: '状态', valueType: 'status', width: 100, displayValue: (row) => row.exists ? '可用' : '缺失' },
  { key: 'size_bytes', label: '大小', valueType: 'number', width: 110, displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'tail', label: '日志片段', valueType: 'actions', width: 110, hideable: false },
]

onMounted(async () => { await Promise.all([refreshOverview(), recoverTask()]); scheduleRefresh() })
onBeforeUnmount(() => { if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = null; stopTaskPolling() })

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
  selected.value = null; links.value = []; linkTotal.value = 0; timeline.value = []; switches.value = []; rssi.value = null
  channelBusy.value = []; rateSeries.value = { items: [], total: 0, downsampled: false }; counterDeltas.value = { items: [], total: 0, downsampled: false }
  anomalies.value = []; anomalyTotal.value = 0; apStatistics.value = []; artifacts.value = []; rawTail.value = null; detailSectionError.value = ''
  try {
    const id = row.session_id
    const detail = await getMeshAnalysisSession(id)
    if (generation !== detailGeneration) return
    selected.value = detail
    const results = await Promise.allSettled([
      listMeshLinks(id, linkFilters), getMeshTimeline(id), listMeshSwitchEvents(id, { page: 1, page_size: 500 }), getMeshRssi(id),
      getMeshChannelBusy(id), getMeshRateSeries(id, { max_points: 2_000 }), getMeshCounterDeltas(id, { max_points: 2_000 }),
      listMeshAnomalies(id), listMeshApStatistics(id), listMeshArtifacts(id),
    ])
    if (generation !== detailGeneration) return
    const [linkPage, timelineData, switchPage, rssiData, busyData, rateData, counterData, anomalyPage, apPage, artifactRows] = results
    if (linkPage.status === 'fulfilled') { links.value = linkPage.value.items; linkTotal.value = linkPage.value.total }
    if (timelineData.status === 'fulfilled') timeline.value = timelineData.value.items
    if (switchPage.status === 'fulfilled') switches.value = switchPage.value.items
    if (rssiData.status === 'fulfilled') rssi.value = rssiData.value
    if (busyData.status === 'fulfilled') channelBusy.value = busyData.value.items
    if (rateData.status === 'fulfilled') rateSeries.value = rateData.value
    if (counterData.status === 'fulfilled') counterDeltas.value = counterData.value
    if (anomalyPage.status === 'fulfilled') { anomalies.value = anomalyPage.value.items; anomalyTotal.value = anomalyPage.value.total }
    if (apPage.status === 'fulfilled') apStatistics.value = apPage.value.items
    if (artifactRows.status === 'fulfilled') artifacts.value = artifactRows.value
    const failed = results.filter((result) => result.status === 'rejected').length
    detailSectionError.value = failed ? `${failed} 个旧版指标区域不可用；会话详情、可兼容指标和原始日志仍可查看。` : ''
    error.value = ''
  } catch (reason) { if (generation === detailGeneration) error.value = reason instanceof Error ? reason.message : '分析详情加载失败' }
  finally { if (generation === detailGeneration) detailLoading.value = false }
}

async function reloadLinks(page = linkFilters.page): Promise<void> {
  if (!selected.value) return
  linkFilters.page = page
  const result = await listMeshLinks(selected.value.session.session_id, linkFilters)
  links.value = result.items; linkTotal.value = result.total
}

async function loadRawTail(sourceId: string, available: boolean): Promise<void> {
  if (!selected.value || !available) return
  rawTail.value = await getMeshRawTail(selected.value.session.session_id, sourceId)
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
function rememberTask(value: RailTransitTask | null): void { task.value = value; if (value) localStorage.setItem(taskStorageKey, value.task_id); else localStorage.removeItem(taskStorageKey) }
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
    activeTab.value = 'links'
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
async function startTask(factory: () => Promise<RailTransitTask>, fallback: string): Promise<void> {
  taskLoading.value = true; error.value = ''
  try { rememberTask(await factory()); pollTask(); openTaskWindow() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : fallback }
  finally { taskLoading.value = false }
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
function generateReport(): void {
  if (!selected.value) return
  void startTask(() => exportMeshAnalysisReport(selected.value!.session.session_id), 'MESH 分析报告生成启动失败')
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
    rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => ['mesh_log_import', 'mesh_bundle_import', 'mesh_schema_rebuild', 'mesh_source_rebuild', 'mesh_analysis_report'].includes(item.action)) || null)
    pollTask()
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'MESH 任务恢复失败' }
}
function openTaskWindow(taskId = task.value?.task_id || ''): void {
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}

function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function formatBytes(value: number): string { if (!value) return '0 B'; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 ** 2).toFixed(1)} MB` }
function severityType(value: string): 'error' | 'warning' | 'info' { return value === 'error' || value === 'critical' ? 'error' : value === 'warning' ? 'warning' : 'info' }
function linkRowClass(params: { row: MeshLinkDetail }): string { return linkTimeGroups.value.get(params.row) || '' }
function timelineRowClass(params: { row: MeshTimelineItem }): string { return timelineTimeGroups.value.get(params.row) || '' }
function switchRowClass(params: { row: MeshSwitchEvent }): string { return switchTimeGroups.value.get(params.row) || '' }
function busyRowClass(params: { row: MeshChannelBusy }): string { return busyTimeGroups.value.get(params.row) || '' }
function roleClass(value: string): string { return value === 'ACTIVE' ? 'mesh-role-active' : value === 'STANDBY' ? 'mesh-role-standby' : '' }
</script>

<template>
  <section class="mesh-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · OFFLINE MESH ANALYSIS</p><h1>Mesh 原始日志分析</h1><p>选择日志后自动匹配当前局点车载 MR，并完成归档、解析、分析和报告交付。</p></div>
      <div class="jump-actions"><el-button :loading="importContextLoading" :disabled="!isFeatureEnabled('web.mesh_analysis_import')" @click="openImportDialog">导入原始 MESH 日志</el-button><el-button type="primary" :loading="taskLoading" :disabled="!selected || ['missing','unreadable'].includes(selected.session.parsed_status) || !isFeatureEnabled('web.mesh_analysis_report_export')" @click="generateReport">生成分析报告</el-button><el-button :loading="loading" @click="refreshOverview()">刷新结果</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <div v-if="task" class="content-card task-card"><div class="detail-heading"><div><h2>MESH 处理结果 · {{ task.action }}</h2><p>{{ task.task_id }}</p></div><el-tag>{{ task.status }}</el-tag></div><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><NcDataTable v-if="taskRows.length" table-id="mesh-analysis-task-results" route-key="/rail-transit/mesh-analysis" :preference-scope="task.task_id" :data="taskRows" :columns="taskResultColumns" max-height="220" /><el-alert title="停止、日志、恢复与生成报告下载统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow()">打开任务窗口</el-button></el-alert></div>

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

    <div class="summary-grid">
      <article v-for="card in cards" :key="String(card[0])" class="metric-card"><span>{{ card[0] }}</span><strong>{{ card[1] }}</strong></article>
    </div>

    <div class="content-card" v-loading="loading">
      <div class="toolbar">
        <el-input v-model="filters.query" clearable placeholder="搜索列车、MR 或来源文件" @keyup.enter="filters.page = 1; refreshOverview()" />
        <el-select v-model="filters.mr_role" clearable placeholder="MR 角色"><el-option label="CT" value="CT" /><el-option label="TC" value="TC" /><el-option label="CW" value="CW" /></el-select>
        <el-select v-model="filters.has_warning" clearable placeholder="数据告警"><el-option label="有告警" value="true" /><el-option label="无告警" value="false" /></el-select>
        <el-button type="primary" @click="filters.page = 1; refreshOverview()">查询</el-button>
      </div>
      <NcDataTable table-id="mesh-analysis-sessions" route-key="/rail-transit/mesh-analysis" :data="sessions" :columns="sessionColumns" border height="340" empty-text="暂无已持久化 Mesh 分析来源" @row-dblclick="openSession">
        <template #cell-warnings="{ row }"><el-tag :type="row.warning_count ? 'warning' : 'success'">{{ row.warning_count }}</el-tag></template>
        <template #cell-actions="{ row }"><el-button link type="primary" @click="openSession(row)">查看</el-button></template>
      </NcDataTable>
      <div class="pagination"><span>共 {{ total }} 个来源</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="total" @current-change="(page: number) => { filters.page = page; refreshOverview() }" /></div>
    </div>

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

      <el-tabs v-model="activeTab">
        <el-tab-pane label="链路明细" name="links">
          <div class="toolbar"><el-input v-model="linkFilters.query" clearable placeholder="Peer AP / MAC / 站点" /><el-select v-model="linkFilters.link_role" clearable placeholder="链路角色"><el-option label="主链路" value="ACTIVE" /><el-option label="备份链路" value="STANDBY" /></el-select><el-button @click="reloadLinks(1)">筛选</el-button></div>
          <NcDataTable table-id="mesh-analysis-links" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="links" :columns="linkColumns" :stripe="false" :row-class-name="linkRowClass" border height="430"><template #cell-link_role="{ row }"><span :class="roleClass(row.link_role)">{{ row.link_role }}</span></template></NcDataTable>
          <div class="pagination"><span>共 {{ linkTotal }} 条</span><el-pagination :current-page="linkFilters.page" :page-size="linkFilters.page_size" layout="prev, pager, next" :total="linkTotal" @current-change="reloadLinks" /></div>
        </el-tab-pane>

        <el-tab-pane label="主链路时间线" name="timeline"><NcDataTable table-id="mesh-analysis-timeline" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="timeline" :columns="timelineColumns" :stripe="false" :row-class-name="timelineRowClass" border height="430" /></el-tab-pane>

        <el-tab-pane label="切换事件" name="switches"><NcDataTable table-id="mesh-analysis-switch-events" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="switches" :columns="switchColumns" :stripe="false" :row-class-name="switchRowClass" border height="430" /></el-tab-pane>

        <el-tab-pane label="RSSI" name="rssi"><template v-if="rssi"><div class="mini-summary"><span>最近 <strong>{{ display(rssi.statistics.latest_rssi) }}</strong></span><span>最小 <strong>{{ display(rssi.statistics.min_rssi) }}</strong></span><span>平均 <strong>{{ display(rssi.statistics.avg_rssi) }}</strong></span><span>最大 <strong>{{ display(rssi.statistics.max_rssi) }}</strong></span><span>样本 <strong>{{ rssi.statistics.sample_count }}</strong></span><span>缺失 <strong>{{ rssi.statistics.missing_sample_count }}</strong></span></div><MeshRssiChart :points="rssi.points" /><p class="hint">{{ rssi.downsampled ? `已由后端从 ${rssi.total_points} 点降采样` : '展示全部结构化样本' }}；空值保持为空，不用 0 补齐。</p></template></el-tab-pane>

        <el-tab-pane label="TxBusy / RxBusy" name="busy"><MeshChannelBusyChart :points="channelBusy" /><NcDataTable table-id="mesh-analysis-channel-busy" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="channelBusy" :columns="busyColumns" :stripe="false" :row-class-name="busyRowClass" border height="430" /></el-tab-pane>

        <el-tab-pane label="Rate（原始值）" name="rate"><MeshRateChart :points="rateSeries.items" /><p class="hint">{{ rateSeries.downsampled ? `已由后端从 ${rateSeries.total} 点降采样` : `后端返回 ${rateSeries.total} 点` }}；仅展示 Query API 原始值，不猜测单位。</p></el-tab-pane>
        <el-tab-pane label="Retry / Error 增量" name="retry-error"><MeshCounterDeltaChart :points="counterDeltas.items" /><p class="hint">{{ counterDeltas.downsampled ? `已由后端从 ${counterDeltas.total} 点降采样` : `后端返回 ${counterDeltas.total} 点` }}；增量由后端提供，Vue 不计算。</p></el-tab-pane>
        <el-tab-pane label="切换前后 RSSI" name="switch-rssi"><MeshSwitchRssiChart :events="switches" /><p class="hint">基于正式切换事件的 before_rssi / after_rssi / timestamp / AP / Radio 字段，以散点展示，不连接为连续趋势。</p></el-tab-pane>

        <el-tab-pane :label="`异常摘要 (${anomalyTotal})`" name="anomalies"><NcDataTable table-id="mesh-analysis-anomalies" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="anomalies" :columns="anomalyColumns" border height="430"><template #cell-severity="{ row }"><el-tag :type="severityType(row.severity)">{{ row.severity }}</el-tag></template></NcDataTable></el-tab-pane>

        <el-tab-pane label="AP 统计" name="aps"><NcDataTable table-id="mesh-analysis-ap-statistics" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="apStatistics" :columns="apStatisticColumns" border height="430" /></el-tab-pane>

        <el-tab-pane label="报告与来源" name="artifacts">
          <h3>已有报告与文件</h3><NcDataTable table-id="mesh-analysis-artifacts" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="artifacts" :columns="artifactColumns" border><template #cell-actions="{ row }"><el-button v-if="row.downloadable" link type="primary" @click="downloadArtifact(row)">下载</el-button></template></NcDataTable>
          <h3>原始数据来源</h3><NcDataTable table-id="mesh-analysis-sources" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="selected.sources" :columns="sourceColumns" border><template #cell-tail="{ row }"><el-button link type="primary" :disabled="!row.tail_available" @click="loadRawTail(row.source_id, row.tail_available)">查看 tail</el-button></template></NcDataTable>
          <el-alert v-if="rawTail?.message" :title="rawTail.message" type="info" :closable="false" /><pre v-if="rawTail?.available">{{ rawTail.lines.join('\n') }}</pre>
        </el-tab-pane>
      </el-tabs>
    </div>
  </section>
</template>

<style scoped>
.mesh-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.detail-heading,.jump-actions,.toolbar,.pagination,.mini-summary{display:flex;align-items:center;gap:12px}.page-heading,.detail-heading,.pagination{justify-content:space-between}.page-heading h1,.detail-heading h2{margin:2px 0 6px}.page-heading p,.detail-heading p,.hint{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(8,minmax(105px,1fr));gap:10px}.metric-card,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--el-text-color-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar,.jump-actions,.mini-summary{flex-wrap:wrap}.toolbar{margin-bottom:12px}.toolbar .el-input{width:300px}.toolbar .el-select{width:130px}.pagination{padding-top:12px;color:var(--el-text-color-secondary)}.detail-card .el-alert,.task-card .el-alert{margin:10px 0}.warning-summary .el-alert{margin:10px 0}.warning-list{display:flex;flex-direction:column;gap:8px}.mini-summary{padding:10px 0}.mini-summary span{padding:9px 12px;border-radius:8px;background:var(--el-fill-color-light)}.hint{font-size:12px}.hidden-input{display:none}.profile-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.bundle-table-wrap{overflow-x:auto;margin-top:12px}.bundle-table{width:100%;border-collapse:collapse;min-width:900px}.bundle-table th,.bundle-table td{padding:9px;border-bottom:1px solid var(--nc-border-light);text-align:left;vertical-align:middle}.bundle-table th{color:var(--nc-text-secondary);font-size:12px}.bundle-table td small{display:block;color:var(--nc-text-secondary);margin-top:4px}.mesh-role-active{color:var(--el-color-success);font-weight:600}.mesh-role-standby{color:var(--el-color-warning);font-weight:600}.nc-data-table :deep(.mesh-time-group-0 > td.el-table__cell){background:var(--el-fill-color-blank)}.nc-data-table :deep(.mesh-time-group-1 > td.el-table__cell){background:var(--el-fill-color-light)}.nc-data-table :deep(.mesh-time-group-0:hover > td.el-table__cell),.nc-data-table :deep(.mesh-time-group-1:hover > td.el-table__cell){background:var(--nc-table-hover-bg)}h3{margin:16px 0 8px}pre{max-height:360px;overflow:auto;padding:12px;background:var(--nc-bg-code);color:var(--nc-text-code);border-radius:8px;font:12px/1.6 Consolas,monospace}@media(max-width:1450px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}}@media(max-width:900px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.page-heading,.detail-heading{align-items:flex-start;flex-direction:column}.profile-grid{grid-template-columns:1fr}}
</style>
