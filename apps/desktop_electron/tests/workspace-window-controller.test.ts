import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceLayoutStore } from '../src/main/workspace-layout-store'
import {
  WorkspaceWindowController,
  type WorkspaceWindowLike,
} from '../src/main/workspace-window-controller'

const roots: string[] = []
afterEach(() => {
  vi.useRealTimers()
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})

function createWindowHarness(id: number) {
  let url = ''
  let visible = false
  let destroyed = false
  let title = ''
  const webListeners = new Map<string, Array<(...args: unknown[]) => void>>()
  const windowListeners = new Map<string, Array<(...args: unknown[]) => void>>()
  const add = (map: Map<string, Array<(...args: unknown[]) => void>>, event: string, listener: (...args: unknown[]) => void) => {
    map.set(event, [...(map.get(event) || []), listener])
  }
  const window: WorkspaceWindowLike = {
    webContents: {
      id,
      getURL: () => url,
      on: (event, listener) => add(webListeners, event, listener),
    },
    loadURL: vi.fn(async (target: string) => { url = target }),
    isDestroyed: () => destroyed,
    isVisible: () => visible,
    isMinimized: () => false,
    isMaximized: () => false,
    show: vi.fn(() => { visible = true }),
    hide: vi.fn(() => { visible = false }),
    focus: vi.fn(),
    restore: vi.fn(),
    maximize: vi.fn(),
    close: vi.fn(() => {
      windowListeners.get('close')?.forEach((listener) => listener({ preventDefault: vi.fn() }))
      destroyed = true
      windowListeners.get('closed')?.forEach((listener) => listener())
    }),
    setTitle: vi.fn((value: string) => { title = value }),
    getBounds: () => ({ x: 10, y: 20, width: 1_200, height: 800 }),
    on: (event, listener) => add(windowListeners, event, listener),
  }
  return {
    window,
    emitWeb: (event: string, ...args: unknown[]) => webListeners.get(event)?.forEach((listener) => listener(...args)),
    emitWindow: (event: string, ...args: unknown[]) => windowListeners.get(event)?.forEach((listener) => listener(...args)),
    setUrl: (value: string) => { url = value },
    getTitle: () => title,
  }
}

function createHarness(legacyMainState?: {
  bounds: { x: number; y: number; width: number; height: number }
  maximized: boolean
  snapshot?: object
}) {
  const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-window-'))
  roots.push(root)
  if (legacyMainState) {
    writeFileSync(join(root, 'workspace-layout.json'), JSON.stringify({
      schemaVersion: 1,
      windows: [{
        windowId: 'main',
        role: 'main',
        bounds: legacyMainState.bounds,
        maximized: legacyMainState.maximized,
        snapshot: legacyMainState.snapshot ?? null,
      }, {
        windowId: 'workspace-old',
        role: 'workspace',
        bounds: { x: 2_000, y: 100, width: 1_200, height: 800 },
        maximized: false,
        snapshot: legacyMainState.snapshot ?? null,
      }],
    }), 'utf8')
  }
  const windows: ReturnType<typeof createWindowHarness>[] = []
  const createWindowCalls: Array<{
    role: 'main' | 'workspace'
    bounds: { x: number; y: number; width: number; height: number } | undefined
  }> = []
  let hideMain = true
  let explicitQuit = false
  const controller = new WorkspaceWindowController(
    new WorkspaceLayoutStore(root),
    {
      createWindow: (role, bounds) => {
        createWindowCalls.push({ role, bounds })
        const harness = createWindowHarness(windows.length + 1)
        windows.push(harness)
        return harness.window
      },
      buildTarget: (route, id, role) => `http://127.0.0.1:5173${route}${route.includes('?') ? '&' : '?'}workspace_window=${role === 'workspace' ? '1' : '0'}&workspace_window_id=${id}`,
      prepareNavigation: vi.fn(),
      loadLoadingPage: vi.fn(async () => undefined),
      loadFailurePage: vi.fn(async () => undefined),
      getWorkAreas: () => [{ x: 0, y: 0, width: 1_920, height: 1_080 }],
      shouldHideMainToTray: () => hideMain,
      isExplicitQuit: () => explicitQuit,
      onMainHidden: vi.fn(),
      onVisibleWindowCountChanged: vi.fn(),
      logger: vi.fn(),
      timeoutMs: 1_000,
    },
  )
  return {
    controller,
    windows,
    createWindowCalls,
    setHideMain: (value: boolean) => { hideMain = value },
    setExplicitQuit: (value: boolean) => { explicitQuit = value },
  }
}

