import { apiRequest } from './client'
import type {
  FpingRequest,
  IperfClientRequest,
  IperfServerRequest,
  TrafficCancelResponse,
  TrafficEvent,
  TrafficExecutionTarget,
  TrafficPingSample,
  TrafficRetryResponse,
  TrafficRun,
  TrafficStartResponse,
  TrafficSummaryResponse,
} from '../types/traffic'

export function listTrafficExecutionTargets(): Promise<TrafficExecutionTarget[]> {
  return apiRequest<TrafficExecutionTarget[]>('/api/traffic/execution-targets')
}

export function startIperfServer(value: IperfServerRequest): Promise<TrafficStartResponse> {
  return apiRequest<TrafficStartResponse>('/api/traffic/iperf/server', { method: 'POST', body: JSON.stringify(value) })
}

export function startIperfClient(value: IperfClientRequest): Promise<TrafficStartResponse> {
  return apiRequest<TrafficStartResponse>('/api/traffic/iperf/client', { method: 'POST', body: JSON.stringify(value) })
}

export function startFping(value: FpingRequest): Promise<TrafficStartResponse> {
  return apiRequest<TrafficStartResponse>('/api/traffic/fping', { method: 'POST', body: JSON.stringify(value) })
}

export function listTrafficRuns(): Promise<TrafficRun[]> {
  return apiRequest<TrafficRun[]>('/api/traffic/runs?limit=200')
}

export function getTrafficRun(id: string): Promise<TrafficRun> {
  return apiRequest<TrafficRun>(`/api/traffic/runs/${encodeURIComponent(id)}`)
}

export function getTrafficSummary(id: string): Promise<TrafficSummaryResponse> {
  return apiRequest<TrafficSummaryResponse>(`/api/traffic/runs/${encodeURIComponent(id)}/summary`)
}

export function listTrafficEvents(id: string, after = 0): Promise<TrafficEvent[]> {
  return apiRequest<TrafficEvent[]>(`/api/traffic/runs/${encodeURIComponent(id)}/events?after=${after}&limit=500`)
}

export function listTrafficPingSamples(id: string, after = 0): Promise<TrafficPingSample[]> {
  return apiRequest<TrafficPingSample[]>(`/api/traffic/runs/${encodeURIComponent(id)}/ping-samples?after=${after}&limit=1000`)
}

export function cancelTrafficRun(id: string): Promise<TrafficCancelResponse> {
  return apiRequest<TrafficCancelResponse>(`/api/traffic/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

export function retryTrafficRun(id: string): Promise<TrafficRetryResponse> {
  return apiRequest<TrafficRetryResponse>(`/api/traffic/runs/${encodeURIComponent(id)}/retry`, { method: 'POST' })
}
