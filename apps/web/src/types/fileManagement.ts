export type ManagedFileCategory = '' | 'session' | 'raw' | 'package' | 'artifact'

export interface FileManagementCapability {
  available: boolean
  message: string
}

export interface FileManagementStatus {
  site_id: string
  local_files: FileManagementCapability
  device_files: FileManagementCapability
  winscp: FileManagementCapability
}

export interface ManagedFile {
  file_ref: string
  site_id: string
  category: Exclude<ManagedFileCategory, ''>
  name: string
  relative_path: string
  size_bytes: number
  modified_at: string | null
  downloadable: boolean
}

export interface ManagedFilePage {
  site_id: string
  category: ManagedFileCategory
  items: ManagedFile[]
  total: number
}

export interface LocalFileEntry {
  entry_id: string
  name: string
  is_dir: boolean
  size_bytes: number | null
  modified_at: string | null
  file_type: string
  downloadable: boolean
}

export interface LocalFilePage {
  site_id: string
  root_entry_id: string
  current_entry_id: string
  parent_entry_id: string
  current_label: string
  items: LocalFileEntry[]
  total: number
  page: number
  limit: number
  has_more: boolean
}

export type FileDownloadStatus = 'PENDING' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export interface FileDownloadResult {
  result_kind: 'managed_file' | 'device_file'
  file_ref: string
  device_file_ref: string
  name: string
  size_bytes: number
  artifact_id: string
  relative_path: string
  sha256: string
  device_id: string
  remote_entry_id: string
  target_kind: 'device_file' | 'mr_raw' | ''
  mesh_import_status: '' | 'completed' | 'duplicate' | 'failed' | 'rebuild_required'
  mesh_imported_count: number
  mesh_duplicate_count: number
  mesh_parsed_record_count: number
  mesh_import_error_code?: string
  mesh_import_error: string
}

export interface FileDownloadTask {
  task_id: string
  site_id: string
  status: FileDownloadStatus
  progress: number
  stage: string
  message: string
  batch_id: string
  source_kind: 'managed_file' | 'remote' | ''
  device_name: string
  remote_name: string
  remote_path: string
  local_path: string
  downloaded_bytes: number
  total_bytes: number
  speed_bytes_per_second: number
  created_at: string
  updated_at: string
  retryable: boolean
  retry_reason: string
  result: FileDownloadResult | null
}

export interface FileDownloadBatch {
  batch_id: string
  tasks: FileDownloadTask[]
  failures: string[]
}

export interface FileConnection {
  connection_id: string
  device_id: string
  device_name: string
  status: string
  root_entry_id: string
  current_entry_id: string
  current_label: string
  message: string
}

export interface HostKeyChallenge {
  code: 'DEVICE_FILE_HOST_KEY_UNKNOWN' | 'DEVICE_FILE_HOST_KEY_MISMATCH' | string
  message: string
  details: {
    challenge_id?: string
    device_id?: string
    device_name?: string
    host?: string
    port?: number
    algorithm?: string
    fingerprint_sha256?: string
  }
}

export interface FileRemoteDevice {
  device_id: string
  name: string
  address: string
  group_id: number | null
  group_name: string
  device_type: string
  station: string
}

export interface RemoteFileEntry {
  entry_id: string
  name: string
  is_dir: boolean
  size_bytes: number | null
  modified_at: string | null
  category: string
  file_type: string
  downloadable: boolean
}

export interface RemoteFilePage {
  connection_id: string
  current_entry_id: string
  parent_entry_id: string
  current_label: string
  items: RemoteFileEntry[]
  total: number
  page: number
  limit: number
  has_more: boolean
}

export interface FileDesktopAction {
  action: string
  action_ref: string
  expires_at: string
  accepted: boolean
  integration_required: boolean
  message: string
}
