import { afterEach, describe, expect, it, vi } from 'vitest'

import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import {
  getRuntimeConfig,
  initializePlatformRuntime,
  resetPlatformRuntimeForTests,
  resolveApiUrl,
  resolveWebSocketUrl,
} from './runtime'

const TOKEN = 'electron-test-token-abcdefghijklmnopqrstuvwxyz'

function nativeBridge(): NetConsoleDesktopBridge {
  return {
    getAppInfo: vi.fn(async () => ({ version: '1.3.8', platform: 'win32', isPackaged: false })),
    getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: 'http://127.0.0.1:43123' })),
    getRuntimeConfig: vi.fn(async () => ({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: TOKEN })),
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    openPath: vi.fn(async () => ({ success: true })),
    showItemInFolder: vi.fn(async () => ({ success: true })),
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
  })

  it('retains relative browser URLs when no desktop bridge exists', async () => {
    vi.stubGlobal('window', {
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })

    await initializePlatformRuntime()

    expect(getRuntimeConfig().hostType).toBe('browser')
    expect(resolveApiUrl('/api/health')).toBe('/api/health')
    expect(resolveWebSocketUrl('/ws/tasks')).toBe('ws://127.0.0.1:5173/ws/tasks')
  })
})
