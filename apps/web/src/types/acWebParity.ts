export interface AcWebTask {
  task_id: string
  status: string
  action: string
  target_id?: string
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

export type AcOmniPeekRadioMode = 'auto' | 'r1_only' | 'r2_only' | 'r1_r2' | 'none'

export interface AcOmniPeekConfig {
  line_name: string
  include_ac_fit_ap: boolean
  include_ap_extensions: boolean
  include_device_mr: boolean
  export_trackside_physical: boolean
  export_trackside_r1: boolean
  export_trackside_r2: boolean
  export_onboard_physical: boolean
  export_onboard_r1: boolean
  export_onboard_r2: boolean
  onboard_radio_mode: AcOmniPeekRadioMode
  enable_h3c_derivation: boolean
  colors: Record<string, string>
}

export interface AcOmniPeekPreviewItem {
  item_key: string
  selected: boolean
  force_export: boolean
  force_export_allowed: boolean
  role: 'trackside_ap' | 'onboard_mr'
  type_label: string
  name: string
  location: string
  physical_mac: string
  r1_mac: string
  r2_mac: string
  r1_source: string
  r2_source: string
  export_content: string
  group: string
  color: string
  status: string
  abnormal_reason: string
  data_source: string
}

export interface AcOmniPeekPreview {
  task_id: string
  task_status: string
  ready: boolean
  config: Partial<AcOmniPeekConfig>
  source_counts: Record<string, number>
  statistics: Record<string, number>
  items: AcOmniPeekPreviewItem[]
  matching_item_keys: string[]
  selected_item_keys: string[]
  total: number
  page: number
  page_size: number
  input_ap_count: number
  exportable_entry_count: number
  skipped_count: number
  error_count: number
  message: string
}

export interface AcOmniPeekPreferences {
  line_name: string
  colors: Record<string, string>
}

export interface AcFitApRemoteTerminalProfile {
  ac_id: string
  scope: 'ac' | 'site'
  protocol: 'ssh' | 'telnet'
  port: number
  username: string
  password_configured: boolean
  source: 'ac_profile' | 'site_profile' | 'none'
}

export type AcTerminalType = 'securecrt' | 'putty' | 'xshell'

export interface AcExternalTerminalOptions {
  default_terminal_type: AcTerminalType | null
  options: Array<{ terminal_type: AcTerminalType; label: string }>
}

export interface AcExternalTerminalAction {
  ap_id: string
  terminal_type: AcTerminalType
  success: true
  message: string
}
