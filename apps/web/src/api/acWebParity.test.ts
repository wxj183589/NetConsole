import { describe, expect, it, vi } from 'vitest'

import { exportAcExtensions, startAcRefresh } from './acWebParity'

describe('AC Web parity API client', () => {
  it('submits only the controlled refresh fields and starts the guarded export', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await startAcRefresh('optical', 'ac-1')
    await exportAcExtensions('station-a', 'ac-1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/ac-management/refresh/optical')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ac_id: 'ac-1' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/ac-management/extensions/export?search=station-a&ac_id=ac-1')
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
  })
})
