import { meshTimestampMillis } from './meshChartViewport'

type WindowQuery = { time_from: string; time_to: string }
type MetricResult = { items: unknown[]; total: number; downsampled?: boolean }

/** Reuse only explicitly complete responses for the same non-time query. */
export class MeshCompleteMetricCache<Q extends WindowQuery, R extends MetricResult> {
  private entries = new Map<string, { scope: string; start: number; end: number; result: R }>()

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
