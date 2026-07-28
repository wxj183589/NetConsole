import { apiRequest } from './client'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  GroundActionResponse, GroundArchive, GroundDeepCollection, GroundPage, GroundPingTarget,
  GroundProfile, GroundStatus, GroundTimelineEvent, GroundTrain, GroundHealth, GroundInventorySummary, GroundRawFile, GroundTrainPolicy,
  GroundOperation, GroundPingSeries, GroundPingSample, GroundSyslogRecord, GroundPagedResult,
  LocalIpv4Address, SourceIpRecommendation, UdpPortCheck,
} from '../types/groundUnattended'

const root = '/api/rail-transit/ground-unattended'

export const getGroundStatus = (): Promise<GroundStatus> => apiRequest(`${root}/status`)
export const getGroundProfile = (): Promise<GroundProfile> => apiRequest(`${root}/profile`)
export const saveGroundProfile = (value: GroundProfile & { external_syslog_address_confirmation?: boolean }): Promise<GroundProfile> => apiRequest(`${root}/profile`, { method: 'PUT', body: JSON.stringify(value) })
export const startGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/start`, { method: 'POST' })
export const pauseGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/pause`, { method: 'POST' })
export const resumeGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/resume`, { method: 'POST' })
export const stopGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/stop`, { method: 'POST' })
export const stopAndArchiveGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/stop-and-archive`, { method: 'POST' })
export const listGroundTrains = (): Promise<GroundPage<GroundTrain>> => apiRequest(`${root}/trains`)
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
export const getGroundHealth = (): Promise<GroundHealth> => apiRequest(`${root}/health`)
export const listGroundRawFiles = (): Promise<GroundPage<GroundRawFile>> => apiRequest(`${root}/raw-files?limit=100`)
export const listGroundPingTargets = (): Promise<GroundPage<GroundPingTarget>> => apiRequest(`${root}/ping-targets`)
export function getGroundPingSeries(params: {
  run_id?: string; train_id?: string; mr_id?: string; target_ip?: string; start_time?: string; end_time?: string
  include_warmup?: boolean; max_points?: number
}): Promise<GroundPingSeries> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/ping-series?${query}`)
}
export function listGroundPingSamples(params: {
  run_id?: string; train_id?: string; mr_id?: string; target_ip?: string; start_time?: string; end_time?: string
  include_warmup?: boolean; page?: number; page_size?: number
}): Promise<GroundPagedResult<GroundPingSample> & { raw_sample_count: number; effective_sample_count: number; ignored_sample_count: number }> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/ping-samples?${query}`)
}
export function listGroundSyslogRecords(params: {
  run_id?: string; train_id?: string; mr_id?: string; mr_name?: string; source_ip?: string; system_name?: string
  severity?: string; keyword?: string; start_time?: string; end_time?: string; page?: number; page_size?: number
}): Promise<GroundPagedResult<GroundSyslogRecord>> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return apiRequest(`${root}/syslog-records?${query}`)
}
export const getLatestGroundOperation = (): Promise<GroundOperation | null> => apiRequest(`${root}/operations/latest`)
export const getGroundOperation = (operationId: string): Promise<GroundOperation> => apiRequest(`${root}/operations/${encodeURIComponent(operationId)}`)
export const listGroundDeepCollections = (): Promise<GroundPage<GroundDeepCollection>> => apiRequest(`${root}/deep-collections`)
export function listGroundTimeline(trainId = '', eventType = ''): Promise<GroundPage<GroundTimelineEvent>> {
  const params = new URLSearchParams()
  if (trainId) params.set('train_id', trainId)
  if (eventType) params.set('event_type', eventType)
  return apiRequest(`${root}/timeline?${params}`)
}
export const listGroundArchives = (): Promise<GroundPage<GroundArchive>> => apiRequest(`${root}/archives`)
export const getGroundArchive = (archiveId: string): Promise<GroundArchive> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}`)
export const deleteGroundArchive = (archiveId: string): Promise<GroundActionResponse> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}`, { method: 'DELETE', body: JSON.stringify({ explicit_confirmation: true }) })
export const openGroundArchiveDirectory = (): Promise<{ success: boolean; code: string; message: string }> => apiRequest(`${root}/archives/open-directory`, { method: 'POST' })
export const groundArchiveSummaryDownloadRequest = (row: GroundArchive): BackendDownloadRequest => ({
  apiPath: `${root}/archives/${encodeURIComponent(row.archive_id)}/summary-download`,
  suggestedName: `${row.run_date}_ground_unattended_summary.json`,
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
