import { apiRequest } from './client'
import type {
  AgentFormValue,
  AgentItem,
  AgentProbeResult,
  AgentRemotePackage,
  AgentRemoteStatus,
  AgentRemoteTask,
  AgentRemoteTaskLogs,
  AgentToolsStatus,
} from '../types/agent'

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

export async function getAgentRemoteStatus(agentId: string): Promise<AgentRemoteStatus> {
  return (await apiRequest<ApiResponse<AgentRemoteStatus>>(`/api/agents/${agentId}/remote/status`)).data
}

export async function getAgentRemoteTools(agentId: string): Promise<AgentToolsStatus> {
  return (await apiRequest<ApiResponse<AgentToolsStatus>>(`/api/agents/${agentId}/remote/tools`)).data
}

export async function listAgentRemoteTasks(agentId: string): Promise<AgentRemoteTask[]> {
  return (await apiRequest<ApiResponse<AgentRemoteTask[]>>(`/api/agents/${agentId}/remote/tasks`)).data
}

export async function getAgentRemoteTask(agentId: string, taskId: string): Promise<AgentRemoteTask> {
  return (await apiRequest<ApiResponse<AgentRemoteTask>>(`/api/agents/${agentId}/remote/tasks/${encodeURIComponent(taskId)}`)).data
}

export async function getAgentRemoteTaskLogs(agentId: string, taskId: string, tail = 300): Promise<AgentRemoteTaskLogs> {
  const value = Math.max(1, Math.min(Math.trunc(tail), 2000))
  return (await apiRequest<ApiResponse<AgentRemoteTaskLogs>>(`/api/agents/${agentId}/remote/tasks/${encodeURIComponent(taskId)}/logs?tail=${value}`)).data
}

export async function listAgentRemotePackages(agentId: string): Promise<AgentRemotePackage[]> {
  return (await apiRequest<ApiResponse<AgentRemotePackage[]>>(`/api/agents/${agentId}/remote/packages`)).data
}
