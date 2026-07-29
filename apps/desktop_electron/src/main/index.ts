import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, nativeTheme, Notification as ElectronNotification, screen, shell, Tray } from 'electron'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { DESKTOP_IPC, DESKTOP_SESSION_COOKIE, DESKTOP_SESSION_HEADER, type CloseToTrayState, type NativeActionResult, type RendererHostReport, type RendererRecoveryState, type RendererWorkloadReport, type SiteStorageRestartRequest, type TaskWindowContext, type WorkspaceWindowOpenRequest, type WorkspaceWindowSnapshot, type WorkspaceWindowStateResult } from '../shared/bridge'
import { PythonBackendManager, type BackendRuntimeInfo } from './backend-manager'
import { DesktopBootstrapStore } from './bootstrap'
import { DESKTOP_SAFE_BACKGROUND_COLOR, isDevelopmentMenuEnabled, loadDesktopConfig, resolveDesktopBackgroundColor } from './config'
import { registerDesktopIpc, type DesktopIpcRegistration } from './ipc'
import { createFileLogger, type DesktopLogger } from './logger'
import { buildChildProcessGoneDiagnostic, logDevelopmentGpuFeatureStatus } from './gpu-diagnostics'
import { ensureDesktopRuntimePaths, resolveDesktopStorageContext } from './development-data-root'
import { resolveDesktopDataRootConfiguration } from './data-root-configuration'
import { GrantedPathRegistry } from './path-access'
import { UiPreferenceStore } from './ui-preferences'
import { ExternalToolStore } from './external-tool-store'
import { ExternalToolService } from './external-tool-service'
import { StartupTimeline } from './startup-timeline'
import {
  installRendererDiagnostics,
  safeDiagnosticUrl,
  type RendererFailureActions,
  type RendererProcessFailure,
} from './renderer-diagnostics'
import { NETCONSOLE_WINDOW_TITLE, resolveDesktopIconPath, resolveTrayIconPath } from './branding'
import {
  MANAGED_RENDERER_OPEN_LOGS_ACTION,
  MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION,
  MANAGED_RENDERER_RETRY_ACTION,
  MANAGED_RENDERER_SAFE_RECOVERY_ACTION,
  ManagedRendererRetryNavigation,
  ManagedWindowErrorCoordinator,
  RendererThemeDisplayGate,
} from './renderer-theme-display-gate'
import { TaskNotificationController } from './task-notification'
import { TrayController, type TrayMenuItem, type TraySiteSummary } from './tray-controller'
import { WorkspaceLayoutStore, type WorkspaceWindowBounds } from './workspace-layout-store'
import { WorkspaceWindowController } from './workspace-window-controller'
import {
  desktopSessionCookiePath,
  installWindowSecurity,
  isAllowedNavigation,
  isTrustedRendererSender,
  secureWebPreferences,
} from './security'

const desktopDataRootResolution = resolveDesktopDataRootConfiguration()
const desktopStorageContext = resolveDesktopStorageContext({
  ...process.env,
  NETCONSOLE_DATA_ROOT: desktopDataRootResolution.dataRoot,
})
ensureDesktopRuntimePaths(desktopStorageContext)
app.setPath('userData', desktopStorageContext.userDataRoot)
app.setPath('sessionData', desktopStorageContext.sessionDataRoot)
app.setPath('cache', desktopStorageContext.cacheRoot)
app.setPath('logs', desktopStorageContext.logsRoot)
app.setPath('crashDumps', desktopStorageContext.crashDumpsRoot)
app.setPath('temp', desktopStorageContext.tempRoot)
assertElectronStoragePaths()
app.enableSandbox()

let mainWindow: BrowserWindow | undefined
let workspaceWindowController: WorkspaceWindowController | undefined
let workspaceLayoutStore: WorkspaceLayoutStore | undefined
let trayController: TrayController | undefined
let taskNotificationController: TaskNotificationController | undefined
let trayAvailable = false
let closeToTrayEnabled = true
let explicitQuitRequested = false
let backend: PythonBackendManager | undefined
let allowQuit = false
let requestedExitCode = 0
let shutdownPromise: Promise<void> | undefined
let smokeWatchdogTimer: NodeJS.Timeout | undefined
let smokeStableTimer: NodeJS.Timeout | undefined
let smokeRendererHealthy = false
let smokeRendererLoading = true
let taskCenterSmokeStarted = false
let workspaceTraySmokeStarted = false
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
let uiPreferenceStore: UiPreferenceStore | undefined
let desktopDataRoot = ''
let desktopActiveSiteId = ''
let desktopActiveSiteName = ''
let desktopSites: TraySiteSummary[] = []
const windowDisplayGates = new WeakMap<BrowserWindow, RendererThemeDisplayGate>()
const windowErrorCoordinators = new WeakMap<BrowserWindow, ManagedWindowErrorCoordinator>()
const windowRetryNavigations = new WeakMap<BrowserWindow, ManagedRendererRetryNavigation>()
const windowRendererTargets = new WeakMap<BrowserWindow, string>()
const latestRendererWorkloads = new Map<number, RendererWorkloadReport>()
const rendererProcessFailures = new Map<number, RendererProcessFailure>()
const rendererRecoveries = new Map<number, RendererRecoveryState>()
let recentGpuProcessFailureAt = 0
const RENDERER_THEME_READY_TIMEOUT_MS = 10_000
const RECENT_GPU_FAILURE_WINDOW_MS = 15_000

const hasSingleInstanceLock = process.env.NETCONSOLE_ISOLATED_SMOKE === '1'
  ? true
  : app.requestSingleInstanceLock()
if (!hasSingleInstanceLock) app.quit()

app.on('second-instance', () => {
  void restoreApplicationWindow()
})

app.on('before-quit', (event) => {
  if (allowQuit) return
  event.preventDefault()
  beginShutdownAndExit()
})

