export type ConfigSnapshotType = 'running' | 'saved' | 'diff' | string

export interface ConfigDeviceGroup {
  id: number
  name: string
  device_count: number
}

export interface ConfigDevice {
  id: number
  device_uuid: string
  name: string
  system_name: string
  device_type: string
  station: string
  group_id: number | null
}

export interface ConfigDevicePage {
  items: ConfigDevice[]
  total: number
  page: number
  page_size: number
  total_pages: number
  groups: ConfigDeviceGroup[]
}

export interface ConfigSnapshot {
  id: number
  device_id: number | null
  device_uuid: string
  timestamp: string
  type: ConfigSnapshotType
  size_bytes: number
  artifact_id: string
  filename: string
  hash: string
  created_at: string
  error_message: string
}

export interface ConfigTaskReference {
  id: string
  type: string
  status: string
  progress: number
  device_id: string
  device_name: string
  message: string
}

export interface ConfigTaskStatus extends ConfigTaskReference {
  stage: string
  created_time: string
  started_time: string
  finished_time: string
  error_message: string
  result: Record<string, unknown>
}

export type ConfigDiffStatus = '=' | '+' | '-' | '~'

export interface ConfigDiffRow {
  left_line: number | null
  left_text: string
  status: ConfigDiffStatus
  right_line: number | null
  right_text: string
}

export interface ConfigDiffSummary {
  added: number
  removed: number
  modified: number
}

export interface ConfigConfirmation {
  action: 'delete_snapshots' | 'save_force'
  confirmation_token: string
  digest: string
  summary: string
  expires_at: string
  snapshot_ids: number[]
  device_ids: number[]
  action_plan: string[]
}

export interface ConfigDirectory {
  directory_kind: 'config_snapshots' | 'config_exports'
  action: 'open_controlled_directory'
  target_id: string
  success: boolean
  code: string
  message: string
}
