import { describe, expect, it, vi } from 'vitest'

import { listAcAps } from './acManagement'

describe('AC FIT-AP repeated filter parameters', () => {
  it('sends repeated query params without comma-splitting Chinese station names', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, page: 1, page_size: 1 }) })
    vi.stubGlobal('fetch', fetchMock)
    await listAcAps({
      ac_id: 'ac-1', page: 2, page_size: 1,
      statuses: ['online', 'offline'],
      stations: ['01-小洋江站', '02-云龙火车站'],
    })
    const url = new URL(fetchMock.mock.calls[0][0], 'http://localhost')
    expect(url.pathname).toBe('/api/ac-management/aps')
    expect(url.searchParams.getAll('statuses')).toEqual(['online', 'offline'])
    expect(url.searchParams.getAll('stations')).toEqual(['01-小洋江站', '02-云龙火车站'])
    expect(url.searchParams.get('page')).toBe('2')
  })
})
