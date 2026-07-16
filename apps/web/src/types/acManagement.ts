export interface AcOverview {
  id: string
  name: string
  management_ip: string
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
  section: string
  mileage: string
  direction: string
  switch_name: string
  switch_interface: string
  lldp_status: string
  optical_status: string
  optical_severity: string
  optical_rx_power: string
  updated_at: string
}

export interface AcApPage {
  items: AcAp[]
  total: number
  page: number
  page_size: number
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
  lldp_neighbor: string
  port_status: string
  vlan: string
  optical_module_status: string
  match_status: string
  source: string
  updated_at: string
}

export interface AcOptical {
  optical_status: string
  optical_severity: string
  raw_status: string
  ap_offline_related: boolean
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
