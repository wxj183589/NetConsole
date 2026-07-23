import type {
  MeshTracksideSignalPointData,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import { meshTimestampMillis } from './meshChartViewport'

export type TracksideRoleCode = -1 | 0 | 1
export type CompactTracksideChartPoint = [
  timestampMillis: number,
  rssi: number | null,
  metaId: number,
  roleCode: TracksideRoleCode,
]

export interface CompactTracksidePointMeta {
  metaId: number
  seriesId: string
  timestampMillis: number
  timestampTag: string
  sourceFileId: number | null
  linkId: number | null
  sampleId: number | null
  localRadio: number | null
  role: 'ACTIVE' | 'STANDBY'
  peerMac: string | null
  peerApName: string | null
  peerApMac: string | null
  peerRadio: string | null
  peerRadioMac: string | null
  station: string | null
  section: string | null
  rssi: number | null
  localRssi: number | null
  peerSignal: number | null
  localSignal: number | null
  runId: string | null
  segmentDurationSeconds: number | null
  dataSource: string
}

export interface CompactTracksideSeriesMeta {
  seriesId: string
  name: string
  peerName: string | null
  peerMac: string | null
  apMac: string | null
  peerRadioMac: string | null
  radio: number | null
  station: string | null
  section: string | null
  pointCount: number
}

export interface RenderedTracksideSignalSeries {
  id: string
  name: string
  data: CompactTracksideChartPoint[]
  meta: CompactTracksideSeriesMeta
  pointCount: number
  firstTimestampMillis: number | null
  lastTimestampMillis: number | null
}

export interface TracksideViewportSeriesItem {
  seriesId: string
  metaId: number
  timestampMillis: number
  apName: string | null
  apMac: string | null
  radio: number | null
  rssi: number | null
  rssiSource: 'pointer' | 'latest'
}

export interface TracksideSeriesCache {
  series: RenderedTracksideSignalSeries[]
  totalRenderedPoints: number
  unorderedSeriesIds: string[]
  pointMetaById: ReadonlyMap<number, CompactTracksidePointMeta>
  seriesMetaById: ReadonlyMap<string, CompactTracksideSeriesMeta>
  dataIndexToMetaId: ReadonlyMap<string, readonly number[]>
  frameMetaIds: ReadonlyMap<number, readonly number[]>
  frameTimestamps: number[]
  medianFrameIntervalMs: number
  frameMatchToleranceMs: number
  firstTimestampMillis: number | null
  lastTimestampMillis: number | null
  disposed: boolean
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
  const pointMetaById = new Map<number, CompactTracksidePointMeta>()
  const seriesMetaById = new Map<string, CompactTracksideSeriesMeta>()
  const dataIndexToMetaId = new Map<string, number[]>()
  const frameMetaIds = new Map<number, number[]>()
  const unorderedSeriesIds: string[] = []
  let totalRenderedPoints = 0
  let nextMetaId = 0
  let firstTimestampMillis: number | null = null
  let lastTimestampMillis: number | null = null

  const series = sourceSeries.map((item) => {
    const rendered: CompactTracksideChartPoint[] = []
    const metaIds: number[] = []
    let seriesFirstTimestampMillis: number | null = null
    let seriesLastTimestampMillis: number | null = null
    const compactSeries: CompactTracksideSeriesMeta = {
      seriesId: item.series_id,
      name: seriesLabel(item),
      peerName: item.peer_name,
      peerMac: item.peer_mac,
      apMac: item.ap_mac,
      peerRadioMac: item.peer_radio_mac,
      radio: item.radio,
      station: item.station,
      section: item.section,
      pointCount: item.points.length,
    }
    seriesMetaById.set(item.series_id, compactSeries)
    let previousRunId: string | null = null
    let previousTimestampMillis: number | null = null
    let previousTimestampTag = ''
    let ordered = true
    for (const point of item.points) {
      const timestampMillis = meshTimestampMillis(point.timestamp)
      if (timestampMillis === null) continue
      if (
        previousTimestampMillis !== null
        && (
          timestampMillis < previousTimestampMillis
          || (timestampMillis === previousTimestampMillis && point.timestamp_tag < previousTimestampTag)
        )
      ) ordered = false
      const currentRunId = point.run_id
        ?? (point.run_sequence == null ? null : `${item.series_id}:${point.run_sequence}`)
      if (
        rendered.length
        && point.break_before
        && (currentRunId == null || currentRunId !== previousRunId)
      ) {
        rendered.push([timestampMillis, null, -1, -1])
        metaIds.push(-1)
      }
      const metaId = nextMetaId++
      const value = tracksidePointValue(point)
      const roleCode: TracksideRoleCode = point.role === 'ACTIVE' ? 0 : 1
      rendered.push([timestampMillis, value, metaId, roleCode])
      metaIds.push(metaId)
      pointMetaById.set(metaId, {
        metaId,
        seriesId: item.series_id,
        timestampMillis,
        timestampTag: point.timestamp_tag,
        sourceFileId: point.source_file_id,
        linkId: point.link_id,
        sampleId: point.sample_id,
        localRadio: point.local_radio,
        role: point.role,
        peerMac: point.peer_mac,
        peerApName: point.peer_ap_name,
        peerApMac: point.peer_ap_mac,
        peerRadio: point.peer_radio,
        peerRadioMac: point.peer_radio_mac,
        station: point.station,
        section: point.section,
        rssi: value,
        localRssi: point.local_rssi,
        peerSignal: point.peer_signal,
        localSignal: point.local_signal,
        runId: currentRunId,
        segmentDurationSeconds: point.segment_duration_seconds,
        dataSource: point.data_source,
      })
      const frame = frameMetaIds.get(timestampMillis)
      if (frame) frame.push(metaId)
      else frameMetaIds.set(timestampMillis, [metaId])
      firstTimestampMillis = firstTimestampMillis === null
        ? timestampMillis
        : Math.min(firstTimestampMillis, timestampMillis)
      lastTimestampMillis = lastTimestampMillis === null
        ? timestampMillis
        : Math.max(lastTimestampMillis, timestampMillis)
      seriesFirstTimestampMillis = seriesFirstTimestampMillis === null
        ? timestampMillis
        : Math.min(seriesFirstTimestampMillis, timestampMillis)
      seriesLastTimestampMillis = seriesLastTimestampMillis === null
        ? timestampMillis
        : Math.max(seriesLastTimestampMillis, timestampMillis)
      previousRunId = currentRunId
      previousTimestampMillis = timestampMillis
      previousTimestampTag = point.timestamp_tag
      totalRenderedPoints += 1
    }
    if (!ordered) unorderedSeriesIds.push(item.series_id)
    dataIndexToMetaId.set(item.series_id, metaIds)
    return {
      id: item.series_id,
      name: compactSeries.name,
      data: rendered,
      meta: compactSeries,
      pointCount: item.points.length,
      firstTimestampMillis: seriesFirstTimestampMillis,
      lastTimestampMillis: seriesLastTimestampMillis,
    }
  })

  const frameTimestamps = [...frameMetaIds.keys()].sort((left, right) => left - right)
  const medianFrameIntervalMs = medianTracksideFrameIntervalMs(frameTimestamps)
  return {
    series,
    totalRenderedPoints,
    unorderedSeriesIds,
    pointMetaById,
    seriesMetaById,
    dataIndexToMetaId,
    frameMetaIds,
    frameTimestamps,
    medianFrameIntervalMs,
    frameMatchToleranceMs: tracksideFrameMatchToleranceMs(medianFrameIntervalMs),
    firstTimestampMillis,
    lastTimestampMillis,
    disposed: false,
  }
}

export function medianTracksideFrameIntervalMs(
  frameTimestamps: readonly number[],
): number {
  if (frameTimestamps.length < 2) return 0
  const intervals: number[] = []
  for (let index = 1; index < frameTimestamps.length; index += 1) {
    const interval = frameTimestamps[index] - frameTimestamps[index - 1]
    if (interval > 0 && Number.isFinite(interval)) intervals.push(interval)
  }
  if (!intervals.length) return 0
  intervals.sort((left, right) => left - right)
  const middle = intervals.length >>> 1
  return intervals.length % 2 === 0
    ? (intervals[middle - 1] + intervals[middle]) / 2
    : intervals[middle]
}

export function tracksideFrameMatchToleranceMs(medianFrameIntervalMs: number): number {
  const candidate = Number.isFinite(medianFrameIntervalMs) && medianFrameIntervalMs > 0
    ? medianFrameIntervalMs * 0.75
    : 500
  return Math.max(500, Math.min(3_000, candidate))
}

export function findNearestTracksideFrameTimestamp(
  cache: TracksideSeriesCache,
  pointerMillis: number,
  maximumToleranceMs = cache.frameMatchToleranceMs,
): number | null {
  if (!Number.isFinite(pointerMillis) || !cache.frameTimestamps.length) return null
  let low = 0
  let high = cache.frameTimestamps.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (cache.frameTimestamps[middle] < pointerMillis) low = middle + 1
    else high = middle
  }
  const after = cache.frameTimestamps[low]
  const before = low > 0 ? cache.frameTimestamps[low - 1] : undefined
  const matched = before === undefined
    ? after
    : after === undefined
      ? before
      : pointerMillis - before <= after - pointerMillis ? before : after
  return matched !== undefined && Math.abs(matched - pointerMillis) <= maximumToleranceMs
    ? matched
    : null
}

