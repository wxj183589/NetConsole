<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { createTimeChartInitOptions } from '../charts/multiSeriesTimeChart'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { mrMonitoringChartOption } from './mrMonitoringChartOptions'
const props = defineProps<{ data: GroundMrMonitoring; start: string; end: string; active: boolean; selectedTime: string }>()
const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | undefined, observer: ResizeObserver | undefined, unsubscribe: (() => void) | undefined
let disposed = false, initialized = false
function render(): void {
  if (!chart || !props.active) return
  const option = mrMonitoringChartOption(props.data, props.start, props.end, readNetConsoleChartTokens(), props.selectedTime)
  option.series = (option.series as Array<Record<string, unknown>>).map((series) => series.type === 'line' ? { ...series, connectNulls: false } : series)
  if (initialized) delete option.dataZoom
  chart.setOption(option, { replaceMerge: ['series', 'xAxis', 'yAxis'], lazyUpdate: true }); initialized = true
}
function resize(): void { if (props.active) chart?.resize() }
onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers')])
  if (disposed || !container.value) return
  core.use([charts.LineChart, charts.CustomChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, components.DataZoomComponent, components.MarkLineComponent, components.TitleComponent, components.ToolboxComponent, renderers.CanvasRenderer])
  chart = core.init(container.value, undefined, createTimeChartInitOptions(props.data.series.points.length, { useDirtyRect: false }))
  observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize); observer?.observe(container.value)
  window.addEventListener('resize', resize); unsubscribe = subscribeNetConsoleChartTheme(render); render()
})
watch(() => [props.data, props.start, props.end, props.selectedTime], render)
watch(() => props.active, async (active) => { if (active) { await nextTick(); resize(); render() } else chart?.dispatchAction({ type: 'hideTip' }) })
onBeforeUnmount(() => { disposed = true; observer?.disconnect(); unsubscribe?.(); window.removeEventListener('resize', resize); chart?.dispose(); chart = undefined })
</script>
<template><div ref="container" class="mr-monitor-chart" role="img" aria-label="RTT 毫秒、丢包百分比和 Peer AP 连接证据共享时间轴" /></template>
<style scoped>.mr-monitor-chart{height:460px;width:100%;min-width:0}</style>
