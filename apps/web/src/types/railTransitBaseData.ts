export interface Mileage {
  raw: string
  normalized: string
  meters: number | null
  line_type: string
  valid: boolean
  error: string
}

export interface RuntimeStatus {
  fit_ap_status: string
  optical_status: string
  mesh_status: string
  mesh_related_name: string
  latest_session_id: string
  latest_session_status: string
  updated_at: string
}

export interface DataQualityIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  entity_type: string
  entity_id: string
  entity_name: string
  row_number: number | null
  field_name: string
  original_value: string
  message: string
  suggested_action: string
}

export interface RailTransitSummary {
  site_id: string
  site_name: string
  line_name: string
  project_type: string
  network_type: string
  remark: string
  created_at: string
  updated_at: string
  station_count: number
  section_count: number
  ap_count: number
  train_count: number
  mr_count: number
  missing_location_ap_count: number
  invalid_mileage_count: number
  duplicate_ap_mac_count: number
  duplicate_static_ip_count: number
  unbound_mr_count: number
  issue_count: number
  message: string
}

export interface Station {
  id: string
  name: string
  code: string
  line_name: string
  sort_order: number
  ap_count: number
  section_count: number
  mileage_min: number | null
  mileage_max: number | null
  remark: string
}

export interface Section {
  id: string
  name: string
  start_station: string
  end_station: string
  line_side: string
  ap_count: number
  mileage_min: number | null
  mileage_max: number | null
  remark: string
}

export interface MeshRadio {
  radio_id: number
  channel: string
  bandwidth: string
  power: string
  bssid: string
}

export interface TracksideAp {
  id: string
  site_id: string
  line_name: string
  name: string
  point_code: string
  mac: string
  management_ip: string
  model: string
  station: string
  section: string
  section_start_station: string
  section_end_station: string
  mileage: Mileage
  line_side: string
  direction: string
  radios: MeshRadio[]
  remark: string
  source_file: string
  source_sheet: string
  source_row: number | null
  updated_at: string
  runtime: RuntimeStatus
  issue_count: number
  highest_issue_severity: string
}

export interface VehicleMr {
  id: string
  device_id: number | null
  name: string
  train_id: string
  train_no: string
  role: string
  management_ip: string
  mac: string
  protocol: string
  port: number | null
  remark: string
  runtime: RuntimeStatus
  issue_count: number
  highest_issue_severity: string
}

export interface Train {
  id: string
  train_no: string
  name: string
  mr_count: number
  roles: string[]
  latest_mesh_status: string
  latest_session_id: string
  issue_count: number
  highest_issue_severity: string
}

export interface Relation {
  mr_id: string
  mr_name: string
  train_no: string
  ap_id: string
  ap_name: string
  station: string
  section: string
  status: string
  updated_at: string
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface ImportPreviewRow {
  row_number: number
  entity_type: string
  values: Record<string, unknown>
  issues: DataQualityIssue[]
}

export interface ImportPreviewResult {
  file_name: string
  file_size: number
  template_type: string
  confidence_score: number
  total_rows: number
  valid_rows: number
  error_count: number
  warning_count: number
  rows: ImportPreviewRow[]
  message: string
}

export interface PageQuery {
  query?: string
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: string
  [key: string]: string | number | boolean | undefined
}
