<script setup lang="ts">
defineProps<{
  loading?: boolean
}>()
</script>

<template>
  <section class="nc-log-workspace" :aria-busy="loading || undefined">
    <header v-if="$slots.header" class="nc-log-workspace__header">
      <slot name="header" />
    </header>
    <div v-if="$slots.summary" class="nc-log-workspace__summary">
      <slot name="summary" />
    </div>
    <div v-if="$slots.actions" class="nc-log-workspace__actions">
      <slot name="actions" />
    </div>
    <div class="nc-log-workspace__table">
      <slot />
    </div>
    <footer v-if="$slots.pagination" class="nc-log-workspace__pagination">
      <slot name="pagination" />
    </footer>
  </section>
</template>

<style scoped>
.nc-log-workspace {
  display: flex;
  flex: 1;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.nc-log-workspace__header,
.nc-log-workspace__summary,
.nc-log-workspace__actions,
.nc-log-workspace__pagination {
  flex: none;
  min-width: 0;
}

.nc-log-workspace__table {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.nc-log-workspace__pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-height: 42px;
  padding-top: 8px;
}
</style>
