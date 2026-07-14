import type { OnlineMrControlMr, OnlineMrStartConfig } from './onlineMrControl'

export interface OnlineMrAgentProfile {
  profile_id: string; name: string; address_display: string; enabled: boolean
  status: string; has_credential: boolean
}

export interface OnlineMrAgentCapabilities {
  agent_executor_enabled: boolean; site_id: string; profiles: OnlineMrAgentProfile[]
}

export interface OnlineMrAgentReadiness {
  profile_id: string; ready: boolean; reachable: boolean; authenticated: boolean
  agent_id: string; version: string; mr_collector_ready: boolean; fping_ready: boolean
  iperf3_ready: boolean; error_code: string; error_summary: string
}

export interface OnlineMrAgentOperation {
  operation_id: string; controller_task_id: string; session_id: string | null; site_id: string
  device_id: string | number | null; device_name: string; mr_id: string; mr_name: string
  executor: 'AGENT'; agent_id: string; agent_profile_id: string; agent_task_id: string
  remote_session_id: string; remote_package_id: string; state: string; phase: string
  remote_status: string; task_status: string | null; mapping_status: string
  started_at: string | null; updated_at: string; deadline_at: string | null
  duration_minutes: number | null; consecutive_status_failures: number
  package_status: string; download_status: string; import_status: string; data_integrity: string
  error_code: string; error_summary: string
}

export interface OnlineMrAgentStatus {
  agent_executor_enabled: boolean; site_id: string; operations: OnlineMrAgentOperation[]
}

export interface OnlineMrAgentStartConfig extends Omit<OnlineMrStartConfig, 'executor'> {
  executor: 'AGENT'; agent_profile_id: string
}

export type OnlineMrAgentControlMr = OnlineMrControlMr
