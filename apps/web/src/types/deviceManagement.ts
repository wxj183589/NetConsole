export type DeviceConnectionStatus = 'UNKNOWN' | 'TESTING' | 'REACHABLE' | 'UNREACHABLE' | 'ERROR'
export type DeviceConnectionProtocol = 'SSH' | 'TELNET' | 'SNMP'
export type DeviceSecretField =
  | 'ssh_password'
  | 'telnet_password'
  | 'tunnel1_password'
  | 'tunnel2_password'
  | 'snmp_ro_community'

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
  snmp_timeout_ms: number
  snmp_retries: number
  ssh_secret_configured: boolean
  telnet_secret_configured: boolean
  tunnel1_secret_configured: boolean
  tunnel2_secret_configured: boolean
  snmp_ro_secret_configured: boolean
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
  /** 后端根据设备实际能力返回；前端不自行推断分区。 */
  capabilities?: DeviceDetailCapabilities
  visible_sections?: DeviceDetailSection[]
  fetched_at?: string
  source?: DeviceDataSource
  task_id?: string
}

export interface DeviceDetailSource {
  available: boolean
  source: string
  collected_at: string | null
  task_id?: string | null
  reason: string | null
}

export interface DevicePlatformFacts {
  vendor: string
  role: string
  platform: string
  software_version: string | null
  software_major: string | null
  source: string
  confidence: 'high' | 'medium' | 'low' | 'unknown'
  collected_at: string | null
}

export interface DeviceDetailCapabilityInfo {
  capability_id: string
  available: boolean
  executable: boolean
  source: string
  reason: string | null
  profile_id: string | null
  profile_version: number | null
  compatibility?: string | null
  risk?: string | null
  real_device_status?: string | null
}

export interface DeviceOverviewTaskFact {
  task_id: string
  task_type: string
  status: string
  updated_at: string
  finished_at: string | null
  message: string | null
}

export interface DeviceOverviewTaskFacts {
  recent_task_count: number | null
  active_task_count: number | null
  latest_running_task: DeviceOverviewTaskFact | null
  latest_successful_task: DeviceOverviewTaskFact | null
  latest_failed_task: DeviceOverviewTaskFact | null
  latest_error: string | null
  truncated: boolean
}

export interface DeviceOverviewCounts {
  interfaces: number | null
  transceivers: number | null
  lldp_neighbors: number | null
  recent_tasks: number | null
  config_snapshots: number | null
}

export interface DeviceOverviewResponse {
  device_uuid: string
  name: string
  system_name: string | null
  device_type: string | null
  station: string | null
  location: string | null
  primary_address: string | null
  backup_address: string | null
  model: string | null
  serial_number: string | null
  mac_address: string | null
  bootrom_version: string | null
  uptime: string | null
  connection_status: string
  platform_facts: DevicePlatformFacts
  capabilities: DeviceDetailCapabilityInfo[]
  command_profile: DeviceDetailCapabilityInfo
  visible_sections: DeviceDetailSection[]
  task_facts: DeviceOverviewTaskFacts
  counts: DeviceOverviewCounts
  snapshot: DeviceDetailSource
}

export interface DeviceInterfaceRecord {
  name: string
  normalized_name: string
  category: string
  link_status: string | null
  protocol_status: string | null
  speed: string | null
  duplex: string | null
  interface_type: string | null
  port_status: string | null
  pvid: string | null
  description: string | null
  ip_address: string | null
  mac_address: string | null
  vlan: string | null
  collected_at: string | null
}

export interface DeviceTransceiverRecord {
  interface_name: string
  normalized_interface_name: string
  rx_power: number | null
  tx_power: number | null
  temperature: number | null
  voltage: number | null
  bias_current: number | null
  module_model: string | null
  module_serial_number: string | null
  module_vendor: string | null
  wavelength: string | null
  transmission_distance: string | null
  connector_type: string | null
  rx_low_alarm: number | null
  rx_high_alarm: number | null
  rx_low_warning: number | null
  rx_high_warning: number | null
  severity: string
  severity_reason: string | null
  collected_at: string | null
}

export interface DeviceLldpRecord {
  local_interface: string
  normalized_local_interface: string
  neighbor_system_name: string | null
  neighbor_mac: string | null
  neighbor_interface: string | null
  neighbor_ip: string | null
  neighbor_device_uuid: string | null
  association_status: 'matched' | 'unresolved'
  collected_at: string | null
}

export interface DeviceConfigSnapshotRecord {
  snapshot_id: number
  snapshot_type: string
  timestamp: string
  size_bytes: number | null
  artifact_id: string | null
  filename: string | null
  sha256: string | null
  created_at: string | null
  error_summary: string | null
}

