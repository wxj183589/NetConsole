import type { TrafficExecutionTargetRequest, TrafficRun } from './traffic'
import type { TaskStatus } from './task'

export interface TcpPortTestRequest {
  execution_target: TrafficExecutionTargetRequest
  target: string
  port: number
  interval_ms: number
  timeout_ms: number
  count: number
}

export interface TcpPortTestResponse {
  run: TrafficRun
}

export interface ToolboxResult {
  rows: Record<string, unknown>[]
  summary: Record<string, unknown>
  errors: string[]
}

export interface NetworkToolTask {
  id: string
  type: string
  name: string
  status: TaskStatus
  progress: number
  current: number
  total: number
  message: string
  created_time: string
  updated_time: string
  finished_time: string
  result_path: string
  error_message: string
  result: Record<string, unknown>
  source: string
  cancellable: boolean
}

export interface NetworkTaskStartRequest {
  kind: 'single_ping' | 'continuous_ping' | 'batch_ping' | 'subnet_ping' | 'tcp_ping'
  target?: string
  targets?: string[]
  port?: number
  interval_ms?: number
  timeout_ms?: number
  count?: number
  packet_size?: number
  concurrency?: number
  source_ip?: string
  usable_only?: boolean
}

export interface NetworkTaskResponse { task: NetworkToolTask }

export interface NetworkTaskResultPage {
  items: Record<string, unknown>[]
  offset: number
  limit: number
  total: number
  next_offset: number
  next_cursor: number
  has_more: boolean
}

export interface NetworkToolArtifact {
  artifact_id: string
  filename: string
  format: 'csv' | 'xlsx'
  sha256: string
  size: number
  download_url: string
}

export interface WirelessAdapter {
  name: string
  guid: string
  state: string
  connected_ssid: string
  display_name: string
}

export interface WirelessProject {
  project_id: string
  name: string
  description: string
}

export interface WirelessScanRun {
  scan_id: string
  site: string
  project_id: string
  project_name: string
  project_description: string
  adapter_name: string
  adapter_guid: string
  started_at: string
  ended_at: string
  status: string
  network_count: number
  raw_file: string
}

export interface NetworkAdapter {
  name: string
  interface_index: number
  status: string
  ipv4_addresses: string[]
  display_name: string
}

export interface NetworkProbeEnvironment {
  adapters: NetworkAdapter[]
  scan_engine: string
  scan_engine_available: boolean
  supports_source_ip: boolean
  message: string
}

export interface WirelessScanRunDetail extends Omit<WirelessScanRun, 'site' | 'raw_file'> {
  raw_output: string
}

export interface WirelessScanStartRequest {
  adapter_name: string
  adapter_guid: string
  project_id: string
  scan_source: 'auto' | 'hybrid' | 'wlan_api' | 'netsh'
}

export interface WirelessScanPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface WirelessScanFilters {
  only_trackside?: boolean
  band?: string
  radio?: string
  search?: string
}
