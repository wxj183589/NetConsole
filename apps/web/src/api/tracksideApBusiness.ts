import { apiRequest } from './client'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  TracksideApBusinessPage, TracksideApPlan, TracksideApPlanPreview, TracksideApPlanRow,
  TracksideApTask, TracksideApUpdateRequest,
} from '../types/tracksideApBusiness'

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

export function getTracksideApPlan(): Promise<TracksideApPlan> {
  return apiRequest(`${root}/plan`)
}

export function previewTracksideApPlan(file: File, duplicateStrategy: 'replace' | 'skip' | 'error'): Promise<TracksideApPlanPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('duplicate_strategy', duplicateStrategy)
  return apiRequest(`${root}/plan/import/preview`, { method: 'POST', body: form })
}

export function saveTracksideApPlan(rows: TracksideApPlanRow[]): Promise<TracksideApTask> {
  return apiRequest(`${root}/plan/save`, {
    method: 'POST', body: JSON.stringify({ rows, explicit_confirmation: true, audit: { source: 'electron-trackside-plan' } }),
  })
}

export function exportTracksideApPlan(template = false): Promise<TracksideApTask> {
  return apiRequest(`${root}/plan/export`, { method: 'POST', body: JSON.stringify({ template }) })
}

export const tracksideApPlanDownloadRequest = (artifactId: string, template = false): BackendDownloadRequest => ({
  apiPath: `${root}/plan/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: template ? '轨旁AP规划模板.xlsx' : '轨旁AP规划.xlsx',
})