app.on('window-all-closed', () => {
  if (trayAvailable && closeToTrayEnabled && !explicitQuitRequested) return
  requestExit(0)
})
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
    resolvedDataRoot: desktopStorageContext.dataRoot,
    bootstrapActiveSiteId: bootstrap.active_site_id,
    storageMode: desktopStorageContext.mode,
  })
  if (resolve(config.dataRoot) !== resolve(desktopStorageContext.dataRoot)) {
    throw new Error('Electron、Backend 和持久化配置的数据根不一致，已停止启动。')
  }
  desktopDataRoot = config.dataRoot
  desktopActiveSiteId = config.activeSiteId ?? ''
  logger = createFileLogger(resolve(app.getPath('logs'), 'electron.log'))
  logger('ELECTRON_STORAGE_MODE', `mode=${desktopStorageContext.mode}`)
  logger('NETCONSOLE_STORAGE_ROOT_SELECTED', `data_root=${config.dataRoot} source=${desktopDataRootResolution.source} fallback_used=false`)
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
    storageMode: config.storageMode,
    pythonPath: config.backendPythonPath,
    rendererOrigin: config.rendererOrigin,
    startupTimeoutMs: config.startupTimeoutMs,
    logger,
    onStartupMilestone: (event) => startupTimeline?.mark(event),
  })
  const developmentMenu = isDevelopmentMenuEnabled(config.devServerUrl)
  if (!developmentMenu) Menu.setApplicationMenu(null)
  rendererDevelopment = Boolean(config.devServerUrl)
  logDevelopmentGpuFeatureStatus(
    rendererDevelopment,
    () => app.getGPUFeatureStatus() as unknown as Record<string, string>,
    logger,
  )
  uiPreferenceStore = new UiPreferenceStore(app.getPath('userData'))
  const storedCloseToTray = await uiPreferenceStore.get('desktop.close-to-tray')
  closeToTrayEnabled = typeof storedCloseToTray === 'boolean' ? storedCloseToTray : true
  workspaceLayoutStore = new WorkspaceLayoutStore(app.getPath('userData'), (event) => logger(event))
  const externalToolStore = new ExternalToolStore(app.getPath('userData'), logger)
  const externalToolService = new ExternalToolService({
    store: externalToolStore,
    spawn: (executable, arguments_, options) => spawn(executable, [...arguments_], options),
    reveal: (path) => shell.showItemInFolder(path),
    getExecutableIcon: async (path) => (await app.getFileIcon(path, { size: 'large' })).toDataURL(),
    getCustomIcon: async (path) => {
      const image = nativeImage.createFromPath(path)
      return image.isEmpty() ? null : image.toDataURL()
    },
    logger,
  })
  workspaceWindowController = new WorkspaceWindowController(workspaceLayoutStore, {
    createWindow: (role, bounds) => {
      const window = createMainWindow(
        rendererDevelopment,
        role === 'main' ? developmentMenu : false,
        NETCONSOLE_WINDOW_TITLE,
        bounds,
      )
      if (role === 'main') {
        mainWindow = window
        window.on('closed', () => {
          if (mainWindow === window) mainWindow = undefined
        })
      }
      installManagedWindowDiagnostics(window, role === 'main')
      return window
    },
    buildTarget: buildWorkspaceRendererTarget,
    prepareNavigation: (window, target) => {
      const browserWindow = window as BrowserWindow
      rememberManagedRendererTarget(browserWindow, target)
      armRendererThemeDisplay(browserWindow)
    },
    loadLoadingPage: (window) => loadStatusPage(
      window as BrowserWindow,
      '正在加载 NetConsole…',
      '正在加载工作区和页面状态。',
    ),
    loadFailurePage: (window, title, detail) => loadStatusPage(
      window as BrowserWindow,
      title,
      detail,
      true,
    ),
    getWorkAreas: () => screen.getAllDisplays().map((display) => ({ ...display.workArea })),
    shouldHideMainToTray: () => trayAvailable && closeToTrayEnabled,
    isExplicitQuit: () => explicitQuitRequested || allowQuit,
    onMainHidden: () => trayController?.displayBackgroundHint(),
    onVisibleWindowCountChanged: handleVisibleBusinessWindowCount,
    logger: (event) => logger(event),
    timeoutMs: RENDERER_THEME_READY_TIMEOUT_MS,
  })
  mainWindow = workspaceWindowController.ensureMainWindow(false) as BrowserWindow
  startupTimeline.mark('electron.window_created')
  taskNotificationController = new TaskNotificationController({
    createNotification: (payload) => {
      if (!ElectronNotification.isSupported()) throw new Error('native notification unsupported')
      return new ElectronNotification({
        title: payload.title,
        body: payload.body,
        silent: payload.kind === 'success',
      })
    },
    activateTask: async (taskId) => {
      await openTaskWindow({ taskId })
    },
    isApplicationFocused: () => getAllDesktopWindows().some(
      (window) => !window.isDestroyed() && window.isFocused(),
    ),
    logger: (event) => logger(event),
  })
  trayController = new TrayController({
    createTray: () => {
      const iconPath = resolveTrayIconPath({
        isPackaged: app.isPackaged,
        appPath: app.getAppPath(),
        resourcesPath: process.resourcesPath,
      })
      if (!existsSync(iconPath)) {
        logger('ELECTRON_TRAY_ICON_FAILED')
        throw new Error('tray icon is unavailable')
      }
      return new Tray(iconPath)
    },
    buildMenu: (template: TrayMenuItem[]) => Menu.buildFromTemplate(
      template as Parameters<typeof Menu.buildFromTemplate>[0],
    ),
    showMainWindow: () => workspaceWindowController?.showMainWindow(),
    showTaskCenter: async () => { await openTaskWindow({}) },
    createWorkspaceWindow: async () => {
      await openWorkspaceWindow({ routeFullPath: '/', title: 'Dashboard' })
    },
    requestSiteSwitch: requestTraySiteSwitch,
    setCloseToTrayEnabled: async (enabled) => {
      await updateCloseToTrayEnabled(enabled)
    },
    explicitQuit: requestExplicitQuit,
    logger: (event) => logger(event),
  })
  trayAvailable = trayController.initialize()
  trayController.updateContext({
    backendState: 'starting',
    activeSiteId: desktopActiveSiteId,
    activeSiteName: desktopActiveSiteName,
    sites: desktopSites,
    closeToTrayEnabled,
    visibleWindowCount: 1,
  })
  desktopIpc = registerDesktopIpc({
    ipcMain,
    dialog,
    shell,
    window: mainWindow,
    windowForEvent: (event) => BrowserWindow.fromWebContents(event.sender as Electron.WebContents)
      ?? workspaceWindowController?.getMainWindow()
      ?? mainWindow,
    openTaskWindow,
    showTaskNotification: (payload) => (
      taskNotificationController?.show(payload) ?? { success: false, error: '系统通知不可用' }
    ),
    setTaskTrayStatus: (status) => trayController?.updateContext({
      activeTaskCount: status.active,
      failedTaskCount: status.failed,
      warningTaskCount: status.warning,
    }),
    openWorkspaceWindow,
    getWorkspaceWindowState: (window) => getWorkspaceWindowState(window),
    saveWorkspaceWindowState: (window, snapshot) => saveWorkspaceWindowState(window, snapshot),
    setWorkspaceWindowTitle: (window, title) => workspaceWindowController?.setWindowTitle(window, title),
    getCloseToTrayState,
    setCloseToTrayEnabled: updateCloseToTrayEnabled,
    restartBackend: restartManagedBackend,
    refreshSiteContext: async () => { await refreshTraySiteContext() },
    setSiteSwitching: (switching) => trayController?.updateContext({ siteSwitching: switching }),
    appInfo: {
      version: app.getVersion(),
      platform: process.platform,
      isPackaged: app.isPackaged,
    },
    backend,
    pathRegistry,
    isTrustedSender: (event) => getAllDesktopWindows().some((window) => (
      isTrustedRendererSender(event, window, [...rendererOrigins])
    )),
    onRendererReady: handleRendererReady,
    onRendererWorkload: handleRendererWorkload,
    getRendererRecoveryState,
    logger,
    uiPreferenceStore,
    externalToolService,
  })
  backend.onStatusChange((status) => {
    logger('ELECTRON_BACKEND_STATUS', `state=${status.state}`)
    const publicStatus = {
      state: status.state,
      ...(status.baseUrl ? { baseUrl: status.baseUrl } : {}),
      ...(status.error ? { error: '本地后端不可用' } : {}),
    }
    trayController?.updateContext({ backendState: status.state })
    for (const window of getAllDesktopWindows()) {
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
    await refreshTraySiteContext(runtime, desktopActiveSiteId)
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
    if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') {
      await runManagedBackendWorkerTextSmoke(runtime)
    }
    if (desktopStorageContext.persistent && desktopActiveSiteId) {
      bootstrapStore.save({ schema_version: 1, data_root: desktopDataRoot, active_site_id: desktopActiveSiteId })
    }
    trayController?.updateContext({
      activeSiteId: desktopActiveSiteId,
      activeSiteName: desktopActiveSiteName,
      sites: desktopSites,
      siteSwitching: false,
    })
    const restoredMainState = workspaceWindowController.getWindowState(mainWindow)
    const restoredMainRoute = restoredMainState.snapshot?.tabs.find(
      (tab) => tab.id === restoredMainState.snapshot?.activeTabId,
    )?.routeFullPath || '/'
    const mainRendererTarget = buildWorkspaceRendererTarget(
      restoredMainRoute,
      restoredMainState.windowId,
      'main',
    )
    rememberManagedRendererTarget(mainWindow, mainRendererTarget)
    startSmokeWatchdog()
    startupTimeline.mark('renderer.navigation_started')
    const rendererWindow = mainWindow
    rendererWindow.webContents.once('dom-ready', () => startupTimeline?.mark('renderer.dom_ready'))
    armRendererThemeDisplay(rendererWindow)
    void rendererWindow.loadURL(mainRendererTarget).then(
      () => workspaceWindowController?.restoreAdditionalWindows(),
    ).catch((cause) => {
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

function createMainWindow(
  development: boolean,
  developmentMenu = false,
  title = NETCONSOLE_WINDOW_TITLE,
  bounds: WorkspaceWindowBounds = { x: 80, y: 80, width: 1_360, height: 860 },
): BrowserWindow {
  const window = new BrowserWindow({
    title,
    icon: resolveDesktopIconPath({
      isPackaged: app.isPackaged,
      appPath: app.getAppPath(),
      resourcesPath: process.resourcesPath,
    }),
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
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
  window.on('page-title-updated', (event) => {
    event.preventDefault()
    window.setTitle(title)
  })
  window.setTitle(title)
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
    () => retryManagedRenderer(window, 'safe'),
    openElectronLogs,
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
  const webContentsId = window.webContents.id
  window.once('closed', () => {
    displayGate.dispose()
    latestRendererWorkloads.delete(webContentsId)
    rendererProcessFailures.delete(webContentsId)
    rendererRecoveries.delete(webContentsId)
  })
  return window
}

async function restartManagedBackend(update: SiteStorageRestartRequest): Promise<void> {
  const cookieWindow = getAllDesktopWindows()[0]
  if (!backend || !cookieWindow || !bootstrapStore) throw new Error('desktop runtime is unavailable')
  if (!desktopStorageContext.persistent) throw new Error('隔离测试模式不允许修改正式局点或数据根')
  const previousRoot = desktopDataRoot
  const previousSite = desktopActiveSiteId
  const nextRoot = update.dataRoot ?? previousRoot
  const nextSite = update.activeSiteId ?? previousSite
  logger('SITE_SWITCH_STARTED', `site_changed=${nextSite !== previousSite} data_root_changed=${nextRoot !== previousRoot}`)
  await backend.stop()
  let workspaceCheckpoint: Map<string, WorkspaceWindowSnapshot | null> | undefined
  try {
    workspaceCheckpoint = workspaceWindowController?.prepareSiteSwitchSnapshots()
    backend.configureStorage(nextRoot, nextSite)
    const runtime = await backend.start()
    await applyManagedBackendRuntime(runtime, nextRoot, nextSite)
    const verified = await refreshTraySiteContext(runtime, '')
    if (!verified || verified.activeSiteId !== nextSite) {
      throw new Error('Backend ready 后返回的当前局点与目标局点不一致')
    }
    if (nextSite !== previousSite) {
      rendererRecoveries.clear()
      latestRendererWorkloads.clear()
    }
    logger('SITE_SWITCH_BACKEND_RESTARTED', `site_changed=${nextSite !== previousSite} data_root_changed=${nextRoot !== previousRoot}`)
    setImmediate(() => { void reloadManagedRenderersAfterBackendRestart() })
  } catch (cause) {
    try {
      await backend.stop()
      backend.configureStorage(previousRoot, previousSite)
      const restoredRuntime = await backend.start()
      await applyManagedBackendRuntime(restoredRuntime, previousRoot, previousSite)
      await refreshTraySiteContext(restoredRuntime, previousSite)
    } catch (restoreCause) {
      if (workspaceCheckpoint) workspaceWindowController?.restoreSiteSwitchSnapshots(workspaceCheckpoint)
      logger('SITE_SWITCH_FAILED', `stage=backend_restore restored=false type=${restoreCause instanceof Error ? restoreCause.name : 'unknown'}`)
      throw new Error('Backend 重启失败，原局点恢复失败，请重新启动应用。')
    }
    if (workspaceCheckpoint) workspaceWindowController?.restoreSiteSwitchSnapshots(workspaceCheckpoint)
    logger('SITE_SWITCH_FAILED', `stage=backend_start restored=true type=${cause instanceof Error ? cause.name : 'unknown'}`)
    throw new Error('Backend 重启失败，已恢复原局点。')
  }
}

async function applyManagedBackendRuntime(runtime: BackendRuntimeInfo, dataRoot: string, activeSiteId: string): Promise<void> {
  const cookieWindow = getAllDesktopWindows()[0]
  if (!cookieWindow || !bootstrapStore) throw new Error('desktop runtime is unavailable')
  desktopDataRoot = dataRoot
  desktopActiveSiteId = activeSiteId
  bootstrapStore.save({ schema_version: 1, data_root: dataRoot, active_site_id: activeSiteId })
  const backendOrigin = new URL(runtime.baseUrl).origin
  connectionOrigins.add(backendOrigin)
  const cookiePath = desktopSessionCookiePath(rendererDevelopment)
  await cookieWindow.webContents.session.cookies.set({
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
}

async function reloadManagedRenderersAfterBackendRestart(): Promise<void> {
  let reloaded = 0
  for (const window of getAllDesktopWindows()) {
    if (window.isDestroyed()) continue
    const previousTarget = windowRendererTargets.get(window)
    if (!previousTarget) continue
    try {
      const previousUrl = new URL(previousTarget)
      const nextTarget = new URL(`${previousUrl.pathname}${previousUrl.search}`, rendererUrl).toString()
      rememberManagedRendererTarget(window, nextTarget)
      armRendererThemeDisplay(window)
      await window.loadURL(nextTarget)
      reloaded += 1
    } catch (cause) {
      logger('SITE_SWITCH_FAILED', `stage=renderer_reload type=${cause instanceof Error ? cause.name : 'unknown'}`)
    }
  }
  logger('SITE_SWITCH_COMPLETED', `renderer_reloaded=${reloaded}`)
}

interface DesktopSiteContext {
  activeSiteId: string
  activeSiteName: string
  sites: TraySiteSummary[]
}

async function requestTraySiteSwitch(siteId: string): Promise<void> {
  if (!mainWindow || mainWindow.isDestroyed() || !trayController) return
  trayController.updateContext({ siteSwitching: true })
  try {
    await workspaceWindowController?.showMainWindow()
    mainWindow.webContents.send(DESKTOP_IPC.traySiteSwitchRequested, siteId)
  } catch {
    trayController.updateContext({ siteSwitching: false })
    logger('ELECTRON_TRAY_SITE_SWITCH_REQUEST_FAILED')
  }
}

async function refreshTraySiteContext(
  runtime?: BackendRuntimeInfo,
  fallbackSiteId = desktopActiveSiteId,
): Promise<DesktopSiteContext | null> {
  const currentRuntime = runtime ?? backend?.getRuntimeInfo()
  if (!currentRuntime) return null
  try {
    const context = await readBackendSiteContext(
      currentRuntime.baseUrl,
      currentRuntime.apiToken,
    )
    if (!context) return null
    desktopActiveSiteId = context.activeSiteId || fallbackSiteId
    desktopActiveSiteName = context.activeSiteName
    desktopSites = context.sites
    trayController?.updateContext({
      activeSiteId: desktopActiveSiteId,
      activeSiteName: desktopActiveSiteName,
      sites: desktopSites,
      siteSwitching: false,
    })
    return context
  } catch {
    logger('ELECTRON_TRAY_SITE_CONTEXT_REFRESH_FAILED')
    return null
  }
}

async function readBackendSiteContext(
  baseUrl: string,
  apiToken: string,
): Promise<DesktopSiteContext | null> {
  const headers = { [DESKTOP_SESSION_HEADER]: apiToken }
  const [activeResponse, sitesResponse] = await Promise.all([
    fetch(`${baseUrl}/api/v1/sites/active`, { cache: 'no-store', headers }),
    fetch(`${baseUrl}/api/v1/sites`, { cache: 'no-store', headers }),
  ])
  if (!activeResponse.ok || !sitesResponse.ok) return null
  const active = toTraySiteSummary(await activeResponse.json())
  const payload = await sitesResponse.json()
  if (!active || !Array.isArray(payload)) return null
  const sites = payload.flatMap((item) => {
    const site = toTraySiteSummary(item)
    return site ? [site] : []
  })
  const selected = sites.find((site) => site.siteId === active.siteId) ?? active
  return {
    activeSiteId: selected.siteId,
    activeSiteName: selected.displayName,
    sites,
  }
}

function toTraySiteSummary(value: unknown): TraySiteSummary | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const siteId = typeof record.site_id === 'string' ? record.site_id.trim() : ''
  const displayName = typeof record.display_name === 'string' ? record.display_name : ''
  if (!/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(siteId) || !displayName.trim()) {
    return null
  }
  return {
    siteId,
    displayName,
    active: record.active === true,
    selectable: record.active !== true,
  }
}

async function runManagedBackendWorkerTextSmoke(runtime: BackendRuntimeInfo): Promise<void> {
  const headers = {
    [DESKTOP_SESSION_HEADER]: runtime.apiToken,
    'content-type': 'application/json',
  }
  const startedResponse = await fetch(`${runtime.baseUrl}/api/system-maintenance/open-source/tasks`, {
    method: 'POST',
    cache: 'no-store',
    headers,
    body: '{}',
  })
  if (!startedResponse.ok) throw new Error(`冻结 Worker 中文任务提交失败：HTTP ${startedResponse.status}`)
  const started = await startedResponse.json() as { task_id?: unknown }
  const taskId = typeof started.task_id === 'string' ? started.task_id : ''
  if (!taskId) throw new Error('冻结 Worker 中文任务没有返回 task_id')

  let detail: Record<string, unknown> | undefined
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await fetch(`${runtime.baseUrl}/api/job-center/tasks/${encodeURIComponent(taskId)}`, {
      cache: 'no-store',
      headers,
    })
    if (!response.ok) throw new Error(`冻结 Worker 中文任务读取失败：HTTP ${response.status}`)
    detail = await response.json() as Record<string, unknown>
    if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(String(detail.status ?? ''))) break
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
  }
  if (!detail || detail.status !== 'COMPLETED' || detail.text_integrity !== 'ok') {
    throw new Error('冻结 Worker 中文任务未以 text_integrity=ok 完成')
  }
  const logsResponse = await fetch(
    `${runtime.baseUrl}/api/job-center/tasks/${encodeURIComponent(taskId)}/logs?tail=300`,
    { cache: 'no-store', headers },
  )
  if (!logsResponse.ok) throw new Error(`冻结 Worker 中文日志读取失败：HTTP ${logsResponse.status}`)
  const logs = await logsResponse.json() as { lines?: Array<{ message?: unknown }> }
  const messages = (logs.lines ?? []).map((line) => String(line.message ?? ''))
  if (
    JSON.stringify({ detail, logs }).includes('\uFFFD')
    || !messages.includes('正在扫描运行依赖')
    || !messages.includes('后台任务完成')
  ) {
    throw new Error('Electron 受管 Backend 的冻结 Worker 中文事件不完整或包含替换字符')
  }
  logger('ELECTRON_FROZEN_WORKER_TEXT_SMOKE_PASSED')
}

function installManagedWindowDiagnostics(window: BrowserWindow, smoke = false): void {
  installRendererDiagnostics(window, {
    logger,
    canRetry: () => Boolean(windowRendererTargets.get(window)),
    surface: window === mainWindow ? 'main' : 'workspace-window',
    getLatestWorkload: () => latestRendererWorkloads.get(window.webContents.id),
    hasRecentGpuFailure: () => (
      recentGpuProcessFailureAt > 0
      && Date.now() - recentGpuProcessFailureAt <= RECENT_GPU_FAILURE_WINDOW_MS
    ),
    onProcessGone: (failure) => rendererProcessFailures.set(window.webContents.id, failure),
    ...(smoke ? { onLoadStarted: handleRendererLoadStarted, onLoadStopped: handleRendererLoadStopped } : {}),
    showError: (title, detail, retryable, actions) => (
      showManagedWindowError(window, title, detail, retryable, actions)
    ),
  })
}

async function openTaskWindow(context: TaskWindowContext): Promise<NativeActionResult> {
  if (!rendererUrl || !workspaceWindowController || explicitQuitRequested) {
    return { success: false, error: '任务中心尚未就绪' }
  }
  await restoreApplicationWindow()
  const target = workspaceWindowController.getMainWindow() as BrowserWindow | undefined
  if (!target || target.isDestroyed()) return { success: false, error: '任务中心尚未就绪' }
  target.webContents.send(DESKTOP_IPC.taskCenterOpenRequested, context)
  logger('ELECTRON_TASK_CENTER_DRAWER_REQUESTED')
  return { success: true }
}

async function openWorkspaceWindow(request: WorkspaceWindowOpenRequest): Promise<NativeActionResult> {
  if (!rendererUrl || !workspaceWindowController || explicitQuitRequested) {
    return { success: false, error: '工作区窗口尚未就绪' }
  }
  return workspaceWindowController.open(request)
}

function getWorkspaceWindowState(window: unknown): WorkspaceWindowStateResult {
  if (!workspaceWindowController) throw new Error('工作区窗口尚未就绪')
  return workspaceWindowController.getWindowState(window)
}

function saveWorkspaceWindowState(window: unknown, snapshot: WorkspaceWindowSnapshot): void {
  if (!workspaceWindowController) throw new Error('工作区窗口尚未就绪')
  workspaceWindowController.saveWindowState(window, snapshot)
}

function buildWorkspaceRendererTarget(
  routeFullPath: string,
  windowId: string,
  role: 'main' | 'workspace',
): string {
  if (!rendererUrl) throw new Error('工作区窗口尚未就绪')
  const target = new URL(routeFullPath, rendererUrl)
  target.searchParams.set('netconsole_host', 'electron')
  if (role === 'workspace') target.searchParams.set('workspace_window', '1')
  target.searchParams.set('workspace_window_id', windowId)
  return target.toString()
}

async function loadStatusPage(
  window: BrowserWindow,
  title: string,
  detail: string,
  retryable = false,
  openMainTasks = false,
  failureActions?: RendererFailureActions,
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
  const safeRecovery = failureActions?.safeRecovery
    ? `<a href="${MANAGED_RENDERER_SAFE_RECOVERY_ACTION}">安全恢复</a>`
    : ''
  const retry = retryable || failureActions?.directRetry
    ? `<a${safeRecovery ? ' class="secondary"' : ''} href="${MANAGED_RENDERER_RETRY_ACTION}">${safeRecovery ? '直接重试' : '重试'}</a>`
    : ''
  const openLogs = failureActions?.openLogs
    ? `<a class="secondary" href="${MANAGED_RENDERER_OPEN_LOGS_ACTION}">打开日志目录</a>`
    : ''
  const mainTasks = openMainTasks
    ? `<a class="secondary" href="${MANAGED_RENDERER_OPEN_MAIN_TASKS_ACTION}">在主窗口打开任务中心</a>`
    : ''
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>${escapeHtml(title)}</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:${statusBackground};color:${statusText};font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(620px,calc(100vw - 48px));padding:36px;border:1px solid ${statusBorder};border-radius:14px;background:${statusPanel};text-align:center;box-shadow:${statusShadow}}h1{font-size:22px;margin:0 0 12px}p{color:${statusMuted};line-height:1.7;margin:0 0 18px;white-space:pre-line}.actions{display:flex;justify-content:center;gap:10px;flex-wrap:wrap}a{display:inline-block;padding:8px 18px;border-radius:8px;background:#0078d4;color:#fff;text-decoration:none}.secondary{background:transparent;color:${statusText};border:1px solid ${statusBorder}}</style></head><body><main><h1>${escapeHtml(title)}</h1><p>${escapeHtml(detail)}</p><div class="actions">${safeRecovery}${retry}${openLogs}${mainTasks}</div></main></body></html>`
  const statusPageUrl = `data:text/html;charset=utf-8,${encodeURIComponent(html)}`
  await window.loadURL(statusPageUrl)
  if ((retryable || openMainTasks || failureActions) && !window.isDestroyed()) {
    retryNavigation?.armForStatusPage(statusPageUrl)
  }
}

function handleRendererReady(report: RendererHostReport, sourceWindow: unknown): void {
  const window = resolveManagedDesktopWindow(sourceWindow)
  workspaceWindowController?.acceptRendererReport(report, window)
  if ('resolvedTheme' in report) {
    if (window) windowDisplayGates.get(window)?.acceptResolvedTheme()
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
  if (process.env.NETCONSOLE_ELECTRON_TASK_CENTER_SMOKE === '1') {
    if (smokeStableTimer) {
      clearTimeout(smokeStableTimer)
      smokeStableTimer = undefined
    }
    if (!taskCenterSmokeStarted) {
      taskCenterSmokeStarted = true
      void runTaskCenterSmoke()
    }
    return
  }
  if (process.env.NETCONSOLE_ELECTRON_WORKSPACE_TRAY_SMOKE === '1') {
    if (!workspaceTraySmokeStarted) {
      workspaceTraySmokeStarted = true
      void runWorkspaceTraySmoke()
    }
    return
  }
  scheduleSmokeStableExit()
}

function handleRendererWorkload(report: RendererWorkloadReport, sourceWindow: unknown): void {
  const window = resolveManagedDesktopWindow(sourceWindow)
  if (!window || window.isDestroyed()) return
  const webContentsId = window.webContents.id
  latestRendererWorkloads.set(webContentsId, report)
  logger(
    'ELECTRON_RENDERER_WORKLOAD',
    [
      `web_contents_id=${webContentsId}`,
      `surface=${window === mainWindow ? 'main' : 'workspace-window'}`,
      `module=${report.module}`,
      `phase=${report.phase}`,
      `session_id=${report.sessionId ?? 'none'}`,
      `source_file_id=${report.sourceFileId ?? 'none'}`,
      `radio=${report.radio ?? 'none'}`,
      `series_count=${report.seriesCount ?? 'none'}`,
      `point_count=${report.pointCount ?? 'none'}`,
      `metadata_count=${report.metadataCount ?? 'none'}`,
      `conflict_edge_count=${report.conflictEdgeCount ?? 'none'}`,
      `mesh_instances=${report.meshInstanceCount ?? 'none'}`,
      `trackside_caches=${report.tracksideCacheCount ?? 'none'}`,
      `trackside_charts=${report.tracksideChartCount ?? 'none'}`,
      `active_detail_requests=${report.activeDetailRequests ?? 'none'}`,
      `returned_link_points=${report.returnedLinkPoints ?? 'none'}`,
      `returned_frames=${report.returnedFrames ?? 'none'}`,
      `report_revision=${report.reportRevision}`,
    ].join(' '),
  )
  const rendererPid = window.webContents.getOSProcessId()
  const memory = app.getAppMetrics().find((metric) => metric.pid === rendererPid)?.memory
  const meshWindowReports = getAllDesktopWindows()
    .map((candidate) => latestRendererWorkloads.get(candidate.webContents.id))
    .filter((candidate): candidate is RendererWorkloadReport => candidate?.module === 'mesh-analysis')
  const sum = (field: keyof RendererWorkloadReport): number => meshWindowReports.reduce((total, item) => {
    const value = item[field]
    return total + (typeof value === 'number' ? value : 0)
  }, 0)
  logger(
    'MESH_MEMORY_PROFILE',
    [
      `web_contents_id=${webContentsId}`,
      `session_id=${report.sessionId ?? 'none'}`,
      `mesh_tabs=${sum('meshInstanceCount')}`,
      `mesh_windows=${meshWindowReports.length}`,
      `rendered_trackside_charts=${sum('tracksideChartCount')}`,
      `trackside_caches=${sum('tracksideCacheCount')}`,
      `series=${report.seriesCount ?? 0}`,
      `points=${report.pointCount ?? 0}`,
      `metadata=${report.metadataCount ?? 0}`,
      `conflict_edges=${report.conflictEdgeCount ?? 0}`,
      `echarts_instances=${report.echartsInstanceCount ?? 0}`,
      `canvas=${report.canvasCount ?? 0}`,
      `active_session_api=${sum('activeDetailRequests')}`,
      `cache_builds=${report.tracksideCacheBuildCount ?? 0}`,
      `cache_disposes=${report.tracksideCacheDisposeCount ?? 0}`,
      `echarts_inits=${report.chartInitCount ?? 0}`,
      `echarts_disposes=${report.chartDisposeCount ?? 0}`,
      `heap_used_mb=${report.heapUsedBytes == null ? 'unavailable' : (report.heapUsedBytes / 1024 / 1024).toFixed(1)}`,
      'array_buffer_mb=unavailable',
      `private_memory_mb=${memory?.privateBytes == null ? 'unavailable' : (memory.privateBytes / 1024).toFixed(1)}`,
      `resident_set_mb=${memory == null ? 'unavailable' : (memory.workingSetSize / 1024).toFixed(1)}`,
    ].join(' '),
  )
  const recovery = rendererRecoveries.get(webContentsId)
  if (report.phase !== 'echarts-interactive' || !recovery) return
  rendererRecoveries.delete(webContentsId)
  rendererProcessFailures.delete(webContentsId)
  logger(
    'ELECTRON_RENDERER_RECOVERED',
    [
      `previous_reason=${recovery.previousReason}`,
      `module=${recovery.module}`,
      `session_id=${recovery.sessionId ?? 'none'}`,
      `recovery_mode=${recovery.mode}`,
    ].join(' '),
  )
}

function getRendererRecoveryState(sourceWindow: unknown): RendererRecoveryState | null {
  const window = resolveManagedDesktopWindow(sourceWindow)
  if (!window || window.isDestroyed()) return null
  return rendererRecoveries.get(window.webContents.id) ?? null
}

async function runTaskCenterSmoke(): Promise<void> {
  try {
    const result = await openTaskWindow({ module: 'rail' })
    logger(result.success ? 'ELECTRON_TASK_CENTER_SMOKE_PASSED' : 'ELECTRON_TASK_CENTER_SMOKE_FAILED')
    requestExit(result.success ? 0 : 2)
  } catch {
    logger('ELECTRON_TASK_CENTER_SMOKE_FAILED')
    requestExit(2)
  }
}

async function runWorkspaceTraySmoke(): Promise<void> {
  try {
    const created = await openWorkspaceWindow({ routeFullPath: '/', title: 'Dashboard' })
    if (!created.success) throw new Error('workspace window create failed')
    const additional = workspaceWindowController?.getAllManagedWindows()
      .find((window) => window !== mainWindow) as BrowserWindow | undefined
    if (!additional || additional.isDestroyed()) throw new Error('workspace window missing')
    additional.close()
    if (!mainWindow || mainWindow.isDestroyed() || !trayAvailable) {
      throw new Error('tray runtime unavailable')
    }
    mainWindow.close()
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 150))
    if (mainWindow.isVisible() || backend?.getStatus().state !== 'ready') {
      throw new Error('close-to-tray did not preserve backend')
    }
    await workspaceWindowController?.showMainWindow()
    if (!mainWindow.isVisible()) throw new Error('main window restore failed')
    logger('ELECTRON_WORKSPACE_TRAY_SMOKE_PASSED')
    requestExplicitQuit()
  } catch {
    logger('ELECTRON_WORKSPACE_TRAY_SMOKE_FAILED')
    requestExit(2)
  }
}

function scheduleSmokeStableExit(): void {
  if (
    process.env.NETCONSOLE_ELECTRON_TASK_CENTER_SMOKE === '1'
    || process.env.NETCONSOLE_ELECTRON_WORKSPACE_TRAY_SMOKE === '1'
  ) return
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
  taskCenterSmokeStarted = false
  workspaceTraySmokeStarted = false
  logger('ELECTRON_SMOKE_WATCHDOG_STARTED')
  smokeWatchdogTimer = setTimeout(() => {
    logger('ELECTRON_SMOKE_WATCHDOG_EXPIRED')
    requestExit(2)
  }, 30_000)
}

function getAllDesktopWindows(): BrowserWindow[] {
  const windows = [
    ...(workspaceWindowController?.getAllManagedWindows() ?? []),
  ] as BrowserWindow[]
  return [...new Set(windows)]
}

function resolveManagedDesktopWindow(value: unknown): BrowserWindow | undefined {
  return getAllDesktopWindows().find((window) => window === value)
}

function handleVisibleBusinessWindowCount(count: number): void {
  trayController?.updateContext({ visibleWindowCount: count })
  if (count === 0 && (!trayAvailable || !closeToTrayEnabled) && !explicitQuitRequested) {
    requestExit(0)
  }
}

function getCloseToTrayState(): CloseToTrayState {
  return { enabled: closeToTrayEnabled, available: trayAvailable }
}

async function updateCloseToTrayEnabled(enabled: boolean): Promise<CloseToTrayState> {
  closeToTrayEnabled = enabled
  await uiPreferenceStore?.set('desktop.close-to-tray', enabled)
  const state = getCloseToTrayState()
  trayController?.updateContext({ closeToTrayEnabled: enabled })
  for (const window of getAllDesktopWindows()) {
    if (!window.isDestroyed()) window.webContents.send(DESKTOP_IPC.closeToTrayChanged, state)
  }
  if (!enabled && (workspaceWindowController?.countVisibleBusinessWindows() ?? 0) === 0) {
    requestExit(0)
  }
  return state
}

async function restoreApplicationWindow(): Promise<void> {
  try {
    await workspaceWindowController?.showMainWindow()
  } catch {
    const fallback = workspaceWindowController?.getMostRecentlyFocusedWindow() as BrowserWindow | undefined
    if (!fallback || fallback.isDestroyed()) return
    if (fallback.isMinimized()) fallback.restore()
    if (!fallback.isVisible()) fallback.show()
    fallback.focus()
  }
}

function requestExplicitQuit(): void {
  if (explicitQuitRequested) return
  explicitQuitRequested = true
  logger('ELECTRON_TRAY_EXPLICIT_QUIT')
  requestExit(0)
}

function requestExit(code: number): void {
  requestedExitCode = Math.max(requestedExitCode, code)
  beginShutdownAndExit()
}

function beginShutdownAndExit(): void {
  if (shutdownPromise) return
  allowQuit = true
  workspaceWindowController?.flush()
  workspaceWindowController?.closeAllForQuit()
  trayController?.dispose()
  shutdownPromise = shutdown().finally(() => {
    traceSmoke('EXIT_REQUESTED')
    app.releaseSingleInstanceLock()
    app.exit(requestedExitCode)
    traceSmoke('EXIT_RETURNED')
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
    taskNotificationController = undefined
    workspaceWindowController?.flush()
  } catch {
    requestedExitCode = Math.max(requestedExitCode, 1)
  }
  try {
    await desktopIpc?.shutdown()
    logger('ELECTRON_DOWNLOADS_STOPPED')
    traceSmoke('DOWNLOADS_STOPPED')
  } catch {
    requestedExitCode = Math.max(requestedExitCode, 1)
  }
  try {
    await backend?.stop()
    logger('ELECTRON_SHUTDOWN_COMPLETE')
    traceSmoke('BACKEND_STOPPED')
  } catch {
    // BackendManager has already moved to the failed state and logged the reason.
    requestedExitCode = Math.max(requestedExitCode, 1)
  } finally {
    workspaceWindowController?.dispose()
    workspaceWindowController = undefined
    trayController = undefined
    pathRegistry.clear()
  }
}

function traceSmoke(event: string): void {
  if (process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1') {
    process.stderr.write(`[netconsole-smoke] ${event}\n`)
  }
}

function assertElectronStoragePaths(): void {
  const expected: Array<[string, string]> = [
    ['userData', desktopStorageContext.userDataRoot],
    ['sessionData', desktopStorageContext.sessionDataRoot],
    ['cache', desktopStorageContext.cacheRoot],
    ['logs', desktopStorageContext.logsRoot],
    ['crashDumps', desktopStorageContext.crashDumpsRoot],
    ['temp', desktopStorageContext.tempRoot],
  ]
  const pathProvider = app as unknown as { getPath: (name: string) => string }
  for (const [name, target] of expected) {
    if (resolve(pathProvider.getPath(name)) !== resolve(target)) {
      throw new Error(`Electron ${name} 路径未重定向到统一数据根。`)
    }
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

async function retryManagedRenderer(
  window: BrowserWindow,
  recoveryMode: RendererRecoveryState['mode'] = 'normal',
): Promise<void> {
  const failure = rendererProcessFailures.get(window.webContents.id)
  const workload = failure?.workload
  let target = windowRendererTargets.get(window)
  if (workload?.module === 'mesh-analysis' && failure?.actions.safeRecovery) {
    rendererRecoveries.set(window.webContents.id, {
      mode: recoveryMode,
      previousReason: failure.reason,
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      ...(workload.sessionId ? { sessionId: workload.sessionId } : {}),
      ...(workload.sourceFileId == null ? {} : { sourceFileId: workload.sourceFileId }),
      ...(workload.radio === undefined ? {} : { radio: workload.radio }),
    })
    target = new URL('/rail-transit/mesh-analysis', rendererUrl).toString()
    rememberManagedRendererTarget(window, target)
    logger(
      'ELECTRON_RENDERER_RECOVERY_STARTED',
      `mode=${recoveryMode} reason=${failure.reason} module=mesh-analysis session_id=${workload.sessionId ?? 'none'}`,
    )
  }
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

async function openElectronLogs(): Promise<void> {
  const result = await shell.openPath(app.getPath('logs'))
  logger(result ? 'ELECTRON_RENDERER_LOGS_OPEN_FAILED' : 'ELECTRON_RENDERER_LOGS_OPENED')
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
  failureActions?: RendererFailureActions,
): Promise<void> {
  const coordinator = windowErrorCoordinators.get(window)
  const show = async () => {
    const render = () => loadStatusPage(window, title, detail, retryable, false, failureActions)
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
  const diagnostic = buildChildProcessGoneDiagnostic(details)
  if (diagnostic.event === 'ELECTRON_GPU_PROCESS_GONE') recentGpuProcessFailureAt = Date.now()
  logger(diagnostic.event, diagnostic.detail)
})
