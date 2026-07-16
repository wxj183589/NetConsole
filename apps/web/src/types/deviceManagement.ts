export type DeviceConnectionStatus = 'UNKNOWN' | 'TESTING' | 'REACHABLE' | 'UNREACHABLE' | 'ERROR'
export type DeviceConnectionProtocol = 'SSH' | 'TELNET' | 'SNMP'

export interface DeviceCapability {
  ssh: boolean
  ssh_port: number | null
  telnet: boolean
  telnet_port: number | null
  snmp: boolean
  snmp_versions: string[]
  snmp_port: number | null
}

export interface DeviceGroupOption {
  id: number
  name: string
}

export interface DeviceListItem {
  id: number
  device_uuid: string
  name: string
  system_name: string
  station: string
  group_id: number | null
  group_name: string
  device_vendor: string
  device_type: string
  primary_address: string
  backup_address: string
  updated_at: string
  capabilities: DeviceCapability
  connection_status: DeviceConnectionStatus
  last_test_task_id: string
  last_test_time: string
}

export interface DevicePage {
  items: DeviceListItem[]
  groups: DeviceGroupOption[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface DeviceTaskSummary {
  task_id: string
  task_type: string
  task_name: string
  status: string
  stage: string
  message: string
  created_time: string
  updated_time: string
  error_summary: string
}

export interface DeviceDetail extends DeviceListItem {
  location: string
  mac_address: string
  https_port: number | null
  web_url: string
  ssh_username: string
  telnet_username: string
  tunnel_enabled: boolean
  tunnel1_enabled: boolean
  tunnel1_host: string
  tunnel1_port: number | null
  tunnel1_username: string
  tunnel2_enabled: boolean
  tunnel2_host: string
  tunnel2_port: number | null
  tunnel2_username: string
  snmp_v1_enabled: boolean
  snmp_v2c_enabled: boolean
  snmp_v3_enabled: boolean
  snmpv3_username: string
  snmpv3_security_level: 'noAuthNoPriv' | 'AuthNoPriv' | 'AuthPriv'
  snmpv3_auth_protocol: 'MD5' | 'SHA' | 'SHA224' | 'SHA256' | 'SHA384' | 'SHA512'
  snmpv3_priv_protocol: 'DES' | '3DES' | 'AES128' | 'AES192' | 'AES256'
  snmp_context_name: string
  snmp_timeout_ms: number
  snmp_retries: number
  ssh_secret_configured: boolean
  telnet_secret_configured: boolean
  tunnel1_secret_configured: boolean
  tunnel2_secret_configured: boolean
  snmp_ro_secret_configured: boolean
  snmp_rw_secret_configured: boolean
  snmpv3_auth_secret_configured: boolean
  snmpv3_priv_secret_configured: boolean
  remark: string
  created_at: string
}

export interface DeviceDetailResponse {
  device: DeviceDetail
  fact: null | {
    system_name: string
    model: string
    serial_number: string
    mac_address: string
    software_version: string
    bootrom_version: string
    vendor: string
    uptime: string
    collected_at: string
  }
  recent_tasks: DeviceTaskSummary[]
  recent_collection: null | {
    collect_run_uuid: string
    collect_type: string
    status: string
    started_at: string
    ended_at: string
    error_summary: string
  }
  recent_errors: Array<{ source: 'task' | 'collection'; time: string; message: string }>
  connection_commands: Array<{ protocol: 'SSH' | 'TELNET'; command: string }>
  interfaces: Array<Record<string, unknown>>
  optical_modules: Array<Record<string, unknown>>
  lldp_neighbors: Array<Record<string, unknown>>
  trackside_ap_business: Array<Record<string, unknown>>
}

export interface DeviceEditPreviewRequest {
  name: string
  system_name?: string
  station?: string
  location?: string
  group_id?: number | null
  device_vendor?: string
  device_type?: string
  primary_address: string
  backup_address?: string
  ssh_enabled?: boolean
  ssh_port?: number
  telnet_enabled?: boolean
  telnet_port?: number
  snmp_enabled?: boolean
  snmp_v1_enabled?: boolean
  snmp_v2c_enabled?: boolean
  snmp_v3_enabled?: boolean
  snmp_port?: number
  https_port?: number | null
  remark?: string
}

export interface DeviceWriteRequest extends DeviceEditPreviewRequest {
  ssh_username?: string
  ssh_password?: string
  telnet_username?: string
  telnet_password?: string
  tunnel_enabled?: boolean
  tunnel1_enabled?: boolean
  tunnel1_host?: string
  tunnel1_port?: number | null
  tunnel1_username?: string
  tunnel1_password?: string
  tunnel2_enabled?: boolean
  tunnel2_host?: string
  tunnel2_port?: number | null
  tunnel2_username?: string
  tunnel2_password?: string
  snmp_ro_community?: string
  snmp_rw_community?: string
  snmpv3_username?: string
  snmpv3_security_level?: 'noAuthNoPriv' | 'AuthNoPriv' | 'AuthPriv'
  snmpv3_auth_protocol?: 'MD5' | 'SHA' | 'SHA224' | 'SHA256' | 'SHA384' | 'SHA512'
  snmpv3_auth_password?: string
  snmpv3_priv_protocol?: 'DES' | '3DES' | 'AES128' | 'AES192' | 'AES256'
  snmpv3_priv_password?: string
  snmp_context_name?: string
  snmp_timeout_ms?: number
  snmp_retries?: number
}

export interface DeviceEditPreview {
  valid: boolean
  normalized: DeviceEditPreviewRequest
  errors: string[]
  warnings: string[]
  persistence: 'preview_only'
}

export interface DeviceConnectionTest {
  task_id: string
  task_status: string
  device_uuid: string
  protocol: DeviceConnectionProtocol | null
  success: boolean | null
  result_status: string
  message: string
  method: string
  host: string
  port: number | null
  latency_ms: number | null
  system_name: string
  model: string
  os_family: string
  interface_count: number | null
  error_type: string
  suggestion: string
  created_time: string
  updated_time: string
}

export interface DeviceListQuery {
  search?: string
  group_id?: number
  ungrouped?: boolean
  device_type?: string
  vendor?: string
  group_filter?: number | '__ungrouped__'
  connection_status?: DeviceConnectionStatus | ''
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export interface DeviceWriteResponse {
  action: 'created' | 'updated' | 'duplicated'
  device: DeviceDetail
}

export interface DeviceGroup {
  id: number
  name: string
  device_count: number
}

export interface DeviceTaskReference {
  task_id: string
  task_status: string
  action: string
  artifact_id: string
  available: boolean
  sha256: string
  size_bytes: number
  message: string
}

export interface DeviceTaskBatch {
  action: string
  tasks: DeviceTaskReference[]
}

export interface DeviceHistoryPage {
  kind: 'interface' | 'optical' | 'lldp'
  object_name: string
  items: Array<Record<string, unknown>>
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface DeviceImportPreview {
  preview_token: string
  source_name: string
  source_sha256: string
  row_count: number
  columns: string[]
  errors: string[]
  warnings: string[]
  persistence: 'preview_only'
}

export interface DeviceDeleteToken {
  confirmation_token: string
  device_uuids: string[]
  expires_at: string
}

export interface DeviceExternalTerminalAction {
  native_action: 'launchTerminal'
  device_uuid: string
  terminal_type: 'securecrt' | 'putty' | 'xshell'
  success: true
  code: string
  message: string
}

export interface DeviceExternalTerminalBatch {
  terminal_type: 'securecrt' | 'putty' | 'xshell'
  success: number
  failed: number
  failures: string[]
}

export interface DeviceExternalTerminalConfirmation {
  confirmation_token: string
  device_uuids: string[]
  terminal_type: 'securecrt' | 'putty' | 'xshell'
  expires_at: string
}

export interface DeviceExternalTerminalSettings {
  terminal_type: 'securecrt' | 'putty' | 'xshell'
  securecrt_path: string
  xshell_path: string
  putty_path: string
  pass_password: boolean
}

export interface DeviceExportRequest extends DeviceListQuery {
  device_uuids?: string[]
  include_credentials?: boolean
}

export interface DeviceOmniPeekPreviewItem {
  key: string
  role: 'trackside_ap' | 'onboard_mr'
  name: string
  physical_mac: string
  system_name: string
  location: string
  source: string
  selected: boolean
  force_export: boolean
  normalized_physical_mac: string
  r1_mac: string
  r2_mac: string
  status: string
  warnings: string[]
}

export interface DeviceOmniPeekPreview {
  task_id: string
  task_status: string
  ready: boolean
  items: DeviceOmniPeekPreviewItem[]
  source_counts: Record<string, number>
  stats: Record<string, number>
  message: string
}
