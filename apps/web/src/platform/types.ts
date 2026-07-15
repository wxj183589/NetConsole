import type {
  AppInfo,
  BackendStatus,
  ChooseSavePathOptions,
  ChooseSavePathResult,
  DesktopRuntimeConfig,
  NativeActionResult,
  SelectDirectoryResult,
  SelectFileOptions,
  SelectFileResult,
} from '../../../desktop_electron/src/shared/bridge'

export type HostType = 'browser' | 'electron'

export interface PlatformAdapter {
  readonly hostType: HostType
  getAppInfo(): Promise<AppInfo>
  getBackendStatus(): Promise<BackendStatus>
  getRuntimeConfig(): Promise<DesktopRuntimeConfig>
  selectFile(options?: SelectFileOptions): Promise<SelectFileResult>
  selectDirectory(): Promise<SelectDirectoryResult>
  chooseSavePath(options: ChooseSavePathOptions): Promise<ChooseSavePathResult>
  openPath(path: string): Promise<NativeActionResult>
  showItemInFolder(path: string): Promise<NativeActionResult>
  onBackendStatusChanged(listener: (status: BackendStatus) => void): () => void
  reportRendererReady(healthOk: boolean): void
}

export interface ActiveRuntimeConfig extends DesktopRuntimeConfig {
  hostType: HostType
}
