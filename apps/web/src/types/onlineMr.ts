export interface OnlineMrSessionSummary {
  session_id: string
  site_id: string
  mr_name: string
  device_id: string | number | null
  device_name: string
  status: string
  phase: string | null
  created_at: string | null
  started_at: string | null
  stopped_at: string | null
  duration_seconds: number | null
  duration_minutes: number | null
  controller_task_id: string | null
  executor_kind: string | null
  agent_id: string | null
  has_raw_data: boolean
  has_parsed_data: boolean
  has_package: boolean
  package_name: string | null
  package_reference: string | null
  force_stopped: boolean | null
  finalization_complete: boolean | null
  stop_reason: string | null
  task_status: string | null
  mapping_state: string | null
  error_code: string | null
  error_message: string | null
}

export interface OnlineMrSessionDetail extends OnlineMrSessionSummary {
  session_path_reference: string
  connection_summary: Record<string, unknown>
  collection_config: Record<string, unknown>
  enabled_collectors: string[]
  traffic_summary: Record<string, unknown>
  file_summary: Record<string, unknown>
  database_summary: Record<string, unknown>
  notes_count: number
  latest_metric_time: string | null
  data_integrity: 'complete' | 'partial' | 'unknown'
}

export interface OnlineMrCollectorStatus {
  name: string
  label: string
  status: string
  enabled: boolean
  raw_file: string
  exists: boolean
  size_bytes: number
  error: string
  started_at: string | null
  ended_at: string | null
  updated_at: string | null
}

export interface OnlineMrRealtimePreview {
  session_id: string
  available: boolean
  updated_at: string | null
  message: string
  display_context: Record<string, unknown>
  link: Record<string, unknown>
  fping: Record<string, unknown>
  iperf: Record<string, unknown>
}

export interface OnlineMrRawFile {
  name: string
  relative_name: string
  exists: boolean
  size_bytes: number
  modified_at: string | null
}

export interface OnlineMrRawTail {
  success: boolean
  name: string
  exists: boolean
  lines: string[]
  message: string
  size_bytes: number
  modified_at: string | null
  summary: Record<string, unknown>
}

export interface OnlineMrManualNote {
  event_id: string
  session_id: string
  local_time: string | null
  device_time: string | null
  source: string
  event_type: string
  severity: string | null
  title: string
  payload: Record<string, unknown>
}
