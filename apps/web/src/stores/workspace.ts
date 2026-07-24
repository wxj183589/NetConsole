import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Router } from 'vue-router'

import {
  WORKSPACE_DEFAULT_ROUTE,
  canonicalizeWorkspaceRoute,
  sanitizeWorkspaceTitle,
} from '../workspace/route-identity'
import {
  WORKSPACE_SCHEMA_VERSION,
  loadWorkspace,
  saveWorkspace,
} from '../workspace/persistence'
import {
  WORKSPACE_TITLE_EVENT,
  openWorkspaceWindow,
  updateDesktopWorkspaceTitle,
} from '../workspace/runtime'
import type {
  CanonicalWorkspaceRoute,
  WorkspaceTab,
  WorkspaceWindowState,
} from '../workspace/types'

const SAVE_DEBOUNCE_MS = 250

export const useWorkspaceStore = defineStore('workspace', () => {
  const windowId = ref('browser-main')
  const tabs = ref<WorkspaceTab[]>([])
  const activeTabId = ref('')
  const initialized = ref(false)
  let router: Router | undefined
  let removeAfterEach: (() => void) | undefined
  let saveTimer: ReturnType<typeof setTimeout> | undefined

  const activeTab = computed(() => (
    tabs.value.find((tab) => tab.id === activeTabId.value) || null
  ))
  const activeCacheKey = computed(() => activeTab.value?.cacheKey || '')

  function routeCacheKey(routeFullPath: string): string {
    return tabs.value.find((tab) => tab.routeFullPath === routeFullPath)?.cacheKey || routeFullPath
  }

  async function initialize(nextRouter: Router): Promise<void> {
    if (initialized.value) return
    router = nextRouter
    const restored = await loadWorkspace(nextRouter)
    windowId.value = restored.windowId
    if (restored.snapshot) {
      restoreSnapshot(restored.snapshot)
    } else {
      const initial = safeCanonical(nextRouter.currentRoute.value.fullPath)
      const tab = createTab(initial)
      tabs.value = [tab]
      activeTabId.value = tab.id
    }
    sortTabs()
    removeAfterEach = nextRouter.afterEach((to) => {
      synchronizeRoute(to.fullPath)
    })
    initialized.value = true
    const target = activeTab.value?.routeFullPath || WORKSPACE_DEFAULT_ROUTE
    if (nextRouter.currentRoute.value.fullPath !== target) {
      await nextRouter.replace(target)
    }
    syncTitle()
    scheduleSave()
    window.addEventListener('beforeunload', flushPersistence)
    window.addEventListener(WORKSPACE_TITLE_EVENT, handleTitleEvent)
  }

  function dispose(): void {
    removeAfterEach?.()
    removeAfterEach = undefined
    window.removeEventListener('beforeunload', flushPersistence)
    window.removeEventListener(WORKSPACE_TITLE_EVENT, handleTitleEvent)
    flushPersistence()
  }

  async function openRoute(
    routeFullPath: string,
    options: { duplicate?: boolean; activate?: boolean } = {},
  ): Promise<WorkspaceTab> {
    const canonical = safeCanonical(routeFullPath)
    if (!options.duplicate && canonical.policy.identity !== 'multiple') {
      const existing = tabs.value.find((tab) => tab.identityKey === canonical.identityKey)
      if (existing) {
        if (options.activate !== false) await activateTab(existing.id)
        return existing
      }
    }
    const tab = createTab(canonical, Boolean(options.duplicate))
    tabs.value.push(tab)
    sortTabs()
    if (options.activate !== false) await activateTab(tab.id)
    scheduleSave()
    return tab
  }

  async function openOrActivateRoute(routeFullPath: string): Promise<WorkspaceTab> {
    return openRoute(routeFullPath)
  }

  async function activateTab(tabId: string): Promise<void> {
    const tab = tabs.value.find((candidate) => candidate.id === tabId)
    if (!tab) return
    activeTabId.value = tab.id
    tab.lastActivatedAt = Date.now()
    syncTitle()
    scheduleSave()
    if (router && router.currentRoute.value.fullPath !== tab.routeFullPath) {
      await router.push(tab.routeFullPath)
    }
  }

  async function closeTab(tabId: string): Promise<void> {
    const index = tabs.value.findIndex((tab) => tab.id === tabId)
    if (index < 0 || tabs.value[index].pinned) return
    const closingActive = activeTabId.value === tabId
    tabs.value.splice(index, 1)
    if (!closingActive) {
      scheduleSave()
      return
    }
    if (tabs.value.length === 0) {
      const fallback = createTab(safeCanonical(WORKSPACE_DEFAULT_ROUTE))
      tabs.value = [fallback]
      activeTabId.value = fallback.id
    } else {
      activeTabId.value = tabs.value[Math.max(0, index - 1)]?.id || tabs.value[0].id
    }
    syncTitle()
    scheduleSave()
    if (router && activeTab.value) await router.replace(activeTab.value.routeFullPath)
  }

  async function closeOtherTabs(tabId: string): Promise<void> {
    const target = tabs.value.find((tab) => tab.id === tabId)
    if (!target) return
    tabs.value = tabs.value.filter((tab) => tab.id === tabId || tab.pinned)
    activeTabId.value = target.id
    sortTabs()
    syncTitle()
    scheduleSave()
    if (router?.currentRoute.value.fullPath !== target.routeFullPath) {
      await router?.replace(target.routeFullPath)
    }
  }

  function closeTabsToRight(tabId: string): void {
    const index = tabs.value.findIndex((tab) => tab.id === tabId)
    if (index < 0) return
    const removedIds = new Set(
      tabs.value.slice(index + 1).filter((tab) => !tab.pinned).map((tab) => tab.id),
    )
    tabs.value = tabs.value.filter((tab) => !removedIds.has(tab.id))
    if (removedIds.has(activeTabId.value)) void activateTab(tabId)
    scheduleSave()
  }

  async function duplicateTab(tabId = activeTabId.value): Promise<WorkspaceTab | null> {
    const source = tabs.value.find((tab) => tab.id === tabId)
    if (!source) return null
    return openRoute(source.routeFullPath, { duplicate: true })
  }

  function pinTab(tabId: string): void {
    const tab = tabs.value.find((candidate) => candidate.id === tabId)
    if (!tab) return
    tab.pinned = true
    sortTabs()
    scheduleSave()
  }

  function unpinTab(tabId: string): void {
    const tab = tabs.value.find((candidate) => candidate.id === tabId)
    if (!tab) return
    tab.pinned = false
    sortTabs()
    scheduleSave()
  }

  function updateActiveTabRoute(routeFullPath: string): void {
    synchronizeRoute(routeFullPath)
  }

  function updateTabTitle(title: string, tabId = activeTabId.value): void {
    const tab = tabs.value.find((candidate) => candidate.id === tabId)
    if (!tab) return
    tab.title = sanitizeWorkspaceTitle(title)
    if (tab.id === activeTabId.value) syncTitle()
    scheduleSave()
  }

  async function popOutTab(tabId = activeTabId.value): Promise<{ success: boolean; error?: string }> {
    const tab = tabs.value.find((candidate) => candidate.id === tabId)
    if (!tab) return { success: false, error: '当前没有可打开的标签' }
    return openWorkspaceWindow(tab.routeFullPath, tab.title)
  }

  async function createWorkspaceWindow(): Promise<{ success: boolean; error?: string }> {
    return openWorkspaceWindow(WORKSPACE_DEFAULT_ROUTE, 'Dashboard')
  }

  function restoreSnapshot(snapshot: WorkspaceWindowState): void {
    windowId.value = snapshot.windowId
    tabs.value = snapshot.tabs.map((tab) => ({ ...tab }))
    activeTabId.value = snapshot.activeTabId
  }

  function createSnapshot(): WorkspaceWindowState {
    return {
      schemaVersion: WORKSPACE_SCHEMA_VERSION,
      windowId: windowId.value,
      activeTabId: activeTabId.value,
      tabs: tabs.value.map((tab) => ({
        ...tab,
        title: sanitizeWorkspaceTitle(tab.title),
      })),
    }
  }

  function synchronizeRoute(routeFullPath: string): void {
    if (!initialized.value || !router) return
    const canonical = safeCanonical(routeFullPath)
    const current = activeTab.value
    if (!current) {
      const tab = createTab(canonical)
      tabs.value.push(tab)
      activeTabId.value = tab.id
      scheduleSave()
      return
    }
    const conflict = tabs.value.find((tab) => (
      tab.id !== current.id && tab.identityKey === canonical.identityKey
    ))
    if (conflict && canonical.policy.identity !== 'multiple') {
      if (!current.pinned) tabs.value = tabs.value.filter((tab) => tab.id !== current.id)
      activeTabId.value = conflict.id
      conflict.routeFullPath = canonical.routeFullPath
      conflict.lastActivatedAt = Date.now()
    } else {
      Object.assign(current, {
        ...(canonical.routeName ? { routeName: canonical.routeName } : {}),
        routeFullPath: canonical.routeFullPath,
        identityKey: canonical.identityKey,
        title: current.routeName === canonical.routeName ? current.title : canonical.title,
        lastActivatedAt: Date.now(),
      })
    }
    syncTitle()
    scheduleSave()
  }

  function safeCanonical(routeFullPath: string): CanonicalWorkspaceRoute {
    if (!router) throw new Error('工作区路由尚未初始化')
    try {
      return canonicalizeWorkspaceRoute(router, routeFullPath)
    } catch {
      return canonicalizeWorkspaceRoute(router, WORKSPACE_DEFAULT_ROUTE)
    }
  }

  function createTab(
    canonical: CanonicalWorkspaceRoute,
    duplicate = false,
  ): WorkspaceTab {
    const now = Date.now()
    const id = createId('tab')
    const instanceId = createId('instance')
    return {
      id,
      instanceId,
      ...(canonical.routeName ? { routeName: canonical.routeName } : {}),
      routeFullPath: canonical.routeFullPath,
      title: canonical.title,
      identityKey: duplicate
        ? `${canonical.identityKey}:instance:${instanceId}`
        : canonical.identityKey,
      cacheKey: `${canonical.routeName || 'route'}:${instanceId}`,
      pinned: false,
      openedAt: now,
      lastActivatedAt: now,
    }
  }

  function sortTabs(): void {
    tabs.value = tabs.value
      .map((tab, index) => ({ tab, index }))
      .sort((left, right) => (
        Number(right.tab.pinned) - Number(left.tab.pinned)
        || left.index - right.index
      ))
      .map(({ tab }) => tab)
  }

  function syncTitle(): void {
    updateDesktopWorkspaceTitle(activeTab.value?.title || 'NetConsole')
  }

  function handleTitleEvent(event: Event): void {
    const title = (event as CustomEvent<unknown>).detail
    if (typeof title === 'string') updateTabTitle(title)
  }

  function scheduleSave(): void {
    if (!initialized.value) return
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      saveTimer = undefined
      void saveWorkspace(createSnapshot())
    }, SAVE_DEBOUNCE_MS)
  }

  function flushPersistence(): void {
    if (!initialized.value) return
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = undefined
    void saveWorkspace(createSnapshot())
  }

  return {
    windowId,
    tabs,
    activeTabId,
    initialized,
    activeTab,
    activeCacheKey,
    routeCacheKey,
    initialize,
    dispose,
    openRoute,
    openOrActivateRoute,
    activateTab,
    closeTab,
    closeOtherTabs,
    closeTabsToRight,
    duplicateTab,
    pinTab,
    unpinTab,
    updateActiveTabRoute,
    updateTabTitle,
    popOutTab,
    createWorkspaceWindow,
    restoreSnapshot,
    createSnapshot,
    flushPersistence,
  }
})

function createId(prefix: string): string {
  const random = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  return `${prefix}-${random}`
}
