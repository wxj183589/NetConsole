<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import MeshRssiChart from '../../components/mesh-analysis/MeshRssiChart.vue'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import {
  createMeshProfile, getMeshAlignment, getMeshAnalysisSession, getMeshAnalysisSummary, getMeshChannelBusy, getMeshRawTail,
  getMeshRssi, getMeshTimeline, listMeshAnalysisSessions, listMeshAnomalies, listMeshApStatistics,
  listMeshArtifacts, listMeshLinks, listMeshProfiles, listMeshSwitchEvents, meshArtifactDownloadRequest,
} from '../../api/meshAnalysis'
import { listVehicleMrs } from '../../api/railTransitBaseData'
import {
  exportMeshAnalysisReport, getRailTransitTask, importMeshAnalysis, recoverRailTransitTasks,
} from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import type {
  MeshAlignment, MeshAlignmentPoint, MeshAnalysisSession, MeshAnalysisSummary, MeshAnomaly, MeshApStatistics, MeshArtifact,
  MeshChannelBusy, MeshLinkDetail, MeshProfile, MeshRawSource, MeshRawTail, MeshRssi, MeshSessionDetail, MeshSwitchEvent, MeshTimelineItem,
} from '../../types/meshAnalysis'
import type { VehicleMr } from '../../types/railTransitBaseData'
import type { RailTransitTask } from '../../types/railTransitWeb'
import { downloadBackendResource } from '../../platform/runtime'

