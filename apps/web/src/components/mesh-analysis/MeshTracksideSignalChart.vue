<script setup lang="ts">
import { markRaw, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import {
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import {
  createMultiSeriesTimeChartBaseOption,
  createTimeChartInitOptions,
  createTimeChartLinePresentation,
  isLargeTimeChart,
} from '../charts/multiSeriesTimeChart'
import type {
  MeshChartEvent,
  MeshLocationSegment,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import TracksideExternalTooltip from './TracksideExternalTooltip.vue'
import TracksideFrameDetailPanel from './TracksideFrameDetailPanel.vue'
import { buildMeshLocationBands } from './chartSeries'
import {
  createFullMeshViewport,
  createFullMeshViewportFromDomain,
  formatMeshViewportTimestamp,
  meshDataZoomRequiresCorrection,
  meshTimestampMillis,
  meshViewportRangeEquals,
  normalizeMeshViewport,
  viewportFromDataZoomWithOptions,
  type MeshChartViewport,
  type MeshRssiChartSource,
  type MeshSharedPointerChange,
  type MeshSharedTimeDomain,
} from './meshChartViewport'
import {
  buildTracksideSeriesCache,
  disposeTracksideSeriesCache,
  findTracksideFrameMetaIds,
  resolveTracksideTooltipFrame,
  tracksidePointMeta,
  tracksideViewportSeriesItems,
  type CompactTracksideChartPoint,
  type CompactTracksidePointMeta,
  type CompactTracksideSeriesMeta,
  type TracksideSeriesCache,
  type TracksideViewportSeriesItem,
} from './tracksideSeriesCache'
import {
  assignTracksideSeriesColors,
  createTracksideSeriesPalette,
  disposeTracksideSeriesColorAssignment,
  type TracksideSeriesColorAssignment,
} from './tracksideSeriesColors'
import {
  type PinnedTracksideFrame,
  type TracksideTooltipEntry,
} from './tracksideTooltip'

const props = withDefaults(defineProps<{
  series?: MeshTracksideSignalSeriesData[]
  seriesCache?: TracksideSeriesCache | null
  events?: MeshChartEvent[]
  locationSegments?: MeshLocationSegment[]
  showSwitchLines?: boolean
  showSwitchPoints?: boolean
  showLocationBand?: boolean
  active?: boolean
  workspaceVisible?: boolean
  initialViewport?: MeshChartViewport | null
  syncViewport?: MeshChartViewport | null
  lockedViewport?: MeshChartViewport | null
  continuityGapSeconds?: number | null
  preserveViewport?: boolean
  sharedTimeDomain?: MeshSharedTimeDomain | null
  chartId?: Exclude<MeshRssiChartSource, 'active-rssi' | 'programmatic'>
  syncPointerTime?: string | null
  syncPointerSource?: MeshRssiChartSource | null
}>(), {
  series: () => [],
  seriesCache: null,
  events: () => [],
  locationSegments: () => [],
  showSwitchLines: false,
  showSwitchPoints: false,
  showLocationBand: true,
  active: true,
  workspaceVisible: true,
  initialViewport: null,
  syncViewport: null,
  lockedViewport: null,
  continuityGapSeconds: null,
  preserveViewport: true,
  sharedTimeDomain: null,
  chartId: 'trackside-rssi',
  syncPointerTime: null,
  syncPointerSource: null,
})
const emit = defineEmits<{
  selectSwitch: [event: MeshChartEvent]
  'viewport-change': [viewport: MeshChartViewport]
  'viewport-ready': [viewport: MeshChartViewport]
  'pointer-change': [pointer: MeshSharedPointerChange]
  'viewport-interaction-start': []
  'viewport-interaction-end': []
  'workload-phase': [phase: 'echarts-init' | 'echarts-set-option' | 'echarts-interactive' | 'chart-disposed']
  'workload-profile': [profile: { conflictEdgeCount: number }]
}>()

const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let initialization: Promise<boolean> | null = null
let resizeFrame: number | null = null
let pendingRenderReason: 'data' | 'display' | 'theme' | 'reset' | null = null
let disposed = false
let currentViewport: MeshChartViewport | null = null
let appliedViewport: MeshChartViewport | null = null
let chartRenderEpoch = 0
let appliedViewportEpoch = -1
let viewportReady = false
let viewportFrame: number | null = null
let pendingViewport: MeshChartViewport | null = null
let pointerGlobalOut: (() => void) | null = null
let zrenderBlankClick: ((event: { target?: unknown }) => void) | null = null
let interactiveTimer: ReturnType<typeof setTimeout> | null = null
let viewportListTimer: ReturnType<typeof setTimeout> | null = null
let tooltipHideTimer: ReturnType<typeof setTimeout> | null = null
let tooltipPointerInside = false
let pointerOrigin: TracksidePointerOrigin = 'none'
let localPointerSide: TracksideTooltipState['side'] = 'right'
let seriesCache: TracksideSeriesCache = markRaw(props.seriesCache ?? buildTracksideSeriesCache(props.series))
let seriesColors: TracksideSeriesColorAssignment = buildSeriesColors(seriesCache)
const reportedPhases = new Set<string>()
const viewportSeries = ref<TracksideViewportListItem[]>([])
const rangePanelOpen = ref(false)
const selectedTracksideAp = ref<SelectedTracksideAp | null>(null)
const selectedOutsideRange = ref(false)
const pinnedTracksideFrame = shallowRef<PinnedTracksideFrame | null>(null)
const pinnedOutsideRange = ref(false)
const tooltipAvailableHeight = ref(640)
const tracksideTooltip = shallowRef<TracksideTooltipState>({
  visible: false,
  timestamp: null,
  timestampMillis: null,
  entries: [],
  side: 'right',
  source: 'none',
})
let lastViewportListComputeMs = 0
let lastSelectionStyleUpdateMs = 0

function invalidateAppliedViewport(): void {
  chartRenderEpoch += 1
  appliedViewport = null
  appliedViewportEpoch = -1
}

function markViewportApplied(viewport: MeshChartViewport): void {
  appliedViewport = { ...viewport }
  appliedViewportEpoch = chartRenderEpoch
}

interface SelectedTracksideAp {
  seriesId: string
  metaId: number
  timestampMillis: number
  apName: string | null
  apMac: string | null
  radio: number | null
  rssi: number | null
}

interface TracksideViewportListItem extends TracksideViewportSeriesItem {
  color: string
}

interface TracksideTooltipState {
  visible: boolean
  timestamp: string | null
  timestampMillis: number | null
  entries: TracksideTooltipEntry[]
  side: 'left' | 'right'
  source: TracksidePointerOrigin
}

type TracksidePointerOrigin = 'local' | 'shared' | 'none'

const timestamps = (): string[] => [
  seriesCache.firstTimestampMillis,
  seriesCache.lastTimestampMillis,
].filter((value): value is number => value !== null).map(formatMeshViewportTimestamp)
const hasData = () => seriesCache.series.some((item) => item.data.some((point) => point[1] != null))
const fullViewport = (source: MeshChartViewport['source'] = 'initial'): MeshChartViewport | null => (
  props.sharedTimeDomain
    ? createFullMeshViewportFromDomain(props.sharedTimeDomain, source, props.chartId, currentViewport?.revision ?? 0)
    : createFullMeshViewport(timestamps(), source)
)

function hasRenderableSize(): boolean {
  return Boolean(container.value && container.value.clientWidth > 0 && container.value.clientHeight > 0)
}

function pointLabel(point: CompactTracksidePointMeta): string {
  return point.peerApName || point.peerMac || '轨旁 AP 未知'
}

function buildSeriesColors(
  cache: TracksideSeriesCache,
  theme = readNetConsoleChartTokens(),
): TracksideSeriesColorAssignment {
  return markRaw(assignTracksideSeriesColors(
    cache,
    createTracksideSeriesPalette(
      [theme.primary, theme.series[1] || ''],
      [theme.warning, theme.danger],
      Math.max(32, cache.series.length),
    ),
  ))
}

function seriesColor(seriesId: string, fallback: string): string {
  return seriesColors.colorBySeriesId.get(seriesId) || fallback
}

function handleLocalPointerMove(event: PointerEvent): void {
  if (!props.active) return
  pointerOrigin = 'local'
  cancelTooltipHide()
  const bounds = container.value?.getBoundingClientRect()
  const pointerX = bounds ? event.clientX - bounds.left : event.offsetX
  if (!Number.isFinite(pointerX)) return
  localPointerSide = pointerX < (container.value?.clientWidth || 0) / 2 ? 'right' : 'left'
}

function rebuildSeriesColors(theme = readNetConsoleChartTokens()): void {
  disposeTracksideSeriesColorAssignment(seriesColors)
  seriesColors = buildSeriesColors(seriesCache, theme)
  emit('workload-profile', { conflictEdgeCount: seriesColors.conflictEdgeCount })
}

function tooltipFrameTimestamp(pointerMillis: number): number | null {
  return resolveTracksideTooltipFrame(seriesCache, pointerMillis)
}

function compactMac(value: string | null | undefined): string {
  const source = String(value || '').trim()
  const normalized = source.toLowerCase().replace(/[^0-9a-f]/g, '')
  return normalized.length === 12 ? normalized : source || '—'
}

function apDisplayName(value: { apName: string | null; apMac: string | null }): string {
  const name = String(value.apName || '').trim()
  const normalizedName = name.toLowerCase().replace(/[^0-9a-f]/g, '')
  if (name && normalizedName.length !== 12) return name
  const mac = compactMac(value.apMac || name)
  return /^[0-9a-f]{12}$/.test(mac)
    ? `${mac.slice(0, 4)}-${mac.slice(4, 8)}-${mac.slice(8)}`
    : mac === '—' ? '轨旁 AP 未知' : mac
}

function displayRssi(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : String(value)
}

function reportInteractionProfile(): void {
  if (!import.meta.env.DEV) return
  console.debug('trackside interaction profile', {
    totalSeries: seriesCache.series.length,
    visibleSeriesInViewport: viewportSeries.value.length,
    legendEnabled: false,
    selectedSeriesId: selectedTracksideAp.value?.seriesId || null,
    viewportListComputeMs: Number(lastViewportListComputeMs.toFixed(3)),
    selectionStyleUpdateMs: Number(lastSelectionStyleUpdateMs.toFixed(3)),
  })
}

function recordSelectionUpdate(): void {
  const started = performance.now()
  lastSelectionStyleUpdateMs = performance.now() - started
  if (rangePanelOpen.value) reportInteractionProfile()
}

function selectedSeriesColor(): string {
  const series = seriesCache.seriesMetaById.get(selectedTracksideAp.value?.seriesId || '')
  const theme = readNetConsoleChartTokens()
  return series
    ? seriesColor(series.seriesId, theme.textSecondary)
    : theme.textSecondary
}

function currentViewportBounds(): [number, number] | null {
  const viewport = currentViewport || props.syncViewport || props.initialViewport || fullViewport()
  const start = meshTimestampMillis(viewport?.start_time)
  const end = meshTimestampMillis(viewport?.end_time)
  return start === null || end === null ? null : [start, end]
}

function updateSelectedRangeStatus(): void {
  const selected = selectedTracksideAp.value
  const bounds = currentViewportBounds()
  selectedOutsideRange.value = Boolean(
    selected
    && bounds
    && (selected.timestampMillis < bounds[0] || selected.timestampMillis > bounds[1]),
  )
  pinnedOutsideRange.value = Boolean(
    pinnedTracksideFrame.value
    && bounds
    && (
      pinnedTracksideFrame.value.timestampMillis < bounds[0]
      || pinnedTracksideFrame.value.timestampMillis > bounds[1]
    ),
  )
}

function recomputeViewportSeries(): void {
  if (disposed || seriesCache.disposed) return
  const bounds = currentViewportBounds()
  if (!bounds) {
    viewportSeries.value = []
    return
  }
  const started = performance.now()
  const theme = readNetConsoleChartTokens()
  viewportSeries.value = tracksideViewportSeriesItems(
    seriesCache,
    bounds[0],
    bounds[1],
    null,
  ).map((item) => {
    return {
      ...item,
      color: seriesColor(item.seriesId, theme.textSecondary),
    }
  })
  lastViewportListComputeMs = performance.now() - started
  updateSelectedRangeStatus()
  if (rangePanelOpen.value) reportInteractionProfile()
}

function scheduleViewportSeriesUpdate(): void {
  if (viewportListTimer) clearTimeout(viewportListTimer)
  viewportListTimer = setTimeout(() => {
    viewportListTimer = null
    recomputeViewportSeries()
  }, 75)
}

function clearTracksideSelection(updateChart = true): void {
  if (!selectedTracksideAp.value) return
  selectedTracksideAp.value = null
  selectedOutsideRange.value = false
  if (updateChart) recordSelectionUpdate()
}

function selectTracksidePoint(
  point: CompactTracksidePointMeta,
  series: CompactTracksideSeriesMeta,
  toggleExactPoint = true,
): void {
  if (
    toggleExactPoint
    && selectedTracksideAp.value?.seriesId === series.seriesId
    && selectedTracksideAp.value.metaId === point.metaId
  ) {
    clearTracksideSelection()
    return
  }
  selectedTracksideAp.value = {
    seriesId: series.seriesId,
    metaId: point.metaId,
    timestampMillis: point.timestampMillis,
    apName: point.peerApName || series.peerName,
    apMac: point.peerApMac || series.apMac,
    radio: point.localRadio ?? series.radio,
    rssi: point.rssi,
  }
  updateSelectedRangeStatus()
  recordSelectionUpdate()
}

function selectViewportSeries(item: TracksideViewportListItem): void {
  const point = tracksidePointMeta(seriesCache, item.metaId)
  const series = seriesCache.seriesMetaById.get(item.seriesId)
  if (point && series) selectTracksidePoint(point, series, false)
}

function handleRangePanelToggle(event: Event): void {
  rangePanelOpen.value = Boolean((event.currentTarget as HTMLDetailsElement | null)?.open)
  if (rangePanelOpen.value) recomputeViewportSeries()
}

function handleSelectionEscape(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !props.active) return
  const handled = Boolean(pinnedTracksideFrame.value)
    || tracksideTooltip.value.visible
    || Boolean(selectedTracksideAp.value)
  if (!handled) return
  event.preventDefault()
  event.stopPropagation()
  if (pinnedTracksideFrame.value) {
    closePinnedTracksideFrame()
    return
  }
  pointerOrigin = 'none'
  tooltipPointerInside = false
  hideTracksideTooltip()
  if (selectedTracksideAp.value) clearTracksideSelection()
}

function rebuildSeriesCache(): void {
  const next = props.seriesCache ?? buildTracksideSeriesCache(props.series)
  if (next !== seriesCache) {
    pointerOrigin = 'none'
    tooltipPointerInside = false
    hideTracksideTooltip()
    closePinnedTracksideFrame()
    clearTracksideSelection(false)
    disposeTracksideSeriesCache(seriesCache)
    seriesCache = markRaw(next)
    rebuildSeriesColors()
  }
  if (import.meta.env.DEV && seriesCache.unorderedSeriesIds.length) {
    console.warn(`轨旁信号 payload 存在未按时间排序的序列：${seriesCache.unorderedSeriesIds.join(', ')}`)
  }
  recomputeViewportSeries()
}

interface ResolvedTracksidePoint {
  data: CompactTracksideChartPoint
  meta: CompactTracksidePointMeta
  series: CompactTracksideSeriesMeta
}

interface ResolvedSwitchEvent {
  event: MeshChartEvent
  eventIndex: number
  timestamp: string
  timestampMillis: number
}

function resolvedPoint(metaId: number): ResolvedTracksidePoint | undefined {
  const meta = tracksidePointMeta(seriesCache, metaId)
  const series = meta ? seriesCache.seriesMetaById.get(meta.seriesId) : undefined
  if (!meta || !series) return undefined
  return {
    data: [meta.timestampMillis, meta.rssi, meta.metaId, meta.role === 'ACTIVE' ? 0 : 1],
    meta,
    series,
  }
}

function normalizedIdentity(value: string | null | undefined): string {
  return String(value || '').trim().toLocaleLowerCase().replace(/[^0-9a-z\u4e00-\u9fff]/g, '')
}

function authoritativeSwitchEvents(): ResolvedSwitchEvent[] {
  const seen = new Set<string>()
  return props.events.flatMap((event, eventIndex) => {
    if (event.event_type !== 'ACTIVE_SWITCH') return []
    const timestamp = event.render_point_timestamp || event.point_timestamp || event.timestamp
    const timestampMillis = meshTimestampMillis(timestamp)
    if (timestampMillis === null) return []
    const key = [
      timestampMillis,
      event.local_radio ?? '',
      normalizedIdentity(event.from_peer_mac),
      normalizedIdentity(event.to_peer_mac),
    ].join(':')
    if (seen.has(key)) return []
    seen.add(key)
    return [{ event, eventIndex, timestamp, timestampMillis }]
  })
}

function findRenderedSwitchPoint(item: ResolvedSwitchEvent): ResolvedTracksidePoint | undefined {
  const { event, timestampMillis } = item
  if (event.render_aligned === false) return undefined
  const context = event.point_context
  return findTracksideFrameMetaIds(seriesCache, timestampMillis)
    .map(resolvedPoint)
    .filter((point): point is ResolvedTracksidePoint => Boolean(point))
    .find(({ meta }) => (
      meta.role === 'ACTIVE'
      && (context?.link_id == null || meta.linkId === context.link_id)
      && (context?.timestamp_tag == null || meta.timestampTag === context.timestamp_tag)
      && (event.local_radio == null || meta.localRadio === event.local_radio)
      && (!event.to_peer_mac || normalizedIdentity(meta.peerMac) === normalizedIdentity(event.to_peer_mac))
      && (!event.to_ap_name || normalizedIdentity(meta.peerApName) === normalizedIdentity(event.to_ap_name))
      && meta.rssi != null
      && meta.rssi !== 0
    ))
}

function switchNodeData(events: ResolvedSwitchEvent[]): Array<{ value: [number, number, number]; symbol: string }> {
  return events.flatMap((event) => {
    const point = findRenderedSwitchPoint(event)
    if (!point || point.data[1] == null) return []
    return [{
      value: [point.data[0], point.data[1], event.eventIndex],
      symbol: 'circle',
    }]
  })
}

function tooltipEntry(point: ResolvedTracksidePoint): TracksideTooltipEntry {
  const { meta, series } = point
  return {
    seriesId: series.seriesId,
    metaId: meta.metaId,
    apName: pointLabel(meta),
    radio: meta.localRadio ?? series.radio,
    role: meta.role,
    tracksideRssi: meta.rssi,
    mrRssi: meta.localRssi,
    station: meta.station ?? series.station,
    section: meta.section ?? series.section,
    activeDurationSeconds: meta.segmentDurationSeconds,
    color: seriesColor(series.seriesId, readNetConsoleChartTokens().textSecondary),
    rssiZeroRun: meta.rssiZeroRun,
  }
}

function cancelTooltipHide(): void {
  if (tooltipHideTimer) clearTimeout(tooltipHideTimer)
  tooltipHideTimer = null
}

function hideTracksideTooltip(hideEchartsTip = true): void {
  cancelTooltipHide()
  const side = tracksideTooltip.value.side
  tracksideTooltip.value = {
    visible: false,
    timestamp: null,
    timestampMillis: null,
    entries: [],
    side,
    source: 'none',
  }
  if (hideEchartsTip) {
    chart?.dispatchAction({ type: 'hideTip' }, { silent: true })
  }
}

function scheduleTooltipHide(): void {
  cancelTooltipHide()
  tooltipHideTimer = setTimeout(() => {
    tooltipHideTimer = null
    if (!tooltipPointerInside) hideTracksideTooltip()
  }, 100)
}

function showTracksideTooltip(timestampMillis: number): void {
  const matchedTimestamp = tooltipFrameTimestamp(timestampMillis)
  if (matchedTimestamp === null) {
    hideTracksideTooltip(false)
    return
  }
  const points = findTracksideFrameMetaIds(seriesCache, matchedTimestamp)
    .map(resolvedPoint)
    .filter((point): point is ResolvedTracksidePoint => Boolean(point))
  if (!points.length) {
    hideTracksideTooltip(false)
    return
  }
  tracksideTooltip.value = {
    visible: true,
    timestamp: formatMeshViewportTimestamp(matchedTimestamp),
    timestampMillis: matchedTimestamp,
    entries: points.map(tooltipEntry),
    side: pinnedTracksideFrame.value ? 'left' : localPointerSide,
    source: 'local',
  }
}

function pinCurrentTracksideFrame(): void {
  const current = tracksideTooltip.value
  if (
    !current.visible
    || current.timestampMillis === null
    || !current.timestamp
    || !current.entries.length
  ) return
  pinnedTracksideFrame.value = {
    timestamp: current.timestamp,
    timestampMillis: current.timestampMillis,
    entries: current.entries.map((entry) => ({ ...entry })),
  }
  updateSelectedRangeStatus()
  hideTracksideTooltip(false)
}

function closePinnedTracksideFrame(): void {
  pinnedTracksideFrame.value = null
  pinnedOutsideRange.value = false
}

function selectPinnedTracksideEntry(entry: TracksideTooltipEntry): void {
  const point = tracksidePointMeta(seriesCache, entry.metaId)
  const series = seriesCache.seriesMetaById.get(entry.seriesId)
  if (point && series) selectTracksidePoint(point, series, false)
}

function updateTooltipAvailableHeight(): void {
  const height = container.value?.clientHeight || 0
  tooltipAvailableHeight.value = height > 24 ? height - 24 : 640
}

function handleTooltipPointerEnter(): void {
  tooltipPointerInside = true
  cancelTooltipHide()
}

function handleTooltipPointerLeave(): void {
  tooltipPointerInside = false
  scheduleTooltipHide()
}

async function ensureChart(): Promise<boolean> {
  if (chart) return true
  if (!props.active || !hasRenderableSize() || disposed) return false
  if (initialization) return initialization
  initialization = (async () => {
    const [core, charts, components, renderers] = await Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ])
    core.use([
      charts.LineChart,
      charts.ScatterChart,
      components.GridComponent,
      components.LegendComponent,
      components.TooltipComponent,
      components.DataZoomComponent,
      components.MarkLineComponent,
      components.MarkAreaComponent,
      components.ToolboxComponent,
      renderers.CanvasRenderer,
    ])
    await nextTick()
    if (!props.active || !hasRenderableSize() || disposed || !container.value) return false
    emit('workload-profile', { conflictEdgeCount: seriesColors.conflictEdgeCount })
    reportWorkloadPhase('echarts-init')
    chart = core.init(container.value, undefined, createTimeChartInitOptions(seriesCache.totalRenderedPoints, {
      useDirtyRect: false,
    }))
    invalidateAppliedViewport()
    chart.on('click', handleChartClick)
    chart.on('datazoom', handleDataZoom)
    chart.on('restore', handleRestore)
    chart.on('updateAxisPointer', handleAxisPointer)
    pointerGlobalOut = () => {
      if (!props.active) return
      pointerOrigin = 'none'
      emit('pointer-change', { time: null, source_chart: props.chartId })
      scheduleTooltipHide()
    }
    const zrender = (chart as unknown as { getZr?: () => { on: (event: string, listener: (event: { target?: unknown }) => void) => void } }).getZr?.()
    zrender?.on('globalout', pointerGlobalOut)
    zrenderBlankClick = (event) => {
      if (!event.target) clearTracksideSelection()
    }
    zrender?.on('click', zrenderBlankClick)
    unsubscribeTheme = subscribeNetConsoleChartTheme(() => {
      rebuildSeriesColors()
      scheduleChartUpdate('theme')
      scheduleViewportSeriesUpdate()
    })
    return true
  })().finally(() => { initialization = null })
  return initialization
}

