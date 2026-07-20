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
import type { MeshChartBackupLink, MeshChartEvent, MeshChartPoint } from '../../types/meshAnalysis'
import { buildMeshRssiSeries } from './chartSeries'

const props = withDefaults(defineProps<{
  points: MeshChartPoint[]
  events?: MeshChartEvent[]
  showPeer?: boolean
  scope?: 'active' | 'peer'
  active?: boolean
  focusTimestamp?: string
}>(), { events: () => [], showPeer: false, scope: 'active', active: true, focusTimestamp: '' })
const emit = defineEmits<{ selectSwitch: [event: MeshChartEvent] }>()

const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let primarySeriesData: Array<{ value: [string, number | null]; meta: MeshChartPoint }> = []

function escapeHtml(value: unknown): string {
  return String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)
}

function metric(value: number | null | undefined, unit = ''): string {
  return value == null ? '—' : `${value}${unit}`
}

function backupLines(backups: MeshChartBackupLink[]): string[] {
  if (!backups.length) return ['同采样点备链：无']
  return [
    `同采样点备链（${backups.length}）：`,
    ...backups.map((item) => `· ${escapeHtml(item.peer_ap_name || item.peer_mac)} / Radio ${escapeHtml(item.local_radio)} / MR RSSI ${metric(item.local_rssi)}`),
  ]
}

function tooltip(point: MeshChartPoint | undefined): string {
  if (!point) return '暂无采样上下文'
  return [
    `采样时间：${escapeHtml(point.timestamp)}`,
    `采样标识：${escapeHtml(point.timestamp_tag)}`,
    `当前 AP：${escapeHtml(point.peer_ap_name)}`,
    `AP MAC：${escapeHtml(point.peer_ap_mac)}`,
    `Peer MAC：${escapeHtml(point.peer_mac)}`,
    `Radio / Peer Radio：${escapeHtml(point.local_radio)} / ${escapeHtml(point.peer_radio)}`,
    `MR / Peer RSSI：${metric(point.local_rssi)} / ${metric(point.peer_rssi)}`,
    `MR / Peer 接收信号：${metric(point.local_signal, ' dBm')} / ${metric(point.peer_signal, ' dBm')}`,
    `归属站点 / 区间：${escapeHtml(point.station)} / ${escapeHtml(point.section)}`,
    `建链持续：${metric(point.segment_duration_seconds, ' s')}`,
    `当前区段：${escapeHtml(point.segment_sequence)}`,
    ...backupLines(point.backups || []),
  ].join('<br>')
}

async function initialize(): Promise<void> {
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
    components.ToolboxComponent,
    renderers.CanvasRenderer,
  ])
  await nextTick()
  if (!container.value) return
  chart = core.init(container.value)
  chart.on('click', handleChartClick)
  unsubscribeTheme = subscribeNetConsoleChartTheme(render)
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    if (container.value && container.value.clientWidth > 0) chart?.resize()
  })
  resizeObserver?.observe(container.value)
  render()
  window.addEventListener('resize', resize)
  await nextTick()
  resize()
}

onMounted(initialize)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  resizeObserver?.disconnect()
  resizeObserver = null
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.off('click', handleChartClick)
  chart?.dispose()
  chart = null
})

watch(() => [props.points, props.events, props.showPeer, props.scope] as const, () => {
  render()
  void nextTick(resize)
}, { deep: true })
watch(() => props.active, (active) => { if (active) void nextTick(resize) })
watch(() => props.focusTimestamp, () => { void nextTick(focusCurrentPoint) })

function resize(): void { chart?.resize() }

function handleChartClick(raw: unknown): void {
  const data = (raw as { data?: { meshEvent?: MeshChartEvent; meta?: MeshChartPoint } }).data
  const event = data?.meshEvent || props.events.find((item) => item.timestamp === data?.meta?.timestamp)
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
    yAxis: { type: 'value', name: 'RSSI', nameTextStyle: { color: theme.textSecondary }, min: 'dataMin', ...axisStyle },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      { type: 'slider', height: 18, bottom: 28, filterMode: 'none', ...createNetConsoleDataZoomStyle(theme) },
    ],
    series: series.map((item, index) => ({
      name: item.name,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      data: item.data,
      markLine: index === 0 && switchEvents.length ? {
        silent: false,
        symbol: 'none',
        label: { show: false },
        lineStyle: { color: theme.warning, type: 'dashed' },
        data: switchEvents.map((event) => ({ name: event.timestamp, xAxis: event.timestamp, meshEvent: event })),
      } : undefined,
    })),
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
.chart-shell { position: relative; min-height: 380px; width: 100%; }
.chart { height: 430px; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
