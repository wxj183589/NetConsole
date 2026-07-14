import { apiRequest } from './client'
import type {
  AcMeshLinkPage,
  AcMeshLinkQuery,
  AcMeshLinkSummary,
  AcMeshMrDetail,
  AcMeshMrPage,
  AcMeshMrQuery,
  AcMeshRawTail,
  AcMeshSnapshotPage,
} from '../types/acMeshLink'

const root = '/api/ac-management/mesh-links'

function queryString(values: object): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values as Record<string, string | number | boolean | undefined>)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export function getMeshLinkSummary(): Promise<AcMeshLinkSummary> {
  return apiRequest<AcMeshLinkSummary>(`${root}/summary`)
}

export function listMeshLinks(values: AcMeshLinkQuery): Promise<AcMeshLinkPage> {
  return apiRequest<AcMeshLinkPage>(`${root}/current${queryString(values)}`)
}

export function listMeshMrs(values: AcMeshMrQuery): Promise<AcMeshMrPage> {
  return apiRequest<AcMeshMrPage>(`${root}/mrs${queryString(values)}`)
}

export function getMeshMrDetail(mrId: string): Promise<AcMeshMrDetail> {
  return apiRequest<AcMeshMrDetail>(`${root}/mrs/${encodeURIComponent(mrId)}`)
}

export function listMeshSnapshots(page = 1, pageSize = 30): Promise<AcMeshSnapshotPage> {
  return apiRequest<AcMeshSnapshotPage>(`${root}/snapshots${queryString({ page, page_size: pageSize })}`)
}

export function getMeshRawTail(snapshotId?: number): Promise<AcMeshRawTail> {
  return apiRequest<AcMeshRawTail>(`${root}/raw-tail${queryString({ snapshot_id: snapshotId, limit: 300 })}`)
}
