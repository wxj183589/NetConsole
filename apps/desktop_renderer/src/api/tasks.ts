import { apiRequest } from './client'
import type {
  TaskAcknowledgeResult,
  TaskCleanupResult,
  TaskCleanupType,
  TaskItem,
  TaskLogTail,
  TaskSummary,
} from '../types/task'

export function listTasks(): Promise<TaskItem[]> {
  return apiRequest<TaskItem[]>('/api/job-center/tasks')
}

export function getTask(id: string): Promise<TaskItem> {
  return apiRequest<TaskItem>(`/api/job-center/tasks/${encodeURIComponent(id)}`)
}

export function getTaskLogs(id: string, tail = 300): Promise<TaskLogTail> {
  return apiRequest<TaskLogTail>(`/api/job-center/tasks/${encodeURIComponent(id)}/logs?tail=${tail}`)
}

export function cancelTask(id: string): Promise<TaskItem> {
  return apiRequest<TaskItem>(`/api/job-center/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

export function getTaskSummary(): Promise<TaskSummary> {
  return apiRequest<TaskSummary>('/api/job-center/summary')
}

export function cleanupTasks(
  cleanupType: TaskCleanupType,
  options: { dryRun?: boolean } = {},
): Promise<TaskCleanupResult> {
  return apiRequest<TaskCleanupResult>('/api/job-center/cleanup', {
    method: 'POST',
    body: JSON.stringify({
      cleanup_type: cleanupType,
      dry_run: Boolean(options.dryRun),
      delete_artifacts: false,
    }),
  })
}

export function dismissTask(id: string): Promise<TaskCleanupResult> {
  return apiRequest<TaskCleanupResult>(`/api/job-center/tasks/${encodeURIComponent(id)}/dismiss`, {
    method: 'POST',
  })
}

export function acknowledgeTask(id: string): Promise<TaskAcknowledgeResult> {
  return apiRequest<TaskAcknowledgeResult>(
    `/api/job-center/tasks/${encodeURIComponent(id)}/acknowledge`,
    { method: 'POST' },
  )
}

export function acknowledgeAllTaskAlerts(): Promise<TaskAcknowledgeResult> {
  return apiRequest<TaskAcknowledgeResult>('/api/job-center/acknowledge', {
    method: 'POST',
    body: JSON.stringify({ all_alerts: true }),
  })
}
