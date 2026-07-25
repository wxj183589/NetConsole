import { UI_PREFERENCE_KEYS } from './bridge'
import type {
  BackendDownloadRequest,
  ChooseSavePathOptions,
  RendererHostReport,
  RendererWorkloadReport,
  FileFilter,
  RendererReadyReport,
  SelectFileOptions,
  TaskWindowContext,
  WorkspaceWindowOpenRequest,
  WorkspaceWindowSnapshot,
  WorkspaceTabSnapshot,
  UiPreferenceKey,
  SettingsActionId, SettingsDirectoryId, SettingsToolId,
  SiteStorageRestartRequest,
} from './bridge'

const MAX_FILTERS = 20
const MAX_EXTENSIONS = 32
const FILTER_NAME_MAX = 80
const EXTENSION_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/
const INVALID_FILE_NAME_RE = /[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069<>:"/\\|?*]/
const QUERY_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/
const SENSITIVE_QUERY_KEY_RE = /(?:token|password|secret|authorization|community|passphrase)/i
const MAX_QUERY_FIELDS = 32
const MAX_QUERY_VALUE_LENGTH = 2_000
const MAX_API_PATH_LENGTH = 4_096
const MAX_WORKSPACE_ROUTE_LENGTH = 2_048
const MAX_WORKSPACE_TITLE_LENGTH = 80
const MAX_WORKSPACE_TABS = 40
const WORKSPACE_ID_RE = /^[A-Za-z0-9_-]{1,100}$/
const WORKSPACE_SAFE_TEXT_RE = /^[^\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]{1,512}$/
const WORKSPACE_INTERNAL_QUERY_KEYS = new Set(['task_window', 'workspace_window', 'workspace_window_id', 'workspace_restore'])
const WORKSPACE_ALLOWED_PATHS = new Set([
  '/',
  '/network/devices',
  '/ac-management/fit-aps',
  '/ac-management/extensions',
  '/rail-transit/wireless-dashboard',
  '/rail-transit/base-data',
  '/rail-transit/train-online',
  '/rail-transit/train-communication',
  '/rail-transit/trackside-ap-business',
  '/rail-transit/mesh-analysis',
  '/rail-transit/online-mr',
  '/rail-transit/online-mr-analysis',
  '/config-center',
  '/device-files',
  '/network-tools/traffic',
  '/network-tools/toolbox',
  '/network-tools/wireless-scan',
  '/tasks',
  '/agents',
  '/settings',
  '/command-reference',
  '/logs',
])
const WINDOWS_RESERVED_NAME_RE = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i
const COMPOUND_ARTIFACT_SUFFIXES = ['.tar.gz', '.zip.gz']
const OPENABLE_ARTIFACT_SUFFIXES = [
  '.tar.gz', '.zip.gz', '.pcapng', '.jsonl',
  '.xlsx', '.pcap', '.diff', '.html', '.json', '.yaml',
  '.csv', '.log', '.nam', '.pdf', '.png', '.txt', '.xls', '.yml',
  '.cfg', '.md', '.tgz', '.zip',
]
const DOWNLOAD_SEGMENT = String.raw`(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+`
const DOWNLOAD_ENDPOINTS = [
  { pattern: new RegExp(`^/api/device-management/exports/${DOWNLOAD_SEGMENT}/download$`), query: new Set(['artifact_id']), required: new Set(['artifact_id']) },
  { pattern: new RegExp(`^/api/config-collection/artifacts/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/file-management/downloads/${DOWNLOAD_SEGMENT}/file$`), query: new Set(['site_id']), required: new Set<string>() },
  { pattern: new RegExp(`^/api/ac-management/extensions/artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/ac-management/fit-aps/omnipeek/artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/rail-transit/mesh-analysis/sessions/${DOWNLOAD_SEGMENT}/artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/rail-transit/trackside-ap-business/artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: /^\/api\/rail-transit\/base-data\/station-template$/, query: new Set(['site_id']), required: new Set<string>() },
  { pattern: /^\/api\/rail-transit\/base-data\/station-template-export$/, query: new Set(['site_id']), required: new Set<string>() },
  { pattern: new RegExp(`^/api/online-mr/report-artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/rail-transit/mesh-analysis/report-artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/network-tools/artifacts/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/network-tools/wireless-scan/artifacts/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/command-reference/artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/system-maintenance/artifacts/${DOWNLOAD_SEGMENT}/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/job-center/artifacts/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
]

export function validateTaskWindowContext(value: unknown): TaskWindowContext {
  if (value === undefined) return {}
  const record = asRecord(value, 'task window context')
  rejectUnknownKeys(record, ['taskId', 'module', 'status'])
  const result: TaskWindowContext = {}
  if (record.taskId !== undefined) {
    if (typeof record.taskId !== 'string' || !/^[A-Za-z0-9_-]{1,160}$/.test(record.taskId)) throw new TypeError('taskId is invalid')
    result.taskId = record.taskId
  }
  if (record.module !== undefined) {
    if (!['devices', 'ac', 'rail', 'config', 'files', 'network', 'command-reference', 'logs'].includes(String(record.module))) throw new TypeError('module is invalid')
    result.module = record.module as TaskWindowContext['module']
  }
  if (record.status !== undefined) {
    if (!['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED'].includes(String(record.status))) throw new TypeError('status is invalid')
    result.status = record.status as TaskWindowContext['status']
  }
  return result
}

export function validateWorkspaceRoute(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('workspace route must be a string')
  const route = value.trim()
  if (
    !route.startsWith('/')
    || route.startsWith('//')
    || route.length > MAX_WORKSPACE_ROUTE_LENGTH
    || /[\\#\u0000-\u001f\u007f]/.test(route)
  ) {
    throw new TypeError('workspace route is invalid')
  }
  let url: URL
  let decodedPath: string
  try {
    const rawDecodedPath = decodeURIComponent(route.split(/[?#]/, 1)[0])
    if (rawDecodedPath.split('/').some((part) => part === '.' || part === '..')) {
      throw new TypeError('workspace route traversal is invalid')
    }
    url = new URL(route, 'http://127.0.0.1')
    decodedPath = decodeURIComponent(url.pathname)
  } catch {
    throw new TypeError('workspace route encoding is invalid')
  }
  if (
    url.origin !== 'http://127.0.0.1'
    || decodedPath.split('/').some((part) => part === '.' || part === '..')
    || (!WORKSPACE_ALLOWED_PATHS.has(decodedPath) && !/^\/devices\/[A-Za-z0-9_-]{1,160}$/.test(decodedPath))
  ) {
    throw new TypeError('workspace route is not allowed')
  }
  const query = new URLSearchParams()
  if ([...url.searchParams.keys()].length > MAX_QUERY_FIELDS) {
    throw new TypeError('workspace route has too many query fields')
  }
  for (const key of [...new Set(url.searchParams.keys())].sort()) {
    if (
      !QUERY_KEY_RE.test(key)
      || SENSITIVE_QUERY_KEY_RE.test(key)
      || key === 'confirm_token'
      || WORKSPACE_INTERNAL_QUERY_KEYS.has(key)
      || key.startsWith('__nc_')
    ) {
      throw new TypeError('workspace route query is invalid')
    }
    for (const item of url.searchParams.getAll(key)) {
      if (
        item.length > 1_000
        || /[\u0000-\u001f\u007f]/.test(item)
        || /^(?:[A-Za-z]:[\\/]|\\\\|file:)/i.test(item.trim())
      ) {
        throw new TypeError('workspace route query value is invalid')
      }
      query.append(key, item)
    }
  }
  return `${url.pathname}${query.size ? `?${query.toString()}` : ''}`
}

export function validateWorkspaceTitle(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('workspace title must be a string')
  const title = value
    .replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (
    !title
    || title.length > MAX_WORKSPACE_TITLE_LENGTH
    || /^(?:[A-Za-z]:[\\/]|\\\\|file:)/i.test(title)
    || SENSITIVE_QUERY_KEY_RE.test(title)
    || title.includes('confirm_token')
  ) {
    throw new TypeError('workspace title is invalid')
  }
  return title
}

export function validateWorkspaceWindowOpenRequest(value: unknown): WorkspaceWindowOpenRequest {
  const record = asRecord(value, 'workspace window request')
  rejectUnknownKeys(record, ['routeFullPath', 'title'])
  return {
    routeFullPath: validateWorkspaceRoute(record.routeFullPath),
    title: validateWorkspaceTitle(record.title),
  }
}

export function validateWorkspaceWindowSnapshot(value: unknown): WorkspaceWindowSnapshot {
  const record = asRecord(value, 'workspace window snapshot')
  rejectUnknownKeys(record, ['schemaVersion', 'windowId', 'activeTabId', 'tabs'])
  if (record.schemaVersion !== 1) throw new TypeError('workspace snapshot schema is invalid')
  const windowId = validateWorkspaceId(record.windowId, 'windowId')
  const activeTabId = validateWorkspaceId(record.activeTabId, 'activeTabId')
  if (!Array.isArray(record.tabs) || record.tabs.length === 0 || record.tabs.length > MAX_WORKSPACE_TABS) {
    throw new TypeError('workspace snapshot tabs are invalid')
  }
  const tabs = record.tabs.map(validateWorkspaceTabSnapshot)
  if (!tabs.some((tab) => tab.id === activeTabId)) throw new TypeError('workspace active tab is invalid')
  return { schemaVersion: 1, windowId, activeTabId, tabs }
}

function validateWorkspaceTabSnapshot(value: unknown): WorkspaceTabSnapshot {
  const record = asRecord(value, 'workspace tab snapshot')
  rejectUnknownKeys(record, [
    'id', 'instanceId', 'routeName', 'routeFullPath', 'title', 'identityKey',
    'cacheKey', 'pinned', 'openedAt', 'lastActivatedAt',
  ])
  const id = validateWorkspaceId(record.id, 'tab id')
  const instanceId = validateWorkspaceId(record.instanceId, 'tab instance id')
  if (
    record.routeName !== undefined
    && (typeof record.routeName !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(record.routeName))
  ) {
    throw new TypeError('workspace route name is invalid')
  }
  if (
    typeof record.identityKey !== 'string'
    || !WORKSPACE_SAFE_TEXT_RE.test(record.identityKey)
    || typeof record.cacheKey !== 'string'
    || !WORKSPACE_SAFE_TEXT_RE.test(record.cacheKey)
    || typeof record.pinned !== 'boolean'
    || typeof record.openedAt !== 'number'
    || !Number.isFinite(record.openedAt)
    || typeof record.lastActivatedAt !== 'number'
    || !Number.isFinite(record.lastActivatedAt)
  ) {
    throw new TypeError('workspace tab fields are invalid')
  }
  return {
    id,
    instanceId,
    ...(typeof record.routeName === 'string' ? { routeName: record.routeName } : {}),
    routeFullPath: validateWorkspaceRoute(record.routeFullPath),
    title: validateWorkspaceTitle(record.title),
    identityKey: record.identityKey,
    cacheKey: record.cacheKey,
    pinned: record.pinned,
    openedAt: record.openedAt,
    lastActivatedAt: record.lastActivatedAt,
  }
}

function validateWorkspaceId(value: unknown, label: string): string {
  if (typeof value !== 'string' || !WORKSPACE_ID_RE.test(value)) {
    throw new TypeError(`${label} is invalid`)
  }
  return value
}

export function validateUiPreferenceKey(value: unknown): UiPreferenceKey {
  if (!UI_PREFERENCE_KEYS.includes(value as UiPreferenceKey)) throw new TypeError('UI preference key is invalid')
  return value as UiPreferenceKey
}

export function validateUiPreferenceValue(key: UiPreferenceKey, value: unknown): unknown | null {
  if (value === null) return null
  if (key === 'desktop.close-to-tray') {
    if (typeof value !== 'boolean') throw new TypeError('close-to-tray preference must be a boolean')
    return value
  }
  if (key === 'mesh-analysis-rssi.layout-mode') {
    if (!['compare', 'active-focus', 'trackside-focus'].includes(String(value))) {
      throw new TypeError('UI RSSI layout preference is invalid')
    }
    return value
  }
  if (key === 'mesh-analysis-rssi.compare-split-ratio') {
    if (
      typeof value !== 'number'
      || !Number.isFinite(value)
      || value < 0.25
      || value > 0.75
    ) throw new TypeError('UI RSSI split preference is invalid')
    return value
  }
  if (key.startsWith('mesh-analysis-rssi.') || key.startsWith('mesh-analysis-airload.')) {
    if (typeof value !== 'boolean') throw new TypeError('UI chart preference must be a boolean')
    return value
  }
  const record = asRecord(value, 'table preference')
  rejectUnknownKeys(record, ['version', 'order', 'columns'])
  if (record.version !== 1) throw new TypeError('table preference version is invalid')
  if (!Array.isArray(record.order) || record.order.length > 256 || !record.order.every((item) => typeof item === 'string' && item.length > 0 && item.length <= 128)) {
    throw new TypeError('table preference order is invalid')
  }
  if (!Array.isArray(record.columns) || record.columns.length > 256) throw new TypeError('table preference columns are invalid')
  const columns = record.columns.map((item) => {
    const column = asRecord(item, 'table preference column')
    rejectUnknownKeys(column, ['key', 'width', 'visible', 'fixed'])
    if (typeof column.key !== 'string' || !column.key || column.key.length > 128) throw new TypeError('table preference column key is invalid')
    if (column.width !== undefined && (typeof column.width !== 'number' || !Number.isFinite(column.width) || column.width <= 0 || column.width > 10_000)) throw new TypeError('table preference column width is invalid')
    if (column.visible !== undefined && typeof column.visible !== 'boolean') throw new TypeError('table preference column visibility is invalid')
    if (column.fixed !== undefined && column.fixed !== false && column.fixed !== 'left' && column.fixed !== 'right') throw new TypeError('table preference column fixed state is invalid')
    return {
      key: column.key,
      ...(column.width === undefined ? {} : { width: column.width }),
      ...(column.visible === undefined ? {} : { visible: column.visible }),
      ...(column.fixed === undefined ? {} : { fixed: column.fixed }),
    }
  })
  return { version: 1, order: [...record.order], columns }
}

export function validateSelectFileOptions(value: unknown): SelectFileOptions {
  if (value === undefined) return {}
  const record = asRecord(value, 'file selection options')
  rejectUnknownKeys(record, ['filters', 'multiple'])
  if (record.multiple !== undefined && typeof record.multiple !== 'boolean') {
    throw new TypeError('multiple must be a boolean')
  }
  return {
    ...(record.filters === undefined ? {} : { filters: validateFilters(record.filters) }),
    ...(record.multiple === undefined ? {} : { multiple: record.multiple }),
  }
}

export function validateSettingsToolId(value: unknown): SettingsToolId {
  if (!['iperf3', 'fping', 'ipop', 'securecrt', 'xshell', 'putty'].includes(String(value))) {
    throw new TypeError('settings tool id is invalid')
  }
  return value as SettingsToolId
}

export function validateSettingsDirectoryId(value: unknown): SettingsDirectoryId {
  if (value !== 'securecrt_sessions_root') throw new TypeError('settings directory id is invalid')
  return value
}

export function validateSettingsActionId(value: unknown): SettingsActionId {
  if (!['open_settings_config', 'open_current_site', 'launch_ipop'].includes(String(value))) {
    throw new TypeError('settings action id is invalid')
  }
  return value as SettingsActionId
}

export function validateOnlineMrSessionId(value: unknown): string {
  if (
    typeof value !== 'string'
    || !/^[0-9A-Za-z][0-9A-Za-z_.-]{0,159}$/.test(value)
    || value === '.'
    || value === '..'
  ) {
    throw new TypeError('Online MR session id is invalid')
  }
  return value
}

export function validateSiteStorageRestartRequest(value: unknown): SiteStorageRestartRequest {
  const record = asRecord(value, 'site storage restart request')
  rejectUnknownKeys(record, ['dataRoot', 'activeSiteId'])
  const result: SiteStorageRestartRequest = {}
  if (record.dataRoot !== undefined) {
    const dataRoot = validateBridgePath(record.dataRoot)
    if (!/^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(dataRoot)) throw new TypeError('dataRoot must be absolute')
    result.dataRoot = dataRoot
  }
  if (record.activeSiteId !== undefined) result.activeSiteId = validateSiteId(record.activeSiteId, 'activeSiteId')
  if (!result.dataRoot && !result.activeSiteId) throw new TypeError('storage restart request is empty')
  return result
}

export function validateSiteId(value: unknown, fieldName = 'siteId'): string {
  if (typeof value !== 'string' || !/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(value)) {
    throw new TypeError(`${fieldName} is invalid`)
  }
  return value
}

export function validateChooseSavePathOptions(value: unknown): ChooseSavePathOptions {
  const record = asRecord(value, 'save path options')
  rejectUnknownKeys(record, ['suggestedName', 'filters', 'directoryPath'])
  if (typeof record.suggestedName !== 'string') {
    throw new TypeError('suggestedName must be a string')
  }
  const suggestedName = record.suggestedName.trim()
  if (
    !suggestedName
    || suggestedName.length > 180
    || suggestedName === '.'
    || suggestedName === '..'
    || INVALID_FILE_NAME_RE.test(suggestedName)
  ) {
    throw new TypeError('suggestedName must be a safe file name')
  }
  return {
    suggestedName,
    ...(record.filters === undefined ? {} : { filters: validateFilters(record.filters) }),
    ...(record.directoryPath === undefined ? {} : { directoryPath: validateBridgePath(record.directoryPath) }),
  }
}

export function validateBackendDownloadRequest(value: unknown): BackendDownloadRequest {
  const record = asRecord(value, 'backend download request')
  rejectUnknownKeys(record, ['apiPath', 'query', 'suggestedName', 'filters', 'destinationPath'])
  const saveOptions = validateChooseSavePathOptions({
    suggestedName: record.suggestedName,
    ...(record.filters === undefined ? {} : { filters: record.filters }),
  })
  const apiPath = validateBackendApiPath(record.apiPath)
  const query = record.query === undefined ? undefined : validateQuery(record.query)
  validateArtifactEndpoint(apiPath, query ?? {})
  validateArtifactFileName(saveOptions.suggestedName)
  return {
    apiPath,
    ...(query === undefined ? {} : { query }),
    ...saveOptions,
    ...(record.destinationPath === undefined ? {} : { destinationPath: validateBridgePath(record.destinationPath) }),
  }
}

export function buildBackendRequestPath(value: BackendDownloadRequest): string {
  const request = validateBackendDownloadRequest(value)
  const query = new URLSearchParams(request.query)
  const text = query.toString()
  return `${request.apiPath}${text ? `?${text}` : ''}`
}

export function validateBridgePath(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('path must be a string')
  const candidate = value.trim()
  if (!candidate || candidate.length > 32_767 || /[\u0000-\u001f]/.test(candidate)) {
    throw new TypeError('path is invalid')
  }
  return candidate
}

export function validateArtifactFileName(value: string): string {
  const name = validateChooseSavePathOptions({ suggestedName: value }).suggestedName
  if (WINDOWS_RESERVED_NAME_RE.test(name) || name.endsWith('.') || name.endsWith(' ')) {
    throw new TypeError('suggestedName must be a safe Artifact file name')
  }
  const lower = name.toLocaleLowerCase()
  const compound = COMPOUND_ARTIFACT_SUFFIXES.find((suffix) => lower.endsWith(suffix))
  if (compound) return compound
  const lastDot = name.lastIndexOf('.')
  return lastDot <= 0 ? '<none>' : lower.slice(lastDot)
}

export function isOpenableArtifactFileName(value: string): boolean {
  validateArtifactFileName(value)
  const lower = value.toLocaleLowerCase()
  return OPENABLE_ARTIFACT_SUFFIXES.some((suffix) => lower.endsWith(suffix))
}

export function validateCapabilityId(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
    throw new TypeError('capabilityId is invalid')
  }
  return value
}

export function validateFileDesktopActionRef(value: unknown): string {
  if (typeof value !== 'string' || !/^fda1_[0-9a-f]{32}$/.test(value)) {
    throw new TypeError('file desktop action reference is invalid')
  }
  return value
}

export function validateExternalUrl(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('url must be a string')
  const candidate = value.trim()
  if (!candidate || candidate.length > 2_048 || /[\u0000-\u001f]/.test(candidate)) {
    throw new TypeError('url is invalid')
  }
  let parsed: URL
  try {
    parsed = new URL(candidate)
  } catch {
    throw new TypeError('url is invalid')
  }
  if (
    parsed.protocol !== 'https:'
    || !parsed.hostname
    || parsed.username
    || parsed.password
  ) {
    throw new TypeError('desktop bridge only allows credential-free HTTPS urls')
  }
  return parsed.href
}

export function validateRendererReadyReport(value: unknown): RendererHostReport {
  const record = asRecord(value, 'renderer ready report')
  if ('resolvedTheme' in record) {
    rejectUnknownKeys(record, ['resolvedTheme'])
    if (record.resolvedTheme !== 'light' && record.resolvedTheme !== 'dark') {
      throw new TypeError('resolved theme is invalid')
    }
    return { resolvedTheme: record.resolvedTheme }
  }
  rejectUnknownKeys(record, ['healthOk', 'phase', 'surface'])
  if (typeof record.healthOk !== 'boolean') throw new TypeError('healthOk must be a boolean')
  if (!['mounted', 'interactive', 'failed'].includes(String(record.phase))) {
    throw new TypeError('renderer phase is invalid')
  }
  if (record.surface !== undefined && !['main', 'task-window', 'workspace-window'].includes(String(record.surface))) {
    throw new TypeError('renderer surface is invalid')
  }
  return {
    healthOk: record.healthOk,
    phase: record.phase as RendererReadyReport['phase'],
    ...(record.surface === undefined ? {} : { surface: record.surface as RendererReadyReport['surface'] }),
  }
}

const RENDERER_WORKLOAD_PHASES = new Set<RendererWorkloadReport['phase']>([
  'session-selected',
  'trackside-request-started',
  'trackside-response-received',
  'trackside-cache-building',
  'trackside-cache-ready',
  'echarts-init',
  'echarts-set-option',
  'echarts-interactive',
  'chart-disposed',
])

export function validateRendererWorkloadReport(value: unknown): RendererWorkloadReport {
  const record = asRecord(value, 'renderer workload report')
  rejectUnknownKeys(record, [
    'module',
    'route',
    'phase',
    'sessionId',
    'sourceFileId',
    'radio',
    'totalFrames',
    'returnedFrames',
    'totalLinkPoints',
    'returnedLinkPoints',
    'seriesCount',
    'pointCount',
    'metadataCount',
    'conflictEdgeCount',
    'echartsInstanceCount',
    'canvasCount',
    'meshInstanceCount',
    'tracksideCacheCount',
    'tracksideChartCount',
    'activeDetailRequests',
    'tracksideCacheBuildCount',
    'tracksideCacheDisposeCount',
    'chartInitCount',
    'chartDisposeCount',
    'viewportStart',
    'viewportEnd',
    'heapUsedBytes',
    'heapTotalBytes',
    'heapLimitBytes',
    'reportRevision',
  ])
  if (record.module !== 'mesh-analysis') throw new TypeError('renderer workload module is invalid')
  if (record.route !== '/rail-transit/mesh-analysis') throw new TypeError('renderer workload route is invalid')
  if (!RENDERER_WORKLOAD_PHASES.has(record.phase as RendererWorkloadReport['phase'])) {
    throw new TypeError('renderer workload phase is invalid')
  }
  const result: RendererWorkloadReport = {
    module: 'mesh-analysis',
    route: '/rail-transit/mesh-analysis',
    phase: record.phase as RendererWorkloadReport['phase'],
    reportRevision: boundedInteger(record.reportRevision, 'reportRevision', 1, 2_147_483_647),
  }
  if (record.sessionId !== undefined) {
    if (typeof record.sessionId !== 'string' || !/^[0-9A-Za-z][0-9A-Za-z_.:-]{0,159}$/.test(record.sessionId)) {
      throw new TypeError('renderer workload sessionId is invalid')
    }
    result.sessionId = record.sessionId
  }
  if (record.sourceFileId !== undefined) {
    result.sourceFileId = boundedInteger(record.sourceFileId, 'sourceFileId', 1, 2_147_483_647)
  }
  if (record.radio !== undefined) {
    result.radio = record.radio === null ? null : boundedInteger(record.radio, 'radio', 0, 255)
  }
  for (const field of [
    'totalFrames',
    'returnedFrames',
    'totalLinkPoints',
    'returnedLinkPoints',
    'seriesCount',
    'pointCount',
    'metadataCount',
    'conflictEdgeCount',
    'echartsInstanceCount',
    'canvasCount',
    'meshInstanceCount',
    'tracksideCacheCount',
    'tracksideChartCount',
    'activeDetailRequests',
    'tracksideCacheBuildCount',
    'tracksideCacheDisposeCount',
    'chartInitCount',
    'chartDisposeCount',
  ] as const) {
    if (record[field] !== undefined) result[field] = boundedInteger(record[field], field, 0, 100_000_000)
  }
  for (const field of ['heapUsedBytes', 'heapTotalBytes', 'heapLimitBytes'] as const) {
    if (record[field] !== undefined) result[field] = boundedInteger(record[field], field, 0, Number.MAX_SAFE_INTEGER)
  }
  for (const field of ['viewportStart', 'viewportEnd'] as const) {
    if (record[field] === undefined) continue
    if (
      typeof record[field] !== 'string'
      || record[field].length > 64
      || !/^[0-9TZ: .+-]+$/.test(record[field])
    ) throw new TypeError(`renderer workload ${field} is invalid`)
    result[field] = record[field]
  }
  return result
}

function boundedInteger(
  value: unknown,
  field: string,
  minimum: number,
  maximum: number,
): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum || Number(value) > maximum) {
    throw new TypeError(`renderer workload ${field} is invalid`)
  }
  return Number(value)
}

function validateFilters(value: unknown): FileFilter[] {
  if (!Array.isArray(value) || value.length > MAX_FILTERS) {
    throw new TypeError(`filters must contain at most ${MAX_FILTERS} entries`)
  }
  return value.map((item) => {
    const record = asRecord(item, 'file filter')
    rejectUnknownKeys(record, ['name', 'extensions'])
    if (
      typeof record.name !== 'string'
      || !record.name.trim()
      || record.name.trim().length > FILTER_NAME_MAX
    ) {
      throw new TypeError('filter name is invalid')
    }
    if (
      !Array.isArray(record.extensions)
      || record.extensions.length === 0
      || record.extensions.length > MAX_EXTENSIONS
      || record.extensions.some((extension) => typeof extension !== 'string' || !EXTENSION_RE.test(extension))
    ) {
      throw new TypeError('filter extensions are invalid')
    }
    return {
      name: record.name.trim(),
      extensions: [...record.extensions] as string[],
    }
  })
}

function validateBackendApiPath(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('apiPath must be a string')
  const candidate = value.trim()
  if (
    !candidate.startsWith('/api/')
    || candidate.length > MAX_API_PATH_LENGTH
    || /[\\?#\u0000-\u001f]/.test(candidate)
    || candidate.includes('//')
  ) {
    throw new TypeError('apiPath must be a safe relative /api path')
  }
  let decoded: string
  try {
    decoded = decodeURIComponent(candidate)
  } catch {
    throw new TypeError('apiPath contains invalid escaping')
  }
  if (decoded.split('/').some((part) => part === '.' || part === '..')) {
    throw new TypeError('apiPath traversal is not allowed')
  }
  const parsed = new URL(candidate, 'http://127.0.0.1')
  if (parsed.origin !== 'http://127.0.0.1' || parsed.pathname !== candidate) {
    throw new TypeError('apiPath must be a safe relative /api path')
  }
  return candidate
}

function validateArtifactEndpoint(apiPath: string, query: Record<string, string>): void {
  const endpoint = DOWNLOAD_ENDPOINTS.find(({ pattern }) => pattern.test(apiPath))
  if (
    !endpoint
    || Object.keys(query).some((key) => !endpoint.query.has(key))
    || [...(endpoint?.required ?? [])].some((key) => !query[key])
  ) {
    throw new TypeError('apiPath must be an approved Artifact download endpoint')
  }
}

function validateQuery(value: unknown): Record<string, string> {
  const record = asRecord(value, 'download query')
  const entries = Object.entries(record)
  if (entries.length > MAX_QUERY_FIELDS) {
    throw new TypeError(`download query must contain at most ${MAX_QUERY_FIELDS} fields`)
  }
  const result: Record<string, string> = {}
  for (const [key, item] of entries) {
    if (!QUERY_KEY_RE.test(key) || SENSITIVE_QUERY_KEY_RE.test(key)) {
      throw new TypeError('download query key is invalid')
    }
    if (
      typeof item !== 'string'
      || item.length > MAX_QUERY_VALUE_LENGTH
      || /[\u0000-\u001f]/.test(item)
    ) {
      throw new TypeError('download query value is invalid')
    }
    result[key] = item
  }
  return result
}

function asRecord(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`)
  }
  return value as Record<string, unknown>
}

function rejectUnknownKeys(record: Record<string, unknown>, allowed: string[]): void {
  const unknown = Object.keys(record).filter((key) => !allowed.includes(key))
  if (unknown.length) throw new TypeError(`unsupported field: ${unknown[0]}`)
}
