import type { RailTransitTask } from './railTransitWeb'

export interface TracksideApBusinessRow {
  row_id?: string
  station_id?: string; site: string; device_name: string; switch_device_uuid?: string; switch_terminal_available?: boolean; switch_terminal_unavailable_reason?: string; switch_vendor: string; interface_name: string; link_status: string; port_type: string
    switch_station_id?: string; ap_station_id?: string; planning_station_id?: string; effective_station_id?: string
    station_consistency_status?: string; station_consistency_reason?: string
  description: string; pvid: unknown; vlan: unknown
  planned_management_vlan: number | null; vlan_group_id: string; vlan_group_code: string; vlan_group_name: string
  pvid_plan_status: 'matched' | 'mismatched' | 'unresolved'
  switch_rx_power: unknown; switch_tx_power: unknown
  switch_rx_low_alarm: unknown; switch_rx_high_alarm: unknown; switch_tx_low_alarm: unknown; switch_tx_high_alarm: unknown
  switch_device_optical_status?: string
  switch_optical_status: string
  switch_interface_updated_at: string; switch_optical_updated_at: string
  switch_interface_data_status: 'current' | 'stale' | 'missing' | 'unknown'
  switch_optical_data_status: 'current' | 'stale' | 'missing' | 'unknown'
  switch_optical_collection_status?: string; switch_optical_collection_error?: string
  ap_uuid: string; ap_mac: string; ap_name: string; model?: string; ap_optical_applicable?: boolean; ap_terminal_ac_id?: string; ap_terminal_ap_id?: string; ap_terminal_available?: boolean; ap_terminal_unavailable_reason?: string; ap_rx_power: unknown; ap_tx_power: unknown
  ap_device_optical_status?: string; ap_business_optical_status?: string; ap_business_threshold_dbm?: number | null; ap_business_reason?: string; ap_optical_data_freshness?: string
  ap_optical_status: string
  ap_match_source: string; ap_match_confidence: number; lldp_match_status: string
  ap_identity_entity_id?: string; identity_match_status?: string; identity_match_rule?: string; lldp_observed_neighbor_mac?: string
  recognition_status?: 'identified' | 'unidentified'; primary_reason_code?: string; primary_reason_label?: string
  lldp_history_status?: string; runtime_snapshot_status?: string; fit_ap_snapshot_collected_at?: string
    lldp_snapshot_collected_at?: string; lldp_snapshot_generation?: string
  local_rx_power_dbm: unknown; local_tx_power_dbm: unknown; remote_rx_power_dbm: unknown; remote_tx_power_dbm: unknown
  forward_loss_db: unknown; reverse_loss_db: unknown; calculation_status: string; calculation_reason: string
  local_sample_time: string; remote_sample_time: string; sample_time_delta_seconds: number | null; updated_at: string
  optical_severity: string
}

export interface TracksideApBusinessPage {
  items: TracksideApBusinessRow[]; total: number; page: number; page_size: number; site_id: string
  station_options: string[]
  device_count: number; candidate_interface_count: number; optical_abnormal_count: number
  configured_ap_port_total?: number; planned_ap_total?: number; identified_ap_port_total?: number
  unidentified_ap_port_total?: number; physical_ap_total?: number
  unidentified_reason_counts?: Record<string, number>
  fit_ap_resource_count: number; fit_ap_resource_total_count?: number; fit_ap_matched_count?: number
  fit_ap_matched_online_count?: number; fit_ap_online_total_count?: number
  fit_ap_offline_total_count?: number; fit_ap_unknown_total_count?: number
  fit_ap_unmatched_online_count?: number; business_row_count?: number
  fit_ap_lldp_snapshot_stale_count?: number; fit_ap_lldp_exact_match_pending_count?: number
  fit_ap_current_conflict_count?: number; fit_ap_planning_missing_count?: number
  fit_ap_ambiguous_online_count?: number; fit_ap_station_master_missing_count?: number
  fit_ap_unknown_association_count?: number
  fit_ap_switch_not_found_count?: number; fit_ap_switch_identity_ambiguous_count?: number
  fit_ap_switch_data_incomplete_count?: number; fit_ap_plan_not_found_count?: number
  fit_ap_plan_station_missing_count?: number; fit_ap_plan_station_invalid_count?: number
  runtime_snapshot?: Record<string, unknown>
  query_ms: number; build_ms: number; empty_reason: string
  identity_shadow: Record<string, unknown>
  scope_description?: string; scope_station_count?: number; scope_device_count?: number
  scope_ap_reference_count?: number; excluded_device_count?: number; excluded_items?: TracksideApScopeExcluded[]
  unmatched_online_items?: TracksideApUnmatchedOnline[]
  partial_data?: boolean
  source_statuses?: Record<string, 'loaded' | 'partial' | 'failed'>
  unavailable_sources?: TracksideApDataSourceIssue[]
  snapshot_id?: string; business_revision?: string; source_revisions?: Record<string, string>
  identity_revision?: number; created_at?: string; content_sha256?: string
  row_count?: number; abnormal_count?: number; unresolved_count?: number; ambiguous_count?: number
  snapshot_retry_count?: number; identity_distinct_count?: number
}