function reportWorkloadPhase(
  phase: 'echarts-init' | 'echarts-set-option' | 'echarts-interactive' | 'chart-disposed',
): void {
  if (reportedPhases.has(phase)) return
  reportedPhases.add(phase)
  emit('workload-phase', phase)
}

function scheduleInteractiveReport(): void {
  if (interactiveTimer) clearTimeout(interactiveTimer)
  interactiveTimer = setTimeout(() => {
    interactiveTimer = null
    if (!disposed && chart) reportWorkloadPhase('echarts-interactive')
  }, 3_000)
}

function scheduleChartUpdate(reason: 'data' | 'display' | 'theme' | 'reset' | 'resize' = 'resize'): void {
  if (reason !== 'resize') {
    const priority = { display: 1, theme: 2, data: 3, reset: 4 }
    if (!pendingRenderReason || priority[reason] >= priority[pendingRenderReason]) pendingRenderReason = reason
  }
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    if (!props.active || !hasRenderableSize() || disposed) return
    const chartExisted = Boolean(chart)
    void ensureChart().then((ready) => {
      if (!ready || !props.active || disposed) return
      const renderReason = pendingRenderReason
      pendingRenderReason = null
      if (renderReason || !chartExisted) render(renderReason || 'data')
      chart?.resize({ silent: true, animation: { duration: 0 } })
    })
  })
}

