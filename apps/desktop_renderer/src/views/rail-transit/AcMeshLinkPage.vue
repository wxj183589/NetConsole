<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { FullScreen, Refresh, RefreshRight, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import { useGroundContext } from './useGroundUnattended'
import { t } from '../../i18n/runtime'
import NcDataTable from '../../components/table/NcDataTable.vue'
import AcMeshRssiChart from '../../components/ground-unattended/AcMeshRssiChart.vue'
import { getAcMeshMrDetail, getAcMeshRawTail, getAcMeshSnapshot, listAcMeshPeerAps } from '../../api/acMeshLink'
import type { AcMeshAp, AcMeshLinkRecord, AcMeshLinkSummary, AcMeshMrDetail, AcMeshMrStatus, AcMeshRawTail, AcMeshSnapshot, AcMeshSnapshotDetail } from '../../types/acMeshLink'
import type { VehicleMrController } from '../../types/vehicleMrOnline'
const { acMeshQuery, acMeshTotals, loadAcMesh } = useGroundContext()
const props = defineProps<{ summary: AcMeshLinkSummary | null; links: AcMeshLinkRecord[]; mrs: AcMeshMrStatus[]; snapshots: AcMeshSnapshot[]; rawTail: AcMeshRawTail | null; controllers: VehicleMrController[]; selectedControllerId: string; controllersLoading: boolean; controllersError: boolean; loading: boolean }>()
const emit = defineEmits<{ (event: 'refresh'): void; (event: 'update:selectedControllerId', value: string): void }>()
const view = ref('mr'), collapsed = ref<string[]>([]), detail = ref<AcMeshMrDetail | null>(null), drawer = ref(false), loadingDetail = ref(false), error = ref('')
const aps = ref<AcMeshAp[]>([]), apTotal = ref(0), apPage = ref(1), selectedAp = ref<AcMeshAp | null>(null)
const selectedSnapshot = ref<AcMeshSnapshotDetail | null>(null), snapshotRaw = ref<AcMeshRawTail | null>(null)
const selectedGraphNode = ref('')
const minutes = ref(60), customRange = ref<[string, string] | null>(null), historyPage = ref(1), relationPage = ref(1), peerPage = ref(1)
let request: AbortController | undefined, generation = 0, apRequest: AbortController | undefined
const graphSurface = ref<HTMLElement | null>(null), graphSvg = ref<SVGSVGElement | null>(null)
const graphViewport = ref({ x: 0, y: 0, width: 1000, height: 600 })
const graphFullscreen = ref(false)
let graphInitialWidth = 1000, graphInitialized = false, graphResizeObserver: ResizeObserver | undefined
let graphDrag: { pointerId: number; x: number; y: number; moved: boolean } | undefined
let suppressGraphClick = false, graphClickTimer: ReturnType<typeof setTimeout> | undefined
const groups = computed(() => {
  const values = new Map<string, AcMeshMrStatus[]>()
  for (const mr of props.mrs) { const key = mr.train_no || '—'; values.set(key, [...(values.get(key) || []), mr]) }
  return [...values].sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
})
const peers = (mr: AcMeshMrStatus) => mr.peer_aps || []
const graphRows = computed(() => props.mrs.flatMap(mr => peers(mr).map(peer => ({ mr, peer }))))
const graphPage = computed(() => graphRows.value.slice((relationPage.value - 1) * 40, relationPage.value * 40))
const graph = computed(() => {
  const mrNodes = new Map<string, { id: string; label: string; y: number; mr: AcMeshMrStatus }>()
  const apNodes = new Map<string, { id: string; label: string; y: number; peer: AcMeshLinkRecord }>()
  for (const { mr, peer } of graphPage.value) {
    if (!mrNodes.has(mr.mr_id)) mrNodes.set(mr.mr_id, { id: mr.mr_id, label: mr.mr_name, y: mrNodes.size * 68 + 45, mr })
    const apId = peer.peer_ap_id || peer.peer_ap_mac || peer.bssid || `observation:${peer.id}`
    if (!apNodes.has(apId)) apNodes.set(apId, { id: apId, label: peer.peer_ap_name || peer.bssid || '—', y: apNodes.size * 68 + 45, peer })
  }
  return { mrs: [...mrNodes.values()], aps: [...apNodes.values()],
    edges: graphPage.value.map(({ mr, peer }) => ({ mr, peer, from: mrNodes.get(mr.mr_id)!,
      to: apNodes.get(peer.peer_ap_id || peer.peer_ap_mac || peer.bssid || `observation:${peer.id}`)! })),
    height: Math.max(mrNodes.size, apNodes.size) * 68 + 30 }
})
const graphViewBox = computed(() => {
  const { x, y, width, height } = graphViewport.value
  return `${x} ${y} ${width} ${height}`
})
function graphSize() {
  const rect = graphSvg.value?.getBoundingClientRect()
  return { width: Math.max(rect?.width || 0, 1), height: Math.max(rect?.height || 0, 1) }
}
function fitGraph() {
  if (!graphPage.value.length || !graphSvg.value) return
  const { width, height } = graphSize()
  const viewportWidth = Math.max(1060, (graph.value.height + 60) * width / height)
  const viewportHeight = viewportWidth * height / width
  graphInitialWidth = viewportWidth
  graphViewport.value = { x: 500 - viewportWidth / 2, y: graph.value.height / 2 - viewportHeight / 2,
    width: viewportWidth, height: viewportHeight }
  graphInitialized = true
}
function zoomGraph(factor: number, clientX?: number, clientY?: number) {
  const svg = graphSvg.value
  if (!svg || !graphInitialized) return
  const rect = svg.getBoundingClientRect(), current = graphViewport.value
  const width = Math.min(graphInitialWidth * 6, Math.max(graphInitialWidth / 8, current.width * factor))
  const height = current.height * width / current.width
  const px = clientX === undefined || !rect.width ? 0.5 : Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  const py = clientY === undefined || !rect.height ? 0.5 : Math.min(1, Math.max(0, (clientY - rect.top) / rect.height))
  graphViewport.value = { x: current.x + (current.width - width) * px, y: current.y + (current.height - height) * py, width, height }
}
function wheelGraph(event: WheelEvent) {
  event.preventDefault()
  const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? graphSize().height : 1)
  zoomGraph(Math.exp(Math.max(-800, Math.min(800, pixels)) * 0.0015), event.clientX, event.clientY)
}
function startGraphDrag(event: PointerEvent) {
  if (event.button !== 0) return
  if (graphClickTimer) clearTimeout(graphClickTimer)
  suppressGraphClick = false
  graphDrag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, moved: false }
  graphSvg.value?.setPointerCapture?.(event.pointerId)
}
function moveGraphDrag(event: PointerEvent) {
  if (!graphDrag || event.pointerId !== graphDrag.pointerId) return
  const dx = event.clientX - graphDrag.x, dy = event.clientY - graphDrag.y
  if (!dx && !dy) return
  const { width, height } = graphSize(), current = graphViewport.value
  graphViewport.value = { ...current, x: current.x - dx * current.width / width, y: current.y - dy * current.height / height }
  graphDrag.x = event.clientX; graphDrag.y = event.clientY; graphDrag.moved = true
}
function endGraphDrag(event: PointerEvent) {
  if (!graphDrag || event.pointerId !== graphDrag.pointerId) return
  suppressGraphClick = graphDrag.moved
  if (suppressGraphClick) graphClickTimer = setTimeout(() => { suppressGraphClick = false }, 0)
  graphDrag = undefined
  if (graphSvg.value?.hasPointerCapture?.(event.pointerId)) graphSvg.value.releasePointerCapture(event.pointerId)
}
function graphNodeClick(event: MouseEvent, id: string, open: () => void) {
  if (suppressGraphClick) { suppressGraphClick = false; event.stopPropagation(); return }
  selectedGraphNode.value = id
  open()
}
function openGraphAp(peer: AcMeshLinkRecord) {
  const key = peer.peer_ap_id || peer.peer_ap_mac || peer.bssid || `observation:${peer.id}`
  openAp({ ap_key: key, ap_name: peer.peer_ap_name || peer.bssid || '—', mac: peer.peer_ap_mac || peer.bssid || '',
    bssids: peer.bssid ? [peer.bssid] : [], station: peer.station, section: peer.section,
    relations: graphPage.value.filter(({ peer: item }) =>
      (item.peer_ap_id || item.peer_ap_mac || item.bssid || `observation:${item.id}`) === key).map(({ peer: item }) => item) })
}
function resetGraph() { fitGraph() }
async function toggleGraphFullscreen() {
  if (!graphSurface.value) return
  if (document.fullscreenElement === graphSurface.value) await document.exitFullscreen()
  else await graphSurface.value.requestFullscreen()
}
function syncGraphFullscreen() { graphFullscreen.value = document.fullscreenElement === graphSurface.value }
watch(graphSurface, (surface, previous) => {
  if (previous && graphResizeObserver) graphResizeObserver.unobserve(previous)
  if (!surface) return
  if (typeof ResizeObserver === 'undefined') { void nextTick(() => { if (!graphInitialized) fitGraph() }); return }
  graphResizeObserver ??= new ResizeObserver(() => {
    if (!graphInitialized) { fitGraph(); return }
    const { width, height } = graphSize(), current = graphViewport.value
    const nextHeight = current.width * height / width
    graphViewport.value = { ...current, y: current.y + (current.height - nextHeight) / 2, height: nextHeight }
  })
  graphResizeObserver.observe(surface)
  void nextTick(() => { if (!graphInitialized) fitGraph() })
})
watch(graphPage, () => { if (view.value === 'graph' && !graphInitialized) void nextTick(fitGraph) })
const columns = computed(() => [
  { key: 'peer_ap_name', label: t('ground.acv.peer', '区间 AP'), minWidth: 160 },
  { key: 'bssid', label: 'BSSID', minWidth: 150 }, { key: 'peer_ap_mac', label: 'AP MAC', minWidth: 150 },
  { key: 'rssi', label: 'RSSI', width: 80 }, { key: 'station', label: t('ground.station', '站点'), minWidth: 100 },
  { key: 'section', label: t('ground.section', '区间'), minWidth: 110 }, { key: 'relation_status', label: t('ground.acv.relation_state', '关联状态'), minWidth: 100 },
  { key: 'device_time', label: t('ground.device_time', '设备时间'), minWidth: 180 }, { key: 'received_at', label: t('ground.received_at', '接收时间'), minWidth: 180 },
  { key: 'match_warning', label: t('ground.v2.match_warning', '匹配提示'), minWidth: 180 },
])
const snapshotColumns = computed(() => [{ key: 'id', label: 'ID', width: 80 }, { key: 'device_time', label: t('ground.device_time', '设备时间'), minWidth: 180 }, { key: 'received_at', label: t('ground.received_at', '接收时间'), minWidth: 180 }, { key: 'link_count', label: t('ground.acv.relations', '关联记录'), width: 100 }, { key: 'data_status', label: t('ground.v2.data_state', '数据状态'), width: 100 }, { key: 'parse_status', label: t('ground.v2.parse', '解析'), width: 100 }, { key: 'error_summary', label: t('ground.v2.error', '错误'), minWidth: 200 }])
function stateType(status?: string) { return status === 'fresh' || status === 'current' ? 'success' : status === 'stale' || status === 'recent' ? 'warning' : status === 'error' ? 'danger' : 'info' }
function toggle(train: string) { collapsed.value = collapsed.value.includes(train) ? collapsed.value.filter(item => item !== train) : [...collapsed.value, train] }
async function queryMesh() { acMeshQuery.mrPage = acMeshQuery.page = acMeshQuery.snapshotPage = apPage.value = relationPage.value = 1; await loadAcMesh(false); if (view.value === 'ap') await loadAps() }
async function loadAps() {
  apRequest?.abort(); const controller = new AbortController(); apRequest = controller
  try { const value = await listAcMeshPeerAps({ query: acMeshQuery.query, station: acMeshQuery.station, section: acMeshQuery.section, page: apPage.value, page_size: acMeshQuery.pageSize }, { signal: controller.signal }); if (apRequest === controller && !controller.signal.aborted) { aps.value = value.items; apTotal.value = value.total } }
  catch (cause) { if (!controller.signal.aborted) error.value = String(cause) }
}
async function openMr(mr: AcMeshMrStatus, reset = true) {
  if (reset) { historyPage.value = peerPage.value = 1; detail.value = null }
  drawer.value = true; loadingDetail.value = true; selectedSnapshot.value = null; selectedAp.value = null; error.value = ''
  request?.abort(); request = new AbortController(); const controller = request, current = ++generation
  const end = new Date(), start = new Date(end.getTime() - minutes.value * 60000)
  const format = (value: Date) => new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 19)
  try { const value = await getAcMeshMrDetail(mr.mr_id, { start_time: customRange.value?.[0] || format(start), end_time: customRange.value?.[1] || format(end), page: historyPage.value, page_size: 100 }, { signal: controller.signal }); if (current === generation && drawer.value) detail.value = value }
  catch (cause) { if (!controller.signal.aborted) error.value = String(cause) }
  finally { if (current === generation) loadingDetail.value = false }
}
async function openSnapshot(snapshot: AcMeshSnapshot) {
  request?.abort(); const controller = new AbortController(); request = controller; const current = ++generation
  drawer.value = true; detail.value = null; selectedAp.value = null; selectedSnapshot.value = null; snapshotRaw.value = null; loadingDetail.value = true
  try { const [value, raw] = await Promise.all([getAcMeshSnapshot(snapshot.id, { signal: controller.signal }), getAcMeshRawTail(snapshot.id, 300, { signal: controller.signal })]); if (current === generation) { selectedSnapshot.value = value; snapshotRaw.value = raw } }
  catch (cause) { if (!controller.signal.aborted) error.value = String(cause) }
  finally { if (current === generation) loadingDetail.value = false }
}
function openAp(ap: AcMeshAp) {
  request?.abort(); generation++
  selectedAp.value = ap; detail.value = null; selectedSnapshot.value = null; snapshotRaw.value = null
  peerPage.value = 1; loadingDetail.value = false; error.value = ''; drawer.value = true
}
function closeDrawer() { drawer.value = false; generation++; request?.abort(); detail.value = null; selectedAp.value = null; selectedSnapshot.value = null; loadingDetail.value = false }
watch(view, value => { if (value === 'ap') void loadAps() })
watch(() => props.mrs, () => { if (view.value === 'ap') void loadAps() })
onBeforeUnmount(() => { generation++; request?.abort(); apRequest?.abort(); graphResizeObserver?.disconnect(); if (graphClickTimer) clearTimeout(graphClickTimer); document.removeEventListener('fullscreenchange', syncGraphFullscreen) })
document.addEventListener('fullscreenchange', syncGraphFullscreen)
</script>