export interface DeviceDetailTaskRecord {
  task_id: string
  task_type: string
  task_name: string
  status: string
  progress: number
  stage: string | null
  message: string | null
  error_summary: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  duration_seconds?: number | null
  duration_ms?: number | null
}

export interface DeviceTracksideApAssociationFacts {
  link_status: string | null
  switch_rx_power: number | null
  ap_rx_power: number | null
}

export interface DeviceAcApAssociationFacts {
  mac_address: string | null
  radio1_status: string | null
  radio1_channel: string | null
  radio1_power: string | null
  radio2_status: string | null
  radio2_channel: string | null
  radio2_power: string | null
  lldp_status: string | null
  optical_status: string | null
  optical_rx_power: number | null
}

export interface DeviceMrSessionAssociationFacts {
  site_id: string
  started_at: string | null
  stopped_at: string | null
  executor_kind: string | null
  has_raw_data: boolean
  has_parsed_data: boolean
  has_package: boolean
  mesh_available: boolean
  rssi_available: boolean
  fping_available: boolean
  iperf_available: boolean
}

export type DeviceBusinessAssociationType = 'trackside_ap' | 'fit_ap' | 'online_mr_session'

export interface DeviceBusinessAssociationRecord {
  association_type: DeviceBusinessAssociationType
  association_id: string
  name: string | null
  status: string | null
  local_interface: string | null
  peer_address: string | null
  trackside_ap: DeviceTracksideApAssociationFacts | null
  fit_ap: DeviceAcApAssociationFacts | null
  online_mr_session: DeviceMrSessionAssociationFacts | null
  updated_at: string | null
}

export interface DeviceInterfaceDetailResponse {
  interface: DeviceInterfaceRecord
  transceiver: DeviceTransceiverRecord | null
  lldp_neighbors: DeviceLldpRecord[]
  lldp_truncated: boolean
  source: DeviceDetailSource
}

export interface DeviceDetailPageSource {
  source: DeviceDetailSource
  truncated?: boolean
}

export interface DeviceDetailSectionResponse {
  items?: DeviceDetailRecord[]
  total?: number
  page?: number
  page_size?: number
  total_pages?: number
  source: DeviceDetailSource
  task_id?: string | null
  truncated?: boolean
}

export interface DeviceDetailRefreshTask {
  task_id: string
  operation_id: string
  status: string
  reused: boolean
  message: string | null
}

export interface DeviceDetailHistoryRecord {
  kind: 'interface' | 'optical' | 'lldp'
  object_name: string
  collected_at: string | null
  values: Record<string, unknown>
}

export interface DeviceDetailHistoryPage {
  items: DeviceDetailHistoryRecord[]
  total: number
  page: number
  page_size: number
  total_pages: number
  source: DeviceDetailSource
}

export type DeviceDetailSection =
  | 'overview'
  | 'interfaces'
  | 'optical'
  | 'lldp'
  | 'configuration'
  | 'tasks'
  | 'business'

export interface DeviceDetailCapabilities {
  sections: Partial<Record<DeviceDetailSection, boolean>>
  actions?: Partial<Record<'refresh' | 'connection_test' | 'edit' | 'terminal', boolean>>
}

export type DeviceDataSource = 'live' | 'snapshot' | 'cache' | 'unknown'

export type DeviceDetailRecord = Record<string, unknown>

export interface DeviceDetailSectionPage {
  section: Exclude<DeviceDetailSection, 'overview'>
  items: DeviceDetailRecord[]
  total: number
  page: number
  page_size: number
  total_pages: number
  fetched_at?: string
  source: DeviceDataSource | DeviceDetailSource
  task_id?: string
  truncated?: boolean
}

export interface DeviceDetailSectionQuery {
  page?: number
  page_size?: number
  search?: string
  status?: string
  interface_type?: string
  severity?: string
  linked_only?: boolean
  snapshot_type?: string
}

export interface DeviceWriteRequest {
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
  snmp_port?: number
  https_port?: number | null
  remark?: string
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
  snmp_timeout_ms?: number
  snmp_retries?: number
  clear_secret_fields?: DeviceSecretField[]
}

export interface DeviceEditProfileResponse extends DeviceWriteRequest {
  device_uuid: string
  ssh_secret_configured: boolean
  telnet_secret_configured: boolean
  tunnel1_secret_configured: boolean
  tunnel2_secret_configured: boolean
  snmp_ro_secret_configured: boolean
}

export interface DeviceFormConnectionTestRequest extends DeviceWriteRequest {
  protocol: DeviceConnectionProtocol
  device_uuid?: string
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
  duplicate_rows: number[]
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
