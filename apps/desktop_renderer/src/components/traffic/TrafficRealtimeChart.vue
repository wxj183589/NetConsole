<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  createNetConsoleAxisStyle,
  createNetConsoleLegendStyle,
  createNetConsoleTooltipStyle,
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import type { TrafficPingSample } from '../../types/traffic'

const props = defineProps<{ samples: TrafficPingSample[] }>()
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
  core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, renderers.CanvasRenderer])
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

watch(() => props.samples, render, { deep: true })

function resize(): void {
  chart?.resize()
}

function render(): void {
  if (!chart) return
  const theme = readNetConsoleChartTokens()
  const axisStyle = createNetConsoleAxisStyle(theme)
  const groups = new Map<string, [string, number][]>()
  for (const sample of props.samples) {
    if (!sample.ok || sample.rtt_ms === null) continue
    const values = groups.get(sample.target) || []
    values.push([sample.timestamp, sample.rtt_ms])
    groups.set(sample.target, values)
  }
  chart.setOption({
    animation: false,
    color: theme.series,
    textStyle: { color: theme.text },
    tooltip: {
      trigger: 'axis',
      ...createNetConsoleTooltipStyle(theme),
    },
    legend: { top: 0, type: 'scroll', ...createNetConsoleLegendStyle(theme) },
    grid: { left: 48, right: 24, top: 44, bottom: 36 },
    xAxis: { type: 'time', ...axisStyle },
    yAxis: { type: 'value', name: 'RTT ms', nameTextStyle: { color: theme.textSecondary }, min: 0, ...axisStyle },
    series: Array.from(groups.entries()).map(([name, data]) => ({ name, type: 'line', showSymbol: false, data })),
  })
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!samples.length" class="chart-empty" description="暂无 Ping 采样" :image-size="64" />
  </div>
</template>

<style scoped>
.chart-shell {
  position: relative;
  min-height: 260px;
}

.chart {
  height: 260px;
  width: 100%;
}

.chart-empty {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
</style>
