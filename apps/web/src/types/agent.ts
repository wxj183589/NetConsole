export type AgentStatus = 'UNKNOWN' | 'ONLINE' | 'OFFLINE' | 'UNAUTHORIZED' | 'DISABLED'
export type AgentAuthenticationType = 'none' | 'token'

export interface AgentItem {
  agent_id: string
  name: string
  base_url: string
  enabled: boolean
  authentication_type: AgentAuthenticationType
  has_credential: boolean
  tags: string[]
  note: string
  created_at: string
  updated_at: string
  status: AgentStatus
  last_seen_at: string
  last_checked_at: string
  latency_ms: number | null
  version: string
  platform: string
  architecture: string
  capabilities: Record<string, unknown>
  last_error_code: string
  last_error_message: string
}

export interface AgentFormValue {
  name: string
  base_url: string
  enabled: boolean
  authentication_type: AgentAuthenticationType
  token?: string
  tags: string[]
  note: string
}

export interface AgentProbeResult {
  remote_agent_id: string
  remote_name: string
  version: string
  platform: string
  architecture: string
  capabilities: Record<string, unknown>
  latency_ms: number
}

export interface AgentSocketEvent {
  type: string
  agent_id?: string
  agents?: AgentItem[]
}
