import type { MrCommunicationStatus } from './trainCommunication'

export type OnlineMrControlState = 'idle' | 'preparing' | 'starting' | 'running' | 'stopping' | 'stopped' | 'completed_with_warnings' | 'failed' | 'aborted'

export interface OnlineMrCollectorStatus {
  name: string; label: string; status: string; enabled: boolean; raw_file: string
  exists: boolean; size_bytes: number; error: string; started_at: string | null; ended_at: string | null; updated_at: string | null
  health_status: 'normal' | 'stale' | 'interrupted' | 'unknown'; stale_seconds: number | null
  client_status?: string; server_status?: string; supervisor_status?: string
  pid?: number | null; alive?: boolean | null; exit_code?: number | null; last_error?: string; stderr_tail?: string
  last_exit_at?: string | null; last_data_at?: string | null; bytes_written?: number; restart_count?: number; stop_reason?: string
}

export interface OnlineMrControlOperation {
  operation_id: string; task_id: string; session_id: string | null; site_id: string
  device_id: string | number | null; device_name: string; mr_id: string; mr_name: string
  owner: string; executor: 'LOCAL'; state: OnlineMrControlState; phase: string
  task_status: string | null; session_status: string | null; mapping_status: string
  started_at: string | null; updated_at: string; duration_minutes: number | null; duration_limit: number | null
  collectors: OnlineMrCollectorStatus[]; fping_status: string; iperf_status: string
  package_status: string; package_path_reference: string | null; error_code: string; error_summary: string; data_integrity: string
}

export interface OnlineMrControlStatus {
  enabled: boolean; local_only: true; site_id: string; operations: OnlineMrControlOperation[]
  real_device_test: boolean; safety_constraints: Record<string, unknown>
}

export interface OnlineMrPingPreset {
  key: string; name: string; packet_size_bytes: number; interval_ms: number; timeout_ms: number
  loss_warn_percent: number; latency_warn_ms: number; description: string
}

export interface OnlineMrTrafficPreset {
  key: string; name: string; protocol: 'TCP' | 'UDP'; test_type: string
  deployment_mode: string; business_direction: string; report_threshold_mbps: number
  udp_bitrate_mbps: number | null; packet_length: number | null; parallel: number
  reverse: boolean; duration_sec: number; interval_sec: number; port: number; duration_mode: string
}

export interface OnlineMrControlPresets {
  ping: OnlineMrPingPreset[]; traffic: OnlineMrTrafficPreset[]
}

export interface OnlineMrStartConfig {
  site_id: string; device_id: string | number; mr_id: string; executor: 'LOCAL'; duration_minutes: number
  items: { terminal_monitor: true; mesh_link: boolean; channel_busy: boolean; ap_radio_statistics: boolean; switch_history: boolean; interface_rate: boolean; wireless_status: boolean }
  intervals: { mesh_link: number; channel_busy: number; ap_radio_statistics: number; switch_history: number; interface_rate: number; wireless_status: number }
  radio: {
    radio_mode: '' | 'unified' | 'per_collector'; unified_radio_id: number | null
    collector_radio_ids: Record<string, number>
    channel_busy_radio: number; ap_radio_statistics_radio: number; wireless_status_radio: number
  }
  fping: { enabled: boolean; target: string; preset_key: string; preset_name: string; packet_size: number; interval_ms: number; timeout_ms: number; loss_warn_percent: number; latency_warn_ms: number }
  iperf: { enabled: boolean; server_ip: string; port: number; protocol: 'TCP' | 'UDP'; parallel: number; interval_seconds: number; udp_bitrate_mbps: number | null; tcp_report_threshold_mbps: number | null; tcp_rate_limit_mbps: number | null; packet_length: number | null; reverse: boolean }
}

export type OnlineMrControlMr = Pick<MrCommunicationStatus, 'mr_id' | 'mr_name' | 'device_id' | 'management_ip' | 'train_name' | 'mr_role'>