export interface TracksideApDataSourceIssue {
  source: string; label: string; code: string; message: string; device_id?: string
}

export interface TracksideApUpdateRequest {
  station?: string; ap_uuid?: string; ap_mac?: string; ap_name?: string; concurrency?: number
}

export interface TracksideApBusinessExportProposal {
  site_id: string; site_display_name: string; generated_at: string; suggested_name: string
}
export interface TracksideApBusinessExportRequest {
  generated_at: string; suggested_name: string; expected_revision: string
  station?: string; query?: string; selected_row_ids?: string[]
}
export type TracksideApTask = RailTransitTask

export type TracksideSwitchCapabilityStatus =
  | 'DOCUMENTED'
  | 'IMPLEMENTED'
  | 'SAMPLE_REQUIRED'
  | 'VERIFIED'
  | 'UNSUPPORTED'

export interface TracksideSwitchCommandProfile {
  profile_id: string; vendor: string; platform: string; product_family: string; reference_version: string
  privilege_required: boolean; enable_command: string; enable_level: number; enable_secret_configured: boolean
  device_version: string[]; interface_brief: string[]; interface_detail: string[]
  optical_brief: string[]; optical_detail: string[]
  lldp_global_candidates: string[]; lldp_interface_candidates: string[]; lldp_config_candidates: string[]
}

export interface TracksideSwitchCapability {
  key: string; label: string; status: TracksideSwitchCapabilityStatus; message: string
}

export interface TracksideSwitchAdapter {
  vendor: string; vendor_label: string; platform: string; product_family: string
  adaptation_status: string; verification_status: string
  profile: TracksideSwitchCommandProfile
  capabilities: TracksideSwitchCapability[]
  pending_items: string[]
}

export interface TracksideSwitchDevice {
  device_uuid: string; device_name: string; station: string; primary_address: string
  adapter: TracksideSwitchAdapter
}

export interface TracksideSwitchAdapterCatalog {
  items: TracksideSwitchDevice[]
  total: number
}

export interface TracksideSwitchSampleRequest {
  device_uuid: string
  vendor: string
  command_profile: string
  selected_interface: string
  requested_commands: string[]
}

export interface TracksideApPlanRow {
  station_id: string; sequence_no: number; planning_order?: number | null; display_order?: number | null; station_name: string; planned_ap_count: number
  management_vlan: number | null; remark: string
  relation_status?: 'resolved' | 'missing' | 'ambiguous' | 'stale'
  candidate_station_ids?: string[]
}

export interface TracksideApOnlineStatusRow {
  station_id: string; station_name: string; planned_ap_count: number
  actual_online_count: number; offline_count: number; online_rate: number | null
  optical_problem_count?: number
  remark: string; planning_missing?: boolean; count_anomaly: boolean
  status?: 'normal' | 'planning_missing' | 'unplanned_online' | 'over_planned'
  warning: string
}

export interface TracksideApUnassigned {
  ap_id: string; ap_name: string; point_code: string; mac: string; station_name: string
}

export interface TracksideApScopeExcluded {
  source: string; item_id: string; device_name: string; station_name: string
  operation_status: string; project_phase: string; reason: string; mac: string
}

