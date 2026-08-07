import { describe, expect, it, vi } from 'vitest'

import type {
  TracksideApBusinessExportProposal,
  TracksideApBusinessExportRequest,
} from '../types/tracksideApBusiness'

import {
  cancelTracksideApTask,
  exportTracksideApPlan,
  exportTracksideApRenameCommands,
  getTracksideApOnlineStatus,
  getTracksideApPlan,
  getTracksideApTask,
  listTracksideSwitchAdapters,
  listTracksideApBusiness,
  recoverTracksideApTasks,
  saveTracksideApPlan,
  startTracksideApBusinessExport,
  startTracksideApUpdate,
  startTracksideSwitchSample,
  tracksideApBusinessDownloadRequest,
  tracksideSwitchSampleDownloadRequest,
} from './tracksideApBusiness'

describe('trackside AP business API', () => {
  it('sends only the export request DTO fields from a proposal', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-export' }) })
    vi.stubGlobal('fetch', fetchMock)

    const proposal = {
      generated_at: '2026-08-02T18:00:00+08:00',
      suggested_name: '宁波地铁12号线_轨旁AP业务_20260802_180000.xlsx',
      expected_revision: 'revision-1',
      site_id: '宁波地铁12号线',
      site_display_name: '宁波地铁12号线',
      station: '站点A',
      query: 'AP-A',
      selected_row_ids: ['row-1'],
      optical_anomaly_only: true,
    } as TracksideApBusinessExportProposal & TracksideApBusinessExportRequest & {
      optical_anomaly_only: boolean
    }

    await startTracksideApBusinessExport(proposal)

    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        generated_at: '2026-08-02T18:00:00+08:00',
        suggested_name: '宁波地铁12号线_轨旁AP业务_20260802_180000.xlsx',
        expected_revision: 'revision-1',
        station: '站点A',
        query: 'AP-A',
        selected_row_ids: ['row-1'],
      }),
    })
  })

  it('keeps query, update, export and task lifecycle in the trackside boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await listTracksideApBusiness({ station: '站点A', optical_anomaly_only: true })
    await startTracksideApUpdate({ station: '站点A' })
    await startTracksideApBusinessExport()
    await listTracksideSwitchAdapters()
    await startTracksideSwitchSample({
      device_uuid: 'zte-1',
      vendor: 'ZTE',
      command_profile: 'zte_zxr10_5960x_es_v2',
      selected_interface: 'xgei-0/1/1/2',
      requested_commands: [],
    })
    await getTracksideApTask('task-1')
    await cancelTracksideApTask('task-1')
    await recoverTracksideApTasks()
    await getTracksideApPlan()
    await getTracksideApOnlineStatus()
    await saveTracksideApPlan([])
    await exportTracksideApPlan(true)
    await exportTracksideApRenameCommands()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/trackside-ap-business/rows?station=%E7%AB%99%E7%82%B9A&optical_anomaly_only=true',
      '/api/rail-transit/trackside-ap-business/update',
      '/api/rail-transit/trackside-ap-business/export',
      '/api/rail-transit/trackside-ap-business/switch-adapters',
      '/api/rail-transit/trackside-ap-business/switch-adapters/sample',
      '/api/rail-transit/trackside-ap-business/tasks/task-1',
      '/api/rail-transit/trackside-ap-business/tasks/task-1/cancel',
      '/api/rail-transit/trackside-ap-business/tasks/recover',
      '/api/rail-transit/trackside-ap-business/plan',
      '/api/rail-transit/trackside-ap-business/plan/online-status',
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
    expect(tracksideSwitchSampleDownloadRequest(
      'sample / 1',
      'zte-adapter-sample-ZTE-SW-01-20260728_101500.zip',
    )).toEqual({
      apiPath: '/api/rail-transit/trackside-ap-business/switch-adapters/artifacts/sample%20%2F%201/download',
      suggestedName: 'zte-adapter-sample-ZTE-SW-01-20260728_101500.zip',
    })
    expect(() => tracksideSwitchSampleDownloadRequest(
      'sample-1',
      '../zte-adapter-sample-ZTE-SW-01-20260728_101500.zip',
    )).toThrow('artifactName')
  })
})
