import { describe, expect, it } from 'vitest'

import {
  createFullMeshViewport,
  normalizeMeshViewport,
  viewportFromDataZoom,
  visibleMeshSamples,
} from './meshChartViewport'

const timestamps = [
  '2026-07-20 14:31:20.181',
  '2026-07-20 14:31:55.181',
  '2026-07-20 14:32:30.181',
  '2026-07-20 14:33:05.620',
]

describe('MESH chart viewport', () => {
  it('resolves direct and batched datazoom events to real millisecond sample times', () => {
    expect(viewportFromDataZoom({ start: 20, end: 80 }, timestamps)).toMatchObject({
      start_time: timestamps[1],
      end_time: timestamps[2],
      source: 'user_zoom',
    })
    expect(viewportFromDataZoom({ batch: [{ startValue: timestamps[1], endValue: timestamps[3] }] }, timestamps)).toMatchObject({
      start_time: timestamps[1],
      end_time: timestamps[3],
      source: 'user_zoom',
    })
  })

  it('clips stale ranges to the current data without dropping milliseconds', () => {
    const full = createFullMeshViewport(timestamps)!
    const clipped = normalizeMeshViewport({
      ...full,
      start_time: '2026-07-20 14:30:00.000',
      end_time: '2026-07-20 14:32:30.181',
    }, timestamps)
    expect(clipped?.start_time).toBe(timestamps[0])
    expect(clipped?.end_time).toBe(timestamps[2])
    expect(visibleMeshSamples(timestamps.map((timestamp) => ({ timestamp })), clipped!)).toHaveLength(3)
  })
})
