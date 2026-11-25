import { apiRequest } from './client'

export interface LocalServiceConfig {
  address: string
  port: number
  max_connections: number
  timeout: number
  log_level: 'INFO' | 'WARNING'
  allow_upload: boolean
  tls_enabled: boolean
  auto_restart: boolean
  ftp_username?: string
  passive_ports?: [number, number] | null
  dns_records: Record<string, string>
}

export interface LocalService {
  id: string
  group: string
  source: string
  status: string
  available: boolean
  installed: boolean
  capabilities?: {
    ssh_client: boolean
    sftp_client: boolean
    ssh_server: boolean
    sftp_server: boolean
    service_state: string
    pid: number | null
    listeners: { LocalAddress: string; LocalPort: number }[]
    version: string | null
  }
  dependency: string
  transport: string
  error_code: string
  enabled: boolean
  pid: number | null
  process_owner: string
  started_at: string
  uptime_seconds: number
  health: string
  cpu_percent: number | null
  memory_bytes: number | null
  restart_attempts: number
  tls_supported: boolean
  certificate_fingerprint: string
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

export interface ServiceLogEntry {
  index: number
  time: string
  level: string
  message: string
  raw: string
}

export function readLocalServiceLogs(id: string, query: { keyword?: string; level?: string; since?: string; until?: string; history?: boolean } = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, String(value))
  }
  const suffix = params.size ? `?${params}` : ''
  return apiRequest<{ lines: string[]; entries: ServiceLogEntry[]; bounded_tail: boolean; scanned_lines: number; history: boolean; line_limit: number }>(`${path}/${id}/logs${suffix}`)
}
