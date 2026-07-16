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
export type VehicleMrOnlineTask = RailTransitTask
