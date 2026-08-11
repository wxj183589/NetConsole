import type { TaskStatus } from '../types/task'

export const activeTaskStatuses: TaskStatus[] = ['CREATED', 'QUEUED', 'PENDING', 'STARTING', 'RUNNING', 'STOPPING']

export function taskStatusLabel(status: TaskStatus): string {
  return {
    CREATED: '已创建',
    QUEUED: '排队中',
    PENDING: '等待中',
    STARTING: '启动中',
    RUNNING: '运行中',
    STOPPING: '停止中',
    COMPLETED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    ABORTED: '已中断',
    STOPPED: '已停止',
    WARNING: '有告警',
    UNKNOWN: '未知',
  }[status] || '未知'
}

export function taskStatusType(status: TaskStatus): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'RUNNING') return 'success'
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'WARNING') return 'warning'
  if (status === 'CANCELLED' || status === 'ABORTED' || status === 'STOPPED') return 'info'
  if (status === 'STOPPING') return 'warning'
  return 'primary'
}