describe('WorkspaceWindowController', () => {
  it.each([
    ['off-screen normal', { x: 50_000, y: 50_000, width: 900, height: 600 }, false],
    ['secondary maximized', { x: 2_200, y: 100, width: 1_400, height: 900 }, true],
    ['negative minimized-era bounds', { x: -2_000, y: -900, width: 1_100, height: 700 }, false],
  ])('never passes legacy main window state into creation: %s', (_name, bounds, maximized) => {
    const harness = createHarness({ bounds, maximized })
    const main = harness.controller.ensureMainWindow(false)

    expect(harness.createWindowCalls).toEqual([{ role: 'main', bounds: undefined }])
    expect(main.maximize).not.toHaveBeenCalled()
  })

  it('starts with no legacy tabs or additional windows', async () => {
    const legacySnapshot = {
      schemaVersion: 1,
      windowId: 'main',
      activeTabId: 'tasks-tab',
      tabs: [{
        id: 'tasks-tab',
        instanceId: 'tasks-instance',
        routeFullPath: '/tasks',
        title: '任务中心',
        identityKey: 'singleton:tasks',
        cacheKey: 'tasks:instance',
        pinned: false,
        openedAt: 1,
        lastActivatedAt: 1,
      }],
    }
    const harness = createHarness({
      bounds: { x: 2_200, y: 100, width: 1_400, height: 900 },
      maximized: true,
      snapshot: legacySnapshot,
    })

    const main = harness.controller.ensureMainWindow(false)
    await harness.controller.restoreAdditionalWindows()

    expect(harness.controller.getWindowState(main).snapshot).toBeNull()
    expect(harness.createWindowCalls).toEqual([{ role: 'main', bounds: undefined }])
  })

  it('hides the main window to tray but destroys additional windows normally', async () => {
    const harness = createHarness()
    const main = harness.controller.ensureMainWindow(false)
    main.show()
    const closeEvent = { preventDefault: vi.fn() }
    harness.windows[0].emitWindow('close', closeEvent)
    expect(closeEvent.preventDefault).toHaveBeenCalledOnce()
    expect(main.hide).toHaveBeenCalledOnce()

    const opened = harness.controller.open({ routeFullPath: '/tasks', title: '任务中心' })
    await vi.waitFor(() => expect(harness.windows).toHaveLength(2))
    const extra = harness.windows[1]
    const target = (extra.window.loadURL as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[0] as string
    extra.setUrl(target)
    extra.emitWeb('did-finish-load')
    harness.controller.acceptRendererReport({ resolvedTheme: 'dark' }, extra.window)
    harness.controller.acceptRendererReport({ healthOk: true, phase: 'mounted', surface: 'workspace-window' }, extra.window)
    harness.controller.acceptRendererReport({ healthOk: true, phase: 'interactive', surface: 'workspace-window' }, extra.window)
    await expect(opened).resolves.toEqual({ success: true })
    extra.emitWindow('closed')
    expect(harness.controller.getAllManagedWindows()).toEqual([main])
  })

  it('stores snapshots per sender and applies controlled window titles', () => {
    const harness = createHarness()
    const main = harness.controller.ensureMainWindow(false)
    const state = harness.controller.getWindowState(main)
    const snapshot = {
      schemaVersion: 1 as const,
      windowId: state.windowId,
      activeTabId: 'tab-1',
      tabs: [{
        id: 'tab-1',
        instanceId: 'instance-1',
        routeFullPath: '/',
        title: 'Dashboard',
        identityKey: 'singleton:dashboard',
        cacheKey: 'dashboard:instance-1',
        pinned: false,
        openedAt: 1,
        lastActivatedAt: 1,
      }],
    }
    harness.controller.saveWindowState(main, snapshot)
    expect(harness.controller.getWindowState(main).snapshot).toEqual(snapshot)
    harness.controller.setWindowTitle(main, '设备：AC1')
    expect(harness.windows[0].getTitle()).toBe('设备：AC1 - NetConsole')
  })

  it('removes site-scoped routes from every window snapshot and can roll them back', () => {
    const harness = createHarness()
    const main = harness.controller.ensureMainWindow(false)
    const state = harness.controller.getWindowState(main)
    const snapshot = {
      schemaVersion: 1 as const,
      windowId: state.windowId,
      activeTabId: 'settings-tab',
      tabs: [
        { id: 'dashboard-tab', instanceId: 'dashboard-instance', routeFullPath: '/', title: 'Dashboard', identityKey: 'singleton:dashboard', cacheKey: 'dashboard:instance', pinned: false, openedAt: 1, lastActivatedAt: 1 },
        { id: 'mesh-tab', instanceId: 'mesh-instance', routeFullPath: '/rail-transit/mesh-analysis?session_id=mr-id%3A1', title: 'MESH', identityKey: 'singleton:mesh-analysis', cacheKey: 'mesh:instance', pinned: true, openedAt: 2, lastActivatedAt: 2 },
        { id: 'settings-tab', instanceId: 'settings-instance', routeFullPath: '/settings?section=site-storage', title: '系统设置', identityKey: 'singleton:system-settings', cacheKey: 'settings:instance', pinned: false, openedAt: 3, lastActivatedAt: 3 },
      ],
    }
    harness.controller.saveWindowState(main, snapshot)

    const checkpoint = harness.controller.prepareSiteSwitchSnapshots()
    const prepared = harness.controller.getWindowState(main).snapshot!
    expect(prepared.tabs.map((tab) => tab.id)).toEqual(['settings-tab', 'dashboard-tab'])
    expect(prepared.activeTabId).toBe('settings-tab')
    expect(JSON.stringify(prepared)).not.toContain('session_id')

    harness.controller.restoreSiteSwitchSnapshots(checkpoint)
    expect(harness.controller.getWindowState(main).snapshot).toEqual(snapshot)
  })

  it('allows main destruction when close-to-tray is disabled', () => {
    const harness = createHarness()
    harness.setHideMain(false)
    const main = harness.controller.ensureMainWindow(false)
    const event = { preventDefault: vi.fn() }
    harness.windows[0].emitWindow('close', event)
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(main.hide).not.toHaveBeenCalled()
  })

  it('restores the existing tray-hidden window without reapplying startup maximization', async () => {
    const harness = createHarness()
    const main = harness.controller.ensureMainWindow(false)
    const state = harness.controller.getWindowState(main)
    const snapshot = {
      schemaVersion: 1 as const,
      windowId: state.windowId,
      activeTabId: 'tasks-tab',
      tabs: [{
        id: 'dashboard-tab',
        instanceId: 'dashboard-instance',
        routeFullPath: '/',
        title: 'Dashboard',
        identityKey: 'singleton:dashboard',
        cacheKey: 'dashboard:instance',
        pinned: true,
        openedAt: 1,
        lastActivatedAt: 1,
      }, {
        id: 'tasks-tab',
        instanceId: 'tasks-instance',
        routeFullPath: '/tasks',
        title: '任务中心',
        identityKey: 'singleton:tasks',
        cacheKey: 'tasks:instance',
        pinned: false,
        openedAt: 2,
        lastActivatedAt: 2,
      }],
    }
    harness.controller.saveWindowState(main, snapshot)
    main.show()
    harness.windows[0].emitWindow('close', { preventDefault: vi.fn() })

    await harness.controller.showMainWindow()

    expect(main.show).toHaveBeenCalledTimes(2)
    expect(main.focus).toHaveBeenCalledOnce()
    expect(main.maximize).not.toHaveBeenCalled()
    expect(main.loadURL).not.toHaveBeenCalled()
    expect(harness.controller.getWindowState(main).snapshot).toEqual(snapshot)
  })
})