export function findTracksideFrameMetaIds(
  cache: TracksideSeriesCache,
  timestampMillis: number,
): readonly number[] {
  let low = 0
  let high = cache.frameTimestamps.length - 1
  while (low <= high) {
    const middle = (low + high) >>> 1
    const candidate = cache.frameTimestamps[middle]
    if (candidate === timestampMillis) return cache.frameMetaIds.get(candidate) ?? []
    if (candidate < timestampMillis) low = middle + 1
    else high = middle - 1
  }
  return []
}

export function tracksidePointMeta(
  cache: TracksideSeriesCache,
  metaId: number,
): CompactTracksidePointMeta | undefined {
  return metaId < 0 ? undefined : cache.pointMetaById.get(metaId)
}

function lowerBoundTracksidePoint(
  data: readonly CompactTracksideChartPoint[],
  timestampMillis: number,
): number {
  let low = 0
  let high = data.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (data[middle][0] < timestampMillis) low = middle + 1
    else high = middle
  }
  return low
}

function upperBoundTracksidePoint(
  data: readonly CompactTracksideChartPoint[],
  timestampMillis: number,
): number {
  let low = 0
  let high = data.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (data[middle][0] <= timestampMillis) low = middle + 1
    else high = middle
  }
  return low
}

function pointAtExactTimestamp(
  data: readonly CompactTracksideChartPoint[],
  timestampMillis: number,
): CompactTracksideChartPoint | undefined {
  for (
    let index = lowerBoundTracksidePoint(data, timestampMillis);
    index < data.length && data[index][0] === timestampMillis;
    index += 1
  ) {
    if (data[index][2] >= 0) return data[index]
  }
  return undefined
}

