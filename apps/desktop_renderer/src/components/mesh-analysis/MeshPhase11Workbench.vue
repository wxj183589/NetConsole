<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import MeshMetricChart, { type MeshMonitorWindow } from './MeshMetricChart.vue'
import NcDataTable from '../table/NcDataTable.vue'
import type { NcTableColumn } from '../table/NcTableColumn'
import { getMeshBusinessSummary, listMeshApSignalStatistics, listMeshLinks, listMeshParseIssues, listMeshActiveBuildOrder } from '../../api/meshAnalysis'
import type { MeshActiveBuildOrder, MeshAnalysisSession, MeshApSignal, MeshBusinessSummary, MeshLinkDetail, MeshParseIssue } from '../../types/meshAnalysis'
import { buildMeshBusinessMetricGroups, type MeshBusinessMetricKey, type MeshBusinessMetricGroup } from './meshBusinessMetrics'
import { meshLoadingPhaseLabel, type MeshLoadingPhase } from './meshLoadingState'
import { meshTimestampMillis as millis, formatMeshViewportTimestamp as stamp } from './meshChartViewport'
type Workspace = 'overview' | 'parse' | 'aps' | 'main'
type Status = { phase: MeshLoadingPhase; message: string; cached: boolean }
const props = defineProps<{ sessionId: string; session: MeshAnalysisSession }>()
const emit = defineEmits<{ scopeChange: [scope: { exclude_depot: boolean; exclude_parking: boolean }]; workspaceChange: [workspace: Workspace] }>()
const workspace = ref<Workspace>('overview')
const scope = ref({ exclude_depot: true, exclude_parking: true })
const business = ref<MeshBusinessSummary | null>(null), aps = ref<MeshApSignal[]>([]), parseIssues = ref<MeshParseIssue[]>([])
const apLoading = ref(false), parseLoading = ref(false), summaryError = ref('')
const apTotal = ref(0), apPage = ref(1)
const filters = ref({ ap: '', radio: 1 as number | undefined, role: 'ACTIVE', include_zero: false })
const domain = ref<MeshMonitorWindow>({ start: '', end: '' }), windowRange = ref<MeshMonitorWindow>({ start: '', end: '' })
const pointer = ref<string | null>(null), selectedLink = shallowRef<MeshLinkDetail | null>(null)
const records = shallowRef<MeshActiveBuildOrder[]>([]), recordTotal = ref(0), recordPage = ref(1), recordLoading = ref(false)
const history = shallowRef<MeshLinkDetail[]>([]), historyTotal = ref(0), historyPage = ref(1), historyLoading = ref(false), zeroTotal = ref(0)
const activeMetric = ref<MeshBusinessMetricKey>('rssi')
const definitions: Array<{ key: MeshBusinessMetricKey; label: string; unit: string }> = [
  { key: 'rssi', label: 'RSSI', unit: '' }, { key: 'cpu', label: 'CPU', unit: '%' }, { key: 'memory', label: 'Memory', unit: '%' },
  { key: 'busy', label: 'TxBusy / RxBusy', unit: '%' }, { key: 'rate', label: 'Rate', unit: '' }, { key: 'noise', label: 'Noise', unit: 'dBm' },
  { key: 'tx_des_free_cnt', label: 'TxDesFreeCnt', unit: '' }, { key: 'counters', label: 'Tx / Rx / Retry / Err / GARP / MulJoin', unit: '增量' },
]
const groups = shallowRef<Partial<Record<MeshBusinessMetricKey, MeshBusinessMetricGroup>>>({})
const samples = shallowRef<Partial<Record<MeshBusinessMetricKey, MeshLinkDetail[]>>>({})
const statuses = ref(Object.fromEntries(definitions.map(d => [d.key, { phase: 'IDLE', message: '', cached: false }])) as Record<MeshBusinessMetricKey, Status>)
let autoSelect = true, selectionGeneration = 0, recordRequest = 0, historyRequest = 0, apRequest = 0
let generation = 0, auxGeneration = 0, zoomTimer: ReturnType<typeof setTimeout> | undefined
let mainController = new AbortController(), auxController = new AbortController()
const cache = new Map<string, { rows: MeshLinkDetail[]; group: MeshBusinessMetricGroup }>()
const pending = new Map<string, Promise<void>>()
function phase(key: MeshBusinessMetricKey, value: MeshLoadingPhase, message = '', cached = false): void { statuses.value[key] = { phase: value, message: message || meshLoadingPhaseLabel(value), cached } }
function query() { return { time_from: windowRange.value.start, time_to: windowRange.value.end, radio: filters.value.radio, peer_ap_mac: filters.value.ap, exact_ap: true, link_role: filters.value.role, include_zero: filters.value.include_zero, ...scope.value } }
function cancel(): void { generation++; mainController.abort(); mainController = new AbortController(); pending.clear(); clearTimeout(zoomTimer); definitions.forEach(d => { if (['PREPARING', 'QUERYING', 'PROCESSING', 'RENDERING'].includes(statuses.value[d.key].phase)) phase(d.key, 'CANCELLED') }) }
function resetMain(): void { cancel(); autoSelect = true; selectionGeneration++; groups.value = {}; samples.value = {}; selectedLink.value = null; pointer.value = null; records.value = []; history.value = []; zeroTotal.value = 0; historyTotal.value = 0; recordTotal.value = 0; historyPage.value = 1; recordPage.value = 1 }
function accept(key: MeshBusinessMetricKey, rows: MeshLinkDetail[], group: MeshBusinessMetricGroup): void { samples.value = { ...samples.value, [key]: rows }; groups.value = { ...groups.value, [key]: group }; if (autoSelect && !selectedLink.value && rows.length) selectLink(rows[0]!) }
function finishChart(key: MeshBusinessMetricKey): void { if (statuses.value[key].phase === 'RENDERING') phase(key, 'COMPLETED', '', statuses.value[key].cached) }
async function loadMetric(key: MeshBusinessMetricKey, refresh = false): Promise<void> {
  const local = generation, signal = mainController.signal, values = query(), id = `${props.sessionId}|${key}|${JSON.stringify(values)}`
  if (pending.has(id)) return pending.get(id)
  const hit = cache.get(id)
  if (hit && !refresh) { phase(key, 'RENDERING', '正在绘制缓存图表', true); accept(key, hit.rows, hit.group) }
  phase(key, 'QUERYING', `${hit ? '正在刷新' : '正在查询'} ${definitions.find(d => d.key === key)?.label} 数据`, Boolean(hit))
  const task = (async () => {
    try {
      const result = await listMeshLinks(props.sessionId, { ...values, metric_group: key, max_points: 1000, page_size: 1000 }, signal)
      if (local !== generation || signal.aborted) return
      phase(key, 'PROCESSING', key === 'counters' ? '正在整理计数器增量' : '正在整理链路数据')
      await nextTick()
      if (local !== generation || signal.aborted) return
      const numeric = (value: unknown): number | null => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value)
      const adapted = result.items.map(row => ({ ...row, local_rssi: row.local_rssi_db, peer_rssi: row.peer_rssi_db, local_rate_raw: numeric(row.local_rate_raw), peer_rate_raw: numeric(row.peer_rate_raw), local_error_delta: row.local_err_delta, peer_error_delta: row.peer_err_delta }))
      const group = buildMeshBusinessMetricGroups(adapted, key)[0]!
      cache.set(id, { rows: result.items, group }); while (cache.size > 16) cache.delete(cache.keys().next().value!)
      phase(key, 'RENDERING', result.items.length ? '正在绘制图表' : '正在绘制空数据视图', Boolean(hit))
      accept(key, result.items, group)
    } catch (error) { if (local === generation) phase(key, signal.aborted ? 'CANCELLED' : 'ERROR', signal.aborted ? '' : error instanceof Error ? error.message : '查询失败') }
    finally { if (local === generation) pending.delete(id) }
  })()
  pending.set(id, task); return task
}
async function loadOverview(): Promise<void> {
  const local = auxGeneration, signal = auxController.signal; summaryError.value = ''
  try { const value = await getMeshBusinessSummary(props.sessionId, scope.value, signal); if (local === auxGeneration && !signal.aborted) business.value = value } catch (error) { if (!signal.aborted) summaryError.value = error instanceof Error ? error.message : '摘要查询失败' }
}
async function loadAps(): Promise<void> {
  const request = ++apRequest, local = auxGeneration, signal = auxController.signal; apLoading.value = true
  try { const result = await listMeshApSignalStatistics(props.sessionId, { page: apPage.value, page_size: 100, ...scope.value }, signal); if (request === apRequest && local === auxGeneration && !signal.aborted) { aps.value = result.items; apTotal.value = result.total } } catch (error) { if (!signal.aborted) ElMessage.warning(String(error)) } finally { if (request === apRequest && local === auxGeneration) apLoading.value = false }
}
async function loadIssues(): Promise<void> {
  const local = auxGeneration, signal = auxController.signal; parseLoading.value = true
  try { const result = await listMeshParseIssues(props.sessionId, { page: 1, page_size: 100 }, signal); if (local === auxGeneration && !signal.aborted) parseIssues.value = result.items } catch (error) { if (!signal.aborted) ElMessage.warning(String(error)) } finally { if (local === auxGeneration) parseLoading.value = false }
}
async function loadRecords(): Promise<void> {
  const request = ++recordRequest, local = generation, signal = mainController.signal; recordLoading.value = true
  try { const result = await listMeshActiveBuildOrder(props.sessionId, { ...query(), peer: filters.value.ap, page: recordPage.value, page_size: 100 }, signal); if (request === recordRequest && local === generation && !signal.aborted) { records.value = result.items; recordTotal.value = result.total } } catch (error) { if (!signal.aborted) ElMessage.warning(String(error)) } finally { if (request === recordRequest && local === generation) recordLoading.value = false }
}
async function loadHistory(): Promise<void> {
  const request = ++historyRequest, local = generation, signal = mainController.signal; historyLoading.value = true
    try { const result = await listMeshLinks(props.sessionId, { ...query(), page: historyPage.value, page_size: 100 }, signal); if (request === historyRequest && local === generation && !signal.aborted) { history.value = result.items; historyTotal.value = result.total; zeroTotal.value = result.zero_link_count || 0 } } catch (error) { if (!signal.aborted) ElMessage.warning(String(error)) } finally { if (request === historyRequest && local === generation) historyLoading.value = false }
}
function loadMain(refresh = false): void { definitions.forEach(d => { void loadMetric(d.key, refresh) }); void loadRecords(); void loadHistory() }
function changeFilters(): void { resetMain(); loadMain() }
function setWindow(value: MeshMonitorWindow): void {
  if (millis(value.start) === null || millis(value.end) === null || millis(value.start)! >= millis(value.end)!) { ElMessage.warning('请输入有效的起止时间'); return }
  cancel(); windowRange.value = value
  zoomTimer = setTimeout(() => { groups.value = {}; samples.value = {}; historyPage.value = 1; recordPage.value = 1; if (selectedLink.value && (millis(selectedLink.value.timestamp)! < millis(value.start)! || millis(selectedLink.value.timestamp)! > millis(value.end)!)) selectedLink.value = null; loadMain() }, 180)
}
function selectLink(row: MeshLinkDetail): void { selectedLink.value = row; pointer.value = row.timestamp }
function selectMetric(key: MeshBusinessMetricKey): void { activeMetric.value = key; const rows = samples.value[key] || []; const focus = millis(pointer.value); const selected = focus === null ? rows.at(-1) : rows.reduce<MeshLinkDetail | undefined>((best, row) => !best || Math.abs((millis(row.timestamp) || 0) - focus) < Math.abs((millis(best.timestamp) || 0) - focus) ? row : best, undefined); if (selected) selectLink(selected); document.getElementById(`monitor-${key}`)?.scrollIntoView({ block: 'nearest', behavior: 'auto' }) }
async function selectBuild(row: MeshActiveBuildOrder): Promise<void> {
  const selection = ++selectionGeneration
  const local = generation, signal = mainController.signal
  const result = await listMeshLinks(props.sessionId, { ...query(), radio: row.local_radio ?? undefined, peer_ap_mac: row.peer_ap_mac || '', query: row.active_peer_mac || '', link_role: row.link_count === 0 ? '' : 'ACTIVE', include_zero: row.link_count === 0, time_from: row.observation_time || row.first_sample_time || row.build_start_time, time_to: row.observation_time || row.build_end_time, page_size: 1 }, signal).catch(() => null)
  if (selection === selectionGeneration && result?.items[0] && local === generation && !signal.aborted) selectLink(result.items[0])
}
function switchWorkspace(value: Workspace): void {
  if (workspace.value !== value) { cancel(); auxGeneration++; auxController.abort(); auxController = new AbortController(); groups.value = {}; samples.value = {} }
  workspace.value = value; emit('workspaceChange', value)
  if (value === 'main') loadMain(); if (value === 'aps') void loadAps(); if (value === 'parse') void loadIssues(); if (value === 'overview' && !business.value) void loadOverview()
}
function changeScope(): void { auxGeneration++; auxController.abort(); auxController = new AbortController(); business.value = null; emit('scopeChange', scope.value); void loadOverview(); if (workspace.value === 'main') changeFilters(); if (workspace.value === 'aps') void loadAps() }
function openAp(row: MeshApSignal): void { resetMain(); filters.value.ap = row.peer_ap_mac || ''; filters.value.role = ''; switchWorkspace('main') }
async function openContext(context: { ap?: string; radio?: number | null; start: string; end: string; focus?: string | null }): Promise<void> {
  resetMain(); autoSelect = !context.focus; filters.value.include_zero = false; filters.value.ap = context.ap || ''; filters.value.radio = context.radio ?? undefined; filters.value.role = 'ACTIVE'; windowRange.value = { start: context.start, end: context.end }; workspace.value = 'main'; emit('workspaceChange', 'main'); loadMain();
  if (context.focus) { const local = generation, signal = mainController.signal; const result = await listMeshLinks(props.sessionId, { ...query(), time_from: context.focus, time_to: context.focus, page_size: 1 }, signal).catch(() => null); if (local === generation && result?.items[0]) selectLink(result.items[0]) }
}
defineExpose({ openContext, switchWorkspace })
watch(() => props.sessionId, () => {
  resetMain(); auxGeneration++; auxController.abort(); auxController = new AbortController(); cache.clear(); business.value = null; aps.value = []; parseIssues.value = []; workspace.value = 'overview'; emit('workspaceChange', 'overview');
  domain.value = { start: props.session.first_sample_time || '', end: props.session.last_sample_time || '' }; windowRange.value = { start: stamp(Math.max(millis(domain.value.start) || 0, (millis(domain.value.end) || 0) - 300_000)), end: domain.value.end }; void loadOverview()
}, { immediate: true })
onDeactivated(() => { cancel(); auxGeneration++; auxController.abort(); auxController = new AbortController(); groups.value = {}; samples.value = {} })
onActivated(() => { if (workspace.value === 'main' && !Object.keys(groups.value).length) loadMain() })
onBeforeUnmount(() => { cancel(); auxGeneration++; auxController.abort(); cache.clear() })
const apColumns: NcTableColumn<MeshApSignal>[] = [{ key: 'peer_ap_name', label: 'AP 名称' }, { key: 'peer_ap_mac', label: 'AP MAC' }, { key: 'station', label: '归属站点' }, { key: 'section', label: '归属区间' }, { key: 'avg_rssi', label: '平均 RSSI' }, { key: 'min_rssi', label: '最低 RSSI' }, { key: 'signal_grade', label: '信号质量' }, { key: 'valid_sample_count', label: '有效采样' }, { key: 'last_seen', label: '最近采样时间' }]
const parseColumns: NcTableColumn<MeshParseIssue>[] = [{ key: 'severity', label: '级别' }, { key: 'code', label: '异常类型' }, { key: 'message', label: '简要原因' }]
const recordColumns: NcTableColumn<MeshActiveBuildOrder>[] = [{ key: 'sequence', label: '序号' }, { key: 'local_radio', label: 'Radio' }, { key: 'first_sample_time', label: '首次采样时间' }, { key: 'build_start_time', label: '建链开始时间', displayValue: row => row.link_count === 0 ? '—' : row.build_start_time }, { key: 'build_end_time', label: '建链结束时间', displayValue: row => row.link_count === 0 ? '—' : row.build_end_time }, { key: 'main_link_duration_seconds', label: '持续时长 (s)' }, { key: 'peer_ap_name', label: 'AP 名称' }, { key: 'peer_ap_mac', label: 'AP MAC' }, { key: 'peer_radio', label: '对端射频口' }, { key: 'build_result', label: '链路状态', displayValue: row => ({ normal: '正常', short: '短时建链', pingpong: '乒乓切换', UNCONNECTED: '未连接' }[row.build_result] || row.build_result) }, { key: 'avg_mr_rssi', label: '平均 RSSI' }, { key: 'min_mr_rssi', label: '最低 RSSI' }, { key: 'p10_mr_rssi', label: 'P10 RSSI' }]
const historyColumns: NcTableColumn<MeshLinkDetail>[] = [{ key: 'timestamp', label: '采样时间' }, { key: 'peer_ap_name', label: 'AP 名称' }, { key: 'peer_ap_mac', label: 'AP MAC' }, { key: 'local_radio', label: 'Radio' }, { key: 'peer_radio', label: '对端射频口' }, { key: 'link_role', label: '历史角色' }, { key: 'link_count', label: '链路数量' }, { key: 'local_rssi_db', label: 'L RSSI' }, { key: 'peer_rssi_db', label: 'P RSSI' }]
const detailPairs = [{ label: 'RSSI', local: 'local_rssi_db', peer: 'peer_rssi_db' }, { label: 'CPU (%)', local: 'local_cpu_percent', peer: 'peer_cpu_percent' }, { label: 'Memory (%)', local: 'local_mem_percent', peer: 'peer_mem_percent' }, { label: 'TxBusy (%)', local: 'local_tx_busy', peer: 'peer_tx_busy' }, { label: 'RxBusy (%)', local: 'local_rx_busy', peer: 'peer_rx_busy' }, { label: 'Rate', local: 'local_rate_raw', peer: 'peer_rate_raw' }, { label: 'Noise (dBm)', local: 'local_noise_dbm', peer: 'peer_noise_dbm' }, { label: 'TxDesFreeCnt', local: 'local_tx_des_free_cnt', peer: 'peer_tx_des_free_cnt' }, { label: 'Tx', local: 'local_tx', peer: 'peer_tx' }, { label: 'Rx', local: 'local_rx', peer: 'peer_rx' }, { label: 'Retry', local: 'local_retry', peer: 'peer_retry' }, { label: 'Err', local: 'local_err', peer: 'peer_err' }, { label: 'GARP', local: 'local_tx_garp', peer: 'peer_rx_garp' }, { label: 'MulJoin', local: 'local_tx_mul_join', peer: 'peer_rx_mul_join' }] as const
function detailValue(field: string): unknown { return (selectedLink.value as unknown as Record<string, unknown> | null)?.[field] ?? '—' }
const completed = computed(() => definitions.filter(d => statuses.value[d.key].phase === 'COMPLETED').length)
function latest(key: MeshBusinessMetricKey): string { const lines = groups.value[key]?.lines || []; return lines.slice(0, 2).map(line => `${line.side === 'local' ? 'L' : 'P'} ${line.data.at(-1)?.value[1] ?? '—'}`).join(' / ') || '—' }
</script>

