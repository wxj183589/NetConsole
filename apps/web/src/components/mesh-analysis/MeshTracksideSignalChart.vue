<script setup lang="ts">
import { markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
  normalizedApRadioColorKey,
  stableTimeChartSeriesColor,
} from '../charts/multiSeriesTimeChart'
import type {
  MeshChartEvent,
  MeshLocationSegment,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
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
  tracksidePointMeta,
  type CompactTracksideChartPoint,
  type CompactTracksidePointMeta,
  type CompactTracksideSeriesMeta,
  type TracksideSeriesCache,
} from './tracksideSeriesCache'
import {
  buildTracksideTooltip,
  resolveTracksideTooltipPosition,
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
  'workload-phase': [phase: 'echarts-init' | 'echarts-set-option' | 'echarts-interactive' | 'chart-disposed']
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
let viewportReady = false
let viewportFrame: number | null = null
let pendingViewport: MeshChartViewport | null = null
let pointerGlobalOut: (() => void) | null = null
let interactiveTimer: ReturnType<typeof setTimeout> | null = null
let seriesCache: TracksideSeriesCache = markRaw(props.seriesCache ?? buildTracksideSeriesCache(props.series))
const reportedPhases = new Set<string>()
const guardedTooltipElements = new Set<HTMLElement>()

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

function tracksideColorKey(series: CompactTracksideSeriesMeta): string {
  if (!series.peerRadioMac && !series.apMac && !series.peerMac) return series.seriesId
  return normalizedApRadioColorKey(
    series.peerRadioMac || series.apMac,
    series.peerMac,
    series.radio,
  )
}

function rebuildSeriesCache(): void {
  const next = props.seriesCache ?? buildTracksideSeriesCache(props.series)
  if (next !== seriesCache) {
    chart?.clear?.()
    disposeTracksideSeriesCache(seriesCache)
    seriesCache = markRaw(next)
  }
  if (import.meta.env.DEV && seriesCache.unorderedSeriesIds.length) {
    console.warn(`轨旁信号 payload 存在未按时间排序的序列：${seriesCache.unorderedSeriesIds.join(', ')}`)
  }
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
    apName: pointLabel(meta),
    radio: meta.localRadio ?? series.radio,
    role: meta.role,
    tracksideRssi: meta.rssi,
    mrRssi: meta.localRssi,
    station: meta.station ?? series.station,
    section: meta.section ?? series.section,
    activeDurationSeconds: meta.segmentDurationSeconds,
  }
}

function stopTooltipWheelPropagation(event: WheelEvent): void {
  event.stopPropagation()
}

function guardTooltipWheel(element: HTMLElement): void {
  if (guardedTooltipElements.has(element)) return
  guardedTooltipElements.add(element)
  element.addEventListener('wheel', stopTooltipWheelPropagation, { passive: true })
}

function releaseTooltipWheelGuards(): void {
  for (const element of guardedTooltipElements) {
    element.removeEventListener('wheel', stopTooltipWheelPropagation)
  }
  guardedTooltipElements.clear()
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
    reportWorkloadPhase('echarts-init')
    chart = core.init(container.value, undefined, createTimeChartInitOptions(seriesCache.totalRenderedPoints))
    chart.on('click', handleChartClick)
    chart.on('datazoom', handleDataZoom)
    chart.on('restore', handleRestore)
    chart.on('updateAxisPointer', handleAxisPointer)
    pointerGlobalOut = () => emit('pointer-change', { time: null, source_chart: props.chartId })
    const zrender = (chart as unknown as { getZr?: () => { on: (event: string, listener: () => void) => void } }).getZr?.()
    zrender?.on('globalout', pointerGlobalOut)
    unsubscribeTheme = subscribeNetConsoleChartTheme(() => scheduleChartUpdate('theme'))
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
      chart?.resize()
    })
  })
}

function handleWindowResize(): void {
  scheduleChartUpdate()
}

