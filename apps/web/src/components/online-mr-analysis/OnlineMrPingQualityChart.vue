<script setup lang="ts">
import OnlineMrAnalysisChart from './OnlineMrAnalysisChart.vue'
import type { OnlineMrMetricSeries } from '../../types/onlineMr'
import type { MeshChartViewport, MeshSharedPointerChange, MeshSharedTimeDomain } from '../mesh-analysis/meshChartViewport'

const props = withDefaults(defineProps<{
  lossSeries: OnlineMrMetricSeries[]
  rttSeries: OnlineMrMetricSeries[]
  events?: Array<{ time: string; label: string; severity?: string }>
  viewport?: MeshChartViewport | null
  cursorTime?: string | null
  selectedTime?: string | null
  sharedTimeDomain?: MeshSharedTimeDomain | null
  active?: boolean
}>(), {
  events: () => [],
  viewport: null,
  cursorTime: null,
  selectedTime: null,
  sharedTimeDomain: null,
  active: true,
})

const emit = defineEmits<{
  'update:viewport': [viewport: MeshChartViewport]
  'pointer-change': [pointer: MeshSharedPointerChange]
  'select-time': [time: string]
}>()
</script>

<template>
  <div class="ping-quality-chart">
    <section class="ping-quality-chart__pane">
      <OnlineMrAnalysisChart
        :series="props.lossSeries"
        title="Ping 丢包率"
        unit="%"
        tooltip-kind="ping-loss"
        :events="props.events"
        :viewport="props.viewport"
        :cursor-time="props.cursorTime"
        :selected-time="props.selectedTime"
        :shared-time-domain="props.sharedTimeDomain"
        :active="props.active"
        @update:viewport="emit('update:viewport', $event)"
        @pointer-change="emit('pointer-change', $event)"
        @select-time="emit('select-time', $event)"
      />
    </section>
    <section class="ping-quality-chart__pane">
      <OnlineMrAnalysisChart
        :series="props.rttSeries"
        title="Ping RTT"
        unit="ms"
        tooltip-kind="ping-rtt"
        :events="props.events"
        :viewport="props.viewport"
        :cursor-time="props.cursorTime"
        :selected-time="props.selectedTime"
        :shared-time-domain="props.sharedTimeDomain"
        :active="props.active"
        @update:viewport="emit('update:viewport', $event)"
        @pointer-change="emit('pointer-change', $event)"
        @select-time="emit('select-time', $event)"
      />
    </section>
  </div>
</template>

<style scoped>
.ping-quality-chart{display:flex;min-width:0;min-height:0;height:100%;flex-direction:column;gap:8px}
.ping-quality-chart__pane{display:flex;min-width:0;min-height:220px;flex:1 1 0;overflow:hidden;border-top:1px solid var(--el-border-color-lighter)}
</style>