<template>
<section class="mesh-page">
  <div class="page-heading"><div><p class="eyebrow">AC / MESH-LINK</p><h2>{{ t('ground.acv.title', '车载 MR 连接监测') }}</h2></div><div class="controller-actions"><el-select :model-value="selectedControllerId" :placeholder="t('ground.v2.select_ac', '选择无线控制器 AC')" @update:model-value="emit('update:selectedControllerId', String($event || ''))"><el-option v-for="item in controllers" :key="item.controller_id" :label="`${item.name} (${item.primary_address})`" :value="item.controller_id" :disabled="!item.connection_ready" /></el-select><el-button type="primary" :icon="Refresh" :loading="loading" :disabled="!controllers.some(item => item.controller_id === selectedControllerId && item.connection_ready)" @click="emit('refresh')">{{ t('ground.v2.refresh_mesh', '刷新 Mesh-Link') }}</el-button></div></div>
  <el-alert v-if="controllersError" :title="t('ground.v2.ac_load_failed', '无线控制器 AC 加载失败，无法刷新 Mesh-Link')" type="error" :closable="false" />
  <el-alert v-else-if="!controllersLoading && !controllers.length" :title="t('ground.v2.no_ac', '未配置无线控制器 AC，无法刷新 Mesh-Link')" type="warning" :closable="false" />
  <el-alert v-else-if="!controllersLoading && controllers.length && !selectedControllerId" :title="t('ground.v2.select_ac_to_refresh', '请选择要刷新的无线控制器 AC')" type="info" :closable="false" />
  <el-alert v-if="summary?.message" :title="summary.message" :type="summary.data_status === 'error' ? 'error' : 'info'" :closable="false" />
  <el-alert v-if="error" :title="error" type="error" closable @close="error = ''" />
  <div class="metric-grid">
    <article><span>{{ t('ground.v2.registered_mr', '注册 MR') }}</span><strong>{{ summary?.registered_mrs ?? 0 }}</strong></article>
    <article><span>{{ t('ground.acv.normal', '正常 MR') }}</span><strong class="good">{{ summary?.online_mrs ?? 0 }}</strong></article>
    <article><span>{{ t('ground.acv.abnormal', '异常 MR') }}</span><strong>{{ summary?.abnormal_mrs ?? 0 }}</strong></article>
    <article><span>{{ t('ground.acv.stale', '过期 MR') }}</span><strong>{{ summary?.stale_mrs ?? 0 }}</strong></article>
    <article><span>{{ t('ground.acv.relations', '关联记录') }}</span><strong>{{ summary?.link_total ?? 0 }}</strong></article>
    <article><span>{{ t('ground.acv.unique_ap', '已确认唯一区间 AP') }}</span><strong>{{ summary?.unique_peer_aps ?? 0 }}</strong></article>
  </div>
  <div class="data-bar"><el-tag :type="stateType(summary?.data_status)">{{ summary?.data_status || 'unknown' }}</el-tag><span>{{ t('ground.device_time', '设备时间') }} {{ summary?.device_time || '—' }}</span><span>{{ t('ground.received_at', '接收时间') }} {{ summary?.received_at || summary?.updated_at || '—' }}</span><span>{{ t('ground.acv.age', '数据年龄') }} {{ summary?.age_seconds ?? '—' }} s</span><small>{{ t('ground.acv.ac_only', 'AC 辅助数据状态独立于 Ping 在线状态') }}</small></div>
  <el-radio-group v-model="view" class="view-tabs"><el-radio-button value="mr">{{ t('ground.acv.mr_view', '车载 MR 视图') }}</el-radio-button><el-radio-button value="ap">{{ t('ground.acv.ap_view', '区间 AP 视图') }}</el-radio-button><el-radio-button value="graph">{{ t('ground.acv.graph_view', '连接关系图') }}</el-radio-button><el-radio-button value="snapshots">{{ t('ground.acv.snapshots', '数据快照') }}</el-radio-button></el-radio-group>
  <div class="mesh-filters"><el-input v-model="acMeshQuery.query" clearable :placeholder="t('ground.acv.search', '列车 / MR / UUID / IP / AP / BSSID')" @keyup.enter="queryMesh" /><el-input v-model="acMeshQuery.station" clearable :placeholder="t('ground.station', '站点')" /><el-input v-model="acMeshQuery.section" clearable :placeholder="t('ground.section', '区间')" /><template v-if="view === 'mr' || view === 'graph'"><el-select v-model="acMeshQuery.carEnd" clearable :placeholder="t('ground.acv.role', '端位')"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select><el-select v-model="acMeshQuery.dataStatus" clearable :placeholder="t('ground.v2.data_state', '数据状态')"><el-option v-for="state in ['fresh', 'recent', 'stale', 'unknown', 'error', 'no_data']" :key="state" :label="state" :value="state" /></el-select><el-select v-model="acMeshQuery.matchStatus" clearable :placeholder="t('ground.acv.match', '匹配状态')"><el-option :label="t('ground.acv.matched', '已匹配')" value="matched" /><el-option :label="t('ground.v2.unmatched', '未匹配')" value="unmatched" /><el-option :label="t('ground.acv.conflict', '匹配冲突')" value="conflict" /></el-select><el-checkbox v-model="acMeshQuery.multiplePeers">{{ t('ground.acv.multi', '多个区间 AP') }}</el-checkbox><el-checkbox v-model="acMeshQuery.abnormalOnly">{{ t('ground.acv.only_abnormal', '仅异常') }}</el-checkbox></template><el-button type="primary" @click="queryMesh">{{ t('common.query', '查询') }}</el-button></div>
  <template v-if="view === 'mr'">
    <el-empty v-if="!mrs.length" :description="t('ground.acv.empty', '暂无 MR 数据')" />
    <section v-for="[train, rows] in groups" :key="train" class="train-group"><button class="train-heading" @click="toggle(train)">{{ collapsed.includes(train) ? '▸' : '▾' }} {{ t('ground.train', '列车') }} {{ train }} <span>{{ rows.length }} MR</span></button><div v-if="!collapsed.includes(train)" class="mr-rows"><article v-for="mr in rows" :key="mr.mr_id" class="mr-row" @click="openMr(mr)"><div class="mr-identity"><el-tag :type="mr.car_end === 'CT' ? 'primary' : 'warning'">{{ mr.car_end || 'MR' }}</el-tag><strong>{{ mr.mr_name }}</strong><small>{{ mr.resolved_ap || '—' }}</small></div><div><el-tag size="small" :type="stateType(mr.data_status)">{{ mr.data_status }}</el-tag><small>{{ mr.identity_status || 'unresolved' }}</small></div><div class="management"><strong>{{ mr.management_ip || '—' }}</strong><small>{{ (mr.management_ips || []).slice(1).join(' / ') }}</small></div><div class="peer-list"><span class="peer-count">{{ t('ground.acv.peer', '区间 AP') }} · {{ peers(mr).length }}</span><el-tag v-for="peer in peers(mr).slice(0, 2)" :key="peer.id" :type="stateType(peer.relation_status)" size="small">{{ peer.peer_ap_name || peer.bssid || '—' }} · {{ peer.rssi ?? '—' }}</el-tag><el-button v-if="peers(mr).length > 2" link type="primary" @click.stop="openMr(mr)">+{{ peers(mr).length - 2 }}</el-button><small v-if="!peers(mr).length">{{ t('ground.acv.no_peers', '暂无关联数据') }}</small></div><div><span>{{ mr.resolved_ap_station || mr.resolved_ap_section || '' }}</span><small>{{ mr.device_time || mr.last_seen_at || '—' }}</small></div><el-button link type="primary" @click.stop="openMr(mr)">{{ t('common.details', '详情') }}</el-button></article></div></section>
    <el-pagination v-model:current-page="acMeshQuery.mrPage" :page-size="acMeshQuery.pageSize" :total="acMeshTotals.mrs" layout="total, prev, pager, next" @current-change="loadAcMesh(false)" />
  </template>
  <template v-else-if="view === 'ap'"><el-empty v-if="!aps.length" :description="t('ground.acv.no_peers', '暂无关联数据')" /><article v-for="ap in aps" :key="ap.ap_key" class="ap-card" @click="openAp(ap)"><div><strong>{{ ap.ap_name || ap.mac || ap.ap_key }}</strong><small>{{ ap.mac }} · {{ ap.station || ap.section }}</small></div><el-tag>{{ new Set(ap.relations.map(link => link.mr_id)).size }} MR</el-tag><div class="peer-list"><el-tag v-for="relation in ap.relations.slice(0, 3)" :key="relation.id" :type="stateType(relation.relation_status)">{{ relation.mr_name }} · {{ relation.rssi ?? '—' }}</el-tag><span v-if="ap.relations.length > 3">+{{ ap.relations.length - 3 }}</span></div></article><el-pagination v-model:current-page="apPage" :page-size="acMeshQuery.pageSize" :total="apTotal" layout="total, prev, pager, next" @current-change="loadAps" /></template>
  <template v-else-if="view === 'graph'">
    <p class="muted">{{ t('ground.acv.graph_note', '显示当前筛选页的全部关联；虚线表示过期、断开或未知。点击 MR、AP 或连线查看详情。') }}</p>
    <el-empty v-if="!graphPage.length" :description="t('ground.acv.no_peers', '暂无关联数据')" />
    <div v-else ref="graphSurface" class="graph-surface">
      <div class="graph-toolbar">
        <span>{{ t('ground.acv.graph_view', '连接关系图') }} · {{ graph.mrs.length }} MR / {{ graph.aps.length }} AP</span>
        <div class="graph-tools">
          <el-button :icon="ZoomOut" title="缩小" aria-label="缩小" @click="zoomGraph(1.2)" />
          <el-button :icon="ZoomIn" title="放大" aria-label="放大" @click="zoomGraph(1 / 1.2)" />
          <el-button title="适应画布" @click="fitGraph">适应画布</el-button>
          <el-button :icon="RefreshRight" title="重置视图" aria-label="重置视图" @click="resetGraph" />
          <el-button :icon="FullScreen" :title="graphFullscreen ? '退出全屏' : '全屏'" :aria-label="graphFullscreen ? '退出全屏' : '全屏'" @click="toggleGraphFullscreen" />
        </div>
      </div>
      <svg ref="graphSvg" class="relation-graph" role="img" :aria-label="t('ground.acv.graph_view', '连接关系图')"
        :viewBox="graphViewBox" preserveAspectRatio="none" @wheel="wheelGraph"
        @pointerdown="startGraphDrag" @pointermove="moveGraphDrag" @pointerup="endGraphDrag" @pointercancel="endGraphDrag">
        <g v-for="edge in graph.edges" :key="edge.peer.id">
          <path :d="`M 270 ${edge.from.y} C 430 ${edge.from.y}, 570 ${edge.to.y}, 730 ${edge.to.y}`"
            :class="['relation-edge', { uncertain: edge.peer.relation_status !== 'current' }]"
            @click="graphNodeClick($event, `edge:${edge.peer.id}`, () => openMr(edge.mr))" />
        </g>
        <g v-for="node in graph.mrs" :key="node.id" :class="['graph-mr-node', { 'graph-selected': selectedGraphNode === `mr:${node.id}` }]"
          @click="graphNodeClick($event, `mr:${node.id}`, () => openMr(node.mr))">
          <title>{{ node.label }} · {{ node.mr.management_ip || node.id }}</title>
          <rect x="10" :y="node.y-25" width="260" height="50" rx="5" />
          <text x="22" :y="node.y-3">{{ node.label }}</text>
          <text class="graph-node-secondary" x="22" :y="node.y+15">{{ node.mr.management_ip || node.id }}</text>
        </g>
        <g v-for="node in graph.aps" :key="node.id" :class="['graph-ap-node', { 'graph-selected': selectedGraphNode === `ap:${node.id}` }]"
          @click="graphNodeClick($event, `ap:${node.id}`, () => openGraphAp(node.peer))">
          <title>{{ node.label }} · {{ node.peer.peer_ap_mac || node.peer.bssid || node.id }}</title>
          <rect x="730" :y="node.y-25" width="260" height="50" rx="5" />
          <text x="744" :y="node.y-3">{{ node.label }}</text>
          <text class="graph-node-secondary" x="744" :y="node.y+15">{{ node.peer.peer_ap_mac || node.peer.bssid || node.id }}</text>
        </g>
      </svg>
    </div>
    <div class="graph-observations"><button v-for="edge in graph.edges" :key="edge.peer.id" @click="openMr(edge.mr)">{{ edge.mr.mr_name }} → {{ edge.peer.peer_ap_name || edge.peer.bssid }} · RSSI {{ edge.peer.rssi ?? '—' }} · {{ edge.peer.device_time }}</button></div>
    <el-pagination v-model:current-page="relationPage" :page-size="40" :total="graphRows.length" layout="total, prev, pager, next" />
    <el-pagination v-model:current-page="acMeshQuery.mrPage" :page-size="acMeshQuery.pageSize" :total="acMeshTotals.mrs" layout="total, prev, pager, next" @current-change="loadAcMesh(false)" />
  </template>
  <template v-else><NcDataTable table-id="ground-ac-snapshots" route-key="ground-ac" :data="snapshots" :columns="snapshotColumns" row-key="id" compact @row-click="openSnapshot" /><el-pagination v-model:current-page="acMeshQuery.snapshotPage" :page-size="acMeshQuery.pageSize" :total="acMeshTotals.snapshots" layout="total, prev, pager, next" @current-change="loadAcMesh(false)" /><pre v-if="rawTail?.available" class="raw-tail">{{ rawTail.lines.join('\n') }}</pre></template>
  <el-drawer :model-value="drawer" :title="detail?.mr.mr_name || selectedAp?.ap_name || t('ground.acv.details', 'MR / AP 关联详情')" size="min(900px, 100vw)" destroy-on-close @close="closeDrawer"><div v-loading="loadingDetail" class="drawer-content"><template v-if="detail"><div class="detail-identity"><el-tag>{{ detail.mr.car_end || 'MR' }}</el-tag><strong>{{ detail.mr.mr_name }}</strong><code>{{ detail.mr.mr_id }}</code><p>{{ (detail.mr.management_ips || [detail.mr.management_ip]).join(' / ') }}</p><p>{{ t('ground.acv.resolved_ap', '解析后 AP') }}：{{ detail.mr.resolved_ap || '—' }} · {{ detail.mr.identity_status }}</p><p>{{ detail.mr.resolved_ap_station || detail.mr.resolved_ap_section || '' }}</p><el-tag :type="stateType(detail.mr.data_status)">{{ detail.mr.data_status }}</el-tag></div><h3>{{ t('ground.acv.current_peers', '当前快照关联') }} ({{ detail.current_links.length }})</h3><NcDataTable table-id="ground-ac-current-peers" route-key="ground-ac" :data="detail.current_links.slice((peerPage-1)*20, peerPage*20)" :columns="columns" row-key="id" compact /><el-pagination v-model:current-page="peerPage" :page-size="20" :total="detail.current_links.length" layout="total, prev, pager, next" /><h3>{{ t('ground.acv.rssi', 'RSSI 观测趋势') }}</h3><div class="mesh-filters"><el-select v-model="minutes" @change="customRange = null; historyPage = 1; openMr(detail.mr, false)"><el-option v-for="count in [10, 30, 60]" :key="count" :value="count" :label="`${count} min`" /></el-select><el-date-picker v-model="customRange" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss" @change="historyPage = 1; openMr(detail.mr, false)" /></div><AcMeshRssiChart v-if="detail.history_links.length" :rows="detail.history_links" :active="drawer" /><el-empty v-else :description="t('ground.acv.no_history', '所选时间内没有历史观测')" /><p class="muted">{{ detail.history_note }} {{ t('ground.acv.paged_history', '图表仅展示当前历史页的实际观测，切页查看其余记录。') }}</p><h3>{{ t('ground.acv.history', '历史关联观测') }}</h3><NcDataTable table-id="ground-ac-history-peers" route-key="ground-ac" :data="detail.history_links" :columns="columns" row-key="id" compact /><el-pagination v-model:current-page="historyPage" :page-size="100" :total="detail.history_total" layout="total, prev, pager, next" @current-change="openMr(detail.mr, false)" /><h3>{{ t('ground.acv.events', '已有事件记录') }}</h3><pre class="raw-tail">{{ JSON.stringify(detail.recent_events, null, 2) }}</pre><h3>{{ t('ground.acv.raw', '快照与解析结果') }}</h3><el-button v-for="id in [...new Set(detail.current_links.map(link => link.snapshot_id))]" :key="id" @click="openSnapshot({ id } as AcMeshSnapshot)">{{ t('ground.acv.snapshots', '数据快照') }} #{{ id }}</el-button></template><template v-if="selectedAp"><h3>{{ selectedAp.ap_name }}</h3><p>{{ selectedAp.mac }} · {{ selectedAp.station || selectedAp.section }}</p><NcDataTable table-id="ground-ac-reverse-peers" route-key="ground-ac" :data="selectedAp.relations.slice((peerPage-1)*20, peerPage*20)" :columns="[{ key: 'mr_name', label: 'MR', minWidth: 160 }, ...columns]" row-key="id" compact /><el-pagination v-model:current-page="peerPage" :page-size="20" :total="selectedAp.relations.length" layout="total, prev, pager, next" /></template><template v-if="selectedSnapshot"><h3>{{ t('ground.acv.snapshots', '数据快照') }} #{{ selectedSnapshot.snapshot.id }}</h3><pre class="raw-tail">{{ JSON.stringify(selectedSnapshot.snapshot, null, 2) }}</pre><NcDataTable table-id="ground-ac-snapshot-peers" route-key="ground-ac" :data="selectedSnapshot.links" :columns="[{ key: 'mr_name', label: 'MR', minWidth: 160 }, ...columns]" row-key="id" compact /><pre v-if="snapshotRaw?.available" class="raw-tail">{{ snapshotRaw.lines.join('\n') }}</pre><el-empty v-else :description="snapshotRaw?.message || t('ground.v2.ac_no_raw_tail', '暂无原始尾部')" /></template></div></el-drawer>
