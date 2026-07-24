import { mkdtempSync, rmSync } from 'node:fs'
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

function createHarness() {
  const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-window-'))
  roots.push(root)
  const windows: ReturnType<typeof createWindowHarness>[] = []
  let hideMain = true
  let explicitQuit = false
  const controller = new WorkspaceWindowController(
    new WorkspaceLayoutStore(root),
    {
      createWindow: () => {
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
    setHideMain: (value: boolean) => { hideMain = value },
    setExplicitQuit: (value: boolean) => { explicitQuit = value },
  }
}

describe('WorkspaceWindowController', () => {
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

  it('allows main destruction when close-to-tray is disabled', () => {
    const harness = createHarness()
    harness.setHideMain(false)
    const main = harness.controller.ensureMainWindow(false)
    const event = { preventDefault: vi.fn() }
    harness.windows[0].emitWindow('close', event)
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(main.hide).not.toHaveBeenCalled()
  })
})
