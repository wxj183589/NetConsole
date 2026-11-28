<script setup lang="ts">
import NetworkToolboxPanel from '../../components/network-tools/NetworkToolboxPanel.vue'
</script>

<template>
  <section class="network-tools-page">
    <NetworkToolboxPanel />
  </section>
</template>

<style scoped>
.network-tools-page { display: flex; flex-direction: column; gap: 16px; }
</style>
