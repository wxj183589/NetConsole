import type { BackendState } from '../shared/bridge'

export interface TrayRuntimeContext {
  backendState: BackendState
  activeSiteId?: string
  activeSiteName?: string
  sites: TraySiteSummary[]
  siteSwitching: boolean
  closeToTrayEnabled: boolean
  visibleWindowCount: number
  activeTaskCount: number
  failedTaskCount: number
  warningTaskCount: number
}

export interface TraySiteSummary {
  siteId: string
  displayName: string
  active: boolean
  selectable: boolean
}

export interface TrayMenuItem {
  label?: string
  type?: 'normal' | 'separator' | 'checkbox' | 'radio'
  enabled?: boolean
  checked?: boolean
  click?: () => void
  submenu?: TrayMenuItem[]
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
  showTaskCenter(): Promise<void> | void
  createWorkspaceWindow(): Promise<void> | void
  requestSiteSwitch(siteId: string): Promise<void> | void
  setCloseToTrayEnabled(enabled: boolean): Promise<void> | void
  explicitQuit(): void
  logger(event: string): void
}

const INITIAL_CONTEXT: TrayRuntimeContext = {
  backendState: 'starting',
  sites: [],
  siteSwitching: false,
  closeToTrayEnabled: true,
  visibleWindowCount: 1,
  activeTaskCount: 0,
  failedTaskCount: 0,
  warningTaskCount: 0,
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
      sites: (context.sites ?? this.context.sites).flatMap((site) => {
        const displayName = sanitizeSiteName(site.displayName)
        return displayName ? [{ ...site, displayName }] : []
      }),
      activeTaskCount: sanitizeCount(context.activeTaskCount ?? this.context.activeTaskCount),
      failedTaskCount: sanitizeCount(context.failedTaskCount ?? this.context.failedTaskCount),
      warningTaskCount: sanitizeCount(context.warningTaskCount ?? this.context.warningTaskCount),
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

  showTaskCenter(): void {
    void this.options.showTaskCenter()
  }

  createWorkspaceWindow(): void {
    void this.options.createWorkspaceWindow()
  }

  rebuildMenu(): void {
    const tray = this.tray
    if (!tray || tray.isDestroyed?.()) return
    try {
      tray.setToolTip(resolveTooltip(this.context))
      tray.setContextMenu(this.options.buildMenu([
        { label: '打开 NetConsole', click: () => this.showMainWindow() },
        { label: '新建工作区窗口', click: () => this.createWorkspaceWindow() },
        { label: taskCenterMenuLabel(this.context), click: () => this.showTaskCenter() },
        { type: 'separator' },
        { label: `Backend：${backendStateLabel(this.context.backendState)}`, enabled: false },
        { label: `当前局点：${this.context.activeSiteName || '未选择'}`, enabled: false },
        {
          label: this.context.siteSwitching ? '正在切换局点…' : '快速切换局点',
          enabled: this.context.backendState === 'ready' && !this.context.siteSwitching && this.context.sites.length > 0,
          submenu: this.buildSiteSwitchMenu(),
        },
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

  private buildSiteSwitchMenu(): TrayMenuItem[] {
    if (this.context.siteSwitching) return [{ label: '正在切换局点…', enabled: false }]
    if (this.context.backendState !== 'ready') return [{ label: 'Backend 未就绪', enabled: false }]
    if (!this.context.sites.length) return [{ label: '暂无可切换局点', enabled: false }]
    const duplicateNames = new Set(
      [...this.context.sites]
        .map((site) => site.displayName)
        .filter((name, index, names) => names.indexOf(name) !== index),
    )
    return this.context.sites.map((site) => {
      const active = site.siteId === this.context.activeSiteId
      const label = duplicateNames.has(site.displayName)
        ? `${site.displayName} (${site.siteId})`
        : site.displayName
      return {
        label,
        type: 'radio',
        checked: active,
        enabled: !active && site.selectable,
        click: () => { void this.options.requestSiteSwitch(site.siteId) },
      }
    })
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

function resolveTooltip(context: TrayRuntimeContext): string {
  const taskStatus = context.failedTaskCount
    ? ` · 失败任务 ${context.failedTaskCount}`
    : context.activeTaskCount
      ? ` · 运行任务 ${context.activeTaskCount}`
      : ''
  if (context.backendState === 'starting') return 'NetConsole · 正在启动'
  if (context.backendState === 'ready') {
    return context.activeSiteName ? `NetConsole · ${context.activeSiteName}${taskStatus}` : `NetConsole · 未选择局点${taskStatus}`
  }
  return context.activeSiteName
    ? `NetConsole · ${context.activeSiteName} · Backend 离线`
    : 'NetConsole · Backend 离线'
}

function taskCenterMenuLabel(context: TrayRuntimeContext): string {
  const states = [
    context.activeTaskCount ? `运行 ${context.activeTaskCount}` : '',
    context.failedTaskCount ? `失败 ${context.failedTaskCount}` : '',
    context.warningTaskCount ? `告警 ${context.warningTaskCount}` : '',
  ].filter(Boolean)
  return states.length ? `打开任务中心（${states.join(' / ')}）` : '打开任务中心'
}

function sanitizeCount(value: number): number {
  return Number.isSafeInteger(value) ? Math.max(0, Math.min(value, 999)) : 0
}

function sanitizeSiteName(value: string | undefined): string | undefined {
  if (!value) return undefined
  const safe = value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim()
  return safe ? safe.slice(0, 80) : undefined
}
