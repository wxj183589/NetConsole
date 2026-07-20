import { app, BrowserWindow, dialog, ipcMain, Menu, nativeTheme, shell } from 'electron'
import { resolve } from 'node:path'

import { DESKTOP_IPC, DESKTOP_SESSION_COOKIE, DESKTOP_SESSION_HEADER, type NativeActionResult, type RendererHostReport, type SiteStorageRestartRequest, type TaskWindowContext } from '../shared/bridge'
import { PythonBackendManager } from './backend-manager'
import { DesktopBootstrapStore } from './bootstrap'
import { DESKTOP_SAFE_BACKGROUND_COLOR, isDevelopmentMenuEnabled, loadDesktopConfig, resolveDesktopBackgroundColor } from './config'
import { registerDesktopIpc, type DesktopIpcRegistration } from './ipc'
import { createFileLogger, type DesktopLogger } from './logger'
import { resolveDesktopStorageContext } from './development-data-root'
import { GrantedPathRegistry } from './path-access'
import { UiPreferenceStore } from './ui-preferences'
import { StartupTimeline } from './startup-timeline'
import {
  installRendererDiagnostics,
  safeDiagnosticUrl,
} from './renderer-diagnostics'
import {
  MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION,
  MANAGED_RENDERER_RETRY_ACTION,
  ManagedRendererRetryNavigation,
  ManagedWindowErrorCoordinator,
  RendererThemeDisplayGate,
} from './renderer-theme-display-gate'
import { TaskWindowController } from './task-window-controller'
import {
  desktopSessionCookiePath,
  installWindowSecurity,
  isAllowedNavigation,
  isTrustedRendererSender,
  secureWebPreferences,
} from './security'

const desktopStorageContext = resolveDesktopStorageContext()
if (!desktopStorageContext.persistent) app.setPath('userData', desktopStorageContext.userDataRoot!)
app.enableSandbox()

let mainWindow: BrowserWindow | undefined
let taskWindow: BrowserWindow | undefined
let taskWindowController: TaskWindowController | undefined
let backend: PythonBackendManager | undefined
let allowQuit = false
let requestedExitCode = 0
let shutdownPromise: Promise<void> | undefined
let smokeWatchdogTimer: NodeJS.Timeout | undefined
let smokeStableTimer: NodeJS.Timeout | undefined
let smokeRendererHealthy = false
let smokeRendererLoading = true
let taskWindowSmokeStarted = false
const rendererOrigins = new Set<string>()
const connectionOrigins = new Set<string>()
const pathRegistry = new GrantedPathRegistry()
let rendererUrl = ''
let rendererDevelopment = false
let logger: DesktopLogger = () => undefined
let desktopIpc: DesktopIpcRegistration | undefined
const startupStartedAt = process.hrtime.bigint()
let startupTimeline: StartupTimeline | undefined
let bootstrapStore: DesktopBootstrapStore | undefined
let desktopDataRoot = ''
let desktopActiveSiteId = ''
const windowDisplayGates = new WeakMap<BrowserWindow, RendererThemeDisplayGate>()
const windowErrorCoordinators = new WeakMap<BrowserWindow, ManagedWindowErrorCoordinator>()
const windowRetryNavigations = new WeakMap<BrowserWindow, ManagedRendererRetryNavigation>()
const windowRendererTargets = new WeakMap<BrowserWindow, string>()
const RENDERER_THEME_READY_TIMEOUT_MS = 10_000

const hasSingleInstanceLock = process.env.NETCONSOLE_ISOLATED_SMOKE === '1'
  ? true
  : app.requestSingleInstanceLock()
if (!hasSingleInstanceLock) app.quit()

app.on('second-instance', () => {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.focus()
})

app.on('before-quit', (event) => {
  if (allowQuit) return
  event.preventDefault()
  beginShutdownAndExit()
})

app.on('window-all-closed', () => requestExit(0))
process.once('SIGINT', () => requestExit(0))
process.once('SIGTERM', () => requestExit(0))

if (hasSingleInstanceLock) {
  void app.whenReady().then(startDesktop).catch((cause) => handleFatalStartup(cause))
}

