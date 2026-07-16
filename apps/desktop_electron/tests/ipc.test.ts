import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { registerDesktopIpc } from '../src/main/ipc'
import { GrantedPathRegistry } from '../src/main/path-access'
import { DESKTOP_HANDLED_CHANNELS, DESKTOP_IPC } from '../src/shared/bridge'

class FakeIpcMain {
  readonly handlers = new Map<string, (event: { sender: unknown }, value?: unknown) => unknown>()
  readonly listeners = new Map<string, (event: { sender: unknown }, value?: unknown) => void>()

  handle(channel: string, listener: (event: { sender: unknown }, value?: unknown) => unknown): void {
    this.handlers.set(channel, listener)
  }

  removeHandler(channel: string): void {
    this.handlers.delete(channel)
  }

  on(channel: string, listener: (event: { sender: unknown }, value?: unknown) => void): void {
    this.listeners.set(channel, listener)
  }
}

function createHarness(overrides: {
  logger?: (event: string, detail?: string) => void
  onRendererReady?: (healthOk: boolean) => void
  openTaskWindow?: (value: unknown) => void
  windowForEvent?: (event: { sender: unknown }) => unknown
} = {}) {
  const ipcMain = new FakeIpcMain()
  const sender = {}
  const selectedFile = resolve('selected.log')
  const selectedDirectory = resolve('selected-directory')
  const savedFile = resolve('report.xlsx')
  const pathRegistry = new GrantedPathRegistry()
  const shell = {
    openPath: vi.fn(async () => ''),
    showItemInFolder: vi.fn(),
    openExternal: vi.fn(async () => undefined),
  }
  const dialog = {
    showOpenDialog: vi.fn(async (_window, options) => options.properties.includes('openDirectory')
      ? { canceled: false, filePaths: [selectedDirectory] }
      : { canceled: false, filePaths: [selectedFile] }),
    showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: savedFile })),
  }
  registerDesktopIpc({
    ipcMain,
    dialog,
    shell,
    window: {},
    windowForEvent: overrides.windowForEvent,
    appInfo: { version: '1.3.8', platform: 'win32', isPackaged: false },
    backend: {
      getStatus: () => ({ state: 'ready', baseUrl: 'http://127.0.0.1:43123' }),
      getRuntimeInfo: () => ({ baseUrl: 'http://127.0.0.1:43123', apiToken: 'secret-token' }),
    },
    pathRegistry,
    isTrustedSender: (event) => event.sender === sender,
    logger: overrides.logger,
    onRendererReady: overrides.onRendererReady,
    openTaskWindow: overrides.openTaskWindow,
  })
  return { ipcMain, sender, selectedFile, selectedDirectory, savedFile, shell, pathRegistry, dialog }
}

