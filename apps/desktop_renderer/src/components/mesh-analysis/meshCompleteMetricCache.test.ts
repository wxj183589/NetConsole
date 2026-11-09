import { describe, expect, it } from 'vitest'
import { MeshCompleteMetricCache } from './meshCompleteMetricCache'

const base = { time_from: '2026-11-09 10:00:00.000', time_to: '2026-11-09 10:10:00.000', radio: 1, ap: 'AP1', role: 'ACTIVE', include_zero: false }
const inside = { ...base, time_from: '2026-11-09 10:02:00.000', time_to: '2026-11-09 10:08:00.000' }
const complete = { items: [1, 2], total: 2, downsampled: false }

describe('complete MESH metric response cache', () => {
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
