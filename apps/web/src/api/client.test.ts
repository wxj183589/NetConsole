import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from './client'
import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import { initializePlatformRuntime, resetPlatformRuntimeForTests } from '../platform/runtime'

describe('API client errors', () => {
  afterEach(() => {
    resetPlatformRuntimeForTests()
    vi.unstubAllGlobals()
  })

  it('shows standardized backend message without exposing stack details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ ok: false, error: { code: 'AGENT_TIMEOUT', message: '连接 Agent 超时' } }),
    }))
    await expect(apiRequest('/api/agents/probe')).rejects.toMatchObject({
      message: '连接 Agent 超时',
      status: 502,
    })
  })

  it('leaves multipart content type to the browser so the boundary is preserved', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const body = new FormData()
    body.append('file', 'preview')

    await apiRequest('/api/rail-transit/base-data/import-preview', { method: 'POST', body })

    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.has('Content-Type')).toBe(false)
  })

  it('uses structured FastAPI detail messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: { code: 'BASE_DATA_WRITE_DISABLED', message: '基础资料写入未启用' } }),
    }))
    await expect(apiRequest('/api/rail-transit/base-data/import-apply')).rejects.toThrow('基础资料写入未启用')
  })

  it('uses the ephemeral Electron URL and header without changing browser call sites', async () => {
    const token = 'electron-test-token-abcdefghijklmnopqrstuvwxyz'
    const bridge = {
      getRuntimeConfig: vi.fn(async () => ({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: token })),
      getAppInfo: vi.fn(),
      getBackendStatus: vi.fn(),
      selectFile: vi.fn(),
      selectDirectory: vi.fn(),
      chooseSavePath: vi.fn(),
      openPath: vi.fn(),
      showItemInFolder: vi.fn(),
      onBackendStatusChanged: vi.fn(),
      reportRendererReady: vi.fn(),
    } as unknown as NetConsoleDesktopBridge
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })
    const fetchCalls: Array<[RequestInfo | URL, RequestInit | undefined]> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, request?: RequestInit) => {
      fetchCalls.push([input, request])
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    await initializePlatformRuntime()

    await apiRequest('/api/health')

    expect(fetchCalls[0][0]).toBe('http://127.0.0.1:43123/api/health')
    const request = fetchCalls[0][1] as RequestInit
    expect(new Headers(request.headers).get('X-NetConsole-Session')).toBe(token)
    expect(request.credentials).toBe('include')
  })
})
