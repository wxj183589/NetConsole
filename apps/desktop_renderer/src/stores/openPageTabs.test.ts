// @vitest-environment happy-dom

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MAX_OPEN_PAGE_TABS,
  OPEN_PAGE_TABS_STORAGE_KEY,
  useOpenPageTabsStore,
  type OpenPageTabDefinition,
} from './openPageTabs'

function tab(
  routeName: string,
  overrides: Partial<OpenPageTabDefinition> = {},
): OpenPageTabDefinition {
  return {
    routeName,
    path: `/${routeName}`,
    title: routeName,
    fullTitle: `模块 / ${routeName}`,
    navigationId: routeName,
    closable: routeName !== 'dashboard',
    keepAlive: false,
    ...overrides,
  }
}

beforeEach(() => {
  sessionStorage.clear()
  setActivePinia(createPinia())
  vi.restoreAllMocks()
})

describe('open page tabs store', () => {
  it('keeps Dashboard fixed and reuses the route-name tab across query changes', () => {
    const store = useOpenPageTabsStore()
    store.restoreTabs(() => null)

    store.openOrActivate(tab('mesh-analysis', {
      path: '/rail-transit/mesh-analysis?session=first',
      title: 'MR 原始 MESH 日志分析',
      keepAlive: true,
      componentName: 'MeshAnalysisView',
    }))
    store.openOrActivate(tab('mesh-analysis', {
      path: '/rail-transit/mesh-analysis?session=second',
      title: 'MR 原始 MESH 日志分析',
      keepAlive: true,
      componentName: 'MeshAnalysisView',
    }))

    expect(store.tabs.map((item) => item.routeName)).toEqual(['dashboard', 'mesh-analysis'])
    expect(store.tabs[1].path).toContain('session=second')
    expect(store.cachedComponentNames).toEqual(['MeshAnalysisView'])

    expect(sessionStorage.getItem(OPEN_PAGE_TABS_STORAGE_KEY)).toBeNull()
  })

  it('clears legacy tab data and always initializes Dashboard', () => {
    sessionStorage.setItem(OPEN_PAGE_TABS_STORAGE_KEY, JSON.stringify({
      version: 1,
      tabs: [
        { routeName: 'dashboard', path: '/', title: 'Dashboard', navigationId: 'dashboard' },
        { routeName: 'mesh-analysis', path: '/rail-transit/mesh-analysis', title: 'MESH', navigationId: 'rail.mesh-analysis' },
        { routeName: 'removed-page', path: '/removed', title: '旧页面' },
      ],
      activeRouteName: 'mesh-analysis',
    }))
    const store = useOpenPageTabsStore()
    const resolver = vi.fn(() => tab('mesh-analysis'))
    store.restoreTabs(resolver)

    expect(resolver).not.toHaveBeenCalled()
    expect(store.tabs.map((item) => item.routeName)).toEqual(['dashboard'])
    expect(store.activeRouteName).toBe('dashboard')
    expect(store.cachedComponentNames).toEqual([])
    expect(sessionStorage.getItem(OPEN_PAGE_TABS_STORAGE_KEY)).toBeNull()
  })

  it('evicts the least recently used ordinary tab at the limit and never auto-evicts MESH', () => {
    const store = useOpenPageTabsStore()
    store.restoreTabs(() => null)
    store.openOrActivate(tab('mesh-analysis', {
      keepAlive: true,
      componentName: 'MeshAnalysisView',
    }))
    for (let index = 0; index < MAX_OPEN_PAGE_TABS - 2; index += 1) {
      store.openOrActivate(tab(`ordinary-${index}`))
    }
    store.setActiveRoute('mesh-analysis')

    const result = store.openOrActivate(tab('ordinary-new'))

    expect(result).toEqual({
      accepted: true,
      opened: true,
      evictedRouteName: 'ordinary-0',
    })
    expect(store.tabs).toHaveLength(MAX_OPEN_PAGE_TABS)
    expect(store.tabs.some((item) => item.routeName === 'mesh-analysis')).toBe(true)
    expect(store.tabs.some((item) => item.routeName === 'ordinary-0')).toBe(false)
  })

  it('removes the MESH cache allowlist entry only when its tab closes', () => {
    const store = useOpenPageTabsStore()
    store.restoreTabs(() => null)
    store.openOrActivate(tab('mesh-analysis', {
      keepAlive: true,
      componentName: 'MeshAnalysisView',
    }))
    store.openOrActivate(tab('rail-transit-base-data'))

    expect(store.cachedComponentNames).toEqual(['MeshAnalysisView'])
    expect(store.fallbackFor('mesh-analysis').routeName).toBe('dashboard')

    store.removeTabs(['mesh-analysis'])

    expect(store.cachedComponentNames).toEqual([])
    expect(store.tabs.map((item) => item.routeName)).toEqual(['dashboard', 'rail-transit-base-data'])
  })
})
