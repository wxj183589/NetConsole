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
  directoryPath?: string
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

export interface SettingsToolDefinition {
  displayName: string
  fieldLabel: string
  filterName: string
  executableNames: readonly string[]
}

export const SETTINGS_TOOL_DEFINITIONS: Record<SettingsToolId, SettingsToolDefinition> = {
  iperf3: { displayName: 'iperf3', fieldLabel: 'iperf3.exe', filterName: 'iperf3.exe', executableNames: ['iperf3.exe'] },
  fping: { displayName: 'fping', fieldLabel: 'fping.exe', filterName: 'fping.exe', executableNames: ['fping.exe', 'Fping_v3.exe'] },
  ipop: { displayName: 'IPOP', fieldLabel: 'IPOP.exe', filterName: 'IPOP.exe', executableNames: ['IPOP.EXE'] },
  securecrt: { displayName: 'SecureCRT', fieldLabel: 'SecureCRT.exe', filterName: 'SecureCRT', executableNames: ['SecureCRT.exe'] },
  xshell: { displayName: 'Xshell', fieldLabel: 'Xshell.exe', filterName: 'Xshell', executableNames: ['Xshell.exe'] },
  putty: { displayName: 'PuTTY', fieldLabel: 'PuTTY.exe / PuTTY64.exe', filterName: 'PuTTY', executableNames: ['putty.exe', 'putty64.exe'] },
}

export function settingsToolNameMatches(toolId: SettingsToolId, path: string): boolean {
  if (!path.trim()) return true
  const executableName = path.trim().split(/[\\/]/).pop()?.toLowerCase() ?? ''
  return SETTINGS_TOOL_DEFINITIONS[toolId].executableNames.some((name) => name.toLowerCase() === executableName)
}

export function settingsToolMismatchMessage(toolId: SettingsToolId): string {
  if (toolId === 'putty') return '所选程序与 PuTTY 类型不匹配。请选择 putty.exe 或 putty64.exe。'
  const definition = SETTINGS_TOOL_DEFINITIONS[toolId]
  return `所选程序与 ${definition.displayName} 类型不匹配。请选择 ${definition.executableNames.join(' 或 ')}。`
}

export interface SettingsPathResult { cancelled: boolean; path?: string }
export interface SettingsColorResult { cancelled: boolean; color?: SettingsThemeColor }

export interface SiteStorageRestartRequest {
  dataRoot?: string
  activeSiteId?: string
}

export interface BackendDownloadRequest {
  apiPath: string
  query?: Record<string, string>
  suggestedName: string
  filters?: FileFilter[]
  destinationPath?: string
  expectedSizeBytes?: number
  expectedSha256?: string
}

export type BackendDownloadErrorCode =
  | 'ARTIFACT_NOT_FOUND'
  | 'BACKEND_DOWNLOAD_FAILED'
  | 'FILE_INTEGRITY_MISMATCH'
  | 'FILE_TYPE_MISMATCH'
  | 'PATH_NOT_WRITABLE'
  | 'DISK_FULL'
  | 'DOWNLOAD_IN_PROGRESS'
  | 'DESKTOP_SHUTTING_DOWN'

export interface BackendDownloadResult {
  status: 'started' | 'saved' | 'cancelled' | 'failed'
  capabilityId?: string
  fileName?: string
  directoryLabel?: string
  sizeBytes?: number
  sha256?: string
  errorCode?: BackendDownloadErrorCode
  error?: string
}

export interface RendererReadyReport {
  healthOk: boolean
  phase: 'mounted' | 'interactive' | 'failed'
  surface?: 'main' | 'task-window' | 'workspace-window'
}

export type DesktopResolvedTheme = 'light' | 'dark'

export interface RendererThemeReport {
  resolvedTheme: DesktopResolvedTheme
}

export type RendererHostReport = RendererReadyReport | RendererThemeReport

export type RendererWorkloadPhase =
  | 'session-selected'
  | 'trackside-request-started'
  | 'trackside-response-received'
  | 'trackside-cache-building'
  | 'trackside-cache-ready'
  | 'echarts-init'
  | 'echarts-set-option'
  | 'echarts-interactive'
  | 'chart-disposed'

export interface RendererWorkloadReport {
  module: 'mesh-analysis'
  route: '/rail-transit/mesh-analysis'
  phase: RendererWorkloadPhase
  sessionId?: string
  sourceFileId?: number
  radio?: number | null
  totalFrames?: number
  returnedFrames?: number
  totalLinkPoints?: number
  returnedLinkPoints?: number
  seriesCount?: number
  pointCount?: number
  metadataCount?: number
  conflictEdgeCount?: number
  echartsInstanceCount?: number
  canvasCount?: number
  meshInstanceCount?: number
  tracksideCacheCount?: number
  tracksideChartCount?: number
  activeDetailRequests?: number
  tracksideCacheBuildCount?: number
  tracksideCacheDisposeCount?: number
  chartInitCount?: number
  chartDisposeCount?: number
  viewportStart?: string
  viewportEnd?: string
  heapUsedBytes?: number
  heapTotalBytes?: number
  heapLimitBytes?: number
  reportRevision: number
}

