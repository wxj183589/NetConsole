import type { TaskStatus } from '../types/task'

export const activeTaskStatuses: TaskStatus[] = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING']

export function taskStatusLabel(status: TaskStatus): string {
  return {
    PENDING: '等待中',
    STARTING: '启动中',
    RUNNING: '运行中',
    STOPPING: '停止中',
    COMPLETED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
  }[status]
}

export function taskStatusType(status: TaskStatus): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'info'
  if (status === 'STOPPING') return 'warning'
  return 'primary'
}
