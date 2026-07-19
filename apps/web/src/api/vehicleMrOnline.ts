import { ApiRequestError, apiRequest } from './client'
import { getTask } from './tasks'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  VehicleMrController, VehicleMrEventPage, VehicleMrHistoryFilters, VehicleMrOnlinePage,
  VehicleMrMappingPreview, VehicleMrOnlineTask, VehicleMrTrainMapping, VehicleMrTrainState,
} from '../types/vehicleMrOnline'

const root = '/api/rail-transit/train-online'

export function listVehicleMrOnline(params: {
  query?: string; overall_status?: string; station?: string; section?: string; data_status?: string
  unmatched_only?: boolean; page?: number; page_size?: number
} = {}): Promise<VehicleMrOnlinePage> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value))
  return apiRequest(`${root}/trains?${query}`)
}
export const listVehicleMrMappings = (): Promise<VehicleMrTrainMapping[]> => apiRequest(`${root}/mappings`)
export const listVehicleMrControllers = (): Promise<VehicleMrController[]> => apiRequest(`${root}/controllers`)
export function listVehicleMrEvents(trainId: string, filters: VehicleMrHistoryFilters = {}): Promise<VehicleMrEventPage> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value))
  if (!query.has('limit')) query.set('limit', '200')
  return apiRequest(`${root}/trains/${encodeURIComponent(trainId)}/events?${query}`)
}
export const getVehicleMrOnlineDetail = (trainId: string): Promise<VehicleMrTrainState> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}`)
export async function refreshVehicleMrOnline(controllerId: string): Promise<VehicleMrOnlineTask> {
  const result = await apiRequest<{ task_id: string; status: string; message: string }>(`${root}/refresh`, {
    method: 'POST', body: JSON.stringify({ controller_id: controllerId, include_switch_history: false }),
  })
  return { task_id: result.task_id, status: result.status, action: 'ac_mesh_link_refresh', artifact_id: '', available: false, sha256: '', size_bytes: 0, message: result.message, error_message: '', result_summary: {} }
}
export const refreshVehicleMrApMapping = (trainId = ''): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/ap-mapping/refresh?train_id=${encodeURIComponent(trainId)}`, { method: 'POST' })
export const saveVehicleMrMappings = (mappings: VehicleMrTrainMapping[]): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/mappings`, { method: 'PUT', body: JSON.stringify({ mappings, explicit_confirmation: true, audit: { source: 'electron-vehicle-mr-mapping' } }) })
export async function getVehicleMrOnlineTask(taskId: string): Promise<VehicleMrOnlineTask> {
  try {
    return await apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}`)
  } catch (reason) {
    if (!(reason instanceof ApiRequestError) || reason.status !== 404) throw reason
    const item = await getTask(taskId)
    return {
      task_id: item.id, status: item.status, action: item.type, artifact_id: item.artifact_download?.artifact_id || '',
      available: Boolean(item.artifact_download), sha256: '', size_bytes: item.artifact_download?.size_bytes || 0,
      message: item.message, error_message: item.error_summary,
      result_summary: { records_count: item.records_count, snapshot_id: item.snapshot_id, parser_version: item.parser_version },
    }
  }
}
export const cancelVehicleMrOnlineTask = (taskId: string): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
export const recoverVehicleMrOnlineTasks = (): Promise<VehicleMrOnlineTask[]> => apiRequest(`${root}/tasks/recover`, { method: 'POST' })
export const startVehicleMrCollection = (acDeviceId: number, intervalSeconds: number): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/collection/start`, { method: 'POST', body: JSON.stringify({ ac_device_id: acDeviceId, interval_seconds: intervalSeconds }) })
export const stopVehicleMrCollection = (taskId: string): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/collection/${encodeURIComponent(taskId)}/stop`, { method: 'POST' })
export function exportVehicleMrHistory(trainId: string, filters: VehicleMrHistoryFilters): Promise<VehicleMrOnlineTask> {
  const { event_status, ...rest } = filters
  return apiRequest(`${root}/history/export`, { method: 'POST', body: JSON.stringify({ train_id: trainId, ...rest, status: event_status || '' }) })
}
export const vehicleMrHistoryDownloadRequest = (artifactId: string, trainName: string): BackendDownloadRequest => ({
  apiPath: `${root}/history/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: `${trainName || '列车'}_经过历史.xlsx`,
})
export function previewVehicleMrMappings(file: File, duplicateStrategy: 'replace' | 'skip' | 'error'): Promise<VehicleMrMappingPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('duplicate_strategy', duplicateStrategy)
  return apiRequest(`${root}/mappings/import/preview`, { method: 'POST', body: form })
}
export const exportVehicleMrMappingTemplate = (): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/mappings/template/export`, { method: 'POST' })
export const vehicleMrMappingTemplateDownloadRequest = (artifactId: string): BackendDownloadRequest => ({
  apiPath: `${root}/mappings/template/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: '车载MR映射模板.xlsx',
})
