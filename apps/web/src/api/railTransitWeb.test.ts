import { describe, expect, it, vi } from 'vitest'

import {
  cancelCarNetworkDiagnostic,
  cancelRailTransitTask,
  exportMeshAnalysisReport,
  exportOnlineMrReport,
  getCarNetworkDiagnosticTask,
  importMeshAnalysis,
  queryOnlineMrTimeline,
  recoverCarNetworkDiagnostics,
  recoverRailTransitTasks,
  startCarNetworkDiagnostic,
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
      display_name: 'MR 1',
      safe_folder_name: 'mr-1',
      notes: 'fixture',
    })

    const form = fetchMock.mock.calls[0][1].body as FormData
    expect([...form.keys()].sort()).toEqual(['display_name', 'files', 'mr_id', 'notes', 'safe_folder_name'])
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
})
