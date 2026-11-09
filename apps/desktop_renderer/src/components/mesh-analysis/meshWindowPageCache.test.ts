import { describe, expect, it } from 'vitest'
import { MeshWindowPageCache } from './meshWindowPageCache'
import { meshTimestampMillis } from './meshChartViewport'

const query = { time_from: '2026-11-09 10:00:00.000', time_to: '2026-11-09 10:00:00.010', page: 1, page_size: 3, radio: 1, role: 'ACTIVE', ap: 'A', include_zero: true }
const inside = { ...query, time_from: '2026-11-09 10:00:00.005', time_to: '2026-11-09 10:00:00.010' }
const rows = [{ time: '2026-11-09 10:00:00.004', zero: false }, { time: '2026-11-09 10:00:00.005', zero: true }, { time: '2026-11-09 10:00:00.010', zero: false }]
const result = { items: rows, total: 3, page: 1, page_size: 3, zero_link_count: 1, downsampled: false }
const makeCache = () => new MeshWindowPageCache<typeof query, typeof rows[number]>((row, start, end) => { const time = meshTimestampMillis(row.time)!; return time >= start && time <= end }, row => row.zero)

describe('MESH window page cache', () => {
  it('reuses exact pages and filters complete enclosing pages at inclusive millisecond boundaries', () => {
    const cache = makeCache(); cache.put('session', query, result)
    expect(cache.get('session', query)).toBe(result)
    expect(cache.get('session', inside)).toMatchObject({ items: rows.slice(1), total: 2, zero_link_count: 1 })
    expect(cache.get('session', { ...inside, page: 2 })).toMatchObject({ items: [], total: 2, page: 2 })
    expect(cache.get('session', { ...inside, time_to: '2026-11-09 10:00:00.009' })?.items).toEqual([rows[1]])
  })

  it('isolates session and filters and refuses to infer coverage from partial or sampled pages', () => {
    const cache = makeCache(); cache.put('session', query, { ...result, total: 4 })
    expect(cache.get('session', query)).toBeDefined()
    expect(cache.get('session', inside)).toBeUndefined()
    cache.put('session', query, { ...result, downsampled: true })
    expect(cache.get('session', inside)).toBeUndefined()
    cache.put('session', query, result)
    for (const changed of [{ ...inside, radio: 2 }, { ...inside, role: 'STANDBY' }, { ...inside, ap: 'B' }, { ...inside, include_zero: false }, { ...inside, time_from: '2026-11-09 09:59:59.999' }]) expect(cache.get('session', changed)).toBeUndefined()
    expect(cache.get('other', inside)).toBeUndefined()
    cache.clear(); expect(cache.get('session', query)).toBeUndefined()
  })

  it('rejects mismatched page metadata and evicts least recently used pages', () => {
    const cache = makeCache(); cache.put('bad', query, { ...result, page: 2 })
    expect(cache.get('bad', query)).toBeUndefined()
    for (let i = 0; i < 32; i++) cache.put(String(i), query, result)
    cache.get('0', query); cache.put('32', query, result)
    expect(cache.get('0', query)).toBeDefined(); expect(cache.get('1', query)).toBeUndefined()
  })

  it('supports build intervals that cross the requested window', () => {
    const cache = new MeshWindowPageCache<typeof query, { start: number; end: number }>((row, start, end) => row.start <= end && row.end >= start)
    const start = meshTimestampMillis(query.time_from)!
    cache.put('s', query, { items: [{ start, end: start + 7 }], total: 1, page: 1, page_size: 3 })
    expect(cache.get('s', inside)?.items).toHaveLength(1)
  })
})