</section>
</template>
<style scoped>
.mesh-page{display:flex;flex-direction:column;gap:14px;min-width:0}.page-heading,.controller-actions,.data-bar,.mesh-filters{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.page-heading{justify-content:space-between}.page-heading h2{margin:3px 0}.eyebrow{margin:0;color:var(--el-color-primary);font-size:12px;font-weight:700}.controller-actions .el-select{width:270px}.metric-grid{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:12px}.metric-grid article{border:1px solid var(--el-border-color-lighter);border-radius:8px;padding:14px;background:var(--el-bg-color)}.metric-grid strong{display:block;font-size:25px;margin-top:8px}.metric-grid span,.muted,.data-bar{font-size:12px;color:var(--el-text-color-secondary)}.good{color:var(--el-color-success)}.data-bar{padding:10px;background:var(--el-fill-color-light);border-radius:6px}.mesh-filters .el-input{width:180px}.mesh-filters .el-input:first-child{width:300px}.mesh-filters .el-select{width:130px}.train-group{border:1px solid var(--el-border-color-lighter);border-radius:8px;overflow:hidden}.train-heading{width:100%;border:0;padding:10px 14px;text-align:left;background:var(--el-fill-color-light);color:var(--el-text-color-primary);font-weight:600;cursor:pointer}.train-heading span{margin-left:12px;color:var(--el-text-color-secondary)}.mr-row{display:grid;grid-template-columns:minmax(165px,1.1fr) 95px 150px minmax(230px,2fr) minmax(130px,1fr) 45px;gap:14px;align-items:center;padding:14px;cursor:pointer;background:var(--el-bg-color)}.mr-row+.mr-row{border-top:1px solid var(--el-border-color-lighter)}.mr-row:hover{background:var(--el-fill-color-light)}.mr-identity{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.mr-identity small{flex-basis:100%;padding-left:44px}.mr-row small,.ap-card small{display:block;font-size:12px;color:var(--el-text-color-secondary);margin-top:5px;overflow-wrap:anywhere}.peer-list{display:flex;gap:6px;align-items:center;flex-wrap:wrap;min-width:0}.peer-list .el-tag{max-width:100%;height:auto;white-space:normal}.peer-count{font-size:12px;flex-basis:100%;color:var(--el-text-color-secondary)}.management{font-size:13px}.ap-card{display:flex;gap:20px;align-items:center;padding:16px;border:1px solid var(--el-border-color-lighter);border-radius:8px;cursor:pointer}.relation-graph{width:100%;max-height:650px;overflow:auto;font-size:12px}.relation-graph rect{fill:var(--el-fill-color-light);stroke:var(--el-border-color);cursor:pointer}.relation-graph text{fill:var(--el-text-color-primary);cursor:pointer}.relation-edge{fill:none;stroke:var(--el-color-primary);stroke-width:3;cursor:pointer}.relation-edge.uncertain{stroke:var(--el-text-color-placeholder);stroke-dasharray:7 5}.drawer-content{min-height:180px}.detail-identity{padding:14px;border-radius:8px;background:var(--el-fill-color-light)}.detail-identity strong{margin:0 10px}.detail-identity code{display:block;margin-top:10px;overflow-wrap:anywhere}.raw-tail{max-height:300px;overflow:auto;background:var(--el-fill-color-light);padding:12px;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}:deep(.el-drawer__body){overflow:auto}:deep(.el-pagination){flex-wrap:wrap;margin-top:6px}@media(max-width:1200px){.metric-grid{grid-template-columns:repeat(3,1fr)}.mr-row{grid-template-columns:170px 90px 140px 1fr}.mr-row>div:nth-last-child(2){grid-column:1/4}.mr-row>.el-button{justify-self:end}}@media(max-width:650px){.metric-grid{grid-template-columns:repeat(2,1fr)}.mr-row{grid-template-columns:1fr 1fr}.mr-row>div:nth-last-child(2){grid-column:auto}.controller-actions .el-select,.mesh-filters .el-input:first-child{width:100%}.ap-card{flex-wrap:wrap}}
.graph-surface{display:flex;flex-direction:column;width:100%;height:65vh;min-height:460px;max-height:850px;min-width:0;overflow:hidden;border:1px solid var(--el-border-color);border-radius:6px;background:var(--el-bg-color)}.graph-surface:fullscreen{height:100vh;border:0;border-radius:0}.graph-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:50px;padding:6px 12px;border-bottom:1px solid var(--el-border-color);font-size:12px;color:var(--el-text-color-secondary)}.graph-tools{display:flex;align-items:center;flex-wrap:wrap;gap:4px}.graph-tools :deep(.el-button+.el-button){margin-left:0}.relation-graph{width:100%;height:100%;min-height:0;max-height:none;overflow:hidden;cursor:grab;touch-action:none;user-select:none}.relation-graph:active{cursor:grabbing}.relation-graph .graph-selected rect{fill:var(--el-color-primary-light-9);stroke:var(--el-color-primary);stroke-width:2}.relation-graph .graph-node-secondary{font-size:10px;fill:var(--el-text-color-secondary)}.graph-observations{display:flex;gap:6px;flex-wrap:wrap;padding:8px 0}.graph-observations button{border:1px solid var(--el-border-color);border-radius:4px;background:var(--el-bg-color);color:var(--el-text-color-regular);padding:5px 8px;cursor:pointer;font-size:12px}.graph-observations button:hover{color:var(--el-color-primary)}@media(max-width:650px){.graph-toolbar{align-items:flex-start;flex-direction:column}.graph-surface{height:65vh;min-height:420px;max-height:700px}}
</style>
