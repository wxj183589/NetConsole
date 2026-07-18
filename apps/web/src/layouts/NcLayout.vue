<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  description?: string
  eyebrow?: string
  maxWidth?: string
}>(), {
  title: '',
  description: '',
  eyebrow: '',
  maxWidth: '1680px',
})
</script>

<template>
  <section class="nc-layout" :style="{ maxWidth }">
    <header v-if="title || description || eyebrow || $slots.header || $slots.actions" class="nc-layout__header">
      <slot name="header">
        <div class="nc-layout__heading">
          <p v-if="eyebrow" class="nc-layout__eyebrow">{{ eyebrow }}</p>
          <h1 v-if="title">{{ title }}</h1>
          <p v-if="description" class="nc-layout__description">{{ description }}</p>
        </div>
      </slot>
      <div v-if="$slots.actions" class="nc-layout__actions"><slot name="actions" /></div>
    </header>
    <div v-if="$slots.summary" class="nc-layout__summary"><slot name="summary" /></div>
    <div class="nc-layout__body"><slot /></div>
    <footer v-if="$slots.footer" class="nc-layout__footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.nc-layout { display: flex; flex-direction: column; gap: var(--nc-card-gap); width: 100%; min-width: 0; margin: 0 auto; }
.nc-layout__header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--nc-space-4); }
.nc-layout__heading { min-width: 0; }
.nc-layout__eyebrow { margin: 0 0 var(--nc-space-1); color: var(--nc-primary); font-size: var(--nc-font-size-xs); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.nc-layout__heading h1 { margin: 0; color: var(--nc-text-primary); font-size: var(--nc-font-size-title); line-height: 1.35; }
.nc-layout__description { margin: var(--nc-space-1) 0 0; color: var(--nc-text-secondary); font-size: var(--nc-font-size-sm); }
.nc-layout__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--nc-space-2); }
.nc-layout__summary, .nc-layout__body, .nc-layout__footer { min-width: 0; }

@media (max-width: 850px) {
  .nc-layout__header { flex-direction: column; }
  .nc-layout__actions { justify-content: flex-start; }
}
</style>
