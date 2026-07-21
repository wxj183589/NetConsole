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
  database_summary: OnlineMrDatabaseSummary
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
  health_status: 'normal' | 'stale' | 'interrupted' | 'unknown'
  stale_seconds: number | null
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

export type OnlineMrParsedStatus = 'ready' | 'missing' | 'legacy' | 'stale' | 'unreadable' | 'parsing'

export interface OnlineMrDatabaseSummary {
  status: OnlineMrParsedStatus
  available: boolean
  compatible: boolean | null
  size_bytes: number
  modified_at: string | null
  schema_version: string | null
  parser_version: string | null
  tables: string[]
  row_counts: Record<string, number>
  available_capabilities: string[]
  missing_capabilities: string[]
  missing_tables: string[]
  error_code: string | null
  message: string
  recoverable: boolean
  action: string | null
}

export interface OnlineMrMetricPoint {
  timestamp: string | null
  value: number | null
  text_value: string | null
  dimensions: Record<string, unknown>
}

export interface OnlineMrMetricSeries {
  metric_type: string
  series_key: string
  unit: string
  points: OnlineMrMetricPoint[]
  summary: { count: number; minimum: number | null; maximum: number | null; average: number | null }
}

export interface OnlineMrMetricPage {
  series: OnlineMrMetricSeries[]
  limit: number
  offset: number
  page_size_per_metric: number
  next_offset: number
  returned_points: number
  has_more: boolean
}

export type OnlineMrSwitchRssiSource = 'history' | 'realtime'

export type OnlineMrBusinessTable = 'mesh_link' | 'mesh_detail' | 'channel_busy' | 'radio_statistics' | 'switch_history' | 'switch_realtime' | 'interface_rate' | 'fping_1s' | 'iperf' | 'diagnostics'

export interface OnlineMrBusinessSummary {
  session_id: string
  sample_count: number
  active_count: number
  standby_count: number
  active_segment_count: number
  switch_count: number
  fping_point_count: number
  iperf_point_count: number
  channel_busy_count: number
  interface_pps_count: number
  diagnosis_count: number
  first_sample_time: string | null
  last_sample_time: string | null
  estimated_interval_seconds: number | null
  time_sync_status: string
  time_sync_avg_offset_ms: number | null
  current_radio: number | null
  current_link_state: string
  current_peer_mac: string
  current_peer_name: string
  current_ap_mac: string
  current_peer_radio_mac: string
  current_station: string
  current_section: string
  current_rssi: number | null
  current_segment_start: string | null
  current_segment_end: string | null
  current_segment_duration_seconds: number | null
}

export interface OnlineMrBusinessTablePage {
  table: OnlineMrBusinessTable
  rows: Array<Record<string, unknown>>
  limit: number
  offset: number
  returned_count: number
  next_offset: number
  has_more: boolean
}

export interface OnlineMrSwitchRssiWindow {
  event_id: string
  source: OnlineMrSwitchRssiSource
  event_time: string | null
  radio: number | null
  reason: string
  old_peer_name: string
  old_peer_mac: string
  old_rssi_dbm: number | null
  new_peer_name: string
  new_peer_mac: string
  new_rssi_dbm: number | null
  raw_file: string
  raw_line_start: number | null
  raw_line_end: number | null
}

export interface OnlineMrSwitchRssiPage {
  items: OnlineMrSwitchRssiWindow[]
  limit: number
  offset: number
  has_more: boolean
}

export interface OnlineMrTimelineEvent {
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
