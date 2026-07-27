import { createHash } from 'node:crypto'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { mkdir, mkdtemp, readFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, isAbsolute, resolve } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { registerDesktopIpc } from '../src/main/ipc'
import { GrantedPathRegistry } from '../src/main/path-access'
import { createDesktopBridge, type IpcRendererLike } from '../src/preload/bridge'
import { DESKTOP_IPC } from '../src/shared/bridge'

class FakeIpcMain {
  readonly handlers = new Map<string, (event: { sender: unknown }, value?: unknown) => unknown>()

  handle(channel: string, listener: (event: { sender: unknown }, value?: unknown) => unknown): void {
    this.handlers.set(channel, listener)
  }

  removeHandler(channel: string): void {
    this.handlers.delete(channel)
  }

  on(): void {}
}

const cleanup: Array<() => Promise<void>> = []

afterEach(async () => {
  await Promise.all(cleanup.splice(0).map((callback) => callback()))
})

describe('artifact save bridge integration', () => {
  it('writes and verifies a real file through Preload bridge, Main IPC and download manager', async () => {
    const content = Buffer.from('\uFEFF名称,厂商\r\nAC-1,H3C\r\nSW-1,ZTE\r\n', 'utf8')
    const sha256 = createHash('sha256').update(content).digest('hex')
    const server = await loopbackServer((_request, response) => {
      response.writeHead(200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Length': String(content.byteLength),
      })
      response.end(content)
    })
    cleanup.push(server.close)

    const configuredTarget = process.env.NETCONSOLE_ARTIFACT_ACCEPTANCE_PATH?.trim()
    const testDirectory = configuredTarget
      ? dirname(configuredTarget)
      : await mkdtemp(resolve(tmpdir(), 'netconsole-artifact-save-integration-'))
    if (!configuredTarget) cleanup.push(() => rm(testDirectory, { recursive: true, force: true }))
    const target = configuredTarget || resolve(testDirectory, '设备表.csv')
    if (!isAbsolute(target)) throw new Error('NETCONSOLE_ARTIFACT_ACCEPTANCE_PATH must be absolute')
    await mkdir(dirname(target), { recursive: true })

    const ipcMain = new FakeIpcMain()
    const sender = {}
    const parentWindow = {
      id: 23,
      isDestroyed: () => false,
      isMinimized: () => false,
      isVisible: () => true,
      isFocused: () => true,
      focus: vi.fn(),
    }
    const shell = {
      openPath: vi.fn(async () => ''),
      showItemInFolder: vi.fn(),
      openExternal: vi.fn(async () => undefined),
    }
    const logger = vi.fn()
    const registration = registerDesktopIpc({
      ipcMain,
      dialog: {
        showOpenDialog: vi.fn(async () => ({ canceled: true, filePaths: [] })),
        showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: target })),
        showMessageBox: vi.fn(async () => ({ response: 1 })),
      },
      shell,
      window: parentWindow,
      windowForEvent: () => parentWindow,
      appInfo: { version: '1.4.3', platform: 'win32', isPackaged: false },
      backend: {
        getStatus: () => ({ state: 'ready', baseUrl: server.origin }),
        getRuntimeInfo: () => ({ baseUrl: server.origin, apiToken: 'integration-token-' + 'x'.repeat(32) }),
      },
      pathRegistry: new GrantedPathRegistry(),
      isTrustedSender: (event) => event.sender === sender,
      logger,
    })
    cleanup.push(() => registration.shutdown())

    const ipcRenderer: IpcRendererLike = {
      invoke: async (channel, value) => {
        const handler = ipcMain.handlers.get(channel)
        if (!handler) throw new Error(`missing IPC handler: ${channel}`)
        return handler({ sender }, value)
      },
      send: vi.fn(),
      on: vi.fn(),
      removeListener: vi.fn(),
    }
    const bridge = createDesktopBridge(ipcRenderer)

    const result = await bridge.downloadBackendResource({
      apiPath: '/api/device-management/exports/integration-task/download',
      query: { artifact_id: 'integration-artifact' },
      suggestedName: basename(target),
      expectedSizeBytes: content.byteLength,
      expectedSha256: sha256,
    })

    expect(result).toMatchObject({
      status: 'saved',
      fileName: basename(target),
      directoryLabel: '用户选择的目录',
      sizeBytes: content.byteLength,
      sha256,
      capabilityId: expect.stringMatching(/^[0-9a-f-]{36}$/),
    })
    expect(await readFile(target)).toEqual(content)
    expect((await readdir(dirname(target))).some((name) => name.endsWith('.part'))).toBe(false)
    expect(result.capabilityId).toBeTruthy()
    await expect(bridge.openPath(result.capabilityId!)).resolves.toEqual({ success: true })
    await expect(bridge.showItemInFolder(result.capabilityId!)).resolves.toEqual({ success: true })
    expect(shell.openPath).toHaveBeenCalledWith(target)
    expect(shell.showItemInFolder).toHaveBeenCalledWith(target)
    expect(logger).toHaveBeenCalledWith(
      'ARTIFACT_LOCAL_FILE_COMMITTED',
      expect.stringContaining(`file=${basename(target)}`),
    )
    expect(JSON.stringify(logger.mock.calls)).not.toContain(server.token)
    expect(JSON.stringify(logger.mock.calls)).not.toContain(dirname(target))
  })
})

async function loopbackServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void,
): Promise<{ origin: string; token: string; close(): Promise<void> }> {
  const server = createServer(handler)
  await new Promise<void>((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('loopback server address unavailable')
  return {
    origin: `http://127.0.0.1:${address.port}`,
    token: 'integration-token-' + 'x'.repeat(32),
    close: () => new Promise<void>((resolvePromise, reject) => {
      server.close((error) => error ? reject(error) : resolvePromise())
    }),
  }
}
