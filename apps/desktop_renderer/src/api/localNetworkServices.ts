import { apiRequest } from './client'

export interface LocalServiceConfig {
  address: string
  port: number
  max_connections: number
  timeout: number
  log_level: 'INFO' | 'WARNING'
  allow_upload: boolean
  dns_records: Record<string, string>
}

export interface LocalService {
  id: string
  group: string
  source: string
  status: string
  available: boolean
  installed: boolean
  dependency: string
  transport: string
  error_code: string
  config: LocalServiceConfig | null
  root: string | null
  listeners?: { address: string; port: number; transport: string }[]
  session_credential?: { username: string; password: string }
}

export type LocalServiceAction = 'initialize' | 'start' | 'stop' | 'restart'

const path = '/api/local-network-services'

export function listLocalServices() {
  return apiRequest<{ services: LocalService[]; addresses: Record<string, string> }>(path)
}

export function configureLocalService(id: string, config: LocalServiceConfig) {
  return apiRequest<LocalService>(`${path}/${id}/config`, { method: 'PUT', body: JSON.stringify(config) })
}

export function runLocalServiceAction(id: string, action: LocalServiceAction) {
  return apiRequest<LocalService>(`${path}/${id}/actions/${action}`, { method: 'POST' })
}

export function readLocalServiceLogs(id: string) {
  return apiRequest<{ lines: string[] }>(`${path}/${id}/logs`)
}
