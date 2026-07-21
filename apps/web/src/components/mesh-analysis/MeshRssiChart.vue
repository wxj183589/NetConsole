<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import {
  createNetConsoleAxisStyle,
  createNetConsoleDataZoomStyle,
  createNetConsoleTooltipStyle,
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import type { MeshChartEvent, MeshChartPoint, MeshLocationSegment } from '../../types/meshAnalysis'
import { buildMeshLocationBands, buildMeshRssiSeries } from './chartSeries'
import {
  createFullMeshViewport,
  normalizeMeshViewport,
  viewportFromDataZoom,
  type MeshChartViewport,
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
  lockedViewport?: MeshChartViewport | null
  preserveViewport?: boolean
}>(), { events: () => [], locationSegments: () => [], showPeer: false, showSwitchLines: false, showSwitchPoints: true, showLocationBand: true, scope: 'active', active: true, focusTimestamp: '', initialViewport: null, lockedViewport: null, preserveViewport: true })
const emit = defineEmits<{
  selectSwitch: [event: MeshChartEvent]
  'viewport-change': [viewport: MeshChartViewport]
  'viewport-ready': [viewport: MeshChartViewport]
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
let applyingViewport = false
let viewportReady = false
let viewportTimer: ReturnType<typeof setTimeout> | null = null

const timestamps = (): string[] => props.points.map((point) => point.timestamp)

function findRenderedSwitchPoint(event: MeshChartEvent): MeshChartPoint | undefined {
  if (event.render_aligned === false) return undefined
  const timestamp = event.render_point_timestamp || event.point_timestamp
  if (!timestamp) return undefined
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
    chart = core.init(container.value)
    chart.on('click', handleChartClick)
    chart.on('datazoom', handleDataZoom)
    unsubscribeTheme = subscribeNetConsoleChartTheme(() => scheduleChartUpdate('theme'))
    return true
  })().finally(() => { initialization = null })
  return initialization
}

function scheduleChartUpdate(reason: 'data' | 'display' | 'theme' | 'reset' | 'resize' = 'resize'): void {
  if (reason !== 'resize') pendingRenderReason = reason
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
  if (viewportTimer) clearTimeout(viewportTimer)
  viewportTimer = null
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.off('click', handleChartClick)
  chart?.off('datazoom', handleDataZoom)
  chart?.dispose()
  chart = null
})

watch(() => props.points, () => scheduleChartUpdate('data'), { deep: true })
watch(() => [props.events, props.locationSegments] as const, () => scheduleChartUpdate('data'), { deep: true })
watch(() => [props.showPeer, props.showSwitchLines, props.showSwitchPoints, props.showLocationBand] as const, () => scheduleChartUpdate('display'))
watch(() => props.scope, () => { currentViewport = null; viewportReady = false; scheduleChartUpdate('reset') })
watch(() => props.active, (active) => { if (active) void nextTick(() => scheduleChartUpdate(pendingRenderReason || 'resize')) })
watch(() => props.focusTimestamp, () => { void nextTick(() => scheduleChartUpdate()) })
watch(() => props.lockedViewport, (viewport, previous) => {
  if (viewport) void nextTick(() => applyViewport(viewport))
  else if (previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })
watch(() => props.initialViewport, (viewport) => { if (viewport && !currentViewport) void nextTick(() => applyViewport(viewport)) }, { deep: true })

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
  if (applyingViewport) return
  const viewport = viewportFromDataZoom(raw, timestamps())
  if (!viewport) return
  currentViewport = viewport
  if (viewportTimer) clearTimeout(viewportTimer)
  viewportTimer = setTimeout(() => emit('viewport-change', { ...viewport }), 100)
}

function getViewport(): MeshChartViewport | null {
  return currentViewport ? { ...currentViewport } : createFullMeshViewport(timestamps())
}

function applyViewport(viewport: MeshChartViewport): void {
  const isLocked = Boolean(props.lockedViewport
    && props.lockedViewport.start_time === viewport.start_time
    && props.lockedViewport.end_time === viewport.end_time)
  const normalized = normalizeMeshViewport(viewport, isLocked ? [] : timestamps(), 'programmatic')
  if (!normalized) return
  currentViewport = normalized
  if (!chart) return
  applyingViewport = true
  chart.dispatchAction({
    type: 'dataZoom',
    batch: [0, 1].map((dataZoomIndex) => ({ dataZoomIndex, startValue: normalized.start_time, endValue: normalized.end_time })),
  })
  queueMicrotask(() => { applyingViewport = false })
}

function resetViewport(): void {
  const target = props.lockedViewport || createFullMeshViewport(timestamps())
  if (target) applyViewport(target)
}

function render(reason: 'data' | 'display' | 'theme' | 'reset'): void {
  if (!chart) return
  const previous = reason !== 'reset' && props.preserveViewport ? getViewport() : null
  const theme = readNetConsoleChartTokens()
  const axisStyle = createNetConsoleAxisStyle(theme)
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
  chart.setOption({
    animation: false,
    color: [theme.primary, theme.info, theme.warning, theme.danger],
    textStyle: { color: theme.text },
    tooltip: {
      trigger: 'axis',
      ...createNetConsoleTooltipStyle(theme),
      formatter: (rawParams: unknown) => {
        const params = Array.isArray(rawParams) ? rawParams : [rawParams]
        const eventParam = params.find((item) => (item as { data?: { meshEvent?: MeshChartEvent } }).data?.meshEvent) as { data?: { meshEvent?: MeshChartEvent; meta?: MeshChartPoint } } | undefined
        const pointParam = params.find((item) => (item as { data?: { meta?: MeshChartPoint } }).data?.meta) as { data?: { meta?: MeshChartPoint } } | undefined
        const event = eventParam?.data?.meshEvent
        const point = pointParam?.data?.meta
          || eventParam?.data?.meta
          || (event ? findRenderedSwitchPoint(event) : undefined)
        return buildMeshRssiTooltip(point, event)
      },
    },
    legend: { bottom: 4, textStyle: { color: theme.textSecondary } },
    toolbox: { right: 16, feature: { saveAsImage: { title: '保存图像', pixelRatio: 2 } } },
    grid: { left: 54, right: 22, top: 42, bottom: 74, containLabel: true },
    xAxis: {
      type: 'time',
      min: props.lockedViewport?.start_time,
      max: props.lockedViewport?.end_time,
      ...axisStyle,
    },
    yAxis: { type: 'value', name: 'RSSI', nameTextStyle: { color: theme.textSecondary }, min: 'dataMin', ...axisStyle },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      { type: 'slider', height: 18, bottom: 28, filterMode: 'none', ...createNetConsoleDataZoomStyle(theme) },
    ],
    series: [
      ...series.map((item, index) => ({
      name: item.name,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      data: item.data,
      markArea: index === 0 ? markArea : undefined,
      markLine: index === 0 && props.showSwitchLines && switchEvents.length ? {
        silent: false,
        symbol: 'none',
        label: { show: false },
        lineStyle: { color: theme.warning, type: 'dashed' },
        data: switchEvents.map((event) => ({ name: event.timestamp, xAxis: event.timestamp, meshEvent: event })),
      } : undefined,
      })),
      ...(nodes.length ? [{
        name: '切换节点',
        type: 'scatter',
        symbolSize: 10,
        data: nodes.map((node) => ({ ...node, itemStyle: { color: theme.danger } })),
      }] : []),
    ],
  }, { notMerge: true })
  const target = props.lockedViewport || previous || props.initialViewport || createFullMeshViewport(timestamps())
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
