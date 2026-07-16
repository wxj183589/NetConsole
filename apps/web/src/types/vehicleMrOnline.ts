import type { RailTransitTask } from './railTransitWeb'

export interface VehicleMrEndState {
  seen: boolean; station: string; ap_name: string; rssi: number | null; last_seen_at: string
  match_method: string; match_score: number
}
export interface VehicleMrTrainState {
  train_id: string; train_no: string; display_name: string; is_registered: boolean; status: string
  current_station: string; last_ac_time: string; last_seen_at: string; tc1: VehicleMrEndState; tc2: VehicleMrEndState
  online_policy: string; expected_end: string; direction: string; status_reason: string
}
export interface VehicleMrOnlinePage {
  items: VehicleMrTrainState[]; total: number; page: number; page_size: number; site_id: string
  online_count: number; abnormal_count: number; offline_count: number; unregistered_count: number
}
export interface VehicleMrTrainMapping {
  id: number | null; enabled: boolean; train_display_name: string; train_id: string; train_no: string
  tc1_peer_name: string; tc2_peer_name: string; online_policy: string; remark: string
  created_at: string; updated_at: string
}
export interface VehicleMrEventPage { items: Array<Record<string, unknown>>; total: number }
export interface VehicleMrController {
  device_id: number; name: string; primary_address: string; protocol: string; connection_ready: boolean
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
