import { describe, expect, it, vi } from 'vitest'

import {
  cancelCarNetworkDiagnostic,
  cancelCarNetworkPointTableTask,
  cancelRailTransitTask,
  exportMeshAnalysisReport,
  exportOnlineMrReport,
  exportCarNetworkPointTable,
  getCarNetworkDiagnosticTask,
  getCarNetworkPointTable,
  generateCarNetworkPointTable,
  importMeshAnalysis,
  queryOnlineMrTimeline,
  recoverCarNetworkDiagnostics,
  recoverCarNetworkPointTableTasks,
  recoverRailTransitTasks,
  startCarNetworkDiagnostic,
  saveCarNetworkPointTable,
} from './railTransitWeb'

describe('rail transit Web parity API client', () => {
  it('uses the train communication diagnostic lifecycle without a browser-supplied site', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await startCarNetworkDiagnostic('train-1')
    await getCarNetworkDiagnosticTask('task-1')
    await cancelCarNetworkDiagnostic('task-1')
    await recoverCarNetworkDiagnostics()
    await exportOnlineMrReport('session-1', 'report.xlsx')

    expect(fetchMock.mock.calls.slice(0, 4).map((call) => call[0])).toEqual([
      '/api/rail-transit/train-communication/trains/train-1/diagnostics',
      '/api/rail-transit/train-communication/diagnostics/task-1',
      '/api/rail-transit/train-communication/diagnostics/task-1/cancel',
      '/api/rail-transit/train-communication/diagnostics/recover',
    ])
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined()
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ output_name: 'report.xlsx' })
  })

  it('uploads only whitelisted profile fields and no site or relative path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-2' }) })
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['mesh'], 'raw.log', { type: 'text/plain' })

    await importMeshAnalysis([file], {
      mr_id: 'mr-1',
    })

    const form = fetchMock.mock.calls[0][1].body as FormData
    expect([...form.keys()].sort()).toEqual(['files', 'mr_id'])
    expect(form.has('site_id')).toBe(false)
    expect(form.has('relative_folder_path')).toBe(false)
  })

  it('exposes guarded MESH export and task cancellation/recovery calls', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-3' }) })
    vi.stubGlobal('fetch', fetchMock)

    await exportMeshAnalysisReport('mr-id:1')
    await cancelRailTransitTask('task-3')
    await recoverRailTransitTasks()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/mesh-analysis/sessions/mr-id%3A1/report',
      '/api/online-mr/tasks/task-3/cancel',
      '/api/online-mr/tasks/recover',
    ])
  })

  it('reads Online MR timeline through the session analysis boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: [] }) })
    vi.stubGlobal('fetch', fetchMock)

    await queryOnlineMrTimeline('session/1', 300)

    expect(fetchMock.mock.calls[0][0]).toBe('/api/online-mr/sessions/session%2F1/timeline?limit=300&offset=0')
  })

  it('uses point-table read, write, generation, export and task control endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-4' }) })
    vi.stubGlobal('fetch', fetchMock)

    await getCarNetworkPointTable()
    await saveCarNetworkPointTable([], {}, false, 'revision-1')
    await generateCarNetworkPointTable([], {})
    await exportCarNetworkPointTable('xlsx')
    await cancelCarNetworkPointTableTask('task-4')
    await recoverCarNetworkPointTableTasks()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/train-communication/point-table',
      '/api/rail-transit/train-communication/point-table/save',
      '/api/rail-transit/train-communication/point-table/generate',
      '/api/rail-transit/train-communication/point-table/export',
      '/api/rail-transit/train-communication/point-table/tasks/task-4/cancel',
      '/api/rail-transit/train-communication/point-table/tasks/recover',
    ])
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).explicit_confirmation).toBe(true)
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).revision).toBe('revision-1')
  })
})
