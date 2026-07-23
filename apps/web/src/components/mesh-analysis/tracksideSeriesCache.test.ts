import { describe, expect, it } from 'vitest'

import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import { buildTracksideSeriesCache } from './tracksideSeriesCache'

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
    radio: 1,
    station: null,
    section: null,
    role: 'ACTIVE',
    data_source: 'peer_rssi_db',
    total_points: points.length,
    returned_points: points.length,
    points,
  }
}

describe('trackside immutable series cache', () => {
  it('builds run-preserving line data once without sorting the backend payload', () => {
    const first = point('2026-07-20 10:00:00.000', 1)
    const second = point('2026-07-20 10:00:02.000', 2, true)
    const cache = buildTracksideSeriesCache([series([first, second])])
    expect(cache.unorderedSeriesIds).toEqual([])
    expect(cache.series[0].data.map((item) => item.value)).toEqual([
      [first.timestamp, first.peer_rssi],
      [second.timestamp, null],
      [second.timestamp, second.peer_rssi],
    ])
    expect(cache.series[0].data[0].meta).toBe(first)
    expect(cache.totalRenderedPoints).toBe(2)
  })

  it('reports an unordered payload while preserving its original order for diagnostics', () => {
    const late = point('2026-07-20 10:00:02.000', 1)
    const early = point('2026-07-20 10:00:01.000', 1)
    const cache = buildTracksideSeriesCache([series([late, early])])
    expect(cache.unorderedSeriesIds).toEqual(['ap-1:radio:1'])
    expect(cache.series[0].data.map((item) => item.value[0])).toEqual([late.timestamp, early.timestamp])
  })
})
