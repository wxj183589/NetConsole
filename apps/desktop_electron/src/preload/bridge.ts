import type { IpcRendererEvent } from 'electron'

import type { BackendStatus, NetConsoleDesktopBridge } from '../shared/bridge'
import { DESKTOP_IPC } from '../shared/bridge'
import {
  validateCapabilityId,
  validateExternalUrl,
  validateFileDesktopActionRef,
  validateBackendDownloadRequest,
  validateChooseSavePathOptions,
  validateRendererReadyReport,
  validateSelectFileOptions,
  validateTaskWindowContext,
  validateUiPreferenceKey, validateUiPreferenceValue,
  validateSettingsActionId, validateSettingsDirectoryId, validateSettingsToolId,
  validateSiteStorageRestartRequest,
} from '../shared/validation'

export interface IpcRendererLike {
  invoke(channel: string, value?: unknown): Promise<unknown>
  send(channel: string, value?: unknown): void
  on(channel: string, listener: (event: IpcRendererEvent, value: unknown) => void): void
  removeListener(channel: string, listener: (event: IpcRendererEvent, value: unknown) => void): void
}

export function createDesktopBridge(ipcRenderer: IpcRendererLike): NetConsoleDesktopBridge {
  const bridge: NetConsoleDesktopBridge = {
    getAppInfo: () => ipcRenderer.invoke(DESKTOP_IPC.getAppInfo) as ReturnType<NetConsoleDesktopBridge['getAppInfo']>,
    getBackendStatus: () => ipcRenderer.invoke(DESKTOP_IPC.getBackendStatus) as ReturnType<NetConsoleDesktopBridge['getBackendStatus']>,
    getRuntimeConfig: () => ipcRenderer.invoke(DESKTOP_IPC.getRuntimeConfig) as ReturnType<NetConsoleDesktopBridge['getRuntimeConfig']>,
    getUiPreference: (key) => ipcRenderer.invoke(
      DESKTOP_IPC.getUiPreference, validateUiPreferenceKey(key),
    ) as Promise<unknown | null>,
    setUiPreference: (key, value) => ipcRenderer.invoke(
      DESKTOP_IPC.setUiPreference,
      [validateUiPreferenceKey(key), validateUiPreferenceValue(key, value)],
    ) as Promise<void>,
    openTaskWindow: (context) => ipcRenderer.invoke(
      DESKTOP_IPC.openTaskWindow,
      validateTaskWindowContext(context),
    ) as ReturnType<NetConsoleDesktopBridge['openTaskWindow']>,
    selectFile: (options) => ipcRenderer.invoke(
      DESKTOP_IPC.selectFile,
      validateSelectFileOptions(options),
    ) as ReturnType<NetConsoleDesktopBridge['selectFile']>,
    selectDirectory: () => ipcRenderer.invoke(DESKTOP_IPC.selectDirectory) as ReturnType<NetConsoleDesktopBridge['selectDirectory']>,
    selectSettingsTool: (toolId) => ipcRenderer.invoke(
      DESKTOP_IPC.selectSettingsTool, validateSettingsToolId(toolId),
    ) as ReturnType<NetConsoleDesktopBridge['selectSettingsTool']>,
    selectSettingsDirectory: (directoryId) => ipcRenderer.invoke(
      DESKTOP_IPC.selectSettingsDirectory, validateSettingsDirectoryId(directoryId),
    ) as ReturnType<NetConsoleDesktopBridge['selectSettingsDirectory']>,
    selectSettingsColor: () => ipcRenderer.invoke(DESKTOP_IPC.selectSettingsColor) as ReturnType<NetConsoleDesktopBridge['selectSettingsColor']>,
    executeSettingsAction: (actionId) => ipcRenderer.invoke(
      DESKTOP_IPC.executeSettingsAction, validateSettingsActionId(actionId),
    ) as ReturnType<NetConsoleDesktopBridge['executeSettingsAction']>,
    selectDataRootDirectory: () => ipcRenderer.invoke(DESKTOP_IPC.selectDataRootDirectory) as ReturnType<NetConsoleDesktopBridge['selectDataRootDirectory']>,
    selectSitePackage: () => ipcRenderer.invoke(DESKTOP_IPC.selectSitePackage) as ReturnType<NetConsoleDesktopBridge['selectSitePackage']>,
    selectSiteExportDestination: (suggestedName) => ipcRenderer.invoke(
      DESKTOP_IPC.selectSiteExportDestination,
      validateChooseSavePathOptions({ suggestedName, filters: [{ name: 'NetConsole 局点包', extensions: ['ncsite'] }] }).suggestedName,
    ) as ReturnType<NetConsoleDesktopBridge['selectSiteExportDestination']>,
    restartBackend: (request) => ipcRenderer.invoke(
      DESKTOP_IPC.restartBackend, validateSiteStorageRestartRequest(request),
    ) as ReturnType<NetConsoleDesktopBridge['restartBackend']>,
    chooseSavePath: (options) => ipcRenderer.invoke(
      DESKTOP_IPC.chooseSavePath,
      validateChooseSavePathOptions(options),
    ) as ReturnType<NetConsoleDesktopBridge['chooseSavePath']>,
    downloadBackendResource: (request) => ipcRenderer.invoke(
      DESKTOP_IPC.downloadBackendResource,
      validateBackendDownloadRequest(request),
    ) as ReturnType<NetConsoleDesktopBridge['downloadBackendResource']>,
    executeFileDesktopAction: (actionRef) => ipcRenderer.invoke(
      DESKTOP_IPC.executeFileDesktopAction,
      validateFileDesktopActionRef(actionRef),
    ) as ReturnType<NetConsoleDesktopBridge['executeFileDesktopAction']>,
    openPath: (capabilityId) => ipcRenderer.invoke(
      DESKTOP_IPC.openPath,
      validateCapabilityId(capabilityId),
    ) as ReturnType<NetConsoleDesktopBridge['openPath']>,
    showItemInFolder: (capabilityId) => ipcRenderer.invoke(
      DESKTOP_IPC.showItemInFolder,
      validateCapabilityId(capabilityId),
    ) as ReturnType<NetConsoleDesktopBridge['showItemInFolder']>,
    openExternalUrl: (url) => ipcRenderer.invoke(
      DESKTOP_IPC.openExternalUrl,
      validateExternalUrl(url),
    ) as ReturnType<NetConsoleDesktopBridge['openExternalUrl']>,
    onBackendStatusChanged: (listener) => {
      const wrapped = (_event: IpcRendererEvent, value: unknown) => listener(value as BackendStatus)
      ipcRenderer.on(DESKTOP_IPC.backendStatusChanged, wrapped)
      return () => ipcRenderer.removeListener(DESKTOP_IPC.backendStatusChanged, wrapped)
    },
    reportRendererReady: (report) => ipcRenderer.send(
      DESKTOP_IPC.rendererReady,
      validateRendererReadyReport(report),
    ),
  }
  return Object.freeze(bridge)
}
