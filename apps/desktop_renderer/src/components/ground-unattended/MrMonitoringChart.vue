<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { createTimeChartInitOptions } from '../charts/multiSeriesTimeChart'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { mrMonitoringChartOption } from './mrMonitoringChartOptions'
const props = withDefaults(defineProps<{
  data: GroundMrMonitoring; start: string; end: string; active: boolean; selectedTime: string
  visibleStart?: string; visibleEnd?: string; mode?: 'all' | 'ping' | 'peer' | 'navigator'
}>(), { mode: 'all', visibleStart: '', visibleEnd: '' })
const emit = defineEmits<{
  (event: 'viewport-change', value: { start: string; end: string }): void
  (event: 'cursor-change', value: string): void
}>()
const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | undefined, observer: ResizeObserver | undefined, unsubscribe: (() => void) | undefined
let disposed = false
function render(): void {
  if (!chart || !props.active) return
  const option = mrMonitoringChartOption(
    props.data, props.start, props.end, readNetConsoleChartTokens(), props.selectedTime, props.mode,
    props.visibleStart || props.start, props.visibleEnd || props.end,
  )
  option.series = (option.series as Array<Record<string, unknown>>).map((series) => series.type === 'line' ? { ...series, connectNulls: false } : series)
  chart.setOption(option, { replaceMerge: ['series', 'xAxis', 'yAxis', 'dataZoom'], lazyUpdate: true })
}
function emitViewport(payload: unknown): void {
  const event = payload as { batch?: Array<{ start?: number; end?: number; startValue?: number; endValue?: number }>; start?: number; end?: number; startValue?: number; endValue?: number }
  const value = event.batch?.[0] || event
  const fullStart = Date.parse(props.start), fullEnd = Date.parse(props.end)
  const start = Number.isFinite(value.startValue) ? Number(value.startValue) : fullStart + (fullEnd - fullStart) * Number(value.start ?? 0) / 100
  const end = Number.isFinite(value.endValue) ? Number(value.endValue) : fullStart + (fullEnd - fullStart) * Number(value.end ?? 100) / 100
  if (Number.isFinite(start) && Number.isFinite(end) && start < end) emit('viewport-change', { start: new Date(start).toISOString(), end: new Date(end).toISOString() })
}
function emitCursor(payload: unknown): void {
  const event = payload as { axesInfo?: Array<{ value?: string | number }> }
  const stamp = Number(event.axesInfo?.[0]?.value)
  if (Number.isFinite(stamp)) emit('cursor-change', new Date(stamp).toISOString())
}
function resize(): void { if (props.active) chart?.resize() }
onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers')])
  if (disposed || !container.value) return
  core.use([charts.LineChart, charts.CustomChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, components.DataZoomComponent, components.MarkLineComponent, components.TitleComponent, components.ToolboxComponent, renderers.CanvasRenderer])
  chart = core.init(container.value, undefined, createTimeChartInitOptions(props.data.series.points.length, { useDirtyRect: false }))
  chart.on('datazoom', emitViewport)
  chart.on('updateaxispointer', emitCursor)
  observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize); observer?.observe(container.value)
  window.addEventListener('resize', resize); unsubscribe = subscribeNetConsoleChartTheme(render); render()
})
watch(() => [props.data, props.start, props.end, props.visibleStart, props.visibleEnd, props.selectedTime, props.mode], render)
watch(() => props.active, async (active) => { if (active) { await nextTick(); resize(); render() } else chart?.dispatchAction({ type: 'hideTip' }) })
onBeforeUnmount(() => { disposed = true; observer?.disconnect(); unsubscribe?.(); window.removeEventListener('resize', resize); chart?.dispose(); chart = undefined })
</script>
<template><div ref="container" class="mr-monitor-chart" :class="`mode-${mode}`" role="img" aria-label="RTT 毫秒、丢包百分比和 Peer AP 连接证据共享时间轴" /></template>
<style scoped>.mr-monitor-chart{height:460px;width:100%;min-width:0}.mr-monitor-chart.mode-ping{height:320px}.mr-monitor-chart.mode-peer{height:300px}.mr-monitor-chart.mode-navigator{height:84px}</style>
