<script setup lang="ts">
import { isFeatureVisible } from '../../features'
import NetworkToolboxPanel from '../../components/network-tools/NetworkToolboxPanel.vue'
import TcpPortTestPanel from '../../components/network-tools/TcpPortTestPanel.vue'
import WirelessScanPanel from '../../components/network-tools/WirelessScanPanel.vue'
import TrafficTestView from './TrafficTestView.vue'
</script>

<template>
  <section class="network-tools-page">
    <header><h1>网络工具</h1><p>算法、连通性、Traffic 与无线扫描统一从 Web 进入。</p></header>
    <NetworkToolboxPanel />
    <el-tabs type="border-card">
      <el-tab-pane label="TCP 端口测试"><TcpPortTestPanel /></el-tab-pane>
      <el-tab-pane label="高频 Ping 与 iPerf" lazy><TrafficTestView /></el-tab-pane>
      <el-tab-pane v-if="isFeatureVisible('web.network_tools_wireless_scan')" label="无线扫描" lazy><WirelessScanPanel /></el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.network-tools-page { display: flex; flex-direction: column; gap: 16px; }
header h1 { margin: 0 0 4px; }
header p { color: var(--el-text-color-secondary); margin: 0; }
</style>
