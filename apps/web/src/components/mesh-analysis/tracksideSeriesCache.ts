import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'

export interface RenderedTracksideSignalPoint {
  value: [string, number | null]
  meta?: MeshTracksideSignalPointData
  seriesMeta?: MeshTracksideSignalSeriesData
}

export interface RenderedTracksideSignalSeries {
  id: string
  name: string
  data: RenderedTracksideSignalPoint[]
  meta: MeshTracksideSignalSeriesData
  pointCount: number
}

export interface TracksideSeriesCache {
  series: RenderedTracksideSignalSeries[]
  timestamps: string[]
  totalRenderedPoints: number
  unorderedSeriesIds: string[]
}

function seriesLabel(series: MeshTracksideSignalSeriesData): string {
  const base = series.peer_name || series.peer_mac || '轨旁 AP 未知'
  const radio = series.radio == null ? '—' : series.radio
  return `${base} · Radio ${radio}`
}

export function tracksidePointValue(point: MeshTracksideSignalPointData): number | null {
  return point.peer_rssi ?? point.peer_signal ?? null
}

export function buildTracksideSeriesCache(
  sourceSeries: readonly MeshTracksideSignalSeriesData[],
): TracksideSeriesCache {
  const timestamps: string[] = []
  const unorderedSeriesIds: string[] = []
  let totalRenderedPoints = 0
  const series = sourceSeries.map((item) => {
    const rendered: RenderedTracksideSignalPoint[] = []
    let previousRunId: string | null = null
    let previousTimestamp = ''
    let ordered = true
    for (const point of item.points) {
      if (
        previousTimestamp
        && (
          point.timestamp < previousTimestamp
          || (point.timestamp === previousTimestamp && point.timestamp_tag < (rendered.at(-1)?.meta?.timestamp_tag || ''))
        )
      ) ordered = false
      const currentRunId = point.run_id ?? (point.run_sequence == null ? null : `${item.series_id}:${point.run_sequence}`)
      if (
        rendered.length
        && point.break_before
        && (currentRunId == null || currentRunId !== previousRunId)
      ) {
        rendered.push({ value: [point.timestamp, null] })
      }
      rendered.push({
        value: [point.timestamp, tracksidePointValue(point)],
        meta: point,
        seriesMeta: item,
      })
      timestamps.push(point.timestamp)
      previousRunId = currentRunId
      previousTimestamp = point.timestamp
      totalRenderedPoints += 1
    }
    if (!ordered) unorderedSeriesIds.push(item.series_id)
    return {
      id: item.series_id,
      name: seriesLabel(item),
      data: rendered,
      meta: item,
      pointCount: item.points.length,
    }
  })
  return {
    series,
    timestamps,
    totalRenderedPoints,
    unorderedSeriesIds,
  }
}
