import { describe, expect, it, vi } from 'vitest'

import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import { createElectronAdapter } from './electron-adapter'

function bridge(runtime = {
  apiBaseUrl: 'http://127.0.0.1:43123',
  apiToken: 'electron-test-token-abcdefghijklmnopqrstuvwxyz',
}): NetConsoleDesktopBridge {
  return {
    getAppInfo: vi.fn(async () => ({ version: '1.3.8', platform: 'win32', isPackaged: false })),
    getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: runtime.apiBaseUrl })),
    getRuntimeConfig: vi.fn(async () => runtime),
    openTaskWindow: vi.fn(async () => ({ success: true })),
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsTool: vi.fn(async () => ({ cancelled: true })),
    selectSettingsDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsColor: vi.fn(async () => ({ cancelled: true })),
    executeSettingsAction: vi.fn(async () => ({ success: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    downloadBackendResource: vi.fn(async () => ({ status: 'cancelled' as const })),
    executeFileDesktopAction: vi.fn(async () => ({ success: true })),
    openPath: vi.fn(async () => ({ success: true })),
    showItemInFolder: vi.fn(async () => ({ success: true })),
    openExternalUrl: vi.fn(async () => ({ success: true })),
    onBackendStatusChanged: vi.fn(() => () => undefined),
    reportRendererReady: vi.fn(),
  }
}

describe('Electron platform adapter', () => {
  it('accepts only a dynamic loopback API config and delegates the fixed bridge', async () => {
    const nativeBridge = bridge()
    const adapter = createElectronAdapter(nativeBridge)

    await expect(adapter.getRuntimeConfig()).resolves.toEqual({
      apiBaseUrl: 'http://127.0.0.1:43123',
      apiToken: 'electron-test-token-abcdefghijklmnopqrstuvwxyz',
    })
    adapter.reportRendererReady(true)
    expect(nativeBridge.reportRendererReady).toHaveBeenCalledWith({ healthOk: true })
    await adapter.downloadBackendResource({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'report.zip',
    })
    expect(nativeBridge.downloadBackendResource).toHaveBeenCalledWith({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'report.zip',
    })
    await adapter.openTaskWindow({ taskId: 'task-1', status: 'RUNNING' })
    expect(nativeBridge.openTaskWindow).toHaveBeenCalledWith({ taskId: 'task-1', status: 'RUNNING' })
    await adapter.openExternalUrl('https://192.0.2.10/')
    expect(nativeBridge.openExternalUrl).toHaveBeenCalledWith('https://192.0.2.10/')
  })

  it.each([
    { apiBaseUrl: 'http://0.0.0.0:43123', apiToken: 'electron-test-token-abcdefghijklmnopqrstuvwxyz' },
    { apiBaseUrl: 'https://127.0.0.1:43123', apiToken: 'electron-test-token-abcdefghijklmnopqrstuvwxyz' },
    { apiBaseUrl: 'http://127.0.0.1:43123/path', apiToken: 'electron-test-token-abcdefghijklmnopqrstuvwxyz' },
    { apiBaseUrl: 'http://127.0.0.1:43123', apiToken: 'short' },
  ])('rejects unsafe runtime config %#', async (runtime) => {
    await expect(createElectronAdapter(bridge(runtime)).getRuntimeConfig()).rejects.toThrow()
  })
})
