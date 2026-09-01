import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'main', 'index.ts'),
  'utf8',
)
const brandingSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'main', 'branding.ts'),
  'utf8',
)
const displayGateSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'main', 'renderer-theme-display-gate.ts'),
  'utf8',
)
const devSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'dev.mjs'),
  'utf8',
)

describe('Electron shell product contract', () => {
  it('uses the branded product title, icon, and hides the default menu unless development opts in', () => {
    expect(brandingSource).toContain("NETCONSOLE_WINDOW_TITLE = 'NetConsole'")
    expect(brandingSource).not.toContain('NETCONSOLE_TASK_WINDOW_TITLE')
    expect(brandingSource).toContain("resolve(context.resourcesPath, 'branding', 'netconsole.ico')")
    expect(brandingSource).toContain("resolve(context.appPath, '..', '..', 'resources', 'branding', 'netconsole.ico')")
    expect(source).toContain('title = NETCONSOLE_WINDOW_TITLE')
    expect(source).toContain('title,')
    expect(source).toContain('icon: resolveDesktopIconPath')
    expect(source).toContain("window.on('page-title-updated'")
    expect(source).toContain('event.preventDefault()')
    expect(source).toContain('setManagedWindowTitle(window, title)')
    expect(source).not.toContain('NETCONSOLE_TASK_WINDOW_TITLE')
    expect(source).not.toContain("title: 'NetConsole'")
    expect(source).not.toContain("window.setTitle('NetConsole 任务中心')")
    expect(source).toContain('autoHideMenuBar: !developmentMenu')
    expect(source).toContain('Menu.setApplicationMenu(null)')
    expect(source).toContain('isDevelopmentMenuEnabled(config.devServerUrl)')
    expect(source).toContain("logger('ELECTRON_UNMANAGED_DOWNLOAD_BLOCKED')")
  })

  it('starts the smoke watchdog before awaiting the renderer navigation', () => {
    expect(source.indexOf('startSmokeWatchdog()')).toBeLessThan(
      source.indexOf('void rendererWindow.loadURL(mainRendererTarget)'),
    )
    expect(source).toContain("logger('ELECTRON_SMOKE_WATCHDOG_EXPIRED')")
    expect(source).toContain("logger('ELECTRON_SMOKE_RENDERER_STABLE')")
    expect(source).toContain("logger('ELECTRON_SMOKE_STABILITY_RESET')")
    const backendStopped = source.indexOf("logger('ELECTRON_BACKEND_STOPPED')")
    const finalizing = source.indexOf("logger('ELECTRON_SHUTDOWN_STAGE', 'stage=finalizing_windows')")
    const firstLoggerFlush = source.indexOf('const preCompleteLogFlush = await flushShutdownLogs()')
    const shutdownComplete = source.indexOf("'ELECTRON_SHUTDOWN_COMPLETE'")
    expect(backendStopped).toBeGreaterThanOrEqual(0)
    expect(finalizing).toBeGreaterThan(backendStopped)
    expect(firstLoggerFlush).toBeGreaterThan(finalizing)
    expect(shutdownComplete).toBeGreaterThan(firstLoggerFlush)
    expect(source).toContain('function beginShutdownAndExit(): void')
    expect(source).toContain("app.on('window-all-closed'")
    expect(source).toContain('if (trayAvailable && closeToTrayEnabled && !explicitQuitRequested) return')
    expect(source).toContain('workspaceWindowController?.closeAllForQuit()')
    expect(source).not.toContain('process.exit(requestedExitCode)')
    expect(source).toContain("logger('ELECTRON_BACKEND_PROCESS_STILL_ALIVE')")
    expect(source).toContain("logger('ELECTRON_SHUTDOWN_INCOMPLETE'")
    expect(source).toContain('if (!complete) return')
    expect(source.indexOf('allowQuit = true')).toBeGreaterThan(
      source.indexOf('shutdownPromise = shutdown().then((complete)'),
    )
  })

  it('shows an observable system-themed loading page and gates the business renderer theme', () => {
    expect(source).toContain('show: false')
    expect(source).toContain('frame: true')
    expect(source).toContain('fullscreen: false')
    expect(source).toContain('nativeTheme.shouldUseDarkColors')
    expect(source).toContain('armRendererThemeDisplay(rendererWindow)')
    expect(source).toContain("windowDisplayGates.get(window)?.acceptResolvedTheme()")
    expect(displayGateSource).toContain('if (this.window.isVisible?.()) this.window.hide()')
    expect(source).toContain('installMainWindowStartup(')
    expect(source).toContain('screen.getPrimaryDisplay().workArea')
    expect(source).toContain('validateMainWindowStartupState()')
    expect(source).toContain('!mainWindow.isFullScreen()')
    expect(source).toContain('currentDisplay.id === primaryDisplay.id')
    expect(source).not.toMatch(/startupTimeline\.mark\('electron\.loading_view_shown'\)\r?\n\s+mainWindow\.show\(\)/)
    expect(source.indexOf("startupTimeline.mark('electron.loading_view_shown')")).toBeLessThan(
      source.indexOf('const runtime = await backend.start()'),
    )
    expect(source.indexOf('armRendererThemeDisplay(rendererWindow)')).toBeLessThan(
      source.indexOf('void rendererWindow.loadURL(mainRendererTarget)'),
    )
  })

  it('retries a fallback only through the Main-managed renderer target', () => {
    const retrySource = source.slice(
      source.indexOf('async function retryManagedRenderer'),
      source.indexOf('async function showManagedWindowError'),
    )
    expect(source).toContain('MANAGED_RENDERER_RETRY_ACTION')
    expect(source).not.toContain('href="${escapeHtml(retryUrl)}"')
    expect(source).toContain('rememberManagedRendererTarget(mainWindow, mainRendererTarget)')
    expect(source).toContain('prepareNavigation: (window, target) => {')
    expect(source).toContain('const windowRendererTargets = new WeakMap<BrowserWindow, string>()')
    expect(source.indexOf('rememberManagedRendererTarget(mainWindow, mainRendererTarget)')).toBeLessThan(
      source.indexOf('void rendererWindow.loadURL(mainRendererTarget)'),
    )
    expect(retrySource).toContain('let target = windowRendererTargets.get(window)')
    expect(retrySource).toContain('isAllowedNavigation(target, [...rendererOrigins])')
    expect(retrySource.indexOf('armRendererThemeDisplay(window)')).toBeLessThan(
      retrySource.indexOf('await window.loadURL(target)'),
    )
    expect(retrySource).not.toContain('window.loadURL(rendererUrl)')
  })

  it('cleans up the dev server for either Electron child completion event', () => {
    expect(devSource).toContain("electron.once('exit', finish)")
    expect(devSource).toContain("electron.once('close', finish)")
  })

  it('can be launched directly without a global pnpm command', () => {
    expect(devSource).not.toContain('npm_execpath')
    expect(devSource).toContain("require.resolve('typescript/package.json')")
    expect(devSource).toContain('Electron main/preload build')
    expect(devSource).toContain('delete electronEnv.ELECTRON_RUN_AS_NODE')
    expect(devSource).toContain("process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1'")
  })

  it('keeps Codex backend coordinates identical for persistent and isolated development', () => {
    expect(devSource).toContain('resolveCodexBackendPort(process.env.NETCONSOLE_DEV_BACKEND_PORT)')
    expect(devSource).toContain('resolveCodexSessionToken(process.env.NETCONSOLE_DEV_SESSION_TOKEN)')
    expect(devSource).toContain("NETCONSOLE_DEV_BACKEND_PORT: String(codexBackendPort)")
    expect(devSource).toContain("NETCONSOLE_DEV_SESSION_TOKEN: codexSessionToken")
    const isolatedBlock = devSource.slice(
      devSource.indexOf('...(isolated ? {'),
      devSource.indexOf('...(codex ? {', devSource.indexOf('...(isolated ? {')),
    )
    expect(isolatedBlock).not.toContain('NETCONSOLE_DEV_BACKEND_PORT')
    expect(isolatedBlock).not.toContain('NETCONSOLE_DEV_SESSION_TOKEN')
  })

  it('warms the renderer entry before Electron starts', () => {
    expect(devSource).toContain("process.stdout.write('Vite process started\\n')")
    expect(devSource).toContain("process.stdout.write('Vite HTTP ready\\n')")
    expect(devSource).toContain("process.stdout.write('Vite warmup ready\\n')")
    expect(devSource).toContain('await warmRendererModules()')
    expect(devSource.indexOf('await waitForVite(vite)')).toBeLessThan(
      devSource.indexOf("process.stdout.write('Electron starting\\n')"),
    )
  })

  it('opens the task center in the main renderer without creating a dedicated BrowserWindow', () => {
    const taskCenterSource = source.slice(
      source.indexOf('async function openTaskWindow'),
      source.indexOf('async function openWorkspaceWindow'),
    )
    expect(source).not.toContain('let taskWindow: BrowserWindow | undefined')
    expect(source).not.toContain("url.searchParams.set('task_window', '1')")
    expect(source).not.toContain('new TaskWindowController')
    expect(taskCenterSource).toContain('await restoreApplicationWindow()')
    expect(taskCenterSource).toContain('workspaceWindowController.getMainWindow()')
    expect(taskCenterSource).toContain('target.webContents.send(DESKTOP_IPC.taskCenterOpenRequested, context)')
    expect(source).toContain('for (const window of getAllDesktopWindows())')
    expect(source).toContain("error: '本地后端不可用'")
  })

  it('restores an existing process window without reapplying startup maximization', () => {
    const restoreSource = source.slice(
      source.indexOf('async function restoreApplicationWindow'),
      source.indexOf('function requestExplicitQuit'),
    )
    expect(restoreSource).not.toContain('.maximize()')
    expect(restoreSource).toContain('workspaceWindowController?.showMainWindow()')
    expect(source).toContain("throw new Error('tray restore reapplied main window startup state')")
  })

  it('blocks business actions once shutdown starts and handles Windows session end', () => {
    const taskSource = source.slice(
      source.indexOf('async function openTaskWindow'),
      source.indexOf('async function openWorkspaceWindow'),
    )
    const workspaceSource = source.slice(
      source.indexOf('async function openWorkspaceWindow'),
      source.indexOf('function getWorkspaceWindowState'),
    )
    const switchSource = source.slice(
      source.indexOf('async function requestTraySiteSwitch'),
      source.indexOf('async function refreshTraySiteContext'),
    )
    expect(taskSource).toContain('shuttingDown')
    expect(workspaceSource).toContain('shuttingDown')
    expect(switchSource).toContain('shuttingDown')
    expect(source).toContain(";(event as { preventDefault?: () => void }).preventDefault?.()")
    expect(source).toContain("logger('ELECTRON_SECOND_INSTANCE_IGNORED', 'reason=shutdown_in_progress')")
  })
})
