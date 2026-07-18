import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'main', 'index.ts'),
  'utf8',
)
const devSource = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'dev.mjs'),
  'utf8',
)

describe('Electron shell product contract', () => {
  it('uses the product title and hides the default menu unless development opts in', () => {
    expect(source).toContain("title: 'NetConsole'")
    expect(source).toContain('autoHideMenuBar: !developmentMenu')
    expect(source).toContain('Menu.setApplicationMenu(null)')
    expect(source).toContain('isDevelopmentMenuEnabled(config.devServerUrl)')
    expect(source).toContain("logger('ELECTRON_UNMANAGED_DOWNLOAD_BLOCKED')")
  })

  it('starts the smoke watchdog before awaiting the renderer navigation', () => {
    expect(source.indexOf('startSmokeWatchdog()')).toBeLessThan(
      source.indexOf('void mainWindow.loadURL(rendererUrl)'),
    )
    expect(source).toContain("logger('ELECTRON_SMOKE_WATCHDOG_EXPIRED')")
    expect(source).toContain("logger('ELECTRON_SMOKE_RENDERER_STABLE')")
    expect(source).toContain("logger('ELECTRON_SMOKE_STABILITY_RESET')")
    expect(source).toContain("logger('ELECTRON_SHUTDOWN_COMPLETE')")
    expect(source).toContain('function beginShutdownAndExit(): void')
    expect(source).toContain("app.on('window-all-closed', () => requestExit(0))")
    expect(source).toContain('mainWindow.destroy()')
    expect(source).toContain('setImmediate(() => process.exit(requestedExitCode))')
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
  })

  it('keeps one hide-on-close task window without stopping the backend', () => {
    expect(source).toContain('let taskWindow: BrowserWindow | undefined')
    expect(source).toContain("url.searchParams.set('task_window', '1')")
    expect(source).toContain('taskWindow?.hide()')
    expect(source).toContain('if (allowQuit) return')
    expect(source.indexOf('taskWindow?.hide()')).toBeLessThan(source.indexOf('await backend?.stop()'))
    expect(source).toContain('taskWindow.destroy()')
    expect(source).toContain('installManagedWindowDiagnostics(taskWindow)')
    expect(source).toContain('for (const window of [mainWindow, taskWindow])')
    expect(source).toContain("error: '本地后端不可用'")
  })
})