export interface TracksideApUnmatchedOnline {
  source: string; item_id: string; ap_name: string; mac: string; ac_status: string
  runtime_station_text: string; reason: string; suggested_action: string
  association_status?: string; reason_code?: string; fit_ap_collected_at?: string
  observed_association_status?: string; observed_switch_device_id?: string
  observed_switch_device_name?: string; observed_port?: string; observed_match_method?: string
  planning_status?: string; planned_switch_device_id?: string
  planned_switch_device_name?: string; planned_port?: string
  lldp_collected_at?: string; lldp_candidate_count?: number
  ap_mac_raw?: string; ap_mac_normalized?: string; planning_record_id?: string
  planning_station_name?: string; plan_station_id?: string; planning_match_method?: string
  lldp_exists?: boolean; lldp_local_interface?: string; lldp_remote_device_name?: string
  lldp_system_name?: string; lldp_management_ip?: string; lldp_chassis_id?: string
  switch_candidate_count?: number; matched_switch_device_id?: string
  switch_match_method?: string; failure_stage?: string; source_revisions?: Record<string, string>
  snapshot_revision?: string; snapshot_created_at?: string
}

export interface TracksideApOnlineStatus {
  items: TracksideApOnlineStatusRow[]
  planned_ap_count: number; actual_online_count: number; offline_count: number
  online_rate: number | null
  optical_problem_count?: number
  unassigned_count: number; unassigned_items: TracksideApUnassigned[]
  updated_at: string; warning: string; count_anomaly?: boolean; status?: 'normal' | 'anomaly'
  scope_description?: string; scope_station_count?: number; scope_device_count?: number
  scope_ap_reference_count?: number; excluded_device_count?: number; excluded_items?: TracksideApScopeExcluded[]
  fit_ap_resource_total_count?: number; fit_ap_matched_count?: number; fit_ap_unmatched_online_count?: number
  fit_ap_matched_online_count?: number; fit_ap_online_total_count?: number
  fit_ap_offline_total_count?: number; fit_ap_unknown_total_count?: number
  fit_ap_unresolved_online_count?: number
  unmatched_online_items?: TracksideApUnmatchedOnline[]
  generated_at?: string; revision?: string; source_revision?: Record<string, unknown>; cache_hit?: boolean
  snapshot_status?: string; snapshot_age_seconds?: number | null; snapshot_warnings?: string[]
  fit_ap_collected_at?: string; switch_lldp_collected_at?: string
  fit_ap_ambiguous_online_count?: number; fit_ap_station_master_missing_count?: number
  fit_ap_unknown_association_count?: number
  fit_ap_switch_not_found_count?: number; fit_ap_switch_identity_ambiguous_count?: number
  fit_ap_switch_data_incomplete_count?: number; fit_ap_plan_not_found_count?: number
  fit_ap_plan_station_missing_count?: number; fit_ap_plan_station_invalid_count?: number
}

export interface TracksideApScopeExcludedPage {
  items: TracksideApScopeExcluded[]; total: number; page: number; page_size: number; revision: string
}

export interface TracksideApUnmatchedOnlinePage {
  items: TracksideApUnmatchedOnline[]; total: number; page: number; page_size: number; revision: string
}

