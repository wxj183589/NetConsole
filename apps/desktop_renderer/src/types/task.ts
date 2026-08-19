export type TaskStatus =
  | 'PENDING'
  | 'STARTING'
  | 'RUNNING'
  | 'STOPPING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'CREATED'
  | 'QUEUED'
  | 'ABORTED'
  | 'STOPPED'
  | 'WARNING'
  | 'UNKNOWN'

export interface TaskItem {
  id: string
  type: string
  name: string
  status: TaskStatus
  lifecycle_status?: string
  business_status?: string
  success_count?: number
  failed_count?: number
  skipped_count?: number
  warning_count?: number
  partial_success?: boolean
  primary_failure_reason?: string
  progress: number
  current?: number
  total?: number
  task_mode?: 'once' | 'resident'
  progress_mode?: 'percentage' | 'indeterminate'
  phase: string
  stage: string
  message: string
  site_name: string
  owner: string
  executor: string
  source: string
  device_id: string
  device_name: string
  agent: string
  mr_name: string
  session_id: string
  mapping_state: string
  created_time: string
  started_time: string
  finished_time: string
  expires_at?: string
  acknowledged_at?: string
  dismissed_at?: string
  updated_time: string
  duration_seconds: number
  error_code: string
  error_summary: string
  has_warning: boolean
  text_integrity?: 'ok' | 'historical_corrupted' | 'current_corrupted' | 'unknown_corrupted'
  text_integrity_reason?: string
  text_integrity_updated_at?: string
  text_schema_version?: number
  producer_kind?: 'local_worker' | 'local_backend' | 'agent' | 'imported' | 'legacy'
  producer_version?: string
  producer_commit?: string
  snapshot_id: number | null
  records_count: number | null
  parser_version: string
  module?: string
  cancellable?: boolean
  cancel_reason?: string
  retryable?: boolean
  retry_reason?: string
  artifact_download?: {
    artifact_id: string
    display_name: string
    size_bytes: number
    sha256?: string
    media_type: string
    api_path: string
    query: Record<string, string>
  } | null
  artifact_reason?: string
  artifact_available?: boolean
  artifact_availability?: 'AVAILABLE' | 'MISSING' | 'INVALID' | 'NOT_APPLICABLE'
  missing_reason?: string | null
  downloadable?: boolean
  openable?: boolean
  parent_directory_openable?: boolean
  details?: Record<string, unknown>
}

export interface TaskLogLine {
  sequence: number
  time: string
  level: string
  type: string
  source: string
  message: string
  details?: Record<string, unknown>
}

export interface TaskLogTail {
  task_id: string
  lines: TaskLogLine[]
  message: string
}

export interface TaskSummary {
  total: number
  active: number
  completed: number
  failed: number
  warning: number
  unacknowledged_failed: number
  unacknowledged_warning: number
}

export type TaskCleanupType =
  | 'completed'
  | 'cancelled'
  | 'expired'
  | 'completed_and_expired'
  | 'resolved_alerts'
  | 'all_history'
  | 'bounded_retention'

export interface TaskCleanupCounts {
  completed: number
  cancelled: number
  expired: number
  alerts: number
}

export interface TaskCleanupResult {
  matched: number
  dismissed: number
  deleted?: number
  retained?: number
  protected?: number
  skipped_active: number
  skipped_unacknowledged: number
  artifacts_deleted: number
  task_ids: string[]
  counts: TaskCleanupCounts
}

export interface TaskAcknowledgeResult {
  acknowledged: number
  task_ids: string[]
  acknowledged_at: string
}
