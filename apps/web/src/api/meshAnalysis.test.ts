import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMeshProfile, listMeshProfiles } from './meshAnalysis'

describe('Mesh profile API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the independent Mesh profile boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await listMeshProfiles()
    await createMeshProfile({ display_name: '列车01-MR-CT', linked_mr_id: 'mr-1', notes: 'fixture' })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/mesh-analysis/profiles',
      '/api/rail-transit/mesh-analysis/profiles',
    ])
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ display_name: '列车01-MR-CT', linked_mr_id: 'mr-1', notes: 'fixture' })
  })
})
