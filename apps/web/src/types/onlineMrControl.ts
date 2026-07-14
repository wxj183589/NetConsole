import type { MrCommunicationStatus } from './trainCommunication'

export type OnlineMrControlState = 'idle' | 'preparing' | 'starting' | 'running' | 'stopping' | 'stopped' | 'completed_with_warnings' | 'failed' | 'aborted'

export interface OnlineMrCollectorStatus {
  name: string; label: string; status: string; enabled: boolean; raw_file: string
  exists: boolean; size_bytes: number; error: string; started_at: string | null; ended_at: string | null; updated_at: string | null
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

export interface OnlineMrControlStatus { enabled: boolean; local_only: true; site_id: string; operations: OnlineMrControlOperation[] }

export interface OnlineMrStartConfig {
  site_id: string; device_id: string | number; mr_id: string; executor: 'LOCAL'; duration_minutes: number
  items: { terminal_monitor: true; mesh_link: boolean; channel_busy: boolean; ap_radio_statistics: boolean; switch_history: boolean; interface_rate: boolean; wireless_status: boolean }
  intervals: { mesh_link: number; channel_busy: number; ap_radio_statistics: number; switch_history: number; interface_rate: number; wireless_status: number }
  radio: { channel_busy_radio: number; ap_radio_statistics_radio: number; wireless_status_radio: number }
  fping: { enabled: boolean; target: string; packet_size: number; interval_ms: number; timeout_ms: number; loss_warn_percent: number; latency_warn_ms: number }
  iperf: { enabled: boolean; server_ip: string; port: number; protocol: 'TCP' | 'UDP'; parallel: number; interval_seconds: number; udp_bitrate_mbps: number | null; tcp_report_threshold_mbps: number | null; reverse: boolean }
}

export type OnlineMrControlMr = Pick<MrCommunicationStatus, 'mr_id' | 'mr_name' | 'device_id' | 'management_ip' | 'train_name' | 'mr_role'>