function handleWindowResize(): void {
  updateTooltipAvailableHeight()
  scheduleChartUpdate()
}

onMounted(() => {
  disposed = false
  rebuildSeriesCache()
  updateTooltipAvailableHeight()
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    updateTooltipAvailableHeight()
    scheduleChartUpdate()
  })
  if (container.value) resizeObserver?.observe(container.value)
  window.addEventListener('resize', handleWindowResize)
  window.addEventListener('keydown', handleSelectionEscape, true)
  scheduleChartUpdate('data')
  recomputeViewportSeries()
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', handleWindowResize)
  window.removeEventListener('keydown', handleSelectionEscape, true)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  resizeFrame = null
  pendingRenderReason = null
  if (viewportFrame !== null) cancelAnimationFrame(viewportFrame)
  viewportFrame = null
  pendingViewport = null
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.off('click', handleChartClick)
  chart?.off('datazoom', handleDataZoom)
  chart?.off('restore', handleRestore)
  chart?.off('updateAxisPointer', handleAxisPointer)
  if (pointerGlobalOut || zrenderBlankClick) {
    const zrender = (chart as unknown as { getZr?: () => { off: (event: string, listener: (event: { target?: unknown }) => void) => void } } | null)?.getZr?.()
    if (pointerGlobalOut) zrender?.off('globalout', pointerGlobalOut)
    if (zrenderBlankClick) zrender?.off('click', zrenderBlankClick)
  }
  pointerGlobalOut = null
  zrenderBlankClick = null
  if (interactiveTimer) clearTimeout(interactiveTimer)
  interactiveTimer = null
  if (viewportListTimer) clearTimeout(viewportListTimer)
  viewportListTimer = null
  cancelTooltipHide()
  tooltipPointerInside = false
  pointerOrigin = 'none'
  closePinnedTracksideFrame()
  chart?.dispose()
  chart = null
  invalidateAppliedViewport()
  disposeTracksideSeriesColorAssignment(seriesColors)
  disposeTracksideSeriesCache(seriesCache)
  reportWorkloadPhase('chart-disposed')
})

