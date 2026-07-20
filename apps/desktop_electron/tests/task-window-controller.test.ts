import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RendererHostReport, TaskWindowContext } from '../src/shared/bridge'
import {
  TaskWindowController,
  type TaskWindowLike,
} from '../src/main/task-window-controller'

function createWindowHarness() {
  let currentUrl = ''
  let visible = false
  const webListeners = new Map<string, Array<(...args: unknown[]) => void>>()
  const windowListeners = new Map<string, Array<(...args: unknown[]) => void>>()
  const add = (map: Map<string, Array<(...args: unknown[]) => void>>, event: string, listener: (...args: unknown[]) => void) => {
    map.set(event, [...(map.get(event) || []), listener])
  }
  const window: TaskWindowLike = {
    loadURL: vi.fn(async (url: string) => { currentUrl = url }),
    isDestroyed: vi.fn(() => false),
    isVisible: vi.fn(() => visible),
    show: vi.fn(() => { visible = true }),
    focus: vi.fn(),
    webContents: {
      getURL: () => currentUrl,
      on: (event, listener) => add(webListeners, event, listener),
    },
    on: (event, listener) => add(windowListeners, event, listener),
  }
  return {
    window,
    setUrl: (url: string) => { currentUrl = url },
    setVisible: (value: boolean) => { visible = value },
    emitWeb: (event: string, ...args: unknown[]) => webListeners.get(event)?.forEach((listener) => listener(...args)),
    emitWindow: (event: string, ...args: unknown[]) => windowListeners.get(event)?.forEach((listener) => listener(...args)),
  }
}

function createHarness(timeoutMs = 1_000) {
  const managedWindow = createWindowHarness()
  const logger = vi.fn()
  const loadLoadingPage = vi.fn(async () => { managedWindow.setUrl('data:text/html,loading') })
  const loadFailurePage = vi.fn(async () => { managedWindow.setUrl('data:text/html,failure') })
  const prepareNavigation = vi.fn()
  const buildTarget = (context: TaskWindowContext) => {
    const url = new URL('/desktop/tasks', 'http://127.0.0.1:5173')
    url.searchParams.set('task_window', '1')
    if (context.taskId) url.searchParams.set('task_id', context.taskId)
    if (context.module) url.searchParams.set('module', context.module)
    return url.toString()
  }
  const controller = new TaskWindowController({
    createWindow: () => managedWindow.window,
    buildTarget,
    loadLoadingPage,
    loadFailurePage,
    prepareNavigation,
    logger,
    timeoutMs,
  })
  return { controller, managedWindow, logger, loadLoadingPage, loadFailurePage, prepareNavigation, buildTarget }
}

async function completeOpen(
  harness: ReturnType<typeof createHarness>,
  context: TaskWindowContext,
) {
  const result = harness.controller.open(context)
  const target = harness.buildTarget(context)
  await vi.waitFor(() => expect(harness.managedWindow.window.loadURL).toHaveBeenCalledWith(target))
  harness.managedWindow.setUrl(target)
  harness.managedWindow.emitWeb('did-finish-load')
  harness.controller.acceptRendererReport({ resolvedTheme: 'light' }, harness.managedWindow.window)
  harness.controller.acceptRendererReport({ healthOk: true, phase: 'mounted', surface: 'task-window' }, harness.managedWindow.window)
  harness.controller.acceptRendererReport({ healthOk: true, phase: 'interactive', surface: 'task-window' }, harness.managedWindow.window)
  return result
}

describe('TaskWindowController', () => {
  afterEach(() => vi.useRealTimers())

  it('shows a loading page and resolves only after the task Renderer is interactive', async () => {
    const harness = createHarness()
    const context = { taskId: 'mesh-task-1', module: 'rail' as const }
    const result = await completeOpen(harness, context)

    expect(result).toEqual({ success: true })
    expect(harness.loadLoadingPage).toHaveBeenCalledOnce()
    expect(harness.prepareNavigation).toHaveBeenCalledWith(harness.managedWindow.window, harness.buildTarget(context))
    expect(harness.logger).toHaveBeenCalledWith('ELECTRON_TASK_WINDOW_DID_FINISH_LOAD')
    expect(harness.logger).toHaveBeenCalledWith('ELECTRON_TASK_WINDOW_RENDERER_MOUNTED')
    expect(harness.logger).toHaveBeenCalledWith('ELECTRON_TASK_WINDOW_INTERACTIVE')
    expect(JSON.stringify(harness.logger.mock.calls)).not.toContain('mesh-task-1')
  })

  it('returns a real failure and renders a retryable page when navigation fails', async () => {
    const harness = createHarness()
    const result = harness.controller.open({ module: 'rail' })
    await vi.waitFor(() => expect(harness.managedWindow.window.loadURL).toHaveBeenCalledTimes(1))
    harness.managedWindow.emitWeb('did-fail-load', {}, -105, 'secret detail', 'http://127.0.0.1:5173/desktop/tasks?token=secret', true)

    await expect(result).resolves.toEqual({ success: false, error: '任务中心加载失败' })
    expect(harness.loadFailurePage).toHaveBeenCalledWith(harness.managedWindow.window, '任务中心加载失败', '任务中心加载失败')
    expect(JSON.stringify(harness.logger.mock.calls)).not.toContain('secret')
  })

  it('times out, reuses one window, and restores a hidden ready window', async () => {
    vi.useFakeTimers()
    const timeoutHarness = createHarness(50)
    const timedOut = timeoutHarness.controller.open({})
    await vi.advanceTimersByTimeAsync(50)
    await expect(timedOut).resolves.toEqual({ success: false, error: '任务中心加载失败' })
    expect(timeoutHarness.logger).toHaveBeenCalledWith('ELECTRON_TASK_WINDOW_TIMEOUT')

    vi.useRealTimers()
    const harness = createHarness()
    const context = { module: 'rail' as const }
    await completeOpen(harness, context)
    harness.managedWindow.setVisible(false)
    await expect(harness.controller.open(context)).resolves.toEqual({ success: true })

    expect(harness.loadLoadingPage).toHaveBeenCalledOnce()
    expect(harness.managedWindow.window.show).toHaveBeenCalledTimes(2)
    expect(harness.logger).toHaveBeenCalledWith('ELECTRON_TASK_WINDOW_REUSED')
  })

  it('ignores main-window readiness reports and fails safely after a crash', async () => {
    const harness = createHarness()
    const result = harness.controller.open({ module: 'rail' })
    await vi.waitFor(() => expect(harness.managedWindow.window.loadURL).toHaveBeenCalledOnce())
    const mainReport: RendererHostReport = { healthOk: true, phase: 'interactive', surface: 'main' }
    harness.controller.acceptRendererReport(mainReport, harness.managedWindow.window)
    harness.managedWindow.emitWeb('render-process-gone', {}, { reason: 'crashed' })

    await expect(result).resolves.toEqual({ success: false, error: '任务中心加载失败' })
    expect(harness.loadFailurePage).toHaveBeenCalled()
  })
})
