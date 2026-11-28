<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import { createTimeChartInitOptions } from '../charts/multiSeriesTimeChart'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { quickPingChartOption } from './quickPingChartOptions'

const props = withDefaults(defineProps<{ rows: Array<Record<string, unknown>>; intervalMs: number; active: boolean; start?: string; end?: string; visibleStart?: string; visibleEnd?: string; selectedTime?: string; secondLossBuckets?: Array<Record<string, unknown>> }>(), { start: '', end: '', visibleStart: '', visibleEnd: '', selectedTime: '', secondLossBuckets: () => [] })
const emit = defineEmits<{ (event: 'viewport-change', value: { start: string; end: string }): void; (event: 'cursor-change', value: string): void }>()
const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | undefined
let observer: ResizeObserver | undefined
let unsubscribe: (() => void) | undefined
let disposed = false
function render(): void {
  if (!chart || !props.active) return
  const option = quickPingChartOption(props.rows, props.intervalMs, readNetConsoleChartTokens(), { connectNulls: false }, props.visibleStart && props.visibleEnd ? { start: props.visibleStart, end: props.visibleEnd } : undefined, props.selectedTime, props.start && props.end ? { start: props.start, end: props.end } : undefined, props.secondLossBuckets)
  chart.setOption(option, { replaceMerge: ['series', 'xAxis', 'yAxis', 'dataZoom'], lazyUpdate: true, silent: true })
}
function resize(): void { if (props.active) chart?.resize() }
onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  if (disposed || !container.value) return
  core.use([charts.LineChart, charts.ScatterChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, components.DataZoomComponent, components.TitleComponent, components.ToolboxComponent, components.MarkAreaComponent, components.MarkLineComponent, renderers.CanvasRenderer])
  chart = core.init(container.value, undefined, createTimeChartInitOptions(props.rows.length, { useDirtyRect: false }))
  chart.on('datazoom', (payload) => {
    const event = payload as { batch?: Array<{ start?: number; end?: number; startValue?: number; endValue?: number }>; start?: number; end?: number; startValue?: number; endValue?: number }
    const value = (event.batch?.[0] || event) as { startValue?: number; endValue?: number }
    const fullStart = Date.parse(props.start || props.rows.map((row) => String(row.received_at || '')).sort()[0] || '')
    const fullEnd = Date.parse(props.end || props.rows.map((row) => String(row.received_at || '')).sort().at(-1) || '')
    const startValue = Number.isFinite(value.startValue) ? Number(value.startValue) : fullStart + (fullEnd - fullStart) * Number((event.batch?.[0] || event).start ?? 0) / 100
    const endValue = Number.isFinite(value.endValue) ? Number(value.endValue) : fullStart + (fullEnd - fullStart) * Number((event.batch?.[0] || event).end ?? 100) / 100
    if (Number.isFinite(startValue) && Number.isFinite(endValue) && startValue < endValue) emit('viewport-change', { start: new Date(startValue).toISOString(), end: new Date(endValue).toISOString() })
  })
  chart.on('updateaxispointer', (payload) => {
    const value = Number((payload as { axesInfo?: Array<{ value?: number }> }).axesInfo?.[0]?.value)
    if (Number.isFinite(value)) emit('cursor-change', new Date(value).toISOString())
  })
  observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize)
  observer?.observe(container.value)
  window.addEventListener('resize', resize)
  unsubscribe = subscribeNetConsoleChartTheme(render)
  render()
})
watch(() => [props.rows, props.start, props.end, props.visibleStart, props.visibleEnd, props.selectedTime, props.secondLossBuckets], render)
watch(() => props.active, async (active) => {
  if (active) { await nextTick(); resize(); render() }
  else chart?.dispatchAction({ type: 'hideTip' })
})
onBeforeUnmount(() => { disposed = true; observer?.disconnect(); unsubscribe?.(); window.removeEventListener('resize', resize); chart?.dispose(); chart = undefined })
</script>

<template><div ref="container" class="quick-ping-chart" role="img" aria-label="快速 Ping RTT 毫秒与单包丢包百分比时间曲线" /></template>
<style scoped>.quick-ping-chart{height:280px;width:100%;min-width:0}</style>
