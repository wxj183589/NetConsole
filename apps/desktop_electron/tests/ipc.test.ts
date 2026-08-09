import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { registerDesktopIpc } from '../src/main/ipc'
import type { ExternalToolServiceLike } from '../src/main/external-tool-service'
import { GrantedPathRegistry } from '../src/main/path-access'
import type {
  NativeActionResult,
  RendererHostReport,
  RendererRecoveryState,
  RendererWorkloadReport,
  TaskWindowContext,
  WorkspaceWindowOpenRequest,
  WorkspaceWindowSnapshot,
} from '../src/shared/bridge'
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
  onRendererWorkload?: (report: RendererWorkloadReport, window: unknown) => void
  getRendererRecoveryState?: (window: unknown) => RendererRecoveryState | null
  openTaskWindow?: (value: TaskWindowContext) => NativeActionResult | Promise<NativeActionResult>
  openWorkspaceWindow?: (value: WorkspaceWindowOpenRequest) => NativeActionResult | Promise<NativeActionResult>
  getWorkspaceWindowState?: (window: unknown) => { windowId: string; snapshot: WorkspaceWindowSnapshot | null }
  saveWorkspaceWindowState?: (window: unknown, value: WorkspaceWindowSnapshot) => void
  setWorkspaceWindowTitle?: (window: unknown, title: string) => void
  restartBackend?: (value: { activeSiteId?: string; dataRoot?: string }) => Promise<void>
  refreshSiteContext?: () => Promise<void>
  setSiteSwitching?: (switching: boolean) => void
  windowForEvent?: (event: { sender: unknown }) => unknown
  fetchImpl?: typeof fetch
  externalToolService?: ExternalToolServiceLike
  clipboardWriteText?: (text: string) => void
  artifactLstat?: (path: string) => Promise<{
    isFile(): boolean
    isDirectory?(): boolean
    isSymbolicLink(): boolean
  }>
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
  const clipboard = { writeText: vi.fn(overrides.clipboardWriteText ?? (() => undefined)) }
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
    clipboard,
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
    onRendererWorkload: overrides.onRendererWorkload,
    getRendererRecoveryState: overrides.getRendererRecoveryState,
    openTaskWindow: overrides.openTaskWindow,
    openWorkspaceWindow: overrides.openWorkspaceWindow,
    getWorkspaceWindowState: overrides.getWorkspaceWindowState,
    saveWorkspaceWindowState: overrides.saveWorkspaceWindowState,
    setWorkspaceWindowTitle: overrides.setWorkspaceWindowTitle,
    restartBackend: overrides.restartBackend,
    refreshSiteContext: overrides.refreshSiteContext,
    setSiteSwitching: overrides.setSiteSwitching,
    fetchImpl: overrides.fetchImpl,
    externalToolService: overrides.externalToolService,
    artifactLstat: overrides.artifactLstat ?? (async () => ({
      isFile: () => true,
      isDirectory: () => true,
      isSymbolicLink: () => false,
    })),
  })
  return { ipcMain, sender, selectedFile, selectedDirectory, savedFile, shell, clipboard, pathRegistry, dialog }
}

