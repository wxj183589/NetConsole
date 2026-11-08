<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import { createTimeChartInitOptions } from '../charts/multiSeriesTimeChart'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import { quickPingChartOption } from './quickPingChartOptions'

const props = defineProps<{ rows: Array<Record<string, unknown>>; intervalMs: number; active: boolean }>()
const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | undefined
let observer: ResizeObserver | undefined
let unsubscribe: (() => void) | undefined
let disposed = false
let initialized = false
function render(): void {
  if (!chart || !props.active) return
  const option = quickPingChartOption(props.rows, props.intervalMs, readNetConsoleChartTokens(), { connectNulls: false })
  if (initialized) delete option.dataZoom
  chart.setOption(option, { replaceMerge: ['series', 'yAxis'], lazyUpdate: true })
  initialized = true
}
function resize(): void { if (props.active) chart?.resize() }
onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  if (disposed || !container.value) return
  core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, components.DataZoomComponent, components.TitleComponent, components.ToolboxComponent, renderers.CanvasRenderer])
  chart = core.init(container.value, undefined, createTimeChartInitOptions(props.rows.length, { useDirtyRect: false }))
  observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize)
  observer?.observe(container.value)
  window.addEventListener('resize', resize)
  unsubscribe = subscribeNetConsoleChartTheme(render)
  render()
})
watch(() => props.rows, render)
watch(() => props.active, async (active) => {
  if (active) { await nextTick(); resize(); render() }
  else chart?.dispatchAction({ type: 'hideTip' })
})
onBeforeUnmount(() => { disposed = true; observer?.disconnect(); unsubscribe?.(); window.removeEventListener('resize', resize); chart?.dispose(); chart = undefined })
</script>

<template><div ref="container" class="quick-ping-chart" role="img" aria-label="快速 Ping RTT 毫秒与单包丢包百分比时间曲线" /></template>
<style scoped>.quick-ping-chart{height:280px;width:100%;min-width:0}</style>
