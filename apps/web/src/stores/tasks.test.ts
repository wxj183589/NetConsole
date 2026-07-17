import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useTaskStore } from './tasks'
import { cancelTask, getTask, getTaskLogs, listTasks } from '../api/tasks'
import type { TaskItem } from '../types/task'

vi.mock('../api/tasks', () => ({
  listTasks: vi.fn(),
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
  cancelTask: vi.fn(),
}))

const task: TaskItem = {
  id: 'task-1', type: 'online_mr_collection_start', name: '车载 MR 在线收集', status: 'RUNNING', progress: 40,
  phase: 'COLLECTING', stage: 'collect', message: '采集中', site_name: 'demo', owner: 'legacy_qt', executor: 'LOCAL',
  source: 'external', device_id: '12', device_name: '列车12-MR-CT', agent: '', mr_name: 'MR-12', session_id: 'session-12',
  mapping_state: 'LINKED', created_time: '2026-07-14T08:00:00Z', started_time: '2026-07-14T08:00:01Z',
  finished_time: '', updated_time: '2026-07-14T08:01:00Z', duration_seconds: 59, error_code: '', error_summary: '',
  has_warning: false, snapshot_id: null, records_count: null, parser_version: '', cancellable: true,
}

describe('Job Center polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(listTasks).mockReset().mockResolvedValue([task])
    vi.mocked(getTask).mockReset().mockResolvedValue(task)
    vi.mocked(getTaskLogs).mockReset().mockResolvedValue({
      task_id: task.id,
      lines: [{ sequence: 1, time: task.updated_time, level: 'INFO', type: 'log', source: 'worker', message: '采集中' }],
      message: '',
    })
    vi.mocked(cancelTask).mockReset().mockResolvedValue({ ...task, status: 'STOPPING' })
    vi.stubGlobal('window', { setTimeout, clearTimeout, setInterval, clearInterval })
  })

  it('keeps logs hidden by default and stops detail/log polling on final cleanup', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    window.setInterval = setInterval
    window.clearInterval = clearInterval
    const store = useTaskStore()

    store.acquirePolling('main-window')
    await vi.runAllTicks()
    await store.selectTask(task.id)
    expect(store.logsExpanded).toBe(false)
    expect(getTaskLogs).not.toHaveBeenCalled()

    store.setLogsExpanded(true)
    await vi.runAllTicks()
    await vi.advanceTimersByTimeAsync(1000)
    expect(getTaskLogs).toHaveBeenCalled()

    const detailCalls = vi.mocked(getTask).mock.calls.length
    const logCalls = vi.mocked(getTaskLogs).mock.calls.length
    store.releasePolling('main-window')
    await vi.advanceTimersByTimeAsync(5000)
    expect(getTask).toHaveBeenCalledTimes(detailCalls)
    expect(getTaskLogs).toHaveBeenCalledTimes(logCalls)
    expect('requestCancel' in store).toBe(true)
    vi.useRealTimers()
  })

  it('does not overlap list requests and reports after three failures', async () => {
    let rejectRequest: ((reason?: unknown) => void) | undefined
    vi.mocked(listTasks).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject }))
    const store = useTaskStore()
    const first = store.refresh()
    void store.refresh()
    expect(listTasks).toHaveBeenCalledOnce()
    rejectRequest?.(new Error('offline'))
    await first
    expect(store.error).toBe('')

    vi.mocked(listTasks).mockRejectedValue(new Error('offline'))
    await store.refresh()
    await store.refresh()
    expect(store.error).toContain('任务中心刷新失败')
  })

  it('keeps polling until main, task window and network page all release', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    window.setInterval = setInterval
    window.clearInterval = clearInterval
    const store = useTaskStore()

    store.acquirePolling('main-window')
    store.acquirePolling('task-window')
    store.acquirePolling('network-page')
    await vi.runAllTicks()
    const initialCalls = vi.mocked(listTasks).mock.calls.length

    store.releasePolling('network-page')
    store.releasePolling('main-window')
    await vi.advanceTimersByTimeAsync(5000)
    expect(listTasks).toHaveBeenCalledTimes(initialCalls + 2)

    const callsBeforeFinalRelease = vi.mocked(listTasks).mock.calls.length
    store.releasePolling('task-window')
    await vi.advanceTimersByTimeAsync(10000)
    expect(listTasks).toHaveBeenCalledTimes(callsBeforeFinalRelease)
    vi.useRealTimers()
  })

  it('handles cancel success, owner conflict and failure messages', async () => {
    const store = useTaskStore()
    await store.selectTask(task.id)
    await store.requestCancel()
    expect(store.selected?.status).toBe('STOPPING')

    for (const message of ['任务当前不可停止', '后端连接失败']) {
      vi.mocked(cancelTask).mockRejectedValueOnce(new Error(message))
      store.selected = { ...task }
      await expect(store.requestCancel()).rejects.toThrow(message)
      expect(store.detailError).toBe(message)
    }
  })
})
