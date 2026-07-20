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
import { buildMeshBusySeries, buildMeshLocationBands } from './chartSeries'

const props = withDefaults(defineProps<{ points: MeshChartPoint[]; events?: MeshChartEvent[]; locationSegments?: MeshLocationSegment[]; showPeer?: boolean; showLocationBand?: boolean; scope?: 'active' | 'peer'; active?: boolean }>(), { events: () => [], locationSegments: () => [], showPeer: false, showLocationBand: true, scope: 'active', active: true })
const emit = defineEmits<{ selectSwitch: [event: MeshChartEvent] }>()
const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let initialization: Promise<boolean> | null = null
let resizeFrame: number | null = null
let renderPending = false
let disposed = false

function escapeHtml(value: unknown): string {
  return String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)
}
function metric(value: number | null | undefined, unit = '%'): string { return value == null ? '—' : `${value}${unit}` }

function tooltip(point: MeshChartPoint | undefined): string {
  if (!point) return '暂无采样上下文'
  const backups = point.backups?.length
    ? point.backups.map((item) => `· ${escapeHtml(item.peer_ap_name || item.peer_mac)} / MR Tx ${metric(item.local_tx_busy)} / MR Rx ${metric(item.local_rx_busy)}`)
    : ['无']
  return [
    `采样时间：${escapeHtml(point.timestamp)}`,
    `当前 ACTIVE AP：${escapeHtml(point.peer_ap_name)}`,
    `Peer MAC / Radio：${escapeHtml(point.peer_mac)} / ${escapeHtml(point.local_radio)}`,
    `MR TxBusy / RxBusy：${metric(point.local_tx_busy)} / ${metric(point.local_rx_busy)}`,
    `Peer TxBusy / RxBusy：${metric(point.peer_tx_busy)} / ${metric(point.peer_rx_busy)}`,
    `MR / Peer RSSI：${metric(point.local_rssi, '')} / ${metric(point.peer_rssi, '')}`,
    `站点 / 区间：${escapeHtml(point.station)} / ${escapeHtml(point.section)}`,
    `同采样点备链：${backups.join('<br>')}`,
  ].join('<br>')
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
      charts.LineChart, components.GridComponent, components.LegendComponent, components.TooltipComponent,
      components.DataZoomComponent, components.MarkLineComponent, components.MarkAreaComponent, components.ToolboxComponent, renderers.CanvasRenderer,
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

watch(() => [props.points, props.events, props.locationSegments, props.showPeer, props.showLocationBand, props.scope] as const, () => scheduleChartUpdate(true), { deep: true })
watch(() => props.active, (active) => { if (active) void nextTick(() => scheduleChartUpdate(true)) })

function handleChartClick(raw: unknown): void {
  const data = (raw as { data?: { meshEvent?: MeshChartEvent; meta?: MeshChartPoint } }).data
  const event = data?.meshEvent || props.events.find((item) => item.timestamp === data?.meta?.timestamp)
  if (event) emit('selectSwitch', event)
}

function render(): void {
  if (!chart) return
  const theme = readNetConsoleChartTokens()
  const axisStyle = createNetConsoleAxisStyle(theme)
  const series = buildMeshBusySeries(props.points, props.showPeer, props.scope)
  const switchEvents = props.events.filter((event) => event.event_type === 'ACTIVE_SWITCH')
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
        return tooltip((params[0] as { data?: { meta?: MeshChartPoint } } | undefined)?.data?.meta)
      },
    },
    legend: { bottom: 4, textStyle: { color: theme.textSecondary } },
    toolbox: { right: 16, feature: { saveAsImage: { title: '保存图像', pixelRatio: 2 } } },
    grid: { left: 54, right: 22, top: 42, bottom: 74, containLabel: true },
    xAxis: { type: 'time', ...axisStyle },
    yAxis: { type: 'value', name: '繁忙度 (%)', min: 0, max: 100, nameTextStyle: { color: theme.textSecondary }, ...axisStyle },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      { type: 'slider', height: 18, bottom: 28, filterMode: 'none', ...createNetConsoleDataZoomStyle(theme) },
    ],
    series: series.map((item, index) => ({
      name: item.name, type: 'line', showSymbol: false, connectNulls: false, data: item.data,
      markArea: index === 0 ? markArea : undefined,
      markLine: index === 0 && switchEvents.length ? {
        silent: false, symbol: 'none', label: { show: false }, lineStyle: { color: theme.warning, type: 'dashed' },
        data: switchEvents.map((event) => ({ name: event.timestamp, xAxis: event.timestamp, meshEvent: event })),
      } : undefined,
    })),
  }, { notMerge: true })
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!points.length" class="empty" description="暂无 TxBusy / RxBusy 数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; height: 100%; min-height: 360px; width: 100%; }
.chart { height: 100%; min-height: 360px; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
