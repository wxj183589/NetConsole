import { performance } from 'node:perf_hooks'

import { describe, expect, it } from 'vitest'

import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'
import type { NetConsoleChartTokens } from '../../theme/echarts'
import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import { buildTracksideSeriesCache } from './tracksideSeriesCache'

const SERIES_COUNT = 140
const POINT_COUNT = 14_581
const RUN_COUNT = 6_264
const PERFORMANCE_BUDGET_MULTIPLIER = process.env.CI ? 2 : 1

const theme: NetConsoleChartTokens = {
  series: ['#1677ff', '#52c41a', '#faad14', '#ff4d4f', '#909399'],
  text: '#fff',
  textSecondary: '#aaa',
  background: '#18212d',
  backgroundMuted: '#101820',
  border: '#344054',
  splitLine: '#273548',
  active: '#12395a',
  primary: '#1677ff',
  warning: '#faad14',
  danger: '#ff4d4f',
  info: '#909399',
}

function fixture(): MeshTracksideSignalSeriesData[] {
  let remaining = POINT_COUNT
  let globalIndex = 0
  return Array.from({ length: SERIES_COUNT }, (_, seriesIndex) => {
    const count = Math.floor(remaining / (SERIES_COUNT - seriesIndex))
    remaining -= count
    let previousRun = -1
    const points = Array.from({ length: count }, (_, pointIndex) => {
      const runSequence = Math.min(RUN_COUNT, Math.floor(globalIndex * RUN_COUNT / POINT_COUNT) + 1)
      const date = new Date(Date.UTC(2026, 6, 20, 9, 0, seriesIndex, pointIndex))
      const timestamp = date.toISOString()
      const point: MeshTracksideSignalPointData = {
        timestamp,
        timestamp_tag: '',
        source_file_id: 1,
        link_id: globalIndex + 1,
        sample_id: globalIndex + 1,
        local_radio: seriesIndex % 2 + 1,
        role: globalIndex % 4 === 0 ? 'ACTIVE' : 'STANDBY',
        peer_mac: `bc5a-3457-${String(seriesIndex).padStart(4, '0')}`,
        peer_ap_name: `AP-${seriesIndex}`,
        peer_ap_mac: `3052-77a8-${String(seriesIndex).padStart(4, '0')}`,
        peer_radio: `Radio ${seriesIndex % 2 + 1}`,
        peer_radio_mac: null,
        station: null,
        section: null,
        peer_rssi: 20 + globalIndex % 30,
        local_rssi: 22 + globalIndex % 30,
        peer_signal: null,
        local_signal: null,
        run_id: `run-${runSequence}`,
        run_sequence: runSequence,
        segment_duration_seconds: 1,
        break_before: previousRun !== -1 && previousRun !== runSequence,
        data_source: 'peer_rssi_db',
      }
      previousRun = runSequence
      globalIndex += 1
      return point
    })
    return {
      series_id: `series-${seriesIndex}`,
      peer_name: `AP-${seriesIndex}`,
      peer_mac: points[0]?.peer_mac || null,
      ap_mac: points[0]?.peer_ap_mac || null,
      peer_radio_mac: points[0]?.peer_radio_mac || null,
      radio: seriesIndex % 2 + 1,
      station: null,
      section: null,
      roles_present: ['ACTIVE', 'STANDBY'],
      data_source: 'peer_rssi_db',
      total_points: points.length,
      returned_points: points.length,
      points,
    }
  })
}

function legacyRepeatedTransform(payload: MeshTracksideSignalSeriesData[]): number {
  return payload.map((series) => [...series.points]
    .sort((left, right) => left.timestamp.localeCompare(right.timestamp) || left.timestamp_tag.localeCompare(right.timestamp_tag))
    .map((point) => ({ value: [point.timestamp, point.peer_rssi ?? point.peer_signal ?? null], meta: point })))
    .reduce((total, points) => total + points.length, 0)
}

describe('trackside chart fixed-scale performance', () => {
  it('builds the 140-series immutable cache below one 200 ms main-thread budget', () => {
    const payload = fixture()
    const legacyStarted = performance.now()
    expect(legacyRepeatedTransform(payload)).toBe(POINT_COUNT)
    const legacyRepeatedTransformMs = performance.now() - legacyStarted
    const heapBefore = process.memoryUsage().heapUsed
    const transformStarted = performance.now()
    const cache = buildTracksideSeriesCache(payload)
    const payloadTransformMs = performance.now() - transformStarted
    const heapDeltaBytes = process.memoryUsage().heapUsed - heapBefore

    const optionStarted = performance.now()
    createMultiSeriesTimeChartBaseOption(theme, {
      unit: 'dBm',
      pointCount: cache.totalRenderedPoints,
      fullDomain: {
        full_start_time: '2026-07-20 09:00:00.000',
        full_end_time: '2026-07-20 12:00:00.000',
      },
      viewport: {
        start_time: '2026-07-20 10:00:00.500',
        end_time: '2026-07-20 10:00:03.500',
      },
    })
    const baseOptionBuildMs = performance.now() - optionStarted

    console.info('TRACKSIDE_CHART_PROFILE', JSON.stringify({
      series_count: cache.series.length,
      point_count: cache.totalRenderedPoints,
      run_count: RUN_COUNT,
      legacy_repeated_transform_ms: Number(legacyRepeatedTransformMs.toFixed(3)),
      payload_transform_ms: Number(payloadTransformMs.toFixed(3)),
      base_option_build_ms: Number(baseOptionBuildMs.toFixed(3)),
      heap_delta_bytes: heapDeltaBytes,
      performance_budget_multiplier: PERFORMANCE_BUDGET_MULTIPLIER,
    }))

    expect(cache.series).toHaveLength(SERIES_COUNT)
    expect(cache.totalRenderedPoints).toBe(POINT_COUNT)
    expect(cache.unorderedSeriesIds).toEqual([])
    expect(payloadTransformMs).toBeLessThan(200 * PERFORMANCE_BUDGET_MULTIPLIER)
    expect(baseOptionBuildMs).toBeLessThan(50 * PERFORMANCE_BUDGET_MULTIPLIER)
    expect(heapDeltaBytes).toBeLessThan(64 * 1024 * 1024)
  })
})
