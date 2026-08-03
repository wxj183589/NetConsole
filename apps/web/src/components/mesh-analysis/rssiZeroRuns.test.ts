import { describe, expect, it } from 'vitest'

import type { MeshRssiZeroRun } from '../../types/meshAnalysis'
import { buildRssiDisplayPoints, type RssiDisplaySource } from './rssiZeroRuns'

interface PointMeta { id: number }

function zeroRun(
  state: MeshRssiZeroRun['state'],
  boundary: MeshRssiZeroRun['boundary'],
  startTime: string,
  endTime: string,
  durationMs: number,
  sampleCount = 1,
): MeshRssiZeroRun {
  return {
    state,
    boundary,
    start_time: startTime,
    end_time: endTime,
    duration_ms: durationMs,
    sample_count: sampleCount,
    estimated_end: false,
  }
}

function point(id: number, timestamp: string, value: number | null): RssiDisplaySource<PointMeta> {
  return { timestamp, value, meta: { id } }
}

describe('RSSI zero-run display points', () => {
  it('removes short zeros and directly joins the surrounding valid samples', () => {
    const source = [
      point(1, '2026-07-24 20:41:20.000', 35),
      {
        ...point(2, '2026-07-24 20:41:20.984', 0),
        zeroRun: zeroRun('suppressed', 'single', '2026-07-24 20:41:20.984', '2026-07-24 20:41:21.968', 984),
      },
      point(3, '2026-07-24 20:41:21.968', 38),
    ]

    const result = buildRssiDisplayPoints(source)

    expect(result.map((item) => item.value)).toEqual([35, 38])
    expect(result.map((item) => item.meta.id)).toEqual([1, 3])
    expect(source[1].value).toBe(0)
  })

  it('compresses a sustained zero run to its exact start and end times', () => {
    const start = '2026-07-24 20:41:21.000'
    const end = '2026-07-24 20:41:24.000'
    const source = [
      point(1, '2026-07-24 20:41:20.000', 35),
      { ...point(2, start, 0), zeroRun: zeroRun('sustained', 'start', start, end, 3_000, 3) },
      { ...point(3, '2026-07-24 20:41:22.000', 0), zeroRun: zeroRun('sustained', 'middle', start, end, 3_000, 3) },
      { ...point(4, '2026-07-24 20:41:23.000', 0), zeroRun: zeroRun('sustained', 'end', start, end, 3_000, 3) },
      point(5, end, 38),
    ]

    const result = buildRssiDisplayPoints(source)

    expect(result.map((item) => [item.timestamp, item.value])).toEqual([
      ['2026-07-24 20:41:20.000', 35],
      [start, 0],
      [end, 0],
      [end, 38],
    ])
    expect(result[2].syntheticEnd).toBe(true)
  })

  it('keeps ordinary missing values and carries a hidden zero break to the next visible point', () => {
    const short = zeroRun('suppressed', 'single', '2026-07-24 20:41:21.000', '2026-07-24 20:41:22.000', 1_000)
    const result = buildRssiDisplayPoints([
      point(1, '2026-07-24 20:41:20.000', 35),
      { ...point(2, '2026-07-24 20:41:21.000', 0), zeroRun: short, breakBefore: true },
      point(3, '2026-07-24 20:41:22.000', null),
      point(4, '2026-07-24 20:41:23.000', 38),
    ])

    expect(result.map((item) => item.value)).toEqual([35, null, 38])
    expect(result[1].breakBefore).toBe(true)
  })

  it('handles 100,000 points in one pass and removes every short zero', () => {
    const short = zeroRun('suppressed', 'single', 'start', 'end', 1_000)
    const source = Array.from({ length: 100_000 }, (_, index) => ({
      ...point(index, new Date(Date.UTC(2026, 6, 24, 0, 0, index)).toISOString(), index % 10 === 1 ? 0 : 40),
      zeroRun: index % 10 === 1 ? short : null,
    }))

    const result = buildRssiDisplayPoints(source)

    expect(result).toHaveLength(90_000)
    expect(result.every((item) => item.value !== 0)).toBe(true)
  })
})
