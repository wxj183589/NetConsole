export interface MeshAnalysisSummary {
  site_id: string
  index_status: 'pending' | 'discovering' | 'enriching' | 'ready' | 'failed'
  indexed_session_count: number
  pending_session_count: number
  index_updated_at: string | null
  session_count: number
  train_count: number
  mr_count: number
  link_record_count: number | null
  active_link_count: number | null
  standby_link_count: number | null
  switch_event_count: number | null
  short_link_count: number | null
  pingpong_count: number | null
  rssi_anomaly_count: number | null
  channel_busy_anomaly_count: number | null
  unmatched_ap_count: number | null
  warning_session_count: number
  latest_analysis_time: string | null
}

export interface MeshProfile {
  mr_id: string; display_name: string; safe_folder_name: string; linked_device_id: number | null; linked_device_uuid: string | null
  source_file_count: number; sample_count: number; link_record_count: number; session_count: number; event_count: number; notes: string
}

export interface MeshImportContextPrepare {
  site_id: string; vehicle_mr_count: number; profile_count: number; created_count: number; updated_count: number
  skipped_count: number; warnings: string[]
}

export interface MeshBundleProfileCandidate { profile_id: string; display_name: string }
export interface MeshBundleProfileImportState {
  profile_id: string; profile_name: string; stored_filename: string; daily_sequence: number | null
  rename_status: string; rename_warning: string; duplicate_status: string; import_allowed: boolean
  existing_source_id: number | null; existing_stored_filename: string; existing_session_id: string
  existing_profile_id: string; existing_profile_name: string
}
export interface MeshBundleMemberPreview {
  member_id: string; original_name: string; original_relative_path?: string; safe_name: string; size_bytes: number; sha256: string
  raw_sha256: string; content_sha256: string
  first_log_timestamp: string | null; last_log_timestamp: string | null; log_date: string | null
  stored_filename: string; daily_sequence: number | null; rename_status: string; rename_warning: string
  duplicate_status: string; batch_duplicate_of: string; import_allowed: boolean
  existing_source_id: number | null; existing_stored_filename: string; existing_session_id: string
  existing_profile_id: string; existing_profile_name: string
  train_number: string; role: string; match_status: 'matched' | 'unmatched' | 'ambiguous'
  selected_profile_id: string; selected_profile_name: string
  profile_import_states: MeshBundleProfileImportState[]
  candidates: MeshBundleProfileCandidate[]
}
export interface MeshBundlePreview {
  preview_id: string; file_name: string; archive_sha256: string; archive_size_bytes: number
  member_count: number; duplicate_archive: boolean; expires_at: string; items: MeshBundleMemberPreview[]
}
export interface MeshBundleMapping {
  member_id: string; train_number: string; role: 'CT' | 'CW'; profile_id: string
}
export interface MeshBundleImportRequest {
  preview_id: string; mappings: MeshBundleMapping[]; explicit_confirmation: boolean
}

export interface MeshLocalScanStats {
  found_count: number; unregistered_count: number; imported_count: number; duplicate_count: number
  invalid_count: number; needs_metadata_count: number; failed_count: number
  waiting_repair_count: number; repairing_count: number; repair_failed_count: number; parse_failed_count: number
}
export interface MeshLocalScanProfile { profile_id: string; display_name: string }
export interface MeshLocalScanCandidate {
  candidate_id: string; relative_path: string; file_name: string; file_type: 'log' | 'log_gz' | 'zip'
  file_size: number; modified_at: string; mtime_ns: number; sha256: string
  profile_id: string; profile_name: string; train_no: string; mr_role: string
  match_status: 'matched' | 'unmatched' | 'ambiguous'
  scan_status: 'unregistered' | 'imported' | 'duplicate' | 'invalid' | 'needs_metadata' | 'failed' | 'ignored'
    | 'waiting_repair' | 'repairing' | 'queued' | 'parsing' | 'repair_failed' | 'parse_failed'
  error_message: string; existing_session_id: string; existing_profile_name: string; duplicate_of_candidate_id: string
}
export interface MeshLocalScanResult {
  scan_id: string; site_id: string; created_at: string; updated_at: string; status: string
  stats: MeshLocalScanStats; profiles: MeshLocalScanProfile[]; candidates: MeshLocalScanCandidate[]
}
export interface MeshLocalScanStart { scan_id: string; task: import('./railTransitWeb').RailTransitTask }

