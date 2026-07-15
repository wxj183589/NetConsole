export interface RailTransitTask {
  task_id: string
  status: string
  action: string
  artifact_id: string
  available: boolean
  sha256: string
  size_bytes: number
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

export interface MeshImportProfile {
  mr_id: string
  display_name: string
  safe_folder_name: string
  linked_device_id?: number
  notes?: string
}
