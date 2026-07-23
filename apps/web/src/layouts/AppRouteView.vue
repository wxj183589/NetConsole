<template>
  <RouterView v-slot="{ Component, route: viewRoute }">
    <KeepAlive :max="10">
      <component
        :is="Component"
        :key="workspace.activeCacheKey || viewRoute.fullPath"
      />
    </KeepAlive>
  </RouterView>
</template>

<script setup lang="ts">
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
</script>
