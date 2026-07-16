import { apiRequest } from './client'
import type { TracksideApBusinessPage, TracksideApTask, TracksideApUpdateRequest } from '../types/tracksideApBusiness'

const root = '/api/rail-transit/trackside-ap-business'

export function listTracksideApBusiness(params: {
  station?: string; query?: string; optical_anomaly_only?: boolean; page?: number; page_size?: number
} = {}): Promise<TracksideApBusinessPage> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value))
  return apiRequest(`${root}/rows?${query}`)
}

export function startTracksideApUpdate(payload: TracksideApUpdateRequest = {}): Promise<TracksideApTask> {
  return apiRequest(`${root}/update`, { method: 'POST', body: JSON.stringify(payload) })
}

export function getTracksideApTask(taskId: string): Promise<TracksideApTask> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelTracksideApTask(taskId: string): Promise<TracksideApTask> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function recoverTracksideApTasks(): Promise<TracksideApTask[]> {
  return apiRequest(`${root}/tasks/recover`, { method: 'POST' })
}