async function startDesktop(): Promise<void> {
  bootstrapStore = new DesktopBootstrapStore(app.getPath('userData'))
  const bootstrapResult = bootstrapStore.loadForRuntime({ storageMode: desktopStorageContext.mode })
  const bootstrap = bootstrapResult.value
  const config = loadDesktopConfig({
    isPackaged: app.isPackaged,
    appPath: app.getAppPath(),
    resourcesPath: process.resourcesPath,
    userDataPath: app.getPath('userData'),
    bootstrapDataRoot: bootstrap.data_root,
    bootstrapActiveSiteId: bootstrap.active_site_id,
    storageMode: desktopStorageContext.mode,
  })
  desktopDataRoot = config.dataRoot
  desktopActiveSiteId = config.activeSiteId ?? ''
  logger = createFileLogger(resolve(app.getPath('logs'), 'electron.log'))
  logger('ELECTRON_STORAGE_MODE', `mode=${desktopStorageContext.mode}`)
  if (bootstrapResult.rejectedEphemeralRoot) logger('ELECTRON_BOOTSTRAP_EPHEMERAL_ROOT_REJECTED')
  startupTimeline = new StartupTimeline(logger, startupStartedAt)
  startupTimeline.mark('electron.app_ready')
  backend = new PythonBackendManager({
    executable: config.backendExecutable,
    argumentsPrefix: config.backendArgumentsPrefix,
    projectRoot: config.projectRoot,
    dataRoot: config.dataRoot,
    activeSiteId: config.activeSiteId,
    runtimeMode: config.runtimeMode,
    pythonPath: config.backendPythonPath,
    rendererOrigin: config.rendererOrigin,
    startupTimeoutMs: config.startupTimeoutMs,
    logger,
    onStartupMilestone: (event) => startupTimeline?.mark(event),
  })
  const developmentMenu = isDevelopmentMenuEnabled(config.devServerUrl)
  if (!developmentMenu) Menu.setApplicationMenu(null)
  rendererDevelopment = Boolean(config.devServerUrl)
  mainWindow = createMainWindow(rendererDevelopment, developmentMenu)
  startupTimeline.mark('electron.window_created')
  mainWindow.on('closed', () => {
    mainWindow = undefined
    if (!allowQuit) requestExit(0)
  })
  installManagedWindowDiagnostics(mainWindow, true)
  taskWindowController = new TaskWindowController({
    createWindow: () => {
      const window = createMainWindow(rendererDevelopment)
      taskWindow = window
      window.setTitle('NetConsole 任务中心')
      window.on('close', (event) => {
        if (allowQuit) return
        event.preventDefault()
        window.hide()
      })
      window.on('closed', () => { if (taskWindow === window) taskWindow = undefined })
      return window
    },
    buildTarget: buildTaskRendererTarget,
    loadLoadingPage: (window) => loadStatusPage(window as BrowserWindow, '正在加载任务中心…', '正在加载任务列表与当前上下文。'),
    loadFailurePage: (window, title, detail) => loadStatusPage(window as BrowserWindow, title, detail, true, true),
    prepareNavigation: (window, target) => rememberManagedRendererTarget(window as BrowserWindow, target),
    logger: (event) => logger(event),
    timeoutMs: RENDERER_THEME_READY_TIMEOUT_MS,
  })
  desktopIpc = registerDesktopIpc({
    ipcMain,
    dialog,
    shell,
    window: mainWindow,
    windowForEvent: (event) => BrowserWindow.fromWebContents(event.sender as Electron.WebContents) ?? mainWindow,
    openTaskWindow,
    restartBackend: restartManagedBackend,
    appInfo: {
      version: app.getVersion(),
      platform: process.platform,
      isPackaged: app.isPackaged,
    },
    backend,
    pathRegistry,
    isTrustedSender: (event) => Boolean(
      (mainWindow && isTrustedRendererSender(event, mainWindow, [...rendererOrigins]))
      || (taskWindow && isTrustedRendererSender(event, taskWindow, [...rendererOrigins])),
    ),
    onRendererReady: handleRendererReady,
    logger,
    uiPreferenceStore: new UiPreferenceStore(app.getPath('userData')),
  })
  backend.onStatusChange((status) => {
    logger('ELECTRON_BACKEND_STATUS', `state=${status.state}`)
    const publicStatus = {
      state: status.state,
      ...(status.baseUrl ? { baseUrl: status.baseUrl } : {}),
      ...(status.error ? { error: '本地后端不可用' } : {}),
    }
    for (const window of [mainWindow, taskWindow]) {
      if (window && !window.isDestroyed()) window.webContents.send(DESKTOP_IPC.backendStatusChanged, publicStatus)
    }
    if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1' && status.state === 'failed') {
      requestExit(2)
    }
  })

  await loadStatusPage(mainWindow, '正在启动 NetConsole', '正在启动本地 Python Core，请稍候。')
  startupTimeline.mark('electron.loading_view_shown')
  mainWindow.show()

  try {
    const runtime = await backend.start()
    desktopActiveSiteId = await readBackendActiveSiteId(runtime.baseUrl, runtime.apiToken, desktopActiveSiteId)
    const backendOrigin = new URL(runtime.baseUrl).origin
    rendererUrl = config.devServerUrl ?? runtime.baseUrl
    const rendererOrigin = new URL(rendererUrl).origin
    rendererOrigins.add(rendererOrigin)
    connectionOrigins.add(rendererOrigin)
    connectionOrigins.add(backendOrigin)
    const cookiePath = desktopSessionCookiePath(Boolean(config.devServerUrl))
    await mainWindow.webContents.session.cookies.set({
      url: new URL(cookiePath, `${runtime.baseUrl}/`).toString(),
      name: DESKTOP_SESSION_COOKIE,
      value: runtime.apiToken,
      httpOnly: true,
      sameSite: 'strict',
      secure: false,
      path: cookiePath,
    })
    if (desktopStorageContext.persistent && desktopActiveSiteId) {
      bootstrapStore.save({ schema_version: 1, data_root: desktopDataRoot, active_site_id: desktopActiveSiteId })
    }
    rememberManagedRendererTarget(mainWindow, rendererUrl)
    startSmokeWatchdog()
    startupTimeline.mark('renderer.navigation_started')
    const rendererWindow = mainWindow
    rendererWindow.webContents.once('dom-ready', () => startupTimeline?.mark('renderer.dom_ready'))
    armRendererThemeDisplay(rendererWindow)
    void rendererWindow.loadURL(rendererUrl).catch((cause) => {
      const message = cause instanceof Error ? cause.message : String(cause)
      if (/ERR_ABORTED/.test(message)) {
        logger('ELECTRON_RENDERER_NAVIGATION_SUPERSEDED')
        return
      }
      logger('ELECTRON_RENDERER_NAVIGATION_REJECTED', message)
      void showManagedWindowError(
        rendererWindow,
        'NetConsole 界面加载失败',
        '界面资源加载失败，请检查本机日志后重试。',
        true,
      )
      if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') requestExit(2)
    })
  } catch (cause) {
    if (mainWindow) {
      await showManagedWindowError(
        mainWindow,
        'NetConsole 启动失败',
        cause instanceof Error ? cause.message : '本地 Python 后端启动失败。',
        Boolean(windowRendererTargets.get(mainWindow)),
      )
    }
    if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') requestExit(2)
  }
}