const router = useRouter()
const loading = ref(false)
const detailLoading = ref(false)
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
const anomalies = ref<MeshAnomaly[]>([])
const anomalyTotal = ref(0)
const apStatistics = ref<MeshApStatistics[]>([])
const alignment = ref<MeshAlignment | null>(null)
const artifacts = ref<MeshArtifact[]>([])
const rawTail = ref<MeshRawTail | null>(null)
const profiles = ref<MeshProfile[]>([])
const baseMrs = ref<VehicleMr[]>([])
const importVisible = ref(false)
const selectedProfileId = ref('')
const selectedFiles = ref<File[]>([])
const newProfileName = ref('')
const linkedMrId = ref('')
const profileNotes = ref('')
const task = ref<RailTransitTask | null>(null)
const taskLoading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const activeTab = ref('links')
const filters = reactive({ query: '', mr_role: '', has_warning: '' as '' | 'true' | 'false', page: 1, page_size: 50 })
const linkFilters = reactive({ query: '', link_role: '', page: 1, page_size: 100, sort_order: 'asc' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let failureCount = 0
let taskTimer: ReturnType<typeof setTimeout> | null = null
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const taskStorageKey = 'netconsole.mesh-analysis.last-task'

const cards = computed(() => summary.value ? [
  ['分析会话', summary.value.session_count], ['列车 / MR', `${summary.value.train_count} / ${summary.value.mr_count}`],
  ['链路记录', summary.value.link_record_count], ['主 / 备链路', `${summary.value.active_link_count} / ${summary.value.standby_link_count}`],
  ['切换事件', summary.value.switch_event_count], ['短时建链', summary.value.short_link_count],
  ['乒乓切换', summary.value.pingpong_count], ['未匹配 AP', summary.value.unmatched_ap_count],
] : [])
const taskRows = computed(() => Object.entries(task.value?.result_summary || {}).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) })))
type TaskResultRow = { name: string; value: string }
const taskResultColumns: NcTableColumn<TaskResultRow>[] = [
  { key: 'name', label: '结果项', minWidth: 220 },
  { key: 'value', label: '值', align: 'left', alignmentReason: 'long-text', minWidth: 240 },
]
const sessionColumns: NcTableColumn<MeshAnalysisSession>[] = [
  { key: 'analysis_time', label: '分析时间', valueType: 'datetime', width: 175 },
  { key: 'train_name', label: '列车', minWidth: 100 },
  { key: 'mr_name', label: 'MR', valueType: 'name', minWidth: 145 },
  { key: 'mr_role', label: '角色', width: 70 },
  { key: 'source_type', label: '来源', width: 125 },
  { key: 'original_filename', label: '原始日志', align: 'left', alignmentReason: 'path', minWidth: 260, showOverflowTooltip: true },
  { key: 'link_record_count', label: '链路记录', valueType: 'number', width: 110 },
  { key: 'link_roles', label: '主 / 备', width: 125, displayValue: (row) => `${row.active_link_count} / ${row.standby_link_count}` },
  { key: 'event_count', label: '事件', valueType: 'number', width: 90 },
  { key: 'data_integrity', label: '完整性', valueType: 'status', width: 95 },
  { key: 'warnings', label: '告警', valueType: 'status', width: 80 },
  { key: 'report_count', label: '报告', valueType: 'number', width: 75 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]
const linkColumns: NcTableColumn<MeshLinkDetail>[] = [
  { key: 'timestamp', label: '时间', valueType: 'datetime', width: 185, fixed: 'left' },
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
  { key: 'start_time', label: '开始', valueType: 'datetime', width: 185 },
  { key: 'end_time', label: '结束', valueType: 'datetime', width: 185 },
  { key: 'duration_seconds', label: '持续(s)', valueType: 'duration', width: 100 },
  { key: 'peer_ap_name', label: 'Peer AP', valueType: 'name', minWidth: 160 },
  { key: 'peer_ap_mac', label: 'Peer MAC', valueType: 'mac', width: 145 },
  { key: 'rssi_range', label: 'RSSI min / avg / max', width: 185, displayValue: (row) => `${display(row.rssi_min)} / ${display(row.rssi_avg)} / ${display(row.rssi_max)}` },
  { key: 'station', label: '站点', width: 130 },
  { key: 'section', label: '区间', minWidth: 150 },
]
const switchColumns: NcTableColumn<MeshSwitchEvent>[] = [
  { key: 'timestamp', label: '时间', valueType: 'datetime', width: 185 },
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
  { key: 'timestamp', label: '时间', valueType: 'datetime', width: 185 },
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
const alignmentColumns: NcTableColumn<MeshAlignmentPoint>[] = [
  { key: 'timestamp', label: '时间', valueType: 'datetime', width: 185 },
  { key: 'peer_ap_name', label: 'Peer AP', valueType: 'name', minWidth: 150 },
  { key: 'rssi', label: 'RSSI', valueType: 'number', width: 90, displayValue: (row) => display(row.rssi) },
  { key: 'fping_rtt_ms', label: 'fping RTT', valueType: 'duration', width: 110, displayValue: (row) => display(row.fping_rtt_ms, ' ms') },
  { key: 'fping_loss_percent', label: '丢包', valueType: 'percentage', width: 95, displayValue: (row) => display(row.fping_loss_percent, '%') },
  { key: 'iperf_mbps', label: 'iPerf', valueType: 'rate', width: 110, displayValue: (row) => display(row.iperf_mbps, ' Mbps') },
  { key: 'station', label: '站点', width: 130 },
]
const artifactColumns: NcTableColumn<MeshArtifact>[] = [
  { key: 'artifact_type', label: '类型', width: 140 },
  { key: 'name', label: '文件名', align: 'left', alignmentReason: 'path', minWidth: 260 },
  { key: 'size_bytes', label: '大小', valueType: 'number', width: 110, displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '生成时间', valueType: 'datetime', width: 175 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 90, hideable: false },
]
const sourceColumns: NcTableColumn<MeshRawSource>[] = [
  { key: 'name', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 260 },
  { key: 'source_type', label: '来源类型', width: 150 },
  { key: 'exists', label: '状态', valueType: 'status', width: 100, displayValue: (row) => row.exists ? '可用' : '缺失' },
  { key: 'size_bytes', label: '大小', valueType: 'number', width: 110, displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'tail', label: '日志片段', valueType: 'actions', width: 110, hideable: false },
]

onMounted(async () => { await Promise.all([refreshOverview(), loadProfiles(), recoverTask()]); scheduleRefresh() })
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
  detailLoading.value = true
  rawTail.value = null
  try {
    const id = row.session_id
    const [detail, linkPage, timelineData, switchPage, rssiData, busyData, anomalyPage, apPage, alignmentData, artifactRows] = await Promise.all([
      getMeshAnalysisSession(id), listMeshLinks(id, linkFilters), getMeshTimeline(id), listMeshSwitchEvents(id), getMeshRssi(id),
      getMeshChannelBusy(id), listMeshAnomalies(id), listMeshApStatistics(id), getMeshAlignment(id), listMeshArtifacts(id),
    ])
    selected.value = detail
    links.value = linkPage.items; linkTotal.value = linkPage.total
    timeline.value = timelineData.items
    switches.value = switchPage.items
    rssi.value = rssiData
    channelBusy.value = busyData.items
    anomalies.value = anomalyPage.items; anomalyTotal.value = anomalyPage.total
    apStatistics.value = apPage.items
    alignment.value = alignmentData
    artifacts.value = artifactRows
    error.value = ''
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '分析详情加载失败' }
  finally { detailLoading.value = false }
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
  try {
    const [nextProfiles, mrs] = await Promise.all([listMeshProfiles(), listVehicleMrs({ page: 1, page_size: 500 })])
    profiles.value = nextProfiles
    baseMrs.value = mrs.items
    selectedProfileId.value = profiles.value.find((item) => item.mr_id === selectedProfileId.value)?.mr_id || profiles.value[0]?.mr_id || ''
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'MESH MR profile 加载失败' }
}
async function createProfile(): Promise<void> {
  if (!newProfileName.value.trim()) return
  taskLoading.value = true; error.value = ''
  try {
    const profile = await createMeshProfile({ display_name: newProfileName.value.trim(), linked_mr_id: linkedMrId.value, notes: profileNotes.value.trim() })
    await loadProfiles(); selectedProfileId.value = profile.mr_id; newProfileName.value = ''; linkedMrId.value = ''; profileNotes.value = ''
    ElMessage.success('MESH MR profile 已创建')
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'MESH MR profile 创建失败' }
  finally { taskLoading.value = false }
}
function chooseFiles(event: Event): void {
  selectedFiles.value = Array.from((event.target as HTMLInputElement).files || []).filter((file) => ['.log', '.txt'].some((suffix) => file.name.toLowerCase().endsWith(suffix)))
}
function rememberTask(value: RailTransitTask | null): void { task.value = value; if (value) localStorage.setItem(taskStorageKey, value.task_id); else localStorage.removeItem(taskStorageKey) }
function stopTaskPolling(): void { if (taskTimer) clearTimeout(taskTimer); taskTimer = null }
async function afterTask(): Promise<void> {
  if (task.value?.status !== 'COMPLETED') return
  await refreshOverview()
  if (task.value.action === 'mesh_log_import') await loadProfiles()
  if (selected.value) artifacts.value = await listMeshArtifacts(selected.value.session.session_id)
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
function startImport(): void {
  if (!selectedProfileId.value || !selectedFiles.value.length) return
  void startTask(() => importMeshAnalysis(selectedFiles.value, { mr_id: selectedProfileId.value }), 'MESH 原始日志导入启动失败')
  importVisible.value = false
}
function generateReport(): void {
  if (!selected.value) return
  void startTask(() => exportMeshAnalysisReport(selected.value!.session.session_id), 'MESH 分析报告生成启动失败')
}
async function recoverTask(): Promise<void> {
  try {
    const saved = localStorage.getItem(taskStorageKey) || ''
    const rows = await recoverRailTransitTasks()
    rememberTask(rows.find((item) => item.task_id === saved) || rows.find((item) => ['mesh_log_import', 'mesh_analysis_report'].includes(item.action)) || null)
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
</script>

<template>
  <section class="mesh-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · OFFLINE MESH ANALYSIS</p><h1>Mesh 原始日志分析</h1><p>独立完成 MR profile、原始日志导入解析、主备链分析、异常汇总、报告与 Artifact 交付。</p></div>
      <div class="jump-actions"><el-button :disabled="!isFeatureEnabled('web.mesh_analysis_import')" @click="importVisible = true">导入日志 / 文件夹</el-button><el-button type="primary" :loading="taskLoading" :disabled="!selected || !isFeatureEnabled('web.mesh_analysis_report_export')" @click="generateReport">生成分析报告</el-button><el-button :loading="loading" @click="refreshOverview()">刷新结果</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <div v-if="task" class="content-card task-card"><div class="detail-heading"><div><h2>MESH 处理结果 · {{ task.action }}</h2><p>{{ task.task_id }}</p></div><el-tag>{{ task.status }}</el-tag></div><el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" /><NcDataTable v-if="taskRows.length" table-id="mesh-analysis-task-results" route-key="/rail-transit/mesh-analysis" :preference-scope="task.task_id" :data="taskRows" :columns="taskResultColumns" max-height="220" /><el-alert title="停止、日志、恢复与生成报告下载统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow()">打开任务窗口</el-button></el-alert></div>

    <el-dialog v-model="importVisible" title="MESH 原始日志导入" width="min(880px, 96vw)"><el-form label-position="top"><el-form-item label="MESH MR profile"><el-select v-model="selectedProfileId" filterable placeholder="选择 profile" style="width:100%"><el-option v-for="profile in profiles" :key="profile.mr_id" :label="`${profile.display_name} · ${profile.source_file_count} 文件`" :value="profile.mr_id" /></el-select></el-form-item><el-form-item label="选择原始日志"><div class="jump-actions"><el-button @click="fileInput?.click()">选择 LOG/TXT 文件</el-button><el-button @click="folderInput?.click()">选择文件夹</el-button><span>已选择 {{ selectedFiles.length }} 个文件</span></div><input ref="fileInput" class="hidden-input" type="file" multiple accept=".log,.txt" @change="chooseFiles"><input ref="folderInput" class="hidden-input" type="file" multiple webkitdirectory @change="chooseFiles"></el-form-item><el-divider content-position="left">创建新 profile</el-divider><div class="profile-grid"><el-form-item label="显示名称"><el-input v-model="newProfileName" placeholder="例如：列车01-MR-CT" /></el-form-item><el-form-item label="关联基础资料 MR（可选）"><el-select v-model="linkedMrId" clearable filterable><el-option v-for="mr in baseMrs" :key="mr.id" :label="`${mr.train_no} · ${mr.role} · ${mr.name}`" :value="mr.id" /></el-select></el-form-item><el-form-item label="备注"><el-input v-model="profileNotes" /></el-form-item></div><el-button :loading="taskLoading" :disabled="!newProfileName.trim()" @click="createProfile">创建 profile</el-button></el-form><template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :loading="taskLoading" :disabled="!selectedProfileId || !selectedFiles.length" @click="startImport">开始导入分析</el-button></template></el-dialog>

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
          <el-button @click="router.push({ path: '/rail-transit/train-communication', query: { train: selected?.session.train_name } })">在线列车通信</el-button>
          <el-button @click="router.push('/rail-transit/online-mr')">Online MR</el-button>
          <el-button @click="router.push('/ac-management/mesh-links')">AC Mesh-Link</el-button>
          <el-button v-if="selected.session.task_id" @click="openTaskWindow(selected.session.task_id)">任务窗口</el-button>
        </div>
      </div>
      <el-alert v-for="warning in selected.warnings" :key="warning.code" :title="warning.message" :type="severityType(warning.severity)" :closable="false" show-icon />

      <el-tabs v-model="activeTab">
        <el-tab-pane label="链路明细" name="links">
          <div class="toolbar"><el-input v-model="linkFilters.query" clearable placeholder="Peer AP / MAC / 站点" /><el-select v-model="linkFilters.link_role" clearable placeholder="链路角色"><el-option label="主链路" value="ACTIVE" /><el-option label="备份链路" value="STANDBY" /></el-select><el-button @click="reloadLinks(1)">筛选</el-button></div>
          <NcDataTable table-id="mesh-analysis-links" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="links" :columns="linkColumns" border height="430" />
          <div class="pagination"><span>共 {{ linkTotal }} 条</span><el-pagination :current-page="linkFilters.page" :page-size="linkFilters.page_size" layout="prev, pager, next" :total="linkTotal" @current-change="reloadLinks" /></div>
        </el-tab-pane>

        <el-tab-pane label="主链路时间线" name="timeline"><NcDataTable table-id="mesh-analysis-timeline" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="timeline" :columns="timelineColumns" border height="430" /></el-tab-pane>

        <el-tab-pane label="切换事件" name="switches"><NcDataTable table-id="mesh-analysis-switch-events" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="switches" :columns="switchColumns" border height="430" /></el-tab-pane>

        <el-tab-pane label="RSSI" name="rssi"><template v-if="rssi"><div class="mini-summary"><span>最近 <strong>{{ display(rssi.statistics.latest_rssi) }}</strong></span><span>最小 <strong>{{ display(rssi.statistics.min_rssi) }}</strong></span><span>平均 <strong>{{ display(rssi.statistics.avg_rssi) }}</strong></span><span>最大 <strong>{{ display(rssi.statistics.max_rssi) }}</strong></span><span>样本 <strong>{{ rssi.statistics.sample_count }}</strong></span><span>缺失 <strong>{{ rssi.statistics.missing_sample_count }}</strong></span></div><MeshRssiChart :points="rssi.points" /><p class="hint">{{ rssi.downsampled ? `已由后端从 ${rssi.total_points} 点降采样` : '展示全部结构化样本' }}；空值保持为空，不用 0 补齐。</p></template></el-tab-pane>

        <el-tab-pane label="空口繁忙度" name="busy"><NcDataTable table-id="mesh-analysis-channel-busy" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="channelBusy" :columns="busyColumns" border height="430" /></el-tab-pane>

        <el-tab-pane :label="`异常摘要 (${anomalyTotal})`" name="anomalies"><NcDataTable table-id="mesh-analysis-anomalies" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="anomalies" :columns="anomalyColumns" border height="430"><template #cell-severity="{ row }"><el-tag :type="severityType(row.severity)">{{ row.severity }}</el-tag></template></NcDataTable></el-tab-pane>

        <el-tab-pane label="AP 统计" name="aps"><NcDataTable table-id="mesh-analysis-ap-statistics" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="apStatistics" :columns="apStatisticColumns" border height="430" /></el-tab-pane>

        <el-tab-pane label="fping / iPerf 对齐" name="alignment"><el-alert v-if="alignment?.message" :title="alignment.message" type="info" :closable="false" /><NcDataTable table-id="mesh-analysis-traffic-alignment" route-key="/rail-transit/mesh-analysis" :preference-scope="selected.session.session_id" :data="alignment?.items || []" :columns="alignmentColumns" border height="400" empty-text="暂无可对齐的结构化流量数据" /></el-tab-pane>

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
.mesh-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.detail-heading,.jump-actions,.toolbar,.pagination,.mini-summary{display:flex;align-items:center;gap:12px}.page-heading,.detail-heading,.pagination{justify-content:space-between}.page-heading h1,.detail-heading h2{margin:2px 0 6px}.page-heading p,.detail-heading p,.hint{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(8,minmax(105px,1fr));gap:10px}.metric-card,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--el-text-color-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar,.jump-actions,.mini-summary{flex-wrap:wrap}.toolbar{margin-bottom:12px}.toolbar .el-input{width:300px}.toolbar .el-select{width:130px}.pagination{padding-top:12px;color:var(--el-text-color-secondary)}.detail-card .el-alert,.task-card .el-alert{margin:10px 0}.mini-summary{padding:10px 0}.mini-summary span{padding:9px 12px;border-radius:8px;background:var(--el-fill-color-light)}.hint{font-size:12px}.hidden-input{display:none}.profile-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}h3{margin:16px 0 8px}pre{max-height:360px;overflow:auto;padding:12px;background:var(--nc-bg-code);color:var(--nc-text-code);border-radius:8px;font:12px/1.6 Consolas,monospace}@media(max-width:1450px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}}@media(max-width:900px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.page-heading,.detail-heading{align-items:flex-start;flex-direction:column}.profile-grid{grid-template-columns:1fr}}
</style>
