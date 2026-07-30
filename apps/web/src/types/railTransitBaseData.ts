export interface Mileage {
  raw: string
  normalized: string
  meters: number | null
  line_type: string
  valid: boolean
  error: string
}

export interface RuntimeStatus {
  fit_ap_id: string
  fit_ap_ac_id: string
  fit_ap_name: string
  fit_ap_match_status: string
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

export interface BaseDataClearPreview {
  site_id: string
  base_revision: string
  station_count: number
  section_count: number
  affected_trackside_ap_count: number
}

export interface BaseDataClearResult {
  revision: string
  deleted_station_count: number
  deleted_section_count: number
  unlinked_trackside_ap_count: number
  deleted_trackside_ap_plan_count: number
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
  main_path_code: string
  increasing_direction_name: string
  decreasing_direction_name: string
  increasing_direction_line_side: string
  decreasing_direction_line_side: string
  increasing_direction_leading_end: 'car_1_end' | 'car_6_end' | 'unknown'
  station_source_group_name: string
  station_source_field: string
  remark: string
  created_at: string
  updated_at: string
  station_count: number
  normal_station_count: number
  special_node_count: number
  source_pending_count: number
  source_conflict_count: number
  source_stale_count: number
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
  node_uid: string
  name: string
  code: string
  line_name: string
  sort_order: number | null
  ap_count: number
  section_count: number
  mileage_min: number | null
  mileage_max: number | null
  remark: string
  source_station_value: string
  source_station_key: string
  source_order_text: string
  source_order: number | null
  canonical_station_name: string
  node_type: StationNodeType
  path_code: string
  participates_in_direction: boolean
  structure_type: StationStructureType
  platform_layout: StationPlatformLayout
  center_mileage_text: string
  center_mileage_m: number | null
  is_line_terminal: boolean
  is_service_terminal: boolean
  turnback_capable: boolean
  turnback_type: StationTurnbackType
  track_facilities: StationTrackFacility[]
  turnback_direction: StationTurnbackDirection
  terminal_extension_enabled: boolean
  terminal_endpoint_label: string
  terminal_extension_distance_m: number | null
  terminal_endpoint_mileage_text: string
  enabled: boolean
  source_kind: StationSourceKind
  source_device_count: number
  source_sync_status: StationSourceSyncStatus
  source_last_seen_at: string
}

export type StationNodeType = 'station' | 'parking_lot' | 'depot' | 'connection_point' | 'other' | 'unknown'
export type StationStructureType = 'underground' | 'elevated' | 'at_grade' | 'cutting' | 'mixed' | 'unknown'
export type StationPlatformLayout = 'island' | 'side' | 'mixed' | 'stacked_island' | 'stacked_side' | 'separated' | 'unknown'
export type StationTurnbackType = 'none' | 'crossover' | 'pocket_track' | 'tail_track' | 'loop' | 'depot_connection' | 'other' | 'unknown'
export type StationTrackFacility = 'turnback_track' | 'crossover' | 'storage_track' | 'depot_connection' | 'tail_track' | 'loop' | 'siding' | 'other'
export type StationTurnbackDirection = 'none' | 'both' | 'increasing_to_decreasing' | 'decreasing_to_increasing' | 'unknown'
export type StationSourceKind = 'device_station_field' | 'template' | 'manual' | 'legacy_ap_derived'
export type StationSourceSyncStatus = 'matched' | 'stale' | 'conflict' | 'manual' | 'legacy' | 'unavailable'

export interface StationSourceIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
  field_name: string
  blocking: boolean
  entity_id: string
}

export interface StationSourceCandidate {
  candidate_id: string
  source_station_value: string
  source_station_key: string
  source_order_text: string
  source_order: number | null
  code: string
  name: string
  canonical_name: string
  order_parse_method: string
  parse_confidence: string
  parse_warning: string
  canonical_station_name: string
  node_type: StationNodeType
  path_code: string
  sort_order: number | null
  participates_in_direction: boolean
  source_device_count: number
  match_status: 'exact_source_key' | 'canonical_name' | 'canonical_name_and_type' | 'alias' | 'create' | 'conflict' | 'manual_review'
  matched_station_id: string
  matched_station_name: string
  matched_station_ids: string[]
  matched_station_names: string[]
  match_basis: string
  suggested_action: string
  processing_strategy: StationSourceProcessingStrategy
  processing_options: StationSourceProcessingStrategy[]
  cleanup_name_prefix_recommended: boolean
  proposed_station: Station
  issues: StationSourceIssue[]
}

export interface StationSourcePreview {
  site_id: string
  source_group_name: string
  source_field: string
  group_found: boolean
  scanned_device_count: number
  empty_station_device_count: number
  unique_station_value_count: number
  normal_station_count: number
  special_node_count: number
  create_count: number
  match_count: number
  conflict_count: number
  manual_review_count: number
  canonical_match_count: number
  recommended_overwrite_count: number
  recommended_create_count: number
  recommended_merge_count: number
  remaining_manual_count: number
  warning_count: number
  candidates: StationSourceCandidate[]
  issues: StationSourceIssue[]
}

export type StationSourceProcessingStrategy = 'auto_match' | 'overwrite_existing' | 'create' | 'ignore' | 'manual_target' | 'merge_duplicates'
export type StationDeletePreflightStatus = 'SAFE_DELETE' | 'REQUIRES_MERGE' | 'BLOCKED'

export interface StationReferenceSummary {
  section_start_count: number
  section_end_count: number
  ap_count: number
  relation_count: number
  endpoint_extension_count: number
  plan_count: number
  total_count: number
}

export interface StationDeletePreflightItem {
  station_id: string
  station_name: string
  code: string
  sort_order: number | null
  source_kind: StationSourceKind
  status: StationDeletePreflightStatus
  reason: string
  is_manual: boolean
  is_line_terminal: boolean
  references: StationReferenceSummary
}