onMounted(() => {
  disposed = false
  rebuildSeriesCache()
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => scheduleChartUpdate())
  if (container.value) resizeObserver?.observe(container.value)
  window.addEventListener('resize', handleWindowResize)
  scheduleChartUpdate('data')
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', handleWindowResize)
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
  if (pointerGlobalOut) {
    const zrender = (chart as unknown as { getZr?: () => { off: (event: string, listener: () => void) => void } } | null)?.getZr?.()
    zrender?.off('globalout', pointerGlobalOut)
  }
  pointerGlobalOut = null
  if (interactiveTimer) clearTimeout(interactiveTimer)
  interactiveTimer = null
  releaseTooltipWheelGuards()
  chart?.dispose()
  chart = null
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
watch(() => props.active, (active) => { if (active) void nextTick(() => scheduleChartUpdate(pendingRenderReason || 'resize')) })
watch(() => props.lockedViewport, (viewport, previous) => {
  if (viewport) void nextTick(() => applyViewport(viewport))
  else if (previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })
watch(() => props.initialViewport, (viewport) => { if (viewport && !currentViewport) void nextTick(() => applyViewport(viewport)) }, { deep: true })
watch(() => props.syncViewport, (viewport, previous) => {
  if (viewport && !meshViewportRangeEquals(currentViewport, viewport)) void nextTick(() => applyViewport(viewport))
  else if (!viewport && previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })
watch(() => props.sharedTimeDomain, () => scheduleChartUpdate('theme'), { deep: true })
watch(() => [props.syncPointerTime, props.syncPointerSource] as const, ([time, source]) => {
  if (source !== props.chartId) void nextTick(() => applySharedPointer(time))
})

function handleChartClick(raw: unknown): void {
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
  const event = Number.isSafeInteger(eventIndex)
    ? props.events[Number(eventIndex)]
    : props.events.find((item) => (
        pointMeta
        && meshTimestampMillis(item.render_point_timestamp || item.point_timestamp || item.timestamp)
          === pointMeta.timestampMillis
      ))
  if (event) emit('selectSwitch', event)
}

function handleDataZoom(raw: unknown): void {
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
  const viewport = fullViewport('user_zoom')
  if (!viewport) return
  currentViewport = { ...viewport, revision: (currentViewport?.revision ?? 0) + 1 }
  emit('viewport-change', { ...currentViewport })
}

function handleAxisPointer(raw: unknown): void {
  const value = (raw as { axesInfo?: Array<{ value?: string | number }> }).axesInfo?.[0]?.value
  const millis = meshTimestampMillis(value)
  if (millis === null) return
  emit('pointer-change', {
    time: typeof value === 'string' ? value : formatMeshViewportTimestamp(millis),
    source_chart: props.chartId,
  })
}

function applySharedPointer(time: string | null): void {
  if (!chart) return
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
  if (meshViewportRangeEquals(currentViewport, normalized) && currentViewport?.revision === normalized.revision) return
  currentViewport = normalized
  if (!chart) return
  chart.dispatchAction({
    type: 'dataZoom',
    batch: [0, 1].map((dataZoomIndex) => ({ dataZoomIndex, startValue: normalized.start_time, endValue: normalized.end_time })),
  }, { silent: true })
}

function resetViewport(): void {
  const target = props.lockedViewport || fullViewport('programmatic')
  if (target) applyViewport(target)
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
      const color = stableTimeChartSeriesColor(
        tracksideColorKey(item.meta),
        theme.series,
      )
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
        lineStyle: { ...presentation.lineStyle, color, type: 'solid' },
        ...(overlayById.get(item.id) || {}),
      }
    }),
    ...(Array.isArray(nodeData) && nodeData.length ? [nodeSeries!] : []),
  ]
}

function render(reason: 'data' | 'display' | 'theme' | 'reset'): void {
  if (!chart) return
  const previous = reason !== 'reset' && props.preserveViewport ? getViewport() : null
  const theme = readNetConsoleChartTokens()
  const target = props.lockedViewport || previous || props.syncViewport || props.initialViewport || fullViewport()
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, {
    unit: 'dBm',
    pointCount: seriesCache.totalRenderedPoints,
    fullDomain: props.sharedTimeDomain,
    viewport: target,
  })
  const tooltip = {
    ...(baseOption.tooltip as Record<string, unknown>),
    enterable: true,
    confine: true,
    transitionDuration: 0,
    hideDelay: 50,
    position: (
      point: [number, number],
      _params: unknown,
      dom: HTMLElement,
      _rect: unknown,
      size: { contentSize: [number, number]; viewSize: [number, number] },
    ) => {
      guardTooltipWheel(dom)
      const contentWidth = Math.max(0, Math.min(340, size.viewSize[0] - 24))
      const content = dom.querySelector<HTMLElement>('.mesh-trackside-signal-tooltip')
      if (content) {
        content.style.width = `${contentWidth}px`
        content.style.minWidth = `${Math.min(260, contentWidth)}px`
      }
      return resolveTracksideTooltipPosition(point[0], size.viewSize[0], contentWidth)
    },
    formatter: (rawParams: unknown) => {
      const params = Array.isArray(rawParams) ? rawParams : [rawParams]
      const first = params[0] as { axisValue?: string | number } | undefined
      const pointerMillis = meshTimestampMillis(first?.axisValue)
      const pointerTime = pointerMillis === null
        ? undefined
        : typeof first?.axisValue === 'string'
          ? first.axisValue
          : formatMeshViewportTimestamp(pointerMillis)
      const pointItems = pointerMillis === null
        ? []
        : findTracksideFrameMetaIds(seriesCache, pointerMillis)
          .map(resolvedPoint)
          .filter((point): point is ResolvedTracksidePoint => Boolean(point))
      return buildTracksideTooltip(
        pointItems[0] ? formatMeshViewportTimestamp(pointItems[0].meta.timestampMillis) : pointerTime,
        pointItems.map(tooltipEntry),
      )
    },
  }

  if (reason === 'display') {
    chart.setOption({ series: tracksideOverlaySeries(theme, true) }, { lazyUpdate: true })
  } else if (reason === 'theme') {
    chart.setOption({
      ...baseOption,
      tooltip,
      yAxis: { ...(baseOption.yAxis as Record<string, unknown>), min: 'dataMin' },
      series: seriesCache.series.map((item) => {
        const color = stableTimeChartSeriesColor(
          tracksideColorKey(item.meta),
          theme.series,
        )
        return { id: item.id, itemStyle: { color }, lineStyle: { color, width: 2 } }
      }),
    }, { lazyUpdate: true })
  } else {
    reportWorkloadPhase('echarts-set-option')
    chart.clear?.()
    chart.setOption({
      ...baseOption,
      tooltip,
      yAxis: { ...(baseOption.yAxis as Record<string, unknown>), min: 'dataMin' },
      series: tracksideDataSeries(theme),
    }, { replaceMerge: ['series'] })
    scheduleInteractiveReport()
  }
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
  getVisibleTimeRange: getViewport,
})
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!hasData()" class="empty" description="暂无轨旁信号数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; height: 100%; min-height: 360px; width: 100%; }
.chart { height: 100%; min-height: 360px; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