function latestPointInRange(
  data: readonly CompactTracksideChartPoint[],
  startMillis: number,
  endMillis: number,
): CompactTracksideChartPoint | undefined {
  let latestRealPoint: CompactTracksideChartPoint | undefined
  for (let index = upperBoundTracksidePoint(data, endMillis) - 1; index >= 0; index -= 1) {
    const point = data[index]
    if (point[0] < startMillis) break
    if (point[2] < 0) continue
    latestRealPoint ??= point
    if (point[1] != null) return point
  }
  return latestRealPoint
}

function unorderedPointInRange(
  data: readonly CompactTracksideChartPoint[],
  startMillis: number,
  endMillis: number,
  pointerMillis: number | null,
): { point: CompactTracksideChartPoint; source: 'pointer' | 'latest' } | undefined {
  let latestRealPoint: CompactTracksideChartPoint | undefined
  let latestValidPoint: CompactTracksideChartPoint | undefined
  for (const point of data) {
    if (point[2] < 0 || point[0] < startMillis || point[0] > endMillis) continue
    if (pointerMillis !== null && point[0] === pointerMillis) return { point, source: 'pointer' }
    if (!latestRealPoint || point[0] >= latestRealPoint[0]) latestRealPoint = point
    if (point[1] != null && (!latestValidPoint || point[0] >= latestValidPoint[0])) latestValidPoint = point
  }
  const point = latestValidPoint || latestRealPoint
  return point ? { point, source: 'latest' } : undefined
}

