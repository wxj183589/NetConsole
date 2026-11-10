import { meshTimestampMillis } from './meshChartViewport'

type WindowQuery = { time_from: string; time_to: string }
type MetricResult = { items: unknown[]; total: number; downsampled?: boolean }
export type Interval = { start: number; end: number }

/** The API uses inclusive, millisecond-resolution boundaries. */
export function meshMissingIntervals(request: Interval, coverage: Interval[]): Interval[] {
  if (!Number.isSafeInteger(request.start) || !Number.isSafeInteger(request.end) || request.start > request.end) return []
  const intervals = coverage.filter(item => Number.isSafeInteger(item.start) && Number.isSafeInteger(item.end) && item.start <= item.end && item.end >= request.start && item.start <= request.end)
    .slice().sort((a, b) => a.start - b.start || a.end - b.end)
  const missing: Interval[] = []
  let cursor = request.start
  for (const interval of intervals) {
    if (interval.start > cursor) missing.push({ start: cursor, end: Math.min(request.end, interval.start - 1) })
    cursor = Math.max(cursor, interval.end + 1)
    if (cursor > request.end) break
  }
  if (cursor <= request.end) missing.push({ start: cursor, end: request.end })
  return missing
}

/** Reuse only explicitly complete responses for the same non-time query. */
export class MeshCompleteMetricCache<Q extends WindowQuery, R extends MetricResult> {
  private entries = new Map<string, { scope: string; start: number; end: number; result: R }>()

  missing(source: string, query: Q): Interval[] | undefined {
    const { time_from, time_to, ...filters } = query
    const start = meshTimestampMillis(time_from), end = meshTimestampMillis(time_to)
    if (start === null || end === null || start > end) return undefined
    const scope = JSON.stringify([source, filters])
    return meshMissingIntervals({ start, end }, [...this.entries.values()].filter(entry => entry.scope === scope))
  }

  get(source: string, query: Q): R | undefined {
    const { time_from, time_to, ...filters } = query
    const start = meshTimestampMillis(time_from), end = meshTimestampMillis(time_to)
    if (start === null || end === null || start > end) return undefined
    const scope = JSON.stringify([source, filters])
    for (const [key, entry] of this.entries) {
      if (entry.scope === scope && entry.start <= start && entry.end >= end) {
        this.entries.delete(key); this.entries.set(key, entry)
        return entry.result
      }
    }
    return undefined
  }

  put(source: string, query: Q, result: R): void {
    if (result.downsampled !== false || result.total !== result.items.length) return
    const { time_from, time_to, ...filters } = query
    const start = meshTimestampMillis(time_from), end = meshTimestampMillis(time_to)
    if (start === null || end === null || start > end) return
    const scope = JSON.stringify([source, filters]), key = JSON.stringify([scope, start, end])
    this.entries.delete(key); this.entries.set(key, { scope, start, end, result })
    while (this.entries.size > 16) this.entries.delete(this.entries.keys().next().value!)
  }

  clear(): void { this.entries.clear() }
}
