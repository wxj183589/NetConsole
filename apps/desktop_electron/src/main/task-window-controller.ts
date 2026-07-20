import type { RendererHostReport, TaskWindowContext, NativeActionResult } from '../shared/bridge'

export interface TaskWindowWebContentsLike {
  getURL(): string
  on(event: string, listener: (...args: unknown[]) => void): void
}

export interface TaskWindowLike {
  loadURL(url: string): Promise<void>
  isDestroyed(): boolean
  isVisible(): boolean
  show(): void
  focus(): void
  webContents: TaskWindowWebContentsLike
  on(event: string, listener: (...args: unknown[]) => void): void
}

export interface TaskWindowControllerOptions {
  createWindow(): TaskWindowLike
  buildTarget(context: TaskWindowContext): string
  loadLoadingPage(window: TaskWindowLike): Promise<void>
  loadFailurePage(window: TaskWindowLike, title: string, detail: string): Promise<void>
  prepareNavigation(window: TaskWindowLike, target: string): void
  logger(event: string): void
  timeoutMs: number
}

interface PendingOpen {
  target: string
  context: TaskWindowContext
  mounted: boolean
  themed: boolean
  didFinishLoad: boolean
  interactive: boolean
  timer: ReturnType<typeof setTimeout>
  resolve: (result: NativeActionResult) => void
  promise: Promise<NativeActionResult>
}

export class TaskWindowController {
  private window: TaskWindowLike | undefined
  private pending: PendingOpen | undefined
  private lastContext: TaskWindowContext | undefined
  private readyTarget = ''
  private disposed = false

  constructor(private readonly options: TaskWindowControllerOptions) {}

  get currentWindow(): TaskWindowLike | undefined { return this.window }

  async open(context: TaskWindowContext = {}): Promise<NativeActionResult> {
    if (this.disposed) return { success: false, error: '任务窗口已关闭' }
    const target = this.options.buildTarget(context)
    if (this.pending) {
      if (this.pending.target === target) {
        this.reveal('ELECTRON_TASK_WINDOW_REUSED')
        return this.pending.promise
      }
      await this.pending.promise
      return this.open(context)
    }

    const window = this.ensureWindow()
    if (this.readyTarget === target && !window.isDestroyed()) {
      this.reveal('ELECTRON_TASK_WINDOW_REUSED')
      return { success: true }
    }

    this.lastContext = { ...context }
    this.readyTarget = ''
    try {
      await this.options.loadLoadingPage(window)
      if (window.isDestroyed()) return { success: false, error: '任务中心加载失败' }
      this.reveal('ELECTRON_TASK_WINDOW_SHOWN')
    } catch {
      return { success: false, error: '任务中心加载失败' }
    }

    let resolvePending!: (result: NativeActionResult) => void
    const promise = new Promise<NativeActionResult>((resolve) => { resolvePending = resolve })
    const pending: PendingOpen = {
      target,
      context: { ...context },
      mounted: false,
      themed: false,
      didFinishLoad: false,
      interactive: false,
      timer: setTimeout(() => { void this.fail('ELECTRON_TASK_WINDOW_TIMEOUT', '任务中心启动超时') }, this.options.timeoutMs),
      resolve: resolvePending,
      promise,
    }
    this.pending = pending
    this.options.prepareNavigation(window, target)
    this.options.logger('ELECTRON_TASK_WINDOW_NAVIGATION_STARTED')
    void window.loadURL(target).catch(() => { void this.fail('ELECTRON_TASK_WINDOW_LOAD_FAILED', '任务中心加载失败') })
    return promise
  }

  async retry(): Promise<NativeActionResult> {
    if (!this.lastContext) return { success: false, error: '任务中心暂无可重试上下文' }
    return this.open(this.lastContext)
  }

