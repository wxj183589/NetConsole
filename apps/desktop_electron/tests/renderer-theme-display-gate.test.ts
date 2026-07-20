import type { BrowserWindow } from 'electron'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  MANAGED_RENDERER_RETRY_ACTION,
  MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION,
  ManagedRendererRetryNavigation,
  ManagedWindowErrorCoordinator,
  RendererThemeDisplayGate,
} from '../src/main/renderer-theme-display-gate'

afterEach(() => vi.useRealTimers())

function createHarness(timeoutMs = 100) {
  let visible = false
  const window = {
    hide: vi.fn(() => { visible = false }),
    isDestroyed: vi.fn(() => false),
    isVisible: vi.fn(() => visible),
    show: vi.fn(() => { visible = true }),
  }
  const renderTimeoutFallback = vi.fn(async (): Promise<void> => undefined)
  const onVisible = vi.fn()
  const onFallbackError = vi.fn()
  const gate = new RendererThemeDisplayGate(window, {
    timeoutMs,
    renderTimeoutFallback,
    onVisible,
    onFallbackError,
  })
  return {
    gate,
    window,
    renderTimeoutFallback,
    onVisible,
    onFallbackError,
    setVisible: (value: boolean) => { visible = value },
  }
}

describe('Renderer theme display gate', () => {
  it('shows exactly once after a resolved theme report', () => {
    vi.useFakeTimers()
    const { gate, window, renderTimeoutFallback, onVisible } = createHarness()

    gate.arm()
    expect(window.show).not.toHaveBeenCalled()
    expect(gate.acceptResolvedTheme()).toBe(true)
    expect(gate.acceptResolvedTheme()).toBe(false)
    vi.advanceTimersByTime(100)

    expect(window.show).toHaveBeenCalledOnce()
    expect(renderTimeoutFallback).not.toHaveBeenCalled()
    expect(onVisible).toHaveBeenCalledWith('theme-ready')
  })

  it('hides an observable loading page before arming and reveals after theme resolution', () => {
    const { gate, window, setVisible } = createHarness()
    setVisible(true)

    gate.arm()
    expect(window.hide).toHaveBeenCalledOnce()
    expect(window.show).not.toHaveBeenCalled()
    gate.acceptResolvedTheme()

    expect(window.hide.mock.invocationCallOrder[0]).toBeLessThan(window.show.mock.invocationCallOrder[0])
    expect(window.show).toHaveBeenCalledOnce()
  })

  it('renders the timeout failure page before making the window visible', async () => {
    vi.useFakeTimers()
    let finishFallback: (() => void) | undefined
    const { gate, window, renderTimeoutFallback, onVisible } = createHarness()
    renderTimeoutFallback.mockImplementation(() => new Promise<void>((resolve) => { finishFallback = resolve }))

    gate.arm()
    await vi.advanceTimersByTimeAsync(100)
    expect(renderTimeoutFallback).toHaveBeenCalledOnce()
    expect(window.show).not.toHaveBeenCalled()

    finishFallback?.()
    await Promise.resolve()
    expect(window.show).toHaveBeenCalledOnce()
    expect(onVisible).toHaveBeenCalledWith('theme-timeout')
  })

  it('uses the same visible fallback for an explicit renderer failure', async () => {
    const { gate, window, onVisible } = createHarness()
    const renderFailure = vi.fn(async () => undefined)

    gate.arm()
    await expect(gate.revealFallback('renderer-failed', renderFailure)).resolves.toBe(true)

    expect(renderFailure).toHaveBeenCalledOnce()
    expect(window.show).toHaveBeenCalledOnce()
    expect(onVisible).toHaveBeenCalledWith('renderer-failed')
  })

  it('shows the timeout page once after hiding the system-themed loading window', async () => {
    vi.useFakeTimers()
    const { gate, window, renderTimeoutFallback, onVisible, setVisible } = createHarness()
    setVisible(true)

    gate.arm()
    await vi.advanceTimersByTimeAsync(100)

    expect(window.hide).toHaveBeenCalledOnce()
    expect(renderTimeoutFallback).toHaveBeenCalledOnce()
    expect(window.show).toHaveBeenCalledOnce()
    expect(onVisible).toHaveBeenCalledWith('theme-timeout')
  })
})

