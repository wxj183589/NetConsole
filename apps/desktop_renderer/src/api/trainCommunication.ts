import { apiRequest } from './client'
import type {
  TrainCommunicationFilters,
  TrainCommunicationPage,
  TrainCommunicationSummary,
  TrainCommunicationTopology,
} from '../types/trainCommunication'

const root = '/api/rail-transit/train-communication'
type TrainCommunicationTask = {
  task_id: string
  status: string
  action: string
  message: string
  error_message?: string
}

function queryString(values: object): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values as Record<string, string | number | boolean | undefined>)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export const getTrainCommunicationSummary = (): Promise<TrainCommunicationSummary> => apiRequest(`${root}/summary`)
export const listTrainCommunications = (filters: TrainCommunicationFilters): Promise<TrainCommunicationPage> => apiRequest(`${root}/trains${queryString(filters)}`)
export const listOnlineTrainCommunications = (page = 1, pageSize = 200): Promise<TrainCommunicationPage> => apiRequest(`${root}/online${queryString({ page, page_size: pageSize })}`)
export const getTrainCommunicationTopology = (id: string): Promise<TrainCommunicationTopology> => apiRequest(`${root}/trains/${encodeURIComponent(id)}/topology`)
export const startTrainCommunicationCheck = (id: string): Promise<TrainCommunicationTask> => apiRequest(`${root}/trains/${encodeURIComponent(id)}/diagnostics`, { method: 'POST' })
export const getTrainCommunicationCheck = (taskId: string): Promise<TrainCommunicationTask> => apiRequest(`${root}/diagnostics/${encodeURIComponent(taskId)}`)
export const recoverTrainCommunicationChecks = (): Promise<TrainCommunicationTask[]> => apiRequest(`${root}/diagnostics/recover`, { method: 'POST' })
