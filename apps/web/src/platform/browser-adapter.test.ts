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
    await expect(adapter.openPath('C:\\report.xlsx')).resolves.toMatchObject({ success: false })
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
