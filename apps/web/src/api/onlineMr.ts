import { apiRequest } from './client'
import type {
  OnlineMrCollectorStatus,
  OnlineMrRawFile,
  OnlineMrRawTail,
  OnlineMrRealtimePreview,
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
} from '../types/onlineMr'

interface ApiResponse<T> { ok: boolean; data: T }

const root = '/api/online-mr/sessions'

export async function getCurrentOnlineMrSession(): Promise<OnlineMrSessionDetail | null> {
  return (await apiRequest<ApiResponse<OnlineMrSessionDetail | null>>(`${root}/current`)).data
}

export async function listRecentOnlineMrSessions(limit = 20): Promise<OnlineMrSessionSummary[]> {
  return (await apiRequest<ApiResponse<OnlineMrSessionSummary[]>>(`${root}/recent?limit=${limit}`)).data
}

export async function getOnlineMrSession(sessionId: string): Promise<OnlineMrSessionDetail> {
  return (await apiRequest<ApiResponse<OnlineMrSessionDetail>>(`${root}/${encodeURIComponent(sessionId)}`)).data
}

export async function listOnlineMrCollectors(sessionId: string): Promise<OnlineMrCollectorStatus[]> {
  return (await apiRequest<ApiResponse<OnlineMrCollectorStatus[]>>(`${root}/${encodeURIComponent(sessionId)}/collectors`)).data
}

export async function getOnlineMrPreview(sessionId: string): Promise<OnlineMrRealtimePreview> {
  return (await apiRequest<ApiResponse<OnlineMrRealtimePreview>>(`${root}/${encodeURIComponent(sessionId)}/preview`)).data
}

export async function listOnlineMrRawFiles(sessionId: string): Promise<OnlineMrRawFile[]> {
  return (await apiRequest<ApiResponse<OnlineMrRawFile[]>>(`${root}/${encodeURIComponent(sessionId)}/raw-summary`)).data
}

export async function getOnlineMrRawTail(sessionId: string, name: string, tail = 200): Promise<OnlineMrRawTail> {
  const query = new URLSearchParams({ name, tail: String(tail) })
  return (await apiRequest<ApiResponse<OnlineMrRawTail>>(`${root}/${encodeURIComponent(sessionId)}/raw-tail?${query}`)).data
}
