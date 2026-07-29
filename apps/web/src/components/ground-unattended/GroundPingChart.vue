<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import type { GroundPingSample, GroundPingSeries } from '../../types/groundUnattended'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { groundTransitionContextLabel } from '../../views/rail-transit/groundUnattendedLabels'

const props = defineProps<{ series: GroundPingSeries | null }>()
const rttContainer = ref<HTMLDivElement | null>(null)
const resultContainer = ref<HTMLDivElement | null>(null)
let rttChart: EChartsType | null = null
let resultChart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let disposed = false

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  if (disposed) return
  core.use([
    charts.LineChart, charts.ScatterChart, components.GridComponent, components.TooltipComponent,
    components.DataZoomComponent, components.MarkLineComponent, components.LegendComponent, renderers.CanvasRenderer,
  ])
  await nextTick()
  if (disposed) return
  if (rttContainer.value) rttChart = core.init(rttContainer.value)
  if (resultContainer.value) resultChart = core.init(resultContainer.value)
  unsubscribeTheme = subscribeNetConsoleChartTheme(render)
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize)
  if (rttContainer.value) resizeObserver?.observe(rttContainer.value)
  if (resultContainer.value) resizeObserver?.observe(resultContainer.value)
  window.addEventListener('resize', resize)
  render()
  await nextTick()
  resize()
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', resize)
  resizeObserver?.disconnect()
  unsubscribeTheme?.()
  rttChart?.dispose()
  resultChart?.dispose()
})

watch(() => props.series, render, { deep: true })

function resize(): void {
  rttChart?.resize()
  resultChart?.resize()
}

function render(): void {
  if (!rttChart || !resultChart) return
  const theme = readNetConsoleChartTokens()
  const points = props.series?.points || []
  const successes = points.filter((point) => point.ok && !point.warmup_ignored)
  const losses = points.filter((point) => !point.ok && !point.warmup_ignored)
  const warmup = points.filter((point) => point.warmup_ignored)
  const transitions = props.series?.ap_transitions || []
  const common = {
    animation: points.length < 1500,
    grid: { left: 54, right: 24, top: 38, bottom: 54 },
    tooltip: { trigger: 'item', formatter: tooltip },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }],
    xAxis: { type: 'time', axisLabel: { color: theme.textSecondary } },
  }
  rttChart.setOption({
    ...common,
    yAxis: { type: 'value', name: 'RTT (ms)', min: 0, axisLabel: { color: theme.textSecondary }, splitLine: { lineStyle: { color: theme.border } } },
    series: [
      {
        name: 'RTT', type: 'line', showSymbol: false, connectNulls: false,
        data: successes.map((point) => ({ value: [point.ts, point.rtt_ms], sample: point })),
        lineStyle: { color: theme.primary, width: 1.5 },
        itemStyle: { color: theme.primary },
        markLine: {
          symbol: 'none',
          label: { formatter: 'AP 切换', color: theme.warning },
          lineStyle: { color: theme.warning, type: 'dashed' },
          data: transitions.map((item) => ({ xAxis: String(item.ts || '') })),
        },
      },
      {
        name: '丢包', type: 'scatter', symbol: 'diamond', symbolSize: 10,
        data: losses.map((point) => ({ value: [point.ts, 0], sample: point })),
        itemStyle: { color: theme.danger },
      },
    ],
  }, { replaceMerge: ['series'] })
  resultChart.setOption({
    ...common,
    grid: { ...common.grid, top: 22 },
    yAxis: {
      type: 'category', data: ['位置未知', '预热忽略', '丢包', '成功'],
      axisLabel: { color: theme.textSecondary }, splitLine: { show: true, lineStyle: { color: theme.border } },
    },
    series: [
      packetSeries('成功', successes, 3, theme.series[1]),
      packetSeries('丢包', losses, 2, theme.danger),
      packetSeries('预热忽略', warmup, 1, theme.textSecondary),
      packetSeries('位置未知', points.filter((point) => point.position_quality === 'UNKNOWN'), 0, theme.warning),
    ],
  }, { replaceMerge: ['series'] })
}

function packetSeries(name: string, points: GroundPingSample[], y: number, color: string) {
  return {
    name, type: 'scatter', symbolSize: 7,
    data: points.map((point) => ({ value: [point.ts, y], sample: point })),
    itemStyle: { color },
  }
}

function tooltip(raw: unknown): string {
  const item = raw as { data?: { sample?: GroundPingSample } }
  const point = item.data?.sample
  if (!point) return '暂无数据'
  return [
    `时间：${escapeHtml(point.ts)}`,
    `列车：${escapeHtml(point.train_no || point.train_id || '未知')}`,
    `MR：${escapeHtml(point.mr_name || point.mr_position_code || '未知')}`,
    `管理 IP：${escapeHtml(point.target_ip)}`,
    `结果：${point.warmup_ignored ? '预热忽略' : point.ok ? '成功' : '丢包'}`,
    `RTT：${escapeHtml(point.rtt_ms == null ? '无' : `${point.rtt_ms} ms`)}`,
    `轨旁 AP：${escapeHtml(point.current_ap_name || '未知')}`,
    `AP MAC：${escapeHtml(point.current_ap_mac || '未知')}`,
    `站点 / 区间：${escapeHtml(point.station || '未知')} / ${escapeHtml(point.section || '未知')}`,
    `里程 / RSSI：${escapeHtml(point.mileage || '未知')} / ${escapeHtml(point.rssi ?? '未知')}`,
    `AC 位置时间：${escapeHtml(point.ac_received_at || '未知')}`,
    `切换窗口：${escapeHtml(groundTransitionContextLabel(point.ap_transition_context))}`,
  ].join('<br/>')
}

function escapeHtml(value: unknown): string {
  return String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)
}
</script>

<template>
  <section class="ping-charts" aria-label="长 Ping 逐包图表">
    <div>
      <h3>RTT 与丢包时间曲线</h3>
      <div ref="rttContainer" class="chart"></div>
    </div>
    <div>
      <h3>Ping 包结果时间轴</h3>
      <div ref="resultContainer" class="chart result-chart"></div>
    </div>
  </section>
</template>

<style scoped>
.ping-charts { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; width: 100%; }
.ping-charts h3 { margin: 0 0 6px; font-size: 14px; letter-spacing: 0; }
.chart { width: 100%; height: 330px; min-width: 0; }
.result-chart { height: 230px; }
</style>
