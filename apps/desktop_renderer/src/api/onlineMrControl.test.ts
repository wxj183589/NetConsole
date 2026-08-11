import { afterEach, describe, expect, it, vi } from 'vitest'

import { forceStopOnlineMrControl, recoverOnlineMrControl } from './onlineMrControl'

describe('Online MR local control API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses explicit force-stop and restart recovery endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await forceStopOnlineMrControl('task/1')
    await recoverOnlineMrControl()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/online-mr-control/task%2F1/force-stop',
      '/api/rail-transit/online-mr-control/recover',
    ])
  })
})
