import { apiRequest } from './client'
import type { OnlineMrMetricSeries, MeshImportProfile, OnlineTrainPage, RailTransitTask } from '../types/railTransitWeb'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

const onlineMrRoot = '/api/online-mr'
const trainRoot = '/api/rail-transit/train-communication'

interface ApiResponse<T> { ok: boolean; data: T }

export function listOnlineTrains(page = 1, pageSize = 50): Promise<OnlineTrainPage> {
  return apiRequest<OnlineTrainPage>(`${trainRoot}/online?page=${page}&page_size=${pageSize}`)
}

export function startCarNetworkDiagnostic(trainId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/trains/${encodeURIComponent(trainId)}/diagnostics`, { method: 'POST' })
}

export function getCarNetworkDiagnosticTask(taskId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/diagnostics/${encodeURIComponent(taskId)}`)
}

export function cancelCarNetworkDiagnostic(taskId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/diagnostics/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function recoverCarNetworkDiagnostics(): Promise<RailTransitTask[]> {
  return apiRequest<RailTransitTask[]>(`${trainRoot}/diagnostics/recover`, { method: 'POST' })
}

export function importMeshAnalysis(files: File[], profile: MeshImportProfile): Promise<RailTransitTask> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('mr_id', profile.mr_id)
  form.append('display_name', profile.display_name)
  form.append('safe_folder_name', profile.safe_folder_name)
  if (profile.linked_device_id !== undefined) form.append('linked_device_id', String(profile.linked_device_id))
  if (profile.notes !== undefined) form.append('notes', profile.notes)
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/mesh-analysis/import`, { method: 'POST', body: form })
}

export function queryOnlineMrMetrics(sessionId: string, metricTypes = ['rssi']): Promise<OnlineMrMetricSeries[]> {
  const query = new URLSearchParams({ metric_types: metricTypes.join(',') })
  return apiRequest<ApiResponse<OnlineMrMetricSeries[]>>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/metrics?${query}`).then((response) => response.data)
}

export function exportOnlineMrReport(sessionId: string, outputName = ''): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/report`, { method: 'POST', body: JSON.stringify({ output_name: outputName }) })
}

export function exportMeshAnalysisReport(sessionId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`/api/rail-transit/mesh-analysis/sessions/${encodeURIComponent(sessionId)}/report`, { method: 'POST' })
}

export function getRailTransitTask(taskId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelRailTransitTask(taskId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function recoverRailTransitTasks(): Promise<RailTransitTask[]> {
  return apiRequest<RailTransitTask[]>(`${onlineMrRoot}/tasks/recover`, { method: 'POST' })
}

export const onlineMrReportDownloadRequest = (artifactId: string): BackendDownloadRequest => ({
  apiPath: `${onlineMrRoot}/report-artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: 'Online-MR-报告.xlsx',
})

export const meshAnalysisReportDownloadRequest = (artifactId: string): BackendDownloadRequest => ({
  apiPath: `/api/rail-transit/mesh-analysis/report-artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: 'MESH-分析报告.xlsx',
})
