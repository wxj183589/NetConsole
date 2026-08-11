import { apiRequest } from './client'
import type {
  OnlineMrAgentCapabilities,
  OnlineMrAgentOperation,
  OnlineMrAgentProfile,
  OnlineMrAgentReadiness,
  OnlineMrAgentStartConfig,
  OnlineMrAgentStatus,
} from '../types/onlineMrAgentControl'

const root = '/api/rail-transit/online-mr-agent'

export const getOnlineMrAgentCapabilities = (): Promise<OnlineMrAgentCapabilities> => apiRequest(`${root}/capabilities`)
export const getOnlineMrAgentProfiles = (): Promise<OnlineMrAgentProfile[]> => apiRequest(`${root}/profiles`)
export const getOnlineMrAgentReadiness = (id: string): Promise<OnlineMrAgentReadiness> => apiRequest(`${root}/profiles/${encodeURIComponent(id)}/readiness`)
export const getOnlineMrAgentStatus = (): Promise<OnlineMrAgentStatus> => apiRequest(`${root}/status`)
export const getOnlineMrAgentOperation = (id: string): Promise<OnlineMrAgentOperation> => apiRequest(`${root}/${encodeURIComponent(id)}`)
export const startOnlineMrAgent = (payload: OnlineMrAgentStartConfig): Promise<OnlineMrAgentOperation> => apiRequest(`${root}/start`, { method: 'POST', body: JSON.stringify(payload) })
export const stopOnlineMrAgent = (id: string): Promise<OnlineMrAgentOperation> => apiRequest(`${root}/${encodeURIComponent(id)}/stop`, { method: 'POST' })
