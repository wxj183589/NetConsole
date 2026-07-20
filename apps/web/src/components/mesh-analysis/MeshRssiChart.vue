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
}>(), { events: () => [], locationSegments: () => [], showPeer: false, showSwitchLines: false, showSwitchPoints: true, showLocationBand: true, scope: 'active', active: true, focusTimestamp: '' })
const emit = defineEmits<{ selectSwitch: [event: MeshChartEvent] }>()

const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let primarySeriesData: Array<{ value: [string, number | null]; meta: MeshChartPoint }> = []
let initialization: Promise<boolean> | null = null
let resizeFrame: number | null = null
let renderPending = false
let disposed = false

function switchNodeData(events: MeshChartEvent[]): Array<{ value: [string, number]; meta?: MeshChartPoint; meshEvent: MeshChartEvent; symbol: string }> {
  return events.flatMap((event) => {
    if (!event.point_timestamp || event.point_rssi == null) return []
    return [{
      value: [event.point_timestamp, event.point_rssi],
      meta: event.point_context || props.points.find((item) => item.timestamp === event.point_timestamp),
      meshEvent: event,
      symbol: event.after_rssi != null && event.point_rssi === event.after_rssi ? 'circle' : 'emptyCircle',
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
    unsubscribeTheme = subscribeNetConsoleChartTheme(() => scheduleChartUpdate(true))
    return true
  })().finally(() => { initialization = null })
  return initialization
}

function scheduleChartUpdate(renderOption = false): void {
  renderPending ||= renderOption
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    const shouldRender = renderPending
    renderPending = false
    if (!props.active || !hasRenderableSize() || disposed) return
    const chartExisted = Boolean(chart)
    void ensureChart().then((ready) => {
      if (!ready || !props.active || disposed) return
      if (shouldRender || !chartExisted) render()
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
  scheduleChartUpdate(true)
})
onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', handleWindowResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  resizeFrame = null
  renderPending = false
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.off('click', handleChartClick)
  chart?.dispose()
  chart = null
})

watch(() => [props.points, props.events, props.locationSegments, props.showPeer, props.showSwitchLines, props.showSwitchPoints, props.showLocationBand, props.scope] as const, () => {
  scheduleChartUpdate(true)
}, { deep: true })
watch(() => props.active, (active) => { if (active) void nextTick(() => scheduleChartUpdate(true)) })
watch(() => props.focusTimestamp, () => { void nextTick(() => scheduleChartUpdate()) })

function handleChartClick(raw: unknown): void {
  const data = (raw as { data?: { meshEvent?: MeshChartEvent; meta?: MeshChartPoint } }).data
  const event = data?.meshEvent || props.events.find((item) => item.point_timestamp === data?.meta?.timestamp || item.timestamp === data?.meta?.timestamp)
  if (event) emit('selectSwitch', event)
}

function focusCurrentPoint(): void {
  if (!props.focusTimestamp) return
  const dataIndex = primarySeriesData.findIndex((point) => point.meta.timestamp === props.focusTimestamp && point.value[1] !== null)
  if (dataIndex >= 0) chart?.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex })
}

function render(): void {
  if (!chart) return
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
          || event?.point_context
          || props.points.find((item) => item.timestamp === (event?.point_timestamp || event?.timestamp))
        return buildMeshRssiTooltip(point, event)
      },
    },
    legend: { bottom: 4, textStyle: { color: theme.textSecondary } },
    toolbox: { right: 16, feature: { saveAsImage: { title: '保存图像', pixelRatio: 2 } } },
    grid: { left: 54, right: 22, top: 42, bottom: 74, containLabel: true },
    xAxis: { type: 'time', ...axisStyle },
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
  focusCurrentPoint()
}
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