function createMainWindow(development: boolean, developmentMenu = false): BrowserWindow {
  const window = new BrowserWindow({
    title: 'NetConsole',
    width: 1360,
    height: 860,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    backgroundColor: DESKTOP_SAFE_BACKGROUND_COLOR,
    autoHideMenuBar: !developmentMenu,
    webPreferences: secureWebPreferences(
      resolve(__dirname, '..', 'preload', 'index.cjs'),
      development,
    ),
  })
  installWindowSecurity(
    window,
    () => [...rendererOrigins],
    () => [...connectionOrigins],
    development,
    (target) => logger('ELECTRON_NAVIGATION_BLOCKED', `target=${safeDiagnosticUrl(target)}`),
    () => logger('ELECTRON_UNMANAGED_DOWNLOAD_BLOCKED'),
  )
  const retryNavigation = new ManagedRendererRetryNavigation(
    window,
    () => retryManagedRenderer(window),
    () => logger('ELECTRON_RENDERER_RETRY_REJECTED'),
    (cause) => logger(
      'ELECTRON_RENDERER_RETRY_FAILED',
      `type=${cause instanceof Error ? cause.name : 'unknown'}`,
    ),
    openTasksInMainWindow,
  )
  const errorCoordinator = new ManagedWindowErrorCoordinator()
  const displayGate = new RendererThemeDisplayGate(window, {
    timeoutMs: RENDERER_THEME_READY_TIMEOUT_MS,
    renderTimeoutFallback: () => loadStatusPage(
      window,
      'NetConsole 界面启动超时',
      '界面没有在限定时间内完成主题和设置加载，请重试。',
      Boolean(windowRendererTargets.get(window)),
    ),
    onVisible: (reason) => {
      if (reason !== 'theme-ready') errorCoordinator.markVisible()
      logger('ELECTRON_WINDOW_VISIBLE', `reason=${reason}`)
    },
    onFallbackError: (reason, cause) => logger(
      'ELECTRON_WINDOW_FALLBACK_FAILED',
      `reason=${reason} type=${cause instanceof Error ? cause.name : 'unknown'}`,
    ),
  })
  windowDisplayGates.set(window, displayGate)
  windowErrorCoordinators.set(window, errorCoordinator)
  windowRetryNavigations.set(window, retryNavigation)
  window.once('closed', () => displayGate.dispose())
  return window
}

