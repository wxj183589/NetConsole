import type { BackendState } from '../shared/bridge'

export interface TrayRuntimeContext {
  backendState: BackendState
  activeSiteName?: string
  closeToTrayEnabled: boolean
  visibleWindowCount: number
}

export interface TrayMenuItem {
  label?: string
  type?: 'normal' | 'separator' | 'checkbox'
  enabled?: boolean
  checked?: boolean
  click?: () => void
}

export interface TrayLike {
  setToolTip(value: string): void
  setContextMenu(menu: unknown): void
  on(event: string, listener: () => void): void
  displayBalloon?(options: { title: string; content: string; noSound?: boolean }): void
  destroy(): void
  isDestroyed?(): boolean
}

export interface TrayControllerOptions {
  createTray(): TrayLike
  buildMenu(template: TrayMenuItem[]): unknown
  showMainWindow(): Promise<void> | void
  showTaskWindow(): Promise<void> | void
  createWorkspaceWindow(): Promise<void> | void
  setCloseToTrayEnabled(enabled: boolean): Promise<void> | void
  explicitQuit(): void
  logger(event: string): void
}

const INITIAL_CONTEXT: TrayRuntimeContext = {
  backendState: 'starting',
  closeToTrayEnabled: true,
  visibleWindowCount: 1,
}

export class TrayController {
  private tray: TrayLike | undefined
  private context: TrayRuntimeContext = { ...INITIAL_CONTEXT }
  private updateTimer: ReturnType<typeof setTimeout> | undefined
  private backgroundHintShown = false

  constructor(private readonly options: TrayControllerOptions) {}

  get available(): boolean {
    return Boolean(this.tray && !this.tray.isDestroyed?.())
  }

  initialize(): boolean {
    if (this.available) return true
    try {
      this.options.logger('ELECTRON_TRAY_CREATE')
      this.tray = this.options.createTray()
      this.tray.on('double-click', () => {
        void this.options.showMainWindow()
      })
      this.rebuildMenu()
      this.options.logger('ELECTRON_TRAY_READY')
      return true
    } catch {
      this.tray = undefined
      this.options.logger('ELECTRON_TRAY_INITIALIZATION_FAILED')
      return false
    }
  }

  updateContext(context: Partial<TrayRuntimeContext>): void {
    this.context = {
      ...this.context,
      ...context,
      activeSiteName: sanitizeSiteName(context.activeSiteName ?? this.context.activeSiteName),
    }
    if (this.updateTimer) clearTimeout(this.updateTimer)
    this.updateTimer = setTimeout(() => {
      this.updateTimer = undefined
      this.rebuildMenu()
    }, 80)
  }

  showMainWindow(): void {
    void this.options.showMainWindow()
  }

  showTaskWindow(): void {
    void this.options.showTaskWindow()
  }

  createWorkspaceWindow(): void {
    void this.options.createWorkspaceWindow()
  }

  rebuildMenu(): void {
    const tray = this.tray
    if (!tray || tray.isDestroyed?.()) return
    try {
      tray.setToolTip(resolveTooltip(this.context.backendState))
      tray.setContextMenu(this.options.buildMenu([
        { label: '打开 NetConsole', click: () => this.showMainWindow() },
        { label: '新建工作区窗口', click: () => this.createWorkspaceWindow() },
        { label: '打开任务中心', click: () => this.showTaskWindow() },
        { type: 'separator' },
        { label: `Backend：${backendStateLabel(this.context.backendState)}`, enabled: false },
        { label: `当前局点：${this.context.activeSiteName || '未选择'}`, enabled: false },
        {
          label: '关闭主窗口后驻留通知区域',
          type: 'checkbox',
          checked: this.context.closeToTrayEnabled,
          click: () => {
            void this.options.setCloseToTrayEnabled(!this.context.closeToTrayEnabled)
          },
        },
        { type: 'separator' },
        { label: '退出 NetConsole', click: () => this.options.explicitQuit() },
      ]))
      this.options.logger('ELECTRON_TRAY_MENU_UPDATED')
    } catch {
      this.options.logger('ELECTRON_TRAY_MENU_UPDATE_FAILED')
    }
  }

  displayBackgroundHint(): void {
    if (this.backgroundHintShown || !this.available) return
    this.backgroundHintShown = true
    try {
      this.tray?.displayBalloon?.({
        title: 'NetConsole 正在后台运行',
        content: '可通过系统托盘图标重新打开或退出程序。',
        noSound: true,
      })
    } catch {
      this.options.logger('ELECTRON_TRAY_HINT_FAILED')
    }
  }

  dispose(): void {
    if (this.updateTimer) clearTimeout(this.updateTimer)
    this.updateTimer = undefined
    if (this.tray && !this.tray.isDestroyed?.()) this.tray.destroy()
    this.tray = undefined
    this.options.logger('ELECTRON_TRAY_DISPOSED')
  }
}

function backendStateLabel(state: BackendState): string {
  if (state === 'ready') return '在线'
  if (state === 'starting') return '正在启动'
  return '离线'
}

function resolveTooltip(state: BackendState): string {
  if (state === 'starting') return 'NetConsole · 正在启动'
  if (state === 'ready') return 'NetConsole'
  return 'NetConsole · Backend 离线'
}

function sanitizeSiteName(value: string | undefined): string | undefined {
  if (!value) return undefined
  const safe = value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim()
  return safe ? safe.slice(0, 80) : undefined
}
