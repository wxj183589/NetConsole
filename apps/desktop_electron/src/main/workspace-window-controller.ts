import { randomUUID } from 'node:crypto'

import type {
  NativeActionResult,
  RendererHostReport,
  WorkspaceWindowOpenRequest,
  WorkspaceWindowSnapshot,
  WorkspaceWindowStateResult,
} from '../shared/bridge'
import {
  WORKSPACE_LAYOUT_MAX_WINDOWS,
  WorkspaceLayoutStore,
  normalizeWorkspaceBounds,
  type PersistedWorkspaceWindow,
  type WorkspaceWindowBounds,
} from './workspace-layout-store'
import { setManagedWindowTitle } from './window-title'

export interface WorkspaceWindowWebContentsLike {
  id: number
  getURL(): string
  on(event: string, listener: (...args: unknown[]) => void): void
}

export interface WorkspaceWindowLike {
  webContents: WorkspaceWindowWebContentsLike
  loadURL(url: string): Promise<void>
  isDestroyed(): boolean
  isVisible(): boolean
  isMinimized(): boolean
  isMaximized(): boolean
  show(): void
  hide(): void
  focus(): void
  restore(): void
  maximize(): void
  moveTop?(): void
  close(): void
  setTitle(title: string): void
  getBounds(): WorkspaceWindowBounds
  on(event: string, listener: (...args: unknown[]) => void): void
}

export interface WorkspaceWindowControllerOptions {
  createWindow(role: 'main' | 'workspace', bounds?: WorkspaceWindowBounds): WorkspaceWindowLike
  buildTarget(routeFullPath: string, windowId: string, role: 'main' | 'workspace'): string
  prepareNavigation(window: WorkspaceWindowLike, target: string): void
  loadLoadingPage(window: WorkspaceWindowLike): Promise<void>
  loadFailurePage(window: WorkspaceWindowLike, title: string, detail: string): Promise<void>
  getWorkAreas(): WorkspaceWindowBounds[]
  shouldHideMainToTray(): boolean
  isExplicitQuit(): boolean
  onMainHidden(): void
  onVisibleWindowCountChanged(count: number): void
  logger(event: string): void
  timeoutMs: number
}

interface ManagedWorkspaceWindow {
  windowId: string
  role: 'main' | 'workspace'
  window: WorkspaceWindowLike
  snapshot: WorkspaceWindowSnapshot | null
  lastFocusedAt: number
}

interface PendingWorkspaceOpen {
  windowId: string
  target: string
  didFinishLoad: boolean
  mounted: boolean
  themed: boolean
  interactive: boolean
  timer: ReturnType<typeof setTimeout>
  resolve(result: NativeActionResult): void
}

export class WorkspaceWindowController {
  private readonly managed = new Map<string, ManagedWorkspaceWindow>()
  private readonly pending = new Map<string, PendingWorkspaceOpen>()
  private readonly restored: PersistedWorkspaceWindow[]
  private layoutTimer: ReturnType<typeof setTimeout> | undefined
  private acceptingWindows = true
  private mainWindowId = 'main'

  constructor(
    private readonly layoutStore: WorkspaceLayoutStore,
    private readonly options: WorkspaceWindowControllerOptions,
  ) {
    this.restored = layoutStore.load()
  }

  ensureMainWindow(navigate = true): WorkspaceWindowLike {
    const existing = this.managed.get(this.mainWindowId)
    if (existing && !existing.window.isDestroyed()) return existing.window
    const record = this.restored.find((item) => item.role === 'main')
      || defaultWindowRecord(this.mainWindowId, 'main')
    this.mainWindowId = record.windowId
    const managed = this.createManaged(record)
    if (navigate) void this.navigateManaged(managed)
    return managed.window
  }

  registerMainWindow(window: WorkspaceWindowLike, record?: PersistedWorkspaceWindow): void {
    if (this.managed.has(this.mainWindowId)) return
    const restored = record
      || this.restored.find((item) => item.role === 'main')
      || defaultWindowRecord(this.mainWindowId, 'main')
    this.mainWindowId = restored.windowId
    this.registerManaged(window, restored)
  }

