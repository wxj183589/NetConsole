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
  fetchImpl?: typeof fetch
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
    fetchImpl: overrides.fetchImpl,
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
    const { ipcMain, sender, selectedFile, shell, pathRegistry } = createHarness()
    const event = { sender }
    const open = ipcMain.handlers.get(DESKTOP_IPC.openPath)!
    const reveal = ipcMain.handlers.get(DESKTOP_IPC.showItemInFolder)!

    expect(await open(event, pathRegistry.grantCapability(selectedFile)!)).toEqual({ success: true })
    const revealCapability = pathRegistry.grantCapability(selectedFile)!
    expect(await reveal(event, revealCapability)).toEqual({ success: true })
    expect(pathRegistry.grantCapability(resolve('danger.exe'))).toBeUndefined()
    expect(pathRegistry.grantCapability(selectedFile, 'artifact-download', [])).toBeUndefined()
    expect(await open(event, resolve('not-granted.txt'))).toEqual({
      success: false,
      error: '文件授权标识无效',
    })
    expect(shell.openPath).toHaveBeenCalledOnce()
    expect(shell.showItemInFolder).toHaveBeenCalledOnce()
  })

  it('expires, evicts and isolates capability purpose and actions', () => {
    let now = 1_000
    const registry = new GrantedPathRegistry({ now: () => now, ttlMs: 10, maxCapabilities: 2 })
    const first = registry.grantCapability(resolve('first.zip'))!
    const second = registry.grantCapability(resolve('second.zip'))!
    const third = registry.grantCapability(resolve('third.zip'))!

    expect(() => registry.requireCapability(first, 'artifact-download', 'open')).toThrow('已失效')
    expect(registry.requireCapability(second, 'artifact-download', 'reveal')).toBe(resolve('second.zip'))
    expect(registry.requireCapability(third, 'artifact-download', 'open')).toBe(resolve('third.zip'))

    const isolated = registry.grantCapability(resolve('selected.txt'), 'selected-file', ['open'])!
    expect(() => registry.requireCapability(isolated, 'artifact-download', 'open')).toThrow('用途不匹配')
    expect(() => registry.requireCapability(isolated, 'selected-file', 'reveal')).toThrow('用途不匹配')
    now += 10
    expect(() => registry.requireCapability(isolated, 'selected-file', 'open')).toThrow('已过期')
    expect(() => registry.requireCapability('00000000-0000-4000-8000-000000000000', 'artifact-download', 'open')).toThrow('已失效')
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
    await expect(handler({ sender }, { module: 'ac' })).resolves.toEqual({ success: true })
    await expect(handler({ sender }, { module: 'rail' })).resolves.toEqual({ success: true })
    await expect(handler({ sender }, { module: 'unknown' })).rejects.toThrow('module is invalid')
    await expect(handler({ sender }, { taskId: '../unsafe' })).rejects.toThrow('taskId is invalid')
    expect(openTaskWindow).toHaveBeenCalledTimes(3)
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

  it('executes only opaque file actions through the fixed loopback endpoint', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(
      JSON.stringify({ action: 'open_local', success: true, message: '已打开目录。' }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    const { ipcMain, sender } = createHarness({ fetchImpl: fetchMock })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.executeFileDesktopAction)!
    const actionRef = `fda1_${'a'.repeat(32)}`

    await expect(handler({ sender }, actionRef)).resolves.toEqual({ success: true })
    expect(() => handler({ sender }, 'C:\\private')).toThrow('reference is invalid')
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:43123/api/file-management/desktop-actions/${actionRef}/execute`,
    )
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      headers: { 'X-NetConsole-Session': 'secret-token' },
      redirect: 'error',
    })
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