export interface MeshAnalysisSession {
  session_id: string
  site_id: string
  analysis_time: string | null
  train_name: string
  mr_name: string
  mr_role: string
  source_type: string
  original_filename: string
  raw_log_count: number
  link_record_count: number | null
  active_link_count: number | null
  standby_link_count: number | null
  event_count: number | null
  data_integrity: string
  analysis_status: string
  parsed_status: 'ready' | 'legacy' | 'stale' | 'missing' | 'unreadable' | 'rebuilding'
  parsed_message: string
  schema_version: string | null
  available_capabilities: string[]
  missing_capabilities: string[]
  warning_count: number
  report_count: number
  first_sample_time: string | null
  last_sample_time: string | null
}

export interface Page<T> {
  items: T[]; total: number; page: number; page_size: number
  index_status?: string; indexed_session_count?: number; pending_session_count?: number
}
export interface MeshImportContext {
  site_id: string; revision: string; profiles: MeshProfile[]
  vehicle_mrs: import('./railTransitBaseData').VehicleMr[]
}
export interface MeshAnalysisOverview { summary: MeshAnalysisSummary; sessions: Page<MeshAnalysisSession> }
export interface MeshWarning { code: string; message: string; severity: string }
export interface MeshRawSource {
  source_file_id: number; source_action_id: string; source_id?: string; source_type: string; name: string; exists: boolean; size_bytes: number; modified_at: string | null
  original_filename: string; stored_filename: string; raw_sha256: string; content_sha256: string
  first_log_timestamp: string | null; last_log_timestamp: string | null; log_date: string | null; daily_sequence: number | null
  rename_status: string; rename_warning: string
  compressed: boolean; tail_available: boolean; recoverable: boolean; recovery_source: string; missing_reason: string
  rebuild_capability: 'ready' | 'recoverable_from_bundle' | 'raw_missing' | 'task_running' | 'unsupported'
  package_name: string; package_sha256: string; bundle_member_id: string
  identity_index_revision: number; identity_current_revision: number; identity_mapped_at: string; identity_mapping_status: string
}
export interface MeshAnalysisParams {
  link_time_window: number; link_switch_threshold: number; link_hold_rssi: number; link_establish_threshold: number
  main_link_switch_time_ms: number; short_link_tolerance_ms: number; pingpong_tolerance_ms: number; pingpong_return_window_ms: number | null
  merge_same_physical_ap_dual_radio: boolean; include_log_boundary_segments: boolean; sample_interval_ms: number | null
  service_type: 'PIS' | 'CBTC' | '信号' | '其他'; wifi_type: 'WiFi5' | 'WiFi6' | '其他'
}
export interface MeshSessionDetail { session: MeshAnalysisSession; analysis_params: MeshAnalysisParams; available_radios?: number[]; warnings: MeshWarning[]; sources: MeshRawSource[] }

export interface MeshIdentityMetadata {
  identity_status?: 'matched' | 'unresolved' | 'ambiguous'
  identity_source?: string | null
  identity_rule?: string | null
  identity_confidence?: number
  identity_reason?: string | null
}

