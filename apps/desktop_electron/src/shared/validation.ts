import type {
  BackendDownloadRequest,
  ChooseSavePathOptions,
  FileFilter,
  RendererReadyReport,
  SelectFileOptions,
  TaskWindowContext,
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
  { pattern: new RegExp(`^/api/rail-transit/mesh-analysis/sessions/${DOWNLOAD_SEGMENT}/artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/online-mr/report-artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/rail-transit/mesh-analysis/report-artifacts/${DOWNLOAD_SEGMENT}/download$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/network-tools/artifacts/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
  { pattern: new RegExp(`^/api/network-tools/wireless-scan/artifacts/${DOWNLOAD_SEGMENT}$`), query: new Set<string>(), required: new Set<string>() },
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
    if (!['devices', 'ac', 'rail', 'config', 'files'].includes(String(record.module))) throw new TypeError('module is invalid')
    result.module = record.module as TaskWindowContext['module']
  }
  if (record.status !== undefined) {
    if (!['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED'].includes(String(record.status))) throw new TypeError('status is invalid')
    result.status = record.status as TaskWindowContext['status']
  }
  return result
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

export function validateChooseSavePathOptions(value: unknown): ChooseSavePathOptions {
  const record = asRecord(value, 'save path options')
  rejectUnknownKeys(record, ['suggestedName', 'filters'])
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
  }
}

export function validateBackendDownloadRequest(value: unknown): BackendDownloadRequest {
  const record = asRecord(value, 'backend download request')
  rejectUnknownKeys(record, ['apiPath', 'query', 'suggestedName', 'filters'])
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

export function validateRendererReadyReport(value: unknown): RendererReadyReport {
  const record = asRecord(value, 'renderer ready report')
  rejectUnknownKeys(record, ['healthOk'])
  if (typeof record.healthOk !== 'boolean') throw new TypeError('healthOk must be a boolean')
  return { healthOk: record.healthOk }
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
