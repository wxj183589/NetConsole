import { apiRequest } from './client'
import type {
  NetworkProbeEnvironment,
  NetworkTaskResponse,
  NetworkTaskResultPage,
  NetworkTaskStartRequest,
  NetworkToolArtifact,
  NetworkToolTask,
  TcpPortTestRequest,
  TcpPortTestResponse,
  ToolboxResult,
  WirelessAdapter,
  WirelessProject,
  WirelessScanPage,
  WirelessScanRun,
  WirelessScanRunDetail,
  WirelessScanFilters,
  WirelessScanStartRequest,
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

export function getNetworkProbeEnvironment(): Promise<NetworkProbeEnvironment> {
  return apiRequest<NetworkProbeEnvironment>('/api/network-tools/toolbox/probe-environment')
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

export function listNetworkTaskResults(id: string, offset = 0, limit = 100, cursor?: number): Promise<NetworkTaskResultPage> {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (cursor !== undefined) query.set('cursor', String(cursor))
  return apiRequest<NetworkTaskResultPage>(`/api/network-tools/runs/${encodeURIComponent(id)}/results?${query}`)
}

export function exportNetworkTask(id: string, format: 'csv' | 'xlsx'): Promise<NetworkTaskResponse> {
  return apiRequest<NetworkTaskResponse>(`/api/network-tools/runs/${encodeURIComponent(id)}/export`, { method: 'POST', body: JSON.stringify({ format }) })
}

export function getNetworkExportArtifact(id: string): Promise<NetworkToolArtifact> {
  return apiRequest<NetworkToolArtifact>(`/api/network-tools/runs/${encodeURIComponent(id)}/artifact`)
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

export function deleteWirelessProject(id: string): Promise<{ project_id: string; deleted: boolean }> {
  return apiRequest<{ project_id: string; deleted: boolean }>(`/api/network-tools/wireless-scan/projects/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function startWirelessScan(value: WirelessScanStartRequest): Promise<NetworkTaskResponse> {
  return apiRequest<NetworkTaskResponse>('/api/network-tools/wireless-scan/tasks', { method: 'POST', body: JSON.stringify(value) })
}

export function listWirelessTasks(): Promise<NetworkToolTask[]> {
  return apiRequest<NetworkToolTask[]>('/api/network-tools/wireless-scan/tasks?limit=200')
}

export function getWirelessTask(id: string): Promise<NetworkToolTask> {
  return apiRequest<NetworkToolTask>(`/api/network-tools/wireless-scan/tasks/${encodeURIComponent(id)}`)
}

export function cancelWirelessTask(id: string): Promise<NetworkToolTask> {
  return apiRequest<NetworkToolTask>(`/api/network-tools/wireless-scan/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

export function listWirelessRuns(page = 1, pageSize = 50): Promise<WirelessScanPage<WirelessScanRun>> {
  return apiRequest<WirelessScanPage<WirelessScanRun>>(`/api/network-tools/wireless-scan/runs?page=${page}&page_size=${pageSize}`)
}

export function listWirelessResults(scanId: string, page = 1, pageSize = 100, filters: WirelessScanFilters = {}): Promise<WirelessScanPage<Record<string, unknown>>> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (filters.only_trackside) query.set('only_trackside', 'true')
  if (filters.band) query.set('band', filters.band)
  if (filters.radio) query.set('radio', filters.radio)
  if (filters.search) query.set('search', filters.search)
  return apiRequest<WirelessScanPage<Record<string, unknown>>>(`/api/network-tools/wireless-scan/runs/${encodeURIComponent(scanId)}/results?${query}`)
}

export function getWirelessRunDetail(scanId: string): Promise<WirelessScanRunDetail> {
  return apiRequest<WirelessScanRunDetail>(`/api/network-tools/wireless-scan/runs/${encodeURIComponent(scanId)}`)
}

export function exportWirelessScan(scanId: string, format: 'csv' | 'xlsx'): Promise<NetworkTaskResponse> {
  return apiRequest<NetworkTaskResponse>('/api/network-tools/wireless-scan/export', { method: 'POST', body: JSON.stringify({ scan_id: scanId, format }) })
}

export function getWirelessExportArtifact(id: string): Promise<NetworkToolArtifact> {
  return apiRequest<NetworkToolArtifact>(`/api/network-tools/wireless-scan/tasks/${encodeURIComponent(id)}/artifact`)
}