  async showMainWindow(): Promise<void> {
    const existing = this.managed.get(this.mainWindowId)
    const window = existing && !existing.window.isDestroyed()
      ? existing.window
      : this.ensureMainWindow(true)
    if (window.isMinimized()) window.restore()
    if (!window.isVisible()) window.show()
    window.moveTop?.()
    window.focus()
    this.options.logger('ELECTRON_MAIN_WINDOW_RESTORED_FROM_TRAY')
    this.emitVisibleCount()
  }

  async open(request: WorkspaceWindowOpenRequest): Promise<NativeActionResult> {
    if (!this.acceptingWindows || this.options.isExplicitQuit()) {
      return { success: false, error: '应用正在退出，不能创建新窗口' }
    }
    if (this.managed.size >= WORKSPACE_LAYOUT_MAX_WINDOWS) {
      return { success: false, error: `工作区窗口最多允许 ${WORKSPACE_LAYOUT_MAX_WINDOWS} 个` }
    }
    const windowId = `workspace-${randomUUID()}`
    const snapshot = createInitialSnapshot(windowId, request)
    const record: PersistedWorkspaceWindow = {
      ...defaultWindowRecord(windowId, 'workspace'),
      snapshot,
    }
    return this.openRecord(record)
  }

  async restoreAdditionalWindows(): Promise<void> {
    for (const record of this.restored.filter((item) => item.role === 'workspace')) {
      if (this.managed.size >= WORKSPACE_LAYOUT_MAX_WINDOWS) break
      await this.openRecord(record)
    }
  }

  getMainWindow(): WorkspaceWindowLike | undefined {
    const value = this.managed.get(this.mainWindowId)?.window
    return value && !value.isDestroyed() ? value : undefined
  }

  getMostRecentlyFocusedWindow(): WorkspaceWindowLike | undefined {
    return [...this.managed.values()]
      .filter((item) => !item.window.isDestroyed())
      .sort((left, right) => right.lastFocusedAt - left.lastFocusedAt)[0]?.window
  }

  getVisibleWorkspaceWindows(): WorkspaceWindowLike[] {
    return [...this.managed.values()]
      .map((item) => item.window)
      .filter((window) => !window.isDestroyed() && window.isVisible())
  }

  getAllManagedWindows(): WorkspaceWindowLike[] {
    return [...this.managed.values()]
      .map((item) => item.window)
      .filter((window) => !window.isDestroyed())
  }

  countVisibleBusinessWindows(): number {
    return this.getVisibleWorkspaceWindows().length
  }

  getWindowState(sourceWindow: unknown): WorkspaceWindowStateResult {
    const managed = this.findByWindow(sourceWindow)
    if (!managed) throw new Error('工作区窗口未注册')
    return {
      windowId: managed.windowId,
      snapshot: managed.snapshot
        ? { ...managed.snapshot, tabs: managed.snapshot.tabs.map((tab) => ({ ...tab })) }
        : null,
    }
  }

  saveWindowState(sourceWindow: unknown, snapshot: WorkspaceWindowSnapshot): void {
    const managed = this.findByWindow(sourceWindow)
    if (!managed || snapshot.windowId !== managed.windowId) {
      throw new Error('工作区快照不属于当前窗口')
    }
    managed.snapshot = {
      ...snapshot,
      tabs: snapshot.tabs.map((tab) => ({ ...tab })),
    }
    this.persistManaged(managed)
  }

  prepareSiteSwitchSnapshots(): Map<string, WorkspaceWindowSnapshot | null> {
    const checkpoint = new Map<string, WorkspaceWindowSnapshot | null>()
    try {
      for (const managed of this.managed.values()) {
        checkpoint.set(managed.windowId, cloneSnapshot(managed.snapshot))
        managed.snapshot = siteSwitchSnapshot(managed.snapshot, managed.windowId)
        this.persistManaged(managed, false)
      }
      this.layoutStore.flush()
      return checkpoint
    } catch (cause) {
      for (const managed of this.managed.values()) {
        if (checkpoint.has(managed.windowId)) {
          managed.snapshot = cloneSnapshot(checkpoint.get(managed.windowId) ?? null)
          this.persistManaged(managed, false)
        }
      }
      throw cause
    }
  }

