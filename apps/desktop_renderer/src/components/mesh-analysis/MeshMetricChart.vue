<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import { readNetConsoleChartTokens, createNetConsoleDataZoomStyle, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { createTimeChartInitOptions } from '../charts/multiSeriesTimeChart'
import { meshTimestampMillis as millis, formatMeshViewportTimestamp as stamp } from './meshChartViewport'
import type { MeshBusinessMetricLine } from './meshBusinessMetrics'
export interface MeshMetricPoint { timestamp: string; value: number | null }
export interface MeshMonitorWindow { start: string; end: string }
const props = withDefaults(defineProps<{ points?: MeshMetricPoint[]; lines?: MeshBusinessMetricLine[]; unit?: string; emptyText?: string; domain?: MeshMonitorWindow; window?: MeshMonitorWindow; pointer?: string | null; selectedTime?: string | null; navigator?: boolean }>(), { points: () => [], lines: () => [], unit: '', emptyText: '暂无有效数据', pointer: null, selectedTime: null, navigator: false })
const emit = defineEmits<{ 'render-complete': []; 'render-error': [error: string]; 'viewport-change': [window: MeshMonitorWindow]; 'pointer-change': [time: string | null]; 'sample-select': [sample: unknown] }>()
const host = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let intersectionObserver: IntersectionObserver | null = null
let disposed = false, visible = false, epoch = 0, applying = false
let finished: (() => void) | null = null
let unsubscribeTheme: (() => void) | null = null
function syncWindow(): void {
  if (!chart || !props.window) return
  applying = true
  chart.dispatchAction({ type: 'dataZoom', startValue: millis(props.window.start), endValue: millis(props.window.end) }, { silent: true })
  applying = false
}
function syncPointer(): void {
  if (!chart) return
  applying = true
  const value = millis(props.pointer ?? props.selectedTime)
  if (value !== null) chart.dispatchAction({ type: 'updateAxisPointer', x: chart.convertToPixel({ xAxisIndex: 0 }, value), y: chart.getHeight() / 2, currTrigger: 'mousemove', escapeConnect: true }, { silent: true })
  else chart.dispatchAction({ type: 'hideTip' }, { silent: true })
  applying = false
}
function onZoom(event: any): void {
  if (applying || !props.domain) return
  const zoom = event.batch?.[0] ?? event
  const low = millis(props.domain.start), high = millis(props.domain.end)
  if (low === null || high === null) return
  const start = millis(zoom.startValue) ?? low + (high - low) * (zoom.start ?? 0) / 100
  const end = millis(zoom.endValue) ?? low + (high - low) * (zoom.end ?? 100) / 100
  if (start < end) emit('viewport-change', { start: stamp(start), end: stamp(end) })
}
function onPointer(event: any): void {
  if (applying) return
  const value = millis(event.axesInfo?.[0]?.value)
  if (value !== null) emit('pointer-change', stamp(value))
}
function onClick(event: any): void { if (event.data?.sample) emit('sample-select', event.data.sample) }
function onLeave(): void { emit('pointer-change', null) }
async function render(): Promise<void> {
  const local = ++epoch
  if (!host.value || disposed || !visible) return
  try {
    const [core, charts, components, renderers] = await Promise.all([import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers')])
    if (disposed || !host.value || local !== epoch) return
    core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.DataZoomComponent, components.LegendComponent, components.AxisPointerComponent, components.MarkLineComponent, renderers.CanvasRenderer])
    const lines = props.lines.length ? props.lines : [{ key: 'metric', label: '', side: 'local', data: props.points.map(point => ({ value: [point.timestamp, point.value], sample: point })) }]
    if (!chart) {
      chart = core.init(host.value, undefined, createTimeChartInitOptions(lines.reduce((sum, line) => sum + line.data.length, 0), { useDirtyRect: false }))
      chart.on('datazoom', onZoom); chart.on('updateAxisPointer', onPointer); chart.on('click', onClick); chart.getZr().on('globalout', onLeave)
    }
    if (finished) chart.off('finished', finished)
    finished = () => { if (!disposed && local === epoch) { if (finished) chart?.off('finished', finished); finished = null; emit('render-complete') } }
    chart.on('finished', finished)
    const theme = readNetConsoleChartTokens()
    const palette = theme.series
    chart.setOption({
      animation: false, color: palette,
      grid: { left: 54, right: 16, top: 35, bottom: props.navigator ? 55 : 27 },
      legend: { type: 'scroll', top: 2, textStyle: { color: theme.textSecondary, fontSize: 10 } },
      tooltip: { trigger: 'axis', showContent: false },
      xAxis: { type: 'time', min: millis(props.domain?.start), max: millis(props.domain?.end), axisLabel: { color: theme.textSecondary, fontSize: 10 }, axisPointer: { show: true, snap: false, triggerTooltip: false, label: { show: true } } },
      yAxis: { type: 'value', scale: true, name: props.unit, nameTextStyle: { color: theme.textSecondary }, axisLabel: { color: theme.textSecondary, fontSize: 10 }, splitLine: { lineStyle: { color: theme.splitLine } } },
      dataZoom: [{ type: 'inside', filterMode: 'none', throttle: 100, startValue: millis(props.window?.start), endValue: millis(props.window?.end) }, ...(props.navigator ? [{ ...createNetConsoleDataZoomStyle(theme), type: 'slider', filterMode: 'none', height: 18, bottom: 5, showDataShadow: false, startValue: millis(props.window?.start), endValue: millis(props.window?.end) }] : [])],
      series: lines.map((line, index) => ({ id: line.key, name: line.label, type: 'line', showSymbol: true, symbolSize: 4, connectNulls: false, lineStyle: { width: 1.3, type: line.side === 'peer' ? 'dashed' : 'solid' }, data: line.data, markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: theme.warning }, data: props.selectedTime ? [{ xAxis: millis(props.selectedTime) }] : [] }, itemStyle: { color: palette[index % palette.length] } })),
    }, { replaceMerge: ['series', 'dataZoom'], lazyUpdate: false })
    syncPointer()
  } catch (error) {
    if (local === epoch && !disposed) {
      if (finished) chart?.off('finished', finished)
      finished = null
      emit('render-error', error instanceof Error ? error.message : '图表绘制失败')
    }
  }
}
function resize(): void { chart?.resize() }
onMounted(async () => {
  await nextTick(); if (disposed || !host.value) return
  unsubscribeTheme = subscribeNetConsoleChartTheme(() => { void render() })
  resizeObserver = new ResizeObserver(resize); resizeObserver.observe(host.value)
  if (typeof IntersectionObserver === 'undefined') { visible = true; void render(); return }
  intersectionObserver = new IntersectionObserver(entries => { const next = entries.some(entry => entry.isIntersecting); if (next && !visible) { visible = true; void render() } else visible = next }, { rootMargin: '240px' })
  intersectionObserver.observe(host.value)
})
watch(() => [props.lines, props.points, props.domain, props.selectedTime], () => { void render() })
watch(() => props.window, syncWindow)
watch(() => props.pointer, syncPointer)
onBeforeUnmount(() => {
  disposed = true; epoch++; unsubscribeTheme?.(); resizeObserver?.disconnect(); intersectionObserver?.disconnect()
  if (chart) { chart.off('datazoom', onZoom); chart.off('updateAxisPointer', onPointer); chart.off('click', onClick); if (finished) chart.off('finished', finished); chart.getZr().off('globalout', onLeave); chart.dispose(); chart = null }
})
</script>
<template><div class="mesh-metric-frame"><div ref="host" class="mesh-metric-chart" :class="{ 'has-navigator': navigator }" :data-window-start="window?.start" :data-window-end="window?.end" :data-pointer="pointer"></div><span v-if="lines.length ? !lines.some(line => line.data.some(point => point.value[1] !== null)) : !points.some(point => point.value !== null)" class="metric-empty">{{ emptyText }}</span></div></template>
<style scoped>
.mesh-metric-frame{position:relative}.mesh-metric-chart{position:relative;width:100%;height:190px;min-height:190px}.mesh-metric-chart.has-navigator{height:220px}.metric-empty{position:absolute;inset:70px 0 auto;text-align:center;color:var(--nc-text-secondary);font-size:12px;pointer-events:none}
@media(prefers-reduced-motion:reduce){.mesh-metric-chart{transition:none}}
</style>
