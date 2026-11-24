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
}

export interface Infrastructure {
  site_id: string
  site_name: string
  line_name: string
  schema_available: boolean
  device_count: number
  unassociated_device_count: number
  unresolved_binding_count: number
  nodes: InfrastructureNode[]
  unassociated_devices: InfrastructureDevice[]
}

export interface InfrastructureSwitchAps {
  items: Pick<TracksideApBusinessRow, 'row_id' | 'ap_uuid' | 'ap_name' | 'interface_name' | 'link_status'>[]
  total: number
  page: number
  page_size: number
}

const root = '/api/rail-transit/infrastructure'

export function getInfrastructure(siteId: string, signal: AbortSignal): Promise<Infrastructure> {
  return apiRequest(`${root}?${new URLSearchParams({ site_id: siteId })}`, { signal })
}

export function getInfrastructureSwitchAps(siteId: string, deviceUuid: string, page: number, signal: AbortSignal): Promise<InfrastructureSwitchAps> {
  const query = new URLSearchParams({ site_id: siteId, device_uuid: deviceUuid, page: String(page) })
  return apiRequest(`${root}/switch-aps?${query}`, { signal })
}
