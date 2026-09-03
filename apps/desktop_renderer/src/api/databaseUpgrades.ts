import { apiRequest } from './client'

const root = '/api/database-upgrades'

export interface DatabaseStatus {
  database_kind: string
  scope_type: string
  scope_id: string
  mr_id: string
  display_name: string
  safe_folder_name: string
  current_version: string
  required_version: string
  health_status: 'healthy' | 'upgrade_required' | 'not_created'
  needs_upgrade: boolean
  backup_count: number
  latest_backup_id: string
  last_upgrade_time: string
  last_upgrade_task: string
  raw_file_count: number
  registered_source_count: number
}

export interface DatabaseBackup {
  backup_id: string
  task_id: string
  database_kind: string
  scope_type: string
  scope_id: string
  profile_id?: string
  profile_name?: string
  created_at: string
  old_schema_version?: string
  target_schema_version?: string
  database_size: number
  size_bytes?: number
  database_sha256: string
  result_status: string
  integrity_check_result?: { valid?: boolean; restorable?: boolean; integrity_check?: string; quick_check?: string }
  path: string
}

export interface DatabaseUpgradeSnapshot {
  site_id: string
  databases: DatabaseStatus[]
  backups: DatabaseBackup[]
  backup_count: number
  backup_size_bytes: number
}

export interface DatabaseTaskReference { task_id: string; task_type: string }
export interface DesktopActionResult { success: boolean; code: string; message: string }

export const getDatabaseUpgradeSnapshot = () => apiRequest<DatabaseUpgradeSnapshot>(root)
export const startDatabaseUpgrade = (profileId: string) => apiRequest<DatabaseTaskReference>(`${root}/upgrade`, {
  method: 'POST', body: JSON.stringify({ database_kind: 'mesh_derived', profile_id: profileId }),
})
export const startDatabaseBatchUpgrade = (profileIds: string[]) => apiRequest<DatabaseTaskReference>(`${root}/upgrade/batch`, {
  method: 'POST', body: JSON.stringify({ database_kind: 'mesh_derived', profile_ids: profileIds, confirmed: true }),
})
export const startDatabaseBatchBackup = (profileIds: string[]) => apiRequest<DatabaseTaskReference>(`${root}/backups/batch`, {
  method: 'POST', body: JSON.stringify({ database_kind: 'mesh_derived', profile_ids: profileIds, confirmed: true }),
})
export const organizeLegacyDatabaseArchives = () => apiRequest<DatabaseTaskReference>(`${root}/legacy-archives/organize`, { method: 'POST' })
export const validateDatabaseBackup = (backupId: string) => apiRequest<DatabaseTaskReference>(`${root}/backups/${encodeURIComponent(backupId)}/validate`, { method: 'POST' })
export const restoreDatabaseBackup = (backupId: string) => apiRequest<DatabaseTaskReference>(`${root}/backups/${encodeURIComponent(backupId)}/restore`, { method: 'POST', body: JSON.stringify({ confirmed: true }) })
export const deleteDatabaseBackup = (backupId: string) => apiRequest<DatabaseTaskReference>(`${root}/backups/${encodeURIComponent(backupId)}/delete`, { method: 'POST', body: JSON.stringify({ confirmed: true }) })
export const deleteDatabaseBackups = (backupIds: string[]) => apiRequest<DatabaseTaskReference>(`${root}/backups/batch-delete`, {
  method: 'POST', body: JSON.stringify({ backup_ids: backupIds, confirmed: true }),
})
export const openDatabaseBackupDirectory = (backupId: string) => apiRequest<DesktopActionResult>(`${root}/backups/${encodeURIComponent(backupId)}/open-directory`, { method: 'POST' })