describe('desktop IPC', () => {
  it('registers only the explicit handler whitelist', () => {
    const { ipcMain } = createHarness()

    expect([...ipcMain.handlers.keys()].sort()).toEqual([...DESKTOP_HANDLED_CHANNELS].sort())
    expect(ipcMain.handlers.has('netconsole:desktop:execute-command')).toBe(false)
  })

  it('rejects untrusted senders before returning runtime secrets', async () => {
    const { ipcMain } = createHarness()
    const handler = ipcMain.handlers.get(DESKTOP_IPC.getRuntimeConfig)!

    expect(() => handler({ sender: {} })).toThrow('未知渲染进程')
  })

  it('opens only opaque in-memory capabilities and never renderer paths', async () => {
    const { ipcMain, sender, selectedFile, selectedDirectory, shell, pathRegistry } = createHarness()
    const event = { sender }
    const open = ipcMain.handlers.get(DESKTOP_IPC.openPath)!
    const reveal = ipcMain.handlers.get(DESKTOP_IPC.showItemInFolder)!

    expect(await open(event, pathRegistry.grantCapability(selectedFile))).toEqual({ success: true })
    expect(await reveal(event, pathRegistry.grantCapability(selectedDirectory, 'directory'))).toEqual({ success: true })
    expect(await open(event, pathRegistry.grantCapability(resolve('danger.py')))).toEqual({
      success: false,
      error: '桌面桥接只允许打开受支持的数据与报告文件',
    })
    expect(await open(event, resolve('not-granted.txt'))).toEqual({
      success: false,
      error: '文件授权标识无效',
    })
    expect(shell.openPath).toHaveBeenCalledOnce()
  })

  it('validates dialog DTOs at the main-process boundary', async () => {
    const { ipcMain, sender } = createHarness()
    const handler = ipcMain.handlers.get(DESKTOP_IPC.chooseSavePath)!

    await expect(handler({ sender }, { suggestedName: '..\\unsafe.exe' })).rejects.toThrow('safe file name')
  })

  it('parents dialogs and downloads to the calling managed window', async () => {
    const taskWindow = { kind: 'task' }
    const { ipcMain, sender, dialog } = createHarness({ windowForEvent: () => taskWindow })
    const event = { sender }

    await ipcMain.handlers.get(DESKTOP_IPC.selectFile)!(event, {})
    await ipcMain.handlers.get(DESKTOP_IPC.chooseSavePath)!(event, { suggestedName: 'report.xlsx' })

    expect(dialog.showOpenDialog).toHaveBeenCalledWith(taskWindow, expect.any(Object))
    expect(dialog.showSaveDialog).toHaveBeenCalledWith(taskWindow, expect.any(Object))
  })

  it('opens the task window only with the strict filter DTO', async () => {
    const openTaskWindow = vi.fn()
    const { ipcMain, sender } = createHarness({ openTaskWindow })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.openTaskWindow)!

    await expect(handler({ sender }, { taskId: 'task-1', module: 'devices', status: 'RUNNING' })).resolves.toEqual({ success: true })
    await expect(handler({ sender }, { module: 'unknown' })).rejects.toThrow('module is invalid')
    await expect(handler({ sender }, { taskId: '../unsafe' })).rejects.toThrow('taskId is invalid')
    expect(openTaskWindow).toHaveBeenCalledOnce()
  })

  it('opens only credential-free HTTPS urls in the system browser', async () => {
    const { ipcMain, sender, shell } = createHarness()
    const handler = ipcMain.handlers.get(DESKTOP_IPC.openExternalUrl)!

    await expect(handler({ sender }, 'https://192.0.2.10:8443')).resolves.toEqual({ success: true })
    await expect(handler({ sender }, 'http://192.0.2.10/')).resolves.toEqual({ success: false, error: '桌面操作失败' })
    await expect(handler({ sender }, 'https://admin:secret@192.0.2.10/')).resolves.toEqual({ success: false, error: '桌面操作失败' })
    expect(shell.openExternal).toHaveBeenCalledOnce()
    expect(shell.openExternal).toHaveBeenCalledWith('https://192.0.2.10:8443/')
  })

  it('rejects arbitrary backend download URLs at the main-process boundary', async () => {
    const { ipcMain, sender } = createHarness()
    const handler = ipcMain.handlers.get(DESKTOP_IPC.downloadBackendResource)!

    await expect(handler({ sender }, {
      apiPath: 'https://example.com/report.zip',
      suggestedName: 'report.zip',
    })).rejects.toThrow('safe relative /api path')
  })

  it('rejects malformed renderer-ready reports without throwing from the main event loop', () => {
    const logger = vi.fn()
    const onRendererReady = vi.fn()
    const { ipcMain, sender } = createHarness({ logger, onRendererReady })
    const listener = ipcMain.listeners.get(DESKTOP_IPC.rendererReady)!

    expect(() => listener({ sender }, { healthOk: 'yes' })).not.toThrow()
    expect(onRendererReady).not.toHaveBeenCalled()
    expect(logger).toHaveBeenCalledWith('ELECTRON_RENDERER_READY_REJECTED')
  })
})
