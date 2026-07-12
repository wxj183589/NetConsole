import { apiRequest } from './client'
import type { TaskEvent, TaskItem } from '../types/task'

export function listTasks(): Promise<TaskItem[]> {
  return apiRequest<TaskItem[]>('/api/tasks')
}

export function getTask(id: string): Promise<TaskItem> {
  return apiRequest<TaskItem>(`/api/tasks/${encodeURIComponent(id)}`)
}

export function listTaskEvents(id: string): Promise<TaskEvent[]> {
  return apiRequest<TaskEvent[]>(`/api/tasks/${encodeURIComponent(id)}/events`)
}

export function cancelTask(id: string): Promise<{ id: string; status: string; message: string }> {
  return apiRequest(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}
