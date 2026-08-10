<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import {
  createMultiSeriesTimeChartBaseOption,
  createTimeChartInitOptions,
  createTimeChartLinePresentation,
} from '../charts/multiSeriesTimeChart'
import {
  formatMeshViewportTimestamp,
  normalizeMeshViewport,
  viewportFromDataZoomWithOptions,
  type MeshChartViewport,
  type MeshSharedPointerChange,
  type MeshSharedTimeDomain,
} from '../mesh-analysis/meshChartViewport'
import type { OnlineMrMetricSeries } from '../../types/onlineMr'
import { buildTimelineTooltip, timelineTooltipPosition, type TimelineTooltipKind, type TimelineTooltipRow } from '../rail-timeline/timelineTooltip'

const props = withDefaults(defineProps<{
  series: OnlineMrMetricSeries[]
  title?: string
  unit?: string
  events?: Array<{ time: string; label: string; severity?: string }>
  viewport?: MeshChartViewport | null
  cursorTime?: string | null
  selectedTime?: string | null
  sharedTimeDomain?: MeshSharedTimeDomain | null
  tooltipKind?: TimelineTooltipKind
  active?: boolean
}>(), {
  title: '',
  unit: '',
  events: () => [],
  viewport: null,
  cursorTime: null,
  selectedTime: null,
  sharedTimeDomain: null,
  tooltipKind: 'generic',
  active: true,
})
const emit = defineEmits<{
  'update:viewport': [viewport: MeshChartViewport]
  'pointer-change': [pointer: MeshSharedPointerChange]
  'select-time': [time: string]
}>()

const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let applyingViewport = false
let pointerGlobalOut: (() => void) | null = null

const pointCount = (): number => props.series.reduce((total, item) => total + item.points.length, 0)
const timestamps = (): string[] => props.series.flatMap((item) => item.points.flatMap((point) => point.timestamp ? [point.timestamp] : []))

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  core.use([
    charts.LineChart,
    components.GridComponent,
    components.LegendComponent,
    components.TooltipComponent,
    components.DataZoomComponent,
    components.MarkLineComponent,
    components.MarkPointComponent,
    components.ToolboxComponent,
    components.TitleComponent,
    renderers.CanvasRenderer,
  ])
  await nextTick()
  if (!container.value) return
  chart = core.init(container.value, undefined, createTimeChartInitOptions(pointCount(), {
    // Dynamic timelines frequently repaint while the pointer, viewport and metric change.
    // Dirty-rectangle compositing can leave stale white rectangles over the canvas.
    useDirtyRect: false,
  }))
  chart.on('datazoom', handleDataZoom)
  chart.on('click', handleChartClick)
  chart.on('updateAxisPointer', handleAxisPointer)
  pointerGlobalOut = () => emit('pointer-change', { time: null, source_chart: 'timeline-metric' })
  chart.getZr().on('globalout', pointerGlobalOut)
  unsubscribeTheme = subscribeNetConsoleChartTheme(render)
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize)
  resizeObserver?.observe(container.value)
  window.addEventListener('resize', resize)
  render()
  await nextTick(() => {
    applyViewport(props.viewport)
    applyPointer(props.cursorTime || props.selectedTime)
    resize()
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  resizeObserver?.disconnect()
  resizeObserver = null
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.off('datazoom', handleDataZoom)
  chart?.off('click', handleChartClick)
  chart?.off('updateAxisPointer', handleAxisPointer)
  if (pointerGlobalOut) chart?.getZr().off('globalout', pointerGlobalOut)
  pointerGlobalOut = null
  chart?.dispose()
  chart = null
})

watch(() => [props.series, props.events, props.selectedTime], () => {
  render()
  void nextTick(() => {
    applyViewport(props.viewport)
    applyPointer(props.cursorTime || props.selectedTime)
    resize()
  })
}, { deep: true })
watch(() => props.viewport, (value) => { if (props.active) void nextTick(() => applyViewport(value)) }, { deep: true })
watch(() => props.active, (active) => {
  if (!active) chart?.dispatchAction({ type: 'hideTip' }, { silent: true })
})
watch(() => [props.cursorTime, props.selectedTime] as const, ([cursor, selected]) => {
  if (props.active) void nextTick(() => applyPointer(cursor || selected))
})

function resize(): void {
  if (container.value?.clientWidth && chart) {
    chart.dispatchAction({ type: 'hideTip' }, { silent: true })
    chart.resize()
  }
}

function applyViewport(viewport: MeshChartViewport | null | undefined): void {
  if (!chart || !viewport) return
  const normalized = normalizeMeshViewport(viewport, [], 'programmatic', {
    boundaryMode: 'absolute',
    fullDomain: props.sharedTimeDomain || viewport,
    sourceChart: 'timeline-metric',
    revision: viewport.revision,
  })
  if (!normalized) return
  applyingViewport = true
  chart.dispatchAction({
    type: 'dataZoom',
    batch: [0, 1].map((dataZoomIndex) => ({
      dataZoomIndex,
      startValue: normalized.start_time,
      endValue: normalized.end_time,
    })),
    silent: true,
  })
  applyingViewport = false
}

function applyPointer(time: string | null | undefined): void {
  if (!chart || !time) return
  chart.dispatchAction({ type: 'showTip', xAxisIndex: 0, value: time, silent: true })
}