export function tracksideViewportSeriesItems(
  cache: TracksideSeriesCache,
  startMillis: number,
  endMillis: number,
  pointerMillis: number | null = null,
): TracksideViewportSeriesItem[] {
  if (!Number.isFinite(startMillis) || !Number.isFinite(endMillis) || startMillis > endMillis) return []
  const unorderedSeries = new Set(cache.unorderedSeriesIds)
  return cache.series.flatMap((series) => {
    if (
      series.firstTimestampMillis === null
      || series.lastTimestampMillis === null
      || series.lastTimestampMillis < startMillis
      || series.firstTimestampMillis > endMillis
    ) return []
    const resolved = unorderedSeries.has(series.id)
      ? unorderedPointInRange(series.data, startMillis, endMillis, pointerMillis)
      : (() => {
          const pointerPoint = pointerMillis !== null
            && pointerMillis >= startMillis
            && pointerMillis <= endMillis
            ? pointAtExactTimestamp(series.data, pointerMillis)
            : undefined
          if (pointerPoint) return { point: pointerPoint, source: 'pointer' as const }
          const latestPoint = latestPointInRange(series.data, startMillis, endMillis)
          return latestPoint ? { point: latestPoint, source: 'latest' as const } : undefined
        })()
    if (!resolved) return []
    const point = tracksidePointMeta(cache, resolved.point[2])
    if (!point) return []
    return [{
      seriesId: series.id,
      metaId: point.metaId,
      timestampMillis: point.timestampMillis,
      apName: point.peerApName || series.meta.peerName,
      apMac: point.peerApMac || series.meta.apMac,
      radio: point.localRadio ?? series.meta.radio,
      rssi: point.rssi,
      rssiSource: resolved.source,
    }]
  }).sort((left, right) => (
    String(left.apName || left.apMac || '').localeCompare(String(right.apName || right.apMac || ''), 'zh-CN')
    || (left.radio ?? Number.MAX_SAFE_INTEGER) - (right.radio ?? Number.MAX_SAFE_INTEGER)
    || left.seriesId.localeCompare(right.seriesId)
  ))
}

export function disposeTracksideSeriesCache(cache: TracksideSeriesCache | null | undefined): void {
  if (!cache || cache.disposed) return
  for (const item of cache.series) item.data.length = 0
  cache.series.length = 0
  cache.unorderedSeriesIds.length = 0
  cache.frameTimestamps.length = 0
  cache.medianFrameIntervalMs = 0
  cache.frameMatchToleranceMs = 500
  clearReadonlyMap(cache.pointMetaById)
  clearReadonlyMap(cache.seriesMetaById)
  clearReadonlyMap(cache.dataIndexToMetaId)
  clearReadonlyMap(cache.frameMetaIds)
  cache.totalRenderedPoints = 0
  cache.firstTimestampMillis = null
  cache.lastTimestampMillis = null
  cache.disposed = true
}

function clearReadonlyMap<Key, Value>(map: ReadonlyMap<Key, Value>): void {
  const mutable = map as Map<Key, Value>
  mutable.clear()
}
