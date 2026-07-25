import { describe, expect, it, vi } from 'vitest'

import {
  TrayController,
  type TrayLike,
  type TrayMenuItem,
} from '../src/main/tray-controller'

function createHarness(options: { fail?: boolean } = {}) {
  const listeners = new Map<string, () => void>()
  let menu: TrayMenuItem[] = []
  const tray: TrayLike = {
    setToolTip: vi.fn(),
    setContextMenu: vi.fn(),
    on: vi.fn((event, listener) => listeners.set(event, listener)),
    displayBalloon: vi.fn(),
    destroy: vi.fn(),
    isDestroyed: vi.fn(() => false),
  }
  const callbacks = {
    showMainWindow: vi.fn(),
    showTaskWindow: vi.fn(),
    createWorkspaceWindow: vi.fn(),
    requestSiteSwitch: vi.fn(),
    setCloseToTrayEnabled: vi.fn(),
    explicitQuit: vi.fn(),
  }
  const controller = new TrayController({
    createTray: () => {
      if (options.fail) throw new Error('icon missing')
      return tray
    },
    buildMenu: (value) => {
      menu = value
      return value
    },
    ...callbacks,
    logger: vi.fn(),
  })
  return { controller, tray, callbacks, listeners, getMenu: () => menu }
}

describe('TrayController', () => {
  it('creates the required menu and routes actions through controlled callbacks', () => {
    const harness = createHarness()
    expect(harness.controller.initialize()).toBe(true)
    const labels = harness.getMenu().map((item) => item.label).filter(Boolean)
    expect(labels).toEqual([
      '打开 NetConsole',
      '新建工作区窗口',
      '打开任务中心',
      'Backend：正在启动',
      '当前局点：未选择',
      '快速切换局点',
      '关闭主窗口后驻留通知区域',
      '退出 NetConsole',
    ])

    harness.listeners.get('double-click')?.()
    harness.getMenu().find((item) => item.label === '新建工作区窗口')?.click?.()
    harness.getMenu().find((item) => item.label === '打开任务中心')?.click?.()
    harness.getMenu().find((item) => item.label === '退出 NetConsole')?.click?.()
    expect(harness.callbacks.showMainWindow).toHaveBeenCalledOnce()
    expect(harness.callbacks.createWorkspaceWindow).toHaveBeenCalledOnce()
    expect(harness.callbacks.showTaskWindow).toHaveBeenCalledOnce()
    expect(harness.callbacks.explicitQuit).toHaveBeenCalledOnce()
  })

  it('updates status without recreating Tray and shows the background hint once', async () => {
    vi.useFakeTimers()
    const harness = createHarness()
    harness.controller.initialize()
    harness.controller.updateContext({ backendState: 'ready', activeSiteName: '宁波地铁12号线' })
    await vi.advanceTimersByTimeAsync(80)
    expect(harness.getMenu().map((item) => item.label)).toContain('Backend：在线')
    expect(harness.getMenu().map((item) => item.label)).toContain('当前局点：宁波地铁12号线')
    harness.controller.displayBackgroundHint()
    harness.controller.displayBackgroundHint()
    expect(harness.tray.displayBalloon).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('uses display names for the active site, tooltip, and quick switch menu', async () => {
    vi.useFakeTimers()
    const harness = createHarness()
    harness.controller.initialize()
    harness.controller.updateContext({
      backendState: 'ready',
      activeSiteId: 'legacy-0d1a8935839e',
      activeSiteName: '宁波地铁6号线',
      sites: [
        { siteId: 'legacy-0d1a8935839e', displayName: '宁波地铁6号线', active: true, selectable: false },
        { siteId: 'line-1', displayName: '宁波地铁1号线', active: false, selectable: true },
      ],
    })
    await vi.advanceTimersByTimeAsync(80)

    expect(harness.getMenu().map((item) => item.label)).toContain('当前局点：宁波地铁6号线')
    expect(harness.getMenu().map((item) => item.label)).not.toContain('当前局点：legacy-0d1a8935839e')
    expect(harness.tray.setToolTip).toHaveBeenLastCalledWith('NetConsole · 宁波地铁6号线')
    const quickSwitch = harness.getMenu().find((item) => item.label === '快速切换局点')
    expect(quickSwitch?.submenu).toHaveLength(2)
    expect(quickSwitch?.submenu?.[0]).toMatchObject({ label: '宁波地铁6号线', checked: true, enabled: false })
    quickSwitch?.submenu?.[1]?.click?.()
    expect(harness.callbacks.requestSiteSwitch).toHaveBeenCalledOnce()
    expect(harness.callbacks.requestSiteSwitch).toHaveBeenCalledWith('line-1')
    vi.useRealTimers()
  })

  it('distinguishes duplicate display names and disables requests while switching', async () => {
    vi.useFakeTimers()
    const harness = createHarness()
    harness.controller.initialize()
    harness.controller.updateContext({
      backendState: 'ready',
      activeSiteId: 'line-a',
      activeSiteName: '同名局点',
      sites: [
        { siteId: 'line-a', displayName: '同名局点', active: true, selectable: false },
        { siteId: 'line-b', displayName: '同名局点', active: false, selectable: true },
      ],
      siteSwitching: true,
    })
    await vi.advanceTimersByTimeAsync(80)

    const switching = harness.getMenu().find((item) => item.label === '正在切换局点…')
    expect(switching).toMatchObject({ enabled: false })
    expect(switching?.submenu).toEqual([{ label: '正在切换局点…', enabled: false }])
    expect(harness.callbacks.requestSiteSwitch).not.toHaveBeenCalled()

    harness.controller.updateContext({ siteSwitching: false })
    await vi.advanceTimersByTimeAsync(80)
    const quickSwitch = harness.getMenu().find((item) => item.label === '快速切换局点')
    expect(quickSwitch?.submenu?.map((item) => item.label)).toEqual([
      '同名局点 (line-a)',
      '同名局点 (line-b)',
    ])
    vi.useRealTimers()
  })

  it('fails closed when the tray icon cannot be initialized', () => {
    const harness = createHarness({ fail: true })
    expect(harness.controller.initialize()).toBe(false)
    expect(harness.controller.available).toBe(false)
  })
})
