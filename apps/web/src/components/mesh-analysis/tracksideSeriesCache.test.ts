import { describe, expect, it } from 'vitest'

import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import {
  buildTracksideSeriesCache,
  disposeTracksideSeriesCache,
  findNearestTracksideFrameTimestamp,
  findTracksideFrameMetaIds,
  tracksidePointMeta,
  tracksideViewportSeriesItems,
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

  it('matches the nearest real frame within the payload-derived tolerance', () => {
    const realFrame = '2024-10-22 14:46:33.852'
    const cache = buildTracksideSeriesCache([series([
      point('2024-10-22 14:46:32.852', 1),
      point(realFrame, 1),
      point('2024-10-22 14:46:34.852', 1),
    ])])

    expect(cache.medianFrameIntervalMs).toBe(1_000)
    expect(cache.frameMatchToleranceMs).toBe(750)
    expect(findNearestTracksideFrameTimestamp(
      cache,
      Date.parse('2024-10-22 14:46:33.607'),
    )).toBe(Date.parse(realFrame))
    expect(findNearestTracksideFrameTimestamp(
      cache,
      Date.parse('2024-10-22 14:46:36.000'),
    )).toBeNull()
  })

  it('finds only viewport series with inclusive boundaries and pointer-or-latest RSSI values', () => {
    const start = Date.parse('2026-07-20 10:00:10.000')
    const end = Date.parse('2026-07-20 10:00:20.000')
    const source = [
      { ...series([point('2026-07-20 10:00:09.000', 1)]), series_id: 'ap-a', peer_name: 'AP-A' },
      { ...series([point('2026-07-20 10:00:10.000', 2)]), series_id: 'ap-b', peer_name: 'AP-B' },
      {
        ...series([{
          ...point('2026-07-20 10:00:15.000', 3),
          peer_rssi: null,
          peer_signal: 35,
        }]),
        series_id: 'ap-c',
        peer_name: 'AP-C',
      },
      { ...series([point('2026-07-20 10:00:20.001', 4)]), series_id: 'ap-d', peer_name: 'AP-D' },
    ]
    const cache = buildTracksideSeriesCache(source)

    const latest = tracksideViewportSeriesItems(cache, start, end)
    expect(latest.map((item) => item.seriesId)).toEqual(['ap-b', 'ap-c'])
    expect(latest.map((item) => item.rssi)).toEqual([42, 35])
    expect(latest.every((item) => item.rssiSource === 'latest')).toBe(true)

    const pointer = tracksideViewportSeriesItems(cache, start, end, Date.parse('2026-07-20 10:00:15.000'))
    expect(pointer.find((item) => item.seriesId === 'ap-c')).toMatchObject({
      rssi: 35,
      rssiSource: 'pointer',
    })
  })

  it('keeps missing trackside RSSI empty and retains peer radio identity only inside the cache', () => {
    const missing = {
      ...point('2026-07-20 10:00:00.000', 1),
      peer_rssi: null,
      peer_signal: null,
      peer_radio_mac: 'bc5a-3457-3a0f',
    }
    const first = {
      ...series([missing]),
      series_id: 'radio-bssid-a',
      peer_radio_mac: 'bc5a-3457-3a0f',
    }
    const second = {
      ...series([{ ...missing, peer_radio_mac: 'bc5a-3457-3a1f' }]),
      series_id: 'radio-bssid-b',
      peer_radio_mac: 'bc5a-3457-3a1f',
    }
    const cache = buildTracksideSeriesCache([first, second])
    const items = tracksideViewportSeriesItems(
      cache,
      Date.parse('2026-07-20 10:00:00.000'),
      Date.parse('2026-07-20 10:00:00.000'),
    )

    expect(cache.series).toHaveLength(2)
    expect(cache.seriesMetaById.get(first.series_id)?.peerRadioMac).toBe(first.peer_radio_mac)
    expect(cache.seriesMetaById.get(second.series_id)?.peerRadioMac).toBe(second.peer_radio_mac)
    expect(items).toHaveLength(2)
    expect(items.every((item) => item.rssi === null)).toBe(true)
    expect(items[0]).not.toHaveProperty('peerRadioMac')
    expect(items[0]).not.toHaveProperty('peerMac')
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
    expect(cache.medianFrameIntervalMs).toBe(0)
    expect(cache.frameMatchToleranceMs).toBe(500)
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

  it('computes 100 viewport lists for 481 sorted series without rebuilding chart data', () => {
    const source = Array.from({ length: 481 }, (_, seriesIndex) => ({
      ...series(Array.from({ length: 24 }, (_, pointIndex) => ({
        ...point(new Date(Date.UTC(2026, 6, 20, 10, 0, pointIndex)).toISOString(), 1),
        peer_ap_name: `AP-${seriesIndex}`,
      }))),
      series_id: `series-${seriesIndex}`,
      peer_name: `AP-${seriesIndex}`,
    }))
    const cache = buildTracksideSeriesCache(source)
    const firstDataReference = cache.series[0].data
    const started = performance.now()
    let visibleCount = 0
    for (let index = 0; index < 100; index += 1) {
      visibleCount = tracksideViewportSeriesItems(
        cache,
        Date.parse('2026-07-20T10:00:08.000Z'),
        Date.parse('2026-07-20T10:00:12.000Z'),
      ).length
    }
    const computeMs = performance.now() - started
    console.info(`trackside viewport list profile: totalSeries=481 visibleSeriesInViewport=${visibleCount} compute100=${computeMs.toFixed(3)}ms`)

    expect(visibleCount).toBe(481)
    expect(cache.series[0].data).toBe(firstDataReference)
    expect(computeMs).toBeLessThan(2_000)
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
