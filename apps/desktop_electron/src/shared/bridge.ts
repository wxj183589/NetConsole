export type BackendState = 'starting' | 'ready' | 'stopped' | 'failed'

export interface AppInfo {
  version: string
  platform: string
  isPackaged: boolean
}

export interface BackendStatus {
  state: BackendState
  baseUrl?: string
  error?: string
}

export interface DesktopRuntimeConfig {
  apiBaseUrl: string
  apiToken: string
}

export interface FileFilter {
  name: string
  extensions: string[]
}

export interface SelectFileOptions {
  filters?: FileFilter[]
  multiple?: boolean
}

export interface SelectFileResult {
  cancelled: boolean
  paths: string[]
}

export interface SelectDirectoryResult {
  cancelled: boolean
  path?: string
}

export interface ChooseSavePathOptions {
  suggestedName: string
  filters?: FileFilter[]
}

export interface ChooseSavePathResult {
  cancelled: boolean
  path?: string
}

export interface NativeActionResult {
  success: boolean
  error?: string
}

export interface BackendDownloadRequest {
  apiPath: string
  query?: Record<string, string>
  suggestedName: string
  filters?: FileFilter[]
}

export interface BackendDownloadResult {
  status: 'started' | 'saved' | 'cancelled' | 'failed'
  savedPath?: string
  error?: string
}

export interface RendererReadyReport {
  healthOk: boolean
}

export interface NetConsoleDesktopBridge {
  getAppInfo(): Promise<AppInfo>
  getBackendStatus(): Promise<BackendStatus>
  getRuntimeConfig(): Promise<DesktopRuntimeConfig>
  selectFile(options?: SelectFileOptions): Promise<SelectFileResult>
  selectDirectory(): Promise<SelectDirectoryResult>
  chooseSavePath(options: ChooseSavePathOptions): Promise<ChooseSavePathResult>
  downloadBackendResource(request: BackendDownloadRequest): Promise<BackendDownloadResult>
  openPath(path: string): Promise<NativeActionResult>
  showItemInFolder(path: string): Promise<NativeActionResult>
  onBackendStatusChanged(listener: (status: BackendStatus) => void): () => void
  reportRendererReady(report: RendererReadyReport): void
}

export const DESKTOP_IPC = Object.freeze({
  getAppInfo: 'netconsole:desktop:get-app-info',
  getBackendStatus: 'netconsole:desktop:get-backend-status',
  getRuntimeConfig: 'netconsole:desktop:get-runtime-config',
  selectFile: 'netconsole:desktop:select-file',
  selectDirectory: 'netconsole:desktop:select-directory',
  chooseSavePath: 'netconsole:desktop:choose-save-path',
  downloadBackendResource: 'netconsole:desktop:download-backend-resource',
  openPath: 'netconsole:desktop:open-path',
  showItemInFolder: 'netconsole:desktop:show-item-in-folder',
  backendStatusChanged: 'netconsole:desktop:backend-status-changed',
  rendererReady: 'netconsole:desktop:renderer-ready',
})

export const DESKTOP_SESSION_HEADER = 'X-NetConsole-Session'
export const DESKTOP_SESSION_COOKIE = 'netconsole_desktop_session'

export const DESKTOP_HANDLED_CHANNELS = Object.freeze([
  DESKTOP_IPC.getAppInfo,
  DESKTOP_IPC.getBackendStatus,
  DESKTOP_IPC.getRuntimeConfig,
  DESKTOP_IPC.selectFile,
  DESKTOP_IPC.selectDirectory,
  DESKTOP_IPC.chooseSavePath,
  DESKTOP_IPC.downloadBackendResource,
  DESKTOP_IPC.openPath,
  DESKTOP_IPC.showItemInFolder,
])
