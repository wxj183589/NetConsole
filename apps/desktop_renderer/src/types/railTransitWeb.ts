export interface RailTransitTask {
  task_id: string
  status: string
  action: string
  artifact_id: string
  artifact_name: string
  available: boolean
  artifact_state?: string
  artifact_message?: string
  sha256: string
  size_bytes: number
  message: string
  error_message: string
  result_summary: Record<string, unknown>
}

export type OnlineMrParsedDatabaseUpgradeStatus = 'CURRENT' | 'REQUIRED' | 'UPGRADING' | 'FAILED' | 'RAW_DATA_MISSING'

export interface OnlineMrParsedDatabaseEnsureResult {
  status: OnlineMrParsedDatabaseUpgradeStatus
  current_schema_version: number | null
  target_schema_version: number
  missing_capabilities: string[]
  message: string
  retry_suppressed: boolean
  task: RailTransitTask | null
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

export interface CarNetworkPointRow {
  train_id: string; train_no: string; display_name: string; tc: string; end: string
  node_name: string; node_type: string; device_id: string; device_name: string; device_group: string
  station: string; primary_address: string; backup_address: string; ip_vehicle: string; ip_uplink: string
  ssh_host: string; vrrp_ip: string; address_mapping_mode: string
  primary_address_role: string; backup_address_role: string; remark: string
}

export interface CarNetworkPointTable {
  rows: CarNetworkPointRow[]
  global_config: Record<string, unknown>
  locked: boolean
  revision: string
}

export interface CarNetworkPointPreviewRow {
  row_number: number; status: 'valid' | 'duplicate' | 'error'; key: string; message: string
  row: CarNetworkPointRow | null
}

export interface CarNetworkPointPreview {
  file_name: string; file_sha256: string; duplicate_strategy: 'replace' | 'skip' | 'error'
  can_apply: boolean; total_count: number; valid_count: number; duplicate_count: number; error_count: number
  rows: CarNetworkPointPreviewRow[]; result_rows: CarNetworkPointRow[]
}

export interface OnlineMrTimelineEvent {
  event_id: string; session_id: string; local_time: string | null; device_time: string | null
  source: string; event_type: string; severity: string | null; title: string; payload: Record<string, unknown>
}

export interface MeshImportProfile {
  mr_id: string
}

export interface OnlineTrainRow {
  train_id: string
  train_no: string
  train_name: string
  communication_status: string
  current_mesh_links: number
  active_sessions: number
  warning_count: number
  last_updated_at: string | null
}

export interface OnlineTrainPage {
  items: OnlineTrainRow[]
  total: number
  page: number
  page_size: number
}
