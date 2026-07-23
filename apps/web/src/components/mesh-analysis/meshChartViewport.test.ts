import { describe, expect, it } from 'vitest'

import {
  acceptMeshSharedViewport,
  createFullMeshViewport,
  normalizeMeshViewport,
  resolveMeshSharedTimeDomain,
  viewportFromDataZoom,
  viewportFromDataZoomWithOptions,
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

  it('keeps one exact absolute viewport for charts with different sample boundaries', () => {
    const domain = {
      full_start_time: '2026-07-20 09:00:00.000',
      full_end_time: '2026-07-20 12:00:00.000',
    }
    const requested = {
      start_time: '2026-07-20 10:00:00.500',
      end_time: '2026-07-20 10:00:03.500',
      start_percent: 0,
      end_percent: 100,
      ...domain,
      source: 'programmatic' as const,
    }
    const active = normalizeMeshViewport(requested, [
      '2026-07-20 10:00:00.000',
      '2026-07-20 10:00:02.000',
      '2026-07-20 10:00:04.000',
    ], 'programmatic', { boundaryMode: 'absolute', fullDomain: domain })
    const trackside = normalizeMeshViewport(requested, [
      '2026-07-20 10:00:01.000',
      '2026-07-20 10:00:03.000',
    ], 'programmatic', { boundaryMode: 'absolute', fullDomain: domain })

    expect(active).toMatchObject({
      start_time: requested.start_time,
      end_time: requested.end_time,
      full_start_time: requested.full_start_time,
      full_end_time: requested.full_end_time,
    })
    expect(trackside).toMatchObject({
      start_time: requested.start_time,
      end_time: requested.end_time,
      full_start_time: requested.full_start_time,
      full_end_time: requested.full_end_time,
    })
    expect(active?.start_percent).toBeCloseTo(trackside!.start_percent)
    expect(active?.end_percent).toBeCloseTo(trackside!.end_percent)
  })

  it('resolves dataZoom percentages against the shared full domain instead of local samples', () => {
    const domain = {
      full_start_time: '2026-07-20 09:00:00.000',
      full_end_time: '2026-07-20 12:00:00.000',
    }
    const viewport = viewportFromDataZoomWithOptions({ start: 50, end: 75 }, [
      '2026-07-20 10:00:01.000',
      '2026-07-20 10:00:03.000',
    ], {
      boundaryMode: 'absolute',
      fullDomain: domain,
      sourceChart: 'trackside-rssi',
      revision: 7,
    })
    expect(viewport).toMatchObject({
      start_time: '2026-07-20 10:30:00.000',
      end_time: '2026-07-20 11:15:00.000',
      ...domain,
      source_chart: 'trackside-rssi',
      revision: 7,
    })
  })

  it('uses valid session bounds before fallback chart timestamps', () => {
    expect(resolveMeshSharedTimeDomain(
      '2026-07-20 09:00:00.000',
      '2026-07-20 12:00:00.000',
      ['2026-07-20 10:00:00.000', '2026-07-20 10:00:04.000'],
    )).toEqual({
      full_start_time: '2026-07-20 09:00:00.000',
      full_end_time: '2026-07-20 12:00:00.000',
    })
  })

  it('accepts one effective source revision and ignores mirrored feedback with the same range', () => {
    const domain = {
      full_start_time: '2026-07-20 09:00:00.000',
      full_end_time: '2026-07-20 12:00:00.000',
    }
    const initial = {
      start_time: domain.full_start_time,
      end_time: domain.full_end_time,
      start_percent: 0,
      end_percent: 100,
      ...domain,
      source: 'initial' as const,
      source_chart: 'programmatic' as const,
      revision: 1,
    }
    const fromActive = acceptMeshSharedViewport(initial, {
      ...initial,
      start_time: '2026-07-20 10:00:00.500',
      end_time: '2026-07-20 10:00:03.500',
      source: 'user_zoom',
      source_chart: 'active-rssi',
      revision: 2,
    }, domain, 2)!
    expect(fromActive).not.toBe(initial)
    expect(fromActive).toMatchObject({ source_chart: 'active-rssi', revision: 2 })

    const mirrored = acceptMeshSharedViewport(fromActive, {
      ...fromActive,
      source_chart: 'trackside-rssi',
      revision: 3,
    }, domain, 3)
    expect(mirrored).toBe(fromActive)
  })
})
