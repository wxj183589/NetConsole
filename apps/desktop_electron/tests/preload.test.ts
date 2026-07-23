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
      'executeFileDesktopAction',
      'executeSettingsAction',
      'getAppInfo',
      'getBackendStatus',
      'getRendererRecoveryState',
      'getRuntimeConfig',
      'getUiPreference',
      'onBackendStatusChanged',
      'openExternalUrl',
      'openPath',
      'openTaskWindow',
      'reportRendererReady',
      'reportRendererWorkload',
      'restartBackend',
      'selectDataRootDirectory',
      'selectDirectory',
      'selectFile',
      'selectSettingsColor',
      'selectSettingsDirectory',
      'selectSettingsTool',
      'selectSiteExportDestination',
      'selectSitePackage',
      'setUiPreference',
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
    bridge.reportRendererReady({ resolvedTheme: 'dark' })
    expect(ipcRenderer.send).toHaveBeenCalledWith(
      DESKTOP_IPC.rendererReady,
      { resolvedTheme: 'dark' },
    )
    bridge.reportRendererWorkload?.({
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'echarts-set-option',
      sessionId: 'session-1',
      returnedLinkPoints: 44_251,
      reportRevision: 1,
    })
    expect(ipcRenderer.send).toHaveBeenCalledWith(
      DESKTOP_IPC.rendererWorkload,
      expect.objectContaining({
        phase: 'echarts-set-option',
        returnedLinkPoints: 44_251,
      }),
    )
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
    expect(() => bridge.openPath('C:\\private\\report.xlsx')).toThrow('capabilityId is invalid')
    expect(() => bridge.showItemInFolder('C:\\private')).toThrow('capabilityId is invalid')
    expect(() => bridge.executeFileDesktopAction('C:\\private')).toThrow('file desktop action reference is invalid')
    expect(() => bridge.restartBackend({ dataRoot: 'relative' })).toThrow('dataRoot must be absolute')
    expect(() => bridge.reportRendererWorkload?.({
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'echarts-set-option',
      reportRevision: 0,
    })).toThrow('reportRevision is invalid')
    expect(() => bridge.reportRendererWorkload?.({
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'echarts-set-option',
      viewportStart: 'C:\\private\\raw.log',
      reportRevision: 1,
    })).toThrow('viewportStart is invalid')
    expect(ipcRenderer.invoke).not.toHaveBeenCalled()
  })


})
