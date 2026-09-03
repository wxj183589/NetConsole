import { apiRequest } from './client'

export interface SiteRecord {
  site_id: string
  display_name: string
  line_name?: string | null
  project_type?: string | null
  path?: string
  created_at: string
  updated_at: string
  remark: string
  active: boolean
  size_bytes: number
  site_kind: 'formal' | 'demo' | 'legacy'
  classification: string
  managed_demo: boolean
  demo_seed_version: string
  migration_status: string
  data_integrity: 'ok' | 'unknown' | 'failed'
  recommended_action: string
  audited_at: string
}

export interface SiteAuditSummary {
  display_name: string
  site_id: string
  total_size: number
  file_count: number
  directory_count: number
  is_current: boolean
  is_registered: boolean
  is_referenced_by_bootstrap: boolean
  is_demo: boolean
  managed_demo: boolean
  demo_seed_version: string
  migration_status: string
  raw_log_count: number
  parsed_database_count: number
  report_count: number
  artifact_count: number
  task_count: number
  online_mr_session_count: number
  mesh_source_count: number
  unique_business_data: boolean
  duplicate_candidates: string[]
  referenced_records: string[]
  classification: string
  recommended_action: string
  can_delete: boolean
  safe_to_replace: boolean
}

export interface SiteCleanupPlan {
  cleanup_token: string
  site_id: string
  classification: string
  blocking_reasons: string[]
  recoverable: boolean
  can_delete: boolean
}

export interface SiteRetentionCandidate {
  candidate_id: string
  category: 'current_database' | 'expired_raw' | 'history_backup' | 'outdated_database' | 'task_history' | string
  relative_path: string
  display_name: string
  size_bytes: number
  estimated_release_bytes: number
  age_days: number
  status: string
  recommended_action: 'keep' | 'archive' | 'delete' | 'purge' | string
  safe: boolean
  reason: string
  details: Record<string, unknown>
}

export interface SiteRetentionReport {
  scan_token: string
  site_id: string
  display_name: string
  generated_at: string
  policy: {
    backup_archive_days: number
    backup_delete_days: number
    online_mr_raw_archive_days: number
    task_event_retention_days: number
    task_retention_status: 'USER_POLICY_REQUIRED' | string
    typed_task_retention_apply_enabled: boolean
    typed_task_retention_proposal: {
      progress_event_days: number
      ordinary_event_days: number
      terminal_metadata_days: number
      terminal_snapshot_days: number
      terminal_result_days: number
    }
    rollback_keep_count: number
  }
  summary: {
    total_bytes: number
    current_database_bytes: number
    raw_bytes: number
    parsed_bytes: number
    backup_bytes: number
    other_bytes: number
    safe_cleanup_bytes: number
    compressible_bytes: number
    actionable_count: number
  }
  candidates: SiteRetentionCandidate[]
}

export interface DataRootSnapshot {
  data_root: string
  default_data_root: string
  site_count: number
  active_site_id: string
  storage_mode: 'persistent' | 'isolated_test'
  data_root_kind: 'persistent' | 'temporary'
  persistent: boolean
}

export interface SiteTaskResponse { task_id: string; task_type: string }
export interface SiteTrashResponse { site_id: string; display_name: string; trash_path: string; recoverable: boolean }

export type SitePackageType = 'full_migration' | 'sanitized_share' | 'field_collection' | 'collection_return' | 'lightweight'
export type SiteConflictChoice = 'local' | 'returned' | 'manual'

export interface SitePackageConflict {
  conflict_id: string
  entity_type: string
  entity_id: string
  field: string
  base_value: unknown
  local_value: unknown
  returned_value: unknown
}

export interface SitePackageInspection {
  site_id: string
  target_site_id?: string
  site_uuid: string
  site_name: string
  package_type: SitePackageType
  package_profile?: string
  package_id: string
  base_revision: number
  local_revision?: number
  file_count: number
  site_identity_match?: boolean
  new_files?: number
  duplicate_files?: number
  new_tasks?: number
  updated_tasks?: number
  new_records?: number
  updated_records?: number
  duplicate_records?: number
  unsupported_records?: number
  deletion_requests?: number
  conflict_count: number
  conflicts: SitePackageConflict[]
  invalid_count: number
  estimated_additional_bytes: number
  create_snapshot?: boolean
  can_import: boolean
  contains_credentials: boolean
  encrypted: boolean
  credential_reentry_count: number
}