export interface RendererRecoveryState {
  mode: 'safe' | 'normal'
  previousReason: string
  module: 'mesh-analysis'
  route: '/rail-transit/mesh-analysis'
  sessionId?: string
  sourceFileId?: number
  radio?: number | null
}

export interface TaskWindowContext {
  taskId?: string
  module?: 'devices' | 'ac' | 'rail' | 'config' | 'files' | 'network' | 'command-reference' | 'logs'
  status?: 'PENDING' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
}

export interface WorkspaceWindowOpenRequest {
  routeFullPath: string
  title: string
}

export interface WorkspaceTabSnapshot {
  id: string
  instanceId: string
  routeName?: string
  routeFullPath: string
  title: string
  identityKey: string
  cacheKey: string
  pinned: boolean
  openedAt: number
  lastActivatedAt: number
}

export interface WorkspaceWindowSnapshot {
  schemaVersion: 1
  windowId: string
  activeTabId: string
  tabs: WorkspaceTabSnapshot[]
}

export interface WorkspaceWindowStateResult {
  windowId: string
  snapshot: WorkspaceWindowSnapshot | null
}

export interface CloseToTrayState {
  enabled: boolean
  available: boolean
}

export interface TraySiteSwitchRequest {
  siteId: string
}

export const UI_PREFERENCE_KEYS = Object.freeze([
  'desktop.close-to-tray',
  'mesh-analysis-rssi.layout-mode',
  'mesh-analysis-rssi.compare-split-ratio',
  'mesh-analysis-rssi.show-switch-lines',
  'mesh-analysis-rssi.show-switch-points',
  'mesh-analysis-rssi.show-location-band',
  'mesh-analysis-airload.show-switch-lines',
  'mesh-analysis-airload.show-switch-points',
  'mesh-analysis.table.sessions:v2',
  'mesh-analysis.table.active-build-order:v2',
  'mesh-analysis.table.link-details:v2',
  'mesh-analysis.table.link-details:v3',
  'mesh-analysis.table.switch-events:v2',
  'mesh-analysis.table.switch-events:v3',
  'mesh-analysis.table.artifacts:v2',
  'mesh-analysis.table.sources:v2',
] as const)

export type UiPreferenceKey = typeof UI_PREFERENCE_KEYS[number]

export interface NetConsoleDesktopBridge {
  getAppInfo(): Promise<AppInfo>
  getBackendStatus(): Promise<BackendStatus>
  getRuntimeConfig(): Promise<DesktopRuntimeConfig>
  getUiPreference?(key: UiPreferenceKey): Promise<unknown | null>
  setUiPreference?(key: UiPreferenceKey, value: unknown | null): Promise<void>
  openTaskWindow(context?: TaskWindowContext): Promise<NativeActionResult>
  openWorkspaceWindow?(request: WorkspaceWindowOpenRequest): Promise<NativeActionResult>
  getWorkspaceWindowState?(): Promise<WorkspaceWindowStateResult>
  saveWorkspaceWindowState?(snapshot: WorkspaceWindowSnapshot): Promise<void>
  setWorkspaceWindowTitle?(title: string): void
  getCloseToTrayState?(): Promise<CloseToTrayState>
  setCloseToTrayEnabled?(enabled: boolean): Promise<CloseToTrayState>
  onCloseToTrayChanged?(listener: (state: CloseToTrayState) => void): () => void
  /** Electron Main re-reads the current site and Registry; Renderer supplies no site data. */
  refreshSiteContext?(): Promise<void>
  onTraySiteSwitchRequested?(listener: (request: TraySiteSwitchRequest) => void): () => void
  reportSiteSwitchState?(switching: boolean): void
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
  chooseSavePath(options: ChooseSavePathOptions): Promise<ChooseSavePathResult>
  downloadBackendResource(request: BackendDownloadRequest): Promise<BackendDownloadResult>
  executeFileDesktopAction(actionRef: string): Promise<NativeActionResult>
  openOnlineMrSessionLocation?(sessionId: string): Promise<NativeActionResult>
  openPath(capabilityId: string): Promise<NativeActionResult>
  showItemInFolder(capabilityId: string): Promise<NativeActionResult>
  openExternalUrl(url: string): Promise<NativeActionResult>
  onBackendStatusChanged(listener: (status: BackendStatus) => void): () => void
  /** One-way, strictly validated renderer lifecycle or resolved-theme report. */
  reportRendererReady(report: RendererHostReport): void
  /** One-way, strictly validated snapshot used only for Renderer diagnostics. */
  reportRendererWorkload?(report: RendererWorkloadReport): void
  /** Returns only the in-memory recovery context for this trusted Renderer. */
  getRendererRecoveryState?(): Promise<RendererRecoveryState | null>
}

