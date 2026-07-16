import { apiRequest } from './client'
import type { VehicleMrEventPage, VehicleMrOnlinePage, VehicleMrOnlineTask, VehicleMrTrainMapping } from '../types/vehicleMrOnline'

const root = '/api/rail-transit/train-online'

export function listVehicleMrOnline(params: { query?: string; train_status?: string; page?: number; page_size?: number } = {}): Promise<VehicleMrOnlinePage> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value))
  return apiRequest(`${root}/trains?${query}`)
}
export const listVehicleMrMappings = (): Promise<VehicleMrTrainMapping[]> => apiRequest(`${root}/mappings`)
export const listVehicleMrEvents = (trainId: string, limit = 200): Promise<VehicleMrEventPage> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}/events?limit=${limit}`)
export const refreshVehicleMrOnline = (): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/refresh`, { method: 'POST' })
export const refreshVehicleMrApMapping = (trainId = ''): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/ap-mapping/refresh?train_id=${encodeURIComponent(trainId)}`, { method: 'POST' })
export const saveVehicleMrMappings = (mappings: VehicleMrTrainMapping[]): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/mappings`, { method: 'PUT', body: JSON.stringify({ mappings }) })
export const getVehicleMrOnlineTask = (taskId: string): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}`)
export const cancelVehicleMrOnlineTask = (taskId: string): Promise<VehicleMrOnlineTask> => apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
export const recoverVehicleMrOnlineTasks = (): Promise<VehicleMrOnlineTask[]> => apiRequest(`${root}/tasks/recover`, { method: 'POST' })
