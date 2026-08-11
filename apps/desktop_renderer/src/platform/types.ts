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
  SiteStorageRestartRequest,
  TaskNotificationPayload,
  TaskTrayStatus,
  TaskWindowContext,
  RendererReadyReport,
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
  selectDataRootDirectory(): Promise<SettingsPathResult>
  selectSitePackage(): Promise<SettingsPathResult>
  selectSiteExportDestination(suggestedName: string): Promise<SettingsPathResult>
  restartBackend(request: SiteStorageRestartRequest): Promise<NativeActionResult>
  refreshSiteContext(): Promise<void>
  chooseSavePath(options: ChooseSavePathOptions): Promise<ChooseSavePathResult>
  downloadBackendResource(request: BackendDownloadRequest): Promise<BackendDownloadResult>
  openTaskWindow(context?: TaskWindowContext): Promise<NativeActionResult>
  showTaskNotification(payload: TaskNotificationPayload): Promise<NativeActionResult>
  setTaskTrayStatus(status: TaskTrayStatus): void
  onTaskCenterOpenRequested(listener: (context: TaskWindowContext) => void): () => void
  openMeshAnalysisSessionLocation(sessionId: string): Promise<NativeActionResult>
  openPath(capabilityId: string): Promise<NativeActionResult>
  showItemInFolder(capabilityId: string): Promise<NativeActionResult>
  openExternalUrl(url: string): Promise<NativeActionResult>
  writeClipboardText(text: string): Promise<NativeActionResult>
  onBackendStatusChanged(listener: (status: BackendStatus) => void): () => void
  onTraySiteSwitchRequested(listener: (siteId: string) => void): () => void
  reportSiteSwitchState(switching: boolean): void
  reportRendererReady(
    healthOk: boolean,
    phase?: RendererReadyReport['phase'],
    surface?: RendererReadyReport['surface'],
  ): void
}

export interface ActiveRuntimeConfig extends DesktopRuntimeConfig {
  hostType: HostType
}
