import type { TaskStatus } from './task'

export type ExecutionTargetKind = 'LOCAL' | 'AGENT'
export type TrafficTestType = 'IPERF_SERVER' | 'IPERF_CLIENT' | 'HIGH_FREQUENCY_PING'
export type TrafficSyncState = 'ACTIVE' | 'STALE' | 'CREDENTIAL_REQUIRED' | 'AGENT_OFFLINE' | 'COMPLETED' | 'ERROR'

export interface TrafficExecutionTarget {
  kind: ExecutionTargetKind
  id: string
  display_name: string
  available: boolean
  unavailable_reason: string
  agent_id: string
  status: string
  platform: string
  architecture: string
  version: string
  capabilities: Record<string, unknown>
}

export interface TrafficExecutionTargetRequest {
  kind: ExecutionTargetKind
  agent_id?: string
  display_name?: string
}

export interface TrafficRun {
  id: string
  traffic_run_id: string
  controller_task_id: string
  test_type: TrafficTestType
  role: string
  executor_kind: ExecutionTargetKind
  agent_id: string
  normalized_config: Record<string, unknown>
  status: TaskStatus
  created_at: string
  started_at: string
  finished_at: string
  updated_at: string
  summary: Record<string, unknown>
  error_code: string
  error_message: string
  raw_reference: string
  result_reference: string
  retry_of_traffic_run_id: string
  parent_task_id: string
  correlation_id: string
  last_event_sequence: number
  sync_state: TrafficSyncState
  cancellable: boolean
}

export interface TrafficEvent {
  sequence: number
  timestamp: string
  traffic_run_id: string
  controller_task_id: string
  source: string
  type: string
  payload: Record<string, unknown>
  remote_sequence: number | null
}

export interface TrafficPingSample {
  traffic_run_id: string
  sequence: number
  timestamp: string
  target: string
  probe_sequence: number | null
  ok: boolean
  rtt_ms: number | null
  timeout: boolean
  packet_size: number | null
  error_code: string
  error_message: string
}

export interface TrafficStartResponse {
  run: TrafficRun
}

export interface TrafficSummaryResponse {
  traffic_run_id: string
  updated_at: string
  summary: Record<string, unknown>
}

export interface TrafficCancelResponse {
  traffic_run_id: string
  controller_task_id: string
  status: TaskStatus
  message: string
}

export interface TrafficRetryResponse {
  run: TrafficRun
  retry_of_traffic_run_id: string
}

export interface IperfServerRequest {
  execution_target: TrafficExecutionTargetRequest
  bind_ip?: string
  port: number
  interval_seconds: number
  one_off: boolean
}

export interface IperfClientRequest {
  execution_target: TrafficExecutionTargetRequest
  server_ip: string
  port: number
  protocol: 'TCP' | 'UDP'
  duration_seconds: number
  interval_seconds: number
  parallel: number
  direction: 'upload' | 'download' | 'bidirectional'
  target_bandwidth?: string | null
  tcp_block_size?: string | null
  packet_length?: number | null
}

export interface FpingRequest {
  execution_target: TrafficExecutionTargetRequest
  targets: string[]
  interval_ms: number
  timeout_ms: number
  packet_size: number
  count: number
  continuous: boolean
  source_address?: string
}

export type TrafficSocketMessage =
  | { type: 'ready'; traffic_run_id: string }
  | { type: 'event'; event: TrafficEvent }
  | { type: 'events'; events: TrafficEvent[] }
  | { type: 'samples'; samples: TrafficPingSample[] }
  | { type: 'heartbeat' }
