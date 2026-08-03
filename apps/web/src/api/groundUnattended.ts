import { ApiRequestError, apiRequest, getHealth } from './client'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  GroundActionResponse, GroundArchive, GroundArchiveDetail, GroundDeepCollection, GroundPage, GroundPingTarget,
  GroundProfile, GroundStatus, GroundTimelineEvent, GroundTrain, GroundHealth, GroundInventorySummary, GroundRawFile, GroundTrainPolicy,
  GroundOperation, GroundPingSeries, GroundPingSample, GroundRun, GroundSyslogRecord, GroundPagedResult,
  GroundSyslogDeleteAccepted, GroundSyslogDeletePreview, GroundSyslogDeletePreviewRequest,
  GroundMrRuntimeStatus,
  GroundSyslogTransportStatus, LocalIpv4Address, SourceIpRecommendation, UdpPortCheck,
} from '../types/groundUnattended'

const root = '/api/rail-transit/ground-unattended'

export interface GroundRawQueryTransportState {
  code: string
  requestId: string
  backendState: 'ONLINE' | 'OFFLINE' | 'UNKNOWN'
}

export async function probeGroundRawQueryTransportState(reason: unknown): Promise<GroundRawQueryTransportState> {
  const requestId = reason instanceof ApiRequestError
    ? String(reason.details.request_id || '')
    : ''
  let code = reason instanceof ApiRequestError ? reason.code : 'UNKNOWN_ERROR'
  let backendState: GroundRawQueryTransportState['backendState'] = 'UNKNOWN'
  if (
    reason instanceof ApiRequestError
    && [
      'BACKEND_CONNECTION_INTERRUPTED',
      'CONNECTION_RESET',
      'RAW_QUERY_TIMEOUT',
      'BACKEND_RESTARTED',
    ].includes(reason.code)
  ) {
    try {
      await getHealth()
      backendState = 'ONLINE'
    } catch {
      backendState = 'OFFLINE'
      code = 'BACKEND_UNREACHABLE'
    }
  } else if (reason instanceof ApiRequestError && reason.status > 0) {
    backendState = 'ONLINE'
  }
  return { code, requestId, backendState }
}

export const probeGroundSyslogTransportState = probeGroundRawQueryTransportState

