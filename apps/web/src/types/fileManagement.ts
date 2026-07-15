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

export type FileDownloadStatus = 'PENDING' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export interface FileDownloadResult {
  file_ref: string
  name: string
  size_bytes: number
  artifact_id: string
  relative_path: string
  sha256: string
  device_id: string
  remote_entry_id: string
}

export interface FileDownloadTask {
  task_id: string
  site_id: string
  status: FileDownloadStatus
  progress: number
  stage: string
  message: string
  result: FileDownloadResult | null
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
}

export interface FileDesktopAction {
  action: string
  accepted: boolean
  integration_required: boolean
  message: string
}
