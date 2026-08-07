<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

import type { GroundApTransition, GroundPingSample, GroundPingSeries } from '../../types/groundUnattended'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { groundTransitionContextLabel } from '../../views/rail-transit/groundUnattendedLabels'

const props = withDefaults(defineProps<{
  series: GroundPingSeries | null
  followLatest?: boolean
}>(), {
  followLatest: true,
})
const emit = defineEmits<{ 'user-zoom': [] }>()
const rttContainer = ref<HTMLDivElement | null>(null)
const resultContainer = ref<HTMLDivElement | null>(null)
let rttChart: EChartsType | null = null
let resultChart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null
let disposed = false
let renderFrame: number | null = null
let optionsInitialized = false
let programmaticZoom = false

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  if (disposed) return
  core.use([
    charts.LineChart, charts.ScatterChart, components.GridComponent, components.TooltipComponent,
    components.DataZoomComponent, components.MarkLineComponent, components.MarkAreaComponent,
    components.LegendComponent, renderers.CanvasRenderer,
  ])
  await nextTick()
  if (disposed) return
  if (rttContainer.value) rttChart = core.init(rttContainer.value)
  if (resultContainer.value) resultChart = core.init(resultContainer.value)
  rttChart?.on?.('datazoom', handleUserZoom)
  resultChart?.on?.('datazoom', handleUserZoom)
  unsubscribeTheme = subscribeNetConsoleChartTheme(scheduleRender)
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize)
  if (rttContainer.value) resizeObserver?.observe(rttContainer.value)
  if (resultContainer.value) resizeObserver?.observe(resultContainer.value)
  window.addEventListener('resize', resize)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  render()
  await nextTick()
  resize()
})

onBeforeUnmount(() => {
  disposed = true
  if (renderFrame !== null) cancelAnimationFrame(renderFrame)
  window.removeEventListener('resize', resize)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  resizeObserver?.disconnect()
  unsubscribeTheme?.()
  rttChart?.off?.('datazoom', handleUserZoom)
  resultChart?.off?.('datazoom', handleUserZoom)
  rttChart?.dispose()
  resultChart?.dispose()
})

watch(() => props.series, scheduleRender, { deep: true })
watch(() => props.followLatest, (follow) => {
  if (follow) scheduleRender()
})

function resize(): void {
  rttChart?.resize()
  resultChart?.resize()
}

function handleVisibilityChange(): void {
  if (!document.hidden) {
    scheduleRender()
    resize()
  }
}

function scheduleRender(): void {
  if (disposed || document.hidden) return
  if (renderFrame !== null) cancelAnimationFrame(renderFrame)
  renderFrame = requestAnimationFrame(() => {
    renderFrame = null
    render()
  })
}

function handleUserZoom(): void {
  if (!programmaticZoom) emit('user-zoom')
}

function followLatestWindow(pointCount: number): void {
  if (!props.followLatest || !pointCount) return
  const visibleCount = Math.min(300, pointCount)
  const start = Math.max(0, 100 - visibleCount / pointCount * 100)
  programmaticZoom = true
  const action = { type: 'dataZoom', start, end: 100 }
  rttChart?.dispatchAction?.(action)
  resultChart?.dispatchAction?.(action)
  queueMicrotask(() => { programmaticZoom = false })
}

function render(): void {
  if (!rttChart || !resultChart) return
  const theme = readNetConsoleChartTokens()
  const points = props.series?.points || []
  const successes = points.filter((point) => point.ok && !point.warmup_ignored)
  const losses = points.filter((point) => !point.ok && !point.warmup_ignored)
  const warmup = points.filter((point) => point.warmup_ignored)
  const transitions = props.series?.ap_transitions || []
  const positionSegments = props.series?.position_segments || []
  const lastTimestamp = String(points.at(-1)?.ts || '')
  const markAreas = positionSegments.flatMap((segment, index) => {
    const startedAt = String(segment.started_at || '')
    const endedAt = String(positionSegments[index + 1]?.started_at || lastTimestamp)
    if (!startedAt || !endedAt) return []
    const label = [
      String(segment.current_ap_name || ''),
      String(segment.station || ''),
      String(segment.section || ''),
    ].filter(Boolean).join(' · ') || '位置未知'
    return [[
      { name: label, xAxis: startedAt },
      { xAxis: endedAt },
    ]]
  })
  const common = {
    animation: points.length < 1500,
    grid: { left: 54, right: 24, top: 38, bottom: 54 },
    tooltip: { trigger: 'item', formatter: tooltip },
    ...(!optionsInitialized ? { dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }] } : {}),
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
          data: transitions.map((item) => ({ xAxis: String(item.ts || ''), transition: item })),
        },
        markArea: {
          silent: true,
          label: { show: true, color: theme.textSecondary, fontSize: 10 },
          itemStyle: { color: theme.primary, opacity: 0.05 },
          data: markAreas,
        },
      },
      {
        name: '丢包', type: 'scatter', symbol: 'diamond', symbolSize: 10,
        data: losses.map((point) => ({ value: [point.ts, 0], sample: point })),
        itemStyle: { color: theme.danger },
      },
    ],
  }, { replaceMerge: ['series'], lazyUpdate: true })
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
  }, { replaceMerge: ['series'], lazyUpdate: true })
  optionsInitialized = true
  followLatestWindow(points.length)
}

function packetSeries(name: string, points: GroundPingSample[], y: number, color: string) {
  return {
    name, type: 'scatter', symbolSize: 7,
    data: points.map((point) => ({ value: [point.ts, y], sample: point })),
    itemStyle: { color },
  }
}

function tooltip(raw: unknown): string {
  const item = raw as { data?: { sample?: GroundPingSample; transition?: GroundApTransition } }
  const transition = item.data?.transition
  if (transition) return transitionTooltip(transition)
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

function transitionTooltip(event: GroundApTransition): string {
  const oldAp = event.old_ap_name || event.old_ap_raw || event.old_ap_mac || '未知 AP'
  const newAp = event.new_ap_name || event.new_ap_raw || event.new_ap_mac || '未知 AP'
  return [
    'AP 主链路切换',
    `时间：${escapeHtml(event.event_time || event.ts)}`,
    `列车 / MR：${escapeHtml(event.train_id || '未知')} / ${escapeHtml(event.mr_role || event.mr_id || '未知')}`,
    `切换：${escapeHtml(oldAp)} → ${escapeHtml(newAp)}`,
    `站点：${escapeHtml(event.old_station || '未知')} → ${escapeHtml(event.new_station || '未知')}`,
    `切换前 RSSI：${formatRssiEvidence(event.rssi_before, event.rssi_before_delta_ms, event.rssi_before_reason)}`,
    `切换后 RSSI：${formatRssiEvidence(event.rssi_after, event.rssi_after_delta_ms, event.rssi_after_reason)}`,
    `来源：${escapeHtml(event.source || 'MR Syslog / WMESH')}`,
  ].join('<br/>')
}

function formatRssiEvidence(value: number | null, deltaMs: number | null, reason: string): string {
  if (value == null) return escapeHtml(reason === 'AP_IDENTITY_UNAVAILABLE' ? 'AP 身份未解析，无法关联采样' : '无对应采样')
  const delta = deltaMs == null ? '' : ` (${deltaMs >= 0 ? '+' : ''}${deltaMs} ms)`
  return `${escapeHtml(value)} dBm${escapeHtml(delta)}`
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
.chart { width: 100%; height: 280px; min-width: 0; }
.result-chart { height: 190px; }
</style>
