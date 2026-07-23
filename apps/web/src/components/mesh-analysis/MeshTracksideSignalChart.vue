<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import {
  createNetConsoleAxisStyle,
  createNetConsoleDataZoomStyle,
  createNetConsoleLegendStyle,
  createNetConsoleTooltipStyle,
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import type {
  MeshChartEvent,
  MeshLocationSegment,
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import { buildMeshLocationBands } from './chartSeries'
import {
  createFullMeshViewport,
  normalizeMeshViewport,
  viewportFromDataZoom,
  type MeshChartViewport,
} from './meshChartViewport'
import { buildSwitchSection, escapeMeshTooltipHtml } from './meshRssiTooltip'

interface RenderedSignalPoint {
  value: [string, number | null]
  meta?: MeshTracksideSignalPointData
  seriesMeta?: MeshTracksideSignalSeriesData
}

interface RenderedSignalSeries {
  name: string
  data: RenderedSignalPoint[]
  meta: MeshTracksideSignalSeriesData
}

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
})
const emit = defineEmits<{
  selectSwitch: [event: MeshChartEvent]
  'viewport-change': [viewport: MeshChartViewport]
  'viewport-ready': [viewport: MeshChartViewport]
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
let applyingViewport = false
let viewportReady = false
let viewportTimer: ReturnType<typeof setTimeout> | null = null
let renderedSeries: RenderedSignalSeries[] = []

const timestamps = (): string[] => props.series.flatMap((item) => item.points.map((point) => point.timestamp))
const hasData = () => props.series.some((item) => item.points.some((point) => point.peer_rssi != null || point.peer_signal != null))

function sameViewport(left: MeshChartViewport | null, right: MeshChartViewport | null): boolean {
  return Boolean(left && right && left.start_time === right.start_time && left.end_time === right.end_time)
}

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

function pointSeriesValue(point: MeshTracksideSignalPointData): number | null {
  return point.peer_rssi ?? point.peer_signal ?? null
}

function renderSeries(): RenderedSignalSeries[] {
  return props.series.map((series) => ({
    name: seriesLabel(series),
    meta: series,
    data: (() => {
      const rendered: RenderedSignalPoint[] = []
      let previousRunId: string | null = null
      for (const point of [...series.points].sort((left, right) => left.timestamp.localeCompare(right.timestamp) || left.timestamp_tag.localeCompare(right.timestamp_tag))) {
        const currentRunId = point.run_id ?? (point.run_sequence == null ? null : `${series.series_id}:${point.run_sequence}`)
        if (
          rendered.length
          && point.break_before
          && (currentRunId == null || currentRunId !== previousRunId)
        ) {
          rendered.push({ value: [point.timestamp, null] })
        }
        rendered.push({
          value: [point.timestamp, pointSeriesValue(point)],
          meta: point,
          seriesMeta: series,
        })
        previousRunId = currentRunId
      }
      return rendered
    })(),
  }))
}

function findRenderedSwitchPoint(event: MeshChartEvent): RenderedSignalPoint | undefined {
  if (event.render_aligned === false) return undefined
  const timestamp = event.render_point_timestamp || event.point_timestamp || event.timestamp
  if (!timestamp) return undefined
  const context = event.point_context
  const exactMatch = renderedSeries.flatMap((item) => item.data).find((point) => (
    Boolean(point.meta)
    && point.value[0] === timestamp
    && (context?.link_id == null || point.meta!.link_id === context.link_id)
    && (context?.timestamp_tag == null || point.meta!.timestamp_tag === context.timestamp_tag)
    && (event.local_radio == null || point.meta!.local_radio === event.local_radio)
    && pointSeriesValue(point.meta!) != null
    && pointSeriesValue(point.meta!) !== 0
  ))
  if (exactMatch) return exactMatch
  return renderedSeries.flatMap((item) => item.data).find((point) => (
    Boolean(point.meta)
    && point.value[0] === timestamp
    && (event.local_radio == null || point.meta!.local_radio === event.local_radio)
    && pointSeriesValue(point.meta!) != null
    && pointSeriesValue(point.meta!) !== 0
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
    `轨旁侧 RSSI：${metric(point.value[1])}`,
    `MR 侧 RSSI（参考）：${metric(meta.local_rssi)}`,
    `Peer Signal / MR Signal：${metric(meta.peer_signal)} / ${metric(meta.local_signal)}`,
    `站点 / 区间：${escapeMeshTooltipHtml(meta.station)} / ${escapeMeshTooltipHtml(meta.section)}`,
    '链路状态：ACTIVE',
    `建链持续时间：${metric(meta.segment_duration_seconds, ' s')}`,
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

function buildTooltip(points: RenderedSignalPoint[], event?: MeshChartEvent): string {
  if (!points.length) {
    return `<div class="mesh-trackside-signal-tooltip" style="min-width:280px;max-width:420px;white-space:normal;overflow-wrap:anywhere;line-height:1.6">采样时间：${escapeMeshTooltipHtml(event?.render_point_timestamp || event?.point_timestamp || event?.timestamp)}${buildSwitchSection(event)}</div>`
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
    chart = core.init(container.value)
    chart.on('click', handleChartClick)
    chart.on('datazoom', handleDataZoom)
    chart.on('restore', handleRestore)
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
    })
  })
}

function handleWindowResize(): void {
  scheduleChartUpdate()
}

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
  chart?.off('restore', handleRestore)
  chart?.dispose()
  chart = null
})