async function restartManagedBackend(update: SiteStorageRestartRequest): Promise<void> {
  if (!backend || !mainWindow || !bootstrapStore) throw new Error('desktop runtime is unavailable')
  if (!desktopStorageContext.persistent) throw new Error('隔离测试模式不允许修改正式局点或数据根')
  const previousRoot = desktopDataRoot
  const previousSite = desktopActiveSiteId
  const nextRoot = update.dataRoot ?? previousRoot
  const nextSite = update.activeSiteId ?? previousSite
  await backend.stop()
  backend.configureStorage(nextRoot, nextSite)
  try {
    const runtime = await backend.start()
    desktopDataRoot = nextRoot
    desktopActiveSiteId = nextSite
    bootstrapStore.save({ schema_version: 1, data_root: nextRoot, active_site_id: nextSite })
    const backendOrigin = new URL(runtime.baseUrl).origin
    connectionOrigins.add(backendOrigin)
    const cookiePath = desktopSessionCookiePath(rendererDevelopment)
    await mainWindow.webContents.session.cookies.set({
      url: new URL(cookiePath, `${runtime.baseUrl}/`).toString(),
      name: DESKTOP_SESSION_COOKIE,
      value: runtime.apiToken,
      httpOnly: true,
      sameSite: 'strict',
      secure: false,
      path: cookiePath,
    })
    if (!rendererDevelopment) {
      rendererUrl = runtime.baseUrl
      rendererOrigins.clear()
      rendererOrigins.add(backendOrigin)
    }
    rememberManagedRendererTarget(mainWindow, rendererUrl)
    armRendererThemeDisplay(mainWindow)
    await mainWindow.loadURL(rendererUrl)
  } catch (cause) {
    await backend.stop()
    backend.configureStorage(previousRoot, previousSite)
    await backend.start()
    throw cause
  }
}

async function readBackendActiveSiteId(baseUrl: string, apiToken: string, fallback: string): Promise<string> {
  try {
    const response = await fetch(`${baseUrl}/api/v1/sites/active`, {
      cache: 'no-store',
      headers: { [DESKTOP_SESSION_HEADER]: apiToken },
    })
    if (!response.ok) return fallback
    const payload = await response.json() as { site_id?: unknown }
    const siteId = typeof payload.site_id === 'string' ? payload.site_id.trim() : ''
    return /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(siteId) ? siteId : fallback
  } catch {
    return fallback
  }
}

function installManagedWindowDiagnostics(window: BrowserWindow, smoke = false): void {
  installRendererDiagnostics(window, {
    logger,
    canRetry: () => Boolean(windowRendererTargets.get(window)),
    ...(smoke ? { onLoadStarted: handleRendererLoadStarted, onLoadStopped: handleRendererLoadStopped } : {}),
    showError: (title, detail, retryable) => showManagedWindowError(window, title, detail, retryable),
  })
}

