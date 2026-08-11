import { afterEach, describe, expect, it, vi } from 'vitest'

import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import {
  downloadBackendResource,
  getRuntimeConfig,
  initializePlatformRuntime,
  resetPlatformRuntimeForTests,
  resolveApiUrl,
  resolveFrontendAssetUrl,
  resolveWebSocketUrl,
} from './runtime'

const TOKEN = 'electron-test-token-abcdefghijklmnopqrstuvwxyz'

function nativeBridge(): NetConsoleDesktopBridge {
  return {
    getAppInfo: vi.fn(async () => ({ version: '1.3.8', platform: 'win32', isPackaged: false })),
    getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: 'http://127.0.0.1:43123' })),
    getRuntimeConfig: vi.fn(async () => ({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: TOKEN })),
    openTaskWindow: vi.fn(async () => ({ success: true })),
    showTaskNotification: vi.fn(async () => ({ success: true })),
    setTaskTrayStatus: vi.fn(),
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsTool: vi.fn(async () => ({ cancelled: true })),
    selectSettingsDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsColor: vi.fn(async () => ({ cancelled: true })),
    executeSettingsAction: vi.fn(async () => ({ success: true })),
    selectDataRootDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSitePackage: vi.fn(async () => ({ cancelled: true })),
    selectSiteExportDestination: vi.fn(async () => ({ cancelled: true })),
    restartBackend: vi.fn(async () => ({ success: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    downloadBackendResource: vi.fn(async () => ({ status: 'cancelled' as const })),
    executeFileDesktopAction: vi.fn(async () => ({ success: true })),
    listExternalTools: vi.fn(async () => ({ schema_version: 2 as const, categories: [], tools: [] })),
    selectExternalToolExecutable: vi.fn(async () => ({ cancelled: true })),
    selectExternalToolWorkingDirectory: vi.fn(async () => ({ cancelled: true })),
    selectExternalToolIcon: vi.fn(async () => ({ cancelled: true })),
    createExternalTool: vi.fn(async () => ({ success: true })),
    createExternalToolSystemReference: vi.fn(async () => ({ success: true })),
    updateExternalTool: vi.fn(async () => ({ success: true })),
    deleteExternalTool: vi.fn(async () => ({ success: true })),
    setExternalToolFavorite: vi.fn(async () => ({ success: true })),
    reorderExternalTools: vi.fn(async () => ({ success: true })),
    reorderExternalToolCategories: vi.fn(async () => ({ success: true })),
    createExternalToolCategory: vi.fn(async () => ({ success: true })),
    renameExternalToolCategory: vi.fn(async () => ({ success: true })),
    deleteExternalToolCategory: vi.fn(async () => ({ success: true })),
    launchExternalTool: vi.fn(async (request) => ({ success: true, toolId: request.toolId })),
    revealExternalTool: vi.fn(async (toolId: string) => ({ success: true, toolId })),
    refreshExternalToolStatuses: vi.fn(async () => ({ schema_version: 2 as const, categories: [], tools: [] })),
    openPath: vi.fn(async () => ({ success: true })),
    showItemInFolder: vi.fn(async () => ({ success: true })),
    openExternalUrl: vi.fn(async () => ({ success: true })),
    onBackendStatusChanged: vi.fn(() => () => undefined),
    reportRendererReady: vi.fn(),
  }
}

afterEach(() => {
  resetPlatformRuntimeForTests()
  vi.unstubAllGlobals()
})

describe('platform runtime', () => {
  it('resolves REST and WebSocket endpoints from the in-memory Electron config', async () => {
    vi.stubGlobal('window', {
      netconsoleDesktop: nativeBridge(),
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()

    expect(getRuntimeConfig()).toEqual({
      hostType: 'electron',
      apiBaseUrl: 'http://127.0.0.1:43123',
      apiToken: TOKEN,
    })
    expect(resolveApiUrl('/api/health')).toBe('http://127.0.0.1:43123/api/health')
    expect(resolveWebSocketUrl('/ws/tasks')).toBe('ws://127.0.0.1:43123/ws/tasks')
    expect(resolveFrontendAssetUrl('/desktop-renderer-build-meta.json')).toBe(
      'http://127.0.0.1:43123/desktop-renderer-build-meta.json',
    )
  })

  it('rebinds the Electron URL and token together after the backend becomes ready again', async () => {
    const tokenB = 'electron-restarted-token-abcdefghijklmnopqrstuvwxyz'
    let backendStatusListener: ((status: { state: 'starting' | 'ready' | 'stopped' | 'failed' }) => void) | undefined
    let resolveRuntimeB: ((runtime: { apiBaseUrl: string; apiToken: string }) => void) | undefined
    const bridge = nativeBridge()
    vi.mocked(bridge.getRuntimeConfig)
      .mockResolvedValueOnce({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: TOKEN })
      .mockReturnValueOnce(new Promise((resolve) => { resolveRuntimeB = resolve }))
    vi.mocked(bridge.onBackendStatusChanged).mockImplementation((listener) => {
      backendStatusListener = listener
      return () => undefined
    })
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()
    backendStatusListener?.({ state: 'starting' })
    backendStatusListener?.({ state: 'ready' })

    expect(backendStatusListener).toBeTypeOf('function')
    expect(getRuntimeConfig()).toMatchObject({
      apiBaseUrl: 'http://127.0.0.1:43123',
      apiToken: TOKEN,
    })
    resolveRuntimeB?.({ apiBaseUrl: 'http://127.0.0.1:43124', apiToken: tokenB })
    await vi.waitFor(() => expect(getRuntimeConfig()).toMatchObject({
      apiBaseUrl: 'http://127.0.0.1:43124',
      apiToken: tokenB,
    }))
  })

  it('keeps the last trusted Electron binding when a runtime rebind fails', async () => {
    let backendStatusListener: ((status: { state: 'starting' | 'ready' | 'stopped' | 'failed' }) => void) | undefined
    const bridge = nativeBridge()
    vi.mocked(bridge.getRuntimeConfig)
      .mockResolvedValueOnce({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: TOKEN })
      .mockRejectedValueOnce(new Error('runtime unavailable'))
    vi.mocked(bridge.onBackendStatusChanged).mockImplementation((listener) => {
      backendStatusListener = listener
      return () => undefined
    })
    const diagnostic = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()
    backendStatusListener?.({ state: 'ready' })
    await vi.waitFor(() => expect(diagnostic).toHaveBeenCalledWith(
      'PLATFORM_RUNTIME_REBIND_FAILED',
      expect.any(Object),
    ))

    expect(getRuntimeConfig()).toEqual({
      hostType: 'electron',
      apiBaseUrl: 'http://127.0.0.1:43123',
      apiToken: TOKEN,
    })
    expect(resolveApiUrl('/api/health')).toBe('http://127.0.0.1:43123/api/health')
    expect(diagnostic).toHaveBeenCalledWith('PLATFORM_RUNTIME_REBIND_FAILED', expect.objectContaining({
      host: 'electron',
      old_generation: 1,
    }))
    expect(JSON.stringify(diagnostic.mock.calls)).not.toContain(TOKEN)
    diagnostic.mockRestore()
  })

  it('retains relative browser URLs when no desktop bridge exists', async () => {
    vi.stubGlobal('window', {
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()

    expect(getRuntimeConfig().hostType).toBe('browser')
    expect(resolveApiUrl('/api/health')).toBe('/api/health')
    expect(resolveWebSocketUrl('/ws/tasks')).toBe('ws://127.0.0.1:5173/ws/tasks')
    expect(resolveFrontendAssetUrl('/desktop-renderer-build-meta.json')).toBe('/desktop-renderer-build-meta.json')
  })

  it('fails closed when Electron is expected but the preload bridge is missing', async () => {
    const click = vi.fn()
    vi.stubGlobal('window', {
      location: {
        origin: 'http://127.0.0.1:5173',
        protocol: 'http:',
        host: '127.0.0.1:5173',
        search: '?netconsole_host=electron',
      },
    })
    vi.stubGlobal('document', {
      body: { append: vi.fn() },
      createElement: vi.fn(() => ({ click })),
    })

    await expect(initializePlatformRuntime()).rejects.toThrow(
      'Electron 文件保存组件未加载，请完全退出 NetConsole 后重新启动。',
    )
    expect(click).not.toHaveBeenCalled()
    expect(() => downloadBackendResource({
      apiPath: '/api/device-management/exports/task-1/download',
      suggestedName: '设备表.csv',
    })).toThrow('Electron 文件保存组件未加载')
  })

  it('normalizes a trailing slash in the Electron runtime base URL', async () => {
    const bridge = nativeBridge()
    vi.mocked(bridge.getRuntimeConfig).mockResolvedValue({
      apiBaseUrl: 'http://127.0.0.1:43123/',
      apiToken: TOKEN,
    })
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()

    expect(resolveApiUrl('/api/health')).toBe('http://127.0.0.1:43123/api/health')
  })

  it('supports a root-relative browser API prefix without affecting Electron rules', () => {
    vi.stubGlobal('window', {
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })
    resetPlatformRuntimeForTests('/backend')

    expect(resolveApiUrl('/api/health')).toBe('/backend/api/health')
    expect(resolveWebSocketUrl('/ws/tasks')).toBe('ws://127.0.0.1:5173/backend/ws/tasks')
  })

  it('never falls back to relative API or WebSocket URLs while Electron config is pending', () => {
    const bridge = nativeBridge()
    resetPlatformRuntimeForTests('', false)
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    expect(() => resolveApiUrl('/api/health')).toThrow('尚未就绪')
    expect(() => resolveWebSocketUrl('/ws/tasks')).toThrow('尚未就绪')
    expect(() => resolveFrontendAssetUrl('/desktop-renderer-build-meta.json')).toThrow('尚未就绪')
    expect(() => downloadBackendResource({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'report.zip',
    })).toThrow('尚未就绪')
    expect(bridge.downloadBackendResource).not.toHaveBeenCalled()
  })
})
