import type { BrowserWindow } from 'electron'

export type RendererDisplayReason = 'theme-ready' | 'renderer-failed' | 'theme-timeout'

export const MANAGED_RENDERER_RETRY_ACTION = 'netconsole-action://retry-renderer/'
export const MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION = 'netconsole-action://open-main-tasks/'

export interface RendererDisplayWindow {
  hide(): void
  isDestroyed(): boolean
  isVisible?(): boolean
  show(): void
}

export interface RendererThemeDisplayGateOptions {
  timeoutMs: number
  renderTimeoutFallback: () => Promise<void> | void
  onVisible?: (reason: RendererDisplayReason) => void
  onFallbackError?: (reason: RendererDisplayReason, cause: unknown) => void
}

/**
 * Keeps a managed window hidden until the Renderer reports a resolved theme.
 * The timeout path first renders an observable failure page and only then shows.
 */
export class RendererThemeDisplayGate {
  private timer: ReturnType<typeof setTimeout> | undefined
  private waiting = false
  private disposed = false

  constructor(
    private readonly window: RendererDisplayWindow,
    private readonly options: RendererThemeDisplayGateOptions,
  ) {}

  arm(): void {
    if (this.disposed) throw new Error('renderer theme display gate is disposed')
    this.clearTimer()
    if (this.window.isVisible?.()) this.window.hide()
    this.waiting = true
    this.timer = setTimeout(() => {
      void this.revealFallback('theme-timeout', this.options.renderTimeoutFallback)
    }, this.options.timeoutMs)
  }

  isWaiting(): boolean {
    return this.waiting
  }

  acceptResolvedTheme(): boolean {
    if (!this.claim()) return false
    this.show('theme-ready')
    return true
  }

  async revealFallback(
    reason: Exclude<RendererDisplayReason, 'theme-ready'>,
    render: () => Promise<void> | void,
  ): Promise<boolean> {
    if (!this.claim()) return false
    try {
      await render()
    } catch (cause) {
      this.options.onFallbackError?.(reason, cause)
    } finally {
      this.show(reason)
    }
    return true
  }

  dispose(): void {
    this.disposed = true
    this.waiting = false
    this.clearTimer()
  }

  private claim(): boolean {
    if (!this.waiting || this.disposed) return false
    this.waiting = false
    this.clearTimer()
    return true
  }

  private show(reason: RendererDisplayReason): void {
    if (this.window.isDestroyed()) return
    if (!this.window.isVisible?.()) this.window.show()
    this.options.onVisible?.(reason)
  }

  private clearTimer(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = undefined
  }
}

/** Deduplicates diagnostics and navigation failures for one managed window. */
export class ManagedWindowErrorCoordinator {
  private visible = false
  private pending: Promise<boolean> | undefined

  reset(): void {
    this.visible = false
    this.pending = undefined
  }

  markVisible(): void {
    this.visible = true
  }

  show(render: () => Promise<void>): Promise<boolean> {
    if (this.visible) return Promise.resolve(false)
    if (this.pending) return this.pending
    const operation = (async () => {
      await render()
      this.visible = true
      return true
    })()
    this.pending = operation
    void operation.finally(() => {
      if (this.pending === operation) this.pending = undefined
    }).catch(() => undefined)
    return operation
  }
}

/**
 * Converts a click from the exact Main-generated error page into one bounded
 * retry callback. No URL or general navigation capability crosses to Renderer.
 */
export class ManagedRendererRetryNavigation {
  private retryPageUrl = ''

  constructor(
    private readonly window: BrowserWindow,
    private readonly retry: () => Promise<void> | void,
    private readonly onRejected: () => void = () => undefined,
    private readonly onRetryError: (cause: unknown) => void = () => undefined,
    private readonly openMainTasks: () => Promise<void> | void = () => undefined,
  ) {
    window.webContents.on('will-navigate', (event, target) => {
      if (target !== MANAGED_RENDERER_RETRY_ACTION && target !== MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION) return
      event.preventDefault()
      if (
        window.isDestroyed()
        || !this.retryPageUrl
        || window.webContents.getURL() !== this.retryPageUrl
      ) {
        this.onRejected()
        return
      }
      this.retryPageUrl = ''
      const action = target === MANAGED_RENDERER_RETRY_ACTION ? this.retry : this.openMainTasks
      void Promise.resolve().then(() => action()).catch(this.onRetryError)
    })
  }

  armForStatusPage(statusPageUrl: string): void {
    this.retryPageUrl = statusPageUrl
  }

  disarm(): void {
    this.retryPageUrl = ''
  }
}
