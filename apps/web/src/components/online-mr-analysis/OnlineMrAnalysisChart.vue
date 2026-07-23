<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import {
  readNetConsoleChartTokens,
  subscribeNetConsoleChartTheme,
} from '../../theme/echarts'
import {
  createMultiSeriesTimeChartBaseOption,
  createTimeChartInitOptions,
  createTimeChartLinePresentation,
} from '../charts/multiSeriesTimeChart'
import type { OnlineMrMetricSeries } from '../../types/onlineMr'

const props = withDefaults(defineProps<{
  series: OnlineMrMetricSeries[]
  title?: string
  unit?: string
  events?: Array<{ time: string; label: string; severity?: string }>
}>(), { title: '', unit: '', events: () => [] })

const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let unsubscribeTheme: (() => void) | null = null

const pointCount = (): number => props.series.reduce((total, item) => total + item.points.length, 0)

onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers'),
  ])
  core.use([charts.LineChart, components.GridComponent, components.LegendComponent, components.TooltipComponent, components.DataZoomComponent, components.MarkLineComponent, components.ToolboxComponent, renderers.CanvasRenderer])
  await nextTick()
  if (!container.value) return
  chart = core.init(container.value, undefined, createTimeChartInitOptions(pointCount()))
  unsubscribeTheme = subscribeNetConsoleChartTheme(render)
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => resize())
  resizeObserver?.observe(container.value)
  window.addEventListener('resize', resize)
  render()
  await nextTick(resize)
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

watch(() => [props.series, props.events], () => { render(); void nextTick(resize) }, { deep: true })

function resize(): void { if (container.value?.clientWidth) chart?.resize() }

function render(): void {
  if (!chart) return
  const theme = readNetConsoleChartTokens()
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, {
    title: props.title,
    unit: props.unit,
    pointCount: pointCount(),
  })
  const events = props.events.filter((event) => event.time)
  const chartSeries = props.series.map((item) => ({
    id: item.series_key || '默认序列',
    name: item.series_key || '默认序列',
    type: 'line',
    ...createTimeChartLinePresentation(pointCount()),
    connectNulls: false,
    data: item.points.map((point) => ({ value: [point.timestamp, point.value], dimensions: point.dimensions })),
  }))
  if (events.length && chartSeries[0]) {
    Object.assign(chartSeries[0], {
      markLine: {
        symbol: 'none',
        label: { color: theme.warning },
        data: events.map((event) => ({ xAxis: event.time, name: event.label, lineStyle: { color: event.severity === 'error' ? theme.danger : theme.warning } })),
      },
    })
  }
  chart.setOption({
    ...baseOption,
    tooltip: {
      ...(baseOption.tooltip as Record<string, unknown>),
      formatter: (raw: unknown) => {
        const rows = Array.isArray(raw) ? raw : [raw]
        const first = rows[0] as { axisValue?: string } | undefined
        const lines = [`时间：${first?.axisValue || '无数据'}`]
        for (const row of rows as Array<{ seriesName?: string; value?: [string, number | null]; data?: { dimensions?: Record<string, unknown> } }>) {
          const value = row.value?.[1]
          const dimensions = row.data?.dimensions || {}
          const suffix = Object.entries(dimensions).map(([key, item]) => `${key}=${item}`).join('，')
          lines.push(`${row.seriesName || '指标'}：${value == null ? '无数据' : value}${props.unit ? ` ${props.unit}` : ''}${suffix ? `<br/>　${suffix}` : ''}`)
        }
        return lines.join('<br/>')
      },
    },
    series: chartSeries,
  }, { replaceMerge: ['series'] })
}
</script>

<template>
  <div class="chart-shell">
    <div ref="container" class="chart"></div>
    <el-empty v-if="!series.some((item) => item.points.some((point) => point.value !== null || point.text_value))" class="empty" description="暂无可用数据" :image-size="58" />
  </div>
</template>

<style scoped>
.chart-shell { position: relative; min-height: 380px; width: 100%; }
.chart { width: 100%; height: 410px; min-width: 0; }
.empty { position: absolute; inset: 0; pointer-events: none; }
</style>
