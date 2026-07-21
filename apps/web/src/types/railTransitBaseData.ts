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

export type BaseDataEntityType = 'site_metadata' | 'station' | 'section' | 'trackside_ap' | 'vehicle_mr' | 'trackside_ap_plan'
export type BaseDataChangeAction = 'create' | 'update' | 'delete' | 'replace'

export interface BaseDataEditSession {
  site_id: string
  base_revision: string
  loaded_at: string
  can_write: boolean
  write_scope: 'copy_validation' | 'real'
  storage_mode: 'persistent' | 'isolated_test'
  write_denial_code: string
  write_denial_reason: string
}

export interface BaseDataChange {
  entity_type: BaseDataEntityType
  action: BaseDataChangeAction
  entity_id?: string
  values: Record<string, unknown>
}

export interface BaseDataValidationIssue {
  change_index: number
  code: string
  message: string
  field_name: string
  blocking: boolean
}

export interface BaseDataValidationResult {
  valid: boolean
  issues: BaseDataValidationIssue[]
}

export interface BaseDataSaveResult {
  revision: string
  created_count: number
  updated_count: number
  deleted_count: number
  warnings: string[]
  validation_issues: BaseDataValidationIssue[]
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
  blocking: boolean
}

export interface DataQualityEntityGroup {
  entity_type: string
  entity_id: string
  display_name: string
  issue_count: number
  error_count: number
  warning_count: number
  info_count: number
  blocking: boolean
  needs_confirmation: boolean
  issues: DataQualityIssue[]
  suggested_action: string
}

export interface DataQualityEntityGroupPage extends Page<DataQualityEntityGroup> {
  issue_total: number
  blocking_total: number
  warning_total: number
  info_total: number
  code_counts: Record<string, number>
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
  record_kind: string
  base_metadata: Record<string, unknown>
}

export interface VehicleMr {
  id: string
  device_id: number | null
  name: string
  train_id: string
  train_no: string
  role: string
  management_ip: string
  station: string
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
  preview_id: string
  file_name: string
  file_size: number
  template_type: string
  confidence_score: number
  total_rows: number
  valid_rows: number
  error_count: number
  warning_count: number
  rows: ImportPreviewRow[]
  merge_plan: MergePlan | null
  database_hash: string
  preview_expires_at: string
  write_enabled: boolean
  message: string
}

export type MergeResult = 'CREATE' | 'UPDATE' | 'UNCHANGED' | 'SKIP' | 'CONFLICT' | 'NEEDS_CONFIRMATION'

export interface MergeFieldDiff {
  field_name: string
  current_value: unknown
  proposed_value: unknown
  source: { source_type: string; source_reference: string; source_row: number | null }
  action: 'keep_existing' | 'use_imported' | 'fill_missing' | 'manual_review'
  warning: string
}

export interface MergePlanItem {
  row_number: number
  entity_type: string
  source_identity: Record<string, unknown>
  matched_entity_id: string
  matched_entity_name: string
  match_method: string
  result: MergeResult
  conflict_summary: string
  field_diffs: MergeFieldDiff[]
  blocking: boolean
}

export interface MergePlan {
  plan_id: string
  site_id: string
  source_file_name: string
  source_file_sha256: string
  source_type: string
  created_at: string
  database_hash: string
  preview_expires_at: string
  write_enabled: boolean
  items: MergePlanItem[]
  summary: {
    create_count: number
    update_count: number
    unchanged_count: number
    skip_count: number
    conflict_count: number
    needs_confirmation_count: number
    blocking_count: number
  }
}

export interface ImportPolicyStatus {
  feature_enabled: boolean
  write_enabled: boolean
  copy_write_authorized: boolean
  real_write_authorized: boolean
  rollback_enabled: boolean
  write_scope: 'copy_validation' | 'real'
  identity_boundaries: Record<string, string>
  items: Array<{ entity_type: string; field_name: string; priority: string[]; runtime_only: boolean; note: string }>
}

export interface MergeFieldDecision {
  row_number: number
  field_name: string
  action: 'keep_existing' | 'use_imported' | 'fill_missing' | 'skip_entity'
}

export interface ImportApplyResult {
  operation_id: string
  status: string
  created_count: number
  updated_count: number
  skipped_count: number
  warning_count: number
  backup_id: string
  database_sha256_before: string
  database_sha256_after: string
  audit_id: string
}

export interface ImportOperation {
  operation_id: string
  preview_id: string
  site_id: string
  source_file_name: string
  source_file_sha256: string
  owner: string
  started_at: string
  ended_at: string
  status: string
  created_count: number
  updated_count: number
  skipped_count: number
  warning_count: number
  backup_reference: string
  database_hash_before: string
  database_hash_after: string
  error_code: string
  error_summary: string
  rolled_back_at: string
}

export interface ImportChange {
  operation_id: string
  entity_type: string
  entity_id: string
  action: string
  field_name: string
  old_value: unknown
  new_value: unknown
  source_type: string
  source_reference: string
  confirmation_method: string
}

export interface PageQuery {
  query?: string
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: string
  [key: string]: string | number | boolean | undefined
}