<template>
<section class="mesh-phase11" aria-label="MESH 业务工作台">
  <div class="phase11-top"><nav class="phase11-nav" aria-label="分析工作区"><button v-for="item in [{ key: 'overview', label: '分析概览' }, { key: 'parse', label: '日志解析' }, { key: 'aps', label: 'AP 情况' }, { key: 'main', label: '主链路监控' }]" :key="item.key" :class="{ active: workspace === item.key }" @click="switchWorkspace(item.key as Workspace)">{{ item.label }}</button></nav><div class="phase11-scope"><el-checkbox v-model="scope.exclude_depot" @change="changeScope">排除车辆段</el-checkbox><el-checkbox v-model="scope.exclude_parking" @change="changeScope">排除停车场</el-checkbox></div></div>
  <div v-if="workspace === 'overview'"><el-alert v-if="summaryError" :title="summaryError" type="error" :closable="false" /><el-skeleton v-if="!business && !summaryError" :rows="2" animated /><template v-if="business"><div class="phase11-cards"><button @click="switchWorkspace('aps')"><span>物理 AP</span><strong>{{ business.ap_total }}</strong></button><button v-for="(label, key) in { GOOD: '信号良好', WARNING: '信号关注', BAD: '信号较差', INSUFFICIENT: '数据不足' }" :key="key" @click="switchWorkspace('aps')"><span>{{ label }}</span><strong>{{ business.grades[key] || 0 }}</strong></button><button @click="switchWorkspace('main')"><span>单链路风险</span><strong>{{ business.single_link_count }}</strong></button></div><p class="phase11-secondary">有效记录 {{ session.link_record_count }} · ACTIVE {{ session.active_link_count }} · STANDBY {{ session.standby_link_count }} · 解析异常 {{ session.error_count + session.warning_count }}</p></template><slot name="overview" /></div>
  <div v-else-if="workspace === 'parse'"><p class="phase11-secondary">解析状态 {{ session.parsed_status === 'ready' ? '已完成' : session.parsed_status }} · 成功解析 {{ session.link_record_count }} · 异常 {{ session.error_count + session.warning_count }} · 数据完整性 {{ session.data_integrity === 'complete' ? '完整' : '存在缺失' }}</p><NcDataTable table-id="mesh-phase11-parse:v2" route-key="/rail-transit/mesh-analysis" :data="parseIssues" :columns="parseColumns" :loading="parseLoading" empty-text="暂无解析异常" /></div>
  <div v-else-if="workspace === 'aps'"><p class="phase11-secondary">{{ apTotal }} 个 AP · 点击 AP 查看历史链路与同期指标</p><NcDataTable table-id="mesh-phase11-aps:v2" route-key="/rail-transit/mesh-analysis" :data="aps" :columns="apColumns" :loading="apLoading" @row-click="openAp" empty-text="暂无 AP 数据" /><el-pagination v-model:current-page="apPage" :page-size="100" :total="apTotal" layout="prev,pager,next" @current-change="loadAps" /></div>
  <div v-else class="phase11-monitor">
    <div class="phase11-filters"><el-input v-model="filters.ap" clearable placeholder="AP MAC（留空为全部）" @change="changeFilters" /><el-select v-model="filters.radio" clearable placeholder="全部 Radio" @change="changeFilters"><el-option :value="1" label="Radio 1" /><el-option :value="2" label="Radio 2" /></el-select><el-select v-model="filters.role" @change="changeFilters"><el-option value="" label="全部角色" /><el-option value="ACTIVE" label="ACTIVE" /><el-option value="STANDBY" label="STANDBY" /></el-select><el-checkbox v-model="filters.include_zero" @change="changeFilters">包含 LinkCnt=0</el-checkbox><el-button size="small" @click="loadMain(true)">刷新</el-button><span>{{ completed }}/8 图表完成</span></div>
    <div class="phase11-range"><el-input :model-value="windowRange.start" aria-label="监控开始时间" @change="(value: string) => setWindow({ ...windowRange, start: value })" /><span>至</span><el-input :model-value="windowRange.end" aria-label="监控结束时间" @change="(value: string) => setWindow({ ...windowRange, end: value })" /><el-button size="small" @click="setWindow({ ...domain })">完整范围</el-button></div>
    <div class="phase11-monitor-body"><aside class="phase11-side-summary"><button v-for="def in definitions" :key="def.key" :class="{ active: activeMetric === def.key }" @click="selectMetric(def.key)"><strong>{{ def.label }}</strong><span>{{ latest(def.key) }}</span><small>{{ statuses[def.key].message }}</small></button></aside>
      <main class="phase11-metrics"><article v-for="(def, index) in definitions" :id="`monitor-${def.key}`" :key="def.key" class="metric-panel" :class="{ active: activeMetric === def.key }"><header><strong>{{ def.label }}</strong><span role="status" :class="`phase-${statuses[def.key].phase.toLowerCase()}`">{{ statuses[def.key].message }}{{ statuses[def.key].cached ? ' · 缓存命中' : '' }}</span><el-button v-if="statuses[def.key].phase === 'ERROR'" link size="small" @click="loadMetric(def.key, true)">重试</el-button></header><MeshMetricChart v-if="groups[def.key]" :lines="groups[def.key]!.lines" :unit="def.unit" :domain="domain" :window="windowRange" :pointer="pointer" :selected-time="selectedLink?.timestamp" :navigator="index === 7" @viewport-change="setWindow" @pointer-change="pointer = $event" @sample-select="selectLink($event as MeshLinkDetail)" @render-complete="finishChart(def.key)" @render-error="phase(def.key, 'ERROR', $event)" /><div v-else class="chart-skeleton"><el-skeleton :rows="2" :animated="statuses[def.key].phase !== 'ERROR'" /></div></article></main>
      <aside class="phase11-detail"><h4>主链路详情</h4><template v-if="selectedLink"><strong>{{ selectedLink.peer_ap_name || '未匹配 AP' }}</strong><p>{{ selectedLink.peer_ap_mac || selectedLink.peer_mac || '—' }}</p><dl><dt>采样时间</dt><dd>{{ selectedLink.timestamp }}</dd><dt>Radio / 对端射频口</dt><dd>{{ selectedLink.local_radio }} / {{ selectedLink.peer_radio || '—' }}</dd><dt>历史角色</dt><dd>{{ selectedLink.link_count === 0 ? '未连接（LinkCnt=0）' : selectedLink.link_role }}</dd><dt>建链时间</dt><dd>{{ selectedLink.link_count === 0 ? '—' : selectedLink.establish_time || '—' }}</dd><dt>持续时间</dt><dd>{{ selectedLink.link_count === 0 ? '—' : selectedLink.duration_seconds ?? '—' }} s</dd></dl><table><thead><tr><th>指标</th><th>本端 L</th><th>对端 P</th></tr></thead><tbody><tr v-for="pair in detailPairs" :key="pair.label"><td>{{ pair.label }}</td><td>{{ detailValue(pair.local) }}</td><td>{{ detailValue(pair.peer) }}</td></tr></tbody></table></template><el-empty v-else description="当前窗口暂无选中样本" :image-size="40" /></aside></div>
    <section class="phase11-records"><h4>主链路记录（建链顺序）</h4><NcDataTable table-id="mesh-phase11-builds:v1" route-key="/rail-transit/mesh-analysis" :data="records" :max-height="390" :columns="recordColumns" :loading="recordLoading" @row-click="selectBuild" empty-text="当前窗口无有效建链区段" /><el-pagination v-model:current-page="recordPage" :total="recordTotal" :page-size="100" layout="total,prev,pager,next" @current-change="loadRecords" /></section>
    <details class="phase11-history" open><summary>AP 历史采样 · {{ historyTotal }} 条 · 未连接 {{ zeroTotal }} 条</summary><NcDataTable table-id="mesh-phase11-history:v1" route-key="/rail-transit/mesh-analysis" :data="history" :max-height="390" :columns="historyColumns" :loading="historyLoading" @row-click="selectLink" empty-text="当前 AP、Radio 和时间窗口无有效数据" /><el-pagination v-model:current-page="historyPage" :total="historyTotal" :page-size="100" layout="total,prev,pager,next" @current-change="loadHistory" /></details>
  </div>
