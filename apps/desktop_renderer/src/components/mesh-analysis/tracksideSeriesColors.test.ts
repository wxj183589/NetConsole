import { describe, expect, it } from 'vitest'

import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import { buildTracksideSeriesCache } from './tracksideSeriesCache'
import {
  assignTracksideSeriesColors,
  createTracksideSeriesPalette,
  disposeTracksideSeriesColorAssignment,
  type TracksideSeriesColorAssignment,
} from './tracksideSeriesColors'

function point(
  timestamp: string,
  role: 'ACTIVE' | 'STANDBY',
  seriesId: string,
  runId = `run-${seriesId}`,
): MeshTracksideSignalPointData {
  return {
    timestamp,
    timestamp_tag: '',
    source_file_id: 1,
    link_id: 1,
    sample_id: 1,
    local_radio: 1,
    role,
    peer_mac: `peer-${seriesId}`,
    peer_ap_name: `AP-${seriesId}`,
    peer_ap_mac: `ap-${seriesId}`,
    peer_radio: 'Radio 1',
    peer_radio_mac: `radio-${seriesId}`,
    station: null,
    section: null,
    peer_rssi: 40,
    local_rssi: 38,
    peer_signal: null,
    local_signal: null,
    run_id: runId,
    run_sequence: 1,
    segment_duration_seconds: 1,
    break_before: false,
    data_source: 'peer_rssi_db',
  }
}

function series(
  seriesId: string,
  points: MeshTracksideSignalPointData[],
): MeshTracksideSignalSeriesData {
  return {
    series_id: seriesId,
    peer_name: `AP-${seriesId}`,
    peer_mac: `peer-${seriesId}`,
    ap_mac: `ap-${seriesId}`,
    peer_radio_mac: `radio-${seriesId}`,
    radio: 1,
    station: null,
    section: null,
    roles_present: ['ACTIVE', 'STANDBY'],
    data_source: 'peer_rssi_db',
    total_points: points.length,
    returned_points: points.length,
    points,
  }
}

function expectEveryConflictUsesDifferentColors(
  assignment: TracksideSeriesColorAssignment,
): void {
  for (const [seriesId, neighbors] of assignment.conflictsBySeriesId) {
    for (const neighbor of neighbors) {
      expect(assignment.colorBySeriesId.get(seriesId)).not.toBe(
        assignment.colorBySeriesId.get(neighbor),
      )
    }
  }
}

