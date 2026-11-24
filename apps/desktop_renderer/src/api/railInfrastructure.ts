import { apiRequest } from './client'
import type { Section, Station } from '../types/railTransitBaseData'
import type { TracksideApBusinessRow } from '../types/tracksideApBusiness'

export interface InfrastructureDevice {
  device_uuid: string
  name: string
  vendor?: string
  platform?: string
  device_type: string
  device_role: string
  role: string
  section_uid: string | null
  source: 'engineering' | 'legacy_station'
}

export interface InfrastructureNode {
  uid: string
  kind: 'station' | 'depot' | 'parking_yard' | 'cocc' | 'bocc' | 'train' | 'section'
  code: string
  name: string
  source: 'engineering' | 'legacy_station' | 'legacy_train'
  station: Station | null
  aliases: { name: string; name_type: string; source: string; valid_from: string | null; valid_to: string | null }[]
  projects: { project_id: string; name: string; stage: string }[]
  devices: InfrastructureDevice[]
  sections: Section[]
  ac_service_stations: string[]
  parent_uid?: string
  sort_order?: number
  custom?: boolean
}

export interface Infrastructure {
  site_id: string
  site_name: string
  line_name: string
  schema_available: boolean
  organization_initialized?: boolean
  organization_writable?: boolean
  device_count: number
  unassociated_device_count: number
  unresolved_binding_count: number
  nodes: InfrastructureNode[]
  unassociated_devices: InfrastructureDevice[]
}

export interface InfrastructureSwitchAps {
  items: (Pick<TracksideApBusinessRow, 'row_id' | 'ap_uuid' | 'ap_name' | 'interface_name' | 'link_status'> & {
    identity_match_status?: string
    recognition_status?: string
    primary_reason_label?: string
    section_ids?: string[]
  })[]
  total: number
  page: number
  page_size: number
  partial_data?: boolean
  unavailable_sources?: string[]
}

const root = '/api/rail-transit/infrastructure'

export function getInfrastructure(siteId: string, signal: AbortSignal): Promise<Infrastructure> {
  return apiRequest(`${root}?${new URLSearchParams({ site_id: siteId })}`, { signal })
}

export function initializeInfrastructure(siteId: string, signal: AbortSignal): Promise<Infrastructure> {
  return apiRequest(`${root}/initialize?${new URLSearchParams({ site_id: siteId })}`, { method: 'POST', signal })
}

export interface OrganizationAsset {
  device_uuid: string
  name: string
  address: string
  mac: string
  serial: string
  device_type: string
  group_name: string
  node_uids: string[]
  project_ids: string[]
  collection: 'included' | 'excluded'
}

export interface OrganizationCatalog {
  revision: string
  devices: OrganizationAsset[]
  projects: InfrastructureNode['projects']
}

export interface OrganizationBatch {
  revision: string
  device_uuids: string[]
  node_uid: string
  collection: OrganizationAsset['collection'] | null
  add_projects: string[]
  remove_projects: string[]
  explicit_confirmation?: boolean
}

export interface OrganizationBatchResult {
  revision: string
  changes: { before: OrganizationAsset; after: OrganizationAsset }[]
}

export function getOrganizationCatalog(siteId: string): Promise<OrganizationCatalog> {
  return apiRequest(`${root}/organization-catalog?${new URLSearchParams({ site_id: siteId })}`)
}

export function changeOrganizationAssets(siteId: string, batch: OrganizationBatch, action: 'preview' | 'apply'): Promise<OrganizationBatchResult> {
  return apiRequest(`${root}/organization-assets/${action}?${new URLSearchParams({ site_id: siteId })}`, {
    method: 'POST', body: JSON.stringify(batch),
  })
}

export type OrganizationNodeKind = Exclude<InfrastructureNode['kind'], 'train' | 'section'>

export interface OrganizationNodeEdit {
  node_uid: string
  parent_uid: string
  kind: OrganizationNodeKind
  name: string
  code: string
  sort_order: number
}

export function saveOrganizationNode(siteId: string, draft: OrganizationNodeEdit, revision: string): Promise<{ node_uid: string }> {
  return apiRequest(`${root}/organization-nodes?${new URLSearchParams({ site_id: siteId })}`, {
    method: 'POST', body: JSON.stringify({ ...draft, revision, explicit_confirmation: true }),
  })
}

export function getInfrastructureSwitchAps(siteId: string, deviceUuid: string, page: number, signal: AbortSignal): Promise<InfrastructureSwitchAps> {
  const query = new URLSearchParams({ site_id: siteId, device_uuid: deviceUuid, page: String(page) })
  return apiRequest(`${root}/switch-aps?${query}`, { signal })
}
