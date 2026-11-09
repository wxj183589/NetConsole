import type { MeshLinkDetail, Page } from '../../types/meshAnalysis'
import { formatMeshViewportTimestamp, meshTimestampMillis } from './meshChartViewport'
import { meshMissingIntervals, type Interval } from './meshCompleteMetricCache'

export const MESH_RAW_SAMPLE_VERSION = 'mesh-raw-v1'
export const MESH_DERIVED_METRIC_VERSION = 'mesh-derived-v1'

export type MeshRawQuery = {
  time_from: string
  time_to: string
  radio?: number
  peer_ap_mac?: string
  exact_ap?: boolean
  link_role?: string
  include_zero?: boolean
  exclude_depot?: boolean
  exclude_parking?: boolean
}

export type MeshRawPage = Page<MeshLinkDetail>

const COUNTER_FIELDS = [
  'local_tx', 'peer_tx', 'local_rx', 'peer_rx',
  'local_retry', 'peer_retry', 'local_err', 'peer_err',
  'local_tx_garp', 'peer_rx_garp', 'local_tx_mul_join', 'peer_rx_mul_join',
] as const

type CounterField = typeof COUNTER_FIELDS[number]
type CounterSample = NonNullable<MeshLinkDetail['counter_samples']>[string]

function numberValue(value: unknown): number | null {
  return value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value)
}

function rowTime(row: MeshLinkDetail): number {
  return meshTimestampMillis(row.timestamp) ?? Number.POSITIVE_INFINITY
}

function stableQuery(value: Record<string, unknown>): string {
  return JSON.stringify(Object.keys(value).sort().map(key => [key, value[key] ?? null]))
}

export function meshRawScopeKey(value: MeshRawQuery): string {
  const { time_from: _from, time_to: _to, ...scope } = value
  return stableQuery(scope)
}

/** A row identity includes the persisted record id; timestamp alone is not a key. */
export function meshRawSampleKey(row: MeshLinkDetail): string {
  return `${row.source_file_id ?? ''}|${row.record_id}|${row.local_radio ?? ''}|${row.peer_mac ?? ''}|${row.establish_time ?? ''}`
}

export function meshRawLaneKey(row: MeshLinkDetail): string {
  return JSON.stringify([
    row.source_file_id ?? null,
    row.local_radio ?? null,
    row.peer_mac ?? null,
    row.establish_time ?? null,
    row.peer_radio_mac ?? null,
    row.peer_radio ?? null,
    row.peer_ap_mac ?? null,
  ])
}

function mergeIntervals(intervals: Interval[]): Interval[] {
  const ordered = intervals
    .filter(item => Number.isSafeInteger(item.start) && Number.isSafeInteger(item.end) && item.start <= item.end)
    .sort((a, b) => a.start - b.start || a.end - b.end)
  const merged: Interval[] = []
  for (const item of ordered) {
    const previous = merged.at(-1)
    if (!previous || item.start > previous.end + 1) merged.push({ ...item })
    else previous.end = Math.max(previous.end, item.end)
  }
  return merged
}

type RawScope = {
  samples: Map<string, MeshLinkDetail>
  coverage: Interval[]
  lastUsed: number
}

export type MeshRawCacheStats = {
  scopes: number
  samples: number
  coveredIntervals: number
}

/**
 * Shared raw facts cache.  Coverage is only advanced after an explicitly
 * complete non-downsampled response; context rows never advance coverage.
 */
export class MeshRawSampleCache {
  private readonly scopes = new Map<string, RawScope>()
  private readonly maxScopes: number
  private readonly maxSamples: number
  private clock = 0

  constructor(options: { maxScopes?: number; maxSamples?: number } = {}) {
    this.maxScopes = options.maxScopes ?? 8
    this.maxSamples = options.maxSamples ?? 100_000
  }

  private scope(scopeKey: string): RawScope {
    const current = this.scopes.get(scopeKey)
    if (current) {
      current.lastUsed = ++this.clock
      return current
    }
    const created: RawScope = { samples: new Map(), coverage: [], lastUsed: ++this.clock }
    this.scopes.set(scopeKey, created)
    this.evict()
    return created
  }

  clear(scopeKey?: string): void {
    if (scopeKey === undefined) this.scopes.clear()
    else this.scopes.delete(scopeKey)
  }

  missing(scopeKey: string, request: Interval): Interval[] {
    const current = this.scopes.get(scopeKey)
    return meshMissingIntervals(request, current?.coverage ?? [])
  }

  put(scopeKey: string, request: Interval, response: MeshRawPage): boolean {
    if (response.raw_sample_version !== MESH_RAW_SAMPLE_VERSION || response.raw_sample_complete !== true || response.downsampled === true) return false
    const current = this.scope(scopeKey)
    // Visible rows win over a predecessor row that was cached as context first.
    const ordered = response.items.slice().sort((a, b) => Number(Boolean(a.is_boundary_context)) - Number(Boolean(b.is_boundary_context)))
    for (const row of ordered) {
      const key = meshRawSampleKey(row)
      const existing = current.samples.get(key)
      if (row.is_boundary_context && existing && !existing.is_boundary_context) continue
      current.samples.set(key, { ...row })
    }
    current.coverage = mergeIntervals([...current.coverage, request])
    this.evict()
    return true
  }

  all(scopeKey: string, end?: number): MeshLinkDetail[] {
    const current = this.scopes.get(scopeKey)
    if (!current) return []
    current.lastUsed = ++this.clock
    return [...current.samples.values()]
      .filter(row => end === undefined || rowTime(row) <= end)
      .sort((a, b) => rowTime(a) - rowTime(b) || a.record_id - b.record_id)
  }

