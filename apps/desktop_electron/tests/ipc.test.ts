import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { registerDesktopIpc } from '../src/main/ipc'
import { GrantedPathRegistry } from '../src/main/path-access'
import type { RendererHostReport } from '../src/shared/bridge'
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
  onRendererReady?: (report: RendererHostReport, window: unknown) => void
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
    showMessageBox: vi.fn(async () => ({ response: 1 })),
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

  it('uses only semantic settings ids for native settings actions', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ success: true }), { status: 200 }))
    const { ipcMain, sender, dialog } = createHarness({ fetchImpl: fetchMock })
    const event = { sender }
    dialog.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [resolve('iperf3.exe')] })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsTool)!(event, 'iperf3')).resolves.toMatchObject({ cancelled: false })
    expect(dialog.showOpenDialog).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ filters: [{ name: 'iperf3.exe', extensions: ['exe'] }] }))
    dialog.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [resolve('cmd.exe')] })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsTool)!(event, 'iperf3')).rejects.toThrow('does not match tool id')
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsTool)!(event, 'cmd')).rejects.toThrow('settings tool id is invalid')
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsColor)!(event)).resolves.toEqual({ cancelled: false, color: '#2563EB' })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.executeSettingsAction)!(event, 'launch_ipop')).resolves.toEqual({ success: true })
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('http://127.0.0.1:43123/api/settings/native-action')
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
    await expect(handler({ sender }, { module: 'network' })).resolves.toEqual({ success: true })
    await expect(handler({ sender }, { module: 'command-reference' })).resolves.toEqual({ success: true })
    await expect(handler({ sender }, { module: 'logs' })).resolves.toEqual({ success: true })
    await expect(handler({ sender }, { module: 'unknown' })).rejects.toThrow('module is invalid')
    await expect(handler({ sender }, { taskId: '../unsafe' })).rejects.toThrow('taskId is invalid')
    expect(openTaskWindow).toHaveBeenCalledTimes(6)
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

  it('updates only the calling managed window for whitelisted resolved themes', () => {
    const setBackgroundColor = vi.fn()
    const logger = vi.fn()
    const managedWindow = { setBackgroundColor }
    const onRendererReady = vi.fn()
    const { ipcMain, sender } = createHarness({ logger, onRendererReady, windowForEvent: () => managedWindow })
    const listener = ipcMain.listeners.get(DESKTOP_IPC.rendererReady)!

    listener({ sender }, { resolvedTheme: 'dark' })
    listener({ sender }, { resolvedTheme: 'light' })
    expect(setBackgroundColor).toHaveBeenNthCalledWith(1, '#0f141c')
    expect(setBackgroundColor).toHaveBeenNthCalledWith(2, '#f4f6f8')
    expect(onRendererReady).toHaveBeenNthCalledWith(1, { resolvedTheme: 'dark' }, managedWindow)
    expect(onRendererReady).toHaveBeenNthCalledWith(2, { resolvedTheme: 'light' }, managedWindow)

    listener({ sender }, { resolvedTheme: 'auto' })
    listener({ sender }, { resolvedTheme: 'dark', arbitraryWindowOption: true })
    expect(setBackgroundColor).toHaveBeenCalledTimes(2)
    expect(logger).toHaveBeenCalledTimes(2)

    listener({ sender: {} }, { resolvedTheme: 'dark' })
    expect(setBackgroundColor).toHaveBeenCalledTimes(2)
  })
})
