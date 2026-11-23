<template>
  <div class="app-route-viewport">
    <ConsoleWorkspaceView v-if="consoleOpened" :key="consoleGeneration" v-show="isConsoleRoute" :workspace-visible="isConsoleRoute" />
    <RouterView v-slot="{ Component, route: viewRoute }">
      <KeepAlive :include="cachedWorkspaceComponentNames" :max="10">
        <component
          v-if="viewRoute.name !== 'device-console'"
          :is="cachedRouteComponent(Component, workspace.routeCacheKey(viewRoute.fullPath))"
          :key="workspace.routeCacheKey(viewRoute.fullPath)"
        />
      </KeepAlive>
    </RouterView>
  </div>
</template>

<script setup lang="ts">
import { cloneVNode, computed, defineAsyncComponent, defineComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { Component, VNode } from 'vue'

import { useWorkspaceStore } from '../stores/workspace'
import { CURRENT_SITE_CHANGED_EVENT } from '../workspace/site-switch'

const workspace = useWorkspaceStore()
const ConsoleWorkspaceView = defineAsyncComponent(() => import('../views/console/ConsoleWorkspaceView.vue'))
const route = useRoute()
const isConsoleRoute = computed(() => route.name === 'device-console')
const consoleOpened = ref(isConsoleRoute.value)
const consoleGeneration = ref(0)
function clearOldSiteConsole() { consoleGeneration.value++; consoleOpened.value = isConsoleRoute.value }
onMounted(() => window.addEventListener(CURRENT_SITE_CHANGED_EVENT, clearOldSiteConsole))
onBeforeUnmount(() => window.removeEventListener(CURRENT_SITE_CHANGED_EVENT, clearOldSiteConsole))
watch(isConsoleRoute, value => { if (value) consoleOpened.value = true })
type CachedRouteComponent = {
  sourceType: VNode['type']
  wrapper: Component
}

const cachedRouteComponents = new Map<string, CachedRouteComponent>()
const cachedWorkspaceComponentNames = computed(() => (
  workspace.cachedTabs.map((tab) => cacheComponentName(tab.cacheKey))
))

function cacheComponentName(cacheKey: string): string {
  return `WorkspacePage_${cacheKey.replace(/[^A-Za-z0-9_]/g, '_')}`
}

function cachedRouteComponent(component: VNode, cacheKey: string): Component {
  const existing = cachedRouteComponents.get(cacheKey)
  if (existing?.sourceType === component.type) return existing.wrapper
  const cached = defineComponent({
    name: cacheComponentName(cacheKey),
    setup: () => () => cloneVNode(component),
  })
  cachedRouteComponents.set(cacheKey, { sourceType: component.type, wrapper: cached })
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
