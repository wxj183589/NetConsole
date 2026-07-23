<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import {
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import {
  createMultiSeriesTimeChartBaseOption,
  createTimeChartInitOptions,
  createTimeChartLinePresentation,
} from '../charts/multiSeriesTimeChart'
import type { MeshChartEvent, MeshChartPoint, MeshLocationSegment } from '../../types/meshAnalysis'
import { buildMeshLocationBands, buildMeshRssiSeries } from './chartSeries'
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
import { buildMeshRssiTooltip } from './meshRssiTooltip'

const props = withDefaults(defineProps<{
  points: MeshChartPoint[]
  events?: MeshChartEvent[]
  locationSegments?: MeshLocationSegment[]
  showPeer?: boolean
  showSwitchLines?: boolean
  showSwitchPoints?: boolean
  showLocationBand?: boolean
  scope?: 'active' | 'peer'
  active?: boolean
  focusTimestamp?: string
  initialViewport?: MeshChartViewport | null
  syncViewport?: MeshChartViewport | null
  lockedViewport?: MeshChartViewport | null
  preserveViewport?: boolean
  sharedTimeDomain?: MeshSharedTimeDomain | null
  chartId?: Exclude<MeshRssiChartSource, 'trackside-rssi' | 'programmatic'>
  syncPointerTime?: string | null
  syncPointerSource?: MeshRssiChartSource | null
}>(), { events: () => [], locationSegments: () => [], showPeer: false, showSwitchLines: false, showSwitchPoints: true, showLocationBand: true, scope: 'active', active: true, focusTimestamp: '', initialViewport: null, syncViewport: null, lockedViewport: null, preserveViewport: true, sharedTimeDomain: null, chartId: 'active-rssi', syncPointerTime: null, syncPointerSource: null })
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
let primarySeriesData: Array<{ value: [string, number | null]; meta: MeshChartPoint }> = []
let initialization: Promise<boolean> | null = null
let resizeFrame: number | null = null
let pendingRenderReason: 'data' | 'display' | 'theme' | 'reset' | null = null
let disposed = false
let currentViewport: MeshChartViewport | null = null
let viewportReady = false
let viewportFrame: number | null = null
let pendingViewport: MeshChartViewport | null = null
let pointerGlobalOut: (() => void) | null = null

const timestamps = (): string[] => props.points.map((point) => point.timestamp)
const pointCount = (): number => props.points.length
const fullViewport = (source: MeshChartViewport['source'] = 'initial'): MeshChartViewport | null => (
  props.sharedTimeDomain
    ? createFullMeshViewportFromDomain(props.sharedTimeDomain, source, props.chartId, currentViewport?.revision ?? 0)
    : createFullMeshViewport(timestamps(), source)
)

function renderedSwitchTimestamp(event: MeshChartEvent): string {
  return event.render_point_timestamp || event.point_timestamp || event.timestamp
}

function findRenderedSwitchPoint(event: MeshChartEvent): MeshChartPoint | undefined {
  if (event.render_aligned === false) return undefined
  const timestamp = renderedSwitchTimestamp(event)
  const context = event.point_context
  return props.points.find((point) => (
    point.timestamp === timestamp
    && (context?.link_id == null || point.link_id === context.link_id)
    && (context?.timestamp_tag == null || point.timestamp_tag === context.timestamp_tag)
    && (event.local_radio == null || point.local_radio === event.local_radio)
    && point.local_rssi != null
    && point.local_rssi !== 0
    && !point.is_anomaly
  ))
}

function switchNodeData(events: MeshChartEvent[]): Array<{ value: [string, number]; meta?: MeshChartPoint; meshEvent: MeshChartEvent; symbol: string }> {
  return events.flatMap((event) => {
    const point = findRenderedSwitchPoint(event)
    if (!point || point.local_rssi == null) return []
    return [{
      value: [point.timestamp, point.local_rssi],
      meta: point,
      meshEvent: event,
      symbol: event.after_rssi != null && point.local_rssi === event.after_rssi ? 'circle' : 'emptyCircle',
    }]
  })
}

function hasRenderableSize(): boolean {
  return Boolean(container.value && container.value.clientWidth > 0 && container.value.clientHeight > 0)
}

async function ensureChart(): Promise<boolean> {
  if (chart) return true
  if (!props.active || !hasRenderableSize() || disposed) return false
  if (initialization) return initialization
  initialization = (async () => {
    const [core, charts, components, renderers] = await Promise.all([
      import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
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
    chart = core.init(container.value, undefined, createTimeChartInitOptions(pointCount()))
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
      focusCurrentPoint()
    })
  })
}

function handleWindowResize(): void { scheduleChartUpdate() }

onMounted(() => {
  disposed = false
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

watch(() => props.points, () => scheduleChartUpdate('data'))
watch(() => [props.events, props.locationSegments] as const, () => scheduleChartUpdate('data'))
watch(() => [props.showPeer, props.showSwitchLines, props.showSwitchPoints, props.showLocationBand] as const, () => scheduleChartUpdate('display'))
watch(() => props.scope, () => { currentViewport = null; viewportReady = false; scheduleChartUpdate('reset') })
watch(() => props.active, (active) => { if (active) void nextTick(() => scheduleChartUpdate(pendingRenderReason || 'resize')) })
watch(() => props.focusTimestamp, () => { void nextTick(() => scheduleChartUpdate()) })
watch(() => props.lockedViewport, (viewport, previous) => {
  if (viewport) void nextTick(() => applyViewport(viewport))
  else if (previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })
watch(() => props.initialViewport, (viewport) => { if (viewport && !currentViewport) void nextTick(() => applyViewport(viewport)) }, { deep: true })
watch(() => props.syncViewport, (viewport) => {
  if (viewport && !meshViewportRangeEquals(currentViewport, viewport)) void nextTick(() => applyViewport(viewport))
}, { deep: true })
watch(() => props.sharedTimeDomain, () => scheduleChartUpdate('display'), { deep: true })
watch(() => [props.syncPointerTime, props.syncPointerSource] as const, ([time, source]) => {
  if (source !== props.chartId) void nextTick(() => applySharedPointer(time))
})

function handleChartClick(raw: unknown): void {
  const data = (raw as { data?: { meshEvent?: MeshChartEvent; meta?: MeshChartPoint } }).data
  const event = data?.meshEvent || props.events.find((item) => (
    (item.render_point_timestamp || item.point_timestamp) === data?.meta?.timestamp
    || item.timestamp === data?.meta?.timestamp
  ))
  if (event) emit('selectSwitch', event)
}

function focusCurrentPoint(): void {
  if (!props.focusTimestamp) return
  const dataIndex = primarySeriesData.findIndex((point) => point.meta.timestamp === props.focusTimestamp && point.value[1] !== null)
  if (dataIndex >= 0) chart?.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex })
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

function render(reason: 'data' | 'display' | 'theme' | 'reset'): void {
  if (!chart) return
  const previous = reason !== 'reset' && props.preserveViewport ? getViewport() : null
  const theme = readNetConsoleChartTokens()
  const series = buildMeshRssiSeries(props.points, props.showPeer, props.scope)
  primarySeriesData = series[0]?.data || []
  const switchEvents = props.events.filter((event) => event.event_type === 'ACTIVE_SWITCH')
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
  } : undefined
  const target = props.lockedViewport || previous || props.initialViewport || fullViewport()
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, {
    unit: 'dBm',
    pointCount: pointCount(),
    fullDomain: props.sharedTimeDomain,
    viewport: target,
  })
  chart.setOption({
    ...baseOption,
    color: [theme.primary, theme.info, theme.warning, theme.danger],
    tooltip: {
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
        const eventParam = params.find((item) => (item as { data?: { meshEvent?: MeshChartEvent } }).data?.meshEvent) as { data?: { meshEvent?: MeshChartEvent; meta?: MeshChartPoint } } | undefined
        const pointParam = params.find((item) => {
          const point = (item as { data?: { meta?: MeshChartPoint } }).data?.meta
          return point && (pointerMillis === null || meshTimestampMillis(point.timestamp) === pointerMillis)
        }) as { data?: { meta?: MeshChartPoint } } | undefined
        const event = eventParam?.data?.meshEvent
        const point = pointParam?.data?.meta
          || eventParam?.data?.meta
          || (event ? findRenderedSwitchPoint(event) : undefined)
        const exactPoint = point && (pointerMillis === null || meshTimestampMillis(point.timestamp) === pointerMillis)
          ? point
          : undefined
        return buildMeshRssiTooltip(exactPoint, event, pointerTime)
      },
    },
    yAxis: { ...(baseOption.yAxis as Record<string, unknown>), min: 'dataMin' },
    series: [
      ...series.map((item, index) => ({
      id: item.metric,
      name: item.name,
      type: 'line',
      ...createTimeChartLinePresentation(pointCount()),
      connectNulls: false,
      data: item.data,
      markArea: index === 0 ? markArea : undefined,
      markLine: index === 0 && props.showSwitchLines && switchEvents.length ? {
        silent: false,
        symbol: 'none',
        label: { show: false },
        lineStyle: { color: theme.warning, type: 'dashed' },
        data: switchEvents.map((event) => ({
          name: renderedSwitchTimestamp(event),
          xAxis: renderedSwitchTimestamp(event),
          meshEvent: event,
        })),
      } : undefined,
      })),
      ...(nodes.length ? [{
        name: '切换节点',
        type: 'scatter',
        symbolSize: 10,
        data: nodes.map((node) => ({ ...node, itemStyle: { color: theme.danger } })),
      }] : []),
    ],
  }, { replaceMerge: ['series'] })
  if (target) {
    applyViewport(target)
    if (!viewportReady && currentViewport) {
      viewportReady = true
      emit('viewport-ready', { ...currentViewport })
    }
  }
  focusCurrentPoint()
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
    <el-empty v-if="!points.length" class="empty" description="暂无 RSSI 数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; height: 100%; min-height: 360px; width: 100%; }
.chart { height: 100%; min-height: 360px; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
