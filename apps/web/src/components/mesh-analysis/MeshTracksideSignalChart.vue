<script setup lang="ts">
import { markRaw, nextTick, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
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
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import { buildMeshLocationBands } from './chartSeries'
import {
  createFullMeshViewport,
  createFullMeshViewportFromDomain,
  formatMeshViewportTimestamp,
  meshTimestampMillis,
  meshViewportRangeEquals,
  normalizeMeshViewport,
  viewportFromDataZoomWithOptions,
  type MeshChartViewport,
  type MeshRssiChartSource,
  type MeshSharedPointerChange,
  type MeshSharedTimeDomain,
} from './meshChartViewport'
import { buildSwitchSection, escapeMeshTooltipHtml } from './meshRssiTooltip'
import {
  buildTracksideSeriesCache,
  tracksidePointValue,
  type RenderedTracksideSignalPoint as RenderedSignalPoint,
  type TracksideSeriesCache,
} from './tracksideSeriesCache'

const props = withDefaults(defineProps<{
  series: MeshTracksideSignalSeriesData[]
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
let seriesCache: TracksideSeriesCache = markRaw(buildTracksideSeriesCache([]))

const timestamps = (): string[] => seriesCache.timestamps
const hasData = () => seriesCache.series.some((item) => item.data.some((point) => point.value[1] != null))
const fullViewport = (source: MeshChartViewport['source'] = 'initial'): MeshChartViewport | null => (
  props.sharedTimeDomain
    ? createFullMeshViewportFromDomain(props.sharedTimeDomain, source, props.chartId, currentViewport?.revision ?? 0)
    : createFullMeshViewport(timestamps(), source)
)

function hasRenderableSize(): boolean {
  return Boolean(container.value && container.value.clientWidth > 0 && container.value.clientHeight > 0)
}

function metric(value: number | null | undefined, unit = ''): string {
  return value == null ? '—' : `${value}${unit}`
}

function seriesLabel(series: MeshTracksideSignalSeriesData): string {
  const base = series.peer_name || series.peer_mac || '轨旁 AP 未知'
  const radio = series.radio == null ? '—' : series.radio
  return `${base} · Radio ${radio}`
}

function pointLabel(point: MeshTracksideSignalPointData): string {
  return point.peer_ap_name || point.peer_mac || '轨旁 AP 未知'
}

function tracksideColorKey(series: MeshTracksideSignalSeriesData): string {
  if (!series.peer_radio_mac && !series.ap_mac && !series.peer_mac) return series.series_id
  return normalizedApRadioColorKey(
    series.peer_radio_mac || series.ap_mac,
    series.peer_mac,
    series.radio,
  )
}

function rebuildSeriesCache(): void {
  const rawSeries = toRaw(props.series).map((item) => ({
    ...toRaw(item),
    points: toRaw(item.points).map((point) => toRaw(point)),
  }))
  seriesCache = markRaw(buildTracksideSeriesCache(rawSeries))
  if (import.meta.env.DEV && seriesCache.unorderedSeriesIds.length) {
    console.warn(`轨旁信号 payload 存在未按时间排序的序列：${seriesCache.unorderedSeriesIds.join(', ')}`)
  }
}

function findRenderedSwitchPoint(event: MeshChartEvent): RenderedSignalPoint | undefined {
  if (event.render_aligned === false) return undefined
  const timestamp = event.render_point_timestamp || event.point_timestamp || event.timestamp
  if (!timestamp) return undefined
  const context = event.point_context
  const exactMatch = seriesCache.series.flatMap((item) => item.data).find((point) => (
    Boolean(point.meta)
    && point.value[0] === timestamp
    && (context?.link_id == null || point.meta!.link_id === context.link_id)
    && (context?.timestamp_tag == null || point.meta!.timestamp_tag === context.timestamp_tag)
    && (event.local_radio == null || point.meta!.local_radio === event.local_radio)
    && tracksidePointValue(point.meta!) != null
    && tracksidePointValue(point.meta!) !== 0
  ))
  if (exactMatch) return exactMatch
  return seriesCache.series.flatMap((item) => item.data).find((point) => (
    Boolean(point.meta)
    && point.value[0] === timestamp
    && (event.local_radio == null || point.meta!.local_radio === event.local_radio)
    && tracksidePointValue(point.meta!) != null
    && tracksidePointValue(point.meta!) !== 0
  ))
}

function switchNodeData(events: MeshChartEvent[]): Array<RenderedSignalPoint & { meshEvent: MeshChartEvent; symbol: string }> {
  return events.flatMap((event) => {
    const point = findRenderedSwitchPoint(event)
    if (!point || point.value[1] == null) return []
    return [{
      ...point,
      meshEvent: event,
      symbol: 'circle',
    }]
  })
}

function buildTooltipPointSection(point: RenderedSignalPoint, index: number): string {
  const meta = point.meta
  const series = point.seriesMeta
  if (!meta || !series) return ''
  return [
    index === 0 ? '<strong>轨旁信号</strong>' : '<hr class="mesh-rssi-tooltip__divider" style="margin:8px 0;border:0;border-top:1px solid currentColor;opacity:.35">',
    `序列：${escapeMeshTooltipHtml(seriesLabel(series))}`,
    `采样时间：${escapeMeshTooltipHtml(point.value[0])}`,
    `轨旁 AP：${escapeMeshTooltipHtml(pointLabel(meta))}`,
    `AP MAC：${escapeMeshTooltipHtml(meta.peer_ap_mac || series.ap_mac)}`,
    `Peer MAC：${escapeMeshTooltipHtml(meta.peer_mac)}`,
    `Peer Radio MAC：${escapeMeshTooltipHtml(meta.peer_radio_mac)}`,
    `Radio：${metric(meta.local_radio)}`,
    `链路角色：${escapeMeshTooltipHtml(meta.role)}`,
    `轨旁侧 RSSI：${metric(point.value[1])}`,
    `MR 侧 RSSI（参考）：${metric(meta.local_rssi)}`,
    `Peer Signal / MR Signal：${metric(meta.peer_signal)} / ${metric(meta.local_signal)}`,
    `站点 / 区间：${escapeMeshTooltipHtml(meta.station)} / ${escapeMeshTooltipHtml(meta.section)}`,
    ...(meta.segment_duration_seconds == null ? [] : [`主链建链持续时间：${metric(meta.segment_duration_seconds, ' s')}`]),
    `数据来源：${escapeMeshTooltipHtml(meta.data_source)}`,
  ].join('<br>')
}

function renderedPointKey(point: RenderedSignalPoint): string {
  const meta = point.meta
  const series = point.seriesMeta
  if (!meta || !series) return ''
  return [
    series.series_id,
    point.value[0],
    meta.link_id ?? '',
    meta.timestamp_tag,
    meta.peer_mac ?? '',
  ].join('|')
}

function buildTooltip(points: RenderedSignalPoint[], event?: MeshChartEvent, pointerTime?: string): string {
  if (!points.length) {
    return `<div class="mesh-trackside-signal-tooltip" style="min-width:280px;max-width:420px;white-space:normal;overflow-wrap:anywhere;line-height:1.6">采样时间：${escapeMeshTooltipHtml(pointerTime || event?.render_point_timestamp || event?.point_timestamp || event?.timestamp)}<br>当前时刻无有效采样${buildSwitchSection(event)}</div>`
  }
  return [
    '<div class="mesh-trackside-signal-tooltip" style="min-width:280px;max-width:420px;white-space:normal;overflow-wrap:anywhere;line-height:1.6">',
    `采样时间：${escapeMeshTooltipHtml(points[0].value[0])}`,
    points.map((point, index) => buildTooltipPointSection(point, index)).join(''),
    buildSwitchSection(event),
    '</div>',
  ].join('<br>')
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
  chart?.dispose()
  chart = null
})

watch(() => props.series, () => { rebuildSeriesCache(); scheduleChartUpdate('data') })
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
  const data = (raw as { data?: { meshEvent?: MeshChartEvent; meta?: MeshTracksideSignalPointData } }).data
  const event = data?.meshEvent || props.events.find((item) => (
    (item.render_point_timestamp || item.point_timestamp || item.timestamp) === data?.meta?.timestamp
    || item.timestamp === data?.meta?.timestamp
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
  const switchEvents = props.events.filter((event) => event.event_type === 'ACTIVE_SWITCH')
  const largeMode = isLargeTimeChart(seriesCache.totalRenderedPoints)
  const nodes = props.showSwitchPoints && !largeMode ? switchNodeData(switchEvents) : []
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
  const markLine = props.showSwitchLines && switchEvents.length && !largeMode ? {
    silent: false,
    symbol: 'none',
    label: { show: false },
    lineStyle: { color: theme.warning, type: 'dashed' },
    data: switchEvents.map((event) => ({ name: event.timestamp, xAxis: event.timestamp, meshEvent: event })),
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
    formatter: (rawParams: unknown) => {
      const params = Array.isArray(rawParams) ? rawParams : [rawParams]
      const first = params[0] as { axisValue?: string | number } | undefined
      const pointerMillis = meshTimestampMillis(first?.axisValue)
      const pointerTime = pointerMillis === null
        ? undefined
        : typeof first?.axisValue === 'string'
          ? first.axisValue
          : formatMeshViewportTimestamp(pointerMillis)
      const eventParam = params.find((item) => (item as { data?: { meshEvent?: MeshChartEvent } }).data?.meshEvent) as { data?: { meshEvent?: MeshChartEvent } } | undefined
      const event = eventParam?.data?.meshEvent
      const seen = new Set<string>()
      const pointItems = params.flatMap((item) => {
        const candidate = item as { data?: RenderedSignalPoint }
        const point = candidate.data
        if (!point?.meta || !point.seriesMeta || !Array.isArray(point.value) || point.value[1] == null) return []
        if (pointerMillis !== null && meshTimestampMillis(point.value[0]) !== pointerMillis) return []
        const key = renderedPointKey(point)
        if (!key || seen.has(key)) return []
        seen.add(key)
        return [point]
      }).sort((left, right) => {
        const role = (left.meta?.role === 'ACTIVE' ? 0 : 1) - (right.meta?.role === 'ACTIVE' ? 0 : 1)
        if (role) return role
        return pointLabel(left.meta!).localeCompare(pointLabel(right.meta!), 'zh-CN')
          || String(left.meta?.peer_mac || '').localeCompare(String(right.meta?.peer_mac || ''))
      })
      return buildTooltip(pointItems, event, pointerTime)
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
    chart.setOption({
      ...baseOption,
      tooltip,
      yAxis: { ...(baseOption.yAxis as Record<string, unknown>), min: 'dataMin' },
      series: tracksideDataSeries(theme),
    }, { replaceMerge: ['series'] })
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
