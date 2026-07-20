import { apiRequest } from './client'
import type {
  CarNetworkPointPreview, CarNetworkPointRow, CarNetworkPointTable,
  OnlineMrMetricSeries, OnlineMrTimelineEvent, MeshImportProfile, OnlineTrainPage, RailTransitTask,
} from '../types/railTransitWeb'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type { MeshAnalysisParams } from '../types/meshAnalysis'

const onlineMrRoot = '/api/online-mr'
const trainRoot = '/api/rail-transit/train-communication'

interface ApiResponse<T> { ok: boolean; data: T }

export type MeshAnalysisParamsOverride = MeshAnalysisParams

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

export function getCarNetworkPointTable(): Promise<CarNetworkPointTable> {
  return apiRequest<CarNetworkPointTable>(`${trainRoot}/point-table`)
}

export function previewCarNetworkPointTable(file: File, duplicateStrategy: 'replace' | 'skip' | 'error'): Promise<CarNetworkPointPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('duplicate_strategy', duplicateStrategy)
  return apiRequest<CarNetworkPointPreview>(`${trainRoot}/point-table/import/preview`, { method: 'POST', body: form })
}

export function transformCarNetworkPointTable(
  operation: 'apply_mapping' | 'apply_global' | 'apply_global_override' | 'restore_defaults',
  rows: CarNetworkPointRow[],
  globalConfig: Record<string, unknown>,
): Promise<CarNetworkPointTable> {
  return apiRequest<CarNetworkPointTable>(`${trainRoot}/point-table/transform`, {
    method: 'POST', body: JSON.stringify({ operation, rows, global_config: globalConfig }),
  })
}

export function saveCarNetworkPointTable(
  rows: CarNetworkPointRow[], globalConfig: Record<string, unknown>, overwriteCustom = false, revision = '',
): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/point-table/save`, {
    method: 'POST', body: JSON.stringify({ rows, global_config: globalConfig, overwrite_custom: overwriteCustom, explicit_confirmation: true, audit: { source: 'electron-point-table' }, revision }),
  })
}

export function generateCarNetworkPointTable(rows: CarNetworkPointRow[], globalConfig: Record<string, unknown>): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/point-table/generate`, {
    method: 'POST', body: JSON.stringify({ rows, global_config: globalConfig }),
  })
}

export function exportCarNetworkPointTable(format: 'xlsx' | 'csv'): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/point-table/export`, { method: 'POST', body: JSON.stringify({ format }) })
}

export function getCarNetworkPointTableTask(taskId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/point-table/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelCarNetworkPointTableTask(taskId: string): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`${trainRoot}/point-table/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function recoverCarNetworkPointTableTasks(): Promise<RailTransitTask[]> {
  return apiRequest<RailTransitTask[]>(`${trainRoot}/point-table/tasks/recover`, { method: 'POST' })
}

export const carNetworkPointTableDownloadRequest = (artifactId: string, format: 'xlsx' | 'csv'): BackendDownloadRequest => ({
  apiPath: `${trainRoot}/point-table/artifacts/${encodeURIComponent(artifactId)}/download?format=${format}`,
  suggestedName: `车内通信点表.${format}`,
})

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

export function exportMeshAnalysisReport(sessionId: string, override?: MeshAnalysisParamsOverride): Promise<RailTransitTask> {
  return apiRequest<RailTransitTask>(`/api/rail-transit/mesh-analysis/sessions/${encodeURIComponent(sessionId)}/report`, {
    method: 'POST',
    ...(override ? { body: JSON.stringify({ analysis_params_override: override }) } : {}),
  })
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
