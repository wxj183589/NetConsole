import { apiRequest } from './client'
import type {
  OnlineMrMetricSeries, OnlineMrParsedDatabaseEnsureResult, OnlineMrTimelineEvent, MeshImportProfile, RailTransitTask,
} from '../types/railTransitWeb'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type { MeshAnalysisParams } from '../types/meshAnalysis'

const onlineMrRoot = '/api/online-mr'

interface ApiResponse<T> { ok: boolean; data: T }

export type MeshAnalysisParamsOverride = MeshAnalysisParams

export function importMeshAnalysis(files: File[], profile: MeshImportProfile): Promise<RailTransitTask> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('mr_id', profile.mr_id)
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/mesh-analysis/import`, { method: 'POST', body: form })
}

export function queryOnlineMrMetrics(sessionId: string, metricTypes = ['rssi']): Promise<OnlineMrMetricSeries[]> {
  const query = new URLSearchParams({ metric_types: metricTypes.join(',') })
  return apiRequest<ApiResponse<OnlineMrMetricSeries[]>>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/metrics?${query}`).then((response) => response.data)
}

export function queryOnlineMrTimeline(sessionId: string, limit = 500): Promise<OnlineMrTimelineEvent[]> {
  return apiRequest<ApiResponse<OnlineMrTimelineEvent[]>>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/timeline?limit=${limit}&offset=0`).then((response) => response.data)
}

export function exportOnlineMrReport(sessionId: string, outputName = ''): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/report`, { method: 'POST', body: JSON.stringify({ output_name: outputName }) })
}

export function parseOnlineMrSession(sessionId: string, forceReparse = false): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/parse`, {
    method: 'POST', body: JSON.stringify({ force_reparse: forceReparse }),
  })
}

export function ensureOnlineMrParsedDatabaseCurrent(sessionId: string): Promise<OnlineMrParsedDatabaseEnsureResult> {
  return apiRequest<OnlineMrParsedDatabaseEnsureResult>(
    `${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}/ensure-current`,
    { method: 'POST' },
  )
}

export function exportMeshAnalysisReport(sessionId: string, override?: MeshAnalysisParamsOverride, exportMode: 'business' | 'diagnostic' = 'business'): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`/api/rail-transit/mesh-analysis/sessions/${encodeURIComponent(sessionId)}/report`, {
    method: 'POST',
    body: JSON.stringify({ export_mode: exportMode, ...(override ? { analysis_params_override: override } : {}) }),
  })
}

export function deleteOnlineMrSession(sessionId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(
    `${onlineMrRoot}/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'DELETE',
      body: JSON.stringify({
        expected_session_id: sessionId,
        explicit_confirmation: true,
      }),
    },
  )
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
