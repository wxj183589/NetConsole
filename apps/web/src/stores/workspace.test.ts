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
      { path: '/devices/:deviceId', name: 'device-detail', component: {}, meta: {
        title: '设备详情',
        workspace: { identity: 'resource', resourceParams: ['deviceId'] },
      } },
      { path: '/mesh', name: 'mesh', component: {}, meta: {
        title: 'MESH',
        workspace: { identity: 'singleton' },
      } },
    ],
  })
  return router.push(initial).then(() => router)
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
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
    expect(duplicate?.cacheKey).not.toBe(initialCacheKey)
    expect(store.routeCacheKey('/mesh?session_id=session-2')).toBe(duplicate?.cacheKey)
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
})
