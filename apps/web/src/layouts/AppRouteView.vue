<script setup lang="ts">
defineProps<{
  cachedComponentNames: string[]
}>()

const MAX_CACHED_PAGE_COUNT = 4
</script>

<template>
  <RouterView v-slot="{ Component, route: viewRoute }">
    <KeepAlive
      :include="cachedComponentNames"
      :max="MAX_CACHED_PAGE_COUNT"
    >
      <component
        :is="Component"
        v-if="viewRoute.meta.keepAlive"
        :key="String(viewRoute.name)"
      />
    </KeepAlive>
    <component
      :is="Component"
      v-if="!viewRoute.meta.keepAlive"
      :key="viewRoute.fullPath"
    />
  </RouterView>
</template>
