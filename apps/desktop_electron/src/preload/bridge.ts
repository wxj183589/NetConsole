import type { IpcRendererEvent } from 'electron'

import type { BackendStatus, NetConsoleDesktopBridge } from '../shared/bridge'
import { DESKTOP_IPC } from '../shared/bridge'
import {
  validateBridgePath,
  validateBackendDownloadRequest,
  validateChooseSavePathOptions,
  validateRendererReadyReport,
  validateSelectFileOptions,
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
    selectFile: (options) => ipcRenderer.invoke(
      DESKTOP_IPC.selectFile,
      validateSelectFileOptions(options),
    ) as ReturnType<NetConsoleDesktopBridge['selectFile']>,
    selectDirectory: () => ipcRenderer.invoke(DESKTOP_IPC.selectDirectory) as ReturnType<NetConsoleDesktopBridge['selectDirectory']>,
    chooseSavePath: (options) => ipcRenderer.invoke(
      DESKTOP_IPC.chooseSavePath,
      validateChooseSavePathOptions(options),
    ) as ReturnType<NetConsoleDesktopBridge['chooseSavePath']>,
    downloadBackendResource: (request) => ipcRenderer.invoke(
      DESKTOP_IPC.downloadBackendResource,
      validateBackendDownloadRequest(request),
    ) as ReturnType<NetConsoleDesktopBridge['downloadBackendResource']>,
    openPath: (path) => ipcRenderer.invoke(
      DESKTOP_IPC.openPath,
      validateBridgePath(path),
    ) as ReturnType<NetConsoleDesktopBridge['openPath']>,
    showItemInFolder: (path) => ipcRenderer.invoke(
      DESKTOP_IPC.showItemInFolder,
      validateBridgePath(path),
    ) as ReturnType<NetConsoleDesktopBridge['showItemInFolder']>,
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
