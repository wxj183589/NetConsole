export type GroundRunState = 'DISABLED' | 'WAITING_WINDOW' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'STOPPING' | 'FINALIZING' | 'ARCHIVING' | 'COMPLETED' | 'ERROR'
export type GroundCoverageStatus = 'NOT_SEEN' | 'WAITING' | 'COLLECTING' | 'PARTIAL' | 'COVERED' | 'EXCLUDED' | 'OFFLINE' | 'FAILED'
export type GroundDataAvailability = 'ACTIVE_RAW' | 'ARCHIVED_RAW' | 'MIXED' | 'SUMMARY_ONLY' | 'MISSING' | 'CORRUPT'

export interface GroundProfile {
  site_id: string; enabled: boolean; schedule_start_time: string; schedule_end_time: string; timezone: string
  ac_poll_interval_seconds: number; stationary_exclusion_minutes: number; ac_stale_grace_seconds: number
  ac_ping_correlation_tolerance_seconds: number; ap_switch_before_seconds: number; ap_switch_after_seconds: number
  max_active_trains: number; max_active_mrs: number; max_starting_mrs: number; max_finalizing_mrs: number
  deep_collection_master_enabled: boolean
  deep_fping_required: true
  deep_fping: {
    enabled: true; target: ''; preset_key: string; preset_name: string
    packet_size: number; interval_ms: number; timeout_ms: number
    loss_warn_percent: number; latency_warn_ms: number
  }
  fleet_ping_interval_ms: number; fleet_ping_timeout_ms: number; fleet_ping_packet_size: number; fleet_ping_shard_size: number; fleet_ping_warmup_seconds: number
  ping_depot_trains_enabled: boolean
  udp_listen_host: string; udp_listen_port: number; udp_queue_capacity: number; raw_flush_interval_seconds: number; raw_flush_record_count: number
  event_batch_size: number; event_batch_interval_seconds: number; boot_time_tolerance_seconds: number; config_check_cooldown_seconds: number
  syslog_server_ip: string; syslog_server_port: number; ping_raw_retention_days: number; syslog_raw_retention_days: number
  allow_external_syslog_address: boolean; syslog_auto_repair_enabled: boolean
  minimum_valid_collection_minutes: number; preferred_collection_minutes: number; maximum_collection_minutes: number
  start_jitter_seconds: number; start_batch_size: number; detail_retention_days: number; summary_retention_days: number
  storage_warning_free_gb: number; storage_critical_free_gb: number; created_at: string; updated_at: string
}
export interface GroundStatus {
  site_id: string; enabled: boolean; state: GroundRunState; service_state: GroundRunState; paused: boolean; run_id: string; run_date: string
  actual_started_at: string; actual_ended_at: string; schedule_start_time: string; schedule_end_time: string; timezone: string
  running_mode: 'STANDARD' | 'LIGHTWEIGHT'
  next_start_at: string; next_end_at: string; profile_effective_at: string; ac_last_updated_at: string; ac_freshness_status: string
  mainline_train_count: number; mainline_ping_target_count: number; depot_ping_target_count: number; ping_target_count: number; active_deep_train_count: number; covered_train_count: number
  incomplete_train_count: number; disk_used_bytes: number; disk_free_bytes: number; disk_status: string
  inventory_train_count: number; syslog_active_mr_count: number; config_abnormal_count: number; data_quality_warning_count: number
  radio_down_mr_count: number; radio_bounce_today_count: number; snmp_radio_control_today_count: number
  snmp_unrecovered_count: number; radio_flapping_mr_count: number; last_snmp_radio_control_at: string
  latest_archive_status: string; latest_archive_message: string
  active_run_id: string; active_run_state: string; active_run_date: string; active_run_started_at: string
  latest_run_id: string; latest_run_state: string; latest_run_date: string; latest_run_started_at: string; latest_run_ended_at: string
  active_operation_id: string; active_operation_state: string; latest_operation_id: string; latest_operation_state: string
  message: string; updated_at: string
}
export interface GroundRun {
  run_id: string; site_id: string; run_date: string; state: GroundRunState; paused: boolean
  scheduled_start_at: string; scheduled_end_at: string; actual_started_at: string; actual_ended_at: string
  ping_sample_count: number; archive_id: string; archive_status: string; data_availability: GroundDataAvailability
  message: string; created_at: string; updated_at: string
}
export interface GroundEndpoint {
  endpoint: 'CT' | 'CW'; mr_id: string; mr_name: string; device_id: number | null; management_ip: string; online_status: string
  ping_target_eligible: boolean; ping_exclusion_reason: string
  ping_active: boolean; ping_sent_count: number; ping_success_count: number; ping_loss_rate_percent: number | null
  ping_avg_rtt_ms: number | null; active_operation_id: string; latest_session_id: string
  syslog_status: string; last_syslog_received_at: string; current_active_peer: string; last_link_switch_at: string
  boot_session_id: string; estimated_boot_time: string; uptime_seconds: number | null; boot_time_uncertainty_seconds: number
  reboot_reason: string; timezone_name: string; utc_offset_seconds: number | null; device_time_quality: string
  config_status: string; config_checked_at: string; managed_target_ip: string; managed_target_port: number | null
  managed_target_statuses: string[]; configured_log_hosts: GroundSyslogHost[]
  managed_profile_version: number; radio_interfaces: GroundRadioInterfaceState[]
  radio_overall_state: 'UP' | 'DOWN' | 'FLAPPING' | 'UNKNOWN'
  snmp_radio_control_state: 'NONE' | 'RECENT_CHANGE' | 'RADIO_DOWN' | 'RADIO_RECOVERED' | 'FREQUENT_SWITCHING'
  last_radio_event_at: string; last_cfg_event_at: string; cfg_command_source: string; cfg_event_index: string
  correlation_confidence: 'HIGH' | 'MEDIUM' | 'UNCONFIRMED'
}
export interface GroundApIdentityDiagnostics {
  train_id: string; mr_id: string; site_id: string; line_id: string
  raw_current_ap: string; canonical_current_ap: string; identity_revision: number
  identity_generated_at: string; candidate_count: number; matched_by: string
  ap_identity_status: string; station_match_status: string; ap_identity_match_status: string
  resolved_ap_id: string; resolved_ap_name: string; resolved_ap_physical_mac: string
  resolved_station_id: string; resolved_station_name: string; resolved_section_id: string; resolved_section_name: string
  position_type: string; mainline_eligible: boolean; mainline_exclusion_code: string; mainline_exclusion_reason: string
  ping_eligible: boolean; ping_exclusion_code: string; ping_exclusion_reason: string; result_code: string
}
export interface GroundRadioInterfaceState {
  interface_name: string; current_state: string; previous_state: string; last_changed_at: string; down_since: string
  last_up_at: string; last_down_at: string; latest_outage_duration_ms: number | null; transition_count_5m: number
  snmp_related_transition_count_5m: number; last_cfg_event_index: string; last_command_source: string
  correlation_confidence: string; last_event_id: number | null
}
export interface GroundMrRuntimeStatus {
  device_uuid: string; train_id: string; mr_role: string; mr_name: string; radio_interfaces: GroundRadioInterfaceState[]
  radio_overall_state: 'UP' | 'DOWN' | 'FLAPPING' | 'UNKNOWN'
  snmp_radio_control_state: 'NONE' | 'RECENT_CHANGE' | 'RADIO_DOWN' | 'RADIO_RECOVERED' | 'FREQUENT_SWITCHING'
  last_radio_event_at: string; last_cfg_event_at: string; cfg_command_source: string; cfg_event_index: string
  config_source: string; config_destination: string; correlation_confidence: 'HIGH' | 'MEDIUM' | 'UNCONFIRMED'
  managed_config_status: string; managed_config_checked_at: string; managed_profile_version: number
}
export interface GroundSyslogHost {
  ip: string; port: number; facility: string; is_managed_target: boolean; same_ip_different_port: boolean
  source: 'DEVICE_EXISTING' | 'NETCONSOLE_MANAGED'
}
export interface GroundTrain {
  train_id: string; train_no: string; train_name: string
  location_class: 'MAINLINE' | 'DEPOT' | 'PARKING_YARD' | 'STABLING' | 'DEPOT_CONNECTION' | 'TEST_TRACK' | 'NON_MAINLINE' | 'OFFLINE' | 'UNKNOWN'
  location_class_source: string; participates_in_mainline: boolean
  mainline_eligible: boolean; mainline_reason_code: string; mainline_reason_text: string
  ping_eligible: boolean; ping_reason_code: string; ping_reason_text: string
  deep_collection_eligible: boolean; deep_collection_reason_code: string; deep_collection_reason_text: string
  decision_revision: number; decision_source: string
  ping_inclusion_reason: string; ping_exclusion_reason: string; deep_exclusion_reason: string
  eligibility_status: string; exclusion_reason: string; current_ap_name: string; current_ap_mac: string
  location_match_level: 'AP_EXACT' | 'AP_REGISTRY' | 'AP_ALIAS' | 'STATION_EXACT' | 'STATION_ALIAS' | 'UNMATCHED'
  location_match_reason: string; resolved_ap_id: string; resolved_ap_name: string; raw_peer_ap_name: string; raw_peer_ap_mac: string; canonical_station_name: string
  station: string; section: string; mileage: string; rssi: number | null; same_ap_duration_seconds: number
  ac_snapshot_id: number | null; ac_received_at: string; coverage_status: GroundCoverageStatus; priority: boolean
  enabled: boolean; scheduling_priority: number; deep_collection_enabled: boolean; monitor_only: boolean; remark: string; inventory_status: string
  attempt_count: number; covered_rounds: number; selection_reason: string; failure_reason: string; endpoints: GroundEndpoint[]
  ap_identity_diagnostics?: GroundApIdentityDiagnostics; updated_at: string
}
export interface GroundPingTarget {
  run_id: string; run_date: string; target_ip: string; train_id: string; train_no: string; mr_id: string; mr_name: string; mr_position_code: string; started_at: string; updated_at: string
  location_class: GroundTrain['location_class']; ping_inclusion_reason: string; mainline_eligible: boolean; deep_collection_eligible: boolean
  shard_id: string; raw_sample_count: number; effective_sample_count: number; warmup_ignored_count: number
  sent_count: number; success_count: number; loss_count: number; loss_rate_percent: number
  min_rtt_ms: number | null; avg_rtt_ms: number | null; max_rtt_ms: number | null
  continuous_loss_max_count: number; continuous_loss_max_seconds: number; current_ap_name: string; station: string; section: string
  first_sample_at: string; last_sample_at: string; active_raw_file_count: number; archived_raw_file_count: number
  raw_file_count: number; raw_record_count: number; raw_file_ids: string[]
  raw_file_available: boolean; archive_available: boolean; archive_id: string
  data_source: 'ACTIVE' | 'ARCHIVE' | 'MIXED' | 'NONE'; source_kind: 'ACTIVE' | 'ARCHIVE' | 'MIXED' | 'NONE'
  data_availability: GroundDataAvailability; availability_reason: string; query_identity: string
}
export interface GroundDeepCollection {
  train_id: string; train_no: string; status: GroundCoverageStatus; queue_position: number | null; scheduling_priority: number
  selection_reason: string; started_at: string; valid_duration_minutes: number; ct_operation_id: string; cw_operation_id: string
  ct_session_id: string; cw_session_id: string; attempt_count: number; covered_rounds: number; failure_reason: string; updated_at: string
  deep_state: GroundDeepCollectionState; deep_state_reason: string; collectors: GroundDeepCollector[]
}
export type GroundDeepCollectionState = 'INELIGIBLE' | 'ELIGIBLE' | 'QUEUED' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'STOPPING' | 'STOPPED' | 'FAILED'
export interface GroundDeepCollector {
  run_id: string; train_id: string; mr_id: string; mr_role: string; management_ip: string; operation_id: string; collector_session_id: string
  state: GroundDeepCollectionState; state_reason: string; started_at: string; last_record_at: string; record_count: number | null; bytes_written: number
  current_ap: string; station: string; section: string; last_error: string; retry_count: number
  fping_status: string; fping_target_ip: string; fping_started_at: string; fping_last_data_at: string
  fping_sample_count: number; fping_interval_ms: number; fping_timeout_ms: number; fping_packet_size: number
  fping_loss_percent: number | null; fping_avg_latency_ms: number | null; fping_latest_latency_ms: number | null
  fping_error: string; data_integrity_status: 'UNKNOWN' | 'COMPLETE' | 'INCOMPLETE'
}
export interface GroundDeepCollectionRecord {
  sequence: number; timestamp: string; category: string; source: string; text: string
}
export interface GroundDeepCollectionRecordPage {
  collector: GroundDeepCollector; records: GroundDeepCollectionRecord[]; next_cursor: string; has_more: boolean
}
export interface GroundTimelineEvent {
  event_id: number | string; ts: string; event_type: string; severity: string; train_id: string; train_no: string; train_name: string; mr_id: string
  mr_name: string; mr_position_code: string
  title: string; message: string; peer_ap_id: string; peer_ap_name: string; peer_ap_mac: string
  peer_radio_mac: string; previous_peer_ap_id: string; previous_peer_ap_name: string; previous_peer_ap_mac: string
  previous_peer_radio_mac: string; station: string; section: string; previous_station: string; previous_section: string
  rssi: number | null; previous_rssi: number | null; reason_code: string; reason_label: string; resolution_status: string
  ap_display: string; ap_transition_display: string; resolved_ap_name: string; previous_resolved_ap_name: string
  old_ap_raw: string; new_ap_raw: string; old_ap_identity_status: string; new_ap_identity_status: string
  old_match_source: string; new_match_source: string; old_match_rule: string; new_match_rule: string
  old_identity_reason: string; new_identity_reason: string; identity_status: string; identity_source: string; identity_revision: number
  details: Record<string, unknown>
}
export interface GroundArchive {
  archive_id: string; site_id: string; run_id: string; run_date: string; actual_started_at: string; actual_ended_at: string
  mainline_train_count: number; ping_target_count: number; ping_sample_count: number; covered_train_count: number
  complete_session_count: number; partial_session_count: number; archive_size_bytes: number; sha256: string; manifest_sha256: string
  archive_status: string; file_count: number; integrity_status: string
  retention_until: string; summary: Record<string, unknown>; message: string; created_at: string; updated_at: string
}
export interface GroundArchiveFile {
  path: string; data_type: string; train_id: string; mr_id: string; mr_role: string; hour: string; record_count: number
  size_bytes: number; compressed_size_bytes: number; sha256: string; parse_status: string
}
export interface GroundArchiveDetail {
  archive: GroundArchive
  files: GroundArchiveFile[]
  validation: {
    status: 'READY' | 'FAILED' | 'NOT_CHECKED'; checked_at: string; archive_size_bytes: number
    archive_sha256: string; manifest_sha256: string; file_count: number; legacy_manifest: boolean; message: string
  }
}
export interface GroundActionResponse { accepted: boolean; state: GroundRunState; run_id: string; operation_id: string; message: string }
export interface GroundOperation {
  operation_id: string; site_id: string; run_id: string; operation_type: 'STOP' | 'STOP_AND_ARCHIVE'
  operation_state: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'; operation_stage: string; progress_percent: number
  message: string; started_at: string; updated_at: string; completed_at: string; failure_code: string; failure_reason: string
  stop_trigger: 'USER_NORMAL_STOP' | 'USER_STOP_AND_ARCHIVE' | 'SCHEDULE_END' | 'PROFILE_DISABLED' | 'BACKEND_SHUTDOWN' | 'SITE_SWITCH' | 'RECOVERY' | 'FATAL_ERROR' | 'UNKNOWN'
  stop_reason: string; requested_by: string; request_id: string; previous_state: string; next_state: string; triggered_at: string
  result_summary: Record<string, unknown>
}
export interface GroundPingSample {
  sample_id: string; ts: string; target_ip: string; train_id: string; train_no: string; mr_id: string; mr_name: string
  mr_position_code: string; seq: number | null; ok: boolean; rtt_ms: number | null; timeout_ms: number | null; packet_size: number | null
  current_ap_identity: string; current_ap_name: string; current_ap_mac: string; station: string; section: string; mileage: string
  rssi: number | null; ac_snapshot_id: number | null; ac_received_at: string; position_quality: string
  ap_transition_context: string; warmup_ignored: boolean; target_activation_started_at: string
  archive_entry: string; data_source: 'ACTIVE' | 'ARCHIVE'
}
export interface GroundApTransition {
  event_id: string; run_id: string
  ts: string; event_time: string; event_type: string; context: string
  train_id: string; mr_id: string; mr_role: string; management_ip: string
  old_ap_raw: string; new_ap_raw: string; old_ap_radio_mac: string; new_ap_radio_mac: string
  old_ap_id: string; new_ap_id: string; old_ap_name: string; new_ap_name: string
  old_ap_mac: string; new_ap_mac: string; old_station: string; new_station: string
  old_section: string; new_section: string; old_ap_identity_status: string; new_ap_identity_status: string
  old_match_source: string; new_match_source: string; old_match_rule: string; new_match_rule: string
  old_identity_reason: string; new_identity_reason: string; identity_status: string; identity_source: string; identity_revision: number
  rssi_before: number | null; rssi_before_time: string; rssi_before_delta_ms: number | null; rssi_before_reason: string
  rssi_after: number | null; rssi_after_time: string; rssi_after_delta_ms: number | null; rssi_after_reason: string
  source: string; source_type: string; source_event_id: number | string | null; syslog_event_id: number | string | null; raw_file_id: string; raw_line_number: number | null; source_sequence: number | null
  details: Record<string, unknown>
}
export interface GroundQueryDiagnostics {
  request_id: string; requested_run_id: string; resolved_start_time: string; resolved_end_time: string
  source_kind: 'ACTIVE' | 'ARCHIVE' | 'MIXED' | 'NONE'; data_availability: GroundDataAvailability
  files_considered: number; files_scanned: number; registered_record_count?: number; records_scanned: number; bytes_scanned: number
  malformed_record_count: number; duplicate_record_count: number; truncated: boolean; optimized_latest_page?: boolean; legacy_archive: boolean; no_data_reason: string
  resolved_train_ids: string[]; resolved_mr_ids: string[]; raw_file_registry_hit_count: number; matched_count: number
  segment_count?: number; active_segment?: string; last_persisted_sample_at?: string; last_query_sample_at?: string
}
export interface GroundPingSeries {
  raw_sample_count: number; effective_sample_count: number; ignored_sample_count: number
  success_count: number; loss_count: number; rtt_sample_count: number; rtt_sum_ms: number
  current_rtt_ms: number | null; average_rtt_ms: number | null; max_rtt_ms: number | null
  points: GroundPingSample[]
  loss_windows: Array<Record<string, unknown>>; ap_transitions: GroundApTransition[]; position_segments: Array<Record<string, unknown>>
  diagnostics: GroundQueryDiagnostics
  next_cursor: string; latest_sequence: number | null; latest_timestamp: string; server_time: string
  active: boolean; target_state: string; has_more: boolean; query_identity: string
}
export interface GroundSyslogRecord {
  receive_time: string; device_time: string; source_ip: string; source_port: number | null; hostname: string; system_name: string
  facility: string; severity: string; train_id: string; train_no: string; device_uuid: string; mr_name: string; mr_role: string
  identity_status: string; parse_status: string; data_quality: string; clock_offset_ms: number | null; raw_text: string
  global_receive_sequence: number | null; source_receive_sequence: number | null; raw_file_id: string; raw_file_status: string
  raw_line_number: number | null; archive_entry: string; data_source: 'ACTIVE' | 'ARCHIVE'; display_enriched: boolean
  event_type: string; event_family: string; interface_name: string; interface_type: string; physical_state: string
  cfg_event_index: string; cfg_command_source: string; cfg_source: string; cfg_destination: string; expected_internal_change: boolean
  correlation_status: string; correlation_confidence: string; correlation_delta_ms: number | null
  correlated_event_ids: number[]; composite_event_type: string
  peer_ap_id: string; peer_name: string; peer_mac: string; peer_radio_mac: string
  previous_peer_ap_id: string; previous_peer_name: string; previous_peer_mac: string; previous_peer_radio_mac: string
  station: string; section: string; previous_station: string; previous_section: string; rssi: number | null
  previous_rssi: number | null; reason_code: string; reason_text: string; resolution_status: string
  parsed_details: Record<string, unknown>
}
export interface GroundSyslogRecordKey {
  raw_file_id: string
  global_receive_sequence?: number | null
  source_receive_sequence?: number | null
  raw_line_number?: number | null
}
export interface GroundSyslogDeleteFilters {
  train_id?: string; mr_id?: string; mr_name?: string; mr_role?: string; source_ip?: string
  system_name?: string; facility?: string; severity?: string; identity_status?: string
  event_type?: string; event_family?: string; cfg_command_source?: string; physical_state?: string
  correlation_status?: string; correlation_confidence?: string
  peer_name?: string; data_source?: string; keyword?: string
  start_time?: string; end_time?: string
}
export interface GroundSyslogDeletePreviewRequest {
  run_id: string
  mode: 'SELECTED' | 'FILTERED' | 'RUN_ALL'
  record_keys?: GroundSyslogRecordKey[]
  filters?: GroundSyslogDeleteFilters
  include_derived_events: boolean
}
export interface GroundSyslogDeletePreview {
  run_id: string; run_date: string; mode: 'SELECTED' | 'FILTERED' | 'RUN_ALL'
  matched_record_count: number; affected_file_count: number; affected_event_count: number
  affected_timeline_count: number; total_bytes: number; file_statuses: Array<Record<string, unknown>>
  archive_status: string; blocked_reasons: string[]; warnings: string[]
  preview_token: string; expires_at: string; confirmation_hint: string
}
export interface GroundSyslogDeleteAccepted {
  accepted: boolean; operation_id: string; task_id: string; run_id: string; status: string; message: string
}
export interface GroundPagedResult<T> extends GroundPage<T> { total_exact?: boolean; page: number; page_size: number; diagnostics?: GroundQueryDiagnostics }
export interface GroundPage<T> { items: T[]; total: number }
export interface GroundInventorySummary {
  site_id: string; discovered_train_count: number; complete_train_count: number; ct_only_count: number; cw_only_count: number
  missing_management_ip_count: number; missing_credential_count: number; added_endpoint_count: number; updated_endpoint_count: number; removed_endpoint_count: number; removed_train_count: number; synchronized_at: string
}
export interface GroundTrainPolicy { enabled: boolean; priority: boolean; scheduling_priority: number; deep_collection_enabled: boolean; monitor_only: boolean; remark: string }
export interface GroundAcPollerHealth {
  controller_id: string; controller_name: string; task_id: string; run_id: string; status: string; connection_state: string
  last_success_at: string; latest_snapshot_id: number | null; next_poll_at: string; poll_interval_seconds: number
  poll_count: number; success_count: number; failure_count: number; reconnect_count: number; consecutive_failures: number
  heartbeat_at: string; heartbeat_age_seconds: number | null; last_error: string
}
export interface GroundHealth {
  site_id: string; status: string; udp_running: boolean; udp_listen_address: string; udp_receive_rate_per_second: number; udp_received_count: number
  udp_unidentified_count: number; udp_identity_conflict_count: number; udp_last_received_at: string
  udp_queue_length: number; udp_queue_capacity: number; udp_dropped_count: number; raw_records_written: number; raw_bytes_written: number
  raw_last_write_duration_ms: number; database_pending_count: number; database_last_batch_duration_ms: number; open_file_count: number
  ping_target_count: number; ping_process_count: number; deep_queue_length: number; archive_pending_count: number; ac_pollers: GroundAcPollerHealth[]
  disk_free_bytes: number; last_error: string; updated_at: string
  receiver_alive: boolean; writer_alive: boolean; parser_alive: boolean
  received: number; written: number; parsed: number; db_saved: number; dropped: number
  memory_queue_size: number; memory_queue_capacity: number; disk_queue_count: number
  parser_queue_size: number; parser_queue_capacity: number; raw_file: string
  raw_file_size: number; last_write_time: string
  spool_bytes: number; spool_files: number; disk_usage_percent: number
  spool_guard_state: string; spool_warning_percent: number; spool_critical_percent: number; spool_emergency_percent: number
}
export interface GroundRawFile { file_id: string; site_id: string; run_id: string; train_id: string; device_id: number | null; mr_role: string; data_type: string; relative_path: string; start_time: string; end_time: string; record_count: number; size_bytes: number; sha256: string; status: string; archive_status: string; parse_status: string; compressed_path: string; created_at: string; updated_at: string }

