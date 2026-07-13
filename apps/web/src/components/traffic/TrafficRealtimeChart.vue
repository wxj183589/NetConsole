<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { TrafficPingSample } from '../../types/traffic'

const props = defineProps<{ samples: TrafficPingSample[] }>()
const container = ref<HTMLDivElement | null>(null)
let chart: { setOption: (option: unknown) => void; resize: () => void; dispose: () => void } | null = null

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
    render()
    window.addEventListener('resize', resize)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})

watch(() => props.samples, render, { deep: true })

function resize(): void {
  chart?.resize()
}

function render(): void {
  if (!chart) return
  const groups = new Map<string, [string, number][]>()
  for (const sample of props.samples) {
    if (!sample.ok || sample.rtt_ms === null) continue
    const values = groups.get(sample.target) || []
    values.push([sample.timestamp, sample.rtt_ms])
    groups.set(sample.target, values)
  }
  chart.setOption({
    animation: false,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, type: 'scroll' },
    grid: { left: 48, right: 24, top: 44, bottom: 36 },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', name: 'RTT ms', min: 0 },
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
