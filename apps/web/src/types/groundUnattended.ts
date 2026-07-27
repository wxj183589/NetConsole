export type GroundRunState = 'DISABLED' | 'WAITING_WINDOW' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'STOPPING' | 'FINALIZING' | 'ARCHIVING' | 'COMPLETED' | 'ERROR'
export type GroundCoverageStatus = 'NOT_SEEN' | 'WAITING' | 'COLLECTING' | 'PARTIAL' | 'COVERED' | 'EXCLUDED' | 'OFFLINE' | 'FAILED'

export interface GroundProfile {
  site_id: string; enabled: boolean; schedule_start_time: string; schedule_end_time: string; timezone: string
  ac_poll_interval_seconds: number; stationary_exclusion_minutes: number; ac_stale_grace_seconds: number
  ac_ping_correlation_tolerance_seconds: number; ap_switch_before_seconds: number; ap_switch_after_seconds: number
  max_active_trains: number; max_active_mrs: number; max_starting_mrs: number; max_finalizing_mrs: number
  fleet_ping_interval_ms: number; fleet_ping_timeout_ms: number; fleet_ping_packet_size: number; fleet_ping_shard_size: number
  udp_listen_host: string; udp_listen_port: number; udp_queue_capacity: number; raw_flush_interval_seconds: number; raw_flush_record_count: number
  event_batch_size: number; event_batch_interval_seconds: number; boot_time_tolerance_seconds: number; config_check_cooldown_seconds: number
  syslog_server_ip: string; syslog_server_port: number; ping_raw_retention_days: number; syslog_raw_retention_days: number
  allow_external_syslog_address: boolean
  minimum_valid_collection_minutes: number; preferred_collection_minutes: number; maximum_collection_minutes: number
  start_jitter_seconds: number; start_batch_size: number; detail_retention_days: number; summary_retention_days: number
  storage_warning_free_gb: number; storage_critical_free_gb: number; created_at: string; updated_at: string
}
export interface GroundStatus {
  site_id: string; enabled: boolean; state: GroundRunState; paused: boolean; run_id: string; run_date: string
  actual_started_at: string; actual_ended_at: string; schedule_start_time: string; schedule_end_time: string; timezone: string
  next_start_at: string; next_end_at: string; profile_effective_at: string; ac_last_updated_at: string; ac_freshness_status: string
  mainline_train_count: number; ping_target_count: number; active_deep_train_count: number; covered_train_count: number
  incomplete_train_count: number; disk_used_bytes: number; disk_free_bytes: number; disk_status: string
  inventory_train_count: number; syslog_active_mr_count: number; config_abnormal_count: number; data_quality_warning_count: number
  latest_archive_status: string; latest_archive_message: string; message: string; updated_at: string
}
export interface GroundEndpoint {
  endpoint: 'CT' | 'CW'; mr_id: string; mr_name: string; device_id: number | null; management_ip: string; online_status: string
  ping_active: boolean; ping_sent_count: number; ping_success_count: number; ping_loss_rate_percent: number | null
  ping_avg_rtt_ms: number | null; active_operation_id: string; latest_session_id: string
  syslog_status: string; last_syslog_received_at: string; current_active_peer: string; last_link_switch_at: string
  boot_session_id: string; estimated_boot_time: string; uptime_seconds: number | null; boot_time_uncertainty_seconds: number
  reboot_reason: string; timezone_name: string; utc_offset_seconds: number | null; device_time_quality: string
  config_status: string; config_checked_at: string; managed_target_ip: string; managed_target_port: number | null
  managed_target_statuses: string[]; configured_log_hosts: GroundSyslogHost[]
}
export interface GroundSyslogHost {
  ip: string; port: number; facility: string; is_managed_target: boolean; same_ip_different_port: boolean
  source: 'DEVICE_EXISTING' | 'NETCONSOLE_MANAGED'
}
export interface GroundTrain {
  train_id: string; train_no: string; train_name: string; ping_eligible: boolean; deep_collection_eligible: boolean
  eligibility_status: string; exclusion_reason: string; current_ap_name: string; current_ap_mac: string
  location_match_level: 'AP_EXACT' | 'AP_REGISTRY' | 'AP_ALIAS' | 'STATION_EXACT' | 'STATION_ALIAS' | 'UNMATCHED'
  location_match_reason: string; resolved_ap_id: string; resolved_ap_name: string; raw_peer_ap_name: string; raw_peer_ap_mac: string; canonical_station_name: string
  station: string; section: string; mileage: string; rssi: number | null; same_ap_duration_seconds: number
  ac_snapshot_id: number | null; ac_received_at: string; coverage_status: GroundCoverageStatus; priority: boolean
  enabled: boolean; scheduling_priority: number; deep_collection_enabled: boolean; monitor_only: boolean; remark: string; inventory_status: string
  attempt_count: number; covered_rounds: number; selection_reason: string; failure_reason: string; endpoints: GroundEndpoint[]; updated_at: string
}
export interface GroundPingTarget {
  target_ip: string; train_id: string; train_no: string; mr_id: string; mr_position_code: string; started_at: string; updated_at: string
  shard_id: string; sent_count: number; success_count: number; loss_count: number; loss_rate_percent: number
  min_rtt_ms: number | null; avg_rtt_ms: number | null; max_rtt_ms: number | null
  continuous_loss_max_count: number; continuous_loss_max_seconds: number; current_ap_name: string; station: string; section: string
}
export interface GroundDeepCollection {
  train_id: string; train_no: string; status: GroundCoverageStatus; queue_position: number | null; scheduling_priority: number
  selection_reason: string; started_at: string; valid_duration_minutes: number; ct_operation_id: string; cw_operation_id: string
  ct_session_id: string; cw_session_id: string; attempt_count: number; covered_rounds: number; failure_reason: string; updated_at: string
}
export interface GroundTimelineEvent {
  event_id: number | string; ts: string; event_type: string; severity: string; train_id: string; mr_id: string
  title: string; message: string; details: Record<string, unknown>
}
export interface GroundArchive {
  archive_id: string; site_id: string; run_id: string; run_date: string; actual_started_at: string; actual_ended_at: string
  mainline_train_count: number; ping_target_count: number; ping_sample_count: number; covered_train_count: number
  complete_session_count: number; partial_session_count: number; archive_size_bytes: number; archive_status: string
  retention_until: string; summary: Record<string, unknown>; message: string; created_at: string; updated_at: string
}
export interface GroundActionResponse { accepted: boolean; state: GroundRunState; run_id: string; message: string }
export interface GroundPage<T> { items: T[]; total: number }
export interface GroundInventorySummary {
  site_id: string; discovered_train_count: number; complete_train_count: number; ct_only_count: number; cw_only_count: number
  missing_management_ip_count: number; missing_credential_count: number; added_endpoint_count: number; updated_endpoint_count: number; removed_endpoint_count: number; removed_train_count: number; synchronized_at: string
}
export interface GroundTrainPolicy { enabled: boolean; priority: boolean; scheduling_priority: number; deep_collection_enabled: boolean; monitor_only: boolean; remark: string }
export interface GroundHealth {
  site_id: string; status: string; udp_running: boolean; udp_listen_address: string; udp_receive_rate_per_second: number; udp_received_count: number
  udp_unidentified_count: number; udp_queue_length: number; udp_queue_capacity: number; udp_dropped_count: number; raw_records_written: number; raw_bytes_written: number
  raw_last_write_duration_ms: number; database_pending_count: number; database_last_batch_duration_ms: number; open_file_count: number
  ping_target_count: number; ping_process_count: number; deep_queue_length: number; archive_pending_count: number; disk_free_bytes: number; last_error: string; updated_at: string
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
