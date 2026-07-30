import type { RailTransitTask } from './railTransitWeb'

export interface TracksideApBusinessRow {
  station_id?: string; site: string; device_name: string; switch_vendor: string; interface_name: string; link_status: string; port_type: string
  description: string; pvid: unknown; vlan: unknown
  planned_management_vlan: number | null; vlan_group_id: string; vlan_group_code: string; vlan_group_name: string
  pvid_plan_status: 'matched' | 'mismatched' | 'unresolved'
  switch_rx_power: unknown; switch_tx_power: unknown
  switch_rx_low_alarm: unknown; switch_rx_high_alarm: unknown; switch_tx_low_alarm: unknown; switch_tx_high_alarm: unknown
  switch_optical_status: string
  ap_uuid: string; ap_mac: string; ap_name: string; ap_rx_power: unknown; ap_tx_power: unknown; ap_optical_status: string
  ap_match_source: string; ap_match_confidence: number; lldp_match_status: string
  local_rx_power_dbm: unknown; local_tx_power_dbm: unknown; remote_rx_power_dbm: unknown; remote_tx_power_dbm: unknown
  forward_loss_db: unknown; reverse_loss_db: unknown; calculation_status: string; calculation_reason: string
  local_sample_time: string; remote_sample_time: string; sample_time_delta_seconds: number | null; updated_at: string
  optical_severity: string
}

export interface TracksideApBusinessPage {
  items: TracksideApBusinessRow[]; total: number; page: number; page_size: number; site_id: string
  station_options: string[]
  device_count: number; candidate_interface_count: number; optical_abnormal_count: number
  fit_ap_resource_count: number; query_ms: number; build_ms: number; empty_reason: string
  identity_shadow: Record<string, unknown>
  scope_description?: string; scope_station_count?: number; scope_device_count?: number
  excluded_device_count?: number; excluded_items?: TracksideApScopeExcluded[]
}

export interface TracksideApUpdateRequest { station?: string; ap_uuid?: string; ap_mac?: string; ap_name?: string }
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
  station_id: string; sequence_no: number; station_name: string; planned_ap_count: number
  management_vlan: number | null; remark: string
}

export interface TracksideApOnlineStatusRow {
  station_id: string; station_name: string; planned_ap_count: number
  actual_online_count: number; offline_count: number; online_rate: number | null
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

export interface TracksideApOnlineStatus {
  items: TracksideApOnlineStatusRow[]
  planned_ap_count: number; actual_online_count: number; offline_count: number
  online_rate: number | null
  unassigned_count: number; unassigned_items: TracksideApUnassigned[]
  updated_at: string; warning: string; count_anomaly?: boolean; status?: 'normal' | 'anomaly'
  scope_description?: string; scope_station_count?: number; scope_device_count?: number
  excluded_device_count?: number; excluded_items?: TracksideApScopeExcluded[]
}

export type ApManagementVlanPlanningMode = 'line_single' | 'station_independent' | 'station_grouped'
export interface ApManagementVlanPlanning {
  line_id: string; planning_mode: ApManagementVlanPlanningMode; auto_group_station_count: number
  address_allocation_strategy: string; revision: number; updated_at: string
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