  acceptRendererReport(report: RendererHostReport, source: TaskWindowLike | undefined): void {
    if (!source || source !== this.window || !this.pending) return
    if ('resolvedTheme' in report) {
      this.pending.themed = true
      this.resolveWhenReady()
      return
    }
    if (report.surface !== 'task-window') return
    if (report.phase === 'failed') {
      void this.fail('ELECTRON_TASK_WINDOW_LOAD_FAILED', '任务中心初始化失败')
      return
    }
    if (report.phase === 'mounted') {
      this.pending.mounted = true
      this.options.logger('ELECTRON_TASK_WINDOW_RENDERER_MOUNTED')
    }
    if (report.phase === 'interactive' && report.healthOk) {
      this.pending.interactive = true
      this.options.logger('ELECTRON_TASK_WINDOW_INTERACTIVE')
    }
    this.resolveWhenReady()
  }

  dispose(): void {
    this.disposed = true
    if (this.pending) {
      clearTimeout(this.pending.timer)
      this.pending.resolve({ success: false, error: '任务中心已关闭' })
      this.pending = undefined
    }
    this.window = undefined
    this.readyTarget = ''
  }

  private ensureWindow(): TaskWindowLike {
    if (this.window && !this.window.isDestroyed()) return this.window
    const window = this.options.createWindow()
    this.window = window
    this.options.logger('ELECTRON_TASK_WINDOW_CREATE')
    window.webContents.on('did-start-loading', () => {
      if (this.pending && window.webContents.getURL() === this.pending.target) this.options.logger('ELECTRON_TASK_WINDOW_NAVIGATION_STARTED')
    })
    window.webContents.on('did-finish-load', () => {
      if (!this.pending || window.webContents.getURL() !== this.pending.target) return
      this.pending.didFinishLoad = true
      this.options.logger('ELECTRON_TASK_WINDOW_DID_FINISH_LOAD')
      this.resolveWhenReady()
    })
    window.webContents.on('did-fail-load', (_event, errorCode, _description, _validatedURL, isMainFrame) => {
      if (isMainFrame && errorCode !== -3 && this.pending) void this.fail('ELECTRON_TASK_WINDOW_LOAD_FAILED', '任务中心加载失败')
    })
    window.webContents.on('render-process-gone', () => {
      if (this.pending) void this.fail('ELECTRON_TASK_WINDOW_LOAD_FAILED', '任务中心渲染进程已退出')
    })
    window.on('unresponsive', () => {
      if (this.pending) void this.fail('ELECTRON_TASK_WINDOW_LOAD_FAILED', '任务中心无响应')
    })
    window.on('closed', () => {
      if (this.window !== window) return
      this.window = undefined
      this.readyTarget = ''
      if (this.pending) void this.fail('ELECTRON_TASK_WINDOW_LOAD_FAILED', '任务中心窗口已关闭')
    })
    return window
  }

  private reveal(event: string): void {
    if (!this.window || this.window.isDestroyed()) return
    if (!this.window.isVisible()) this.window.show()
    this.window.focus()
    this.options.logger(event)
  }

  private resolveWhenReady(): void {
    const pending = this.pending
    if (!pending || !pending.didFinishLoad || !pending.mounted || !pending.themed || !pending.interactive) return
    clearTimeout(pending.timer)
    this.pending = undefined
    this.readyTarget = pending.target
    this.reveal('ELECTRON_TASK_WINDOW_SHOWN')
    pending.resolve({ success: true })
  }

  private async fail(event: string, detail: string): Promise<void> {
    const pending = this.pending
    if (!pending) return
    clearTimeout(pending.timer)
    this.pending = undefined
    this.readyTarget = ''
    this.options.logger(event)
    if (this.window && !this.window.isDestroyed()) {
      try { await this.options.loadFailurePage(this.window, '任务中心加载失败', detail) } catch { /* 保留原始失败结果 */ }
      this.reveal('ELECTRON_TASK_WINDOW_SHOWN')
    }
    pending.resolve({ success: false, error: '任务中心加载失败' })
  }
}
