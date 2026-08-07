import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, apiErrorDetail, apiRequest } from './client'
import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import { initializePlatformRuntime, resetPlatformRuntimeForTests } from '../platform/runtime'

describe('API client errors', () => {
  afterEach(() => {
    vi.useRealTimers()
    resetPlatformRuntimeForTests()
    vi.unstubAllGlobals()
  })

  it('normalizes network request diagnostics', () => {
    const detail = apiErrorDetail(new ApiRequestError(
      'Backend 连接中断，请重试。',
      0,
      'CONNECTION_RESET',
      {
        path: '/api/rail-transit/base-data/mrs',
        network_error: 'socket hang up',
      },
    ))

    expect(detail).toEqual({
      path: '/api/rail-transit/base-data/mrs',
      code: 'CONNECTION_RESET',
      status: 0,
      requestId: '',
      message: 'Backend 连接中断，请重试。',
      originalMessage: 'socket hang up',
    })
  })

  it('preserves HTTP request ids and original messages', () => {
    const detail = apiErrorDetail(new ApiRequestError(
      '服务暂时不可用',
      503,
      'SERVICE_UNAVAILABLE',
      {
        path: '/api/service',
        request_id: 'request-503',
        original_message: 'upstream reset',
      },
    ))

    expect(detail).toMatchObject({
      path: '/api/service',
      code: 'SERVICE_UNAVAILABLE',
      status: 503,
      requestId: 'request-503',
      originalMessage: 'upstream reset',
    })
  })

  it('normalizes unexpected errors with the fallback path', () => {
    expect(apiErrorDetail(new Error('unexpected'), '/api/fallback')).toEqual({
      path: '/api/fallback',
      code: 'UNEXPECTED_ERROR',
      status: 0,
      requestId: '',
      message: 'unexpected',
      originalMessage: 'unexpected',
    })
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
      code: 'AGENT_TIMEOUT',
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

  it('preserves structured device database error codes and messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        detail: {
          code: 'DEVICE_DATABASE_SCHEMA_NOT_READY',
          message: '设备数据库升级未完成，请重启后端或查看数据库迁移日志。',
          details: { operation: 'list_devices', site: 'line-one' },
        },
      }),
    }))
    await expect(apiRequest('/api/device-management/devices')).rejects.toMatchObject({
      message: '设备数据库升级未完成，请重启后端或查看数据库迁移日志。',
      status: 503,
      code: 'DEVICE_DATABASE_SCHEMA_NOT_READY',
      details: { operation: 'list_devices', site: 'line-one' },
    })
  })

  it('classifies fetch failures as an interrupted connection', async () => {
    const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(apiRequest('/api/rail-transit/mesh-analysis/import-context/prepare')).rejects.toEqual(
      expect.objectContaining({
        message: 'Backend 连接中断，请重试。',
        status: 0,
        code: 'BACKEND_CONNECTION_INTERRUPTED',
      }),
    )
    expect(diagnostic).toHaveBeenCalledWith('API_REQUEST_NETWORK_FAILED', {
      path: '/api/rail-transit/mesh-analysis/import-context/prepare',
      error: 'Failed to fetch',
    })
    diagnostic.mockRestore()
  })

  it('classifies response body read failures without calling Backend unreachable', async () => {
    const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => { throw new TypeError('terminated') },
    }))

    await expect(apiRequest('/api/health')).rejects.toMatchObject({
      message: 'Backend 返回内容读取中断，请重试。',
      status: 200,
      code: 'RESPONSE_BODY_FAILED',
    })
    expect(diagnostic).toHaveBeenCalledWith('API_RESPONSE_BODY_FAILED', {
      path: '/api/health',
      status: 200,
      error: 'terminated',
    })
    diagnostic.mockRestore()
  })

  it('classifies invalid successful JSON responses separately', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => '{"incomplete":',
    }))

    await expect(apiRequest('/api/health')).rejects.toMatchObject({
      message: 'Backend 返回内容不完整，请重试。',
      status: 200,
      code: 'INVALID_JSON_RESPONSE',
    })
  })

  it('keeps AbortError cancellable without translating it to a load error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')))

    await expect(apiRequest('/api/health')).rejects.toMatchObject({
      name: 'AbortError',
      code: 'REQUEST_ABORTED',
    })
  })

  it.each([
    ['socket hang up: connection reset', 'CONNECTION_RESET'],
    ['request timed out', 'RAW_QUERY_TIMEOUT'],
    ['backend restarted while waiting', 'BACKEND_RESTARTED'],
  ])('classifies recognizable network signals: %s', async (message, code) => {
    const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError(message)))

    await expect(apiRequest('/api/query')).rejects.toMatchObject({ code })
    diagnostic.mockRestore()
  })

  it('retries one failed GET transport request and returns the recovered response', async () => {
    const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection reset'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest('/api/recoverable-query')).resolves.toEqual({ status: 'ok' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(diagnostic).not.toHaveBeenCalled()
    diagnostic.mockRestore()
  })

  it('rebinds a failed Electron GET to the new URL and session token before retrying', async () => {
    const tokenA = 'electron-runtime-a-token-abcdefghijklmnopqrstuvwxyz'
    const tokenB = 'electron-runtime-b-token-abcdefghijklmnopqrstuvwxyz'
    const bridge = {
      getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: 'http://127.0.0.1:43124' })),
      getRuntimeConfig: vi.fn()
        .mockResolvedValueOnce({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: tokenA })
        .mockResolvedValueOnce({ apiBaseUrl: 'http://127.0.0.1:43124', apiToken: tokenB }),
      onBackendStatusChanged: vi.fn(() => () => undefined),
    } as unknown as NetConsoleDesktopBridge
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ recovered: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    await initializePlatformRuntime()

    await expect(apiRequest('/api/rail-transit/trackside-ap-business/export/proposal'))
      .resolves.toEqual({ recovered: true })

    expect(bridge.getRuntimeConfig).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      'http://127.0.0.1:43123/api/rail-transit/trackside-ap-business/export/proposal',
      'http://127.0.0.1:43124/api/rail-transit/trackside-ap-business/export/proposal',
    ])
    expect(fetchMock.mock.calls.map((call) => (
      new Headers((call[1] as RequestInit).headers).get('X-NetConsole-Session')
    ))).toEqual([tokenA, tokenB])
  })

  it('waits for supervisor ready before rebinding and retrying an Electron GET', async () => {
    const tokenA = 'electron-runtime-a-token-abcdefghijklmnopqrstuvwxyz'
    const tokenB = 'electron-runtime-b-token-abcdefghijklmnopqrstuvwxyz'
    let backendStatusListener: ((status: { state: 'starting' | 'ready'; baseUrl?: string }) => void) | undefined
    const bridge = {
      getBackendStatus: vi.fn(async () => ({ state: 'starting' as const })),
      getRuntimeConfig: vi.fn()
        .mockResolvedValueOnce({ apiBaseUrl: 'http://127.0.0.1:43123', apiToken: tokenA })
        .mockResolvedValueOnce({ apiBaseUrl: 'http://127.0.0.1:43124', apiToken: tokenB }),
      onBackendStatusChanged: vi.fn((listener) => {
        backendStatusListener = listener
        return () => undefined
      }),
    } as unknown as NetConsoleDesktopBridge
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('backend restarted while waiting'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ recovered: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    await initializePlatformRuntime()

    const request = apiRequest('/api/rail-transit/trackside-ap-business/export/proposal')
    await vi.waitFor(() => expect(bridge.getBackendStatus).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledOnce()

    backendStatusListener?.({ state: 'ready', baseUrl: 'http://127.0.0.1:43124' })
    await expect(request).resolves.toEqual({ recovered: true })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      'http://127.0.0.1:43123/api/rail-transit/trackside-ap-business/export/proposal',
      'http://127.0.0.1:43124/api/rail-transit/trackside-ap-business/export/proposal',
    ])
    expect(fetchMock.mock.calls.map((call) => (
      new Headers((call[1] as RequestInit).headers).get('X-NetConsole-Session')
    ))).toEqual([tokenA, tokenB])
  })

  it('does not rebind and replay an Electron export POST after an interrupted response', async () => {
    const bridge = {
      getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: 'http://127.0.0.1:43124' })),
      getRuntimeConfig: vi.fn()
        .mockResolvedValueOnce({
          apiBaseUrl: 'http://127.0.0.1:43123',
          apiToken: 'electron-runtime-a-token-abcdefghijklmnopqrstuvwxyz',
        })
        .mockResolvedValueOnce({
          apiBaseUrl: 'http://127.0.0.1:43124',
          apiToken: 'electron-runtime-b-token-abcdefghijklmnopqrstuvwxyz',
        }),
      onBackendStatusChanged: vi.fn(() => () => undefined),
    } as unknown as NetConsoleDesktopBridge
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    await initializePlatformRuntime()

    await expect(apiRequest('/api/rail-transit/trackside-ap-business/export', {
      method: 'POST',
      body: JSON.stringify({ expected_revision: 'a'.repeat(64) }),
    })).rejects.toMatchObject({ code: 'BACKEND_CONNECTION_INTERRUPTED' })

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(bridge.getRuntimeConfig).toHaveBeenCalledOnce()
    diagnostic.mockRestore()
  })

  it('returns REQUEST_TIMEOUT without retrying the timed out GET', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: RequestInfo | URL, request?: RequestInit) => new Promise((_resolve, reject) => {
      request?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    vi.stubGlobal('fetch', fetchMock)

    const rejection = expect(apiRequest('/api/slow-query')).rejects.toMatchObject({
      name: 'ApiRequestError',
      code: 'REQUEST_TIMEOUT',
      status: 0,
      details: {
        path: '/api/slow-query',
        timeout_ms: 15_000,
      },
    })
    await vi.advanceTimersByTimeAsync(15_000)

    await rejection
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('supports a local heavy-query timeout without changing the 15 second default', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: RequestInfo | URL, request?: RequestInit) => new Promise((_resolve, reject) => {
      request?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    vi.stubGlobal('fetch', fetchMock)

    const rejection = expect(apiRequest('/api/heavy-query', { queryTimeoutMs: 30_000 })).rejects.toMatchObject({
      code: 'REQUEST_TIMEOUT',
      details: {
        path: '/api/heavy-query',
        timeout_ms: 30_000,
      },
    })
    await vi.advanceTimersByTimeAsync(29_999)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await rejection
  })

  it('deduplicates concurrent GET requests for the same path', async () => {
    let resolveFetch: ((value: Response) => void) | undefined
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => {
      resolveFetch = resolve
    }))
    vi.stubGlobal('fetch', fetchMock)

    const first = apiRequest('/api/shared-query')
    const second = apiRequest('/api/shared-query')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    resolveFetch?.(new Response(JSON.stringify({ value: 1 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(Promise.all([first, second])).resolves.toEqual([
      { value: 1 },
      { value: 1 },
    ])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([502, 503, 504])('retries transient HTTP %s once for GET requests', async (status) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ recovered: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest('/api/transient-http')).resolves.toEqual({ recovered: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('preserves the original HTTP error when Electron rebind fails before a GET retry', async () => {
    const bridge = {
      getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: 'http://127.0.0.1:43124' })),
      getRuntimeConfig: vi.fn()
        .mockResolvedValueOnce({
          apiBaseUrl: 'http://127.0.0.1:43123',
          apiToken: 'electron-runtime-a-token-abcdefghijklmnopqrstuvwxyz',
        })
        .mockRejectedValueOnce(new Error('internal runtime path and token details')),
      onBackendStatusChanged: vi.fn(() => () => undefined),
    } as unknown as NetConsoleDesktopBridge
    vi.stubGlobal('window', {
      netconsoleDesktop: bridge,
      location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '暂时不可用' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await initializePlatformRuntime()

    await expect(apiRequest('/api/recoverable-query')).rejects.toMatchObject({
      status: 503,
      message: '暂时不可用',
    })

    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it.each([
    ['POST', '/api/tasks', JSON.stringify({ type: 'COLLECT' })],
    ['POST', '/api/import', new FormData()],
    ['PUT', '/api/resource/1', JSON.stringify({ enabled: true })],
    ['PATCH', '/api/resource/1', JSON.stringify({ name: 'updated' })],
    ['DELETE', '/api/resource/1', undefined],
  ])('does not retry %s request failures for %s', async (method, path, body) => {
    const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest(path, { method, body })).rejects.toMatchObject({
      code: 'BACKEND_CONNECTION_INTERRUPTED',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    diagnostic.mockRestore()
  })

  it('does not retry an externally aborted GET and preserves AbortError semantics', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn((_url: RequestInfo | URL, request?: RequestInit) => new Promise((_resolve, reject) => {
      request?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    vi.stubGlobal('fetch', fetchMock)

    const rejection = expect(apiRequest('/api/cancellable-query', { signal: controller.signal })).rejects.toMatchObject({
      name: 'AbortError',
      code: 'REQUEST_ABORTED',
    })
    controller.abort()

    await rejection
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retries HEAD queries and does not parse a successful response body', async () => {
    const text = vi.fn()
    const json = vi.fn()
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection reset'))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text,
        json,
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest('/api/readiness', { method: 'HEAD' })).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(text).not.toHaveBeenCalled()
    expect(json).not.toHaveBeenCalled()
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