export interface StationDeletePreflight {
  site_id: string
  base_revision: string
  items: StationDeletePreflightItem[]
  safe_delete_count: number
  requires_merge_count: number
  blocked_count: number
}

export interface StationConflictMember {
  station_id: string
  station_name: string
  code: string
  node_uid: string
  node_type: StationNodeType
  path_code: string
  sort_order: number | null
  source_kind: StationSourceKind
}

export interface StationConflictGroup {
  group_id: string
  path_code: string
  sort_order: number
  stations: StationConflictMember[]
  suggested_action: 'OVERWRITE' | 'MERGE' | 'MANUAL'
  reason: string
}

export interface StationConflictPreview {
  site_id: string
  base_revision: string
  groups: StationConflictGroup[]
  conflict_group_count: number
  conflict_station_count: number
  recommended_overwrite_count: number
  recommended_merge_count: number
  remaining_manual_count: number
}

export interface StationTemplatePreviewRow {
  row_number: number
  source_station_value: string
  source_station_key: string
  code: string
  name: string
  node_type: StationNodeType
  path_code: string
  sort_order: number | null
  participates_in_direction: boolean
  proposed_station: Station | null
  action: 'create' | 'update' | 'unchanged' | 'conflict'
  valid: boolean
  issues: StationSourceIssue[]
}

export interface StationTemplatePreview {
  valid: boolean
  line_metadata: Record<string, unknown>
  rows: StationTemplatePreviewRow[]
  section_rows: StationTemplateSectionPreviewRow[]
  section_sheet_present: boolean
  create_count: number
  update_count: number
  unchanged_count: number
  conflict_count: number
  blocking_count: number
  issues: StationSourceIssue[]
}

export interface StationTemplateSectionPreviewRow {
  row_number: number
  section_code: string
  name: string
  section_kind: SectionKind
  path_code: string
  direction_role: SectionDirectionRole
  line_direction: string
  start_node_type: SectionNodeType
  start_station: string
  end_node_type: SectionNodeType
  end_station: string
  proposed_section: Section | null
  action: 'create' | 'update' | 'unchanged' | 'conflict'
  valid: boolean
  issues: StationSourceIssue[]
}

export interface Section {
  id: string
  name: string
  section_code: string
  section_kind: SectionKind
  path_code: string
  direction_role: SectionDirectionRole
  line_direction: string
  start_node_type: SectionNodeType
  start_node_uid: string
  start_station: string
  end_node_type: SectionNodeType
  end_node_uid: string
  end_station: string
  line_side: string
  auto_generated: boolean
  generation_key: string
  manual_override_fields: string[]
  section_mileage_start_m: number | null
  section_mileage_end_m: number | null
  section_mileage_open_end: boolean
  section_mileage_source: SectionMileageSource
  enabled: boolean
  source_kind: SectionSourceKind
  ap_count: number
  mileage_min: number | null
  mileage_max: number | null
  remark: string
}

export type SectionKind = 'between_stations' | 'terminal_extension' | 'depot_connection' | 'manual' | 'legacy'
export type SectionDirectionRole = 'increasing' | 'decreasing' | 'none' | 'unknown'
export type SectionNodeType = 'station' | 'terminal_endpoint' | 'legacy' | 'unknown'
export type SectionSourceKind = 'generated' | 'manual' | 'template' | 'legacy_ap_derived'
export type SectionMileageSource = 'generated' | 'manual' | 'unavailable'
export type SectionGenerationResult = 'CREATE' | 'UPDATE' | 'UNCHANGED' | 'CONFLICT' | 'STALE'

export interface SectionGenerationPreviewItem {
  item_id: string
  result: SectionGenerationResult
  proposed_section: Section | null
  current_section: Section | null
  selected_by_default: boolean
  selectable: boolean
  issues: StationSourceIssue[]
}

export interface SectionGenerationPreview {
  site_id: string
  base_revision: string
  generated_sections: SectionGenerationPreviewItem[]
  create_count: number
  update_count: number
  unchanged_count: number
  conflict_count: number
  stale_count: number
  blocking_count: number
  issues: StationSourceIssue[]
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
  line_side_source: 'section_direction' | 'manual' | 'import' | 'legacy' | 'unavailable'
  line_side_derivation_issue_code: string
  line_side_derivation_issue_message: string
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
  mr_position_code: 'CT' | 'CW' | 'unknown'
  physical_end: 'car_1_end' | 'car_6_end' | 'unknown'
  car_number: number | null
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
  mr_position_codes: Array<'CT' | 'CW' | 'unknown'>
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
  sheet_names?: string[]
  statistics?: Record<string, number>
  rows: ImportPreviewRow[]
  merge_plan: MergePlan | null
  database_hash: string
  preview_expires_at: string
  write_enabled: boolean
  message: string
}

export type MergeResult = 'CREATE' | 'UPDATE' | 'UNCHANGED' | 'SKIP' | 'CONFLICT' | 'INVALID' | 'NEEDS_CONFIRMATION'

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
  source_values: Record<string, unknown>
  blocking: boolean
  issues: DataQualityIssue[]
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
    total_rows: number
    importable_count: number
    create_count: number
    update_count: number
    unchanged_count: number
    skip_count: number
    conflict_count: number
    invalid_count: number
    warning_count: number
    unmatched_fit_ap_count: number
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
  total_rows: number
  imported_rows: number
  created_rows: number
  updated_rows: number
  unchanged_rows: number
  warning_rows: number
  skipped_conflict_rows: number
  skipped_invalid_rows: number
  unmatched_fit_ap_rows: number
  issues: DataQualityIssue[]
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