export type ApManagementVlanPlanningMode = 'line_single' | 'station_independent' | 'station_grouped'
export interface ApManagementVlanPlanning {
  line_id: string; planning_mode: ApManagementVlanPlanningMode; auto_group_station_count: number
  address_allocation_strategy: string; revision: number; created_at?: string; updated_at: string
}
export interface ApManagementVlanGroupMember {
  station_id: string; station_name: string; station_sequence: number; ap_count: number
}
export interface ApManagementVlanIssue {
  code: string; severity: 'error' | 'warning' | 'info'; message: string; blocking: boolean
  field_name: string; group_id: string; station_id: string; ap_id: string
}
export interface ApManagementVlanGroup {
  group_id: string; line_id: string; group_code: string; group_name: string; sequence: number
  management_vlan: number | null; legacy_management_vlans: string; network_address: string
  prefix_length: number | null; subnet_mask: string; default_gateway: string; ap_start_ip: string
  ap_end_ip: string; address_allocation_strategy: string; notes: string; created_at: string; updated_at: string
  members: ApManagementVlanGroupMember[]; start_station_name: string; end_station_name: string
  station_count: number; ap_count: number; address_capacity: number; used_address_count: number
  validation_status: 'valid' | 'warning' | 'error'; issues: ApManagementVlanIssue[]
}
export interface ApManagementVlanAssignment {
  assignment_id: string; assignment_type: 'section_default' | 'interval_default' | 'ap_override'
  target_id: string; group_id: string; source: string; updated_at: string
}
export interface ApManagementVlanAllocation {
  ap_id: string; ap_name: string; point_code: string; station_id: string; station_name: string
  section_name: string; group_id: string; planned_ip: string; allocation_order: number
  is_manual: boolean; is_locked: boolean; source: string; group_source: string; updated_at: string
}
export interface ApManagementVlanStationDetail {
  station_id: string; station_name: string; station_sequence: number; ap_count: number
  group_id: string; group_code: string; group_name: string; ap_start_ip: string; ap_end_ip: string
  management_vlan: number | null; network_address: string; prefix_length: number | null
  subnet_mask: string; default_gateway: string; source: string; notes: string
}
export interface TracksideApPlanDraft {
  planning: ApManagementVlanPlanning
  groups: ApManagementVlanGroup[]
  assignments: ApManagementVlanAssignment[]
  allocations: ApManagementVlanAllocation[]
}
export interface ApManagementVlanImpact {
  old_group_count: number; new_group_count: number; affected_station_count: number; affected_ap_count: number
  vlan_change_count: number; ip_change_count: number; gateway_change_count: number
  manual_address_override_count: number; conflict_count: number; warning_count: number
  issues: ApManagementVlanIssue[]
}
export interface TracksideApPlan extends TracksideApPlanDraft {
  items: TracksideApPlanRow[]; total: number; station_details: ApManagementVlanStationDetail[]
  issues: ApManagementVlanIssue[]; valid: boolean; unassigned_station_count: number
}
export interface ApManagementVlanPreview { plan: TracksideApPlan; impact: ApManagementVlanImpact }
export interface TracksideApPlanPreviewRow {
  row_number: number; status: 'valid' | 'duplicate' | 'error'; key: string; message: string
  row: Record<string, unknown> | null
}
export interface TracksideApPlanPreview {
  file_name: string; file_sha256: string; duplicate_strategy: 'replace' | 'skip' | 'error'
  can_apply: boolean; total_count: number; valid_count: number; duplicate_count: number; error_count: number
  rows: TracksideApPlanPreviewRow[]; result_rows: TracksideApPlanRow[]; result_plan: TracksideApPlan | null
  legacy_schema: boolean; message: string
}

export type WpsTracksideTargetCode = 'wps_standard_spreadsheet'

export interface WpsRuntimeCapabilityNotice {
  capability?: string
  message?: string
}

export interface WpsTracksideDiagnostic {
  executed_at?: string
  status?: string
  script_version?: string
  deployment_id?: string
  script_id?: string
  document_id?: string
  operation?: string
  message?: string
  phase?: string
  http_status?: number
  remote_error_code?: string
  remote_message?: string
  suggestion?: string
  target_code?: string
  runtime_capability?: string
  core_verified?: boolean
  full_replace_ready?: boolean
  prepend_snapshot_ready?: boolean
  capabilities?: Record<string, boolean>
  core_capabilities?: Record<string, boolean>
  optional_capabilities?: Record<string, boolean>
  capability_failures?: WpsRuntimeCapabilityNotice[]
  warnings?: WpsRuntimeCapabilityNotice[]
  sheet_tab_color_verified?: boolean
  expected_tab_color?: string
  actual_tab_color?: string | number
  column_width_verified?: boolean
  expected_column_widths?: Record<string, number>
  actual_column_widths?: Record<string, number | null>
  probe_sheet_visible?: boolean
  probe_sheet?: string
  binding_status?: string
  local_binding_id?: string
  remote_binding_id?: string
  binding_id_match?: boolean
  remote_document_id?: string
  remote_site_id?: string
  remote_site_name?: string
  remote_business_key?: string
  remote_target_code?: string
  remote_target_type?: string
  document_match?: boolean
  document_identity_match?: boolean
  site_match?: boolean
  site_identity_match?: boolean
  business_match?: boolean
  business_identity_match?: boolean
  target_code_match?: boolean
  target_type_match?: boolean
  target_match?: boolean
}

