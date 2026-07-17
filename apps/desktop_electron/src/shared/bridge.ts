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

export type SettingsToolId = 'iperf3' | 'fping' | 'ipop' | 'securecrt' | 'xshell' | 'putty'
export type SettingsDirectoryId = 'securecrt_sessions_root'
export type SettingsActionId = 'open_settings_config' | 'open_current_site' | 'launch_ipop'
export type SettingsThemeColor = '#0078D4' | '#2563EB' | '#0891B2' | '#16A34A'

export interface SettingsPathResult { cancelled: boolean; path?: string }
export interface SettingsColorResult { cancelled: boolean; color?: SettingsThemeColor }

export interface BackendDownloadRequest {
  apiPath: string
  query?: Record<string, string>
  suggestedName: string
  filters?: FileFilter[]
}

export interface BackendDownloadResult {
  status: 'started' | 'saved' | 'cancelled' | 'failed'
  capabilityId?: string
  error?: string
}

export interface RendererReadyReport {
  healthOk: boolean
}

export interface TaskWindowContext {
  taskId?: string
  module?: 'devices' | 'ac' | 'rail' | 'config' | 'files' | 'network' | 'command-reference' | 'logs'
  status?: 'PENDING' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
}

export interface NetConsoleDesktopBridge {
  getAppInfo(): Promise<AppInfo>
  getBackendStatus(): Promise<BackendStatus>
  getRuntimeConfig(): Promise<DesktopRuntimeConfig>
  openTaskWindow(context?: TaskWindowContext): Promise<NativeActionResult>
  selectFile(options?: SelectFileOptions): Promise<SelectFileResult>
  selectDirectory(): Promise<SelectDirectoryResult>
  selectSettingsTool(toolId: SettingsToolId): Promise<SettingsPathResult>
  selectSettingsDirectory(directoryId: SettingsDirectoryId): Promise<SettingsPathResult>
  selectSettingsColor(): Promise<SettingsColorResult>
  executeSettingsAction(actionId: SettingsActionId): Promise<NativeActionResult>
  chooseSavePath(options: ChooseSavePathOptions): Promise<ChooseSavePathResult>
  downloadBackendResource(request: BackendDownloadRequest): Promise<BackendDownloadResult>
  executeFileDesktopAction(actionRef: string): Promise<NativeActionResult>
  openPath(capabilityId: string): Promise<NativeActionResult>
  showItemInFolder(capabilityId: string): Promise<NativeActionResult>
  openExternalUrl(url: string): Promise<NativeActionResult>
  onBackendStatusChanged(listener: (status: BackendStatus) => void): () => void
  reportRendererReady(report: RendererReadyReport): void
}

export const DESKTOP_IPC = Object.freeze({
  getAppInfo: 'netconsole:desktop:get-app-info',
  getBackendStatus: 'netconsole:desktop:get-backend-status',
  getRuntimeConfig: 'netconsole:desktop:get-runtime-config',
  openTaskWindow: 'netconsole:desktop:open-task-window',
  selectFile: 'netconsole:desktop:select-file',
  selectDirectory: 'netconsole:desktop:select-directory',
  selectSettingsTool: 'netconsole:desktop:select-settings-tool',
  selectSettingsDirectory: 'netconsole:desktop:select-settings-directory',
  selectSettingsColor: 'netconsole:desktop:select-settings-color',
  executeSettingsAction: 'netconsole:desktop:execute-settings-action',
  chooseSavePath: 'netconsole:desktop:choose-save-path',
  downloadBackendResource: 'netconsole:desktop:download-backend-resource',
  executeFileDesktopAction: 'netconsole:desktop:execute-file-action',
  openPath: 'netconsole:desktop:open-path',
  showItemInFolder: 'netconsole:desktop:show-item-in-folder',
  openExternalUrl: 'netconsole:desktop:open-external-url',
  backendStatusChanged: 'netconsole:desktop:backend-status-changed',
  rendererReady: 'netconsole:desktop:renderer-ready',
})

export const DESKTOP_SESSION_HEADER = 'X-NetConsole-Session'
export const DESKTOP_SESSION_COOKIE = 'netconsole_desktop_session'

export const DESKTOP_HANDLED_CHANNELS = Object.freeze([
  DESKTOP_IPC.getAppInfo,
  DESKTOP_IPC.getBackendStatus,
  DESKTOP_IPC.getRuntimeConfig,
  DESKTOP_IPC.openTaskWindow,
  DESKTOP_IPC.selectFile,
  DESKTOP_IPC.selectDirectory,
  DESKTOP_IPC.selectSettingsTool,
  DESKTOP_IPC.selectSettingsDirectory,
  DESKTOP_IPC.selectSettingsColor,
  DESKTOP_IPC.executeSettingsAction,
  DESKTOP_IPC.chooseSavePath,
  DESKTOP_IPC.downloadBackendResource,
  DESKTOP_IPC.executeFileDesktopAction,
  DESKTOP_IPC.openPath,
  DESKTOP_IPC.showItemInFolder,
  DESKTOP_IPC.openExternalUrl,
])
