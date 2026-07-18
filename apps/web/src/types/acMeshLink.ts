export type MeshDataStatus = 'fresh' | 'recent' | 'stale' | 'error' | 'unknown' | 'no_data'
export type MrOnlineStatus = 'online' | 'offline' | 'stale' | 'unknown'

export interface AcMeshLinkSummary {
  site_id: string
  controller_id: string
  controller_name: string
  registered_mrs: number
  online_mrs: number
  offline_mrs: number
  stale_mrs: number
  unknown_mrs: number
  active_links: number
  link_total: number
  unmatched_links: number
  offline_ap_links: number
  updated_at: string
  age_seconds: number | null
  data_status: MeshDataStatus
  source_type: string
  raw_available: boolean
  message: string
}

export interface AcMeshLinkRefreshResponse {
  success: boolean
  task_id: string
  status: string
  already_running: boolean
  message: string
}

export interface AcMeshLinkRecord {
  id: number
  snapshot_id: number
  controller_id: string
  controller_name: string
  mr_id: string
  train_no: string
  car_end: string
  mr_name: string
  mr_mac: string
  mr_device_id: string
  mr_management_ip: string
  mr_online_status: MrOnlineStatus
  peer_ap_id: string
  peer_ap_name: string
  peer_ap_mac: string
  peer_radio: string
  mesh_interface: string
  rssi: number | null
  station: string
  section: string
  mileage: string
  line_side: string
  ap_rx_power: string
  switch_rx_power: string
  last_seen_at: string
  match_method: string
  match_warning: string
  data_status: MeshDataStatus
}

export interface AcMeshLinkPage {
  items: AcMeshLinkRecord[]
  total: number
  page: number
  page_size: number
}

export interface AcMeshMrStatus {
  mr_id: string
  train_no: string
  train_display_name: string
  car_end: string
  mr_name: string
  mr_mac: string
  mr_device_id: string
  management_ip: string
  online_status: MrOnlineStatus
  peer_ap_id: string
  peer_ap_name: string
  peer_ap_mac: string
  mesh_radio: string
  rssi: number | null
  station: string
  section: string
  mileage: string
  line_side: string
  ap_rx_power: string
  switch_rx_power: string
  last_seen_at: string
  match_method: string
  match_warning: string
  data_status: MeshDataStatus
}

export interface AcMeshMrPage {
  items: AcMeshMrStatus[]
  total: number
  page: number
  page_size: number
}

export interface AcMeshMrEvent {
  id: number
  event_time: string
  event_type: string
  status: string
  station: string
  ap_name: string
  rssi: number | null
  car_end: string
}

export interface AcMeshMrDetail {
  mr: AcMeshMrStatus
  current_links: AcMeshLinkRecord[]
  recent_events: AcMeshMrEvent[]
}

export interface AcMeshSnapshot {
  id: number
  session_id: string
  controller_id: string
  controller_name: string
  site_id: string
  collected_at: string
  ac_time: string
  source_type: string
  source_reference: string
  data_status: MeshDataStatus
  age_seconds: number | null
  link_count: number
  parse_status: string
  error_summary: string
}

export interface AcMeshSnapshotPage {
  items: AcMeshSnapshot[]
  total: number
  page: number
  page_size: number
}

export interface AcMeshRawTail {
  snapshot_id: number | null
  available: boolean
  lines: string[]
  line_count: number
  source_reference: string
  updated_at: string
  message: string
}

export interface AcMeshMrQuery {
  online_status?: string
  train_no?: string
  mr_name?: string
  station?: string
  section?: string
  line_side?: string
  peer_ap_name?: string
  unmatched_only?: boolean
  query?: string
  page: number
  page_size: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export interface AcMeshLinkQuery {
  controller_id?: string
  mr_name?: string
  mr_mac?: string
  peer_ap_name?: string
  peer_ap_mac?: string
  station?: string
  section?: string
  line_side?: string
  match_status?: string
  query?: string
  page: number
  page_size: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}