  restoreSiteSwitchSnapshots(checkpoint: Map<string, WorkspaceWindowSnapshot | null>): void {
    for (const managed of this.managed.values()) {
      if (!checkpoint.has(managed.windowId)) continue
      managed.snapshot = cloneSnapshot(checkpoint.get(managed.windowId) ?? null)
      this.persistManaged(managed, false)
    }
    this.layoutStore.flush()
  }

  setWindowTitle(sourceWindow: unknown, title: string): void {
    const managed = this.findByWindow(sourceWindow)
    if (!managed || managed.window.isDestroyed()) throw new Error('工作区窗口未注册')
    setManagedWindowTitle(managed.window, title === 'Dashboard' ? 'NetConsole' : title)
  }

  acceptRendererReport(report: RendererHostReport, sourceWindow: unknown): void {
    const managed = this.findByWindow(sourceWindow)
    if (!managed) return
    const pending = this.pending.get(managed.windowId)
    if (!pending) return
    if ('resolvedTheme' in report) {
      pending.themed = true
      this.resolvePending(managed.windowId)
      return
    }
    if (report.surface !== 'workspace-window') return
    if (report.phase === 'failed') {
      void this.failPending(managed.windowId, '工作区窗口初始化失败')
      return
    }
    if (report.phase === 'mounted') pending.mounted = true
    if (report.phase === 'interactive' && report.healthOk) pending.interactive = true
    this.resolvePending(managed.windowId)
  }

  closeAllForQuit(): void {
    this.acceptingWindows = false
    for (const item of this.managed.values()) {
      if (!item.window.isDestroyed()) item.window.close()
    }
  }

  flush(): void {
    if (this.layoutTimer) clearTimeout(this.layoutTimer)
    this.layoutTimer = undefined
    for (const item of this.managed.values()) {
      if (!item.window.isDestroyed()) this.persistManaged(item, false)
    }
    this.layoutStore.flush()
  }

