import type { RailTransitTask } from './railTransitWeb'

export interface TracksideApBusinessRow {
  site: string; device_name: string; interface_name: string; link_status: string; port_type: string
  description: string; pvid: unknown; vlan: unknown; switch_rx_power: unknown; switch_optical_status: string
  ap_mac: string; ap_name: string; ap_rx_power: unknown; ap_optical_status: string; updated_at: string
  optical_severity: string
}

export interface TracksideApBusinessPage {
  items: TracksideApBusinessRow[]; total: number; page: number; page_size: number; site_id: string
  device_count: number; candidate_interface_count: number; optical_abnormal_count: number
  fit_ap_resource_count: number; query_ms: number; build_ms: number; empty_reason: string
  identity_shadow: Record<string, unknown>
}

export interface TracksideApUpdateRequest { station?: string; ap_uuid?: string; ap_mac?: string; ap_name?: string }
export type TracksideApTask = RailTransitTask

export interface TracksideApPlanRow {
  station_name: string; ap_count: number; ap_start_address: string; mask_length: number | null
  ap_gateway: string; ap_management_vlans: string; remark: string; sort_order: number
}

export interface TracksideApPlan { items: TracksideApPlanRow[]; total: number }
export interface TracksideApPlanPreviewRow {
  row_number: number; status: 'valid' | 'duplicate' | 'error'; key: string; message: string
  row: TracksideApPlanRow | null
}
export interface TracksideApPlanPreview {
  file_name: string; file_sha256: string; duplicate_strategy: 'replace' | 'skip' | 'error'
  can_apply: boolean; total_count: number; valid_count: number; duplicate_count: number; error_count: number
  rows: TracksideApPlanPreviewRow[]; result_rows: TracksideApPlanRow[]
}
