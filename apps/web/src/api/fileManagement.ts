import { apiRequest } from './client'
import type { FileDownloadTask, FileManagementStatus, ManagedFileCategory, ManagedFilePage } from '../types/fileManagement'

const root = '/api/file-management'

function qs(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== '' && value !== null && value !== undefined) params.set(key, String(value))
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function getFileManagementStatus(siteId = ''): Promise<FileManagementStatus> {
  return apiRequest(`${root}/status${qs({ site_id: siteId })}`)
}

export function listManagedFiles(values: { site_id?: string; category?: ManagedFileCategory; search?: string; limit?: number } = {}): Promise<ManagedFilePage> {
  return apiRequest(`${root}/files${qs(values)}`)
}

export function startFileDownload(fileRef: string, siteId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads${qs({ site_id: siteId })}`, { method: 'POST', body: JSON.stringify({ file_ref: fileRef }) })
}

export function getFileDownloadTask(taskId: string, siteId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads/${encodeURIComponent(taskId)}${qs({ site_id: siteId })}`)
}

export function fileDownloadUrl(taskId: string, siteId = ''): string {
  return `${root}/downloads/${encodeURIComponent(taskId)}/file${qs({ site_id: siteId })}`
}
