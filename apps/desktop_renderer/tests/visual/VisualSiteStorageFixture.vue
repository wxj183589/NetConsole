<script setup lang="ts">
import NcConfirmDialog from '../../src/components/feedback/NcConfirmDialog.vue'
import SiteStoragePanel from '../../src/views/settings/SiteStoragePanel.vue'
</script>

<template>
  <main class="site-storage-fixture">
    <SiteStoragePanel />
    <NcConfirmDialog />
  </main>
</template>

<style scoped>
.site-storage-fixture {
  width: 100%;
  min-height: 100%;
  padding: 20px;
  overflow: auto;
}

@media (max-width: 640px) {
  .site-storage-fixture { padding: 10px; }
}
</style>
