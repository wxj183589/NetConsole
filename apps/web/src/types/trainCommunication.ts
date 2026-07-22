export type CommunicationStatus = 'normal' | 'warning' | 'critical' | 'stale' | 'unknown'

export interface CommunicationWarning { code: string; message: string; source: string; severity: string }
export interface CommunicationDataSource { source: string; status: string; updated_at: string | null; age_seconds: number | null; reference: string }
export interface CommunicationMetric {
  status: string; target: string | null; protocol: string | null; direction: string | null
  sent: number | null; received: number | null; loss_percent: number | null
  latest_value: number | null; average_value: number | null; maximum_value: number | null
  threshold_value: number | null; updated_at: string | null
}
export interface MrCommunicationStatus {
  train_id: string; train_name: string; mr_id: string; mr_name: string; mr_role: string
  device_id: string | number | null; management_ip: string; mac: string
  executor: string | null; agent_id: string | null; collection_status: string
  session_id: string | null; task_id: string | null; mesh_link_status: string
  peer_ap_id: string; peer_ap_name: string; peer_ap_mac: string; mesh_radio: string
  rssi: number | null; station: string; section: string; mileage: string; line_side: string
  ap_online_status: string; optical_status: string
  fping_status: string; fping_latest_rtt_ms: number | null; fping_avg_rtt_ms: number | null; fping_loss_percent: number | null
  iperf_status: string; iperf_latest_mbps: number | null; iperf_avg_mbps: number | null; iperf_threshold_mbps: number | null
  data_integrity: string; collected_at: string | null; data_age_seconds: number | null
  communication_status: CommunicationStatus; is_active: boolean
  warnings: CommunicationWarning[]; data_sources: CommunicationDataSource[]
  fping: CommunicationMetric; iperf: CommunicationMetric
}

export interface TrainCommunicationRow {
  train_id: string; train_no: string; train_name: string; communication_status: CommunicationStatus
  canonical_train_id: string; display_name: string
  overall_status: 'BOTH_ONLINE' | 'ONE_SIDE_ONLINE' | 'BOTH_OFFLINE' | 'STALE' | 'UNKNOWN' | ''
  ct_online_status: 'ONLINE' | 'OFFLINE' | 'STALE' | 'UNKNOWN'
  tc_online_status: 'ONLINE' | 'OFFLINE' | 'STALE' | 'UNKNOWN'
  ct_mr_id: string; ct_mr_name: string; tc_mr_id: string; tc_mr_name: string
  updated_at: string | null; data_status: string; online_reason: string
  mrs: MrCommunicationStatus[]; current_mesh_links: number; active_sessions: number
  warning_count: number; last_updated_at: string | null
}
export interface TrainCommunicationPage { items: TrainCommunicationRow[]; total: number; page: number; page_size: number }
export interface TrainCommunicationSummary {
  site_id: string; registered_trains: number; registered_mrs: number; normal_trains: number
  warning_trains: number; critical_trains: number; stale_trains: number; unknown_trains: number
  current_mesh_links: number; active_online_mr_sessions: number; agent_imported_sessions: number
  latest_updated_at: string | null
}
export type TopologyStatus = 'normal' | 'abnormal' | 'not_detected' | 'not_configured' | 'checking' | 'stale'
export interface TrainCommunicationTopologyNode {
  node_id: string; side: 'TC1' | 'TC2'; role: 'MR' | 'SWITCH' | 'SERVER'
  name: string; device_id: string | null; ip_address: string | null; status: TopologyStatus; message: string; updated_at: string | null
}
export interface TrainCommunicationTopologyLink {
  link_id: string; source: string; target: string; label: string; status: TopologyStatus; message: string
}
export interface TrainCommunicationTopology {
  train_id: string; train_name: string; train_status: TopologyStatus; checked_at: string | null
  point_table_status: 'configured' | 'missing' | 'invalid'; point_table_message: string; point_table_revision: string; point_table_missing_nodes: string[]
  tc1_nodes: TrainCommunicationTopologyNode[]; tc2_nodes: TrainCommunicationTopologyNode[]
  links: TrainCommunicationTopologyLink[]
  vrrp: { status: TopologyStatus; master_side: 'TC1' | 'TC2' | null; virtual_ip: string | null; master_device: string | null; backup_device: string | null; message: string; updated_at: string | null }
  cross_end: { status: TopologyStatus; message: string; updated_at: string | null }
}
export interface TrainCommunicationFilters {
  train?: string; mr_role?: string; communication_status?: string; mesh_link_status?: string
  station?: string; section?: string; line_side?: string; executor?: string; data_source?: string
  has_warning?: boolean; active_only?: boolean; agent_only?: boolean; optical_anomaly_only?: boolean
  query?: string; page: number; page_size: number; sort_by?: string; sort_order?: 'asc' | 'desc'
}
