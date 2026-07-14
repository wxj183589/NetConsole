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
  connection_status?: DeviceConnectionStatus | ''
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}
