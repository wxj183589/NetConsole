export interface RailTransitTask {
  task_id: string
  status: string
  action: string
  artifact_id: string
  available: boolean
  sha256: string
  size_bytes: number
  message: string
  error_message: string
  result_summary: Record<string, unknown>
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
  points: OnlineMrMetricPoint[]
  summary: { count: number; minimum: number | null; maximum: number | null; average: number | null }
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