watch(() => [props.seriesCache, props.series] as const, () => {
  reportedPhases.clear()
  rebuildSeriesCache()
  scheduleChartUpdate('data')
})
watch(() => [props.events, props.locationSegments] as const, () => scheduleChartUpdate('display'))
watch(() => [props.showSwitchLines, props.showSwitchPoints, props.showLocationBand] as const, () => scheduleChartUpdate('display'))
watch(() => props.active, (active) => {
  if (active) {
    void nextTick(() => scheduleChartUpdate(pendingRenderReason || 'resize'))
    return
  }
  pointerOrigin = 'none'
  hideTracksideTooltip()
  chart?.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' }, { silent: true })
})
watch(() => props.workspaceVisible, (visible) => {
  if (!visible) closePinnedTracksideFrame()
})
watch(() => props.lockedViewport, (viewport, previous) => {
  if (viewport) void nextTick(() => applyViewport(viewport))
  else if (previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })
watch(() => props.initialViewport, (viewport) => { if (viewport && !currentViewport) void nextTick(() => applyViewport(viewport)) }, { deep: true })
watch(() => props.syncViewport, (viewport, previous) => {
  if (props.active && viewport) void nextTick(() => applyViewport(viewport))
  else if (!viewport && previous) { currentViewport = null; scheduleChartUpdate('reset') }
  scheduleViewportSeriesUpdate()
}, { deep: true })
watch(() => props.sharedTimeDomain, () => scheduleChartUpdate('theme'), { deep: true })
watch(() => [props.syncPointerTime, props.syncPointerSource] as const, ([time, source]) => {
  if (source !== props.chartId) void nextTick(() => applySharedPointer(time))
})

function handleChartClick(raw: unknown): void {
  if (!props.active) return
  const candidate = raw as {
    seriesId?: string
    data?: CompactTracksideChartPoint | { value?: [number, number, number]; eventIndex?: number }
  }
  const nodeValue = !Array.isArray(candidate.data) ? candidate.data?.value : undefined
  const eventIndex = candidate.seriesId === 'trackside-switch-nodes'
    ? nodeValue?.[2]
    : !Array.isArray(candidate.data)
      ? candidate.data?.eventIndex
      : undefined
  const pointValue = Array.isArray(candidate.data) ? candidate.data : undefined
  const pointMeta = pointValue ? tracksidePointMeta(seriesCache, pointValue[2]) : undefined
  const pointSeries = pointMeta ? seriesCache.seriesMetaById.get(pointMeta.seriesId) : undefined
  const event = Number.isSafeInteger(eventIndex)
    ? props.events[Number(eventIndex)]
    : props.events.find((item) => (
        pointMeta
        && meshTimestampMillis(item.render_point_timestamp || item.point_timestamp || item.timestamp)
          === pointMeta.timestampMillis
      ))
  if (candidate.seriesId === 'trackside-switch-nodes') {
    if (event) emit('selectSwitch', event)
    return
  }
  if (pointMeta && pointSeries) selectTracksidePoint(pointMeta, pointSeries)
  if (event) emit('selectSwitch', event)
}

function handleDataZoom(raw: unknown): void {
  if (!props.active) return
  pointerOrigin = 'none'
  hideTracksideTooltip()
  const viewport = viewportFromDataZoomWithOptions(raw, timestamps(), {
    boundaryMode: props.sharedTimeDomain ? 'absolute' : 'sample',
    fullDomain: props.sharedTimeDomain,
    sourceChart: props.chartId,
    revision: (currentViewport?.revision ?? 0) + 1,
  })
  if (!viewport) return
  if (meshDataZoomRequiresCorrection(raw, viewport)) {
    chart?.dispatchAction({
      type: 'dataZoom',
      batch: [0, 1].map((dataZoomIndex) => ({
        dataZoomIndex,
        startValue: viewport.start_time,
        endValue: viewport.end_time,
      })),
    }, { silent: true })
  }
  currentViewport = viewport
  markViewportApplied(viewport)
  updateSelectedRangeStatus()
  scheduleViewportSeriesUpdate()
  pendingViewport = viewport
  if (viewportFrame !== null) return
  viewportFrame = requestAnimationFrame(() => {
    viewportFrame = null
    if (!pendingViewport) return
    emit('viewport-change', { ...pendingViewport })
    pendingViewport = null
  })
}

function handleRestore(): void {
  if (!props.active) return
  pointerOrigin = 'none'
  hideTracksideTooltip()
  const viewport = fullViewport('user_zoom')
  if (!viewport) return
  currentViewport = { ...viewport, revision: (currentViewport?.revision ?? 0) + 1 }
  markViewportApplied(currentViewport)
  updateSelectedRangeStatus()
  scheduleViewportSeriesUpdate()
  emit('viewport-change', { ...currentViewport })
}

function beginViewportInteraction(): void {
  if (!props.active) return
  emit('viewport-interaction-start')
}

function endViewportInteraction(): void {
  emit('viewport-interaction-end')
}

function handleAxisPointer(raw: unknown): void {
  if (!props.active) return
  const value = (raw as { axesInfo?: Array<{ value?: string | number }> }).axesInfo?.[0]?.value
  const millis = meshTimestampMillis(value)
  if (millis === null) return
  if (pointerOrigin === 'local') showTracksideTooltip(millis)
  emit('pointer-change', {
    time: typeof value === 'string' ? value : formatMeshViewportTimestamp(millis),
    source_chart: props.chartId,
  })
}

function applySharedPointer(time: string | null): void {
  if (!props.active || !chart) return
  pointerOrigin = 'shared'
  hideTracksideTooltip(false)
  try {
    if (!time) {
      chart.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' }, { silent: true })
      chart.dispatchAction({ type: 'hideTip' }, { silent: true })
      return
    }
    const millis = meshTimestampMillis(time)
    if (millis === null) return
    const convertToPixel = (chart as unknown as { convertToPixel?: (finder: { xAxisIndex: number }, value: number) => number | number[] }).convertToPixel
    if (!convertToPixel) return
    const pixel = convertToPixel.call(chart, { xAxisIndex: 0 }, millis)
    const x = Array.isArray(pixel) ? pixel[0] : pixel
    if (!Number.isFinite(x)) return
    chart.dispatchAction({ type: 'updateAxisPointer', x, y: 1 }, { silent: true })
  } finally {
    pointerOrigin = 'none'
  }
}

function getViewport(): MeshChartViewport | null {
  return currentViewport ? { ...currentViewport } : fullViewport()
}

function applyViewport(viewport: MeshChartViewport): void {
  const isLocked = Boolean(props.lockedViewport
    && props.lockedViewport.start_time === viewport.start_time
    && props.lockedViewport.end_time === viewport.end_time)
  const normalized = normalizeMeshViewport(viewport, isLocked ? [] : timestamps(), 'programmatic', {
    boundaryMode: props.sharedTimeDomain ? 'absolute' : 'sample',
    fullDomain: props.sharedTimeDomain,
    sourceChart: viewport.source_chart,
    revision: viewport.revision,
  })
  if (!normalized) return
  currentViewport = normalized
  updateSelectedRangeStatus()
  scheduleViewportSeriesUpdate()
  if (!chart) return
  if (
    appliedViewportEpoch === chartRenderEpoch
    && meshViewportRangeEquals(appliedViewport, normalized)
    && appliedViewport?.revision === normalized.revision
  ) return
  chart.dispatchAction({
    type: 'dataZoom',
    batch: [0, 1].map((dataZoomIndex) => ({ dataZoomIndex, startValue: normalized.start_time, endValue: normalized.end_time })),
  }, { silent: true })
  markViewportApplied(normalized)
}

function resetViewport(): void {
  const target = props.lockedViewport || fullViewport('programmatic')
  if (target) applyViewport(target)
}

function resize(): void {
  if (props.active) scheduleChartUpdate('resize')
}

function getSeriesColorMap(): ReadonlyMap<string, string> {
  return seriesColors.colorBySeriesId
}

function tracksideOverlaySeries(
  theme: ReturnType<typeof readNetConsoleChartTokens>,
  clearEmpty = false,
): Array<Record<string, unknown>> {
  const switchEvents = authoritativeSwitchEvents()
  const nodes = props.showSwitchPoints ? switchNodeData(switchEvents) : []
  const locationBands = props.showLocationBand ? buildMeshLocationBands(props.locationSegments) : []
  const markArea = locationBands.length ? {
    silent: true,
    itemStyle: { color: theme.info, opacity: 0.08 },
    label: { show: true, position: 'insideBottom', color: theme.textSecondary, fontSize: 11 },
    data: locationBands.map((band) => [
      { name: band.label, xAxis: band.start_time },
      { xAxis: band.end_time },
    ]),
  } : clearEmpty ? { data: [] } : undefined
  const markLine = props.showSwitchLines && switchEvents.length ? {
    silent: false,
    symbol: 'none',
    label: { show: false },
    lineStyle: { color: theme.warning, type: 'dashed' },
    data: switchEvents.map((event) => ({
      name: event.timestamp,
      xAxis: event.timestamp,
      eventIndex: event.eventIndex,
    })),
  } : clearEmpty ? { data: [] } : undefined
  return [
    ...(seriesCache.series[0] ? [{
      id: seriesCache.series[0].id,
      ...(markArea ? { markArea } : {}),
      ...(markLine ? { markLine } : {}),
    }] : []),
    {
      id: 'trackside-switch-nodes',
      name: '切换节点',
      type: 'scatter',
      symbolSize: 10,
      data: nodes.map((node) => ({ ...node, itemStyle: { color: theme.danger } })),
    },
  ]
}

function tracksideDataSeries(theme: ReturnType<typeof readNetConsoleChartTokens>): Array<Record<string, unknown>> {
  const presentation = createTimeChartLinePresentation(seriesCache.totalRenderedPoints)
  const largeMode = isLargeTimeChart(seriesCache.totalRenderedPoints)
  const overlayById = new Map(tracksideOverlaySeries(theme).map((item) => [String(item.id), item]))
  const nodeSeries = overlayById.get('trackside-switch-nodes')
  const nodeData = nodeSeries?.data
  return [
    ...seriesCache.series.map((item) => {
      const color = seriesColor(item.id, theme.textSecondary)
      return {
        id: item.id,
        name: item.name,
        type: 'line',
        ...presentation,
        symbol: presentation.showSymbol
          ? (value: CompactTracksideChartPoint) => value[3] === 1 ? 'emptyCircle' : 'circle'
          : 'none',
        hoverAnimation: false,
        emphasis: { disabled: true },
        progressive: largeMode ? 3_000 : 0,
        progressiveThreshold: 3_000,
        connectNulls: false,
        data: item.data,
        itemStyle: { color },
        lineStyle: {
          ...presentation.lineStyle,
          color,
          type: 'solid',
        },
        ...(overlayById.get(item.id) || {}),
      }
    }),
    ...(Array.isArray(nodeData) && nodeData.length ? [nodeSeries!] : []),
  ]
}

function render(reason: 'data' | 'display' | 'theme' | 'reset'): void {
  if (!chart) return
  const previous = reason !== 'reset' && props.preserveViewport && currentViewport
    ? { ...currentViewport }
    : null
  const theme = readNetConsoleChartTokens()
  const target = props.lockedViewport || previous || props.syncViewport || props.initialViewport || fullViewport()
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, {
    unit: 'RSSI',
    pointCount: seriesCache.totalRenderedPoints,
    fullDomain: props.sharedTimeDomain,
    viewport: target,
    showLegend: false,
    reserveLegendSpace: false,
  })
  const tooltip = {
    ...(baseOption.tooltip as Record<string, unknown>),
    showContent: false,
    appendToBody: false,
    transitionDuration: 0,
  }

  if (reason === 'display') {
    chart.setOption({ series: tracksideOverlaySeries(theme, true) }, { lazyUpdate: true })
  } else if (reason === 'theme') {
    invalidateAppliedViewport()
    chart.setOption({
      ...baseOption,
      tooltip,
      yAxis: { ...(baseOption.yAxis as Record<string, unknown>), min: 'dataMin' },
      series: [
        ...seriesCache.series.map((item) => {
          const color = seriesColor(item.id, theme.textSecondary)
          return { id: item.id, itemStyle: { color }, lineStyle: { color, width: 2 } }
        }),
      ],
    }, { lazyUpdate: true })
  } else {
    reportWorkloadPhase('echarts-set-option')
    invalidateAppliedViewport()
    chart.clear?.()
    chart.setOption({
      ...baseOption,
      tooltip,
      yAxis: { ...(baseOption.yAxis as Record<string, unknown>), min: 'dataMin' },
      series: tracksideDataSeries(theme),
    }, { replaceMerge: ['series'] })
    scheduleInteractiveReport()
  }
  scheduleViewportSeriesUpdate()
  if (target) {
    applyViewport(target)
    if (!viewportReady && currentViewport) {
      viewportReady = true
      emit('viewport-ready', { ...currentViewport })
    }
  }
}

