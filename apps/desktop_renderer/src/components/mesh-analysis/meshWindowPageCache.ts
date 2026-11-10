import type { Page } from '../../types/meshAnalysis'
import { meshTimestampMillis } from './meshChartViewport'

type WindowQuery = { time_from: string; time_to: string; page: number; page_size: number }

/** Cache exact pages, and only derive smaller windows from a verified complete first page. */
export class MeshWindowPageCache<Q extends WindowQuery, T> {
  private pages = new Map<string, { scope: string; start: number; end: number; page: number; result: Page<T> }>()
  constructor(private readonly within: (row: T, start: number, end: number) => boolean, private readonly countZero?: (row: T) => boolean) {}

  get(source: string, query: Q): Page<T> | undefined {
    const { time_from, time_to, page, page_size, ...filters } = query
    const start = meshTimestampMillis(time_from), end = meshTimestampMillis(time_to)
    if (start === null || end === null || start > end) return undefined
    const scope = JSON.stringify([source, filters, page_size])
    const exact = JSON.stringify([scope, start, end, page])
    let key = exact, entry = this.pages.get(exact)
    if (!entry) {
      const complete = [...this.pages].find(([, value]) => value.scope === scope && value.page === 1 && value.start <= start && value.end >= end && value.result.page === 1 && value.result.total === value.result.items.length && value.result.downsampled !== true)
      if (!complete) return undefined
      ;[key, entry] = complete
    }
    this.pages.delete(key); this.pages.set(key, entry)
    if (key === exact) return entry.result
    const items = entry.result.items.filter(row => this.within(row, start, end))
    return { ...entry.result, total: items.length, page, page_size, items: items.slice((page - 1) * page_size, page * page_size), ...(this.countZero ? { zero_link_count: items.filter(this.countZero).length } : {}) }
  }

  put(source: string, query: Q, result: Page<T>): void {
    const { time_from, time_to, page, page_size, ...filters } = query
    const start = meshTimestampMillis(time_from), end = meshTimestampMillis(time_to)
    if (start === null || end === null || start > end || result.page !== page || result.page_size !== page_size) return
    const scope = JSON.stringify([source, filters, page_size]), key = JSON.stringify([scope, start, end, page])
    this.pages.delete(key); this.pages.set(key, { scope, start, end, page, result })
    while (this.pages.size > 32) this.pages.delete(this.pages.keys().next().value!)
  }
  clear(): void { this.pages.clear() }
}
