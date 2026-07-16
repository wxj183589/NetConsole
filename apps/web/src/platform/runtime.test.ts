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
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    downloadBackendResource: vi.fn(async () => ({ status: 'cancelled' as const })),
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
    expect(resolveFrontendAssetUrl('/web-build-meta.json')).toBe(
      'http://127.0.0.1:43123/web-build-meta.json',
    )
  })

  it('retains relative browser URLs when no desktop bridge exists', async () => {
    vi.stubGlobal('window', {
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()

    expect(getRuntimeConfig().hostType).toBe('browser')
    expect(resolveApiUrl('/api/health')).toBe('/api/health')
    expect(resolveWebSocketUrl('/ws/tasks')).toBe('ws://127.0.0.1:5173/ws/tasks')
    expect(resolveFrontendAssetUrl('/web-build-meta.json')).toBe('/web-build-meta.json')
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
    expect(() => resolveFrontendAssetUrl('/web-build-meta.json')).toThrow('尚未就绪')
    expect(() => downloadBackendResource({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'report.zip',
    })).toThrow('尚未就绪')
    expect(bridge.downloadBackendResource).not.toHaveBeenCalled()
  })
})
