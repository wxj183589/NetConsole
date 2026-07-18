import { afterEach, describe, expect, it, vi } from 'vitest'

import { createBrowserAdapter } from './browser-adapter'

afterEach(() => vi.unstubAllGlobals())

describe('browser platform adapter', () => {
  it('keeps browser mode independent and returns safe desktop fallbacks', async () => {
    const adapter = createBrowserAdapter('/backend/')

    expect(await adapter.getRuntimeConfig()).toEqual({ apiBaseUrl: '/backend', apiToken: '' })
    expect(await adapter.selectFile()).toEqual({ cancelled: true, paths: [] })
    expect(await adapter.selectDirectory()).toEqual({ cancelled: true })
    expect(await adapter.chooseSavePath({ suggestedName: 'report.xlsx' })).toEqual({ cancelled: true })
    await expect(adapter.openTaskWindow({ taskId: 'task-1' })).resolves.toMatchObject({ success: false })
    await expect(adapter.openPath('C:\\report.xlsx')).resolves.toMatchObject({ success: false })
  })

  it('establishes an authenticated loopback development session without logging the token', async () => {
    const token = 'browser-development-token-abcdefghijklmnopqrstuvwxyz'
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = []
    const fetchMock = vi.fn(async (url: RequestInfo | URL, request?: RequestInit) => {
      calls.push([url, request])
      return new Response(null, { status: 204 })
    }) as typeof fetch
    vi.stubGlobal('fetch', fetchMock)
    const adapter = createBrowserAdapter('http://127.0.0.1:8000/', token)

    await expect(adapter.getRuntimeConfig()).resolves.toEqual({
      apiBaseUrl: 'http://127.0.0.1:8000',
      apiToken: token,
    })
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, request] = calls[0]!
    expect(url).toBe('http://127.0.0.1:8000/api/dev/session')
    expect(request?.credentials).toBe('include')
    expect(new Headers(request?.headers).get('X-NetConsole-Session')).toBe(token)
  })

  it('rejects malformed development tokens before any request', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    expect(() => createBrowserAdapter('http://127.0.0.1:8000', 'short')).toThrow(
      '开发会话令牌格式无效',
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    'http://0.0.0.0:8000',
    'http://192.0.2.10:8000',
    'https://127.0.0.1:8000',
    '/backend',
  ])('never sends a development token to an unsafe API origin: %s', (apiBaseUrl) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    expect(() => createBrowserAdapter(
      apiBaseUrl,
      'browser-development-token-abcdefghijklmnopqrstuvwxyz',
    )).toThrow('开发 API 必须使用 127.0.0.1 回环地址')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('starts a browser download through the default Vite proxy path', async () => {
    const click = vi.fn()
    const remove = vi.fn()
    const append = vi.fn()
    const anchor = { href: '', download: '', hidden: false, click, remove }
    vi.stubGlobal('document', {
      body: { append },
      createElement: vi.fn(() => anchor),
    })
    const adapter = createBrowserAdapter()

    await expect(adapter.downloadBackendResource({
      apiPath: '/api/file-management/downloads/task-1/file',
      query: { site_id: 'demo' },
      suggestedName: 'report.zip',
    })).resolves.toEqual({ status: 'started' })

    expect(anchor.href).toBe('/api/file-management/downloads/task-1/file?site_id=demo')
    expect(anchor.download).toBe('report.zip')
    expect(click).toHaveBeenCalledOnce()
    expect(remove).toHaveBeenCalledOnce()
  })

  it('supports an explicitly configured root-relative browser API prefix', async () => {
    const anchor = { href: '', download: '', hidden: false, click: vi.fn(), remove: vi.fn() }
    vi.stubGlobal('document', {
      body: { append: vi.fn() },
      createElement: vi.fn(() => anchor),
    })
    const adapter = createBrowserAdapter('/backend/')

    await adapter.downloadBackendResource({
      apiPath: '/api/config-collection/artifacts/artifact-1',
      suggestedName: 'config.txt',
    })

    expect(anchor.href).toBe('/backend/api/config-collection/artifacts/artifact-1')
  })

  it('rejects unsafe browser download paths before creating an anchor', async () => {
    const createElement = vi.fn()
    vi.stubGlobal('document', { body: { append: vi.fn() }, createElement })

    await expect(createBrowserAdapter().downloadBackendResource({
      apiPath: '/api/../private',
      suggestedName: 'report.zip',
    })).rejects.toThrow('safe relative /api path')
    expect(createElement).not.toHaveBeenCalled()
  })
})
