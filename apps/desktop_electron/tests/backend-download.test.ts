import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { BackendDownloadManager } from '../src/main/backend-download'
import { GrantedPathRegistry } from '../src/main/path-access'
import { DESKTOP_SESSION_HEADER } from '../src/shared/bridge'

const cleanup: Array<() => Promise<void>> = []

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(cleanup.splice(0).map((callback) => callback()))
})

describe('backend download manager', () => {
  it('streams from the managed non-8000 backend with the header token', async () => {
    const token = 'download-test-token-abcdefghijklmnopqrstuvwxyz'
    let requestUrl = ''
    let requestToken = ''
    const server = await loopbackServer((request, response) => {
      requestUrl = request.url || ''
      requestToken = String(request.headers[DESKTOP_SESSION_HEADER.toLowerCase()] || '')
      response.writeHead(200, { 'Content-Type': 'application/zip' })
      response.write('first-')
      response.end('second')
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'result.zip')
    const window = { loadURL: vi.fn() }
    const manager = downloadManager(server.origin, token, target, window)

    const result = await manager.download({
      apiPath: '/api/file-management/downloads/task-1/file',
      query: { site_id: '宁波地铁10号线' },
      suggestedName: 'result.zip',
    })

    expect(new URL(server.origin).port).not.toBe('8000')
    expect(requestUrl).toBe('/api/file-management/downloads/task-1/file?site_id=%E5%AE%81%E6%B3%A2%E5%9C%B0%E9%93%8110%E5%8F%B7%E7%BA%BF')
    expect(requestUrl).not.toContain(token)
    expect(requestToken).toBe(token)
    expect(result).toEqual({ status: 'saved', savedPath: target })
    await expect(readFile(target, 'utf8')).resolves.toBe('first-second')
    expect((await readdir(directory)).some((name) => name.endsWith('.part'))).toBe(false)
    expect(window.loadURL).not.toHaveBeenCalled()
  })

  it('returns cancelled without contacting the backend', async () => {
    const fetchImpl = vi.fn<typeof fetch>()
    const manager = new BackendDownloadManager({
      backend: { getRuntimeInfo: () => ({ baseUrl: 'http://127.0.0.1:43123', apiToken: 'x'.repeat(48) }) },
      dialog: { showSaveDialog: vi.fn(async () => ({ canceled: true })) },
      window: {},
      pathRegistry: new GrantedPathRegistry(),
      fetchImpl,
    })

    await expect(manager.download({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'result.zip',
    })).resolves.toEqual({ status: 'cancelled' })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('preserves an existing target when HTTP fails', async () => {
    const server = await loopbackServer((_request, response) => {
      response.writeHead(503)
      response.end('unavailable')
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'existing.zip')
    await writeFile(target, 'original', 'utf8')
    const manager = downloadManager(server.origin, 'y'.repeat(48), target)

    const result = await manager.download({
      apiPath: '/api/file-management/downloads/task-2/file',
      suggestedName: 'existing.zip',
    })

    expect(result.status).toBe('failed')
    await expect(readFile(target, 'utf8')).resolves.toBe('original')
    expect((await readdir(directory)).some((name) => name.endsWith('.part'))).toBe(false)
  })

  it('atomically replaces an existing target only after a successful stream', async () => {
    const server = await loopbackServer((_request, response) => {
      response.writeHead(200)
      response.end('replacement')
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'existing.zip')
    await writeFile(target, 'original', 'utf8')
    const manager = downloadManager(server.origin, 'r'.repeat(48), target)

    const result = await manager.download({
      apiPath: '/api/file-management/downloads/task-replace/file',
      suggestedName: 'existing.zip',
    })

    expect(result.status).toBe('saved')
    await expect(readFile(target, 'utf8')).resolves.toBe('replacement')
    expect((await readdir(directory)).some((name) => name.endsWith('.part'))).toBe(false)
  })

  it('allows only one active download for the same final path', async () => {
    let finishResponse: (() => void) | undefined
    let requestCount = 0
    let markRequestStarted: (() => void) | undefined
    const requestStarted = new Promise<void>((resolvePromise) => {
      markRequestStarted = resolvePromise
    })
    const server = await loopbackServer((_request, response) => {
      requestCount += 1
      response.writeHead(200)
      response.write('first')
      finishResponse = () => response.end('-complete')
      markRequestStarted?.()
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'same-target.zip')
    const manager = downloadManager(server.origin, 'l'.repeat(48), target)

    const first = manager.download({
      apiPath: '/api/file-management/downloads/task-first/file',
      suggestedName: 'same-target.zip',
    })
    await requestStarted
    await expect(manager.download({
      apiPath: '/api/file-management/downloads/task-second/file',
      suggestedName: 'same-target.zip',
    })).resolves.toEqual({ status: 'failed', error: '该目标文件已有下载正在进行。' })
    finishResponse?.()

    await expect(first).resolves.toMatchObject({ status: 'saved' })
    expect(requestCount).toBe(1)
    await expect(readFile(target, 'utf8')).resolves.toBe('first-complete')
  })

  it('removes the temporary file when the response stream is interrupted', async () => {
    const server = await loopbackServer((_request, response) => {
      response.writeHead(200, { 'Content-Length': '1000' })
      response.write('partial')
      setTimeout(() => response.destroy(), 10)
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'interrupted.zip')
    const manager = downloadManager(server.origin, 'z'.repeat(48), target)

    const result = await manager.download({
      apiPath: '/api/file-management/downloads/task-3/file',
      suggestedName: 'interrupted.zip',
    })

    expect(result.status).toBe('failed')
    await expect(readFile(target)).rejects.toThrow()
    expect((await readdir(directory)).some((name) => name.endsWith('.part'))).toBe(false)
  })

  it('aborts active downloads and removes partial files during desktop shutdown', async () => {
    let markRequestStarted: (() => void) | undefined
    const requestStarted = new Promise<void>((resolvePromise) => {
      markRequestStarted = resolvePromise
    })
    const server = await loopbackServer((_request, response) => {
      response.writeHead(200)
      response.write('partial')
      markRequestStarted?.()
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'shutdown.zip')
    const manager = downloadManager(server.origin, 's'.repeat(48), target)

    const download = manager.download({
      apiPath: '/api/file-management/downloads/task-shutdown/file',
      suggestedName: 'shutdown.zip',
    })
    await requestStarted
    await manager.shutdown()

    await expect(download).resolves.toMatchObject({ status: 'failed' })
    await expect(readFile(target)).rejects.toThrow()
    expect((await readdir(directory)).some((name) => name.endsWith('.part'))).toBe(false)
    await expect(manager.download({
      apiPath: '/api/file-management/downloads/after-shutdown/file',
      suggestedName: 'after-shutdown.zip',
    })).resolves.toMatchObject({ status: 'failed' })
  })

  it('does not start a download when shutdown begins while the save dialog is open', async () => {
    const directory = await tempDirectory()
    const target = resolve(directory, 'pending-dialog.zip')
    const fetchImpl = vi.fn<typeof fetch>()
    let finishDialog: ((value: { canceled: boolean; filePath?: string }) => void) | undefined
    const dialogResult = new Promise<{ canceled: boolean; filePath?: string }>((resolvePromise) => {
      finishDialog = resolvePromise
    })
    const manager = new BackendDownloadManager({
      backend: { getRuntimeInfo: () => ({ baseUrl: 'http://127.0.0.1:43123', apiToken: 'p'.repeat(48) }) },
      dialog: { showSaveDialog: vi.fn(() => dialogResult) },
      window: {},
      pathRegistry: new GrantedPathRegistry(),
      fetchImpl,
    })

    const download = manager.download({
      apiPath: '/api/file-management/downloads/task-pending-dialog/file',
      suggestedName: 'pending-dialog.zip',
    })
    await Promise.resolve()
    await manager.shutdown()
    finishDialog?.({ canceled: false, filePath: target })

    await expect(download).resolves.toMatchObject({ status: 'failed' })
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(await readdir(directory)).toEqual([])
  })

  it('rejects non-API paths before opening a dialog', async () => {
    const dialog = { showSaveDialog: vi.fn() }
    const manager = new BackendDownloadManager({
      backend: { getRuntimeInfo: () => ({ baseUrl: 'https://example.com', apiToken: 'x'.repeat(48) }) },
      dialog,
      window: {},
      pathRegistry: new GrantedPathRegistry(),
    })

    await expect(manager.download({
      apiPath: 'https://example.com/report.zip',
      suggestedName: 'report.zip',
    })).rejects.toThrow('safe relative /api path')
    expect(dialog.showSaveDialog).not.toHaveBeenCalled()
  })

  it('rejects an untrusted runtime origin before making a request', async () => {
    const directory = await tempDirectory()
    const target = resolve(directory, 'result.zip')
    const fetchImpl = vi.fn<typeof fetch>()
    const manager = new BackendDownloadManager({
      backend: { getRuntimeInfo: () => ({ baseUrl: 'https://example.com', apiToken: 'x'.repeat(48) }) },
      dialog: { showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: target })) },
      window: {},
      pathRegistry: new GrantedPathRegistry(),
      fetchImpl,
    })

    await expect(manager.download({
      apiPath: '/api/file-management/downloads/task-untrusted/file',
      suggestedName: 'result.zip',
    })).resolves.toMatchObject({ status: 'failed' })
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(await readdir(directory)).toEqual([])
  })

  it('rejects backend redirects without replacing an existing target', async () => {
    const server = await loopbackServer((_request, response) => {
      response.writeHead(302, { Location: 'https://example.com/report.zip' })
      response.end()
    })
    const directory = await tempDirectory()
    const target = resolve(directory, 'existing.zip')
    await writeFile(target, 'original', 'utf8')
    const manager = downloadManager(server.origin, 'd'.repeat(48), target)

    await expect(manager.download({
      apiPath: '/api/file-management/downloads/task-redirect/file',
      suggestedName: 'existing.zip',
    })).resolves.toMatchObject({ status: 'failed' })
    await expect(readFile(target, 'utf8')).resolves.toBe('original')
    expect((await readdir(directory)).some((name) => name.endsWith('.part'))).toBe(false)
  })

  it('never accepts sensitive query fields or the active runtime token in a URL', async () => {
    const token = 'runtime-download-token-' + 'x'.repeat(32)
    const fetchImpl = vi.fn<typeof fetch>()
    const directory = await tempDirectory()
    const target = resolve(directory, 'result.zip')
    const manager = new BackendDownloadManager({
      backend: { getRuntimeInfo: () => ({ baseUrl: 'http://127.0.0.1:43123', apiToken: token }) },
      dialog: { showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: target })) },
      window: {},
      pathRegistry: new GrantedPathRegistry(),
      fetchImpl,
    })

    await expect(manager.download({
      apiPath: '/api/file-management/downloads/task-4/file',
      query: { api_token: 'attempt' },
      suggestedName: 'result.zip',
    })).rejects.toThrow('download query key is invalid')
    await expect(manager.download({
      apiPath: '/api/file-management/downloads/task-4/file',
      query: { site_id: token },
      suggestedName: 'result.zip',
    })).resolves.toMatchObject({ status: 'failed' })
    await expect(manager.download({
      apiPath: `/api/file-management/downloads/${token}/file`,
      suggestedName: 'result.zip',
    })).resolves.toMatchObject({ status: 'failed' })
    const encodedToken = [...token]
      .map((character) => `%${character.charCodeAt(0).toString(16).padStart(2, '0')}`)
      .join('')
    await expect(manager.download({
      apiPath: `/api/file-management/downloads/${encodedToken}/file`,
      suggestedName: 'result.zip',
    })).resolves.toMatchObject({ status: 'failed' })
    expect(fetchImpl).not.toHaveBeenCalled()
  })
})

function downloadManager(
  origin: string,
  token: string,
  target: string,
  window: unknown = {},
): BackendDownloadManager {
  return new BackendDownloadManager({
    backend: { getRuntimeInfo: () => ({ baseUrl: origin, apiToken: token }) },
    dialog: { showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: target })) },
    window,
    pathRegistry: new GrantedPathRegistry(),
    createTempId: () => 'test-download',
  })
}

async function tempDirectory(): Promise<string> {
  const directory = await mkdtemp(resolve(tmpdir(), 'netconsole-download-test-'))
  cleanup.push(() => rm(directory, { recursive: true, force: true }))
  return directory
}

async function loopbackServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void,
): Promise<{ origin: string }> {
  const server = createServer(handler)
  await new Promise<void>((resolvePromise, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolvePromise)
  })
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('loopback test server did not bind')
  if (address.port === 8000) {
    await new Promise<void>((resolvePromise) => server.close(() => resolvePromise()))
    return loopbackServer(handler)
  }
  cleanup.push(() => new Promise<void>((resolvePromise) => server.close(() => resolvePromise())))
  return { origin: `http://127.0.0.1:${address.port}` }
}