  dispose(): void {
    this.acceptingWindows = false
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer)
      pending.resolve({ success: false, error: '工作区窗口控制器已关闭' })
    }
    this.pending.clear()
    this.flush()
    this.managed.clear()
  }

  private async openRecord(record: PersistedWorkspaceWindow): Promise<NativeActionResult> {
    try {
      const managed = this.createManaged(record)
      await this.options.loadLoadingPage(managed.window)
      if (!managed.window.isVisible()) managed.window.show()
      this.emitVisibleCount()
      return await this.navigateManaged(managed, true)
    } catch {
      return { success: false, error: '工作区窗口加载失败' }
    }
  }

  private createManaged(record: PersistedWorkspaceWindow): ManagedWorkspaceWindow {
    if (record.role === 'main') {
      return this.registerManaged(this.options.createWindow('main'), record)
    }
    const normalized = {
      ...record,
      bounds: normalizeWorkspaceBounds(record.bounds, this.options.getWorkAreas()),
    }
    const window = this.options.createWindow('workspace', normalized.bounds)
    if (normalized.maximized) window.maximize()
    return this.registerManaged(window, normalized)
  }

  private registerManaged(
    window: WorkspaceWindowLike,
    record: PersistedWorkspaceWindow,
  ): ManagedWorkspaceWindow {
    const managed: ManagedWorkspaceWindow = {
      windowId: record.windowId,
      role: record.role,
      window,
      snapshot: record.snapshot,
      lastFocusedAt: Date.now(),
    }
    this.managed.set(record.windowId, managed)
    this.persistManaged(managed)
    window.on('focus', () => {
      managed.lastFocusedAt = Date.now()
      this.options.logger('ELECTRON_WORKSPACE_WINDOW_FOCUSED')
    })
    window.on('show', () => this.emitVisibleCount())
    window.on('hide', () => this.emitVisibleCount())
    if (managed.role === 'workspace') {
      window.on('move', () => this.scheduleLayoutSave())
      window.on('resize', () => this.scheduleLayoutSave())
    }
    window.on('close', (event: unknown) => {
      if (
        managed.role === 'main'
        && !this.options.isExplicitQuit()
        && this.options.shouldHideMainToTray()
      ) {
        const closeEvent = event as { preventDefault?: () => void }
        closeEvent.preventDefault?.()
        window.hide()
        this.options.logger('ELECTRON_MAIN_WINDOW_HIDDEN_TO_TRAY')
        this.options.onMainHidden()
        this.emitVisibleCount()
      }
    })
    window.on('closed', () => {
      this.pending.delete(managed.windowId)
      this.managed.delete(managed.windowId)
      if (managed.role === 'workspace' && !this.options.isExplicitQuit()) {
        this.layoutStore.remove(managed.windowId)
        this.scheduleLayoutSave()
      }
      this.emitVisibleCount()
    })
    window.webContents.on('did-finish-load', () => {
      const pending = this.pending.get(managed.windowId)
      if (!pending || window.webContents.getURL() !== pending.target) return
      pending.didFinishLoad = true
      this.resolvePending(managed.windowId)
    })
    window.webContents.on('did-fail-load', (_event, errorCode, _description, _url, isMainFrame) => {
      if (isMainFrame && errorCode !== -3) void this.failPending(managed.windowId, '工作区窗口加载失败')
    })
    this.options.logger(managed.role === 'main'
      ? 'ELECTRON_MAIN_WINDOW_REGISTERED'
      : 'ELECTRON_WORKSPACE_WINDOW_CREATED')
    return managed
  }

  private async navigateManaged(
    managed: ManagedWorkspaceWindow,
    awaitReadiness = false,
  ): Promise<NativeActionResult> {
    const route = activeRoute(managed.snapshot)
    const target = this.options.buildTarget(route, managed.windowId, managed.role)
    this.options.prepareNavigation(managed.window, target)
    if (!awaitReadiness) {
      await managed.window.loadURL(target)
      return { success: true }
    }
    return new Promise<NativeActionResult>((resolve) => {
      const pending: PendingWorkspaceOpen = {
        windowId: managed.windowId,
        target,
        didFinishLoad: false,
        mounted: false,
        themed: false,
        interactive: false,
        timer: setTimeout(() => {
          void this.failPending(managed.windowId, '工作区窗口启动超时')
        }, this.options.timeoutMs),
        resolve,
      }
      this.pending.set(managed.windowId, pending)
      void managed.window.loadURL(target).catch(() => {
        void this.failPending(managed.windowId, '工作区窗口加载失败')
      })
    })
  }

  private resolvePending(windowId: string): void {
    const pending = this.pending.get(windowId)
    if (
      !pending
      || !pending.didFinishLoad
      || !pending.mounted
      || !pending.themed
      || !pending.interactive
    ) return
    clearTimeout(pending.timer)
    this.pending.delete(windowId)
    const window = this.managed.get(windowId)?.window
    if (window && !window.isDestroyed()) {
      if (!window.isVisible()) window.show()
      window.focus()
    }
    pending.resolve({ success: true })
  }

  private async failPending(windowId: string, detail: string): Promise<void> {
    const pending = this.pending.get(windowId)
    if (!pending) return
    clearTimeout(pending.timer)
    this.pending.delete(windowId)
    const window = this.managed.get(windowId)?.window
    if (window && !window.isDestroyed()) {
      try {
        await this.options.loadFailurePage(window, '工作区窗口加载失败', detail)
        if (!window.isVisible()) window.show()
      } catch {
        // 保留原始失败结果。
      }
    }
    pending.resolve({ success: false, error: '工作区窗口加载失败' })
  }

  private findByWindow(sourceWindow: unknown): ManagedWorkspaceWindow | undefined {
    return [...this.managed.values()].find((item) => item.window === sourceWindow)
  }

  private persistManaged(managed: ManagedWorkspaceWindow, scheduleFlush = true): void {
    if (managed.window.isDestroyed()) return
    this.layoutStore.upsert(managed.role === 'main'
      ? {
          windowId: managed.windowId,
          role: 'main',
          snapshot: managed.snapshot,
        }
      : {
          windowId: managed.windowId,
          role: 'workspace',
          bounds: managed.window.getBounds(),
          maximized: managed.window.isMaximized(),
          snapshot: managed.snapshot,
        })
    if (scheduleFlush) this.scheduleLayoutSave()
  }

  private scheduleLayoutSave(): void {
    if (this.layoutTimer) clearTimeout(this.layoutTimer)
    this.layoutTimer = setTimeout(() => {
      this.layoutTimer = undefined
      for (const item of this.managed.values()) {
        if (!item.window.isDestroyed()) this.persistManaged(item, false)
      }
      this.layoutStore.flush()
    }, 300)
  }

  private emitVisibleCount(): void {
    this.options.onVisibleWindowCountChanged(this.countVisibleBusinessWindows())
  }
}

