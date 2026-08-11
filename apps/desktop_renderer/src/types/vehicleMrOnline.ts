import type { RailTransitTask } from './railTransitWeb'

export interface VehicleMrEndState {
  endpoint: 'CT' | 'TC'
  mr_id: string | null; mr_name: string | null; online_status: 'ONLINE' | 'OFFLINE' | 'STALE' | 'UNKNOWN'
  current_ap_name: string | null; current_ap_mac: string | null; mesh_radio: string | null; rssi_dbm: number | null
  station_name: string | null; section_name: string | null; mileage: string | null; direction: string | null
  match_status: 'EXACT' | 'NAME_NORMALIZED' | 'MAC_MATCHED' | 'UNMATCHED' | 'UNKNOWN'
  outdoor_optical_power: string | null; indoor_optical_power: string | null
  updated_at: string | null; data_status: 'FRESH' | 'STALE' | 'ERROR' | 'NO_DATA' | 'UNKNOWN'
}
export interface VehicleMrTrainState {
  train_id: string; train_no: string; train_name: string; is_registered: boolean
  overall_status: 'BOTH_ONLINE' | 'ONE_SIDE_ONLINE' | 'BOTH_OFFLINE' | 'STALE' | 'UNKNOWN'
  ct: VehicleMrEndState; tc: VehicleMrEndState
  current_station: string | null; current_section: string | null; current_mileage: string | null; direction: string | null
  policy: string | null; reason_code: string | null; reason_text: string | null; updated_at: string | null
}
export interface VehicleMrOnlinePage {
  items: VehicleMrTrainState[]; total: number; page: number; page_size: number; site_id: string
  mr_total: number; both_online_count: number; one_side_online_count: number; both_offline_count: number
  stale_count: number; unknown_count: number; active_mesh_link_count: number; unmatched_ap_count: number
}
export interface VehicleMrTrainMapping {
  id: number | null; enabled: boolean; train_display_name: string; train_id: string; train_no: string
  tc1_peer_name: string; tc2_peer_name: string; online_policy: string; remark: string
  created_at: string; updated_at: string
}
export interface VehicleMrEventPage { items: Array<Record<string, unknown>>; total: number }
export interface VehicleMrController {
  controller_id: string; device_id: number; name: string; primary_address: string; protocol: string; connection_ready: boolean
}
export interface VehicleMrHistoryFilters {
  start_time?: string; end_time?: string; car_end_label?: string; event_status?: string
  station?: string; ap_name?: string; limit?: number
}
export interface VehicleMrMappingPreviewRow {
  row_number: number; status: 'valid' | 'duplicate' | 'error'; key: string; message: string
  row: VehicleMrTrainMapping | null
}
export interface VehicleMrMappingPreview {
  file_name: string; file_sha256: string; duplicate_strategy: 'replace' | 'skip' | 'error'
  can_apply: boolean; total_count: number; valid_count: number; duplicate_count: number; error_count: number
  rows: VehicleMrMappingPreviewRow[]; result_rows: VehicleMrTrainMapping[]
}
export type VehicleMrOnlineTask = RailTransitTask