defineExpose({
  getViewport,
  applyViewport,
  resetViewport,
  resize,
  getVisibleTimeRange: getViewport,
  getSeriesColorMap,
})
</script>

<template>
  <div class="chart-shell">
    <div class="trackside-controls">
      <div v-if="selectedTracksideAp" class="trackside-selected-ap" data-trackside-selected-ap>
        <span class="trackside-selected-ap__dot" :style="{ backgroundColor: selectedSeriesColor() }"></span>
        <span><strong>已选 AP：</strong>{{ apDisplayName(selectedTracksideAp) }}</span>
        <span><strong>AP MAC：</strong>{{ compactMac(selectedTracksideAp.apMac) }}</span>
        <span><strong>Radio：</strong>{{ selectedTracksideAp.radio ?? '—' }}</span>
        <span><strong>轨旁 RSSI：</strong>{{ displayRssi(selectedTracksideAp.rssi) }}</span>
        <span v-if="selectedOutsideRange" class="trackside-selected-ap__status">当前范围外</span>
        <button type="button" class="trackside-text-button" @click="clearTracksideSelection()">取消选择</button>
      </div>
      <details class="trackside-range" @toggle="handleRangePanelToggle">
        <summary>当前范围 AP（{{ viewportSeries.length }}）</summary>
        <div v-if="rangePanelOpen" class="trackside-range__list">
          <button
            v-for="item in viewportSeries"
            :key="item.seriesId"
            type="button"
            class="trackside-range__item"
            :class="{ 'is-selected': selectedTracksideAp?.seriesId === item.seriesId }"
            @click="selectViewportSeries(item)"
          >
            <span class="trackside-range__dot" :style="{ backgroundColor: item.color }"></span>
            <span class="trackside-range__copy">
              <strong>{{ apDisplayName(item) }}</strong>
              <small>{{ compactMac(item.apMac) }} · Radio {{ item.radio ?? '—' }} · {{ item.rssiSource === 'pointer' ? 'RSSI' : '最新 RSSI' }} {{ displayRssi(item.rssi) }}</small>
            </span>
          </button>
          <span v-if="!viewportSeries.length" class="trackside-range__empty">当前范围无 AP 采样</span>
        </div>
      </details>
    </div>
    <div
      ref="container"
      class="chart"
      @pointermove.capture="handleLocalPointerMove"
      @pointerdown.capture="beginViewportInteraction"
      @pointerup.capture="endViewportInteraction"
      @pointercancel.capture="endViewportInteraction"
      @touchstart.passive="beginViewportInteraction"
      @touchend.passive="endViewportInteraction"
      @touchcancel.passive="endViewportInteraction"
    ></div>
    <TracksideExternalTooltip
      :visible="tracksideTooltip.visible"
      :timestamp="tracksideTooltip.timestamp"
      :entries="tracksideTooltip.entries"
      :side="tracksideTooltip.side"
      :available-height="tooltipAvailableHeight"
      @pin="pinCurrentTracksideFrame"
      @pointerenter="handleTooltipPointerEnter"
      @pointerleave="handleTooltipPointerLeave"
    />
    <TracksideFrameDetailPanel
      v-if="pinnedTracksideFrame"
      :frame="pinnedTracksideFrame"
      :outside-range="pinnedOutsideRange"
      @close="closePinnedTracksideFrame"
      @select="selectPinnedTracksideEntry"
    />
    <el-empty v-if="!hasData()" class="empty" description="暂无轨旁信号数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; height: 100%; min-height: 0; width: 100%; }
