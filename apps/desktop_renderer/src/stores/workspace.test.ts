// @vitest-environment happy-dom

import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceStore } from './workspace'

function createTestRouter(initial = '/') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: {}, meta: { title: 'Dashboard' } },
      { path: '/devices', name: 'devices', component: {}, meta: { title: '设备管理' } },
      { path: '/rail-transit/base-data', name: 'rail-transit-base-data', component: {}, meta: { title: '基础资料' } },
      { path: '/devices/:deviceId', name: 'device-detail', component: {}, meta: {
        title: '设备详情',
        workspace: { identity: 'resource', resourceParams: ['deviceId'], allowDuplicate: true },
      } },
      { path: '/mesh', name: 'mesh', component: {}, meta: {
        title: 'MESH',
        workspace: { identity: 'singleton', cache: true, allowDuplicate: false },
      } },
      { path: '/settings', name: 'system-settings', component: {}, meta: { title: '系统设置' } },
    ],
  })
  return router.push(initial).then(() => router)
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
})

describe('workspace store', () => {
  it('activates singleton tabs, separates resources, and duplicates instances', async () => {
    const router = await createTestRouter()
    const store = useWorkspaceStore()
    await store.initialize(router)

    const devices = await store.openOrActivateRoute('/devices')
    await store.openOrActivateRoute('/devices')
    expect(store.tabs.filter((tab) => tab.identityKey === devices.identityKey)).toHaveLength(1)

    const deviceA = await store.openOrActivateRoute('/devices/device-a')
    const deviceB = await store.openOrActivateRoute('/devices/device-b')
    expect(deviceA.identityKey).not.toBe(deviceB.identityKey)

    const duplicate = await store.duplicateTab(deviceB.id)
    expect(duplicate?.instanceId).not.toBe(deviceB.instanceId)
    expect(duplicate?.cacheKey).not.toBe(deviceB.cacheKey)
  })

  it('atomically reuses the MESH tab for a new session and keeps its cache key stable', async () => {
    const router = await createTestRouter()
    const store = useWorkspaceStore()
    await store.initialize(router)
    const mesh = await store.openOrActivateRoute('/mesh?z=2&session_id=session-1&a=1')
    store.updateTabTitle('MESH：列车06-MR-CT', mesh.id)
    const initialCacheKey = mesh.cacheKey
    await store.openOrActivateRoute('/mesh?session_id=session-2')

    expect(store.tabs.filter((tab) => tab.identityKey === mesh.identityKey)).toHaveLength(1)
    expect(mesh.routeFullPath).toBe('/mesh?session_id=session-2')
    expect(mesh.cacheKey).toBe(initialCacheKey)
    expect(mesh.title).toBe('MESH：列车06-MR-CT')
    expect(router.currentRoute.value.fullPath).toBe('/mesh?session_id=session-2')
    expect(store.routeCacheKey('/mesh?session_id=session-pending')).toBe(initialCacheKey)

    const duplicate = await store.duplicateTab(mesh.id)
    expect(duplicate).toBeNull()
    expect(store.tabs.filter((tab) => tab.routeName === 'mesh')).toHaveLength(1)
    expect(store.routeCacheKey('/mesh?session_id=session-2')).toBe(initialCacheKey)
    expect(store.cachedTabs.map((tab) => tab.id)).toEqual([mesh.id])
  })

  it('returns base data to its overview landing page after workspace re-entry while preserving explicit deep links', async () => {
    const router = await createTestRouter('/rail-transit/base-data?tab=stations')
    const store = useWorkspaceStore()
    await store.initialize(router)
    const baseData = store.activeTab!

    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data?tab=stations')

    await store.openOrActivateRoute('/devices')
    await store.activateTab(baseData.id)
    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
    expect(baseData.routeFullPath).toBe('/rail-transit/base-data')

    await store.openOrActivateRoute('/rail-transit/base-data?tab=trackside-ap')
    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data?tab=trackside-ap')
    await store.openOrActivateRoute('/rail-transit/base-data')
    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
    await store.openOrActivateRoute('/devices')
    await store.activateTab(baseData.id)
    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
  })

  it('restores a persisted base data edit tab to the overview landing page', async () => {
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: {
        getWorkspaceWindowState: vi.fn(async () => ({
          windowId: 'main',
          snapshot: {
            schemaVersion: 1,
            windowId: 'main',
            activeTabId: 'base-data',
            tabs: [{
              id: 'base-data',
              instanceId: 'base-data',
              routeFullPath: '/rail-transit/base-data?tab=trackside-ap',
              title: '基础资料',
              identityKey: 'ignored',
              cacheKey: 'base-data',
              pinned: false,
              openedAt: 1,
              lastActivatedAt: 1,
            }],
          },
        })),
        saveWorkspaceWindowState: vi.fn(async () => undefined),
        setWorkspaceWindowTitle: vi.fn(),
      },
    })
    const router = await createTestRouter('/devices')
    const store = useWorkspaceStore()

    await store.initialize(router)

    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
    expect(store.activeTab?.routeFullPath).toBe('/rail-transit/base-data')
  })

  it('opens the overview after a site switch removes the prior base data tab', async () => {
    const router = await createTestRouter('/rail-transit/base-data?tab=trackside-ap')
    const store = useWorkspaceStore()
    await store.initialize(router)

    await store.prepareForSiteSwitch('line-b', '/settings?section=site-storage')
    await store.openOrActivateRoute('/rail-transit/base-data')

    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
    expect(store.activeTab?.routeFullPath).toBe('/rail-transit/base-data')
  })

  it('closes the active tab toward the left', async () => {
    const router = await createTestRouter()
    const store = useWorkspaceStore()
    await store.initialize(router)

    const device = await store.openOrActivateRoute('/devices/device-a')
    const leftId = store.tabs[store.tabs.findIndex((tab) => tab.id === device.id) - 1].id
    await store.closeTab(device.id)
    expect(store.activeTabId).toBe(leftId)
  })

  it('keeps pinned tabs when closing others or tabs to the right', async () => {
    const router = await createTestRouter()
    const store = useWorkspaceStore()
    await store.initialize(router)
    const pinned = await store.openOrActivateRoute('/devices')
    store.pinTab(pinned.id)
    const target = await store.openOrActivateRoute('/devices/device-a')
    await store.openOrActivateRoute('/devices/device-b')
    await store.closeOtherTabs(target.id)
    expect(store.tabs.map((tab) => tab.id)).toEqual([pinned.id, target.id])

    await store.openOrActivateRoute('/mesh?session_id=session-2')
    store.closeTabsToRight(pinned.id)
    expect(store.tabs.some((tab) => tab.id === pinned.id)).toBe(true)
  })

  it('falls back from corrupt persistence and excludes sensitive query data', async () => {
    localStorage.setItem('netconsole.workspace.v1', '{"schemaVersion":1,"tabs":"broken"}')
    const router = await createTestRouter('/mesh?session_id=session-1&confirm_token=secret')
    const store = useWorkspaceStore()
    await store.initialize(router)
    expect(store.tabs).toHaveLength(1)
    expect(JSON.stringify(store.createSnapshot())).not.toContain('secret')
  })

  it('ignores and clears legacy tabs on a cold Electron start without touching preferences', async () => {
    localStorage.setItem('netconsole.workspace.v1', JSON.stringify({
      schemaVersion: 1,
      windowId: 'main',
      activeTabId: 'tasks-tab',
      tabs: [{ id: 'tasks-tab', routeFullPath: '/tasks' }],
    }))
    localStorage.setItem('netconsole.theme', 'dark')
    sessionStorage.setItem('netconsole.web.open-page-tabs', JSON.stringify({
      version: 1,
      activeRouteName: 'tasks',
      tabs: [{ routeName: 'tasks', path: '/tasks', title: '任务中心' }],
    }))
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: {
        getWorkspaceWindowState: vi.fn(async () => ({ windowId: 'main', snapshot: null })),
        saveWorkspaceWindowState: vi.fn(async () => undefined),
        setWorkspaceWindowTitle: vi.fn(),
      },
    })
    const router = await createTestRouter()
    const store = useWorkspaceStore()

    await store.initialize(router)

    expect(store.tabs).toHaveLength(1)
    expect(store.activeTab?.routeName).toBe('dashboard')
    expect(store.activeTab?.routeFullPath).toBe('/')
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(localStorage.getItem('netconsole.workspace.v1')).toBeNull()
    expect(sessionStorage.getItem('netconsole.web.open-page-tabs')).toBeNull()
    expect(localStorage.getItem('netconsole.theme')).toBe('dark')
  })

  it('uses the Electron bridge for pop-out without exposing arbitrary URLs', async () => {
    const openWorkspaceWindow = vi.fn(async () => ({ success: true }))
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: {
        getWorkspaceWindowState: vi.fn(async () => ({ windowId: 'main', snapshot: null })),
        saveWorkspaceWindowState: vi.fn(async () => undefined),
        setWorkspaceWindowTitle: vi.fn(),
        openWorkspaceWindow,
      },
    })
    const router = await createTestRouter('/mesh?session_id=session-1')
    const store = useWorkspaceStore()
    await store.initialize(router)
    await expect(store.popOutTab()).resolves.toEqual({ success: true })
    expect(openWorkspaceWindow).toHaveBeenCalledWith({
      routeFullPath: '/mesh?session_id=session-1',
      title: 'MESH',
    })
  })

  it('removes site-scoped tabs and restores the checkpoint when switching fails', async () => {
    const router = await createTestRouter()
    const store = useWorkspaceStore()
    await store.initialize(router)
    await store.openOrActivateRoute('/devices')
    await store.openOrActivateRoute('/mesh?session_id=mr-id%3A1')
    const beforeSwitch = store.createSnapshot()
    const event = vi.fn()
    window.addEventListener('netconsole:before-site-switch', event)

    const checkpoint = await store.prepareForSiteSwitch(
      'line-b',
      '/settings?section=site-storage&site_focus=site-switch-1',
    )

    expect(checkpoint).toEqual(beforeSwitch)
    expect(event).toHaveBeenCalledOnce()
    expect(store.tabs.map((tab) => tab.routeName)).toEqual(['dashboard', 'system-settings'])
    expect(store.activeTab?.routeFullPath).toContain('section=site-storage')
    expect(JSON.stringify(store.createSnapshot())).not.toContain('session_id')

    await store.restoreAfterFailedSiteSwitch(checkpoint)
    expect(store.createSnapshot()).toMatchObject({
      windowId: beforeSwitch.windowId,
      activeTabId: beforeSwitch.activeTabId,
      tabs: beforeSwitch.tabs.map(({ lastActivatedAt: _lastActivatedAt, ...tab }) => expect.objectContaining(tab)),
    })
    expect(router.currentRoute.value.query.session_id).toBe('mr-id:1')
    window.removeEventListener('netconsole:before-site-switch', event)
  })

  it('aborts site preparation when a mounted page cancels the switch', async () => {
    const router = await createTestRouter('/mesh')
    const store = useWorkspaceStore()
    await store.initialize(router)
    const blocker = (event: Event) => event.preventDefault()
    window.addEventListener('netconsole:before-site-switch', blocker)

    await expect(store.prepareForSiteSwitch(
      'line-b',
      '/settings?section=site-storage&site_focus=site-switch-cancelled',
    )).rejects.toMatchObject({ name: 'SiteSwitchCancelled' })
    expect(router.currentRoute.value.path).toBe('/mesh')
    window.removeEventListener('netconsole:before-site-switch', blocker)
  })
})
