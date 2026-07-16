import { describe, expect, it } from 'vitest'

import type { FileDownloadTask, RemoteFileEntry } from '../../types/fileManagement'
import { createFileManagementTranslator } from './fileManagementI18n'
import { activeDownloadTasks, formatBytes, formatSpeed, mergeDownloadTasks, selectableRemoteFiles, summarizeDownloadBatches } from './fileManagementModel'

function task(id: string, status: FileDownloadTask['status'], updatedAt: string): FileDownloadTask {
  return {
    task_id: id, site_id: 'demo', status, progress: 0, stage: '', message: '', batch_id: '', source_kind: 'remote',
    device_name: 'MR-1', remote_name: `${id}.bin`, downloaded_bytes: 0, total_bytes: 0,
    speed_bytes_per_second: 0, created_at: updatedAt, updated_at: updatedAt, retryable: false, retry_reason: '', result: null,
  }
}

describe('file management state model', () => {
  it('recovers server tasks by id and replaces stale state', () => {
    const merged = mergeDownloadTasks(
      [task('a', 'RUNNING', '2026-07-16T10:00:00Z')],
      [task('a', 'COMPLETED', '2026-07-16T10:01:00Z'), task('b', 'FAILED', '2026-07-16T10:02:00Z')],
    )
    expect(merged.map((item) => [item.task_id, item.status])).toEqual([['b', 'FAILED'], ['a', 'COMPLETED']])
    expect(activeDownloadTasks(merged)).toEqual([])
  })

  it('selects downloadable files and applies the Qt mesh-log shortcut', () => {
    const items = [
      { entry_id: 'dir', name: 'diagfile', is_dir: true, downloadable: false },
      { entry_id: 'bin', name: 'boot.bin', is_dir: false, downloadable: true },
      { entry_id: 'mesh', name: '2026_07_16_1meshlog.log.gz', is_dir: false, downloadable: true },
    ] as RemoteFileEntry[]
    expect(selectableRemoteFiles(items).map((item) => item.entry_id)).toEqual(['bin', 'mesh'])
    expect(selectableRemoteFiles(items, true).map((item) => item.entry_id)).toEqual(['mesh'])
  })

  it('formats queue byte counts and speeds', () => {
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatSpeed(2 * 1024 ** 2)).toBe('2.0 MB/s')
    expect(formatSpeed(0)).toBe('-')
  })

  it('summarizes persistent batches from task states', () => {
    const values = [task('a', 'COMPLETED', '2026-07-16T10:00:00Z'), task('b', 'RUNNING', '2026-07-16T10:01:00Z')]
    values.forEach((item) => { item.batch_id = 'fb1_batch' })
    expect(summarizeDownloadBatches(values)).toEqual([{
      batchId: 'fb1_batch', total: 2, completed: 1, failed: 0, cancelled: 0, active: 1,
    }])
  })

  it('routes action labels through the file-management locale table', () => {
    expect(createFileManagementTranslator('zh-CN')('retry')).toBe('重试')
    expect(createFileManagementTranslator('en-US')('containingFolder')).toBe('Show in folder')
  })
})
