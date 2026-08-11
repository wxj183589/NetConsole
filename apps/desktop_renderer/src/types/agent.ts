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

export interface AgentRemoteStatus {
  agent_id: string
  agent_name: string
  version: string
  os: string
  arch: string
  listen: string
  uptime: string
  current_tasks: number
  task_count: number
  package_count: number
  data_dir: string
  package_dir: string
  power: Record<string, unknown>
  disk: Record<string, unknown>
}

export interface AgentToolStatus {
  exists: boolean
  ready: boolean
  path: string
  work_dir: string
  version: string
  warning: string
  required_files: Array<{ name: string; exists: boolean }>
}

export interface AgentToolsStatus {
  iperf3: AgentToolStatus
  fping: AgentToolStatus
  mr_collector: AgentToolStatus
}

export interface AgentRemoteTask {
  task_id: string
  task_type: string
  status: string
  created_at: string | null
  start_time: string | null
  end_time: string | null
  package_id: string
  package_download_url: string
  error_code: string
  error_message: string
  params: Record<string, unknown>
}

export interface AgentRemoteTaskLogs {
  task_id: string
  lines: string[]
}

export interface AgentRemotePackage {
  package_id: string
  task_id: string
  task_type: string
  start_time: string
  end_time: string
  size: number
  package_download_url: string
}
