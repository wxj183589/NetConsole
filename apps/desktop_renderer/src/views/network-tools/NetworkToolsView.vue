<script setup lang="ts">
import NetworkToolboxPanel from '../../components/network-tools/NetworkToolboxPanel.vue'
</script>

<template>
  <section class="network-tools-page">
    <header><h1>小工具与连通性检测</h1><p>IP 计算与 Ping 任务统一走 Python Application Service 和任务中心。</p></header>
    <NetworkToolboxPanel />
  </section>
</template>

<style scoped>
.network-tools-page { display: flex; flex-direction: column; gap: 16px; }
header h1 { margin: 0 0 4px; }
header p { color: var(--el-text-color-secondary); margin: 0; }
</style>
