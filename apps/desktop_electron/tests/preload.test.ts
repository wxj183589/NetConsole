import { describe, expect, it, vi } from 'vitest'

import { createDesktopBridge, type IpcRendererLike } from '../src/preload/bridge'
import { DESKTOP_IPC } from '../src/shared/bridge'

describe('preload bridge', () => {
  it('exposes only named methods and never exposes ipcRenderer or Node native objects', async () => {
    const invocations: Array<[string, unknown]> = []
    const ipcRenderer: IpcRendererLike = {
      invoke: vi.fn(async (channel, value) => {
        invocations.push([channel, value])
        return { cancelled: true, paths: [] }
      }),
      send: vi.fn(),
      on: vi.fn(),
      removeListener: vi.fn(),
    }
    const bridge = createDesktopBridge(ipcRenderer)

    expect(Object.keys(bridge).sort()).toEqual([
      'chooseSavePath',
      'downloadBackendResource',
      'getAppInfo',
      'getBackendStatus',
      'getRuntimeConfig',
      'onBackendStatusChanged',
      'openExternalUrl',
      'openPath',
      'openTaskWindow',
      'reportRendererReady',
      'selectDirectory',
      'selectFile',
      'showItemInFolder',
    ])
    expect('ipcRenderer' in bridge).toBe(false)
    expect('process' in bridge).toBe(false)
    expect('require' in bridge).toBe(false)
    expect('fs' in bridge).toBe(false)

    await bridge.selectFile({ filters: [{ name: '日志', extensions: ['log'] }] })
    expect(invocations[0]).toEqual([
      DESKTOP_IPC.selectFile,
      { filters: [{ name: '日志', extensions: ['log'] }] },
    ])
  })

  it('validates arguments before sending IPC', async () => {
    const ipcRenderer: IpcRendererLike = {
      invoke: vi.fn(),
      send: vi.fn(),
      on: vi.fn(),
      removeListener: vi.fn(),
    }
    const bridge = createDesktopBridge(ipcRenderer)

    expect(() => bridge.chooseSavePath({ suggestedName: '..\\unsafe.exe' })).toThrow()
    expect(() => bridge.downloadBackendResource({
      apiPath: 'https://example.com/report.zip',
      suggestedName: 'report.zip',
    })).toThrow()
    expect(() => bridge.openExternalUrl('http://192.0.2.10/')).toThrow()
    expect(ipcRenderer.invoke).not.toHaveBeenCalled()
  })
})
