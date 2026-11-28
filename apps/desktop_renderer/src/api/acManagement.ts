import { apiRequest } from './client'
import type {
  AcApDetail,
  AcApHistoryPage,
  AcApPage,
  AcApQuery,
  AcCurrentLldp,
  AcConfigContent,
  AcConfigDiff,
  AcConfigSnapshotPage,
  AcManagementSummary,
} from '../types/acManagement'

const root = '/api/ac-management'

function queryString(values: object): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values as Record<string, string | number | readonly string[] | undefined>)) {
    if (Array.isArray(value)) {
      for (const selection of value) if (selection) query.append(key, selection)
    } else if (value !== undefined && value !== '') {
      query.set(key, String(value))
    }
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export function getAcSummary(): Promise<AcManagementSummary> {
  return apiRequest<AcManagementSummary>(`${root}/summary`)
}

export type AcController = Pick<AcManagementSummary['acs'][number],
  'id' | 'name' | 'management_ip' | 'model' | 'software_version' | 'updated_at'>

export function listAcControllers(site: string, options: RequestInit = {}): Promise<AcController[]> {
  return apiRequest<AcController[]>(`${root}/controllers${queryString({ expected_site: site })}`, options)
}

export interface AcDeployment {
  name: string
  mode: 'standalone' | 'stack' | 'cluster' | 'one_plus_one'
  members: string[]
}
export interface AcDeployments {
  site_id: string
  revision: number
  groups: AcDeployment[]
}
export function getAcDeployments(options: RequestInit = {}): Promise<AcDeployments> {
  return apiRequest(`${root}/deployments`, options)
}
export function saveAcDeployments(value: AcDeployments): Promise<AcDeployments> {
  return apiRequest(`${root}/deployments`, { method: 'PUT', body: JSON.stringify(value) })
}

export function listAcAps(values: AcApQuery): Promise<AcApPage> {
  return apiRequest<AcApPage>(`${root}/aps${queryString(values)}`)
}

export function getAcApDetail(apId: string): Promise<AcApDetail> {
  return apiRequest<AcApDetail>(`${root}/aps/${encodeURIComponent(apId)}`)
}

export function getAcApRecentChanges(
  apId: string,
  kind: 'radio' | 'lldp' | 'optical',
  page = 1,
  pageSize = 10,
): Promise<AcApHistoryPage> {
  return apiRequest<AcApHistoryPage>(
    `${root}/aps/${encodeURIComponent(apId)}/history/${kind}${queryString({ page, page_size: pageSize })}`,
  )
}

export function getAcApCurrentLldp(apId: string): Promise<AcCurrentLldp[]> {
  return apiRequest<AcCurrentLldp[]>(`${root}/aps/${encodeURIComponent(apId)}/lldp/current`)
}

export function listAcConfigSnapshots(values: {
  ac_id?: string
  type?: string
  page: number
  page_size: number
}): Promise<AcConfigSnapshotPage> {
  return apiRequest<AcConfigSnapshotPage>(`${root}/config-snapshots${queryString(values)}`)
}

export function getAcConfigSnapshot(snapshotId: number, offset = 0): Promise<AcConfigContent> {
  return apiRequest<AcConfigContent>(
    `${root}/config-snapshots/${snapshotId}${queryString({ offset, limit: 100000 })}`,
  )
}

export function getAcConfigDiff(snapshotId: number): Promise<AcConfigDiff> {
  return apiRequest<AcConfigDiff>(`${root}/config-snapshots/${snapshotId}/diff`)
}