function defaultWindowRecord(
  windowId: string,
  role: PersistedWorkspaceWindow['role'],
): PersistedWorkspaceWindow {
  return role === 'main'
    ? { windowId, role, snapshot: null }
    : {
        windowId,
        role,
        bounds: { x: 80, y: 80, width: 1_360, height: 860 },
        maximized: false,
        snapshot: null,
      }
}

function createInitialSnapshot(
  windowId: string,
  request: WorkspaceWindowOpenRequest,
): WorkspaceWindowSnapshot {
  const now = Date.now()
  const id = `tab-${randomUUID()}`
  const instanceId = `instance-${randomUUID()}`
  return {
    schemaVersion: 1,
    windowId,
    activeTabId: id,
    tabs: [{
      id,
      instanceId,
      routeFullPath: request.routeFullPath,
      title: request.title,
      identityKey: `restored:${instanceId}`,
      cacheKey: `restored:${instanceId}`,
      pinned: false,
      openedAt: now,
      lastActivatedAt: now,
    }],
  }
}

function activeRoute(snapshot: WorkspaceWindowSnapshot | null): string {
  if (!snapshot) return '/'
  return snapshot.tabs.find((tab) => tab.id === snapshot.activeTabId)?.routeFullPath || '/'
}

function cloneSnapshot(snapshot: WorkspaceWindowSnapshot | null): WorkspaceWindowSnapshot | null {
  return snapshot ? { ...snapshot, tabs: snapshot.tabs.map((tab) => ({ ...tab })) } : null
}

function siteSwitchSnapshot(
  snapshot: WorkspaceWindowSnapshot | null,
  windowId: string,
): WorkspaceWindowSnapshot {
  if (!snapshot) return createInitialSnapshot(windowId, { routeFullPath: '/', title: 'Dashboard' })
  const retained: WorkspaceWindowSnapshot['tabs'] = []
  const retainedPaths = new Set<string>()
  const active = snapshot.tabs.find((tab) => tab.id === snapshot.activeTabId)
  for (const tab of active ? [active, ...snapshot.tabs.filter((item) => item.id !== active.id)] : snapshot.tabs) {
    try {
      const pathname = new URL(tab.routeFullPath, 'http://127.0.0.1').pathname
      if ((pathname === '/' || pathname === '/settings') && !retainedPaths.has(pathname)) {
        retained.push(tab)
        retainedPaths.add(pathname)
      }
    } catch {
      // 丢弃损坏或越界的旧工作区路由。
    }
  }
  let dashboard = retained.find((tab) => {
    try { return new URL(tab.routeFullPath, 'http://127.0.0.1').pathname === '/' }
    catch { return false }
  })
  if (!dashboard) {
    dashboard = createInitialSnapshot(windowId, { routeFullPath: '/', title: 'Dashboard' }).tabs[0]
    retained.unshift(dashboard)
  }
  const activeTabId = retained.some((tab) => tab.id === snapshot.activeTabId)
    ? snapshot.activeTabId
    : dashboard.id
  return {
    ...snapshot,
    activeTabId,
    tabs: retained.map((tab) => ({ ...tab })),
  }
}
