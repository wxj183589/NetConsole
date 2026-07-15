import { apiRequest } from './client'
import type {
  ConfigDevicePage,
  ConfigDirectory,
  ConfigSnapshot,
  ConfigTaskReference,
  ConfigTaskStatus,
} from '../types/configCollection'

const root = '/api/config-collection'

function queryString(values: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export function listConfigDevices(values: {
  search?: string
  group_filter?: string
  page?: number
  page_size?: number
} = {}): Promise<ConfigDevicePage> {
  return apiRequest<ConfigDevicePage>(`${root}/devices${queryString(values)}`)
}

export function listConfigSnapshots(deviceId: number, type = ''): Promise<ConfigSnapshot[]> {
  return apiRequest<ConfigSnapshot[]>(
    `${root}/devices/${deviceId}/snapshots${queryString({ type })}`,
  )
}

export function submitConfigCollection(deviceIds: number[]): Promise<ConfigTaskReference[]> {
  return apiRequest<ConfigTaskReference[]>(`${root}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action: 'fetch', device_ids: deviceIds }),
  })
}

export function submitSnapshotContent(snapshotId: number): Promise<ConfigTaskReference> {
  return apiRequest<ConfigTaskReference>(`${root}/snapshots/${snapshotId}/content`, { method: 'POST' })
}

export function submitLatestConfigDiff(deviceId: number): Promise<ConfigTaskReference> {
  return apiRequest<ConfigTaskReference>(`${root}/devices/${deviceId}/diff/latest`, { method: 'POST' })
}

export function submitSnapshotConfigDiff(leftSnapshotId: number, rightSnapshotId: number): Promise<ConfigTaskReference> {
  return apiRequest<ConfigTaskReference>(`${root}/diff/snapshots`, {
    method: 'POST',
    body: JSON.stringify({ left_snapshot_id: leftSnapshotId, right_snapshot_id: rightSnapshotId }),
  })
}

export function submitDeviceConfigDiff(leftDeviceId: number, rightDeviceId: number): Promise<ConfigTaskReference> {
  return apiRequest<ConfigTaskReference>(`${root}/diff/devices`, {
    method: 'POST',
    body: JSON.stringify({ left_device_id: leftDeviceId, right_device_id: rightDeviceId }),
  })
}

export function submitSnapshotDelete(snapshotIds: number[]): Promise<ConfigTaskReference> {
  return apiRequest<ConfigTaskReference>(`${root}/snapshots/delete`, {
    method: 'POST',
    body: JSON.stringify({ snapshot_ids: snapshotIds }),
  })
}

export function listConfigTasks(limit = 100): Promise<ConfigTaskStatus[]> {
  return apiRequest<ConfigTaskStatus[]>(`${root}/tasks${queryString({ limit })}`)
}

export function getConfigTask(taskId: string, diffFilter = 'all'): Promise<ConfigTaskStatus> {
  return apiRequest<ConfigTaskStatus>(`${root}/tasks/${encodeURIComponent(taskId)}${queryString({ diff_filter: diffFilter === 'all' ? undefined : diffFilter })}`)
}

export function cancelConfigTask(taskId: string): Promise<ConfigTaskStatus> {
  return apiRequest<ConfigTaskStatus>(`${root}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function getConfigDirectory(directoryKind = 'config_exports'): Promise<ConfigDirectory> {
  return apiRequest<ConfigDirectory>(`${root}/directory${queryString({ directory_kind: directoryKind })}`)
}

export function configArtifactUrl(artifactId: string): string {
  return `${root}/artifacts/${encodeURIComponent(artifactId)}`
}
