import { apiRequest } from './client'

export interface SiteRecord {
  site_id: string
  display_name: string
  path?: string
  created_at: string
  updated_at: string
  remark: string
  active: boolean
  size_bytes: number
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

export const listSites = () => apiRequest<SiteRecord[]>('/api/v1/sites')
export const getDataRoot = () => apiRequest<DataRootSnapshot>('/api/v1/storage/data-root')
export const createSite = (payload: { site_id: string; display_name: string; remark?: string; activate?: boolean }) => apiRequest<SiteRecord>('/api/v1/sites', { method: 'POST', body: JSON.stringify(payload) })
export const activateSite = (siteId: string) => apiRequest<{ restart_required: boolean }>(`/api/v1/sites/${encodeURIComponent(siteId)}/activate`, { method: 'POST', body: JSON.stringify({ confirmed: true }) })
export const inspectSitePackage = (packagePath: string) => apiRequest<{ site_id: string; site_name: string; file_count: number }>('/api/v1/sites/import/inspect', { method: 'POST', body: JSON.stringify({ package_path: packagePath }) })
export const exportSite = (siteId: string, destinationPath: string) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/export`, { method: 'POST', body: JSON.stringify({ destination_path: destinationPath }) })
export const importSite = (payload: { package_path: string; site_id?: string; display_name?: string; replace_site_id?: string; activate?: boolean }) => apiRequest<SiteTaskResponse>('/api/v1/sites/import', { method: 'POST', body: JSON.stringify(payload) })
export const validateDataRoot = (path: string) => apiRequest<{ valid: boolean; path: string; free_bytes: number }>('/api/v1/storage/data-root/validate', { method: 'POST', body: JSON.stringify({ path }) })
export const migrateDataRoot = (path: string) => apiRequest<SiteTaskResponse>('/api/v1/storage/data-root/migrate', { method: 'POST', body: JSON.stringify({ path }) })
export const migrateSite = (siteId: string, destinationRoot: string) => apiRequest<SiteTaskResponse>(`/api/v1/sites/${encodeURIComponent(siteId)}/migrate`, { method: 'POST', body: JSON.stringify({ destination_root: destinationRoot }) })
