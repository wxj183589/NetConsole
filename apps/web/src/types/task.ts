export type TaskStatus =
  | 'PENDING'
  | 'STARTING'
  | 'RUNNING'
  | 'STOPPING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export interface TaskItem {
  id: string
  type: string
  name: string
  status: TaskStatus
  progress: number
  stage: string
  current: number
  total: number
  message: string
  created_time: string
  started_time: string
  finished_time: string
  updated_time: string
  owner: string
  device: string
  agent: string
  result_path: string
  error_message: string
  result: Record<string, unknown>
  source: string
  cancellable: boolean
}

export interface TaskEvent {
  sequence: number
  id: string
  task_id: string
  type: string
  time: string
  source: string
  payload: Record<string, unknown>
}

export interface TaskSocketEvent {
  id?: string
  task_id?: string
  type: string
  time?: string
  source?: string
  payload?: Record<string, unknown> & { tasks?: TaskItem[] }
}
