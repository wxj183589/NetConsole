import { apiRequest } from './client'

const root = '/api/system-maintenance'

export interface LogEntry {
  time: string
  level: string
  display_level: string
  display_event: string
  display_detail: string
  raw_event: string
  raw_detail: string
}

export interface LogPage {
  items: LogEntry[]
  page: number
  page_size: 50 | 100 | 200 | 500
  total: number
  total_pages: number
}

export type CleanupItemId = 'runtime_logs' | 'runtime_cache' | 'temporary_files'

export interface CleanupItem {
  item_id: CleanupItemId
  title: string
  description: string
  retention_policy: string
  status: string
  file_count: number
  total_bytes: number
}

export interface OpenSourceComponent {
  name: string
  version: string
  license: string
  purpose: string
  homepage: string
  note: string
}

export interface MaintenanceTask {
  task_id: string
  status: string
  action: string
  progress: number
  stage: string
  message: string
  error_message: string
  artifact_id: string
  artifact_kind: string
  artifact_name: string
  available: boolean
  sha256: string
  size_bytes: number
  cleanup_items: CleanupItem[]
  processed_files: number
  deleted_files: number
  failed_count: number
  freed_bytes: number
  components: OpenSourceComponent[]
}

export interface Changelog {
  title: string
  version: string
  content: string
}

export interface AboutInfo {
  title: string
  version: string
  author: string
  external_tool_notice: string
  repositories: Array<{ link_id: string; label: string }>
}

export function getLogs(query: { page: number; page_size: number; keyword: string; level: string }): Promise<LogPage> {
  return apiRequest<LogPage>(`${root}/logs?${new URLSearchParams(Object.entries(query).map(([key, value]) => [key, String(value)]))}`)
}

export function clearLogs(): Promise<{ success: boolean; code: string; message: string }> {
  return apiRequest(`${root}/logs`, { method: 'DELETE' })
}

export function startCleanup(payload: {
  mode: 'scan' | 'clean'
  retention_days: number
  selected_item_ids?: CleanupItemId[]
  confirmed?: boolean
}): Promise<MaintenanceTask> {
  return apiRequest(`${root}/cleanup/tasks`, { method: 'POST', body: JSON.stringify(payload) })
}

export function startOpenSourceScan(): Promise<MaintenanceTask> {
  return apiRequest(`${root}/open-source/tasks`, { method: 'POST', body: '{}' })
}

export function startLogExport(payload: {
  scope: 'current' | 'all'
  keyword: string
  level: string
  page: number
  page_size: number
}): Promise<MaintenanceTask> {
  return apiRequest(`${root}/exports/logs`, { method: 'POST', body: JSON.stringify(payload) })
}

export function startOpenSourceExport(format: 'txt' | 'xlsx'): Promise<MaintenanceTask> {
  return apiRequest(`${root}/exports/open-source`, { method: 'POST', body: JSON.stringify({ format }) })
}

export function getMaintenanceTask(taskId: string): Promise<MaintenanceTask> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}`)
}

export function recoverMaintenanceTasks(): Promise<MaintenanceTask[]> {
  return apiRequest(`${root}/tasks`)
}

export function cancelMaintenanceTask(taskId: string): Promise<MaintenanceTask> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST', body: '{}' })
}

export function getChangelog(): Promise<Changelog> {
  return apiRequest(`${root}/changelog`)
}

export function getAbout(): Promise<AboutInfo> {
  return apiRequest(`${root}/about`)
}

export function requestAboutLink(linkId: string): Promise<{ url: string }> {
  return apiRequest(`${root}/links/about/${encodeURIComponent(linkId)}`, { method: 'POST', body: '{}' })
}

export function requestOpenSourceLink(taskId: string, componentIndex: number): Promise<{ url: string }> {
  return apiRequest(`${root}/links/open-source/${encodeURIComponent(taskId)}/${componentIndex}`, { method: 'POST', body: '{}' })
}

export function openMaintenanceDirectory(kind: 'logs' | 'cache'): Promise<{ success: boolean; code: string; message: string }> {
  return apiRequest(`${root}/desktop-actions/open-directory/${kind}`, { method: 'POST', body: '{}' })
}

export function maintenanceArtifactDownloadRequest(task: MaintenanceTask): { apiPath: string; suggestedName: string } {
  return {
    apiPath: `${root}/artifacts/${encodeURIComponent(task.artifact_kind)}/${encodeURIComponent(task.artifact_id)}`,
    suggestedName: task.artifact_name,
  }
}
