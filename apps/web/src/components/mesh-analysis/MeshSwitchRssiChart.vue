<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  createNetConsoleAxisStyle,
  createNetConsoleDataZoomStyle,
  createNetConsoleTooltipStyle,
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import type { MeshSwitchEvent } from '../../types/meshAnalysis'
import { buildMeshSwitchRssiSeries, hasMeshChartSamples } from './chartSeries'

const props = defineProps<{ events: MeshSwitchEvent[] }>()
const container = ref<HTMLDivElement | null>(null)
const hasData = computed(() => hasMeshChartSamples(buildMeshSwitchRssiSeries(props.events)))
let chart: { setOption: (option: unknown) => void; resize: () => void; dispose: () => void } | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  core.use([
    charts.ScatterChart, components.GridComponent, components.LegendComponent, components.TooltipComponent,
    components.DataZoomComponent, renderers.CanvasRenderer,
  ])
  await nextTick()
  if (!container.value) return
  chart = core.init(container.value)
  unsubscribeTheme = subscribeNetConsoleChartTheme(render)
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    if (container.value && container.value.clientWidth > 0) chart?.resize()
  })
  resizeObserver?.observe(container.value)
  render()
  window.addEventListener('resize', resize)
  await nextTick()
  resize()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  resizeObserver?.disconnect()
  resizeObserver = null
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.dispose()
  chart = null
})

watch(() => props.events, () => { render(); void nextTick(resize) }, { deep: true })

function resize(): void { chart?.resize() }

function render(): void {
  if (!chart) return
  const theme = readNetConsoleChartTokens()
  const axisStyle = createNetConsoleAxisStyle(theme)
  const series = buildMeshSwitchRssiSeries(props.events)
  chart.setOption({
    animation: false,
    color: theme.series,
    textStyle: { color: theme.text },
    tooltip: {
      trigger: 'item',
      ...createNetConsoleTooltipStyle(theme),
      formatter: (rawParam: unknown) => {
        const item = rawParam as { seriesName?: string; data?: { value?: [string | null, number | null]; meta?: MeshSwitchEvent } }
        const event = item.data?.meta
        const value = item.data?.value?.[1]
        return [
          `时间：${event?.timestamp || '—'}`,
          `${item.seriesName || '切换 RSSI'}：${value ?? '—'}`,
          `事件：${event?.event_type || '—'}`,
          `原 AP → 目标 AP：${event?.from_ap_name || event?.from_peer_mac || '—'} → ${event?.to_ap_name || event?.to_peer_mac || '—'}`,
          `Radio：${event?.local_radio ?? '—'}`,
        ].join('<br>')
      },
    },
    legend: { type: 'scroll', bottom: 4, textStyle: { color: theme.textSecondary } },
    grid: { left: 54, right: 22, top: 24, bottom: 74, containLabel: true },
    xAxis: { type: 'time', ...axisStyle },
    yAxis: { type: 'value', name: 'RSSI', nameTextStyle: { color: theme.textSecondary }, min: 'dataMin', ...axisStyle },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      { type: 'slider', height: 18, bottom: 28, filterMode: 'none', ...createNetConsoleDataZoomStyle(theme) },
    ],
    series: series.map((item) => ({ name: item.name, type: 'scatter', symbolSize: 10, data: item.data })),
  })
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!hasData" class="empty" description="暂无切换前后 RSSI 事件数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; min-height: 380px; width: 100%; }
.chart { height: 400px; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
