import { afterEach, describe, expect, it, vi } from 'vitest'

import { getNetworkComponents, saveNetworkComponent } from './systemSettings'

describe('system settings API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads and saves component mode through the dedicated endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: 'v2', components: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getNetworkComponents()
    await saveNetworkComponent('fping', 'builtin', '', 'v1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings/network-components')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/settings/network-components/fping')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual({
      mode: 'builtin', custom_path: '', expected_version: 'v1',
    })
  })
})
