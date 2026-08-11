<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  subtitle?: string
  padding?: boolean
  interactive?: boolean
}>(), {
  title: '',
  subtitle: '',
  padding: true,
  interactive: false,
})
</script>

<template>
  <section :class="['nc-card', { 'nc-card--padded': padding, 'nc-card--interactive': interactive }]">
    <header v-if="title || subtitle || $slots.header || $slots.actions" class="nc-card__header">
      <slot name="header">
        <div class="nc-card__heading">
          <h2 v-if="title">{{ title }}</h2>
          <p v-if="subtitle">{{ subtitle }}</p>
        </div>
      </slot>
      <div v-if="$slots.actions" class="nc-card__actions"><slot name="actions" /></div>
    </header>
    <div class="nc-card__body"><slot /></div>
    <footer v-if="$slots.footer" class="nc-card__footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.nc-card {
  min-width: 0;
  color: var(--nc-text-primary);
  background: var(--nc-bg-card);
  border: 1px solid var(--nc-border);
  border-radius: var(--nc-radius-base);
  box-shadow: var(--nc-shadow-card);
}
.nc-card--padded { padding: var(--nc-card-padding); }
.nc-card--interactive { transition: border-color var(--nc-transition-fast), box-shadow var(--nc-transition-fast); }
.nc-card--interactive:hover { border-color: var(--nc-primary); box-shadow: var(--nc-shadow-floating); }
.nc-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--nc-space-4); margin-bottom: var(--nc-space-4); }
.nc-card__heading { min-width: 0; }
.nc-card__heading h2 { margin: 0; font-size: 17px; line-height: 1.4; }
.nc-card__heading p { margin: var(--nc-space-1) 0 0; color: var(--nc-text-secondary); font-size: var(--nc-font-size-xs); }
.nc-card__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--nc-space-2); }
.nc-card__body { min-width: 0; }
.nc-card__footer { margin-top: var(--nc-space-4); padding-top: var(--nc-space-3); border-top: 1px solid var(--nc-border-light); }
</style>