watch(() => props.series, () => scheduleChartUpdate('data'), { deep: true })
watch(() => [props.events, props.locationSegments] as const, () => scheduleChartUpdate('data'), { deep: true })
watch(() => [props.showSwitchLines, props.showSwitchPoints, props.showLocationBand] as const, () => scheduleChartUpdate('display'))
watch(() => props.active, (active) => { if (active) void nextTick(() => scheduleChartUpdate(pendingRenderReason || 'resize')) })
watch(() => props.lockedViewport, (viewport, previous) => {
  if (viewport) void nextTick(() => applyViewport(viewport))
  else if (previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })
watch(() => props.initialViewport, (viewport) => { if (viewport && !currentViewport) void nextTick(() => applyViewport(viewport)) }, { deep: true })
watch(() => props.syncViewport, (viewport, previous) => {
  if (viewport && !sameViewport(currentViewport, viewport)) void nextTick(() => applyViewport(viewport))
  else if (!viewport && previous) { currentViewport = null; scheduleChartUpdate('reset') }
}, { deep: true })

function handleChartClick(raw: unknown): void {
  const data = (raw as { data?: { meshEvent?: MeshChartEvent; meta?: MeshTracksideSignalPointData } }).data
  const event = data?.meshEvent || props.events.find((item) => (
    (item.render_point_timestamp || item.point_timestamp || item.timestamp) === data?.meta?.timestamp
    || item.timestamp === data?.meta?.timestamp
  ))
  if (event) emit('selectSwitch', event)
}

function handleDataZoom(raw: unknown): void {
  if (applyingViewport) return
  const viewport = viewportFromDataZoom(raw, timestamps())
  if (!viewport) return
  currentViewport = viewport
  if (viewportTimer) clearTimeout(viewportTimer)
  viewportTimer = setTimeout(() => emit('viewport-change', { ...viewport }), 100)
}

function handleRestore(): void {
  const viewport = createFullMeshViewport(timestamps(), 'user_zoom')
  if (!viewport) return
  currentViewport = viewport
  emit('viewport-change', { ...viewport })
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
  renderedSeries = renderSeries()
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
    color: theme.series,
    textStyle: { color: theme.text },
    tooltip: {
      trigger: 'axis',
      ...createNetConsoleTooltipStyle(theme),
      formatter: (rawParams: unknown) => {
        const params = Array.isArray(rawParams) ? rawParams : [rawParams]
        const eventParam = params.find((item) => (item as { data?: { meshEvent?: MeshChartEvent } }).data?.meshEvent) as { data?: { meshEvent?: MeshChartEvent } } | undefined
        const event = eventParam?.data?.meshEvent
        const seen = new Set<string>()
        const pointItems = params.flatMap((item) => {
          const candidate = item as { data?: RenderedSignalPoint }
          const point = candidate.data
          if (!point?.meta || !point.seriesMeta || !Array.isArray(point.value) || point.value[1] == null) return []
          const key = renderedPointKey(point)
          if (!key || seen.has(key)) return []
          seen.add(key)
          return [point]
        }).slice(0, 8)
        return buildTooltip(pointItems, event)
      },
    },
    legend: { type: 'scroll', bottom: 4, ...createNetConsoleLegendStyle(theme) },
    toolbox: {
      right: 16,
      feature: {
        dataZoom: { yAxisIndex: 'none', title: { zoom: '框选缩放', back: '还原缩放' } },
        restore: { title: '恢复视图' },
        saveAsImage: { title: '保存图像', pixelRatio: 2 },
      },
    },
    grid: { left: 54, right: 22, top: 24, bottom: 74, containLabel: true },
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
      ...renderedSeries.map((item, index) => ({
        name: item.name,
        type: 'line',
        showSymbol: item.data.filter((point) => point.value[1] != null).length < 120,
        connectNulls: false,
        data: item.data,
        lineStyle: { width: 2, type: 'solid' },
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
  const target = props.lockedViewport || previous || props.syncViewport || props.initialViewport || createFullMeshViewport(timestamps())
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