async function openTaskWindow(context: TaskWindowContext): Promise<NativeActionResult> {
  if (!mainWindow || !rendererUrl || !taskWindowController) return { success: false, error: '任务窗口尚未就绪' }
  return taskWindowController.open(context)
}

function buildTaskRendererTarget(context: TaskWindowContext): string {
  if (!rendererUrl) throw new Error('任务窗口尚未就绪')
  const url = new URL('/desktop/tasks', rendererUrl)
  url.searchParams.set('task_window', '1')
  if (context.taskId) url.searchParams.set('task_id', context.taskId)
  if (context.module) url.searchParams.set('module', context.module)
  if (context.status) url.searchParams.set('status', context.status)
  return url.toString()
}

async function loadStatusPage(
  window: BrowserWindow,
  title: string,
  detail: string,
  retryable = false,
  openMainTasks = false,
): Promise<void> {
  const retryNavigation = windowRetryNavigations.get(window)
  retryNavigation?.disarm()
  const statusTheme = nativeTheme.shouldUseDarkColors ? 'dark' : 'light'
  const statusBackground = resolveDesktopBackgroundColor(statusTheme)
  const statusPanel = statusTheme === 'dark' ? '#18212d' : '#ffffff'
  const statusText = statusTheme === 'dark' ? '#f2f4f7' : '#182230'
  const statusMuted = statusTheme === 'dark' ? '#98a2b3' : '#667085'
  const statusBorder = statusTheme === 'dark' ? '#344054' : '#e4e7ec'
  const statusShadow = statusTheme === 'dark'
    ? '0 14px 38px rgb(0 0 0 / 42%)'
    : '0 14px 38px rgb(7 16 31 / 12%)'
  window.setBackgroundColor(statusBackground)
  const retry = retryable
    ? `<a href="${MANAGED_RENDERER_RETRY_ACTION}">重试</a>`
    : ''
  const mainTasks = openMainTasks
    ? `<a class="secondary" href="${MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION}">在主窗口打开任务中心</a>`
    : ''
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>${escapeHtml(title)}</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:${statusBackground};color:${statusText};font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid ${statusBorder};border-radius:14px;background:${statusPanel};text-align:center;box-shadow:${statusShadow}}h1{font-size:22px;margin:0 0 12px}p{color:${statusMuted};line-height:1.7;margin:0 0 18px}.actions{display:flex;justify-content:center;gap:10px;flex-wrap:wrap}a{display:inline-block;padding:8px 18px;border-radius:8px;background:#0078d4;color:#fff;text-decoration:none}.secondary{background:transparent;color:${statusText};border:1px solid ${statusBorder}}</style></head><body><main><h1>${escapeHtml(title)}</h1><p>${escapeHtml(detail)}</p><div class="actions">${retry}${mainTasks}</div></main></body></html>`
  const statusPageUrl = `data:text/html;charset=utf-8,${encodeURIComponent(html)}`
  await window.loadURL(statusPageUrl)
  if ((retryable || openMainTasks) && !window.isDestroyed()) retryNavigation?.armForStatusPage(statusPageUrl)
}

