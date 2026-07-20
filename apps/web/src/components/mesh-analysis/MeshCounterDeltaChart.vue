<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  createNetConsoleAxisStyle,
  createNetConsoleDataZoomStyle,
  createNetConsoleTooltipStyle,
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import type { MeshCounterDeltaPoint } from '../../types/meshAnalysis'
import { buildMeshCounterDeltaSeries, hasMeshChartSamples } from './chartSeries'

const props = defineProps<{ points: MeshCounterDeltaPoint[] }>()
const container = ref<HTMLDivElement | null>(null)
const hasData = computed(() => hasMeshChartSamples(buildMeshCounterDeltaSeries(props.points)))
let chart: { setOption: (option: unknown) => void; resize: () => void; dispose: () => void } | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  core.use([
    charts.LineChart, components.GridComponent, components.LegendComponent, components.TooltipComponent,
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

watch(() => props.points, () => { render(); void nextTick(resize) }, { deep: true })

function resize(): void { chart?.resize() }

function render(): void {
  if (!chart) return
  const theme = readNetConsoleChartTokens()
  const axisStyle = createNetConsoleAxisStyle(theme)
  const series = buildMeshCounterDeltaSeries(props.points)
  chart.setOption({
    animation: false,
    color: theme.series,
    textStyle: { color: theme.text },
    tooltip: {
      trigger: 'axis',
      ...createNetConsoleTooltipStyle(theme),
      formatter: (rawParams: unknown) => {
        const params = Array.isArray(rawParams) ? rawParams : [rawParams]
        const first = params[0] as { axisValue?: string; data?: { meta?: MeshCounterDeltaPoint } } | undefined
        const meta = first?.data?.meta
        const lines = [`时间：${meta?.timestamp || first?.axisValue || '—'}`]
        for (const item of params as Array<{ seriesName?: string; data?: { value?: [string, number | null] } }>) {
          lines.push(`${item.seriesName || '计数器增量'}：${item.data?.value?.[1] ?? '—'}`)
        }
        if (meta) lines.push(`Peer AP：${meta.peer_ap_name || meta.peer_ap_mac || '—'}`, `Radio：${meta.local_radio ?? '—'}`)
        return lines.join('<br>')
      },
    },
    legend: { type: 'scroll', bottom: 4, textStyle: { color: theme.textSecondary } },
    grid: { left: 78, right: 22, top: 24, bottom: 74, containLabel: true },
    xAxis: { type: 'time', ...axisStyle },
    yAxis: { type: 'value', name: '增量（原始计数）', nameTextStyle: { color: theme.textSecondary }, ...axisStyle },
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      { type: 'slider', height: 18, bottom: 28, filterMode: 'none', ...createNetConsoleDataZoomStyle(theme) },
    ],
    series: series.map((item) => ({ name: item.name, type: 'line', showSymbol: false, connectNulls: false, data: item.data })),
  })
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!hasData" class="empty" description="暂无 Retry / Error 增量数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; min-height: 380px; width: 100%; }
.chart { height: 400px; width: 100%; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
