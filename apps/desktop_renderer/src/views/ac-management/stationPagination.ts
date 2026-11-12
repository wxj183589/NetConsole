import { listStations } from '../../api/railTransitBaseData'
import type { Page, PageQuery, Station } from '../../types/railTransitBaseData'

export const STATION_PAGE_SIZE = 200

export type StationPageLoader = (values: PageQuery) => Promise<Page<Station>>

export async function listAllStations(
  loadPage: StationPageLoader = listStations,
): Promise<Station[]> {
  const items: Station[] = []
  let page = 1
  while (true) {
    const result = await loadPage({ page, page_size: STATION_PAGE_SIZE, sort_order: 'asc' })
    items.push(...result.items)
    if (result.items.length === 0 || items.length >= result.total) return items
    page += 1
  }
}
