import { apiRequest } from './client'
import type {
  CommunicationPackage,
  CommunicationRawSource,
  CommunicationTask,
  MrCommunicationDetail,
  MrCommunicationStatus,
  TrainCommunicationDetail,
  TrainCommunicationFilters,
  TrainCommunicationPage,
  TrainCommunicationSummary,
} from '../types/trainCommunication'

const root = '/api/rail-transit/train-communication'

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
export const getTrainCommunication = (id: string): Promise<TrainCommunicationDetail> => apiRequest(`${root}/trains/${encodeURIComponent(id)}`)
export const getMrCommunication = (id: string): Promise<MrCommunicationDetail> => apiRequest(`${root}/mrs/${encodeURIComponent(id)}`)
export const getMrCommunicationPreview = (id: string): Promise<MrCommunicationStatus> => apiRequest(`${root}/mrs/${encodeURIComponent(id)}/preview`)
export const listMrRawSources = (id: string): Promise<CommunicationRawSource[]> => apiRequest(`${root}/mrs/${encodeURIComponent(id)}/raw-sources`)
export const listMrTasks = (id: string): Promise<CommunicationTask[]> => apiRequest(`${root}/mrs/${encodeURIComponent(id)}/tasks`)
export const listMrPackages = (id: string): Promise<CommunicationPackage[]> => apiRequest(`${root}/mrs/${encodeURIComponent(id)}/packages`)
