import { apiRequest } from './client'
import type { OnlineMrMetricSeries, MeshImportProfile, RailTransitTask } from '../types/railTransitWeb'

const onlineMrRoot = '/api/online-mr'
const trainRoot = '/api/rail-transit/train-communication'
const acRoot = '/api/ac-management'

interface ApiResponse<T> { ok: boolean; data: T }

export function listOnlineTrains(page = 1, pageSize = 50): Promise<Record<string, unknown>> {
  return apiRequest(`${trainRoot}/online?page=${page}&page_size=${pageSize}`)
}

export function startCarNetworkDiagnostic(siteId = '', trainId = ''): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/car-network-diagnostic`, { method: 'POST', body: JSON.stringify({ site_id: siteId, train_id: trainId }) })
}

export function refreshTracksideBusiness(siteId = '', acId = ''): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${acRoot}/trackside-business/refresh`, { method: 'POST', body: JSON.stringify({ site_id: siteId, ac_id: acId }) })
}

export function importMeshAnalysis(files: File[], profile: MeshImportProfile, siteId = ''): Promise<RailTransitTask> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('site_id', siteId)
  Object.entries(profile).forEach(([key, value]) => {
    if (value !== undefined) form.append(key, String(value))
  })
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/mesh-analysis/import`, { method: 'POST', body: form })
}

export function queryOnlineMrMetrics(sessionId: string, metricTypes = ['rssi']): Promise<OnlineMrMetricSeries[]> {
  const query = new URLSearchParams({ metric_types: metricTypes.join(',') })
  return apiRequest<ApiResponse<OnlineMrMetricSeries[]>>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/metrics?${query}`).then((response) => response.data)
}

export function exportOnlineMrReport(sessionId: string, outputName = ''): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/report`, { method: 'POST', body: JSON.stringify({ output_name: outputName }) })
}
