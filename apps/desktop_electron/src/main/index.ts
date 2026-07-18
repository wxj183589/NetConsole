import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from 'electron'
import { resolve } from 'node:path'

import { DESKTOP_IPC, DESKTOP_SESSION_COOKIE, type RendererReadyReport } from '../shared/bridge'
import { PythonBackendManager } from './backend-manager'
import { isDevelopmentMenuEnabled, loadDesktopConfig } from './config'
import { registerDesktopIpc, type DesktopIpcRegistration } from './ipc'
import { createFileLogger, type DesktopLogger } from './logger'
import {
  cleanupCodexTemporaryDataRoot,
  resolveCodexTemporaryDataRoot,
} from './development-data-root'
import { GrantedPathRegistry } from './path-access'
import { StartupTimeline } from './startup-timeline'
import {
  installRendererDiagnostics,
  safeDiagnosticUrl,
} from './renderer-diagnostics'
import {
  desktopSessionCookiePath,
  installWindowSecurity,
  isTrustedRendererSender,
  secureWebPreferences,
} from './security'

app.enableSandbox()

let mainWindow: BrowserWindow | undefined
let taskWindow: BrowserWindow | undefined
let backend: PythonBackendManager | undefined
let allowQuit = false
let requestedExitCode = 0
let shutdownPromise: Promise<void> | undefined
let smokeWatchdogTimer: NodeJS.Timeout | undefined
let smokeStableTimer: NodeJS.Timeout | undefined
let smokeRendererHealthy = false
let smokeRendererLoading = true
const rendererOrigins = new Set<string>()
const connectionOrigins = new Set<string>()
const pathRegistry = new GrantedPathRegistry()
let rendererUrl = ''
let rendererDevelopment = false
let logger: DesktopLogger = () => undefined
let desktopIpc: DesktopIpcRegistration | undefined
const startupStartedAt = process.hrtime.bigint()
let startupTimeline: StartupTimeline | undefined
let codexTemporaryDataRoot: string | undefined

const hasSingleInstanceLock = app.requestSingleInstanceLock()
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
  codexTemporaryDataRoot = resolveCodexTemporaryDataRoot()
  const config = loadDesktopConfig({
    isPackaged: app.isPackaged,
    appPath: app.getAppPath(),
    resourcesPath: process.resourcesPath,
    userDataPath: app.getPath('userData'),
  })
  logger = createFileLogger(resolve(app.getPath('logs'), 'electron.log'))
  startupTimeline = new StartupTimeline(logger, startupStartedAt)
  startupTimeline.mark('electron.app_ready')
  backend = new PythonBackendManager({
    executable: config.backendExecutable,
    argumentsPrefix: config.backendArgumentsPrefix,
    projectRoot: config.projectRoot,
    dataRoot: config.dataRoot,
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
  desktopIpc = registerDesktopIpc({
    ipcMain,
    dialog,
    shell,
    window: mainWindow,
    windowForEvent: (event) => BrowserWindow.fromWebContents(event.sender as Electron.WebContents) ?? mainWindow,
    openTaskWindow,
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
    startSmokeWatchdog()
    startupTimeline.mark('renderer.navigation_started')
    mainWindow.webContents.once('dom-ready', () => startupTimeline?.mark('renderer.dom_ready'))
    void mainWindow.loadURL(rendererUrl).catch((cause) => {
      const message = cause instanceof Error ? cause.message : String(cause)
      if (/ERR_ABORTED/.test(message)) {
        logger('ELECTRON_RENDERER_NAVIGATION_SUPERSEDED')
        return
      }
      logger('ELECTRON_RENDERER_NAVIGATION_REJECTED', message)
      if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') requestExit(2)
    })
  } catch (cause) {
    await loadStatusPage(
      mainWindow,
      'NetConsole 启动失败',
      cause instanceof Error ? cause.message : '本地 Python 后端启动失败。',
      rendererUrl,
    )
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
    backgroundColor: '#0b1220',
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
  return window
}

function installManagedWindowDiagnostics(window: BrowserWindow, smoke = false): void {
  installRendererDiagnostics(window, {
    logger,
    getRetryUrl: () => rendererUrl,
    ...(smoke ? { onLoadStarted: handleRendererLoadStarted, onLoadStopped: handleRendererLoadStopped } : {}),
    showError: (title, detail, retryUrl) => loadStatusPage(window, title, detail, retryUrl),
  })
}

async function openTaskWindow(context: { taskId?: string; module?: string; status?: string }): Promise<void> {
  if (!mainWindow || !rendererUrl) throw new Error('任务窗口尚未就绪')
  if (!taskWindow || taskWindow.isDestroyed()) {
    taskWindow = createMainWindow(rendererDevelopment)
    installManagedWindowDiagnostics(taskWindow)
    taskWindow.setTitle('NetConsole 任务中心')
    taskWindow.on('close', (event) => {
      if (allowQuit) return
      event.preventDefault()
      taskWindow?.hide()
    })
  }
  const url = new URL('/tasks', rendererUrl)
  url.searchParams.set('task_window', '1')
  if (context.taskId) url.searchParams.set('task_id', context.taskId)
  if (context.module) url.searchParams.set('module', context.module)
  if (context.status) url.searchParams.set('status', context.status)
  await taskWindow.loadURL(url.toString())
  if (taskWindow.isMinimized()) taskWindow.restore()
  taskWindow.show()
  taskWindow.focus()
}

async function loadStatusPage(
  window: BrowserWindow,
  title: string,
  detail: string,
  retryUrl = '',
): Promise<void> {
  const retry = retryUrl
    ? `<a href="${escapeHtml(retryUrl)}">重试</a>`
    : ''
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>${escapeHtml(title)}</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:#0b1220;color:#e2e8f0;font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid #26344d;border-radius:14px;background:#111b2e;text-align:center}h1{font-size:22px;margin:0 0 12px}p{color:#94a3b8;line-height:1.7;margin:0 0 18px}a{display:inline-block;padding:8px 18px;border-radius:8px;background:#1787c9;color:#fff;text-decoration:none}</style></head><body><main><h1>${escapeHtml(title)}</h1><p>${escapeHtml(detail)}</p>${retry}</main></body></html>`
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
}

function handleRendererReady(report: RendererReadyReport): void {
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
  scheduleSmokeStableExit()
}

function scheduleSmokeStableExit(): void {
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
    if (codexTemporaryDataRoot) {
      try {
        cleanupCodexTemporaryDataRoot(codexTemporaryDataRoot)
        logger('ELECTRON_CODEX_DATA_ROOT_CLEANED')
      } catch (cause) {
        const code = cause instanceof Error
          ? (cause as NodeJS.ErrnoException).code || cause.name
          : 'unknown'
        logger('ELECTRON_CODEX_DATA_ROOT_CLEANUP_FAILED', `code=${code}`)
      } finally {
        codexTemporaryDataRoot = undefined
      }
    }
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
