<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { MeshRssiPoint } from '../../types/meshAnalysis'

const props = defineProps<{ points: MeshRssiPoint[] }>()
const container = ref<HTMLDivElement | null>(null)
let chart: { setOption: (option: unknown) => void; resize: () => void; dispose: () => void } | null = null

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers')])
  core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.DataZoomComponent, renderers.CanvasRenderer])
  await nextTick()
  if (container.value) {
    chart = core.init(container.value)
    render()
    window.addEventListener('resize', resize)
  }
})

onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose(); chart = null })
watch(() => props.points, render, { deep: true })
function resize(): void { chart?.resize() }
function render(): void {
  chart?.setOption({ animation: false, tooltip: { trigger: 'axis' }, grid: { left: 54, right: 22, top: 24, bottom: 50 }, xAxis: { type: 'time' }, yAxis: { type: 'value', name: 'RSSI', min: 0 }, dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }], series: [{ type: 'line', showSymbol: false, connectNulls: false, data: props.points.map((item) => [item.timestamp, item.value]) }] })
}
</script>

<template><div class="chart-shell"><div ref="container" class="chart"></div><el-empty v-if="!points.length" class="empty" description="暂无 RSSI 数据" :image-size="60" /></div></template>
<style scoped>.chart-shell{position:relative;min-height:280px}.chart{height:280px;width:100%}.empty{position:absolute;inset:0;pointer-events:none}</style>
