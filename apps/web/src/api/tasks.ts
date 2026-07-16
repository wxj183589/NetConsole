import { apiRequest } from './client'
import type { TaskItem, TaskLogTail, TaskSummary } from '../types/task'

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