  visible(scopeKey: string, request: Interval): MeshLinkDetail[] {
    return this.all(scopeKey).filter(row => {
      const timestamp = rowTime(row)
      return !row.is_boundary_context && timestamp >= request.start && timestamp <= request.end
    })
  }

  stats(): MeshRawCacheStats {
    let samples = 0
    let coveredIntervals = 0
    for (const scope of this.scopes.values()) {
      samples += scope.samples.size
      coveredIntervals += scope.coverage.length
    }
    return { scopes: this.scopes.size, samples, coveredIntervals }
  }

  private evict(): void {
    while (this.scopes.size > this.maxScopes || [...this.scopes.values()].reduce((total, item) => total + item.samples.size, 0) > this.maxSamples) {
      const oldest = [...this.scopes.entries()].sort((a, b) => a[1].lastUsed - b[1].lastUsed)[0]
      if (!oldest) return
      this.scopes.delete(oldest[0])
    }
  }
}

function median(values: number[]): number {
  if (!values.length) return 1
  const ordered = values.slice().sort((a, b) => a - b)
  const middle = Math.floor(ordered.length / 2)
  return ordered.length % 2 ? ordered[middle]! : (ordered[middle - 1]! + ordered[middle]!) / 2
}

function sameLinkRole(previous: MeshLinkDetail, current: MeshLinkDetail): boolean {
  return previous.link_role === current.link_role
}

function counterRecord(field: CounterField, row: MeshLinkDetail): number | null {
  return numberValue(row[field])
}

function setDelta(row: MeshLinkDetail, field: CounterField, value: number | null): void {
  const deltaField = `${field}_delta` as keyof MeshLinkDetail
  if (deltaField in row || field in row) (row as unknown as Record<string, unknown>)[deltaField] = value
  if (field === 'local_err') row.local_err_delta = value
  if (field === 'peer_err') row.peer_err_delta = value
}

function counterStatus(current: number | null, previous: number | null, interval: number | null, hasPrevious: boolean): string {
  if (current === null) return 'missing'
  if (!hasPrevious) return 'first'
  if (interval === null || interval <= 0) return 'invalid_interval'
  if (previous === null) return 'missing'
  return current < previous ? 'reset' : 'valid'
}

/** Rebuilds derived counter/continuity values from the complete ordered raw set. */
export function deriveMeshRawSamples(rows: MeshLinkDetail[], request: Interval): MeshLinkDetail[] {
  const ordered = rows.slice().sort((a, b) => rowTime(a) - rowTime(b) || a.record_id - b.record_id)
  const previous = new Map<string, MeshLinkDetail>()
  const cadence = new Map<string, number[]>()
  const derived: MeshLinkDetail[] = []
  for (const source of ordered) {
    const row = { ...source, counter_samples: {} as MeshLinkDetail['counter_samples'], raw_sample_version: source.raw_sample_version ?? MESH_RAW_SAMPLE_VERSION, derived_metric_version: MESH_DERIVED_METRIC_VERSION }
    const lane = meshRawLaneKey(row)
    const old = previous.get(lane)
    const currentTime = rowTime(row)
    const oldTime = old ? rowTime(old) : null
    const interval = oldTime === null || !Number.isFinite(currentTime) || !Number.isFinite(oldTime) ? null : (currentTime - oldTime) / 1000
    const samples = cadence.get(lane) ?? []
    const threshold = Math.min(Math.max((samples.length ? median(samples) : 1) * 5, 5), 60)
    const gapBefore = interval !== null && interval > threshold
    row.monitor_gap_before = gapBefore
    const roleChanged = old !== undefined && !sameLinkRole(old, row)
    const linkChanged = roleChanged
    const resetBaseline = row.link_count === 0
    for (const field of COUNTER_FIELDS) {
      const current = counterRecord(field, row)
      const before = old ? counterRecord(field, old) : null
      const status = counterStatus(current, before, interval, old !== undefined)
      const valid = !gapBefore && !linkChanged && !resetBaseline && current !== null && before !== null && interval !== null && interval > 0 && current >= before
      const delta = valid ? current - before : null
      const sample: CounterSample = { current, previous: before, delta, interval_seconds: interval, per_second: delta === null || interval === null || interval <= 0 ? null : delta / interval, status: gapBefore || linkChanged || resetBaseline ? (gapBefore ? 'gap' : 'link_changed') : status }
      row.counter_samples![field] = sample
      setDelta(row, field, delta)
    }
    if (old && interval !== null && interval > 0) samples.push(interval)
    cadence.set(lane, samples.slice(-101))
    if (resetBaseline) previous.delete(lane)
    else if (!old || interval === null || interval > 0) previous.set(lane, row)
    if (!row.is_boundary_context && currentTime >= request.start && currentTime <= request.end) derived.push(row)
  }
  return derived
}

export function meshRawRequestInterval(query: MeshRawQuery): Interval | undefined {
  const start = meshTimestampMillis(query.time_from)
  const end = meshTimestampMillis(query.time_to)
  return start === null || end === null || start > end ? undefined : { start, end }
}

export function meshRawIntervalQuery(interval: Interval): Pick<MeshRawQuery, 'time_from' | 'time_to'> {
  return { time_from: formatMeshViewportTimestamp(interval.start), time_to: formatMeshViewportTimestamp(interval.end) }
}
