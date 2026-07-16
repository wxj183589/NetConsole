<script setup lang="ts">
import WirelessScanPanel from '../../components/network-tools/WirelessScanPanel.vue'
</script>

<template>
  <section class="wireless-scan-page">
    <WirelessScanPanel />
  </section>
</template>

<style scoped>
.wireless-scan-page { display: flex; flex-direction: column; gap: 16px; }
</style>
