import { apiRequest } from './client'
import type { AgentFormValue, AgentItem, AgentProbeResult } from '../types/agent'

interface ApiResponse<T> {
  ok: true
  data: T
}

export async function listAgents(): Promise<AgentItem[]> {
  return (await apiRequest<ApiResponse<AgentItem[]>>('/api/agents')).data
}

export async function createAgent(value: AgentFormValue): Promise<AgentItem> {
  return (await apiRequest<ApiResponse<AgentItem>>('/api/agents', { method: 'POST', body: JSON.stringify(value) })).data
}

export async function updateAgent(agentId: string, value: Partial<AgentFormValue>): Promise<AgentItem> {
  return (await apiRequest<ApiResponse<AgentItem>>(`/api/agents/${agentId}`, { method: 'PATCH', body: JSON.stringify(value) })).data
}

export async function probeAgent(agentId: string): Promise<AgentItem> {
  return (await apiRequest<ApiResponse<AgentItem>>(`/api/agents/${agentId}/probe`, { method: 'POST' })).data
}

export async function probeUnsaved(value: Pick<AgentFormValue, 'base_url' | 'authentication_type' | 'token'>): Promise<AgentProbeResult> {
  return (await apiRequest<ApiResponse<AgentProbeResult>>('/api/agents/probe', { method: 'POST', body: JSON.stringify(value) })).data
}

export async function setAgentEnabled(agentId: string, enabled: boolean): Promise<AgentItem> {
  const action = enabled ? 'enable' : 'disable'
  return (await apiRequest<ApiResponse<AgentItem>>(`/api/agents/${agentId}/${action}`, { method: 'POST' })).data
}

export async function archiveAgent(agentId: string): Promise<void> {
  await apiRequest<ApiResponse<{ agent_id: string; archived: boolean }>>(`/api/agents/${agentId}`, { method: 'DELETE' })
}
