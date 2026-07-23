import { describe, expect, it } from 'vitest'

import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import {
  buildTracksideSeriesCache,
  disposeTracksideSeriesCache,
  findTracksideFrameMetaIds,
  tracksidePointMeta,
} from './tracksideSeriesCache'

function point(timestamp: string, run: number, breakBefore = false): MeshTracksideSignalPointData {
  return {
    timestamp,
    timestamp_tag: '',
    source_file_id: 1,
    link_id: run,
    sample_id: run,
    local_radio: 1,
    role: 'ACTIVE',
    peer_mac: 'bc5a-3457-3a00',
    peer_ap_name: 'AP-1',
    peer_ap_mac: 'bc5a-3457-3000',
    peer_radio: 'Radio 1',
    peer_radio_mac: null,
    station: null,
    section: null,
    peer_rssi: 40 + run,
    local_rssi: 30 + run,
    peer_signal: null,
    local_signal: null,
    run_id: `run-${run}`,
    run_sequence: run,
    segment_duration_seconds: 1,
    break_before: breakBefore,
    data_source: 'peer_rssi_db',
  }
}

function series(points: MeshTracksideSignalPointData[]): MeshTracksideSignalSeriesData {
  return {
    series_id: 'ap-1:radio:1',
    peer_name: 'AP-1',
    peer_mac: 'bc5a-3457-3a00',
    ap_mac: 'bc5a-3457-3000',
    peer_radio_mac: null,
    radio: 1,
    station: null,
    section: null,
    roles_present: ['ACTIVE'],
    data_source: 'peer_rssi_db',
    total_points: points.length,
    returned_points: points.length,
    points,
  }
}

