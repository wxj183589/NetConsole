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
  availability?: 'AVAILABLE' | 'MISSING' | 'INVALID'
}

export type ExternalToolStatus = 'AVAILABLE' | 'MISSING' | 'INVALID' | 'WORKDIR_MISSING'
export type ExternalToolIconMode = 'auto' | 'default' | 'custom'
export type ExternalToolLaunchMode = 'normal' | 'administrator'
export type ExternalToolLaunchPrivilege = 'normal' | 'ask' | 'administrator'
export type ExternalToolSourceType = 'independent' | 'system_setting'
export type ExternalToolSystemSettingKey = 'securecrt' | 'xshell' | 'putty'

export interface ExternalToolCategory {
  id: string
  name: string
  sort_order: number
  builtin: boolean
}

export interface ExternalToolRecord {
  id: string
  name: string
  source_type: ExternalToolSourceType
  source_key: ExternalToolSystemSettingKey | null
  executable_path: string | null
  arguments: string[]
  working_directory: string | null
  category_id: string
  favorite: boolean
  sort_order: number
  icon_mode: ExternalToolIconMode
  custom_icon_path: string | null
  launch_privilege: ExternalToolLaunchPrivilege
  launch_count: number
  administrator_launch_count: number
  last_launched_at: string | null
  last_launch_mode: ExternalToolLaunchMode | null
  created_at: string
  updated_at: string
}

export interface ExternalToolView extends Omit<ExternalToolRecord, 'executable_path' | 'working_directory'> {
  executable_path: string
  working_directory: string
  category_name: string
  executable_name: string
  status: ExternalToolStatus
  status_message: string
  icon_data_url: string | null
}

export interface ExternalToolCreateRequest {
  name: string
  executablePath: string
  arguments: string[]
  workingDirectory?: string
  categoryId: string
  favorite: boolean
  iconMode: ExternalToolIconMode
  iconSelectionId?: string
  launchPrivilege: ExternalToolLaunchPrivilege
}

export interface ExternalToolUpdateRequest extends Omit<ExternalToolCreateRequest, 'executablePath'> {
  id: string
  executablePath?: string
}

export interface ExternalToolSystemReferenceCreateRequest {
  sourceKey: ExternalToolSystemSettingKey
}

export interface ExternalToolLaunchRequest {
  toolId: string
  launchMode: ExternalToolLaunchMode
}

export interface ExternalToolReorderRequest {
  categoryId: string
  toolIds: string[]
}

export interface ExternalToolCategoryReorderRequest {
  categoryIds: string[]
}

export interface ExternalToolDeleteCategoryRequest {
  categoryId: string
  moveToolsToOther: boolean
}

export interface ExternalToolListResult {
  schema_version: 2
  categories: ExternalToolCategory[]
  tools: ExternalToolView[]
}

export interface ExternalToolSelectionResult {
  cancelled: boolean
  path?: string
  suggestedName?: string
  workingDirectory?: string
  iconDataUrl?: string | null
  duplicateTool?: Pick<ExternalToolView, 'id' | 'name'>
}

export interface ExternalToolIconSelectionResult {
  cancelled: boolean
  selectionId?: string
  iconDataUrl?: string
}

export interface ExternalToolMutationResult {
  success: boolean
  tool?: ExternalToolView
  list?: ExternalToolListResult
  errorCode?: 'DUPLICATE_PATH' | 'DUPLICATE_SOURCE' | 'INVALID_REQUEST' | 'NOT_FOUND' | 'PERSISTENCE_FAILED'
  error?: string
  existingTool?: Pick<ExternalToolView, 'id' | 'name'>
}

export interface ExternalToolLaunchResult extends NativeActionResult {
  toolId: string
  status?: ExternalToolStatus | 'cancelled'
  errorCode?: 'ELEVATION_CANCELLED'
}

export type SettingsToolId = 'iperf3' | 'fping' | 'securecrt' | 'xshell' | 'putty'
export type SettingsDirectoryId = 'securecrt_sessions_root'
export type SettingsActionId = 'open_settings_config' | 'open_current_site'
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
  | 'SAVE_TARGET_CHANGED'
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
  surface?: 'main' | 'workspace-window'
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

export interface TaskNotificationPayload {
  eventId: string
  taskId: string
  title: string
  body: string
  kind: 'success' | 'warning' | 'failure'
}

export interface TaskTrayStatus {
  active: number
  failed: number
  warning: number
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
  'device-management.device-list',
  'device-detail.interfaces',
  'device-detail.optical-modules',
  'device-detail.lldp',
  'device-detail.task-records',
  'device-detail.related-businesses',
  'rail.trackside-ap-business.table.main',
  'rail.trackside-ap-business.table.scope-excluded',
  'rail.trackside-ap-business.table.unmatched-online',
] as const)

export type UiPreferenceKey = typeof UI_PREFERENCE_KEYS[number]

