import { apiRequest } from './client'
import type {
  FileConnection,
  FileDesktopAction,
  FileDownloadBatch,
  FileDownloadTask,
  FileManagementStatus,
  FileRemoteDevice,
  LocalFilePage,
  ManagedFileCategory,
  ManagedFilePage,
  RemoteFilePage,
} from '../types/fileManagement'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

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

export function listLocalFiles(values: { site_id?: string; directory_id?: string; device_id?: string; page?: number; limit?: number } = {}): Promise<LocalFilePage> {
  return apiRequest(`${root}/local/entries${qs(values)}`)
}

export function createLocalDirectory(values: { site_id?: string; directory_id?: string; device_id?: string; name: string }): Promise<LocalFilePage> {
  const { site_id, ...body } = values
  return apiRequest(`${root}/local/directories${qs({ site_id })}`, { method: 'POST', body: JSON.stringify(body) })
}

export function connectDeviceFiles(deviceId: string, siteId = '', allowSftpSetup = false): Promise<FileConnection> {
  return apiRequest(`${root}/connections${qs({ site_id: siteId })}`, {
    method: 'POST',
    body: JSON.stringify({ device_id: deviceId, allow_sftp_setup: allowSftpSetup }),
  })
}

export function trustDeviceHostKey(
  challengeId: string,
  persist: boolean,
  siteId = '',
  allowSftpSetup = false,
): Promise<FileConnection> {
  const path = persist ? `${root}/host-keys/trust` : `${root}/host-keys/trust-once`
  return apiRequest(path + qs({ site_id: siteId }), {
    method: 'POST',
    body: JSON.stringify({ challenge_id: challengeId, allow_sftp_setup: allowSftpSetup }),
  })
}

export function disconnectDeviceFiles(connectionId: string, siteId = ''): Promise<FileConnection> {
  return apiRequest(`${root}/connections/${encodeURIComponent(connectionId)}${qs({ site_id: siteId })}`, { method: 'DELETE' })
}

export function listRemoteFiles(connectionId: string, entryId = '', siteId = '', page = 1, limit = 500): Promise<RemoteFilePage> {
  return apiRequest(`${root}/connections/${encodeURIComponent(connectionId)}/entries${qs({ entry_id: entryId, site_id: siteId, page, limit })}`)
}

export function startRemoteFileDownload(connectionId: string, remoteEntryId: string, siteId = '', localDirectoryId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads${qs({ site_id: siteId })}`, {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId, remote_entry_id: remoteEntryId, local_directory_id: localDirectoryId }),
  })
}

export function startRemoteFileDownloadBatch(
  connectionId: string,
  remoteEntryIds: string[],
  siteId = '',
  localDirectoryId = '',
): Promise<FileDownloadBatch> {
  return apiRequest(`${root}/downloads/batch${qs({ site_id: siteId })}`, {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId, remote_entry_ids: remoteEntryIds, local_directory_id: localDirectoryId }),
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

export function retryFileDownload(taskId: string, siteId = ''): Promise<FileDownloadTask> {
  return apiRequest(`${root}/downloads/${encodeURIComponent(taskId)}/retry${qs({ site_id: siteId })}`, { method: 'POST' })
}

export function clearFileDownloads(statuses: Array<'COMPLETED' | 'FAILED'>, siteId = ''): Promise<{ cleared_count: number }> {
  return apiRequest(`${root}/downloads/clear${qs({ site_id: siteId })}`, {
    method: 'POST',
    body: JSON.stringify({ statuses }),
  })
}

export function listRemoteDevices(siteId = ''): Promise<FileRemoteDevice[]> {
  return apiRequest(`${root}/devices${qs({ site_id: siteId })}`)
}

export function fileDownloadRequest(
  taskId: string,
  siteId: string,
  suggestedName: string,
): BackendDownloadRequest {
  return {
    apiPath: `${root}/downloads/${encodeURIComponent(taskId)}/file`,
    ...(siteId ? { query: { site_id: siteId } } : {}),
    suggestedName,
  }
}

export function localFileDownloadRequest(entryId: string, siteId: string, suggestedName: string): BackendDownloadRequest {
  return {
    apiPath: `${root}/local/entries/${encodeURIComponent(entryId)}/file`,
    ...(siteId ? { query: { site_id: siteId } } : {}),
    suggestedName,
  }
}

export function prepareFileDesktopAction(
  action: 'winscp' | 'open_local' | 'open_result_dir',
  values: { site_id?: string; device_id?: string; local_entry_id?: string; task_id?: string },
): Promise<FileDesktopAction> {
  const { site_id, ...body } = values
  return apiRequest(`${root}/desktop-actions/${action}${qs({ site_id })}`, { method: 'POST', body: JSON.stringify(body) })
}