function handleDataZoom(raw: unknown): void {
  if (!props.active || applyingViewport) return
  const domain = props.sharedTimeDomain
  const viewport = viewportFromDataZoomWithOptions(raw, timestamps(), domain ? {
    boundaryMode: 'absolute',
    fullDomain: domain,
    sourceChart: 'timeline-metric',
  } : {})
  if (viewport) emit('update:viewport', viewport)
}

function handleChartClick(raw: unknown): void {
  if (!props.active) return
  const value = (raw as { value?: [string | number, number | null]; data?: { value?: [string | number, number | null] } }).value
    || (raw as { data?: { value?: [string | number, number | null] } }).data?.value
  const timestamp = value?.[0]
  if (typeof timestamp === 'string') emit('select-time', timestamp)
  else if (typeof timestamp === 'number') emit('select-time', formatMeshViewportTimestamp(timestamp))
}

function handleAxisPointer(raw: unknown): void {
  if (!props.active) return
  const value = (raw as { axesInfo?: Array<{ value?: string | number }> }).axesInfo?.[0]?.value
  const time = typeof value === 'string'
    ? value
    : typeof value === 'number'
      ? formatMeshViewportTimestamp(value)
      : null
  emit('pointer-change', { time, source_chart: 'timeline-metric' })
}

function render(): void {
  if (!chart) return
  chart.dispatchAction({ type: 'hideTip' }, { silent: true })
  const theme = readNetConsoleChartTokens()
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, {
    title: props.title,
    unit: props.unit,
    pointCount: pointCount(),
    fullDomain: props.sharedTimeDomain,
    viewport: props.viewport,
  })
  const events = props.events.filter((event) => event.time)
  const selectedLine = props.selectedTime ? [{
    xAxis: props.selectedTime,
    name: '当前分析时刻',
    lineStyle: { color: theme.primary, type: 'solid', width: 2 },
  }] : []
  const eventLines = events.map((event) => ({
    xAxis: event.time,
    name: event.label,
    lineStyle: { color: event.severity === 'error' ? theme.danger : theme.warning, type: 'dashed' },
  }))
  const chartSeries = props.series.map((item, index) => {
    const lossPoints = item.metric_type === 'ping_loss'
      ? item.points.filter((point) => point.timestamp && (point.value || 0) > 0)
      : []
    return {
      id: `${item.metric_type}:${item.series_key || index}`,
      name: seriesDisplayName(item, index),
      type: 'line',
      ...createTimeChartLinePresentation(pointCount()),
      connectNulls: false,
      data: item.points.map((point) => ({ value: [point.timestamp, point.value], dimensions: point.dimensions, point, metricType: item.metric_type })),
      markLine: index === 0 && (selectedLine.length || eventLines.length) ? {
        symbol: 'none',
        label: { show: false },
        data: [...selectedLine, ...eventLines],
      } : undefined,
      markPoint: lossPoints.length ? {
        symbol: 'pin',
        symbolSize: 24,
        label: { show: false },
        itemStyle: { color: theme.danger },
        data: lossPoints.map((point) => ({ coord: [point.timestamp, point.value], name: '丢包' })),
      } : undefined,
    }
  })
  chart.setOption({
    ...baseOption,
    tooltip: {
      ...(baseOption.tooltip as Record<string, unknown>),
      renderMode: 'html',
      appendToBody: false,
      confine: true,
      transitionDuration: 0,
      position: timelineTooltipPosition,
      extraCssText: 'box-sizing:border-box;width:max-content;max-width:min(360px,calc(100% - 24px));max-height:min(240px,calc(100% - 24px));overflow:auto;pointer-events:none;white-space:normal;',
      formatter: (raw: unknown) => buildTimelineTooltip(props.tooltipKind, (Array.isArray(raw) ? raw : [raw]) as TimelineTooltipRow[]),
    },
    yAxis: {
      ...(baseOption.yAxis as Record<string, unknown>),
      ...(props.tooltipKind === 'ping-loss' || props.tooltipKind === 'channel-busy' || props.tooltipKind === 'traffic-loss' ? { min: 0, max: 100 } : {}),
    },
    series: chartSeries,
  }, { replaceMerge: ['series', 'dataZoom'] })
}

function seriesDisplayName(item: OnlineMrMetricSeries, index: number): string {
  const point = item.points.find((value) => value.dimensions)
  const dimensions = point?.dimensions || {}
  if (props.tooltipKind === 'channel-busy') return dimensions.radio == null ? `信道繁忙度 ${index + 1}` : `Radio ${dimensions.radio}`
  if (props.tooltipKind === 'interface') return String(dimensions.interface_normalized || dimensions.interface_name || item.series_key || '接口')
  if (props.tooltipKind.startsWith('traffic')) return String(dimensions.direction === 'upload' ? '上行' : dimensions.direction === 'download' ? '下行' : item.series_key || '吞吐')
  if (props.tooltipKind === 'ping-loss' || props.tooltipKind === 'ping-rtt') return String(dimensions.target_ip || dimensions.target_name || item.series_key || '目标')
  return item.series_key || '默认序列'
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!series.some((item) => item.points.some((point) => point.value !== null || point.text_value))" class="empty" description="暂无可用数据" :image-size="58" />
  </div>
</template>

<style scoped>
.chart-shell{position:relative;min-width:0;min-height:0;width:100%;height:100%}
.chart{width:100%;height:100%;min-width:0;min-height:0}
.empty{position:absolute;inset:0;pointer-events:none}
</style>
