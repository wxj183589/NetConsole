<script setup lang="ts">
import { onMounted, ref } from 'vue'
import MeshBusinessSummary from '../../src/components/mesh-analysis/MeshBusinessSummary.vue'
import MeshRssiChart from '../../src/components/mesh-analysis/MeshRssiChart.vue'
import type { MeshPathChart } from '../../src/types/meshAnalysis'

const payload = ref<MeshPathChart | null>(null)
const elapsed = ref<number | null>(null)
let started = 0
onMounted(async () => {
  started = performance.now()
  payload.value = await (await fetch('/mesh-benchmark.json')).json()
})
function ready() {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (elapsed.value == null) elapsed.value = performance.now() - started
  }))
}
</script>

<template>
  <main>
    <h2>Mesh 原始日志分析 · 合成数据组件验收</h2>
    <MeshBusinessSummary session-id="synthetic" />
    <p>当前范围：{{ payload?.time_from }} ～ {{ payload?.time_to }} · {{ payload?.resolution_mode }}</p>
    <section class="chart-panel">
      <MeshRssiChart v-if="payload" :points="payload.points" :rssi-line="payload.rssi_line" :events="payload.events" :location-segments="payload.location_segments" @viewport-ready="ready" />
    </section>
    <output v-if="elapsed != null" data-render-ms :data-value="elapsed">首屏组件绘制 {{ elapsed.toFixed(1) }} ms</output>
  </main>
</template>

<style scoped>
main { padding: 20px; min-width: 0; }
h2 { font-size: 18px; }
.chart-panel { height: 440px; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 12px; }
</style>
