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
      'createExternalTool',
      'createExternalToolCategory',
      'deleteExternalTool',
      'deleteExternalToolCategory',
      'downloadBackendResource',
      'executeFileDesktopAction',
      'executeSettingsAction',
      'getAppInfo',
      'getBackendStatus',
      'getCloseToTrayState',
      'getRendererRecoveryState',
      'getRuntimeConfig',
      'getUiPreference',
      'getWorkspaceWindowState',
      'launchExternalTool',
      'listExternalTools',
      'onBackendStatusChanged',
      'onCloseToTrayChanged',
      'onTaskCenterOpenRequested',
      'onTraySiteSwitchRequested',
      'openExternalUrl',
      'openOnlineMrSessionLocation',
      'openPath',
      'openTaskWindow',
      'openWorkspaceWindow',
      'refreshExternalToolStatuses',
      'refreshSiteContext',
      'renameExternalToolCategory',
      'reorderExternalToolCategories',
      'reorderExternalTools',
      'reportRendererReady',
      'reportRendererWorkload',
      'reportSiteSwitchState',
      'restartBackend',
      'revealExternalTool',
      'saveWorkspaceWindowState',
      'selectDataRootDirectory',
      'selectDirectory',
      'selectExternalToolExecutable',
      'selectExternalToolIcon',
      'selectExternalToolWorkingDirectory',
      'selectFile',
      'selectSettingsColor',
      'selectSettingsDirectory',
      'selectSettingsTool',
      'selectSiteExportDestination',
      'selectSitePackage',
      'setCloseToTrayEnabled',
      'setExternalToolFavorite',
      'setTaskTrayStatus',
      'setUiPreference',
      'setWorkspaceWindowTitle',
      'showItemInFolder',
      'showTaskNotification',
      'updateExternalTool',
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
    await bridge.refreshSiteContext?.()
    expect(invocations).toContainEqual([DESKTOP_IPC.refreshSiteContext, undefined])
    bridge.reportSiteSwitchState?.(true)
    expect(ipcRenderer.send).toHaveBeenCalledWith(DESKTOP_IPC.siteSwitchState, true)
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
    expect(() => bridge.downloadBackendResource({
      apiPath: '/api/device-management/exports/task-1/download',
      query: { artifact_id: 'artifact-1' },
      suggestedName: '设备表.csv',
      expectedSizeBytes: 128,
    })).toThrow('integrity metadata')
    bridge.downloadBackendResource({
      apiPath: '/api/device-management/exports/task-1/download',
      query: { artifact_id: 'artifact-1' },
      suggestedName: '设备表.csv',
      expectedSizeBytes: 128,
      expectedSha256: 'a'.repeat(64),
    })
    expect(ipcRenderer.invoke).toHaveBeenLastCalledWith(
      DESKTOP_IPC.downloadBackendResource,
      expect.objectContaining({
        expectedSizeBytes: 128,
        expectedSha256: 'a'.repeat(64),
      }),
    )
    vi.mocked(ipcRenderer.invoke).mockClear()
    expect(() => bridge.openExternalUrl('http://192.0.2.10/')).toThrow()
    expect(() => bridge.openPath('C:\\private\\report.xlsx')).toThrow('capabilityId is invalid')
    expect(() => bridge.showItemInFolder('C:\\private')).toThrow('capabilityId is invalid')
    expect(() => bridge.executeFileDesktopAction('C:\\private')).toThrow('file desktop action reference is invalid')
    expect(() => bridge.openOnlineMrSessionLocation?.('..\\private')).toThrow('Online MR session id is invalid')
    expect(() => bridge.launchExternalTool('C:\\private\\tool.exe')).toThrow('toolId is invalid')
    expect(() => bridge.revealExternalTool('not-an-id')).toThrow('toolId is invalid')
    expect(() => bridge.createExternalTool({
      name: '工具',
      executablePath: 'relative.exe',
      arguments: [],
      categoryId: 'e5057ec4-03c5-4c17-b24d-b8111ee8f942',
      favorite: false,
      iconMode: 'auto',
    })).toThrow('absolute Windows path')
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

  it('sends only a validated Online MR session id to the fixed IPC channel', async () => {
    const ipcRenderer: IpcRendererLike = {
      invoke: vi.fn(async () => ({ success: true })),
      send: vi.fn(),
      on: vi.fn(),
      removeListener: vi.fn(),
    }
    const bridge = createDesktopBridge(ipcRenderer)

    await bridge.openOnlineMrSessionLocation?.('20260721_155004_ea78c0')

    expect(ipcRenderer.invoke).toHaveBeenCalledWith(
      DESKTOP_IPC.openOnlineMrSessionLocation,
      '20260721_155004_ea78c0',
    )
  })
})
