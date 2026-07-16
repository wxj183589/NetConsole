import { describe, expect, it, vi } from 'vitest'

import {
  cancelTracksideApTask,
  getTracksideApTask,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  startTracksideApUpdate,
} from './tracksideApBusiness'

describe('trackside AP business API', () => {
  it('keeps query, update, export and task lifecycle in the trackside boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await listTracksideApBusiness({ station: '站点A', optical_anomaly_only: true })
    await startTracksideApUpdate({ station: '站点A' })
    await getTracksideApTask('task-1')
    await cancelTracksideApTask('task-1')
    await recoverTracksideApTasks()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/trackside-ap-business/rows?station=%E7%AB%99%E7%82%B9A&optical_anomaly_only=true',
      '/api/rail-transit/trackside-ap-business/update',
      '/api/rail-transit/trackside-ap-business/tasks/task-1',
      '/api/rail-transit/trackside-ap-business/tasks/task-1/cancel',
      '/api/rail-transit/trackside-ap-business/tasks/recover',
    ])
  })
})
