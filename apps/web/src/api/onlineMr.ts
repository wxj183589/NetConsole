import { apiRequest } from './client'
import type {
  OnlineMrCollectorStatus,
  OnlineMrBusinessSummary,
  OnlineMrBusinessTable,
  OnlineMrBusinessTablePage,
  OnlineMrManualNote,
  OnlineMrRawFile,
  OnlineMrRawTail,
  OnlineMrRealtimePreview,
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
  OnlineMrMetricPage,
  OnlineMrSwitchRssiPage,
  OnlineMrSwitchRssiSource,
  OnlineMrTimelineEvent,
} from '../types/onlineMr'

interface ApiResponse<T> { ok: boolean; data: T }

const root = '/api/online-mr/sessions'

export async function getCurrentOnlineMrSession(): Promise<OnlineMrSessionDetail | null> {
  return (await apiRequest<ApiResponse<OnlineMrSessionDetail | null>>(`${root}/current`)).data
}

export async function listRecentOnlineMrSessions(limit = 20): Promise<OnlineMrSessionSummary[]> {
  return (await apiRequest<ApiResponse<OnlineMrSessionSummary[]>>(`${root}/recent?limit=${limit}`)).data
}

export async function getOnlineMrSession(sessionId: string, signal?: AbortSignal): Promise<OnlineMrSessionDetail> {
  return (await apiRequest<ApiResponse<OnlineMrSessionDetail>>(`${root}/${encodeURIComponent(sessionId)}`, { signal })).data
}

export async function listOnlineMrCollectors(sessionId: string): Promise<OnlineMrCollectorStatus[]> {
  return (await apiRequest<ApiResponse<OnlineMrCollectorStatus[]>>(`${root}/${encodeURIComponent(sessionId)}/collectors`)).data
}

export async function getOnlineMrPreview(sessionId: string): Promise<OnlineMrRealtimePreview> {
  return (await apiRequest<ApiResponse<OnlineMrRealtimePreview>>(`${root}/${encodeURIComponent(sessionId)}/preview`)).data
}

export async function listOnlineMrRawFiles(sessionId: string, signal?: AbortSignal): Promise<OnlineMrRawFile[]> {
  return (await apiRequest<ApiResponse<OnlineMrRawFile[]>>(`${root}/${encodeURIComponent(sessionId)}/raw-summary`, { signal })).data
}

export async function getOnlineMrRawTail(sessionId: string, name: string, tail = 200, signal?: AbortSignal): Promise<OnlineMrRawTail> {
  const query = new URLSearchParams({ name, tail: String(tail) })
  return (await apiRequest<ApiResponse<OnlineMrRawTail>>(`${root}/${encodeURIComponent(sessionId)}/raw-tail?${query}`, { signal })).data
}

export async function listOnlineMrNotes(sessionId: string): Promise<OnlineMrManualNote[]> {
  return (await apiRequest<ApiResponse<OnlineMrManualNote[]>>(`${root}/${encodeURIComponent(sessionId)}/notes`)).data
}

export async function getOnlineMrBusinessSummary(sessionId: string): Promise<OnlineMrBusinessSummary> {
  return (await apiRequest<ApiResponse<OnlineMrBusinessSummary>>(`${root}/${encodeURIComponent(sessionId)}/business-summary`)).data
}

export interface OnlineMrMetricQuery {
  startTime?: string
  endTime?: string
  limit?: number
  offset?: number
  downsample?: 'NONE' | 'BUCKET_AVG' | 'MIN_MAX' | 'LATEST_PER_BUCKET'
  bucketSeconds?: number
  signal?: AbortSignal
}

export interface OnlineMrBusinessQuery extends Pick<OnlineMrMetricQuery, 'startTime' | 'endTime' | 'limit' | 'offset' | 'signal'> {}

export async function queryOnlineMrMetrics(sessionId: string, metricTypes: string[], options: OnlineMrMetricQuery = {}): Promise<OnlineMrMetricPage> {
  const query = new URLSearchParams({ metric_types: metricTypes.join(',') })
  if (options.startTime) query.set('start_time', options.startTime)
  if (options.endTime) query.set('end_time', options.endTime)
  if (options.limit) query.set('limit', String(options.limit))
  if (options.offset !== undefined) query.set('offset', String(options.offset))
  if (options.downsample) query.set('downsample', options.downsample)
  if (options.bucketSeconds) query.set('bucket_seconds', String(options.bucketSeconds))
  return (await apiRequest<ApiResponse<OnlineMrMetricPage>>(`${root}/${encodeURIComponent(sessionId)}/metric-page?${query}`, { signal: options.signal })).data
}

export async function queryOnlineMrBusinessTable(
  sessionId: string,
  table: OnlineMrBusinessTable,
  options: OnlineMrBusinessQuery = {},
): Promise<OnlineMrBusinessTablePage> {
  const query = new URLSearchParams({ table })
  if (options.startTime) query.set('start_time', options.startTime)
  if (options.endTime) query.set('end_time', options.endTime)
  if (options.limit) query.set('limit', String(options.limit))
  if (options.offset !== undefined) query.set('offset', String(options.offset))
  return (await apiRequest<ApiResponse<OnlineMrBusinessTablePage>>(`${root}/${encodeURIComponent(sessionId)}/business-table?${query}`, { signal: options.signal })).data
}

export async function queryOnlineMrSwitchRssiWindows(
  sessionId: string,
  source: OnlineMrSwitchRssiSource,
  options: Pick<OnlineMrMetricQuery, 'startTime' | 'endTime' | 'limit' | 'offset' | 'signal'> = {},
): Promise<OnlineMrSwitchRssiPage> {
  const query = new URLSearchParams({ source })
  if (options.startTime) query.set('start_time', options.startTime)
  if (options.endTime) query.set('end_time', options.endTime)
  if (options.limit) query.set('limit', String(options.limit))
  if (options.offset !== undefined) query.set('offset', String(options.offset))
  return (await apiRequest<ApiResponse<OnlineMrSwitchRssiPage>>(`${root}/${encodeURIComponent(sessionId)}/switch-rssi-windows?${query}`, { signal: options.signal })).data
}

export async function queryOnlineMrTimeline(sessionId: string, limit = 500, offset = 0, signal?: AbortSignal): Promise<OnlineMrTimelineEvent[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return (await apiRequest<ApiResponse<OnlineMrTimelineEvent[]>>(`${root}/${encodeURIComponent(sessionId)}/timeline?${query}`, { signal })).data
}

export function addOnlineMrNote(sessionId: string, note: string): Promise<OnlineMrManualNote> {
  return apiRequest<OnlineMrManualNote>(`${root}/${encodeURIComponent(sessionId)}/notes`, {
    method: 'POST',
    body: JSON.stringify({ note, explicit_confirmation: true }),
  })
}
