import { apiRequest } from './client'

export interface StorageAuditSnapshot {
  report_directory: string
  root_path: string
  generated_at: string
  total_size_bytes: number
  total_files: number
  sites: Array<Record<string, unknown> & { site_name?: string; total_size_bytes?: number; total_files?: number; percentage?: number }>
  directories: Array<Record<string, unknown> & { path?: string; size_bytes?: number; percentage?: number }>
  largest_files: Array<Record<string, unknown> & { path?: string; size_bytes?: number; modified_time?: string }>
  databases: Array<Record<string, unknown> & { database?: string; size_bytes?: number; site?: string }>
  errors: string[]
  read_only: boolean
}

export const getStorageAudit = () => apiRequest<StorageAuditSnapshot>('/api/v1/storage-audit')
