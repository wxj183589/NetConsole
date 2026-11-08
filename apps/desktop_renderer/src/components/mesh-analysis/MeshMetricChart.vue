<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'

export interface MeshMetricPoint { timestamp: string; value: number | null }

const props = withDefaults(defineProps<{
  points: MeshMetricPoint[]
  color?: string
  unit?: string
  emptyText?: string
}>(), { color: '#409eff', unit: '', emptyText: '暂无有效数据' })
const emit = defineEmits<{ 'render-complete': []; 'render-error': [error: string] }>()
const host = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let disposed = false

async function render(): Promise<void> {
  if (!host.value || disposed) return
  if (!props.points.length) { chart?.clear(); emit('render-complete'); return }
  try {
    const [core, charts, components, renderers] = await Promise.all([
      import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
    ])
    if (disposed || !host.value) return
    core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.DataZoomComponent, renderers.CanvasRenderer])
    if (!chart) chart = core.init(host.value)
    chart.off('finished')
    chart.on('finished', () => { if (!disposed) emit('render-complete') })
    chart.setOption({
      animation: typeof window === 'undefined' || !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
      grid: { left: 38, right: 12, top: 16, bottom: 24 },
      tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => `${value ?? '—'}${props.unit}` },
      xAxis: { type: 'time', axisLabel: { color: '#8b98aa', fontSize: 10 } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#8b98aa', fontSize: 10 } },
      dataZoom: [{ type: 'inside' }],
      series: [{ type: 'line', showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: props.color }, itemStyle: { color: props.color }, data: props.points.map(point => [point.timestamp, point.value]) }],
    }, true)
  } catch (error) {
    emit('render-error', error instanceof Error ? error.message : '图表绘制失败')
  }
}
function resize(): void { chart?.resize() }
onMounted(async () => { await nextTick(); if (host.value) { resizeObserver = new ResizeObserver(resize); resizeObserver.observe(host.value) }; await render() })
watch(() => props.points, () => { void render() }, { deep: true })
onBeforeUnmount(() => { disposed = true; resizeObserver?.disconnect(); resizeObserver = null; chart?.off('finished'); chart?.dispose(); chart = null })
</script>

<template>
  <div ref="host" class="mesh-metric-chart">
    <el-empty v-if="!points.length" :description="emptyText" :image-size="42" />
  </div>
</template>

<style scoped>
.mesh-metric-chart { width: 100%; height: 176px; min-height: 176px; }
.mesh-metric-chart :deep(.el-empty) { height: 100%; padding: 12px 0; }
</style>
