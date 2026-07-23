import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export const OPEN_PAGE_TABS_STORAGE_KEY = 'netconsole.web.open-page-tabs'
export const MAX_OPEN_PAGE_TABS = 12

export interface OpenPageTab {
  routeName: string
  path: string
  title: string
  fullTitle: string
  navigationId?: string
  closable: boolean
  keepAlive: boolean
  componentName?: string
  lastActiveAt: number
}

export type OpenPageTabDefinition = Omit<OpenPageTab, 'lastActiveAt'>

interface PersistedOpenPageTab {
  routeName: string
  path: string
  title: string
  navigationId?: string
}

interface PersistedOpenPageTabs {
  version: 1
  tabs: PersistedOpenPageTab[]
  activeRouteName: string | null
}

export interface OpenPageTabResult {
  accepted: boolean
  opened: boolean
  evictedRouteName?: string
}

const dashboardTab: OpenPageTabDefinition = {
  routeName: 'dashboard',
  path: '/',
  title: 'Dashboard',
  fullTitle: 'Dashboard',
  navigationId: 'dashboard',
  closable: false,
  keepAlive: false,
}

function readPersistedTabs(): PersistedOpenPageTabs | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const value = JSON.parse(sessionStorage.getItem(OPEN_PAGE_TABS_STORAGE_KEY) || 'null') as Partial<PersistedOpenPageTabs> | null
    if (!value || value.version !== 1 || !Array.isArray(value.tabs)) return null
    const tabs = value.tabs.flatMap((item) => {
      if (
        !item
        || typeof item.routeName !== 'string'
        || typeof item.path !== 'string'
        || typeof item.title !== 'string'
      ) return []
      return [{
        routeName: item.routeName,
        path: item.path,
        title: item.title,
        ...(typeof item.navigationId === 'string' ? { navigationId: item.navigationId } : {}),
      }]
    })
    return {
      version: 1,
      tabs,
      activeRouteName: typeof value.activeRouteName === 'string' ? value.activeRouteName : null,
    }
  } catch {
    return null
  }
}

