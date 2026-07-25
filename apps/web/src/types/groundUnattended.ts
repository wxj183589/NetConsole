export type GroundRunState = 'DISABLED' | 'WAITING_WINDOW' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'STOPPING' | 'FINALIZING' | 'ARCHIVING' | 'COMPLETED' | 'ERROR'
export type GroundCoverageStatus = 'NOT_SEEN' | 'WAITING' | 'COLLECTING' | 'PARTIAL' | 'COVERED' | 'EXCLUDED' | 'OFFLINE' | 'FAILED'

export interface GroundProfile {
  site_id: string; enabled: boolean; schedule_start_time: string; schedule_end_time: string; timezone: string
  ac_poll_interval_seconds: number; stationary_exclusion_minutes: number; ac_stale_grace_seconds: number
  ac_ping_correlation_tolerance_seconds: number; ap_switch_before_seconds: number; ap_switch_after_seconds: number
  max_active_trains: number; max_active_mrs: number; max_starting_mrs: number; max_finalizing_mrs: number
  fleet_ping_interval_ms: number; fleet_ping_timeout_ms: number; fleet_ping_packet_size: number; fleet_ping_shard_size: number
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
  latest_archive_status: string; latest_archive_message: string; message: string; updated_at: string
}
export interface GroundEndpoint {
  endpoint: 'CT' | 'CW'; mr_id: string; mr_name: string; device_id: number | null; management_ip: string; online_status: string
  ping_active: boolean; ping_sent_count: number; ping_success_count: number; ping_loss_rate_percent: number | null
  ping_avg_rtt_ms: number | null; active_operation_id: string; latest_session_id: string
}
export interface GroundTrain {
  train_id: string; train_no: string; train_name: string; ping_eligible: boolean; deep_collection_eligible: boolean
  eligibility_status: string; exclusion_reason: string; current_ap_name: string; current_ap_mac: string
  station: string; section: string; mileage: string; rssi: number | null; same_ap_duration_seconds: number
  ac_snapshot_id: number | null; ac_received_at: string; coverage_status: GroundCoverageStatus; priority: boolean
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
