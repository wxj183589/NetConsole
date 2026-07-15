import { apiRequest } from './client'
import type {
  NetworkTaskResponse,
  NetworkTaskStartRequest,
  NetworkToolArtifact,
  NetworkToolTask,
  TcpPortTestRequest,
  TcpPortTestResponse,
  ToolboxResult,
  WirelessAdapter,
  WirelessProject,
  WirelessScanRun,
} from '../types/networkTools'

export function startTcpPortTest(value: TcpPortTestRequest): Promise<TcpPortTestResponse> {
  return apiRequest<TcpPortTestResponse>('/api/network-tools/tcp-port-test', {
    method: 'POST',
    body: JSON.stringify(value),
  })
}

export function calculateIpv4(text: string): Promise<ToolboxResult> {
  return apiRequest<ToolboxResult>('/api/network-tools/toolbox/ipv4', { method: 'POST', body: JSON.stringify({ text }) })
}

export function calculateIpv6(text: string): Promise<ToolboxResult> {
  return apiRequest<ToolboxResult>('/api/network-tools/toolbox/ipv6', { method: 'POST', body: JSON.stringify({ text }) })
}

export function calculateVlsm(parent: string, requests: string): Promise<ToolboxResult> {
  return apiRequest<ToolboxResult>('/api/network-tools/toolbox/vlsm', { method: 'POST', body: JSON.stringify({ parent, requests }) })
}

export function calculateSubnets(parent: string, target_prefix: number, page = 1, page_size = 50): Promise<ToolboxResult> {
  return apiRequest<ToolboxResult>('/api/network-tools/toolbox/subnets', { method: 'POST', body: JSON.stringify({ parent, target_prefix, page, page_size }) })
}

export function summarizeRoutes(text: string): Promise<ToolboxResult> {
  return apiRequest<ToolboxResult>('/api/network-tools/toolbox/summarize', { method: 'POST', body: JSON.stringify({ text }) })
}

export function calculateWildcard(text: string): Promise<ToolboxResult> {
  return apiRequest<ToolboxResult>('/api/network-tools/toolbox/wildcard', { method: 'POST', body: JSON.stringify({ text }) })
}

export function startNetworkTask(value: NetworkTaskStartRequest): Promise<NetworkTaskResponse> {
  return apiRequest<NetworkTaskResponse>('/api/network-tools/tasks', { method: 'POST', body: JSON.stringify(value) })
}

export function listNetworkTasks(): Promise<NetworkToolTask[]> {
  return apiRequest<NetworkToolTask[]>('/api/network-tools/runs?limit=200')
}

export function getNetworkTask(id: string): Promise<NetworkToolTask> {
  return apiRequest<NetworkToolTask>(`/api/network-tools/runs/${encodeURIComponent(id)}`)
}

export function cancelNetworkTask(id: string): Promise<NetworkToolTask> {
  return apiRequest<NetworkToolTask>(`/api/network-tools/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

export function exportNetworkTask(id: string, format: 'csv' | 'xlsx'): Promise<NetworkToolArtifact> {
  return apiRequest<NetworkToolArtifact>(`/api/network-tools/runs/${encodeURIComponent(id)}/export`, { method: 'POST', body: JSON.stringify({ format }) })
}

export function listWirelessAdapters(): Promise<WirelessAdapter[]> {
  return apiRequest<WirelessAdapter[]>('/api/network-tools/wireless-scan/adapters')
}

export function listWirelessProjects(): Promise<WirelessProject[]> {
  return apiRequest<WirelessProject[]>('/api/network-tools/wireless-scan/projects')
}

export function createWirelessProject(name: string, description = ''): Promise<WirelessProject> {
  return apiRequest<WirelessProject>('/api/network-tools/wireless-scan/projects', { method: 'POST', body: JSON.stringify({ name, description }) })
}

export function startWirelessScan(value: { adapter_name?: string; adapter_guid?: string; project_id?: string }): Promise<NetworkTaskResponse> {
  return apiRequest<NetworkTaskResponse>('/api/network-tools/wireless-scan/tasks', { method: 'POST', body: JSON.stringify(value) })
}

export function listWirelessRuns(): Promise<WirelessScanRun[]> {
  return apiRequest<WirelessScanRun[]>('/api/network-tools/wireless-scan/runs?limit=200')
}

export function listWirelessResults(scanId: string): Promise<Record<string, unknown>[]> {
  return apiRequest<Record<string, unknown>[]>(`/api/network-tools/wireless-scan/runs/${encodeURIComponent(scanId)}/results?limit=2000`)
}

export function exportWirelessScan(scanId: string, format: 'csv' | 'xlsx'): Promise<NetworkToolArtifact> {
  return apiRequest<NetworkToolArtifact>('/api/network-tools/wireless-scan/export', { method: 'POST', body: JSON.stringify({ scan_id: scanId, format }) })
}