export interface LocalIpv4Address {
  adapter_id: string; adapter_name: string; description: string; interface_index: number; ipv4: string
  prefix_length: number; netmask: string; gateway: string; is_up: boolean; is_loopback: boolean; is_virtual: boolean
  is_apipa: boolean; has_default_route: boolean; route_metric: number | null; source: string
  recommended: boolean; recommendation_reason: string
}
export interface SourceIpRoute { target_ip: string; source_ip: string; reachable: boolean; reason: string }
export interface SourceIpRecommendation {
  recommended_ip: string; recommendation_reason: string; routes: SourceIpRoute[]
  candidates: LocalIpv4Address[]; generated_at: string
}
export interface UdpPortCheck {
  listen_host: string; listen_port: number; available: boolean; status: string; message: string; checked_at: string
}
export interface GroundSyslogTransportStatus {
  configured_return_ip: string; configured_return_port: number
  return_address_status: 'LOCAL_ADDRESS' | 'EXTERNAL_CONFIRMED' | 'NOT_LOCAL' | 'EMPTY' | 'INVALID'
  return_address_is_local: boolean; allow_external_address: boolean
  listen_host: string; listen_port: number; receiver_running: boolean
  receiver_state: 'LISTENING' | 'STOPPED' | 'STARTING' | 'ERROR'
  actual_listen_address: string
  port_state: 'NETCONSOLE_LISTENING' | 'AVAILABLE' | 'OCCUPIED_BY_OTHER' | 'ADDRESS_NOT_LOCAL' | 'NOT_CHECKED' | 'UNKNOWN'
  port_message: string; ports_match: boolean | null; target_port_message: string
  last_received_at: string; received_count: number; active_mr_count: number
  unidentified_count: number; identity_conflict_count: number
  queue_length: number; queue_capacity: number; dropped_count: number
  recommended_local_ip: string; recommended_adapter_name: string; checked_at: string
}
