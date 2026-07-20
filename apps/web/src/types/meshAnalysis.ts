export interface MeshAnalysisSummary {
  site_id: string
  session_count: number
  train_count: number
  mr_count: number
  link_record_count: number
  active_link_count: number
  standby_link_count: number
  switch_event_count: number
  short_link_count: number
  pingpong_count: number
  rssi_anomaly_count: number
  channel_busy_anomaly_count: number
  unmatched_ap_count: number
  warning_session_count: number
  latest_analysis_time: string | null
}

export interface MeshProfile {
  mr_id: string; display_name: string; safe_folder_name: string; linked_device_id: number | null
  source_file_count: number; sample_count: number; link_record_count: number; session_count: number; event_count: number; notes: string
}

export interface MeshBundleProfileCandidate { profile_id: string; display_name: string }
export interface MeshBundleMemberPreview {
  original_name: string; safe_name: string; size_bytes: number; sha256: string
  train_number: string; role: string; match_status: 'matched' | 'unmatched' | 'ambiguous'
  selected_profile_id: string; selected_profile_name: string; candidates: MeshBundleProfileCandidate[]
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
  link_record_count: number
  active_link_count: number
  standby_link_count: number
  event_count: number
  data_integrity: string
  analysis_status: string
  warning_count: number
  report_count: number
  first_sample_time: string | null
  last_sample_time: string | null
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface MeshWarning { code: string; message: string; severity: string }
export interface MeshRawSource { source_id: string; source_type: string; name: string; exists: boolean; size_bytes: number; modified_at: string | null; compressed: boolean; tail_available: boolean }
export interface MeshSessionDetail { session: MeshAnalysisSession; warnings: MeshWarning[]; sources: MeshRawSource[] }

export interface MeshLinkDetail {
  record_id: number; timestamp: string; train_name: string; mr_name: string; mr_role: string
  local_radio: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; peer_radio: string | null
  link_role: string; link_status: string; rssi: number | null; channel: string | null; bandwidth: string | null
  station: string | null; section: string | null; mileage: string | null; line_side: string | null
  event_type: string | null; duration_ms: number | null; source_file: string; source_record_index: number | null
  match_method: string | null; warning: string | null
}

export interface MeshTimelineItem { segment_id: number; start_time: string; end_time: string; duration_seconds: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_radio: number | null; rssi_min: number | null; rssi_avg: number | null; rssi_max: number | null; station: string | null; section: string | null; mileage: string | null; line_side: string | null; event_type: string | null; warning: string | null }
export interface MeshSwitchEvent { event_id: number; timestamp: string | null; event_type: string; mr_name: string; local_radio: number | null; from_peer_mac: string | null; to_peer_mac: string | null; from_ap_name: string | null; to_ap_name: string | null; before_rssi: number | null; after_rssi: number | null; duration_ms: number | null; is_short_link: boolean; is_pingpong: boolean; station: string | null; section: string | null; warning: string | null }
export interface MeshRssiPoint { timestamp: string; value: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_radio: number | null }
export interface MeshRssi { statistics: { min_rssi: number | null; max_rssi: number | null; avg_rssi: number | null; latest_rssi: number | null; sample_count: number; missing_sample_count: number; low_rssi_count: number; severe_low_rssi_count: number }; points: MeshRssiPoint[]; downsampled: boolean; total_points: number }
export interface MeshChannelBusy { timestamp: string; local_radio: number | null; ctl_busy: number | null; tx_busy: number | null; rx_busy: number | null; total_busy: number | null; peer_ap_name: string | null; station: string | null; section: string | null; source_type: string; warning: string | null }
export interface MeshRatePoint { timestamp: string; local_radio: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_rate_raw: number | null; peer_rate_raw: number | null }
export interface MeshRatePage { items: MeshRatePoint[]; total: number; downsampled: boolean }
export interface MeshCounterDeltaPoint { timestamp: string; local_radio: number | null; peer_ap_name: string | null; peer_ap_mac: string | null; local_retry_delta: number | null; peer_retry_delta: number | null; local_error_delta: number | null; peer_error_delta: number | null }
export interface MeshCounterDeltaPage { items: MeshCounterDeltaPoint[]; total: number; downsampled: boolean }
export interface MeshAnomaly { anomaly_id: string; severity: string; anomaly_type: string; start_time: string | null; end_time: string | null; train_name: string; mr_name: string; peer_ap_name: string | null; peer_ap_mac: string | null; station: string | null; section: string | null; description: string; evidence_reference: string | null; rule_version: string | null }
export interface MeshApStatistics { peer_ap_name: string | null; peer_ap_mac: string | null; station: string | null; section: string | null; mileage: string | null; line_side: string | null; linked_mr_count: number; link_up_count: number; link_down_count: number; switch_in_count: number; switch_out_count: number; avg_rssi: number | null; min_rssi: number | null; anomaly_count: number; match_status: string }
export interface MeshArtifact { artifact_id: string; artifact_type: string; name: string; size_bytes: number; modified_at: string | null; status: string; source: string; downloadable: boolean }
export interface MeshRawTail { source_id: string; available: boolean; lines: string[]; message: string }