export const getGroundStatus = (options: RequestInit = {}): Promise<GroundStatus> => apiRequest(`${root}/status`, options)
export const getGroundProfile = (options: RequestInit = {}): Promise<GroundProfile> => apiRequest(`${root}/profile`, options)
export const saveGroundProfile = (value: GroundProfile & { external_syslog_address_confirmation?: boolean }): Promise<GroundProfile> => apiRequest(`${root}/profile`, { method: 'PUT', body: JSON.stringify(value) })
export const startGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/start`, { method: 'POST' })
export const pauseGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/pause`, { method: 'POST' })
export const resumeGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/resume`, { method: 'POST' })
export const stopGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/stop`, { method: 'POST' })
export const stopAndArchiveGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/stop-and-archive`, { method: 'POST' })
export const listGroundTrains = (options: RequestInit = {}): Promise<GroundPage<GroundTrain>> => apiRequest(`${root}/trains`, options)
export function listGroundMrRuntimeStatus(params: {
  mr_role?: string; radio_state?: string; snmp_state?: string
} = {}, options: RequestInit = {}): Promise<GroundPage<GroundMrRuntimeStatus>> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value) query.set(key, String(value)) })
  return apiRequest(`${root}/mr-runtime-status?${query}`, options)
}
export const syncGroundInventory = (): Promise<GroundInventorySummary> => apiRequest(`${root}/inventory/sync`, { method: 'POST' })
export const getGroundTrain = (trainId: string): Promise<GroundTrain> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}`)
export const setGroundTrainPriority = (trainId: string, priority: boolean): Promise<GroundTrain> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}/priority`, { method: 'PUT', body: JSON.stringify({ priority }) })
export const saveGroundTrainPolicy = (trainId: string, value: GroundTrainPolicy): Promise<GroundTrain> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}/policy`, { method: 'PUT', body: JSON.stringify(value) })
export const requestGroundConfigCheck = (deviceUuid = '', allowTargetPortChange = false): Promise<GroundActionResponse> => apiRequest(`${root}/config-check`, {
  method: 'POST',
  body: JSON.stringify({
    device_uuid: deviceUuid,
    allow_target_port_change: allowTargetPortChange,
    explicit_confirmation: allowTargetPortChange,
  }),
})
export const getGroundHealth = (options: RequestInit = {}): Promise<GroundHealth> => apiRequest(`${root}/health`, options)
export const getGroundSyslogTransportStatus = (options: RequestInit = {}): Promise<GroundSyslogTransportStatus> => apiRequest(`${root}/syslog-transport-status`, options)
export const listGroundRawFiles = (options: RequestInit = {}): Promise<GroundPage<GroundRawFile>> => apiRequest(`${root}/raw-files?limit=100`, options)
export const listGroundRuns = (options: RequestInit = {}): Promise<GroundPage<GroundRun>> => apiRequest(`${root}/runs?limit=200`, options)
export const deleteGroundRunHistory = (runId: string): Promise<GroundActionResponse> => apiRequest(`${root}/runs/${encodeURIComponent(runId)}`, { method: 'DELETE', body: JSON.stringify({ explicit_confirmation: true }) })
export const listGroundPingTargets = (runId = '', options: RequestInit = {}): Promise<GroundPage<GroundPingTarget>> => {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
  return apiRequest(`${root}/ping-targets${query}`, options)
}
export function getGroundPingSeries(params: {
  run_id?: string; train_id?: string; mr_id?: string; target_ip?: string; query_identity?: string; start_time?: string; end_time?: string
  include_warmup?: boolean; max_points?: number
}, options: RequestInit = {}): Promise<GroundPingSeries> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/ping-series?${query}`, options)
}
export function getGroundPingSeriesIncremental(params: {
  run_id: string; train_id?: string; mr_id?: string; target_ip?: string; query_identity?: string; cursor?: string
  after_sequence?: number | null; after_timestamp?: string; include_warmup?: boolean; max_points?: number
}, options: RequestInit = {}): Promise<GroundPingSeries> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/ping-series/incremental?${query}`, options)
}
export function listGroundPingSamples(params: {
  run_id?: string; train_id?: string; mr_id?: string; target_ip?: string; query_identity?: string; start_time?: string; end_time?: string
  include_warmup?: boolean; page?: number; page_size?: number
}, options: RequestInit = {}): Promise<GroundPagedResult<GroundPingSample> & { raw_sample_count: number; effective_sample_count: number; ignored_sample_count: number }> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/ping-samples?${query}`, options)
}
export function listGroundSyslogRecords(params: {
  run_id?: string; train_id?: string; mr_id?: string; mr_name?: string; source_ip?: string; system_name?: string
  mr_role?: string; facility?: string; severity?: string; identity_status?: string; event_type?: string; peer_name?: string
  event_family?: string; cfg_command_source?: string; physical_state?: string
  correlation_status?: string; correlation_confidence?: string
  data_source?: string; keyword?: string; start_time?: string; end_time?: string; page?: number; page_size?: number
}, options: RequestInit = {}): Promise<GroundPagedResult<GroundSyslogRecord>> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/syslog-records?${query}`, options)
}
export const previewGroundSyslogDelete = (
  request: GroundSyslogDeletePreviewRequest,
): Promise<GroundSyslogDeletePreview> => apiRequest(`${root}/syslog-delete-preview`, {
  method: 'POST',
  body: JSON.stringify({
    ...request,
    record_keys: request.record_keys ?? [],
    filters: request.filters ?? {},
  }),
})
export const submitGroundSyslogDelete = (request: {
  preview_token: string
  explicit_confirmation: boolean
  confirmation_text: string
  include_derived_events: boolean
}): Promise<GroundSyslogDeleteAccepted> => apiRequest(`${root}/syslog-delete`, {
  method: 'POST',
  body: JSON.stringify(request),
})
export const getLatestGroundOperation = (options: RequestInit = {}): Promise<GroundOperation | null> => apiRequest(`${root}/operations/latest`, options)
export const getActiveGroundOperation = (options: RequestInit = {}): Promise<GroundOperation | null> => apiRequest(`${root}/operations/active`, options)
export const getGroundOperation = (operationId: string, options: RequestInit = {}): Promise<GroundOperation> => apiRequest(`${root}/operations/${encodeURIComponent(operationId)}`, options)
export const listGroundDeepCollections = (runId = '', options: RequestInit = {}): Promise<GroundPage<GroundDeepCollection>> => {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
  return apiRequest(`${root}/deep-collections${query}`, options)
}
export function listGroundTimeline(
  trainId = '',
  eventType = '',
  runId = '',
  options: RequestInit = {},
  page = 1,
  pageSize = 100,
  query = '',
): Promise<GroundPagedResult<GroundTimelineEvent>> {
  const params = new URLSearchParams()
  if (trainId) params.set('train_id', trainId)
  if (eventType) params.set('event_type', eventType)
  if (runId) params.set('run_id', runId)
  if (query) params.set('query', query)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiRequest(`${root}/timeline?${params}`, options)
}
export const listGroundArchives = (options: RequestInit = {}): Promise<GroundPage<GroundArchive>> => apiRequest(`${root}/archives`, options)
export const getGroundArchive = (archiveId: string): Promise<GroundArchive> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}`)
export const getGroundArchiveDetail = (archiveId: string, options: RequestInit = {}): Promise<GroundArchiveDetail> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}/detail`, options)
export const verifyGroundArchive = (archiveId: string): Promise<GroundArchiveDetail> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}/verify`, { method: 'POST' })
export const deleteGroundArchive = (archiveId: string): Promise<GroundActionResponse> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}`, { method: 'DELETE', body: JSON.stringify({ explicit_confirmation: true }) })
export const openGroundArchiveDirectory = (): Promise<{ success: boolean; code: string; message: string }> => apiRequest(`${root}/archives/open-directory`, { method: 'POST' })
export const groundArchiveSummaryDownloadRequest = (row: GroundArchive): BackendDownloadRequest => ({
  apiPath: `${root}/artifacts/${encodeURIComponent(row.archive_id)}/summary-download`,
  suggestedName: `${row.run_date}_ground_unattended_summary.json`,
  filters: [{ name: 'JSON 汇总', extensions: ['json'] }],
})
export const groundArchiveZipDownloadRequest = (row: GroundArchive): BackendDownloadRequest => ({
  apiPath: `${root}/artifacts/${encodeURIComponent(row.archive_id)}/download`,
  suggestedName: `${row.run_date}_ground_unattended.zip`,
  filters: [{ name: 'ZIP 归档', extensions: ['zip'] }],
  expectedSizeBytes: row.archive_size_bytes,
  expectedSha256: row.sha256,
})

const networkRoot = '/api/system/network'
export const listLocalIpv4Addresses = (): Promise<{ items: LocalIpv4Address[]; total: number; generated_at: string }> => apiRequest(`${networkRoot}/ipv4-addresses`)
export const recommendLocalSourceIp = (targetIps: string[], preferredIp = ''): Promise<SourceIpRecommendation> => apiRequest(`${networkRoot}/recommend-source-ip`, {
  method: 'POST',
  body: JSON.stringify({ target_ips: targetIps, preferred_ip: preferredIp }),
})
export const checkGroundUdpPort = (listenHost: string, listenPort: number): Promise<UdpPortCheck> => apiRequest(`${networkRoot}/check-udp-port`, {
  method: 'POST',
  body: JSON.stringify({ listen_host: listenHost, listen_port: listenPort }),
})
