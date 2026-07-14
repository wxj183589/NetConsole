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
  progress: number
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
  updated_time: string
  duration_seconds: number
  error_code: string
  error_summary: string
  has_warning: boolean
  result_path: string
  output_dir: string
  package_path: string
  session_path: string
}

export interface TaskLogLine {
  sequence: number
  time: string
  level: string
  type: string
  source: string
  message: string
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
}