export interface MeshLinkDetail extends MeshIdentityMetadata {
  record_id: number; timestamp: string; timestamp_tag: string | null; sample_group_index: number | null; train_name: string; mr_name: string; mr_role: string
  local_radio: number | null; peer_mac_raw?: string | null; peer_mac: string | null; peer_ap_name: string | null; peer_ap_mac: string | null; peer_radio: string | null; peer_radio_mac: string | null
  link_role: string; link_status: string; establish_time: string | null; duration_text: string | null; duration_seconds: number | null; link_count: number | null
  local_rssi_db: number | null; peer_rssi_db: number | null; local_noise_dbm: number | null; peer_noise_dbm: number | null
  local_signal_dbm: number | null; peer_signal_dbm: number | null; local_rate_raw: string | number | null; peer_rate_raw: string | number | null
  local_tx_busy: number | null; peer_tx_busy: number | null; local_rx_busy: number | null; peer_rx_busy: number | null
  rssi: number | null; channel: string | null; bandwidth: string | null
  station: string | null; section: string | null; mileage: string | null; line_side: string | null
  event_type: string | null; duration_ms: number | null; source_file: string; source_record_index: number | null; source_line_number: number | null
  local_cpu_percent: number | null; peer_cpu_percent: number | null; local_mem_percent: number | null; peer_mem_percent: number | null
  local_tx_des_free_cnt: number | null; peer_tx_des_free_cnt: number | null; local_tx: number | null; peer_tx: number | null; local_rx: number | null; peer_rx: number | null
  local_retry: number | null; peer_retry: number | null; local_err: number | null; peer_err: number | null
  local_tx_garp: number | null; peer_rx_garp: number | null; local_tx_mul_join: number | null; peer_rx_mul_join: number | null
  raw_line_start: number | null; raw_line_end: number | null; raw_offset_start: number | null; raw_offset_end: number | null
  match_method: string | null; warning: string | null
}

export interface MeshActiveBuildOrder extends MeshIdentityMetadata {
  sequence: number; source_file_id: number | null; local_radio: number | null; peer_mac_raw?: string; active_peer_mac: string
  peer_ap_name: string | null; peer_ap_mac: string | null; station: string | null; section: string | null; mileage: string | null; line_side: string | null
  peer_radio: string | null; peer_radio_mac?: string | null; anchor_link_id: number | null
  build_start_time: string; build_end_time: string; main_link_duration_seconds: number | null; reported_duration_seconds: number | null
  sample_count: number; avg_mr_rssi: number | null; min_mr_rssi: number | null; max_mr_rssi: number | null; p10_mr_rssi: number | null
  avg_tx_busy: number | null; avg_rx_busy: number | null; avg_peer_tx_busy: number | null; avg_peer_rx_busy: number | null
  link_time_window?: number | null; link_switch_threshold?: number | null; link_hold_rssi?: number | null; link_establish_threshold?: number | null
  link_establish_rssi?: number | null; link_establishment_accepted?: boolean; link_establishment_signal?: number | null; link_establishment_reason?: string
  build_result: string; judge_reason: string; pingpong_type: string; source_file: string
  main_link_switch_time_ms?: number | null; short_link_tolerance_ms?: number | null; pingpong_tolerance_ms?: number | null; pingpong_return_window_ms?: number | null; short_threshold_seconds?: number | null
  physical_ap_key?: string
  is_same_physical_ap_radio_switch?: boolean; is_pingpong_abnormal?: boolean; pingpong_judgment_reason?: string; pingpong_group_id?: string; middle_ap_dwell_ms?: number | null
  pingpong_return_duration_ms?: number | null; previous_ap?: string; middle_ap?: string; return_ap?: string
}

export interface MeshChartBackupLink extends MeshIdentityMetadata {
  link_id: number | null; source_file_id?: number | null; link_count?: number | null; timestamp: string; timestamp_tag: string; local_radio: number | null; link_state?: string; peer_mac: string | null; peer_ap_name: string | null; peer_ap_mac: string | null
  peer_radio: string | null; peer_radio_mac: string | null; local_rssi: number | null; peer_rssi: number | null
  local_signal: number | null; peer_signal: number | null; station?: string | null; section?: string | null
  local_tx_busy: number | null; peer_tx_busy: number | null
  local_rx_busy: number | null; peer_rx_busy: number | null
}

export interface MeshRssiZeroRun {
  state: 'suppressed' | 'sustained'
  start_time: string
  end_time: string
  duration_ms: number
  sample_count: number
  boundary: 'start' | 'middle' | 'end' | 'single'
  estimated_end: boolean
}

