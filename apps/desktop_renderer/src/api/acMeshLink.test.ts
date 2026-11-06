import { describe, expect, it, vi } from 'vitest'

import { getAcMeshMrDetail, getAcMeshRawTail, getAcMeshSnapshot, listAcMeshLinks, listAcMeshMrs, listAcMeshPeerAps, refreshAcMeshLinks } from './acMeshLink'

describe('AC Mesh-Link API', () => {
  it('encodes query filters and pagination', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, page: 2, page_size: 50 }) })
    vi.stubGlobal('fetch', fetchMock)
    await listAcMeshLinks({ page: 2, page_size: 50, query: 'MR 01', match_status: 'matched' })
    const url = new URL(fetchMock.mock.calls[0][0], 'http://localhost')
    expect(url.pathname).toBe('/api/ac-management/mesh-links/current')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('query')).toBe('MR 01')
    expect(url.searchParams.get('match_status')).toBe('matched')
  })

  it('posts refresh requests and supports an optional raw-tail snapshot', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1', status: 'RUNNING', message: 'ok' }) })
    vi.stubGlobal('fetch', fetchMock)
    await refreshAcMeshLinks({ controller_id: 'ac-1' })
    expect(fetchMock.mock.calls[0][0]).toContain('/api/ac-management/mesh-links/refresh')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ controller_id: 'ac-1' })
    await getAcMeshRawTail(9, 20)
    const url = new URL(fetchMock.mock.calls[1][0], 'http://localhost')
    expect(url.searchParams.get('snapshot_id')).toBe('9')
    expect(url.searchParams.get('limit')).toBe('20')
  })

  it('encodes MR, reverse AP, detail and snapshot requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0 }) })
    vi.stubGlobal('fetch', fetchMock)
    await listAcMeshMrs({ car_end: 'CT', multiple_peers: true, abnormal_only: true, page: 3, page_size: 20 })
    await listAcMeshPeerAps({ query: 'AP 1', station: '车站A', section: '区间1', page: 2, page_size: 10 })
    await getAcMeshMrDetail('mr/01', { start_time: '2026-01-01 00:00:00', end_time: '2026-01-01 01:00:00', page: 2, page_size: 30 })
    await getAcMeshSnapshot(42)
    const urls = fetchMock.mock.calls.map(([url]) => new URL(url, 'http://localhost'))
    expect(urls[0].pathname).toBe('/api/ac-management/mesh-links/mrs')
    expect(urls[0].searchParams.get('car_end')).toBe('CT')
    expect(urls[0].searchParams.get('multiple_peers')).toBe('true')
    expect(urls[1].pathname).toBe('/api/ac-management/mesh-links/peer-aps')
    expect(urls[1].searchParams.get('station')).toBe('车站A')
    expect(urls[2].pathname).toBe('/api/ac-management/mesh-links/mrs/mr%2F01')
    expect(urls[2].searchParams.get('page_size')).toBe('30')
    expect(urls[3].pathname).toBe('/api/ac-management/mesh-links/snapshots/42')
  })
})