export interface NetConsoleDesktopBridge {
  getAppInfo(): Promise<AppInfo>
  getBackendStatus(): Promise<BackendStatus>
  getRuntimeConfig(): Promise<DesktopRuntimeConfig>
  getUiPreference?(key: UiPreferenceKey): Promise<unknown | null>
  setUiPreference?(key: UiPreferenceKey, value: unknown | null): Promise<void>
  openTaskWindow(context?: TaskWindowContext): Promise<NativeActionResult>
  showTaskNotification(payload: TaskNotificationPayload): Promise<NativeActionResult>
  setTaskTrayStatus(status: TaskTrayStatus): void
  onTaskCenterOpenRequested?(listener: (context: TaskWindowContext) => void): () => void
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
  listExternalTools(): Promise<ExternalToolListResult>
  selectExternalToolExecutable(): Promise<ExternalToolSelectionResult>
  selectExternalToolWorkingDirectory(): Promise<SelectDirectoryResult>
  selectExternalToolIcon(): Promise<ExternalToolIconSelectionResult>
  createExternalTool(request: ExternalToolCreateRequest): Promise<ExternalToolMutationResult>
  createExternalToolSystemReference(request: ExternalToolSystemReferenceCreateRequest): Promise<ExternalToolMutationResult>
  updateExternalTool(request: ExternalToolUpdateRequest): Promise<ExternalToolMutationResult>
  deleteExternalTool(toolId: string): Promise<ExternalToolMutationResult>
  setExternalToolFavorite(toolId: string, favorite: boolean): Promise<ExternalToolMutationResult>
  reorderExternalTools(request: ExternalToolReorderRequest): Promise<ExternalToolMutationResult>
  reorderExternalToolCategories(request: ExternalToolCategoryReorderRequest): Promise<ExternalToolMutationResult>
  createExternalToolCategory(name: string): Promise<ExternalToolMutationResult>
  renameExternalToolCategory(categoryId: string, name: string): Promise<ExternalToolMutationResult>
  deleteExternalToolCategory(request: ExternalToolDeleteCategoryRequest): Promise<ExternalToolMutationResult>
  launchExternalTool(request: ExternalToolLaunchRequest): Promise<ExternalToolLaunchResult>
  revealExternalTool(toolId: string): Promise<ExternalToolLaunchResult>
  refreshExternalToolStatuses(): Promise<ExternalToolListResult>
  openOnlineMrSessionLocation?(sessionId: string): Promise<NativeActionResult>
  openPath(capabilityId: string): Promise<NativeActionResult>
  showItemInFolder(capabilityId: string): Promise<NativeActionResult>
  openExternalUrl(url: string): Promise<NativeActionResult>
  writeClipboardText?(text: string): Promise<NativeActionResult>
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
  showTaskNotification: 'netconsole:desktop:show-task-notification',
  setTaskTrayStatus: 'netconsole:desktop:set-task-tray-status',
  taskCenterOpenRequested: 'netconsole:desktop:task-center-open-requested',
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
  listExternalTools: 'netconsole:desktop:external-tools:list',
  selectExternalToolExecutable: 'netconsole:desktop:external-tools:select-executable',
  selectExternalToolWorkingDirectory: 'netconsole:desktop:external-tools:select-working-directory',
  selectExternalToolIcon: 'netconsole:desktop:external-tools:select-icon',
  createExternalTool: 'netconsole:desktop:external-tools:create',
  createExternalToolSystemReference: 'netconsole:desktop:external-tools:create-system-reference',
  updateExternalTool: 'netconsole:desktop:external-tools:update',
  deleteExternalTool: 'netconsole:desktop:external-tools:delete',
  setExternalToolFavorite: 'netconsole:desktop:external-tools:set-favorite',
  reorderExternalTools: 'netconsole:desktop:external-tools:reorder',
  reorderExternalToolCategories: 'netconsole:desktop:external-tools:reorder-categories',
  createExternalToolCategory: 'netconsole:desktop:external-tools:create-category',
  renameExternalToolCategory: 'netconsole:desktop:external-tools:rename-category',
  deleteExternalToolCategory: 'netconsole:desktop:external-tools:delete-category',
  launchExternalTool: 'netconsole:desktop:external-tools:launch',
  revealExternalTool: 'netconsole:desktop:external-tools:reveal',
  refreshExternalToolStatuses: 'netconsole:desktop:external-tools:refresh-statuses',
  openOnlineMrSessionLocation: 'netconsole:desktop:open-online-mr-session-location',
  openPath: 'netconsole:desktop:open-path',
  showItemInFolder: 'netconsole:desktop:show-item-in-folder',
  openExternalUrl: 'netconsole:desktop:open-external-url',
  writeClipboardText: 'netconsole:desktop:write-clipboard-text',
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
  DESKTOP_IPC.showTaskNotification,
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
  DESKTOP_IPC.listExternalTools,
  DESKTOP_IPC.selectExternalToolExecutable,
  DESKTOP_IPC.selectExternalToolWorkingDirectory,
  DESKTOP_IPC.selectExternalToolIcon,
  DESKTOP_IPC.createExternalTool,
  DESKTOP_IPC.createExternalToolSystemReference,
  DESKTOP_IPC.updateExternalTool,
  DESKTOP_IPC.deleteExternalTool,
  DESKTOP_IPC.setExternalToolFavorite,
  DESKTOP_IPC.reorderExternalTools,
  DESKTOP_IPC.reorderExternalToolCategories,
  DESKTOP_IPC.createExternalToolCategory,
  DESKTOP_IPC.renameExternalToolCategory,
  DESKTOP_IPC.deleteExternalToolCategory,
  DESKTOP_IPC.launchExternalTool,
  DESKTOP_IPC.revealExternalTool,
  DESKTOP_IPC.refreshExternalToolStatuses,
  DESKTOP_IPC.openOnlineMrSessionLocation,
  DESKTOP_IPC.openPath,
  DESKTOP_IPC.showItemInFolder,
  DESKTOP_IPC.openExternalUrl,
  DESKTOP_IPC.writeClipboardText,
  DESKTOP_IPC.rendererRecoveryState,
])
