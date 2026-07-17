import type {
  AppInfo,
  BackendDownloadRequest,
  BackendDownloadResult,
  BackendStatus,
  ChooseSavePathOptions,
  ChooseSavePathResult,
  DesktopRuntimeConfig,
  NativeActionResult,
  SelectDirectoryResult,
  SelectFileOptions,
  SelectFileResult,
  SettingsActionId, SettingsColorResult, SettingsDirectoryId, SettingsPathResult, SettingsToolId,
  TaskWindowContext,
} from '../../../desktop_electron/src/shared/bridge'

export type HostType = 'browser' | 'electron'

export interface PlatformAdapter {
  readonly hostType: HostType
  getAppInfo(): Promise<AppInfo>
  getBackendStatus(): Promise<BackendStatus>
  getRuntimeConfig(): Promise<DesktopRuntimeConfig>
  selectFile(options?: SelectFileOptions): Promise<SelectFileResult>
  selectDirectory(): Promise<SelectDirectoryResult>
  selectSettingsTool(toolId: SettingsToolId): Promise<SettingsPathResult>
  selectSettingsDirectory(directoryId: SettingsDirectoryId): Promise<SettingsPathResult>
  selectSettingsColor(): Promise<SettingsColorResult>
  executeSettingsAction(actionId: SettingsActionId): Promise<NativeActionResult>
  chooseSavePath(options: ChooseSavePathOptions): Promise<ChooseSavePathResult>
  downloadBackendResource(request: BackendDownloadRequest): Promise<BackendDownloadResult>
  openTaskWindow(context?: TaskWindowContext): Promise<NativeActionResult>
  openPath(capabilityId: string): Promise<NativeActionResult>
  showItemInFolder(capabilityId: string): Promise<NativeActionResult>
  openExternalUrl(url: string): Promise<NativeActionResult>
  onBackendStatusChanged(listener: (status: BackendStatus) => void): () => void
  reportRendererReady(healthOk: boolean): void
}

export interface ActiveRuntimeConfig extends DesktopRuntimeConfig {
  hostType: HostType
}
