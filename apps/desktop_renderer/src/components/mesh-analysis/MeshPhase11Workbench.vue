<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import MeshMetricChart, { type MeshMetricPoint } from './MeshMetricChart.vue'
import NcDataTable from '../table/NcDataTable.vue'
import type { NcTableColumn } from '../table/NcTableColumn'
import {
  getMeshActivePathChart, getMeshBusinessSummary, getMeshCounterDeltas, listMeshApSignalStatistics, listMeshLinks, listMeshParseIssues,
} from '../../api/meshAnalysis'
import type { MeshActiveBuildOrder, MeshAnalysisSession, MeshApSignal, MeshBusinessSummary, MeshChartPoint, MeshCounterDeltaPoint, MeshLinkDetail, MeshParseIssue } from '../../types/meshAnalysis'
import type { MeshPathChart } from '../../types/meshAnalysis'
import { isMeshLoadingActivePhase, meshLoadingPhaseLabel, type MeshLoadingPhase } from './meshLoadingState'

type Workspace = 'overview' | 'parse' | 'aps' | 'main'
type MetricKey = 'rssi' | 'cpu' | 'memory' | 'busy' | 'rate' | 'noise' | 'txdes' | 'counter'
type ChartStatus = { phase: MeshLoadingPhase; message: string; error: string; cached: boolean }
const props = defineProps<{ sessionId: string; session: MeshAnalysisSession }>()
const emit = defineEmits<{ scopeChange: [scope: { exclude_depot: boolean; exclude_parking: boolean }] }>()
const workspace = ref<Workspace>('overview')
const scope = ref({ exclude_depot: true, exclude_parking: true })
const business = ref<MeshBusinessSummary | null>(null)
const aps = ref<MeshApSignal[]>([])
const apTotal = ref(0)
const links = ref<MeshLinkDetail[]>([])
const linkTotal = ref(0)
const counter = ref<MeshCounterDeltaPoint[]>([])
const activePath = ref<MeshPathChart | null>(null)
const parseIssues = ref<MeshParseIssue[]>([])
const parseTotal = ref(0)
const selectedLink = ref<MeshLinkDetail | null>(null)
const mainLoading = ref(false)
const mainError = ref('')
const apLoading = ref(false)
const parseLoading = ref(false)
const generation = ref(0)
let controller: AbortController | null = null
const cache = new Map<string, { business: MeshBusinessSummary | null; aps: MeshApSignal[]; links: MeshLinkDetail[]; counter: MeshCounterDeltaPoint[]; activePath: MeshPathChart | null }>()
const chartStatus = ref<Record<MetricKey, ChartStatus>>(Object.fromEntries((['rssi', 'cpu', 'memory', 'busy', 'rate', 'noise', 'txdes', 'counter'] as MetricKey[]).map(key => [key, { phase: 'IDLE', message: meshLoadingPhaseLabel('IDLE'), error: '', cached: false }])) as Record<MetricKey, ChartStatus>)
const metricDefinitions: Array<{ key: MetricKey; label: string; color: string; unit?: string }> = [
  { key: 'rssi', label: 'RSSI', color: '#4f9dff', unit: ' dBm' },
  { key: 'cpu', label: 'CPU', color: '#f2b84b', unit: '%' },
  { key: 'memory', label: '内存', color: '#8b7cff', unit: '%' },
  { key: 'busy', label: 'TxBusy / RxBusy', color: '#41c7a2', unit: '%' },
  { key: 'rate', label: 'Rate', color: '#ff8b6b' },
  { key: 'noise', label: 'Noise', color: '#a6d86d', unit: ' dBm' },
  { key: 'txdes', label: 'TxDesFreeCnt', color: '#d78cff' },
  { key: 'counter', label: 'Tx / Rx / Retry / Err / GARP / MulJoin', color: '#5dd3e8' },
]
const metricRows = computed(() => metricDefinitions.map(def => ({ ...def, points: metricPoints(def.key) })))
const parseSummary = computed(() => {
  const parsed = props.session.link_record_count ?? 0
  const raw = Math.max(props.session.raw_log_count || 0, parsed)
  return { raw: props.session.raw_log_count, parsed, errors: props.session.error_count, ratio: raw ? parsed / raw * 100 : 0 }
})
const activeCount = computed(() => links.value.filter(row => row.link_role === 'ACTIVE').length)
const standbyCount = computed(() => links.value.filter(row => row.link_role === 'STANDBY').length)
const selectedPathLabel = computed(() => selectedLink.value ? `${selectedLink.value.peer_ap_name || '未命名 AP'} · Radio ${selectedLink.value.local_radio ?? '—'}` : '选择底部记录查看链路详情')
const apColumns: NcTableColumn<MeshApSignal>[] = [
  { key: 'peer_ap_name', label: 'AP 名称', valueType: 'name' }, { key: 'peer_ap_mac', label: 'AP MAC', valueType: 'mac' },
  { key: 'station', label: '归属站点' }, { key: 'section', label: '归属区间' }, { key: 'avg_rssi', label: '平均 RSSI', valueType: 'number' },
  { key: 'min_rssi', label: '最低 RSSI', valueType: 'number' }, { key: 'signal_grade', label: '信号质量' }, { key: 'valid_sample_count', label: '有效采样', valueType: 'number' },
  { key: 'first_seen', label: '最近采样时间', valueType: 'datetime' },
]
const linkColumns: NcTableColumn<MeshLinkDetail>[] = [
  { key: 'timestamp', label: '采样时间', valueType: 'datetime' }, { key: 'peer_ap_name', label: 'AP 名称', valueType: 'name' },
  { key: 'peer_ap_mac', label: 'AP MAC', valueType: 'mac' }, { key: 'peer_radio', label: '对端射频口' }, { key: 'link_role', label: '链路状态' },
  { key: 'local_rssi_db', label: 'RSSI', valueType: 'number' }, { key: 'local_cpu_percent', label: 'CPU', valueType: 'number' },
  { key: 'local_mem_percent', label: '内存', valueType: 'number' }, { key: 'local_tx_busy', label: 'TxBusy', valueType: 'number' }, { key: 'local_rx_busy', label: 'RxBusy', valueType: 'number' },
]
const parseColumns: NcTableColumn<MeshParseIssue>[] = [
  { key: 'severity', label: '级别' }, { key: 'code', label: '异常类型' }, { key: 'message', label: '简要说明' },
]
function setChartPhase(key: MetricKey, phase: MeshLoadingPhase, error = '', cached = false): void { chartStatus.value[key] = { phase, message: error || meshLoadingPhaseLabel(phase), error, cached } }
function metricPoints(key: MetricKey): MeshMetricPoint[] {
  if (key === 'counter') return counter.value.map(row => ({ timestamp: row.timestamp, value: row.local_tx_per_second ?? row.local_rx_per_second ?? row.local_retry_per_second ?? null }))
  const sourceRows = key === 'rssi' ? (activePath.value?.points || links.value) : (links.value.length ? links.value : (activePath.value?.points || []))
  return sourceRows.map((row: MeshChartPoint | MeshLinkDetail) => {
    const source = row as MeshChartPoint & MeshLinkDetail
    let value: number | null = null
    if (key === 'rssi') value = source.local_rssi ?? source.local_rssi_db ?? null
    if (key === 'cpu') value = source.local_cpu_percent ?? null
    if (key === 'memory') value = source.local_mem_percent ?? null
    if (key === 'busy') value = source.local_tx_busy ?? null
    if (key === 'rate') value = typeof source.local_rate_raw === 'number' ? source.local_rate_raw : Number(source.local_rate_raw) || null
    if (key === 'noise') value = source.local_noise_dbm ?? null
    if (key === 'txdes') value = source.local_tx_des_free_cnt ?? null
    return { timestamp: source.timestamp, value }
  }).filter(point => point.value !== null)
}
function useCached(key: string): boolean {
  const hit = cache.get(key)
  if (!hit) return false
  business.value = hit.business; aps.value = hit.aps; links.value = hit.links; counter.value = hit.counter; activePath.value = hit.activePath
  return true
}
async function loadOverview(): Promise<void> {
  const key = `${props.sessionId}|${JSON.stringify(scope.value)}`
  if (useCached(key)) return
  const local = ++generation.value
  controller?.abort(); controller = new AbortController()
  try { business.value = await getMeshBusinessSummary(props.sessionId, scope.value, controller.signal); if (local === generation.value) cache.set(key, { business: business.value, aps: aps.value, links: links.value, counter: counter.value, activePath: activePath.value }) } catch (error) { if (!controller.signal.aborted) ElMessage.warning(error instanceof Error ? error.message : '业务摘要加载失败') }
}
async function loadAps(): Promise<void> {
  apLoading.value = true
  try { const result = await listMeshApSignalStatistics(props.sessionId, { page: 1, page_size: 500, ...scope.value }); aps.value = result.items; apTotal.value = result.total } catch (error) { ElMessage.warning(error instanceof Error ? error.message : 'AP 统计加载失败') } finally { apLoading.value = false }
}
async function loadParse(): Promise<void> {
  parseLoading.value = true
  try { const result = await listMeshParseIssues(props.sessionId, { page: 1, page_size: 100 }); parseIssues.value = result.items; parseTotal.value = result.total } catch (error) { ElMessage.warning(error instanceof Error ? error.message : '解析异常加载失败') } finally { parseLoading.value = false }
}
async function loadMain(): Promise<void> {
  const key = `${props.sessionId}|main|${JSON.stringify(scope.value)}`
  if (useCached(key)) { metricDefinitions.forEach(def => setChartPhase(def.key, 'COMPLETED', '', true)); return }
  const local = ++generation.value
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  mainLoading.value = true; mainError.value = ''
  metricDefinitions.forEach(def => setChartPhase(def.key, 'PREPARING'))
  try {
    setChartPhase('rssi', 'QUERYING', '正在查询 ACTIVE 主链路数据')
    const pathPromise = getMeshActivePathChart(props.sessionId, { max_points: 1200, view_mode: 'overview', resolution_mode: 'overview' }, signal)
    setChartPhase('counter', 'QUERYING', '正在查询 Tx/Rx 计数器')
    const counterPromise = getMeshCounterDeltas(props.sessionId, { max_points: 1200 }, signal)
    setChartPhase('cpu', 'QUERYING', '正在查询主链路指标')
    const linksPromise = listMeshLinks(props.sessionId, { page: 1, page_size: 500, link_roles: ['ACTIVE', 'STANDBY'], ...scope.value }, signal)
    const [path, counters, linkPage] = await Promise.all([pathPromise, counterPromise, linksPromise])
    if (local !== generation.value || signal.aborted) return
    activePath.value = path; counter.value = counters.items; links.value = linkPage.items; linkTotal.value = linkPage.total
    setChartPhase('rssi', 'PROCESSING', '正在整理链路数据'); setChartPhase('counter', 'PROCESSING', '正在计算每秒增量')
    for (const def of metricDefinitions) if (def.key !== 'rssi' && def.key !== 'counter') setChartPhase(def.key, 'PROCESSING', '正在处理主链路指标')
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
    cache.set(key, { business: business.value, aps: aps.value, links: links.value, counter: counter.value, activePath: activePath.value })
    metricDefinitions.forEach(def => setChartPhase(def.key, 'RENDERING', '正在绘制图表'))
  } catch (error) {
    if (signal.aborted) { metricDefinitions.forEach(def => setChartPhase(def.key, 'CANCELLED')); return }
    mainError.value = error instanceof Error ? error.message : '主链路数据加载失败'; metricDefinitions.forEach(def => setChartPhase(def.key, 'ERROR', mainError.value))
  } finally { if (local === generation.value) mainLoading.value = false }
}
function onChartRendered(key: MetricKey): void { setChartPhase(key, 'COMPLETED', '', chartStatus.value[key].cached) }
function onChartError(key: MetricKey, error: string): void { setChartPhase(key, 'ERROR', error) }
function switchWorkspace(next: Workspace): void { workspace.value = next; if (next === 'overview') void loadOverview(); if (next === 'aps' && !aps.value.length) void loadAps(); if (next === 'parse' && !parseIssues.value.length) void loadParse(); if (next === 'main' && !links.value.length) void loadMain() }
function changeScope(): void { emit('scopeChange', scope.value); void loadOverview(); if (workspace.value === 'main') void loadMain() }
function selectLink(row: MeshLinkDetail): void { selectedLink.value = row }
watch(() => props.sessionId, () => { generation.value++; controller?.abort(); business.value = null; aps.value = []; links.value = []; counter.value = []; activePath.value = null; workspace.value = 'overview'; void loadOverview() }, { immediate: true })
onBeforeUnmount(() => { generation.value++; controller?.abort() })
</script>

