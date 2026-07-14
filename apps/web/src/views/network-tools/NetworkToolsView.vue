<script setup lang="ts">
import TcpPortTestPanel from '../../components/network-tools/TcpPortTestPanel.vue'
import TrafficTestView from './TrafficTestView.vue'
</script>

<template>
  <section class="network-tools-page">
    <header><h1>网络工具</h1><p>统一使用 Traffic Run、任务中心和本地 / Agent 执行端。</p></header>
    <el-tabs type="border-card">
      <el-tab-pane label="TCP 端口测试"><TcpPortTestPanel /></el-tab-pane>
      <el-tab-pane label="高频 Ping 与 iPerf" lazy><TrafficTestView /></el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.network-tools-page { display: flex; flex-direction: column; gap: 16px; }
header h1 { margin: 0 0 4px; }
header p { color: var(--el-text-color-secondary); margin: 0; }
</style>
