import { describe, expect, it, vi } from 'vitest'

import { listAllStations, STATION_PAGE_SIZE } from './stationPagination'
import type { Station } from '../../types/railTransitBaseData'

function station(id: string, enabled = true): Station {
  return {
    id,
    site_id: 'demo',
    code: id,
    name: `站点 ${id}`,
    enabled,
  } as unknown as Station
}

describe('FIT-AP station pagination', () => {
  it('uses the backend limit and does not request a second page for a short result', async () => {
    const loadPage = vi.fn().mockResolvedValue({
      items: [station('001')],
      total: 1,
      page: 1,
      page_size: STATION_PAGE_SIZE,
    })

    await expect(listAllStations(loadPage)).resolves.toHaveLength(1)
    expect(loadPage).toHaveBeenCalledWith({ page: 1, page_size: 200, sort_order: 'asc' })
    expect(loadPage).toHaveBeenCalledOnce()
  })

  it('accumulates every page when total exceeds 200 and stops at the last page', async () => {
    const pages = new Map([
      [1, { items: Array.from({ length: 200 }, (_, index) => station(`${index + 1}`)), total: 401, page: 1, page_size: 200 }],
      [2, { items: Array.from({ length: 200 }, (_, index) => station(`${index + 201}`)), total: 401, page: 2, page_size: 200 }],
      [3, { items: [station('401')], total: 401, page: 3, page_size: 200 }],
    ])
    const loadPage = vi.fn(async ({ page }: { page?: number }) => pages.get(page || 1)!)

    const result = await listAllStations(loadPage)

    expect(result).toHaveLength(401)
    expect(loadPage.mock.calls.map(([request]) => request)).toEqual([
      { page: 1, page_size: 200, sort_order: 'asc' },
      { page: 2, page_size: 200, sort_order: 'asc' },
      { page: 3, page_size: 200, sort_order: 'asc' },
    ])
  })

  it('leaves filter, refresh, and export scope behavior to their existing consumers', async () => {
    const loadPage = vi.fn().mockResolvedValue({
      items: [station('enabled'), station('disabled', false)],
      total: 2,
      page: 1,
      page_size: 200,
    })

    const enabled = (await listAllStations(loadPage)).filter((item) => item.enabled !== false)

    expect(enabled.map((item) => item.id)).toEqual(['enabled'])
    expect(loadPage.mock.calls[0][0]).toMatchObject({ page_size: 200 })
  })
})