function handleRendererReady(report: RendererHostReport, sourceWindow: unknown): void {
  const window = sourceWindow === mainWindow
    ? mainWindow
    : sourceWindow === taskWindow
      ? taskWindow
      : undefined
  if (window === taskWindow) {
    logger(
      'ELECTRON_TASK_WINDOW_READY_REPORT',
      'resolvedTheme' in report ? 'phase=theme' : `phase=${report.phase} surface=${report.surface || 'none'}`,
    )
  }
  if (window === taskWindow) taskWindowController?.acceptRendererReport(report, taskWindowController.currentWindow)
  if ('resolvedTheme' in report) {
    if (window && window === mainWindow) windowDisplayGates.get(window)?.acceptResolvedTheme()
    return
  }
  if (report.phase === 'failed' && window && windowDisplayGates.get(window)?.isWaiting()) {
    void showManagedWindowError(
      window,
      'NetConsole 界面启动失败',
      '界面运行时初始化失败，请检查本机日志后重试。',
      Boolean(windowRendererTargets.get(window)),
    )
  }
  if (window !== mainWindow) return
  if (report.phase === 'mounted') startupTimeline?.mark('renderer.mounted')
  if (report.phase === 'interactive' && report.healthOk) startupTimeline?.mark('desktop.interactive')
  if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST !== '1' || report.phase === 'mounted') return
  logger('ELECTRON_SMOKE_RENDERER_READY', `phase=${report.phase} health_ok=${report.healthOk}`)
  if (smokeStableTimer) clearTimeout(smokeStableTimer)
  if (!report.healthOk || report.phase === 'failed') {
    smokeStableTimer = undefined
    requestExit(2)
    return
  }
  smokeRendererHealthy = true
  if (process.env.NETCONSOLE_ELECTRON_TASK_WINDOW_SMOKE === '1') {
    if (smokeStableTimer) {
      clearTimeout(smokeStableTimer)
      smokeStableTimer = undefined
    }
    if (!taskWindowSmokeStarted) {
      taskWindowSmokeStarted = true
      void runTaskWindowSmoke()
    }
    return
  }
  scheduleSmokeStableExit()
}

async function runTaskWindowSmoke(): Promise<void> {
  try {
    let result = await openTaskWindow({ module: 'rail' })
    if (!result.success && taskWindowController) {
      logger('ELECTRON_TASK_WINDOW_SMOKE_RETRY')
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 500))
      result = await taskWindowController.retry()
    }
    logger(result.success ? 'ELECTRON_TASK_WINDOW_SMOKE_PASSED' : 'ELECTRON_TASK_WINDOW_SMOKE_FAILED')
    requestExit(result.success ? 0 : 2)
  } catch {
    logger('ELECTRON_TASK_WINDOW_SMOKE_FAILED')
    requestExit(2)
  }
}

function scheduleSmokeStableExit(): void {
  if (process.env.NETCONSOLE_ELECTRON_TASK_WINDOW_SMOKE === '1') return
  if (!smokeRendererHealthy || smokeRendererLoading || smokeStableTimer) return
  smokeStableTimer = setTimeout(() => {
    logger('ELECTRON_SMOKE_RENDERER_STABLE')
    smokeStableTimer = undefined
    requestExit(0)
  }, 1_500)
}

function handleRendererLoadStarted(): void {
  smokeRendererLoading = true
  if (smokeStableTimer) {
    clearTimeout(smokeStableTimer)
    smokeStableTimer = undefined
    logger('ELECTRON_SMOKE_STABILITY_RESET')
  }
}

function handleRendererLoadStopped(): void {
  smokeRendererLoading = false
  scheduleSmokeStableExit()
}

function startSmokeWatchdog(): void {
  if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST !== '1') return
  if (smokeWatchdogTimer) clearTimeout(smokeWatchdogTimer)
  smokeRendererHealthy = false
  smokeRendererLoading = true
  taskWindowSmokeStarted = false
  logger('ELECTRON_SMOKE_WATCHDOG_STARTED')
  smokeWatchdogTimer = setTimeout(() => {
    logger('ELECTRON_SMOKE_WATCHDOG_EXPIRED')
    requestExit(2)
  }, 30_000)
}

function requestExit(code: number): void {
  requestedExitCode = Math.max(requestedExitCode, code)
  beginShutdownAndExit()
}

function beginShutdownAndExit(): void {
  shutdownPromise ??= shutdown().finally(() => {
    traceSmoke('EXIT_REQUESTED')
    allowQuit = true
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy()
    if (taskWindow && !taskWindow.isDestroyed()) taskWindow.destroy()
    app.releaseSingleInstanceLock()
    app.exit(requestedExitCode)
    traceSmoke('EXIT_RETURNED')
    setImmediate(() => process.exit(requestedExitCode))
  })
}

