import { apiRequest } from './client'
import type {
  AcMeshApPage,
  AcMeshMrDetail,
  AcMeshSnapshotDetail,
  AcMeshLinkPage,
  AcMeshLinkQuery,
  AcMeshLinkRefreshResponse,
  AcMeshLinkSummary,
  AcMeshMrPage,
  AcMeshMrQuery,
  AcMeshRawTail,
  AcMeshSnapshotPage,
} from '../types/acMeshLink'

const root = '/api/ac-management/mesh-links'

function queryString(values: Record<string, unknown>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) if (item !== undefined && item !== '') query.append(key, String(item))
    } else if (typeof value === 'boolean') {
      if (value) query.set(key, 'true')
    } else {
      query.set(key, String(value))
    }
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export function getAcMeshLinkSummary(options: RequestInit = {}): Promise<AcMeshLinkSummary> {
  return apiRequest<AcMeshLinkSummary>(`${root}/summary`, options)
}

export function refreshAcMeshLinks(payload: { controller_id: string; include_switch_history?: boolean }): Promise<AcMeshLinkRefreshResponse> {
  return apiRequest<AcMeshLinkRefreshResponse>(`${root}/refresh`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listAcMeshLinks(values: AcMeshLinkQuery, options: RequestInit = {}): Promise<AcMeshLinkPage> {
  return apiRequest<AcMeshLinkPage>(`${root}/current${queryString(values as unknown as Record<string, unknown>)}`, options)
}

export function listAcMeshMrs(values: AcMeshMrQuery, options: RequestInit = {}): Promise<AcMeshMrPage> {
  return apiRequest<AcMeshMrPage>(`${root}/mrs${queryString(values as unknown as Record<string, unknown>)}`, options)
}

export function listAcMeshSnapshots(page = 1, pageSize = 30, options: RequestInit = {}): Promise<AcMeshSnapshotPage> {
  return apiRequest<AcMeshSnapshotPage>(`${root}/snapshots${queryString({ page, page_size: pageSize })}`, options)
}

export function getAcMeshRawTail(snapshotId?: number, limit = 100, options: RequestInit = {}): Promise<AcMeshRawTail> {
  return apiRequest<AcMeshRawTail>(`${root}/raw-tail${queryString({ snapshot_id: snapshotId, limit })}`, options)
}

export function getAcMeshMrDetail(mrId: string, values: { start_time?: string; end_time?: string; page?: number; page_size?: number } = {}, options: RequestInit = {}): Promise<AcMeshMrDetail> {
  return apiRequest<AcMeshMrDetail>(`${root}/mrs/${encodeURIComponent(mrId)}${queryString(values)}`, options)
}
export function listAcMeshPeerAps(values: { query?: string; station?: string; section?: string; page: number; page_size: number }, options: RequestInit = {}): Promise<AcMeshApPage> {
  return apiRequest<AcMeshApPage>(`${root}/peer-aps${queryString(values)}`, options)
}
export function getAcMeshSnapshot(snapshotId: number, options: RequestInit = {}): Promise<AcMeshSnapshotDetail> {
  return apiRequest<AcMeshSnapshotDetail>(`${root}/snapshots/${snapshotId}`, options)
}
