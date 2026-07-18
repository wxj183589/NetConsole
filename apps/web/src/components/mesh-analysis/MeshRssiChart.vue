<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  createNetConsoleAxisStyle,
  createNetConsoleDataZoomStyle,
  createNetConsoleTooltipStyle,
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import type { MeshRssiPoint } from '../../types/meshAnalysis'

const props = defineProps<{ points: MeshRssiPoint[] }>()
const container = ref<HTMLDivElement | null>(null)
let chart: { setOption: (option: unknown) => void; resize: () => void; dispose: () => void } | null = null
let unsubscribeTheme: (() => void) | null = null

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.DataZoomComponent, renderers.CanvasRenderer])
  await nextTick()
  if (container.value) {
    chart = core.init(container.value)
    unsubscribeTheme = subscribeNetConsoleChartTheme(render)
    render()
    window.addEventListener('resize', resize)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  unsubscribeTheme?.()
  unsubscribeTheme = null
  chart?.dispose()
  chart = null
})
watch(() => props.points, render, { deep: true })
function resize(): void {
  chart?.resize()
}
function render(): void {
  if (!chart) return
  const theme = readNetConsoleChartTokens()
  const axisStyle = createNetConsoleAxisStyle(theme)
  chart.setOption({
    animation: false,
    color: [theme.primary],
    textStyle: { color: theme.text },
    tooltip: {
      trigger: 'axis',
      ...createNetConsoleTooltipStyle(theme),
    },
    grid: { left: 54, right: 22, top: 24, bottom: 50 },
    xAxis: { type: 'time', ...axisStyle },
    yAxis: {
      type: 'value',
      name: 'RSSI',
      nameTextStyle: { color: theme.textSecondary },
      min: 0,
      ...axisStyle,
    },
    dataZoom: [
      { type: 'inside' },
      {
        type: 'slider',
        height: 18,
        ...createNetConsoleDataZoomStyle(theme),
      },
    ],
    series: [
      {
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        data: props.points.map((item) => [item.timestamp, item.value]),
      },
    ],
  })
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!points.length" class="empty" description="暂无 RSSI 数据" :image-size="60" />
  </div>
</template>

<style scoped>
.chart-shell {
  position: relative;
  min-height: 280px;
}

.chart {
  height: 280px;
  width: 100%;
}

.empty {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
</style>