function externalToolService(): ExternalToolServiceLike {
  const emptyList = { schema_version: 2 as const, categories: [], tools: [] }
  return {
    list: vi.fn(async () => emptyList),
    describeExecutable: vi.fn(async (path: string) => ({ cancelled: false, path })),
    stageCustomIcon: vi.fn(async () => ({ cancelled: true })),
    create: vi.fn(async () => ({ success: true, list: emptyList })),
    createSystemReference: vi.fn(async () => ({ success: true, list: emptyList })),
    update: vi.fn(async () => ({ success: true, list: emptyList })),
    delete: vi.fn(async () => ({ success: true, list: emptyList })),
    setFavorite: vi.fn(async () => ({ success: true, list: emptyList })),
    reorderTools: vi.fn(async () => ({ success: true, list: emptyList })),
    reorderCategories: vi.fn(async () => ({ success: true, list: emptyList })),
    createCategory: vi.fn(async () => ({ success: true, list: emptyList })),
    renameCategory: vi.fn(async () => ({ success: true, list: emptyList })),
    deleteCategory: vi.fn(async () => ({ success: true, list: emptyList })),
    launch: vi.fn(async (request) => ({ success: true, toolId: request.toolId })),
    reveal: vi.fn(async (toolId: string) => ({ success: true, toolId })),
  }
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

  it('writes validated text through the trusted clipboard handler', async () => {
    const { ipcMain, sender, clipboard } = createHarness()
    const handler = ipcMain.handlers.get(DESKTOP_IPC.writeClipboardText)!

    expect(handler({ sender }, 'AirScript source')).toEqual({ success: true })
    expect(clipboard.writeText).toHaveBeenCalledWith('AirScript source')
    expect(() => handler({ sender: {} }, 'blocked')).toThrow('未知渲染进程')
    expect(handler({ sender }, '')).toMatchObject({ success: false })
    expect(clipboard.writeText).toHaveBeenCalledOnce()
  })

  it('opens workspace windows only through validated trusted requests', async () => {
    const managedWindow = {}
    const openWorkspaceWindow = vi.fn(async () => ({ success: true }))
    const setWorkspaceWindowTitle = vi.fn()
    const { ipcMain, sender } = createHarness({
      openWorkspaceWindow,
      setWorkspaceWindowTitle,
      windowForEvent: () => managedWindow,
    })
    const event = { sender }
    await expect(ipcMain.handlers.get(DESKTOP_IPC.openWorkspaceWindow)?.(event, {
      routeFullPath: '/rail-transit/mesh-analysis?session_id=session-1',
      title: 'MESH：列车07',
    })).resolves.toEqual({ success: true })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.openWorkspaceWindow)?.(event, {
      routeFullPath: 'https://example.com',
      title: '外部页面',
    })).rejects.toThrow()
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.openWorkspaceWindow)?.(
      { sender: {} },
      { routeFullPath: '/', title: 'Dashboard' },
    )).toThrow('未知渲染进程')

    ipcMain.listeners.get(DESKTOP_IPC.setWorkspaceWindowTitle)?.(event, '设备：AC1')
    ipcMain.listeners.get(DESKTOP_IPC.setWorkspaceWindowTitle)?.({ sender: {} }, '设备：AC2')
    expect(setWorkspaceWindowTitle).toHaveBeenCalledWith(managedWindow, '设备：AC1')
    expect(setWorkspaceWindowTitle).toHaveBeenCalledOnce()
  })

  it('keeps external tool execution and reveal restricted to a validated tool id', async () => {
    const toolId = '7c890030-3a3f-4d6b-b58e-7624d21daff9'
    const service = externalToolService()
    const { ipcMain, sender } = createHarness({ externalToolService: service })
    const event = { sender }

    await ipcMain.handlers.get(DESKTOP_IPC.launchExternalTool)?.(event, {
      toolId,
      launchMode: 'normal',
    })
    await ipcMain.handlers.get(DESKTOP_IPC.revealExternalTool)?.(event, toolId)
    expect(service.launch).toHaveBeenCalledWith({ toolId, launchMode: 'normal' })
    expect(service.reveal).toHaveBeenCalledWith(toolId)
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.launchExternalTool)?.(event, {
      toolId,
      launchMode: 'normal',
      executablePath: 'C:\\Temp\\evil.exe',
    })).toThrow('unsupported field')
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.launchExternalTool)?.(event, {
      toolId,
      launchMode: 'runas',
    })).toThrow('launchMode is invalid')
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.revealExternalTool)?.(event, 'C:\\Temp\\evil.exe')).toThrow()
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.launchExternalTool)?.(
      { sender: {} },
      { toolId, launchMode: 'normal' },
    )).toThrow('未知渲染进程')
  })

  it('validates external tool create requests again in Main before calling the service', async () => {
    const service = externalToolService()
    const { ipcMain, sender } = createHarness({ externalToolService: service })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.createExternalTool)!
    const base = {
      name: 'IPOP',
      executablePath: 'C:\\Tools\\IPOP.EXE',
      arguments: [],
      categoryId: 'e5057ec4-03c5-4c17-b24d-b8111ee8f942',
      favorite: false,
      iconMode: 'auto',
      launchPrivilege: 'normal',
    }
    await handler({ sender }, base)
    expect(service.create).toHaveBeenCalledWith(base)
    expect(() => handler({ sender }, { ...base, executablePath: 'relative.exe' })).toThrow('absolute Windows path')
    expect(() => handler({ sender }, { ...base, executablePath: 'C:\\Tools\\tool.cmd' })).toThrow('.exe')
    expect(() => handler({ sender }, { ...base, command: 'calc.exe' })).toThrow('unsupported field')
    expect(() => handler({ sender }, { ...base, arguments: ['x && calc'] })).toThrow('不支持管道')
  })

  it('adds system terminal references by semantic key without accepting a copied path', async () => {
    const service = externalToolService()
    const { ipcMain, sender } = createHarness({ externalToolService: service })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.createExternalToolSystemReference)!

    await handler({ sender }, { sourceKey: 'securecrt' })
    expect(service.createSystemReference).toHaveBeenCalledWith({ sourceKey: 'securecrt' })
    expect(() => handler({ sender }, {
      sourceKey: 'securecrt',
      executablePath: 'C:\\Tools\\SecureCRT.exe',
    })).toThrow('unsupported field')
    expect(() => handler({ sender }, { sourceKey: 'ipop' })).toThrow('system setting tool key is invalid')
  })

  it('uses dedicated native filters for external executable and icon selection', async () => {
    const service = externalToolService()
    const { ipcMain, sender, dialog, selectedFile } = createHarness({ externalToolService: service })
    await ipcMain.handlers.get(DESKTOP_IPC.selectExternalToolExecutable)?.({ sender })
    expect(dialog.showOpenDialog).toHaveBeenLastCalledWith({}, {
      properties: ['openFile'],
      filters: [{ name: 'Windows 程序', extensions: ['exe'] }],
    })
    expect(service.describeExecutable).toHaveBeenCalledWith(selectedFile)

    await ipcMain.handlers.get(DESKTOP_IPC.selectExternalToolIcon)?.({ sender })
    expect(dialog.showOpenDialog).toHaveBeenLastCalledWith({}, {
      properties: ['openFile'],
      filters: [{ name: '图片文件', extensions: ['png', 'jpg', 'jpeg', 'ico'] }],
    })
  })

  it('returns restart success only after the managed Backend is ready', async () => {
    const restartBackend = vi.fn(async () => undefined)
    const { ipcMain, sender } = createHarness({ restartBackend })

    await expect(ipcMain.handlers.get(DESKTOP_IPC.restartBackend)!({ sender }, {
      activeSiteId: 'line-12',
    })).resolves.toEqual({ success: true })
    expect(restartBackend).toHaveBeenCalledWith({ activeSiteId: 'line-12' })
  })

  it('classifies managed restart failures without exposing raw errors', async () => {
    const restored = createHarness({
      restartBackend: vi.fn(async () => { throw new Error('Backend 重启失败，已恢复原局点。') }),
    })
    await expect(restored.ipcMain.handlers.get(DESKTOP_IPC.restartBackend)!({ sender: restored.sender }, {
      activeSiteId: 'line-12',
    })).resolves.toEqual({ success: false, error: 'Backend 重启失败，已恢复原局点。' })

    const sensitive = createHarness({
      restartBackend: vi.fn(async () => { throw new Error('token=secret C:\\private\\data') }),
    })
    await expect(sensitive.ipcMain.handlers.get(DESKTOP_IPC.restartBackend)!({ sender: sensitive.sender }, {
      activeSiteId: 'line-12',
    })).resolves.toEqual({ success: false, error: '本地 Backend 重启失败，请检查日志后重试。' })
  })

  it('refreshes tray site facts only for a trusted renderer and accepts boolean switch state', async () => {
    const refreshSiteContext = vi.fn(async () => undefined)
    const setSiteSwitching = vi.fn()
    const { ipcMain, sender } = createHarness({ refreshSiteContext, setSiteSwitching })

    await expect(ipcMain.handlers.get(DESKTOP_IPC.refreshSiteContext)!({ sender })).resolves.toBeUndefined()
    expect(refreshSiteContext).toHaveBeenCalledOnce()
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.refreshSiteContext)!({ sender: {} })).toThrow('未知渲染进程')

    ipcMain.listeners.get(DESKTOP_IPC.siteSwitchState)?.({ sender }, true)
    ipcMain.listeners.get(DESKTOP_IPC.siteSwitchState)?.({ sender }, 'true')
    ipcMain.listeners.get(DESKTOP_IPC.siteSwitchState)?.({ sender: {} }, false)
    expect(setSiteSwitching).toHaveBeenCalledWith(true)
    expect(setSiteSwitching).toHaveBeenCalledOnce()
  })

  it('accepts only validated one-way workload reports and returns in-memory recovery state', () => {
    const onRendererWorkload = vi.fn()
    const recovery: RendererRecoveryState = {
      mode: 'safe',
      previousReason: 'oom',
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      sessionId: 'session-1',
      sourceFileId: 9,
      radio: 1,
    }
    const managedWindow = {}
    const logger = vi.fn()
    const { ipcMain, sender } = createHarness({
      logger,
      onRendererWorkload,
      getRendererRecoveryState: () => recovery,
      windowForEvent: () => managedWindow,
    })
    const event = { sender }
    ipcMain.listeners.get(DESKTOP_IPC.rendererWorkload)?.(event, {
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'echarts-set-option',
      sessionId: 'session-1',
      seriesCount: 770,
      returnedLinkPoints: 44_251,
      reportRevision: 2,
    })

    expect(onRendererWorkload).toHaveBeenCalledWith(
      expect.objectContaining({ phase: 'echarts-set-option', seriesCount: 770 }),
      managedWindow,
    )
    expect(ipcMain.handlers.get(DESKTOP_IPC.rendererRecoveryState)?.(event)).toEqual(recovery)

    ipcMain.listeners.get(DESKTOP_IPC.rendererWorkload)?.(event, {
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'echarts-set-option',
      rawPath: 'C:\\private\\raw.log',
      reportRevision: 3,
    })
    ipcMain.listeners.get(DESKTOP_IPC.rendererWorkload)?.({ sender: {} }, {
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'echarts-set-option',
      reportRevision: 4,
    })
    expect(onRendererWorkload).toHaveBeenCalledOnce()
    expect(logger).toHaveBeenCalledWith('ELECTRON_RENDERER_WORKLOAD_REJECTED')
    expect(logger).toHaveBeenCalledWith('ELECTRON_RENDERER_WORKLOAD_UNTRUSTED')
  })

  it('accepts only the fixed UI preference key allowlist', async () => {
    const { ipcMain, sender } = createHarness()
    const event = { sender }
    await expect(ipcMain.handlers.get(DESKTOP_IPC.getUiPreference)!(
      event,
      'C:\\arbitrary\\preference.json',
    )).rejects.toThrow('UI preference key is invalid')
    await expect(ipcMain.handlers.get(DESKTOP_IPC.setUiPreference)!(
      event,
      ['mesh-analysis-rssi.show-switch-points', 'false'],
    )).rejects.toThrow('UI chart preference must be a boolean')
    await expect(ipcMain.handlers.get(DESKTOP_IPC.setUiPreference)!(
      event,
      ['mesh-analysis-airload.show-switch-lines', true],
    )).resolves.toBeUndefined()
    await expect(ipcMain.handlers.get(DESKTOP_IPC.getUiPreference)!(
      event,
      'mesh-analysis.table.link-details:v3',
    )).resolves.toBeNull()
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

  it('hands external paths to Explorer and minimizes NetConsole only when it keeps focus', async () => {
    vi.useFakeTimers()
    try {
      const managedWindow = {
        isDestroyed: vi.fn(() => false),
        isFocused: vi.fn(() => true),
        isAlwaysOnTop: vi.fn(() => true),
        setAlwaysOnTop: vi.fn(),
        blur: vi.fn(),
        minimize: vi.fn(),
      }
      const { ipcMain, sender, selectedFile, pathRegistry } = createHarness({ windowForEvent: () => managedWindow })
      const handler = ipcMain.handlers.get(DESKTOP_IPC.openPath)!

      await expect(handler({ sender }, pathRegistry.grantCapability(selectedFile)!)).resolves.toEqual({ success: true })
      expect(managedWindow.setAlwaysOnTop).toHaveBeenCalledWith(false)
      expect(managedWindow.blur).toHaveBeenCalledOnce()

      vi.advanceTimersByTime(350)
      expect(managedWindow.minimize).toHaveBeenCalledOnce()
      expect(managedWindow.setAlwaysOnTop).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not minimize or leave a failed external open in a released topmost state', async () => {
    vi.useFakeTimers()
    try {
      const managedWindow = {
        isDestroyed: vi.fn(() => false),
        isFocused: vi.fn(() => true),
        isAlwaysOnTop: vi.fn(() => true),
        setAlwaysOnTop: vi.fn(),
        blur: vi.fn(),
        minimize: vi.fn(),
      }
      const { ipcMain, sender, selectedFile, pathRegistry, shell } = createHarness({ windowForEvent: () => managedWindow })
      shell.openPath.mockResolvedValue('系统未能打开')
      const handler = ipcMain.handlers.get(DESKTOP_IPC.openPath)!

      await expect(handler({ sender }, pathRegistry.grantCapability(selectedFile)!)).resolves.toEqual({
        success: false,
        error: '系统未能打开所选路径',
      })
      vi.advanceTimersByTime(350)
      expect(managedWindow.minimize).not.toHaveBeenCalled()
      expect(managedWindow.setAlwaysOnTop).toHaveBeenLastCalledWith(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('leaves an external window that took focus alone', async () => {
    vi.useFakeTimers()
    try {
      const managedWindow = {
        isDestroyed: vi.fn(() => false),
        isFocused: vi.fn(() => false),
        isAlwaysOnTop: vi.fn(() => false),
        setAlwaysOnTop: vi.fn(),
        blur: vi.fn(),
        minimize: vi.fn(),
      }
      const { ipcMain, sender, selectedFile, pathRegistry } = createHarness({ windowForEvent: () => managedWindow })
      const handler = ipcMain.handlers.get(DESKTOP_IPC.openPath)!

      await expect(handler({ sender }, pathRegistry.grantCapability(selectedFile)!)).resolves.toEqual({ success: true })
      vi.advanceTimersByTime(350)
      expect(managedWindow.minimize).not.toHaveBeenCalled()
      expect(managedWindow.setAlwaysOnTop).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('ignores a destroyed source window during external path handoff', async () => {
    vi.useFakeTimers()
    try {
      const managedWindow = {
        isDestroyed: vi.fn(() => true),
        isFocused: vi.fn(() => true),
        isAlwaysOnTop: vi.fn(() => true),
        setAlwaysOnTop: vi.fn(),
        blur: vi.fn(),
        minimize: vi.fn(),
      }
      const { ipcMain, sender, selectedFile, pathRegistry } = createHarness({ windowForEvent: () => managedWindow })
      const handler = ipcMain.handlers.get(DESKTOP_IPC.openPath)!

      await expect(handler({ sender }, pathRegistry.grantCapability(selectedFile)!)).resolves.toEqual({ success: true })
      vi.advanceTimersByTime(350)
      expect(managedWindow.blur).not.toHaveBeenCalled()
      expect(managedWindow.minimize).not.toHaveBeenCalled()
      expect(managedWindow.setAlwaysOnTop).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
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

  it('returns structured unavailable results when an Artifact disappears after capability grant', async () => {
    const missing = Object.assign(new Error('missing'), { code: 'ENOENT' })
    const artifactLstat = vi.fn(async () => { throw missing })
    const { ipcMain, sender, selectedFile, pathRegistry, shell } = createHarness({ artifactLstat })
    const capability = pathRegistry.grantCapability(selectedFile)!

    await expect(ipcMain.handlers.get(DESKTOP_IPC.openPath)!({ sender }, capability)).resolves.toEqual({
      success: false,
      availability: 'MISSING',
      error: '已保存的文件不存在，请重新下载后再试',
    })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.showItemInFolder)!({ sender }, capability)).resolves.toEqual({
      success: false,
      availability: 'MISSING',
      error: '已保存的文件不存在，请重新下载后再试',
    })
    expect(shell.openPath).not.toHaveBeenCalled()
    expect(shell.showItemInFolder).not.toHaveBeenCalled()
  })

  it.each([
    ['directory', false, false],
    ['symbolic link', true, true],
  ])('rejects a replaced Artifact %s before invoking the shell', async (_kind, isFile, isSymbolicLink) => {
    const artifactLstat = vi.fn(async () => ({
      isFile: () => isFile,
      isSymbolicLink: () => isSymbolicLink,
    }))
    const { ipcMain, sender, selectedFile, pathRegistry, shell } = createHarness({ artifactLstat })
    const capability = pathRegistry.grantCapability(selectedFile)!

    await expect(ipcMain.handlers.get(DESKTOP_IPC.openPath)!({ sender }, capability)).resolves.toMatchObject({
      success: false,
      availability: 'INVALID',
    })
    expect(shell.openPath).not.toHaveBeenCalled()
  })

  it('validates dialog DTOs at the main-process boundary', async () => {
    const { ipcMain, sender } = createHarness()
    const handler = ipcMain.handlers.get(DESKTOP_IPC.chooseSavePath)!

    await expect(handler({ sender }, { suggestedName: '..\\unsafe.exe' })).rejects.toThrow('safe file name')
  })

  it('uses the typed site-package filters for migration and collection return packages', async () => {
    const { ipcMain, sender, dialog } = createHarness()
    const event = { sender }

    await ipcMain.handlers.get(DESKTOP_IPC.selectSitePackage)!(event)
    expect(dialog.showOpenDialog).toHaveBeenLastCalledWith(
      expect.anything(),
      expect.objectContaining({ filters: [{ name: 'NetConsole 数据包', extensions: ['ncsite', 'ncresult'] }] }),
    )
    await ipcMain.handlers.get(DESKTOP_IPC.selectSiteExportDestination)!(event, '宁波地铁1号线_采集回传包.ncresult')
    expect(dialog.showSaveDialog).toHaveBeenLastCalledWith(
      expect.anything(),
      expect.objectContaining({ filters: [{ name: 'NetConsole 采集回传包', extensions: ['ncresult'] }] }),
    )
  })

  it('uses only a directory selected in the current desktop session as save location', async () => {
    const { ipcMain, sender, selectedDirectory, savedFile, dialog } = createHarness()
    const event = { sender }
    const directory = await ipcMain.handlers.get(DESKTOP_IPC.selectDirectory)!(event)
    await ipcMain.handlers.get(DESKTOP_IPC.chooseSavePath)!(event, {
      suggestedName: '线路名称表.nam',
      directoryPath: (directory as { path: string }).path,
    })

    expect(dialog.showSaveDialog).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ defaultPath: resolve(selectedDirectory, '线路名称表.nam') }),
    )
    await expect(ipcMain.handlers.get(DESKTOP_IPC.chooseSavePath)!(event, {
      suggestedName: '线路名称表.nam',
      directoryPath: resolve('not-selected'),
    })).rejects.toThrow('未由当前桌面会话授权')
    expect(savedFile).toBeTruthy()
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
    dialog.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [resolve('PuTTY64.exe')] })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsTool)!(event, 'putty')).resolves.toMatchObject({ cancelled: false, path: resolve('PuTTY64.exe') })
    expect(dialog.showOpenDialog).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ filters: [{ name: 'PuTTY', extensions: ['exe'] }] }))
    dialog.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [resolve('plink.exe')] })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsTool)!(event, 'putty')).rejects.toThrow('does not match tool id')
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsTool)!(event, 'cmd')).rejects.toThrow('settings tool id is invalid')
    await expect(ipcMain.handlers.get(DESKTOP_IPC.selectSettingsColor)!(event)).resolves.toEqual({ cancelled: false, color: '#2563EB' })
    await expect(ipcMain.handlers.get(DESKTOP_IPC.executeSettingsAction)!(event, 'open_settings_config')).resolves.toEqual({ success: true })
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('http://127.0.0.1:43123/api/settings/native-action')
    expect(() => ipcMain.handlers.get(DESKTOP_IPC.executeSettingsAction)!(event, 'launch_ipop'))
      .toThrow('settings action id is invalid')
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
    const openTaskWindow = vi.fn(async () => ({ success: true }))
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

  it('returns the task window failure instead of reporting a false success', async () => {
    const openTaskWindow = vi.fn(async () => ({ success: false, error: '任务中心加载失败' }))
    const { ipcMain, sender } = createHarness({ openTaskWindow })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.openTaskWindow)!

    await expect(handler({ sender }, { module: 'rail' })).resolves.toEqual({ success: false, error: '任务中心加载失败' })
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
      JSON.stringify({ action: 'open_local', success: true, message: '已打开目录。', target_path: 'C:\\Users\\测试 用户\\下载' }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    const { ipcMain, sender, shell } = createHarness({ fetchImpl: fetchMock })
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
    expect(shell.openPath).toHaveBeenCalledWith('C:\\Users\\测试 用户\\下载')
  })

  it('resolves and opens an Online MR location only through the fixed authenticated endpoint', async () => {
    const managedFile = resolve('managed-online-mr', 'session.zip')
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(
      JSON.stringify({ target_type: 'file', path: managedFile }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    const { ipcMain, sender, shell } = createHarness({ fetchImpl: fetchMock })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.openOnlineMrSessionLocation)!

    await expect(handler({ sender }, '20260721_155004_ea78c0')).resolves.toEqual({ success: true, availability: 'AVAILABLE' })
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      'http://127.0.0.1:43123/api/online-mr/sessions/20260721_155004_ea78c0/desktop-location',
    )
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      headers: { 'X-NetConsole-Session': 'secret-token' },
      redirect: 'error',
    })
    expect(shell.showItemInFolder).toHaveBeenCalledWith(managedFile)
    expect(shell.openPath).not.toHaveBeenCalled()
    expect(() => handler({ sender }, '..\\outside')).toThrow('session id is invalid')
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('returns a safe message when an Online MR local target no longer exists', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(
      JSON.stringify({
        detail: {
          code: 'ONLINE_MR_LOCAL_FILES_MISSING',
          message: '该会话的本地文件已不存在。',
        },
      }),
      { status: 404, headers: { 'content-type': 'application/json' } },
    ))
    const { ipcMain, sender, shell } = createHarness({ fetchImpl: fetchMock })
    const handler = ipcMain.handlers.get(DESKTOP_IPC.openOnlineMrSessionLocation)!

    await expect(handler({ sender }, 'session-1')).resolves.toEqual({
      success: false,
      availability: 'MISSING',
      error: '该会话的本地文件已不存在。',
    })
    expect(shell.showItemInFolder).not.toHaveBeenCalled()
    expect(shell.openPath).not.toHaveBeenCalled()
  })

  it('returns structured missing and invalid states when an Online MR target changes externally', async () => {
    const managedDirectory = resolve('managed-online-mr', 'session-1')
    const response = () => new Response(
      JSON.stringify({ target_type: 'directory', path: managedDirectory }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )
    const missing = Object.assign(new Error('missing'), { code: 'ENOENT' })
    let harness = createHarness({
      fetchImpl: vi.fn<typeof fetch>(async () => response()),
      artifactLstat: vi.fn(async () => { throw missing }),
    })
    let handler = harness.ipcMain.handlers.get(DESKTOP_IPC.openOnlineMrSessionLocation)!
    await expect(handler({ sender: harness.sender }, 'session-1')).resolves.toEqual({
      success: false,
      availability: 'MISSING',
      error: '该会话的本地文件已不存在。',
    })
    expect(harness.shell.openPath).not.toHaveBeenCalled()

    harness = createHarness({
      fetchImpl: vi.fn<typeof fetch>(async () => response()),
      artifactLstat: vi.fn(async () => ({
        isFile: () => true,
        isDirectory: () => false,
        isSymbolicLink: () => false,
      })),
    })
    handler = harness.ipcMain.handlers.get(DESKTOP_IPC.openOnlineMrSessionLocation)!
    await expect(handler({ sender: harness.sender }, 'session-1')).resolves.toEqual({
      success: false,
      availability: 'INVALID',
      error: '该会话的本地路径无效或不是受管普通路径。',
    })
    expect(harness.shell.openPath).not.toHaveBeenCalled()
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