describe('trackside compact series cache', () => {
  it('builds numeric ECharts data without retaining point, series, or points-array references', () => {
    const first = point('2026-07-20 10:00:00.000', 1)
    const second = point('2026-07-20 10:00:02.000', 2, true)
    const source = series([first, second])
    const cache = buildTracksideSeriesCache([source])
    const [firstData, gapData, secondData] = cache.series[0].data

    expect(firstData).toEqual([Date.parse(first.timestamp), first.peer_rssi, 0, 0])
    expect(gapData).toEqual([Date.parse(second.timestamp), null, -1, -1])
    expect(secondData).toEqual([Date.parse(second.timestamp), second.peer_rssi, 1, 0])
    expect(firstData).not.toHaveProperty('meta')
    expect(firstData).not.toHaveProperty('seriesMeta')
    expect(cache.series[0].meta).not.toBe(source)
    expect(cache.series[0].meta).not.toHaveProperty('points')
    expect(tracksidePointMeta(cache, firstData[2])).toMatchObject({
      peerApName: 'AP-1',
      peerMac: first.peer_mac,
      role: 'ACTIVE',
      rssi: first.peer_rssi,
    })
    expect(tracksidePointMeta(cache, firstData[2])).not.toBe(first)
    expect(cache.dataIndexToMetaId.get(source.series_id)).toEqual([0, -1, 1])
    expect(JSON.stringify(cache.series.map((item) => item.data))).not.toContain('AP-1')
    expect(cache.totalRenderedPoints).toBe(2)
  })

  it('reports an unordered payload while preserving its original order for diagnostics', () => {
    const late = point('2026-07-20 10:00:02.000', 1)
    const early = point('2026-07-20 10:00:01.000', 1)
    const cache = buildTracksideSeriesCache([series([late, early])])
    expect(cache.unorderedSeriesIds).toEqual(['ap-1:radio:1'])
    expect(cache.series[0].data.map((item) => item[0])).toEqual([
      Date.parse(late.timestamp),
      Date.parse(early.timestamp),
    ])
  })

  it('keeps role changes in one link run and exposes point-level role codes', () => {
    const active = point('2026-07-20 10:00:00.000', 1)
    const standby = {
      ...point('2026-07-20 10:00:01.000', 1),
      role: 'STANDBY' as const,
    }
    const activeAgain = point('2026-07-20 10:00:02.000', 1)
    const cache = buildTracksideSeriesCache([{
      ...series([active, standby, activeAgain]),
      roles_present: ['ACTIVE', 'STANDBY'],
    }])

    expect(cache.series).toHaveLength(1)
    expect(cache.series[0].data.map((item) => item[1])).toEqual([
      active.peer_rssi,
      standby.peer_rssi,
      activeAgain.peer_rssi,
    ])
    expect(cache.series[0].data.map((item) => item[3])).toEqual([0, 1, 0])
    expect(cache.series[0].data.some((item) => item[1] === null)).toBe(false)
  })

  it('restores every ACTIVE and STANDBY point in one frame through the external index', () => {
    const timestamp = '2026-07-20 10:00:00.000'
    const active = point(timestamp, 1)
    const standby = { ...point(timestamp, 1), link_id: 2, role: 'STANDBY' as const }
    const cache = buildTracksideSeriesCache([
      series([active]),
      { ...series([standby]), series_id: 'ap-2:radio:1', peer_name: 'AP-2' },
    ])
    const metaIds = findTracksideFrameMetaIds(cache, Date.parse(timestamp))
    const roles = metaIds.map((metaId) => tracksidePointMeta(cache, metaId)?.role)
    expect(roles).toEqual(['ACTIVE', 'STANDBY'])
  })

  it('clears every retained collection when a session cache is released', () => {
    const cache = buildTracksideSeriesCache([series([point('2026-07-20 10:00:00.000', 1)])])
    disposeTracksideSeriesCache(cache)
    expect(cache.disposed).toBe(true)
    expect(cache.series).toEqual([])
    expect(cache.pointMetaById.size).toBe(0)
    expect(cache.seriesMetaById.size).toBe(0)
    expect(cache.dataIndexToMetaId.size).toBe(0)
    expect(cache.frameMetaIds.size).toBe(0)
    expect(cache.frameTimestamps).toEqual([])
    expect(cache.totalRenderedPoints).toBe(0)
  })

  it('builds the real 770-series / 44,251-point shape without recursive ECharts metadata', () => {
    const seriesCount = 770
    const pointCount = 44_251
    const frameCount = 18_188
    const source = Array.from({ length: seriesCount }, (_, index) => series([]))
    for (let index = 0; index < pointCount; index += 1) {
      const seriesIndex = index % seriesCount
      const frameIndex = Math.floor(index * frameCount / pointCount)
      source[seriesIndex].series_id = `ap-${seriesIndex}:radio:${seriesIndex % 2 + 1}`
      source[seriesIndex].peer_name = `AP-${seriesIndex}`
      source[seriesIndex].radio = seriesIndex % 2 + 1
      source[seriesIndex].points.push({
        ...point(new Date(Date.UTC(2026, 6, 20, 10, 0, 0, frameIndex)).toISOString(), index % 6_398),
        role: index % 3 === 0 ? 'STANDBY' : 'ACTIVE',
        peer_ap_name: `AP-${seriesIndex}`,
        peer_mac: `peer-${seriesIndex}`,
        run_id: `run-${index % 6_398}`,
      })
    }
    for (const item of source) {
      item.total_points = item.points.length
      item.returned_points = item.points.length
      item.roles_present = ['ACTIVE', 'STANDBY']
    }
    const rawSeries = source[0]
    const rawPoints = rawSeries.points
    const started = performance.now()
    const cache = buildTracksideSeriesCache(source)
    const buildMs = performance.now() - started
    const echartsDataJson = JSON.stringify(cache.series.map((item) => item.data))

    expect(cache.series).toHaveLength(seriesCount)
    expect(cache.totalRenderedPoints).toBe(pointCount)
    expect(cache.frameTimestamps).toHaveLength(frameCount)
    expect(cache.pointMetaById.size).toBe(pointCount)
    expect(cache.series[0]).not.toBe(rawSeries)
    expect(cache.series[0].data).not.toBe(rawPoints)
    expect(cache.series[0].meta).not.toHaveProperty('points')
    expect(echartsDataJson).not.toContain('seriesMeta')
    expect(echartsDataJson).not.toContain('peer_ap_name')
    expect(buildMs).toBeLessThan(5_000)

    disposeTracksideSeriesCache(cache)
    expect(cache.pointMetaById.size).toBe(0)
    expect(cache.series).toHaveLength(0)
  })

  it('releases ten consecutive session caches instead of retaining old payload indexes', () => {
    const released = []
    for (let sessionIndex = 0; sessionIndex < 10; sessionIndex += 1) {
      const cache = buildTracksideSeriesCache([
        series([point(`2026-07-20 10:00:${String(sessionIndex).padStart(2, '0')}.000`, sessionIndex)]),
      ])
      released.push(cache)
      disposeTracksideSeriesCache(cache)
    }
    expect(released.every((cache) => (
      cache.disposed
      && cache.series.length === 0
      && cache.pointMetaById.size === 0
      && cache.seriesMetaById.size === 0
      && cache.frameMetaIds.size === 0
    ))).toBe(true)
  })
})