<template>
  <section class="mesh-phase11" aria-label="MESH 业务工作台">
    <div class="phase11-head">
      <div><span class="phase11-eyebrow">MESH BUSINESS WORKSPACE</span><h2>MR 原始 MESH 日志分析</h2><p>{{ session.mr_name || session.train_name }} · {{ session.first_sample_time || '—' }} 至 {{ session.last_sample_time || '—' }}</p></div>
      <div class="phase11-scope"><el-checkbox v-model="scope.exclude_depot" @change="changeScope">排除车辆段</el-checkbox><el-checkbox v-model="scope.exclude_parking" @change="changeScope">排除停车场</el-checkbox></div>
    </div>
    <nav class="phase11-nav" aria-label="分析工作区"><button v-for="item in [{ key: 'overview', label: '分析概览' }, { key: 'parse', label: '日志解析' }, { key: 'aps', label: 'AP 情况' }, { key: 'main', label: '主链路监控' }]" :key="item.key" :class="{ active: workspace === item.key }" @click="switchWorkspace(item.key as Workspace)">{{ item.label }}</button></nav>
    <div v-if="workspace === 'overview'" class="phase11-panel">
      <div v-if="!business" class="phase11-skeleton"><el-skeleton :rows="3" animated /></div>
      <template v-else><div class="phase11-cards"><button class="phase11-card" @click="switchWorkspace('aps')"><span>物理 AP</span><strong>{{ business.ap_total }}</strong></button><button v-for="key in ['GOOD', 'WARNING', 'BAD', 'INSUFFICIENT']" :key="key" class="phase11-card" @click="switchWorkspace('aps')"><span>{{ key === 'GOOD' ? '信号良好' : key === 'WARNING' ? '信号关注' : key === 'BAD' ? '信号较差' : '数据不足' }}</span><strong>{{ business.grades[key] || 0 }}</strong></button><button class="phase11-card" @click="switchWorkspace('main')"><span>单链路风险</span><strong>{{ business.single_link_count }}</strong></button></div><div class="phase11-summary-grid"><article><span>分析状态</span><strong>{{ session.analysis_status || '已完成' }}</strong></article><article><span>有效记录</span><strong>{{ session.link_record_count ?? 0 }}</strong></article><article><span>ACTIVE 链路</span><strong>{{ session.active_link_count ?? 0 }}</strong></article><article><span>STANDBY 链路</span><strong>{{ session.standby_link_count ?? 0 }}</strong></article><article><span>解析异常</span><strong>{{ session.error_count + session.warning_count }}</strong></article></div></template>
    </div>
    <div v-else-if="workspace === 'parse'" class="phase11-panel"><div class="phase11-summary-grid"><article><span>解析状态</span><strong>{{ session.parsed_status === 'ready' ? '已完成' : session.parsed_status }}</strong></article><article><span>原始记录数</span><strong>{{ parseSummary.raw }}</strong></article><article><span>成功解析数</span><strong>{{ parseSummary.parsed }}</strong></article><article><span>异常记录数</span><strong>{{ parseSummary.errors }}</strong></article><article><span>有效数据比例</span><strong>{{ parseSummary.ratio.toFixed(1) }}%</strong></article><article><span>数据完整性</span><strong>{{ session.data_integrity || '—' }}</strong></article></div><div class="phase11-table"><el-alert v-if="parseLoading" title="正在读取解析异常" type="info" :closable="false" /><NcDataTable table-id="mesh-phase11-parse-issues:v1" route-key="/rail-transit/mesh-analysis" :data="parseIssues" :columns="parseColumns" :loading="parseLoading" empty-text="暂无解析异常" /></div></div>
    <div v-else-if="workspace === 'aps'" class="phase11-panel"><div class="phase11-panel-heading"><div><h3>AP 情况</h3><p>按信号质量、站点和采样时间筛选业务 AP</p></div><span>{{ apTotal }} 个 AP</span></div><NcDataTable table-id="mesh-phase11-aps:v1" route-key="/rail-transit/mesh-analysis" :data="aps" :columns="apColumns" :loading="apLoading" empty-text="暂无 AP 数据" /></div>
    <div v-else class="phase11-panel phase11-monitor">
      <div class="phase11-monitor-toolbar"><div><h3>主链路监控</h3><p>{{ mainError || (mainLoading ? '正在加载主链路数据…' : 'ACTIVE 主链路 · 八组指标') }}</p></div><el-button size="small" :loading="mainLoading" @click="loadMain">刷新</el-button></div>
      <div class="phase11-monitor-body"><aside class="phase11-side-summary"><h4>指标摘要</h4><div><span>ACTIVE 记录</span><strong>{{ activeCount }}</strong></div><div><span>STANDBY 记录</span><strong>{{ standbyCount }}</strong></div><div><span>Counter 样本</span><strong>{{ counter.length }}</strong></div><div><span>风险 AP</span><strong>{{ business?.single_link_ap_count ?? '—' }}</strong></div></aside><main class="phase11-metrics"><article v-for="row in metricRows" :key="row.key" class="metric-panel"><header><strong>{{ row.label }}</strong><span :class="`phase-${chartStatus[row.key].phase.toLowerCase()}`">{{ chartStatus[row.key].message }}</span></header><MeshMetricChart :points="row.points" :color="row.color" :unit="row.unit" @render-complete="onChartRendered(row.key)" @render-error="onChartError(row.key, $event)" /></article></main><aside class="phase11-detail"><h4>主链路详情</h4><p>{{ selectedPathLabel }}</p><template v-if="selectedLink"><dl><dt>采样时间</dt><dd>{{ selectedLink.timestamp }}</dd><dt>对端射频口</dt><dd>{{ selectedLink.peer_radio || '—' }}</dd><dt>链路状态</dt><dd>{{ selectedLink.link_role }}</dd><dt>RSSI</dt><dd>{{ selectedLink.local_rssi_db ?? '—' }}</dd><dt>Tx / Rx Busy</dt><dd>{{ selectedLink.local_tx_busy ?? '—' }} / {{ selectedLink.local_rx_busy ?? '—' }}</dd></dl></template><el-empty v-else description="点击底部记录查看详情" :image-size="42" /></aside></div>
      <div class="phase11-links"><div class="phase11-panel-heading"><h4>主链路记录</h4><span>{{ linkTotal }} 条</span></div><NcDataTable table-id="mesh-phase11-links:v1" route-key="/rail-transit/mesh-analysis" :data="links" :columns="linkColumns" :loading="mainLoading" :row-class-name="(row: MeshLinkDetail) => row === selectedLink ? 'is-selected' : ''" @row-click="selectLink" empty-text="暂无主链路记录" /></div>
    </div>
  </section>
