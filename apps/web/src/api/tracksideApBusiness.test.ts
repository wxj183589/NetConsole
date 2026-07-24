import { describe, expect, it, vi } from 'vitest'

import {
  cancelTracksideApTask,
  exportTracksideApPlan,
  exportTracksideApRenameCommands,
  getTracksideApPlan,
  getTracksideApTask,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  saveTracksideApPlan,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
  tracksideApBusinessDownloadRequest,
} from './tracksideApBusiness'

describe('trackside AP business API', () => {
  it('keeps query, update, export and task lifecycle in the trackside boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await listTracksideApBusiness({ station: '站点A', optical_anomaly_only: true })
    await startTracksideApUpdate({ station: '站点A' })
    await startTracksideApBusinessExport()
    await getTracksideApTask('task-1')
    await cancelTracksideApTask('task-1')
    await recoverTracksideApTasks()
    await getTracksideApPlan()
    await saveTracksideApPlan([])
    await exportTracksideApPlan(true)
    await exportTracksideApRenameCommands()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/trackside-ap-business/rows?station=%E7%AB%99%E7%82%B9A&optical_anomaly_only=true',
      '/api/rail-transit/trackside-ap-business/update',
      '/api/rail-transit/trackside-ap-business/export',
      '/api/rail-transit/trackside-ap-business/tasks/task-1',
      '/api/rail-transit/trackside-ap-business/tasks/task-1/cancel',
      '/api/rail-transit/trackside-ap-business/tasks/recover',
      '/api/rail-transit/trackside-ap-business/plan',
      '/api/rail-transit/trackside-ap-business/plan/save',
      '/api/rail-transit/trackside-ap-business/plan/export',
      '/api/rail-transit/trackside-ap-business/base/rename-commands/export',
    ])
    expect(tracksideApBusinessDownloadRequest('artifact / 1', '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx')).toEqual({
      apiPath: '/api/rail-transit/trackside-ap-business/artifacts/artifact%20%2F%201/download',
      suggestedName: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(() => tracksideApBusinessDownloadRequest('artifact-1', '轨旁AP业务.xlsx')).toThrow('artifactName')
    expect(() => tracksideApBusinessDownloadRequest('artifact-1', '../宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx')).toThrow('artifactName')
  })
})