describe('managed window error coordinator', () => {
  it('coalesces concurrent failures and ignores repeats until navigation resets', async () => {
    const coordinator = new ManagedWindowErrorCoordinator()
    let finish: (() => void) | undefined
    const render = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))

    const first = coordinator.show(render)
    const second = coordinator.show(render)
    expect(render).toHaveBeenCalledOnce()
    finish?.()
    await expect(Promise.all([first, second])).resolves.toEqual([true, true])
    await expect(coordinator.show(render)).resolves.toBe(false)

    coordinator.reset()
    const afterReset = coordinator.show(async () => undefined)
    await expect(afterReset).resolves.toBe(true)
  })
})

describe('managed Renderer retry navigation', () => {
  function createRetryHarness() {
    let currentUrl = 'data:text/html;charset=utf-8,managed-error'
    const listeners: Array<(event: { preventDefault(): void }, target: string) => void> = []
    const retry = vi.fn(async () => undefined)
    const rejected = vi.fn()
    const retryError = vi.fn()
    const openMainTasks = vi.fn(async () => undefined)
    const window = {
      isDestroyed: vi.fn(() => false),
      webContents: {
        getURL: vi.fn(() => currentUrl),
        on: vi.fn((event, handler) => {
          if (event === 'will-navigate') listeners.push(handler)
        }),
      },
    } as unknown as BrowserWindow
    const navigation = new ManagedRendererRetryNavigation(window, retry, rejected, retryError, openMainTasks)
    return {
      navigation,
      listeners,
      retry,
      rejected,
      retryError,
      openMainTasks,
      setCurrentUrl: (url: string) => { currentUrl = url },
    }
  }

  it('accepts one retry only from the exact Main-generated error page', async () => {
    const { navigation, listeners, retry, rejected } = createRetryHarness()
    const event = { preventDefault: vi.fn() }
    navigation.armForStatusPage('data:text/html;charset=utf-8,managed-error')

    listeners[0]?.(event, MANAGED_RENDERER_RETRY_ACTION)
    await Promise.resolve()
    listeners[0]?.(event, MANAGED_RENDERER_RETRY_ACTION)
    await Promise.resolve()

    expect(event.preventDefault).toHaveBeenCalledTimes(2)
    expect(retry).toHaveBeenCalledOnce()
    expect(rejected).toHaveBeenCalledOnce()
  })

  it('rejects the action from any other page and ignores unrelated navigation', async () => {
    const { navigation, listeners, retry, rejected, setCurrentUrl } = createRetryHarness()
    const actionEvent = { preventDefault: vi.fn() }
    const unrelatedEvent = { preventDefault: vi.fn() }
    navigation.armForStatusPage('data:text/html;charset=utf-8,managed-error')
    setCurrentUrl('http://127.0.0.1:5173/devices')

    listeners[0]?.(actionEvent, MANAGED_RENDERER_RETRY_ACTION)
    listeners[0]?.(unrelatedEvent, 'https://example.com/')
    await Promise.resolve()

    expect(actionEvent.preventDefault).toHaveBeenCalledOnce()
    expect(unrelatedEvent.preventDefault).not.toHaveBeenCalled()
    expect(retry).not.toHaveBeenCalled()
    expect(rejected).toHaveBeenCalledOnce()
  })

  it('installs one listener and reports retry callback failures without reopening it', async () => {
    const { navigation, listeners, retry, retryError } = createRetryHarness()
    retry.mockRejectedValueOnce(new Error('failed'))
    navigation.armForStatusPage('data:text/html;charset=utf-8,managed-error')

    listeners[0]?.({ preventDefault: vi.fn() }, MANAGED_RENDERER_RETRY_ACTION)
    await vi.waitFor(() => expect(retryError).toHaveBeenCalledOnce())

    expect(listeners).toHaveLength(1)
    expect(retry).toHaveBeenCalledOnce()
  })

  it('opens the main task route only from the exact managed status page', async () => {
    const { navigation, listeners, openMainTasks, retry } = createRetryHarness()
    navigation.armForStatusPage('data:text/html;charset=utf-8,managed-error')

    listeners[0]?.({ preventDefault: vi.fn() }, MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION)
    await Promise.resolve()

    expect(openMainTasks).toHaveBeenCalledOnce()
    expect(retry).not.toHaveBeenCalled()
  })
})
