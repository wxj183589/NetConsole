import { describe, expect, it, vi } from 'vitest'

import { exportAcExtensions, getAcWebTask, recoverAcWebTasks, startAcLocalRebuild, startAcResourceRefresh } from './acWebParity'

describe('AC Web parity API client', () => {
  it('submits only the local rebuild target and exposes task recovery', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await startAcLocalRebuild('optical', 'ac-1')
    await startAcResourceRefresh('fit-ap', 'ac-1')
    await exportAcExtensions('station-a', 'ac-1')
    await getAcWebTask('task-1')
    await recoverAcWebTasks()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/ac-management/local-rebuild/optical')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ac_id: 'ac-1' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/ac-management/refresh/fit-ap')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ ac_id: 'ac-1', ap_id: '' })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/ac-management/extensions/export?search=station-a&ac_id=ac-1')
    expect(fetchMock.mock.calls[2][1].method).toBe('POST')
    expect(fetchMock.mock.calls[3][0]).toBe('/api/ac-management/web-tasks/task-1')
    expect(fetchMock.mock.calls[4][0]).toBe('/api/ac-management/web-tasks/recover')
  })
})
