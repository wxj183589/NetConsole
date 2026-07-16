import { describe, expect, it, vi } from 'vitest'

import {
  getLogs,
  maintenanceArtifactDownloadRequest,
  openMaintenanceDirectory,
  requestAboutLink,
  startCleanup,
  startLogExport,
  startOpenSourceExport,
  type MaintenanceTask,
} from './systemMaintenance'

describe('system maintenance API client', () => {
  it('submits strict log, cleanup and Export Process contracts', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await getLogs({ page: 2, page_size: 100, keyword: '启动', level: 'ERROR' })
    await startCleanup('clean')
    await startLogExport({ scope: 'current', keyword: '启动', level: 'ERROR', page: 2, page_size: 100 })
    await startOpenSourceExport('xlsx')

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/system-maintenance/logs?page=2&page_size=100&keyword=%E5%90%AF%E5%8A%A8&level=ERROR',
    )
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ mode: 'clean' })
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({
      scope: 'current',
      keyword: '启动',
      level: 'ERROR',
      page: 2,
      page_size: 100,
    })
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({ format: 'xlsx' })
  })

  it('uses only semantic desktop/link IDs and controlled Artifact URLs', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true }) })
    vi.stubGlobal('fetch', fetchMock)

    await openMaintenanceDirectory('logs')
    await requestAboutLink('repository-1')
    const request = maintenanceArtifactDownloadRequest({
      artifact_kind: 'logs_all',
      artifact_id: 'artifact-1',
      artifact_name: 'logs.csv',
    } as MaintenanceTask)

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/system-maintenance/desktop-actions/open-directory/logs',
      '/api/system-maintenance/links/about/repository-1',
    ])
    expect(request).toEqual({
      apiPath: '/api/system-maintenance/artifacts/logs_all/artifact-1',
      suggestedName: 'logs.csv',
    })
  })
})