export interface SiteConflictResolution {
  conflict_id: string
  choice: SiteConflictChoice
  manual_value?: unknown
}

export const listSites = () => apiRequest<SiteRecord[]>('/api/v1/sites')
export const getActiveSite = () => apiRequest<SiteRecord>('/api/v1/sites/active')
export const getDataRoot = () => apiRequest<DataRootSnapshot>('/api/v1/storage/data-root')
export const updateSite = (siteId: string, payload: { display_name: string; line_name: string | null; project_type: string | null }) => apiRequest<SiteRecord>(`/api/v1/sites/${encodeURIComponent(siteId)}`, { method: 'PATCH', body: JSON.stringify(payload) })
export const trashSite = (siteId: string, confirmDisplayName: string) => apiRequest<SiteTrashResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/trash`, { method: 'POST', body: JSON.stringify({ confirm_display_name: confirmDisplayName }) })
export const createSite = (payload: { site_id: string; display_name: string; remark?: string; activate?: boolean }) => apiRequest<SiteRecord>('/api/v1/sites', { method: 'POST', body: JSON.stringify(payload) })
export const preflightSiteActivation = (siteId: string) => apiRequest<{ ready: boolean; target_site_id: string; previous_site_id: string; registry_revision?: string }>(`/api/v1/sites/${encodeURIComponent(siteId)}/activate/preflight`, { method: 'POST' })
export const activateSite = (siteId: string) => apiRequest<{ restart_required: boolean; site_root?: string; registry_revision?: string; switch_revision?: string; runtime_revision?: string }>(`/api/v1/sites/${encodeURIComponent(siteId)}/activate`, { method: 'POST', body: JSON.stringify({ confirmed: true }) })
export const inspectSitePackage = (packagePath: string, targetSiteId = '') => apiRequest<SitePackageInspection>('/api/v1/sites/import/inspect', { method: 'POST', body: JSON.stringify({ package_path: packagePath, target_site_id: targetSiteId }) })
export const exportSite = (siteId: string, destinationPath: string, packageType: SitePackageType = 'full_migration') => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/export`, { method: 'POST', body: JSON.stringify({ destination_path: destinationPath, package_type: packageType }) })
export const importSite = (payload: { package_path: string; site_id?: string; display_name?: string; replace_site_id?: string; activate?: boolean; raw_only?: boolean; conflict_resolutions?: SiteConflictResolution[] }) => apiRequest<SiteTaskResponse>('/api/v1/sites/import', { method: 'POST', body: JSON.stringify(payload) })
export const validateDataRoot = (path: string) => apiRequest<{ valid: boolean; path: string; free_bytes: number }>('/api/v1/storage/data-root/validate', { method: 'POST', body: JSON.stringify({ path }) })
export const migrateDataRoot = (path: string) => apiRequest<SiteTaskResponse>('/api/v1/storage/data-root/migrate', { method: 'POST', body: JSON.stringify({ path }) })
export const migrateSite = (siteId: string, destinationRoot: string) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/migrate`, { method: 'POST', body: JSON.stringify({ destination_root: destinationRoot }) })
export const auditSite = (siteId: string) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/audit`, { method: 'POST' })
export const getLatestSiteAudit = (siteId: string) => apiRequest<SiteAuditSummary>(`/api/v1/sites/${encodeURIComponent(siteId)}/audit/latest`)
export const scanSiteRetention = (siteId: string) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/retention/scan`, { method: 'POST' })
export const getLatestSiteRetention = (siteId: string) => apiRequest<SiteRetentionReport>(`/api/v1/sites/${encodeURIComponent(siteId)}/retention/latest`)
export const applySiteRetention = (siteId: string, scanToken: string, candidateIds: string[]) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/retention/apply`, { method: 'POST', body: JSON.stringify({ scan_token: scanToken, candidate_ids: candidateIds, confirmed: true }) })
export const prepareSiteCleanup = (siteId: string) => apiRequest<SiteCleanupPlan>(`/api/v1/sites/${encodeURIComponent(siteId)}/cleanup/prepare`, { method: 'POST' })
export const applySiteCleanup = (siteId: string, cleanupToken: string) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/cleanup/apply`, { method: 'POST', body: JSON.stringify({ cleanup_token: cleanupToken, confirmed: true }) })
export const rebuildDemoSite = (allowUserData = false) => apiRequest<SiteTaskResponse>('/api/v1/sites/demo/rebuild', { method: 'POST', body: JSON.stringify({ confirmed: true, allow_user_data: allowUserData }) })