export interface MeshChartPoint extends MeshIdentityMetadata {
  link_id: number | null; link_count?: number | null; timestamp: string; timestamp_tag: string | null; source_file_id: number | null; segment_sequence?: number | null
  local_radio: number | null; link_state: string; peer_mac: string | null; peer_ap_name: string | null; peer_ap_mac: string | null
  peer_radio: string | null; peer_radio_mac: string | null; station: string | null; section?: string | null
  establish_time?: string | null; segment_start?: string | null; segment_end?: string | null; segment_duration_seconds?: number | null
  local_rssi: number | null; peer_rssi: number | null; local_signal: number | null; peer_signal: number | null
  local_rssi_zero_run?: MeshRssiZeroRun | null; peer_rssi_zero_run?: MeshRssiZeroRun | null
  local_tx_busy: number | null; peer_tx_busy: number | null; local_rx_busy: number | null; peer_rx_busy: number | null
  is_switch: boolean; is_anomaly: boolean; bridge_ambiguous_active?: boolean; gap_before: boolean; backups: MeshChartBackupLink[]
}

export interface MeshChartEvent {
  event_id: number | null; timestamp: string; event_type: string; local_radio: number | null; from_peer_mac: string | null; to_peer_mac: string | null
  duration_ms: number | null; from_ap_name?: string | null; to_ap_name?: string | null; segment_sequence?: number | null
  point_timestamp?: string | null; point_rssi?: number | null; point_context?: MeshChartPoint | null
  render_point_timestamp?: string | null; render_point_rssi?: number | null; render_aligned?: boolean
  render_busy_point_timestamp?: string | null; render_busy_point_index?: number | null; render_busy_tx_busy?: number | null
  render_busy_rx_busy?: number | null; render_busy_aligned?: boolean; busy_point_context?: MeshChartPoint | null
  before_rssi?: number | null; after_rssi?: number | null
  station?: string | null; section?: string | null
  reason?: string | null
  from_station?: string | null; from_section?: string | null
  to_station?: string | null; to_section?: string | null
}

export interface MeshLocationSegment {
  start_time: string; end_time: string; station: string | null; section: string | null; label: string | null
  direction?: string | null; mileage_start?: string | number | null; mileage_end?: string | number | null
}

export interface MeshPathChartSummary {
  current_peer_mac: string | null; current_peer_ap_name: string | null; current_radio: number | null
  earliest_sample_time?: string | null; latest_sample_time?: string | null; first_sample_time: string | null; last_sample_time: string | null; sample_count: number; active_count: number
  standby_context_count: number; triangle_link_point_count?: number; switch_count: number; estimated_interval_seconds: number | null; continuity_gap_seconds: number | null
  suppressed_zero_sample_count: number; suppressed_zero_run_count: number; sustained_zero_run_count: number
  sustained_zero_total_duration_ms: number; sustained_zero_longest_duration_ms: number
}

export interface MeshPathChart {
  mode: 'active_path' | 'peer_segment'; anchor: MeshChartPoint | null; points: MeshChartPoint[]; events: MeshChartEvent[]
  location_segments: MeshLocationSegment[]
  total_points: number; returned_points: number; downsampled: boolean; requested_max_points: number; effective_max_points: number; downsample_warning: string | null
  summary: MeshPathChartSummary; time_from: string | null; time_to: string | null
  requested_time_from: string | null; requested_time_to: string | null; effective_time_from: string | null; effective_time_to: string | null
  first_sample_time: string | null; last_sample_time: string | null; total_points_in_range: number; payload_bytes: number; query_duration_ms: number
}

export interface MeshTracksideSignalPointData extends MeshIdentityMetadata {
  timestamp: string; timestamp_tag: string; source_file_id: number | null; link_id: number | null; link_count?: number | null; sample_id: number | null
  local_radio: number | null; role: 'ACTIVE' | 'STANDBY'; peer_mac: string | null; peer_ap_name: string | null; peer_ap_mac: string | null
  peer_radio: string | null; peer_radio_mac: string | null; station: string | null; section: string | null
  peer_rssi: number | null; local_rssi: number | null; peer_signal: number | null; local_signal: number | null
  run_id?: string | null; run_sequence?: number | null
  segment_sequence?: number | null; segment_start?: string | null; segment_end?: string | null
  segment_duration_seconds: number | null; break_before?: boolean; data_source: string
  rssi_zero_run?: MeshRssiZeroRun | null
}

export interface MeshTracksideSignalSeriesData {
  series_id: string; peer_name: string | null; peer_mac: string | null; ap_mac: string | null; radio: number | null
  peer_radio_mac: string | null; station: string | null; section: string | null
  roles_present: Array<'ACTIVE' | 'STANDBY'>; data_source: string
  total_points: number; returned_points: number; points: MeshTracksideSignalPointData[]
}

