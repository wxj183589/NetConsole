import { describe, expect, it } from 'vitest'
import { MeshCompleteMetricCache, meshMissingIntervals } from './meshCompleteMetricCache'

const base = { time_from: '2026-11-09 10:00:00.000', time_to: '2026-11-09 10:10:00.000', radio: 1, ap: 'AP1', role: 'ACTIVE', include_zero: false }
const inside = { ...base, time_from: '2026-11-09 10:02:00.000', time_to: '2026-11-09 10:08:00.000' }
const complete = { items: [1, 2], total: 2, downsampled: false }

describe('complete MESH metric response cache', () => {
  it('plans disjoint inclusive millisecond gaps without losing boundary samples', () => {
    expect(meshMissingIntervals({ start: 0, end: 25 }, [{ start: 20, end: 25 }, { start: 0, end: 5 }, { start: 10, end: 15 }])).toEqual([{ start: 6, end: 9 }, { start: 16, end: 19 }])
    expect(meshMissingIntervals({ start: 0, end: 15 }, [{ start: 0, end: 10 }, { start: 5, end: 12 }])).toEqual([{ start: 13, end: 15 }])
    expect(meshMissingIntervals({ start: 2, end: 8 }, [{ start: 0, end: 5 }, { start: 6, end: 10 }])).toEqual([])
    expect(meshMissingIntervals({ start: 5, end: 5 }, [])).toEqual([{ start: 5, end: 5 }])
    expect(meshMissingIntervals({ start: 6, end: 5 }, [])).toEqual([])
  })

  it('only plans coverage from complete entries with matching identity and retained LRU entries', () => {
    const cache = new MeshCompleteMetricCache<typeof base, typeof complete>()
    cache.put('s', base, complete)
    expect(cache.missing('s', inside)).toEqual([])
    expect(cache.missing('s', { ...inside, radio: 2 })).toHaveLength(1)
    expect(cache.missing('other', inside)).toHaveLength(1)
    for (let index = 0; index < 16; index++) cache.put(String(index), base, complete)
    expect(cache.missing('s', inside)).toHaveLength(1)
  })
  it('reuses a complete enclosing interval and isolates query identities', () => {
    const cache = new MeshCompleteMetricCache<typeof base, typeof complete>()
    cache.put('session-1|counters', base, complete)
    expect(cache.get('session-1|counters', inside)).toBe(complete)
    expect(cache.get('session-2|counters', inside)).toBeUndefined()
    expect(cache.get('session-1|rssi', inside)).toBeUndefined()
    for (const query of [{ ...inside, ap: 'AP2' }, { ...inside, radio: 2 }, { ...inside, role: 'STANDBY' }, { ...inside, include_zero: true }, { ...inside, time_from: '2026-11-09 09:59:59.999' }]) {
      expect(cache.get('session-1|counters', query)).toBeUndefined()
    }
    cache.clear()
    expect(cache.get('session-1|counters', inside)).toBeUndefined()
  })

  it('never treats sampled, partial, or unspecified responses as complete', () => {
    const cache = new MeshCompleteMetricCache<typeof base, { items: number[]; total: number; downsampled?: boolean }>()
    for (const result of [{ ...complete, downsampled: true }, { ...complete, total: 3 }, { items: [1, 2], total: 2 }]) {
      cache.put('s', base, result)
      expect(cache.get('s', inside)).toBeUndefined()
    }
  })

  it('evicts least recently used intervals', () => {
    const cache = new MeshCompleteMetricCache<typeof base, typeof complete>()
    for (let index = 0; index < 16; index++) cache.put(String(index), base, complete)
    expect(cache.get('0', inside)).toBe(complete)
    cache.put('16', base, complete)
    expect(cache.get('0', inside)).toBe(complete)
    expect(cache.get('1', inside)).toBeUndefined()
  })
})
