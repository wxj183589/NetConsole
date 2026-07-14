export type ManagedFileCategory = '' | 'session' | 'raw' | 'package' | 'artifact'

export interface FileManagementCapability {
  available: boolean
  message: string
}

export interface FileManagementStatus {
  site_id: string
  local_files: FileManagementCapability
  device_files: FileManagementCapability
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
