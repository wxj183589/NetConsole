import type { FileDownloadTask, RemoteFileEntry } from '../../types/fileManagement'

export const ACTIVE_DOWNLOAD_STATUSES = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING'])

export function mergeDownloadTasks(current: FileDownloadTask[], incoming: FileDownloadTask[], limit = 100): FileDownloadTask[] {
  const byId = new Map(current.map((task) => [task.task_id, task]))
  for (const task of incoming) byId.set(task.task_id, task)
  return [...byId.values()]
    .sort((left, right) => (right.updated_at || right.created_at).localeCompare(left.updated_at || left.created_at))
    .slice(0, limit)
}

export function activeDownloadTasks(tasks: FileDownloadTask[]): FileDownloadTask[] {
  return tasks.filter((task) => ACTIVE_DOWNLOAD_STATUSES.has(task.status))
}

export interface DownloadBatchSummary {
  batchId: string
  total: number
  completed: number
  failed: number
  cancelled: number
  active: number
}

export function summarizeDownloadBatches(tasks: FileDownloadTask[]): DownloadBatchSummary[] {
  const summaries = new Map<string, DownloadBatchSummary>()
  for (const task of tasks) {
    if (!task.batch_id) continue
    const summary = summaries.get(task.batch_id) || {
      batchId: task.batch_id, total: 0, completed: 0, failed: 0, cancelled: 0, active: 0,
    }
    summary.total += 1
    if (task.status === 'COMPLETED') summary.completed += 1
    else if (task.status === 'FAILED') summary.failed += 1
    else if (task.status === 'CANCELLED') summary.cancelled += 1
    else summary.active += 1
    summaries.set(task.batch_id, summary)
  }
  return [...summaries.values()]
}

export function selectableRemoteFiles(items: RemoteFileEntry[], meshOnly = false): RemoteFileEntry[] {
  return items.filter((item) => !item.is_dir && item.downloadable && (!meshOnly || /meshlog\.log(?:\.gz)?$/i.test(item.name)))
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(1)} GB`
}

export function formatSpeed(value: number): string {
  return value > 0 ? `${formatBytes(value)}/s` : '-'
}