</template>

<style scoped>
.mesh-phase11{display:flex;min-width:0;flex-direction:column;gap:10px;padding:12px;background:var(--nc-bg-card);border:1px solid var(--nc-border-light);border-radius:8px}.phase11-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.phase11-eyebrow{color:var(--nc-primary);font-size:10px;letter-spacing:.08em}.phase11-head h2{margin:3px 0;font-size:20px}.phase11-head p,.phase11-panel-heading p,.phase11-monitor-toolbar p{margin:0;color:var(--nc-text-secondary);font-size:12px}.phase11-scope{display:flex;flex-wrap:wrap;gap:10px}.phase11-nav{display:flex;gap:2px;border-bottom:1px solid var(--nc-border-light)}.phase11-nav button{padding:8px 14px;color:var(--nc-text-secondary);background:transparent;border:0;border-bottom:2px solid transparent;cursor:pointer}.phase11-nav button.active{color:var(--nc-primary);border-bottom-color:var(--nc-primary)}.phase11-panel{min-width:0;padding-top:10px}.phase11-skeleton{min-height:180px;padding:16px;background:var(--nc-bg-page)}.phase11-cards,.phase11-summary-grid{display:grid;grid-template-columns:repeat(6,minmax(100px,1fr));gap:8px}.phase11-card,.phase11-summary-grid article{padding:12px;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:6px}.phase11-card{color:var(--nc-text-primary);text-align:left;cursor:pointer}.phase11-card:hover{border-color:var(--nc-primary)}.phase11-card span,.phase11-summary-grid span,.phase11-side-summary span{display:block;color:var(--nc-text-secondary);font-size:12px}.phase11-card strong,.phase11-summary-grid strong{display:block;margin-top:8px;font-size:22px}.phase11-summary-grid{grid-template-columns:repeat(6,minmax(110px,1fr));margin-top:10px}.phase11-table{margin-top:14px}.phase11-panel-heading,.phase11-monitor-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px}.phase11-panel-heading h3,.phase11-panel-heading h4,.phase11-monitor-toolbar h3{margin:0 0 4px}.phase11-monitor-body{display:grid;grid-template-columns:160px minmax(0,1fr) 220px;gap:10px;margin-top:10px}.phase11-side-summary,.phase11-detail{padding:12px;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:6px}.phase11-side-summary h4,.phase11-detail h4{margin:0 0 12px}.phase11-side-summary div{padding:10px 0;border-bottom:1px solid var(--nc-border-light)}.phase11-side-summary strong{display:block;margin-top:4px;font-size:18px}.phase11-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.metric-panel{min-width:0;padding:8px 10px;background:var(--nc-bg-page);border:1px solid var(--nc-border-light);border-radius:6px}.metric-panel header{display:flex;align-items:center;justify-content:space-between;gap:8px}.metric-panel header strong{font-size:13px}.metric-panel header span{color:var(--nc-text-secondary);font-size:10px}.phase-completed{color:var(--nc-success)!important}.phase-error{color:var(--nc-danger)!important}.phase-querying,.phase-processing,.phase-rendering{color:var(--nc-primary)!important}.phase11-detail p{color:var(--nc-text-secondary);font-size:12px}.phase11-detail dl{display:grid;grid-template-columns:auto 1fr;gap:8px;font-size:12px}.phase11-detail dt{color:var(--nc-text-secondary)}.phase11-detail dd{margin:0;text-align:right}.phase11-links{margin-top:12px}.phase11-links :deep(.is-selected>td){background:color-mix(in srgb,var(--nc-primary) 12%,var(--nc-bg-card))}@media(max-width:1200px){.phase11-monitor-body{grid-template-columns:140px minmax(0,1fr)}.phase11-detail{grid-column:1/-1}.phase11-cards,.phase11-summary-grid{grid-template-columns:repeat(3,minmax(100px,1fr))}}@media(max-width:800px){.phase11-head{flex-direction:column}.phase11-monitor-body,.phase11-metrics{grid-template-columns:1fr}.phase11-cards,.phase11-summary-grid{grid-template-columns:repeat(2,minmax(100px,1fr))}.phase11-nav{overflow-x:auto}.phase11-nav button{white-space:nowrap}}
</style>
