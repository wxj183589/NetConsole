import { apiRequest } from './client'
import type {
  FileConnection,
  FileDesktopAction,
  FileDownloadTask,
  FileManagementStatus,
  ManagedFileCategory,
  ManagedFilePage,
  RemoteFilePage,
} from '../types/fileManagement'

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

export function connectDeviceFiles(deviceId: string, siteId = ''): Promise<FileConnection> {
  return apiRequest(`${root}/connections${qs({ site_id: siteId })}`, { method: 'POST', body: JSON.stringify({ device_id: deviceId }) })
}

export function disconnectDeviceFiles(connectionId: string, siteId = ''): Promise<FileConnection> {
  return apiRequest(`${root}/connections/${encodeURIComponent(connectionId)}${qs({ site_id: siteId })}`, { method: 'DELETE' })
}

export function listRemoteFiles(connectionId: string, entryId = '', siteId = ''): Promise<RemoteFilePage> {
  return apiRequest(`${root}/connections/${encodeURIComponent(connectionId)}/entries${qs({ entry_id: entryId, site_id: siteId })}`)
}

export function startRemoteFileDownload(connectionId: string, remoteEntryId: string, siteId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads${qs({ site_id: siteId })}`, {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId, remote_entry_id: remoteEntryId }),
  })
}

export function listFileDownloads(siteId = '', limit = 100): Promise<FileDownloadTask[]> {
  return apiRequest(`${root}/downloads${qs({ site_id: siteId, limit })}`)
}

export function getFileDownloadTask(taskId: string, siteId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads/${encodeURIComponent(taskId)}${qs({ site_id: siteId })}`)
}

export function cancelFileDownload(taskId: string, siteId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads/${encodeURIComponent(taskId)}/cancel${qs({ site_id: siteId })}`, { method: 'POST' })
}

export function requestWinScp(deviceId: string, siteId = ''): Promise<FileDesktopAction> {
  return apiRequest(`${root}/desktop-actions/winscp${qs({ site_id: siteId })}`, { method: 'POST', body: JSON.stringify({ device_id: deviceId }) })
}

export function requestOpenResultDirectory(artifactId: string): Promise<FileDesktopAction> {
  return apiRequest(`${root}/desktop-actions/open-result-directory`, { method: 'POST', body: JSON.stringify({ artifact_id: artifactId }) })
}

export function fileDownloadUrl(taskId: string, siteId = ''): string {
  return `${root}/downloads/${encodeURIComponent(taskId)}/file${qs({ site_id: siteId })}`
}