export interface MeshTracksideSignalChartData {
  source_id: string; radio: number | null; time_range: { start: string | null; end: string | null }
  series: MeshTracksideSignalSeriesData[]; events: MeshChartEvent[]; warnings: string[]
  estimated_interval_seconds: number | null; continuity_gap_seconds: number | null
  total_series: number; returned_series: number; total_points: number; returned_points: number
  total_frames: number; returned_frames: number; total_link_points: number; returned_link_points: number; total_link_runs: number
  active_link_points: number; standby_link_points: number; triangle_link_points?: number; returned_active_link_points: number; returned_standby_link_points: number; returned_triangle_link_points?: number
  role_switch_count: number; skipped_missing_signal_points: number; skipped_missing_identity_points: number
  suppressed_zero_sample_count: number; suppressed_zero_run_count: number; sustained_zero_run_count: number
  sustained_zero_total_duration_ms: number; sustained_zero_longest_duration_ms: number
  downsampled: boolean; requested_max_frames: number; effective_max_frames: number
  requested_max_points: number; effective_max_points?: number; top_n: number
  included_roles: Array<'ACTIVE' | 'STANDBY'>; include_standby: boolean; payload_bytes: number; query_duration_ms: number
}

export interface MeshTimelineItem extends MeshIdentityMetadata { segment_id: number; start_time: string; end_time: string; duration_seconds: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_radio: number | null; rssi_min: number | null; rssi_avg: number | null; rssi_max: number | null; station: string | null; section: string | null; mileage: string | null; line_side: string | null; event_type: string | null; warning: string | null }
export interface MeshSwitchEvent { event_id: number; timestamp: string | null; event_type: string; mr_name: string; local_radio: number | null; from_peer_mac: string | null; to_peer_mac: string | null; from_ap_name: string | null; to_ap_name: string | null; before_rssi: number | null; after_rssi: number | null; duration_ms: number | null; new_active_duration_ms?: number | null; stability_threshold_ms?: number | null; switch_result?: string; is_short_link: boolean; is_pingpong: boolean; station: string | null; section: string | null; warning: string | null }
export interface MeshRssiPoint extends MeshIdentityMetadata { timestamp: string; value: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_radio: number | null }
export interface MeshRssi { statistics: { min_rssi: number | null; max_rssi: number | null; avg_rssi: number | null; latest_rssi: number | null; sample_count: number; missing_sample_count: number; zero_sample_count: number; low_rssi_count: number; severe_low_rssi_count: number }; points: MeshRssiPoint[]; downsampled: boolean; total_points: number }
export interface MeshChannelBusy { timestamp: string; local_radio: number | null; ctl_busy: number | null; tx_busy: number | null; rx_busy: number | null; total_busy: number | null; peer_ap_name: string | null; station: string | null; section: string | null; source_type: string; warning: string | null }
export interface MeshRatePoint extends MeshIdentityMetadata { timestamp: string; local_radio: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_rate_raw: number | null; peer_rate_raw: number | null }
export interface MeshRatePage { items: MeshRatePoint[]; total: number; downsampled: boolean }
export interface MeshCounterDeltaPoint extends MeshIdentityMetadata { timestamp: string; local_radio: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_retry_delta: number | null; peer_retry_delta: number | null; local_error_delta: number | null; peer_error_delta: number | null }
export interface MeshCounterDeltaPage { items: MeshCounterDeltaPoint[]; total: number; downsampled: boolean }
export interface MeshAnomaly { anomaly_id: string; severity: string; anomaly_type: string; start_time: string | null; end_time: string | null; train_name: string; mr_name: string; peer_ap_name: string | null; peer_ap_mac: string | null; station: string | null; section: string | null; description: string; evidence_reference: string | null; rule_version: string | null }
export interface MeshArtifact { artifact_id: string; artifact_type: string; name: string; size_bytes: number; modified_at: string | null; status: string; source: string; downloadable: boolean; deletable?: boolean }
export interface MeshRawTail { source_action_id: string; source_id?: string; available: boolean; lines: string[]; message: string }