export interface WpsTracksideTarget {
  target_id: string
  site_id: string
  business_key: string
  target_code: WpsTracksideTargetCode
  target_type: 'WPS_STANDARD_SPREADSHEET'
  target_name: string
  document_open_url: string
  webhook_url: string
  expected_document_id: string
  expected_script_version?: string
  expected_deployment_id?: string
  expected_script_id?: string
  runtime_capability?: string
  last_runtime_probe_at?: string
  runtime_probe_document_id?: string
  runtime_probe_script_id?: string
  runtime_probe_script_version?: string
  runtime_probe_deployment_id?: string
  binding_status?: string
  binding_id?: string
  remote_binding_id?: string
  remote_site_id?: string
  remote_site_name?: string
  remote_business_key?: string
  connection_diagnostic?: WpsTracksideDiagnostic
  runtime_probe_diagnostic?: WpsTracksideDiagnostic
  sync_test_diagnostic?: WpsTracksideDiagnostic
  sheet_tab_color_probe_diagnostic?: WpsTracksideDiagnostic
  column_width_probe_diagnostic?: WpsTracksideDiagnostic
  remote_script_version?: string
  remote_deployment_id?: string
  remote_script_id?: string
  remote_identity_verified_at?: string
  enabled: boolean
  protocol_version: number
  timeout_seconds: number
  token_configured: boolean
  token_suffix: string
  last_test_at: string
  last_test_status: string
  last_test_message: string
  last_sync_at: string
  last_sync_status: string
  last_sync_revision: string
}

export interface WpsTracksideTargetUpdate {
  token?: string
  document_open_url?: string
  webhook_url?: string
  enabled?: boolean
  timeout_seconds?: number
}

export interface WpsTracksideSyncResult {
  batch_id: string
  site_id: string
  business_key: string
  snapshot_revision: string
  snapshot_sha256: string
  snapshot_generated_at: string
  payload_bytes: number
  sheet_count: number
  target_count: number
  success_count: number
  failed_count: number
  unknown_count?: number
  warning_count: number
  partial_success: boolean
  status: 'SUCCESS' | 'SUCCESS_WITH_WARNINGS' | 'PARTIAL_SUCCESS' | 'FAILED' | 'REMOTE_RESULT_UNKNOWN'
  targets: Array<{
    target_code: WpsTracksideTargetCode
    target_name: string
    target_type: string
    target_batch_id: string
    status: 'SUCCESS' | 'SUCCESS_WITH_WARNINGS' | 'FAILED' | 'REMOTE_RESULT_UNKNOWN'
    error_code?: string
    message?: string
    remote_task_id_masked?: string
    remote_task_type?: string
    remote_task_status?: string
    remote_task_submitted_at?: string
    remote_task_last_polled_at?: string
    remote_task_finished_at?: string
    format_warning_count?: number
    sheet_count?: number
    sheet_order_verified?: boolean
    binding_status?: string
    format_warnings?: Array<{
      sheet_name: string
      feature: string
      range?: string
      reason: string
    }>
    column_width_verification_report?: {
      status?: 'SUCCESS' | 'SUCCESS_WITH_WARNINGS' | 'FAILED' | 'NOT_ENABLED'
      total_columns?: number
      local_explicit_width_count?: number
      auto_fit_requested_count?: number
      explicit_applied_count?: number
      auto_fit_applied_count?: number
      clamped_count?: number
      dto_match_count?: number
      payload_match_count?: number
      attempted_count?: number
      read_back_count?: number
      physical_read_back_count?: number
      verified_count?: number
      warning_count?: number
      failed_count?: number
      verified_ratio?: number
      stage_counts?: Record<string, number>
      largest_differences?: Array<Record<string, unknown>>
      representative_columns?: Array<Record<string, unknown>>
      items?: Array<Record<string, unknown>>
    }
    format_results?: Record<string, {
      status?: 'SUCCESS' | 'SUCCESS_WITH_WARNINGS' | 'FAILED' | 'WARN' | 'NOT_ENABLED'
      attempted_count?: number
      read_back_count?: number
      verified_count?: number
      failed_count?: number
      applied_count?: number
      expected_count?: number
      warning_count?: number
      format_run_count?: number
      duration_ms?: number
      items?: Array<Record<string, unknown>>
      examples?: Array<{
        sheet_name?: string
        range?: string
        expected?: unknown
        before?: number | null
        actual?: unknown
        verified?: boolean
      }>
    }>
    source_workbook_format_manifest?: {
      totals?: Record<string, number>
      sheets?: Array<Record<string, unknown>>
      column_widths?: Array<Record<string, unknown>>
    }
  }>
}
