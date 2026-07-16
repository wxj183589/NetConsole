export interface AcWebTask {
  task_id: string
  status: string
  action: string
  artifact_id: string
  available: boolean
  progress: number
  stage: string
  current: number
  total: number
  sha256: string
  size_bytes: number
  message: string
  error_message: string
  result_summary: Record<string, unknown>
}

export interface AcTracksidePlan {
  mode: string
  station_name: string
  ap_count: number
  ap_start_address: string
  mask_length: number
  ap_gateway: string
  ap_management_vlans: string
  remark: string
}

export interface AcTracksidePlanPage {
  items: AcTracksidePlan[]
  total: number
  mode: string
}

export interface AcExtension {
  id: number
  ap_name: string
  ap_mac_display: string
  ap_mac_norm: string
  station_name: string
  section_name: string
  mileage_text: string
  location_desc: string
  direction: string
  remark: string
  match_status: string
}

export interface AcExtensionPage {
  items: AcExtension[]
  total: number
  page: number
  page_size: number
}

export interface AcExtensionPreview {
  preview_id: string
  file_name: string
  template_type: string
  confidence_score: number
  low_confidence: boolean
  summary: Record<string, number>
  row_count: number
  preview_digest: string
}

export interface AcActionPlan {
  plan_id: string
  target_id: string
  action_id: string
  action_label: string
  plan_digest: string
  confirm_token: string
  expires_at: number
  status: string
  command_summary: string[]
  task_id: string
}

export interface AcActionAudit {
  plan_id: string
  target_id: string
  action_id: string
  commands: string[]
  plan_digest: string
  status: string
  task_id: string
  task_status: string
  result_summary: Record<string, unknown>
  executor: string
  real_device_task: boolean
  audit: boolean
}