async function shutdown(): Promise<void> {
  if (smokeWatchdogTimer) clearTimeout(smokeWatchdogTimer)
  if (smokeStableTimer) clearTimeout(smokeStableTimer)
  smokeWatchdogTimer = undefined
  smokeStableTimer = undefined
  smokeRendererHealthy = false
  smokeRendererLoading = false
  logger('ELECTRON_SHUTDOWN_STARTED')
  traceSmoke('SHUTDOWN_STARTED')
  try {
    taskWindowController?.dispose()
    taskWindowController = undefined
    await desktopIpc?.shutdown()
    logger('ELECTRON_DOWNLOADS_STOPPED')
    traceSmoke('DOWNLOADS_STOPPED')
    await backend?.stop()
    logger('ELECTRON_SHUTDOWN_COMPLETE')
    traceSmoke('BACKEND_STOPPED')
  } catch {
    // BackendManager has already moved to the failed state and logged the reason.
    requestedExitCode = Math.max(requestedExitCode, 1)
  } finally {
    pathRegistry.clear()
  }
}

function traceSmoke(event: string): void {
  if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') {
    process.stderr.write(`[netconsole-smoke] ${event}\n`)
  }
}

async function handleFatalStartup(cause: unknown): Promise<void> {
  if (!mainWindow) {
    Menu.setApplicationMenu(null)
    mainWindow = createMainWindow(false)
    await loadStatusPage(
      mainWindow,
      'NetConsole 启动失败',
      cause instanceof Error ? cause.message : 'Electron Desktop 初始化失败。',
    )
    mainWindow.show()
  }
  if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') requestExit(2)
}

function armRendererThemeDisplay(window: BrowserWindow): void {
  windowRetryNavigations.get(window)?.disarm()
  windowErrorCoordinators.get(window)?.reset()
  windowDisplayGates.get(window)?.arm()
}

async function retryManagedRenderer(window: BrowserWindow): Promise<void> {
  if (window === taskWindow && taskWindowController) {
    logger('ELECTRON_RENDERER_RETRY_STARTED')
    await taskWindowController.retry()
    return
  }
  const target = windowRendererTargets.get(window)
  if (
    window.isDestroyed()
    || !target
    || !isAllowedNavigation(target, [...rendererOrigins])
  ) {
    logger('ELECTRON_RENDERER_RETRY_REJECTED')
    return
  }
  logger('ELECTRON_RENDERER_RETRY_STARTED')
  armRendererThemeDisplay(window)
  try {
    await window.loadURL(target)
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    if (/ERR_ABORTED/.test(message)) {
      logger('ELECTRON_RENDERER_RETRY_SUPERSEDED')
      return
    }
    logger(
      'ELECTRON_RENDERER_RETRY_NAVIGATION_FAILED',
      `type=${cause instanceof Error ? cause.name : 'unknown'}`,
    )
    await showManagedWindowError(
      window,
      'NetConsole 界面加载失败',
      '界面资源加载失败，请检查本机日志后重试。',
      true,
    )
  }
}

async function openTasksInMainWindow(): Promise<void> {
  if (!mainWindow || mainWindow.isDestroyed() || !rendererUrl) return
  const target = new URL('/tasks', rendererUrl).toString()
  rememberManagedRendererTarget(mainWindow, target)
  armRendererThemeDisplay(mainWindow)
  await mainWindow.loadURL(target)
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.focus()
}

function rememberManagedRendererTarget(window: BrowserWindow, target: string): void {
  if (!isAllowedNavigation(target, [...rendererOrigins])) {
    throw new Error('managed Renderer target is not trusted')
  }
  windowRendererTargets.set(window, target)
}

async function showManagedWindowError(
  window: BrowserWindow,
  title: string,
  detail: string,
  retryable = false,
): Promise<void> {
  const coordinator = windowErrorCoordinators.get(window)
  const show = async () => {
    const render = () => loadStatusPage(window, title, detail, retryable)
    const gate = windowDisplayGates.get(window)
    if (gate?.isWaiting()) {
      await gate.revealFallback('renderer-failed', render)
      return
    }
    await render()
    if (!window.isDestroyed() && !window.isVisible()) window.show()
  }
  if (coordinator) {
    await coordinator.show(show)
  } else {
    await show()
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] ?? character)
}

app.on('child-process-gone', (_event, details) => {
  logger('ELECTRON_CHILD_PROCESS_GONE', `type=${details.type} reason=${details.reason}`)
})
