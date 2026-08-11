import { apiRequest } from './client'
import type { OnlineMrControlOperation, OnlineMrControlPresets, OnlineMrControlStatus, OnlineMrStartConfig } from '../types/onlineMrControl'

const root = '/api/rail-transit/online-mr-control'

export const getOnlineMrControlStatus = (): Promise<OnlineMrControlStatus> => apiRequest(`${root}/status`)
export const getOnlineMrControlPresets = (): Promise<OnlineMrControlPresets> => apiRequest(`${root}/presets`)
export const getOnlineMrControlOperation = (id: string): Promise<OnlineMrControlOperation> => apiRequest(`${root}/${encodeURIComponent(id)}`)
export const startOnlineMrControl = (payload: OnlineMrStartConfig): Promise<OnlineMrControlOperation> => apiRequest(`${root}/start`, { method: 'POST', body: JSON.stringify(payload) })
export const stopOnlineMrControl = (id: string): Promise<OnlineMrControlOperation> => apiRequest(`${root}/${encodeURIComponent(id)}/stop`, { method: 'POST' })
export const forceStopOnlineMrControl = (id: string): Promise<OnlineMrControlOperation> => apiRequest(`${root}/${encodeURIComponent(id)}/force-stop`, { method: 'POST' })
export const recoverOnlineMrControl = (): Promise<OnlineMrControlOperation[]> => apiRequest(`${root}/recover`, { method: 'POST' })