describe('trackside conflict-aware series colors', () => {
  it('separates same-frame and adjacent-frame APs while preserving role changes', () => {
    const first = '2026-07-20T10:00:00.000Z'
    const second = '2026-07-20T10:00:01.000Z'
    const cache = buildTracksideSeriesCache([
      series('A', [point(first, 'ACTIVE', 'A'), point(second, 'STANDBY', 'A')]),
      series('B', [point(first, 'STANDBY', 'B'), point(second, 'ACTIVE', 'B')]),
      series('C', [point(first, 'STANDBY', 'C')]),
      series('D', [point(second, 'STANDBY', 'D')]),
    ])
    const assignment = assignTracksideSeriesColors(cache, createTracksideSeriesPalette())

    for (const [left, right] of [
      ['A', 'B'],
      ['A', 'C'],
      ['B', 'C'],
      ['B', 'D'],
      ['A', 'D'],
    ]) expect(assignment.colorBySeriesId.get(left)).not.toBe(assignment.colorBySeriesId.get(right))
    expectEveryConflictUsesDifferentColors(assignment)

    const rebuilt = assignTracksideSeriesColors(cache, createTracksideSeriesPalette())
    expect([...rebuilt.colorBySeriesId]).toEqual([...assignment.colorBySeriesId])
  })

  it('separates overlapping runs but allows distant unrelated APs to reuse a color', () => {
    const overlapCache = buildTracksideSeriesCache([
      series('X', [
        point('2026-07-20T10:00:00.000Z', 'ACTIVE', 'X'),
        point('2026-07-20T10:01:00.000Z', 'ACTIVE', 'X'),
      ]),
      series('Y', [point('2026-07-20T10:00:30.000Z', 'STANDBY', 'Y')]),
    ])
    const overlap = assignTracksideSeriesColors(overlapCache, createTracksideSeriesPalette())
    expect(overlap.colorBySeriesId.get('X')).not.toBe(overlap.colorBySeriesId.get('Y'))

    const distantCache = buildTracksideSeriesCache([
      series('X', [point('2026-07-20T13:00:00.000Z', 'ACTIVE', 'X')]),
      series('Y', [point('2026-07-20T16:00:00.000Z', 'ACTIVE', 'Y')]),
    ])
    const distant = assignTracksideSeriesColors(distantCache, createTracksideSeriesPalette())
    expect(distant.colorBySeriesId.get('X')).toBe(distant.colorBySeriesId.get('Y'))
  })

  it.each([
    { seriesCount: 481, pointCount: 7_549, targetMs: 50 },
    { seriesCount: 770, pointCount: 44_251, targetMs: 100 },
  ])('colors $seriesCount series / $pointCount points within the target', ({
    seriesCount,
    pointCount,
    targetMs,
  }) => {
    const groupSize = 10
    const basePointCount = Math.floor(pointCount / seriesCount)
    const remainder = pointCount % seriesCount
    const source = Array.from({ length: seriesCount }, (_, seriesIndex) => {
      const startMillis = Date.UTC(2026, 6, 20, 10, Math.floor(seriesIndex / groupSize))
      const count = basePointCount + (seriesIndex < remainder ? 1 : 0)
      return series(
        `series-${seriesIndex}`,
        Array.from({ length: count }, (_, pointIndex) => point(
          new Date(startMillis + pointIndex * 1_000).toISOString(),
          pointIndex % 3 === 0 ? 'STANDBY' : 'ACTIVE',
          `series-${seriesIndex}`,
        )),
      )
    })
    const cache = buildTracksideSeriesCache(source)
    const started = performance.now()
    const assignment = assignTracksideSeriesColors(cache, createTracksideSeriesPalette())
    const elapsed = performance.now() - started
    const effectiveTargetMs = targetMs * (process.env.CI ? 2 : 1)
    console.info(
      `trackside colors: series=${seriesCount} points=${pointCount} edges=${assignment.conflictEdgeCount} `
      + `colors=${assignment.usedColorCount} graph=${assignment.conflictGraphBuildMs.toFixed(3)}ms `
      + `assignment=${assignment.colorAssignmentMs.toFixed(3)}ms total=${assignment.totalMs.toFixed(3)}ms `
      + `measured=${elapsed.toFixed(3)}ms target=${effectiveTargetMs}ms`,
    )

    expectEveryConflictUsesDifferentColors(assignment)
    expect(assignment.colorBySeriesId.size).toBe(seriesCount)
    expect(assignment.totalMs).toBeLessThan(effectiveTargetMs)
  })

  it('clears the conflict graph and color maps when a chart is disposed', () => {
    const cache = buildTracksideSeriesCache([
      series('A', [point('2026-07-20T10:00:00.000Z', 'ACTIVE', 'A')]),
      series('B', [point('2026-07-20T10:00:00.000Z', 'STANDBY', 'B')]),
    ])
    const assignment = assignTracksideSeriesColors(cache, createTracksideSeriesPalette())
    expect(assignment.conflictEdgeCount).toBeGreaterThan(0)

    disposeTracksideSeriesColorAssignment(assignment)

    expect(assignment.colorBySeriesId.size).toBe(0)
    expect(assignment.colorIndexBySeriesId.size).toBe(0)
    expect(assignment.conflictsBySeriesId.size).toBe(0)
    expect(assignment.conflictEdgeCount).toBe(0)
  })
})
