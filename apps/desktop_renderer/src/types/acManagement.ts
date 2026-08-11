export interface AcOverview {
  id: string
  name: string
  management_ip: string
  web_url?: string
  model: string
  software_version: string
  cpu_usage?: string
  memory_usage?: string
  https_port?: number | null
  ap_total: number
  online_aps: number
  offline_aps: number
  unauthenticated_aps: number
  radio_total: number
  optical_anomalies: number
  updated_at: string
  data_source: string
}

export interface AcManagementSummary {
  site_id: string
  acs: AcOverview[]
  ap_total: number
  online_aps: number
  offline_aps: number
  unauthenticated_aps: number
  radio_total: number
  optical_anomalies: number
  updated_at: string
  message: string
}

export interface AcAp {
  id: string
  ac_id: string
  ac_name: string
  name: string
  ip: string
  mac: string
  status: string
  state_display: string
  model: string
  online_time: string
  is_unauthenticated: boolean
  radio1_status: string
  radio2_status: string
  radio1_channel: string
  radio2_channel: string
  radio1_power: string
  radio2_power: string
  station: string
  station_source: string
  station_source_detail: string
  effective_station_id: string
  effective_station_name: string
  station_confidence: number
  manual_station_id: string
  manual_station_name: string
  manual_override_enabled: boolean
  auto_station_id: string
  auto_station_name: string
  auto_match_basis: string
  lldp_suggested_station_id: string
  lldp_suggested_station_name: string
  resource_station_text: string
  software_version: string
  hardware_version: string
  boot_version: string
  detail_updated_at: string
  detail_available: boolean
  section: string
  mileage: string
  direction: string
  location_note: string
  point_code: string
  trackside_ap_name: string
  remark: string
  switch_name: string
  switch_interface: string
  lldp_status: string
  optical_status: string
  optical_applicable?: boolean
  optical_severity: string
  optical_data_freshness: string
  optical_is_current_anomaly: boolean
  optical_rx_power: string
  updated_at: string
}

export interface AcApPage {
  items: AcAp[]
  total: number
  page: number
  page_size: number
  filter_options?: AcApFilterOptions
}

export interface AcApFilterOptions {
  stations: string[]
  sections: string[]
  models: string[]
  switches: string[]
}

export interface AcRadio {
  radio_id: number
  status: string
  mode: string
  band: string
  channel: string
  bandwidth: string
  usage: string
  tx_power: string
  clients: number
  bssid: string
  updated_at: string
}

export interface AcLldp {
  switch_name: string
  switch_ip: string
  interface_name: string
  lldp_local_interface: string
  lldp_neighbor_mac: string
  lldp_neighbor_interface: string
  lldp_neighbor: string
  port_status: string
  vlan: string
  optical_module_status: string
  match_status: string
  source: string
  updated_at: string
}

export interface AcOptical {
  optical_applicable?: boolean
  optical_status: string
  optical_severity: string
  raw_status: string
  ap_rx_status: string
  switch_rx_status: string
  tx_power_status: string
  ap_offline_related: boolean
  ap_online_status: string
  data_freshness: string
  is_current_anomaly: boolean
  anomaly_reason: string
  source_switch: string
  source_interface: string
  tx_power: string
  rx_power: string
  switch_rx_power: string
  temperature: string
  voltage: string
  bias_current: string
  threshold_status: string
  error_summary: string
  updated_at: string
}

export interface AcApDetail {
  ap: AcAp
  radios: AcRadio[]
  lldp: AcLldp
  optical: AcOptical
  connection: {
    ip_address: string
    state: string
    connected_at: string
    updated_at: string
  }
}

export interface AcApHistoryPage {
  kind: 'radio' | 'lldp' | 'optical'
  ap_id: string
  items: Array<Record<string, unknown>>
  total: number
  page: number
  page_size: number
}

export interface AcConfigSnapshot {
  id: number
  device_id: string
  ac_name: string
  timestamp: string
  type: string
  status: string
  size_bytes: number
  task_id: string
  error_summary: string
  path_id: string
  file_name: string
  created_at: string
}

export interface AcConfigSnapshotPage {
  items: AcConfigSnapshot[]
  total: number
  page: number
  page_size: number
}

export interface AcConfigContent {
  snapshot: AcConfigSnapshot
  content: string
  offset: number
  next_offset: number | null
  total_chars: number
  truncated: boolean
}

export interface AcConfigDiff {
  from_snapshot_id: number
  to_snapshot_id: number
  left_label: string
  right_label: string
  left_content: string
  right_content: string
  diff_rows: Array<{
    left_line: number | null
    left_text: string
    status: '=' | '+' | '-' | '~'
    right_line: number | null
    right_text: string
  }>
  diff_summary: {
    added: number
    removed: number
    modified: number
  }
  added: string[]
  removed: string[]
  modified: Array<Record<string, string>>
  raw_diff: string
  truncated: boolean
}

export interface AcApQuery {
  ac_id?: string
  page: number
  page_size: number
  query?: string
  status?: string
  station?: string
  section?: string
  model?: string
  switch?: string
  optical_status?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}
