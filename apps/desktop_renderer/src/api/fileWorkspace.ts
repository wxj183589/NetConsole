import { apiRequest } from './client'

export type FileRoot = 'downloads' | 'tftp' | 'ftp' | 'http' | 'https'
export interface WorkspaceEntry { id: string; name: string; directory: boolean; size: number | null; modified: number; mode: string }
export interface WorkspaceDirectory { kind: FileRoot; directory_id: string; parent_id: string; label: string; writable: boolean; items: WorkspaceEntry[] }
export interface WorkspaceFileTask { task_id: string; action: string; status: string; current: number; total: number; sha256: string; error: string }
const base = '/api/file-management/workspace'

export function browseFileWorkspace(kind: FileRoot, directoryId = ''): Promise<WorkspaceDirectory> {
  return apiRequest(`${base}/entries?${new URLSearchParams({ kind, directory_id: directoryId })}`, { coalesce: false })
}
export function operateFileWorkspace(body: { action: 'copy' | 'move' | 'rename' | 'delete' | 'mkdir' | 'checksum' | 'archive'; source?: string; destination?: string; name?: string; overwrite?: boolean; expected_sha256?: string }): Promise<WorkspaceFileTask> {
  return apiRequest(`${base}/operations`, { method: 'POST', body: JSON.stringify(body) })
}
export function listFileWorkspaceTasks(): Promise<{ items: WorkspaceFileTask[] }> {
  return apiRequest(`${base}/operations`, { coalesce: false })
}
export function cancelFileWorkspaceTask(id: string): Promise<WorkspaceFileTask> {
  return apiRequest(`${base}/operations/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}
export function workspaceFileRequest(entry: WorkspaceEntry) {
  return { apiPath: `${base}/files/${encodeURIComponent(entry.id)}`, suggestedName: entry.name }
}
export function previewWorkspaceFile(entryId: string): Promise<{ name: string; text: string; truncated: boolean }> {
  return apiRequest(`${base}/files/${encodeURIComponent(entryId)}/preview`)
}
export function uploadFileWorkspace(destination: string, file: File): Promise<WorkspaceFileTask> {
  const body = new FormData()
  body.set('destination', destination)
  body.set('file', file)
  return apiRequest(`${base}/upload`, { method: 'POST', body })
}