.chart { height: 100%; min-height: 0; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
.trackside-controls { position: absolute; top: 0; right: 132px; left: 64px; z-index: 4; display: flex; min-height: 30px; align-items: center; gap: 8px; padding: 1px 0; }
.trackside-selected-ap { display: flex; min-width: 0; flex: 1 1 auto; align-items: center; gap: 12px; overflow-x: auto; white-space: nowrap; color: var(--nc-text-secondary); font-size: 12px; }
.trackside-selected-ap strong { color: var(--nc-text-primary); font-weight: 600; }
.trackside-selected-ap__dot { width: 8px; height: 8px; flex: none; border-radius: 50%; }
.trackside-selected-ap__status { color: var(--nc-warning); }
.trackside-text-button { flex: none; border: 0; background: transparent; color: var(--nc-primary); cursor: pointer; font: inherit; }
.trackside-range { position: relative; flex: none; margin-left: auto; color: var(--nc-text-secondary); font-size: 12px; }
.trackside-range summary { cursor: pointer; list-style: none; color: var(--nc-primary); user-select: none; }
.trackside-range summary::-webkit-details-marker { display: none; }
.trackside-range__list { position: absolute; top: calc(100% + 8px); right: 0; z-index: 20; display: grid; width: min(360px, calc(100vw - 48px)); max-height: min(360px, 55vh); overflow-y: auto; padding: 6px; border: 1px solid var(--nc-border); background: var(--nc-bg-elevated); box-shadow: var(--nc-shadow-floating); }
.trackside-range__item { display: grid; grid-template-columns: 10px minmax(0, 1fr); align-items: center; gap: 8px; width: 100%; padding: 7px 8px; border: 0; background: transparent; color: var(--nc-text-primary); text-align: left; cursor: pointer; }
.trackside-range__item:hover,
.trackside-range__item.is-selected { background: var(--nc-bg-muted); }
.trackside-range__dot { width: 8px; height: 8px; border-radius: 50%; }
.trackside-range__copy { display: grid; min-width: 0; gap: 2px; }
.trackside-range__copy strong,
.trackside-range__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trackside-range__copy small { color: var(--nc-text-secondary); }
.trackside-range__empty { padding: 16px 8px; color: var(--nc-text-secondary); text-align: center; }
</style>