export const DESKTOP_IPC = Object.freeze({
  getAppInfo: 'netconsole:desktop:get-app-info',
  getBackendStatus: 'netconsole:desktop:get-backend-status',
  getRuntimeConfig: 'netconsole:desktop:get-runtime-config',
  getUiPreference: 'netconsole:desktop:get-ui-preference',
  setUiPreference: 'netconsole:desktop:set-ui-preference',
  openTaskWindow: 'netconsole:desktop:open-task-window',
  openWorkspaceWindow: 'netconsole:desktop:open-workspace-window',
  getWorkspaceWindowState: 'netconsole:desktop:get-workspace-window-state',
  saveWorkspaceWindowState: 'netconsole:desktop:save-workspace-window-state',
  setWorkspaceWindowTitle: 'netconsole:desktop:set-workspace-window-title',
  getCloseToTrayState: 'netconsole:desktop:get-close-to-tray-state',
  setCloseToTrayEnabled: 'netconsole:desktop:set-close-to-tray-enabled',
  closeToTrayChanged: 'netconsole:desktop:close-to-tray-changed',
  refreshSiteContext: 'netconsole:desktop:refresh-site-context',
  traySiteSwitchRequested: 'netconsole:desktop:tray-site-switch-requested',
  siteSwitchState: 'netconsole:desktop:site-switch-state',
  selectFile: 'netconsole:desktop:select-file',
  selectDirectory: 'netconsole:desktop:select-directory',
  selectSettingsTool: 'netconsole:desktop:select-settings-tool',
  selectSettingsDirectory: 'netconsole:desktop:select-settings-directory',
  selectSettingsColor: 'netconsole:desktop:select-settings-color',
  executeSettingsAction: 'netconsole:desktop:execute-settings-action',
  selectDataRootDirectory: 'netconsole:desktop:select-data-root-directory',
  selectSitePackage: 'netconsole:desktop:select-site-package',
  selectSiteExportDestination: 'netconsole:desktop:select-site-export-destination',
  restartBackend: 'netconsole:desktop:restart-backend',
  chooseSavePath: 'netconsole:desktop:choose-save-path',
  downloadBackendResource: 'netconsole:desktop:download-backend-resource',
  executeFileDesktopAction: 'netconsole:desktop:execute-file-action',
  openOnlineMrSessionLocation: 'netconsole:desktop:open-online-mr-session-location',
  openPath: 'netconsole:desktop:open-path',
  showItemInFolder: 'netconsole:desktop:show-item-in-folder',
  openExternalUrl: 'netconsole:desktop:open-external-url',
  backendStatusChanged: 'netconsole:desktop:backend-status-changed',
  rendererReady: 'netconsole:desktop:renderer-ready',
  rendererWorkload: 'netconsole:desktop:renderer-workload',
  rendererRecoveryState: 'netconsole:desktop:renderer-recovery-state',
})

export const DESKTOP_SESSION_HEADER = 'X-NetConsole-Session'
export const DESKTOP_SESSION_COOKIE = 'netconsole_desktop_session'

export const DESKTOP_HANDLED_CHANNELS = Object.freeze([
  DESKTOP_IPC.getAppInfo,
  DESKTOP_IPC.getBackendStatus,
  DESKTOP_IPC.getRuntimeConfig,
  DESKTOP_IPC.getUiPreference,
  DESKTOP_IPC.setUiPreference,
  DESKTOP_IPC.openTaskWindow,
  DESKTOP_IPC.openWorkspaceWindow,
  DESKTOP_IPC.getWorkspaceWindowState,
  DESKTOP_IPC.saveWorkspaceWindowState,
  DESKTOP_IPC.getCloseToTrayState,
  DESKTOP_IPC.setCloseToTrayEnabled,
  DESKTOP_IPC.refreshSiteContext,
  DESKTOP_IPC.selectFile,
  DESKTOP_IPC.selectDirectory,
  DESKTOP_IPC.selectSettingsTool,
  DESKTOP_IPC.selectSettingsDirectory,
  DESKTOP_IPC.selectSettingsColor,
  DESKTOP_IPC.executeSettingsAction,
  DESKTOP_IPC.selectDataRootDirectory,
  DESKTOP_IPC.selectSitePackage,
  DESKTOP_IPC.selectSiteExportDestination,
  DESKTOP_IPC.restartBackend,
  DESKTOP_IPC.chooseSavePath,
  DESKTOP_IPC.downloadBackendResource,
  DESKTOP_IPC.executeFileDesktopAction,
  DESKTOP_IPC.openOnlineMrSessionLocation,
  DESKTOP_IPC.openPath,
  DESKTOP_IPC.showItemInFolder,
  DESKTOP_IPC.openExternalUrl,
  DESKTOP_IPC.rendererRecoveryState,
])
