import { apiRequest } from './client'
import type {
  TrainCommunicationFilters,
  TrainCommunicationPage,
  TrainCommunicationSummary,
} from '../types/trainCommunication'

const root = '/api/rail-transit/online-mr/inventory'
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