</section>
</template>
<style scoped>
.mesh-phase11{min-width:0;display:flex;flex-direction:column;gap:10px}.phase11-top{display:flex;justify-content:space-between;border-bottom:1px solid var(--nc-border-light)}.phase11-nav{display:flex;gap:3px}.phase11-nav button{padding:10px 16px;background:transparent;border:0;border-bottom:2px solid transparent;color:var(--nc-text-secondary);cursor:pointer}.phase11-nav button.active{color:var(--nc-primary);border-bottom-color:var(--nc-primary)}.phase11-scope{display:flex;gap:12px;align-items:center}.phase11-cards{display:grid;grid-template-columns:repeat(6,minmax(80px,1fr));gap:8px}.phase11-cards button{padding:10px 14px;text-align:left;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:5px;color:var(--nc-text-primary);cursor:pointer}.phase11-cards span{font-size:12px;color:var(--nc-text-secondary)}.phase11-cards strong{float:right;font-size:20px}.phase11-secondary{font-size:12px;color:var(--nc-text-secondary);margin:10px 0}.phase11-filters,.phase11-range{display:flex;gap:10px;align-items:center;margin-bottom:8px;font-size:12px;flex-wrap:wrap}.phase11-filters .el-input{width:250px}.phase11-filters .el-select{width:135px}.phase11-range .el-input{width:235px}.phase11-monitor-body{display:grid;grid-template-columns:150px minmax(0,1fr) 320px;gap:10px;align-items:start}.phase11-side-summary,.phase11-detail{position:sticky;top:8px;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:5px;padding:10px;max-height:calc(100vh - 80px);overflow:auto}.phase11-side-summary button{display:block;width:100%;text-align:left;background:transparent;color:var(--nc-text-primary);border:0;border-bottom:1px solid var(--nc-border-light);padding:10px 2px;cursor:pointer}.phase11-side-summary strong,.phase11-side-summary span,.phase11-side-summary small{display:block;overflow-wrap:anywhere;font-size:11px;margin-bottom:4px}.phase11-side-summary small{color:var(--nc-text-secondary)}.phase11-side-summary .active{color:var(--nc-primary)}.phase11-metrics{display:flex;flex-direction:column;gap:8px;min-width:0}.metric-panel{min-width:0;padding:8px;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:5px}.metric-panel.active{border-color:var(--nc-primary)}.metric-panel header{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:12px}.metric-panel header span{font-size:11px;color:var(--nc-text-secondary)}.phase-error{color:var(--nc-danger)!important}.phase-querying,.phase-processing,.phase-rendering{color:var(--nc-primary)!important}.phase-completed{color:var(--nc-success)!important}.chart-skeleton{min-height:190px;padding:25px}.phase11-detail h4{margin:0 0 12px}.phase11-detail p{font-size:11px;color:var(--nc-text-secondary)}.phase11-detail dl{display:grid;grid-template-columns:90px 1fr;gap:7px;font-size:11px}.phase11-detail dt{color:var(--nc-text-secondary)}.phase11-detail dd{margin:0;text-align:right;overflow-wrap:anywhere}.phase11-detail table{width:100%;border-collapse:collapse;font-size:11px}.phase11-detail td,.phase11-detail th{padding:6px 2px;text-align:right;border-bottom:1px solid var(--nc-border-light)}.phase11-detail td:first-child,.phase11-detail th:first-child{text-align:left}.phase11-records,.phase11-history{margin-top:14px}.phase11-history summary{cursor:pointer;margin-bottom:8px;font-size:13px}
@media(max-width:1100px){.phase11-monitor-body{grid-template-columns:140px minmax(0,1fr)}.phase11-detail{position:static;grid-column:1/-1}.phase11-top{flex-wrap:wrap}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>
