import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { resolve } from 'node:path'

import { DESKTOP_IPC, DESKTOP_SESSION_COOKIE } from '../shared/bridge'
import { PythonBackendManager } from './backend-manager'
import { loadDesktopConfig } from './config'
import { registerDesktopIpc } from './ipc'
import { createFileLogger } from './logger'
import { GrantedPathRegistry } from './path-access'
import {
  desktopSessionCookiePath,
  installWindowSecurity,
  isTrustedRendererSender,
} from './security'

app.enableSandbox()

let mainWindow: BrowserWindow | undefined
let backend: PythonBackendManager | undefined
let allowQuit = false
let requestedExitCode = 0
let shutdownPromise: Promise<void> | undefined
let smokeTimer: NodeJS.Timeout | undefined
const allowedOrigins = new Set<string>()
const pathRegistry = new GrantedPathRegistry()

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
  shutdownPromise ??= shutdown().finally(() => {
    allowQuit = true
    app.exit(requestedExitCode)
  })
})

app.on('window-all-closed', () => app.quit())
process.once('SIGINT', () => app.quit())
process.once('SIGTERM', () => app.quit())

if (hasSingleInstanceLock) {
  void app.whenReady().then(startDesktop).catch((cause) => handleFatalStartup(cause))
}

async function startDesktop(): Promise<void> {
  const config = loadDesktopConfig({
    isPackaged: app.isPackaged,
    appPath: app.getAppPath(),
    resourcesPath: process.resourcesPath,
  })
  const logger = createFileLogger(resolve(app.getPath('logs'), 'electron.log'))
  backend = new PythonBackendManager({
    executable: config.backendExecutable,
    argumentsPrefix: config.backendArgumentsPrefix,
    projectRoot: config.projectRoot,
    rendererOrigin: config.rendererOrigin,
    startupTimeoutMs: config.startupTimeoutMs,
    logger,
  })
  mainWindow = createMainWindow(Boolean(config.devServerUrl))
  registerDesktopIpc({
    ipcMain,
    dialog,
    shell,
    window: mainWindow,
    appInfo: {
      version: app.getVersion(),
      platform: process.platform,
      isPackaged: app.isPackaged,
    },
    backend,
    pathRegistry,
    isTrustedSender: (event) => Boolean(
      mainWindow
      && isTrustedRendererSender(event, mainWindow, [...allowedOrigins]),
    ),
    onRendererReady: handleRendererReady,
  })
  backend.onStatusChange((status) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(DESKTOP_IPC.backendStatusChanged, status)
    }
    if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1' && status.state === 'failed') {
      requestExit(2)
    }
  })

  await loadStatusPage(mainWindow, '正在启动 NetConsole', '正在启动本地 Python Core，请稍候。')
  mainWindow.show()

  try {
    const runtime = await backend.start()
    const backendOrigin = new URL(runtime.baseUrl).origin
    const rendererUrl = config.devServerUrl ?? runtime.baseUrl
    allowedOrigins.add(backendOrigin)
    allowedOrigins.add(new URL(rendererUrl).origin)
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
    await mainWindow.loadURL(rendererUrl)
    if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') {
      smokeTimer = setTimeout(() => requestExit(2), 30_000)
    }
  } catch (cause) {
    await loadStatusPage(
      mainWindow,
      'NetConsole 启动失败',
      cause instanceof Error ? cause.message : '本地 Python 后端启动失败。',
    )
    if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') requestExit(2)
  }
}

function createMainWindow(development: boolean): BrowserWindow {
  const window = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    backgroundColor: '#0b1220',
    webPreferences: {
      preload: resolve(__dirname, '..', 'preload', 'index.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      navigateOnDragDrop: false,
      partition: 'netconsole-desktop-ephemeral',
    },
  })
  installWindowSecurity(window, () => [...allowedOrigins], development)
  return window
}

async function loadStatusPage(window: BrowserWindow, title: string, detail: string): Promise<void> {
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>${escapeHtml(title)}</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:#0b1220;color:#e2e8f0;font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid #26344d;border-radius:14px;background:#111b2e;text-align:center}h1{font-size:22px;margin:0 0 12px}p{color:#94a3b8;line-height:1.7;margin:0}</style></head><body><main><h1>${escapeHtml(title)}</h1><p>${escapeHtml(detail)}</p></main></body></html>`
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
}

function handleRendererReady(healthOk: boolean): void {
  if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST !== '1') return
  if (smokeTimer) clearTimeout(smokeTimer)
  requestExit(healthOk ? 0 : 2)
}

function requestExit(code: number): void {
  requestedExitCode = Math.max(requestedExitCode, code)
  app.quit()
}

async function shutdown(): Promise<void> {
  if (smokeTimer) clearTimeout(smokeTimer)
  smokeTimer = undefined
  pathRegistry.clear()
  try {
    await backend?.stop()
  } catch {
    // BackendManager has already moved to the failed state and logged the reason.
    requestedExitCode = Math.max(requestedExitCode, 1)
  }
}

async function handleFatalStartup(cause: unknown): Promise<void> {
  if (!mainWindow) {
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
