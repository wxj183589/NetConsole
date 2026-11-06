<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsType } from 'echarts/core'
import { createTimeChartInitOptions } from '../charts/multiSeriesTimeChart'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from '../../theme/echarts'
import type { AcMeshLinkRecord } from '../../types/acMeshLink'
import { t } from '../../i18n/runtime'
const props = defineProps<{ rows: AcMeshLinkRecord[]; active: boolean }>()
const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | undefined, observer: ResizeObserver | undefined, unsubscribe: (() => void) | undefined
let disposed = false, initialized = false
function render() {
  if (!chart || !props.active) return
  const tokens = readNetConsoleChartTokens()
  const groups = new Map<string, Array<[number, number]>>()
  for (const row of props.rows) {
    const time = Date.parse(row.device_time || row.last_seen_at)
    if (!Number.isFinite(time) || row.rssi == null) continue
    const key = `${row.peer_ap_name || row.bssid || '—'} · ${row.bssid || row.peer_ap_mac}`
    groups.set(key, [...(groups.get(key) || []), [time, row.rssi]])
  }
  chart.setOption({ backgroundColor: tokens.background, grid: { left: 54, right: 20, top: 48, bottom: 64 },
    legend: { type: 'scroll', top: 4 }, tooltip: { trigger: 'item', appendToBody: false, confine: true,
      extraCssText: 'max-width:320px;max-height:180px;overflow:hidden;pointer-events:none' },
    xAxis: { type: 'time' }, yAxis: { type: 'value', name: 'RSSI', scale: true },
    ...(!initialized ? { dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 12 }] } : {}),
    series: [...groups].map(([name, data]) => ({ id: name, name, type: 'scatter', connectNulls: false, symbolSize: 7, data: data.sort((a, b) => a[0] - b[0]) })),
  }, { replaceMerge: ['series'], lazyUpdate: true })
  initialized = true
}
function resize() { if (props.active) chart?.resize() }
onMounted(async () => {
  const [core, charts, components, renderers] = await Promise.all([import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers')])
  if (disposed || !container.value) return
  core.use([charts.ScatterChart, components.GridComponent, components.LegendComponent, components.TooltipComponent, components.DataZoomComponent, renderers.CanvasRenderer])
  chart = core.init(container.value, undefined, createTimeChartInitOptions(props.rows.length, { useDirtyRect: false }))
  observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize)
  observer?.observe(container.value); window.addEventListener('resize', resize)
  unsubscribe = subscribeNetConsoleChartTheme(render); render()
})
watch(() => props.rows, render)
watch(() => props.active, async active => { if (active) { await nextTick(); resize(); render() } else chart?.dispatchAction({ type: 'hideTip' }) })
onBeforeUnmount(() => { disposed = true; observer?.disconnect(); unsubscribe?.(); window.removeEventListener('resize', resize); chart?.dispose(); chart = undefined })
</script>
<template><div ref="container" class="ac-rssi-chart" role="img" :aria-label="t('ground.acv.rssi', 'RSSI 观测趋势')" /></template>
<style scoped>.ac-rssi-chart{height:300px;width:100%;min-width:0}</style>