export const useOpenPageTabsStore = defineStore('open-page-tabs', () => {
  const tabs = ref<OpenPageTab[]>([])
  const activeRouteName = ref<string | null>(null)
  const restored = ref(false)
  let activityClock = 0

  const activeTab = computed(() => (
    tabs.value.find((item) => item.routeName === activeRouteName.value) ?? null
  ))
  const cachedComponentNames = computed(() => (
    [...new Set(tabs.value.flatMap((item) => (
      item.keepAlive && item.componentName ? [item.componentName] : []
    )))]
  ))

  function nextActivityAt(): number {
    activityClock = Math.max(Date.now(), activityClock + 1)
    return activityClock
  }

  function persist(): void {
    if (typeof sessionStorage === 'undefined') return
    const payload: PersistedOpenPageTabs = {
      version: 1,
      tabs: tabs.value.map((item) => ({
        routeName: item.routeName,
        path: item.path,
        title: item.title,
        ...(item.navigationId ? { navigationId: item.navigationId } : {}),
      })),
      activeRouteName: activeRouteName.value,
    }
    try {
      sessionStorage.setItem(OPEN_PAGE_TABS_STORAGE_KEY, JSON.stringify(payload))
    } catch {
      // 标签状态不是业务数据；存储不可用时继续使用当前内存状态。
    }
  }

  function createTab(definition: OpenPageTabDefinition, active = false): OpenPageTab {
    return {
      ...definition,
      lastActiveAt: active ? nextActivityAt() : 0,
    }
  }

  function ensureDashboard(): void {
    const existing = tabs.value.find((item) => item.routeName === dashboardTab.routeName)
    tabs.value = [
      existing ? { ...existing, ...dashboardTab, closable: false } : createTab(dashboardTab),
      ...tabs.value.filter((item) => item.routeName !== dashboardTab.routeName),
    ]
  }

  function restoreTabs(
    resolveTab: (tab: PersistedOpenPageTab) => OpenPageTabDefinition | null,
  ): void {
    if (restored.value) return
    restored.value = true
    const persisted = readPersistedTabs()
    const restoredTabs = (persisted?.tabs ?? []).flatMap((item) => {
      const resolved = resolveTab(item)
      return resolved ? [createTab(resolved)] : []
    })
    tabs.value = restoredTabs
    ensureDashboard()
    if (tabs.value.length > MAX_OPEN_PAGE_TABS) {
      tabs.value = tabs.value.slice(0, MAX_OPEN_PAGE_TABS)
    }
    activeRouteName.value = tabs.value.some((item) => item.routeName === persisted?.activeRouteName)
      ? persisted?.activeRouteName ?? null
      : null
    persist()
  }

  function evictOldestOrdinaryTab(): string | undefined {
    const candidate = tabs.value
      .filter((item) => (
        item.closable
        && !item.keepAlive
        && item.routeName !== activeRouteName.value
      ))
      .sort((left, right) => left.lastActiveAt - right.lastActiveAt)[0]
    if (!candidate) return undefined
    tabs.value = tabs.value.filter((item) => item.routeName !== candidate.routeName)
    return candidate.routeName
  }

  function openOrActivate(definition: OpenPageTabDefinition): OpenPageTabResult {
    const normalized = definition.routeName === dashboardTab.routeName
      ? { ...definition, ...dashboardTab }
      : definition
    const existingIndex = tabs.value.findIndex((item) => item.routeName === normalized.routeName)
    if (existingIndex >= 0) {
      tabs.value[existingIndex] = {
        ...tabs.value[existingIndex],
        ...normalized,
        lastActiveAt: nextActivityAt(),
      }
      activeRouteName.value = normalized.routeName
      ensureDashboard()
      persist()
      return { accepted: true, opened: false }
    }

    let evictedRouteName: string | undefined
    if (tabs.value.length >= MAX_OPEN_PAGE_TABS) {
      evictedRouteName = evictOldestOrdinaryTab()
      if (!evictedRouteName) return { accepted: false, opened: false }
    }
    tabs.value.push(createTab(normalized, true))
    activeRouteName.value = normalized.routeName
    ensureDashboard()
    persist()
    return { accepted: true, opened: true, ...(evictedRouteName ? { evictedRouteName } : {}) }
  }

  function setActiveRoute(routeName: string | null): void {
    if (!routeName || !tabs.value.some((item) => item.routeName === routeName)) {
      activeRouteName.value = null
      persist()
      return
    }
    activeRouteName.value = routeName
    const tab = tabs.value.find((item) => item.routeName === routeName)
    if (tab) tab.lastActiveAt = nextActivityAt()
    persist()
  }

  function fallbackFor(routeName: string): OpenPageTab {
    const index = tabs.value.findIndex((item) => item.routeName === routeName)
    if (index > 0) return tabs.value[index - 1]
    if (index >= 0 && index + 1 < tabs.value.length) return tabs.value[index + 1]
    return tabs.value.find((item) => item.routeName === dashboardTab.routeName)
      ?? createTab(dashboardTab)
  }

  function removeTabs(routeNames: Iterable<string>): string[] {
    const requested = new Set(routeNames)
    const removed = tabs.value
      .filter((item) => item.closable && requested.has(item.routeName))
      .map((item) => item.routeName)
    if (!removed.length) return []
    const removedSet = new Set(removed)
    tabs.value = tabs.value.filter((item) => !removedSet.has(item.routeName))
    ensureDashboard()
    if (activeRouteName.value && removedSet.has(activeRouteName.value)) {
      activeRouteName.value = dashboardTab.routeName
    }
    persist()
    return removed
  }

  return {
    tabs,
    activeRouteName,
    activeTab,
    cachedComponentNames,
    restoreTabs,
    openOrActivate,
    setActiveRoute,
    fallbackFor,
    removeTabs,
  }
})
