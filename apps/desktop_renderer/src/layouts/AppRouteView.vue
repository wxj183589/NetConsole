<template>
  <div class="app-route-viewport">
    <RouterView v-slot="{ Component, route: viewRoute }">
      <KeepAlive :include="cachedWorkspaceComponentNames" :max="10">
        <component
          :is="cachedRouteComponent(Component, workspace.routeCacheKey(viewRoute.fullPath))"
          :key="workspace.routeCacheKey(viewRoute.fullPath)"
        />
      </KeepAlive>
    </RouterView>
  </div>
</template>

<script setup lang="ts">
import { cloneVNode, computed, defineComponent, watch } from 'vue'
import type { Component, VNode } from 'vue'

import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const cachedRouteComponents = new Map<string, Component>()
const cachedWorkspaceComponentNames = computed(() => (
  workspace.cachedTabs.map((tab) => cacheComponentName(tab.cacheKey))
))

function cacheComponentName(cacheKey: string): string {
  return `WorkspacePage_${cacheKey.replace(/[^A-Za-z0-9_]/g, '_')}`
}

function cachedRouteComponent(component: VNode, cacheKey: string): Component {
  const existing = cachedRouteComponents.get(cacheKey)
  if (existing) return existing
  const cached = defineComponent({
    name: cacheComponentName(cacheKey),
    setup: () => () => cloneVNode(component),
  })
  cachedRouteComponents.set(cacheKey, cached)
  return cached
}

watch(
  () => new Set(workspace.tabs.map((tab) => tab.cacheKey)),
  (activeKeys) => {
    for (const key of cachedRouteComponents.keys()) {
      if (!activeKeys.has(key)) cachedRouteComponents.delete(key)
    }
  },
)
</script>
