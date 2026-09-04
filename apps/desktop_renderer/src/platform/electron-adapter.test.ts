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
    showTaskNotification: vi.fn(async () => ({ success: true })),
    setTaskTrayStatus: vi.fn(),
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsTool: vi.fn(async () => ({ cancelled: true })),
    selectSettingsDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsColor: vi.fn(async () => ({ cancelled: true })),
    executeSettingsAction: vi.fn(async () => ({ success: true })),
    selectDataRootDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSitePackage: vi.fn(async () => ({ cancelled: true })),
    selectSiteExportDestination: vi.fn(async () => ({ cancelled: true })),
    restartBackend: vi.fn(async () => ({ success: true })),
    restartApplication: vi.fn(async () => ({ success: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    downloadBackendResource: vi.fn(async () => ({ status: 'cancelled' as const })),
    executeFileDesktopAction: vi.fn(async () => ({ success: true })),
    listExternalTools: vi.fn(async () => ({ schema_version: 2 as const, categories: [], tools: [] })),
    selectExternalToolExecutable: vi.fn(async () => ({ cancelled: true })),
    selectExternalToolWorkingDirectory: vi.fn(async () => ({ cancelled: true })),
    selectExternalToolIcon: vi.fn(async () => ({ cancelled: true })),
    createExternalTool: vi.fn(async () => ({ success: true })),
    createExternalToolSystemReference: vi.fn(async () => ({ success: true })),
    updateExternalTool: vi.fn(async () => ({ success: true })),
    deleteExternalTool: vi.fn(async () => ({ success: true })),
    setExternalToolFavorite: vi.fn(async () => ({ success: true })),
    reorderExternalTools: vi.fn(async () => ({ success: true })),
    reorderExternalToolCategories: vi.fn(async () => ({ success: true })),
    createExternalToolCategory: vi.fn(async () => ({ success: true })),
    renameExternalToolCategory: vi.fn(async () => ({ success: true })),
    deleteExternalToolCategory: vi.fn(async () => ({ success: true })),
    launchExternalTool: vi.fn(async (request) => ({ success: true, toolId: request.toolId })),
    revealExternalTool: vi.fn(async (toolId: string) => ({ success: true, toolId })),
    refreshExternalToolStatuses: vi.fn(async () => ({ schema_version: 2 as const, categories: [], tools: [] })),
    openPath: vi.fn(async () => ({ success: true })),
    showItemInFolder: vi.fn(async () => ({ success: true })),
    openExternalUrl: vi.fn(async () => ({ success: true })),
    writeClipboardText: vi.fn(async () => ({ success: true })),
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
    expect(nativeBridge.reportRendererReady).toHaveBeenCalledWith({ healthOk: true, phase: 'interactive' })
    adapter.reportRendererReady(true, 'interactive', 'main', 'hz10')
    expect(nativeBridge.reportRendererReady).toHaveBeenLastCalledWith({
      healthOk: true,
      phase: 'interactive',
      surface: 'main',
      siteId: 'hz10',
    })
    await adapter.downloadBackendResource({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'report.zip',
    })
    expect(nativeBridge.downloadBackendResource).toHaveBeenCalledWith({
      apiPath: '/api/file-management/downloads/task-1/file',
      suggestedName: 'report.zip',
    })
    await adapter.openTaskWindow({ taskId: 'task-1', status: 'RUNNING' })
    expect(nativeBridge.openTaskWindow).not.toHaveBeenCalled()
    await adapter.openExternalUrl('https://192.0.2.10/')
    expect(nativeBridge.openExternalUrl).toHaveBeenCalledWith('https://192.0.2.10/')
    await adapter.writeClipboardText('AirScript source')
    expect(nativeBridge.writeClipboardText).toHaveBeenCalledWith('AirScript source')
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
