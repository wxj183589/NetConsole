import type { MeshChartEvent, MeshChartPoint, MeshRssiLinePoint } from '../../types/meshAnalysis'
import { meshTimestampMillis } from './meshChartViewport'

export interface MeshRssiLineSample {
  timestamp: string
  rssi: number
  peerRssi: number | null | undefined
  localTxBusy: number | null | undefined
  localRxBusy: number | null | undefined
  peerTxBusy: number | null | undefined
  peerRxBusy: number | null | undefined
  radio: number | null | undefined
}

interface MeshRssiSegmentContext {
  start: number
  end: number
  point: MeshChartPoint
  linkCount: number | null
  key: string
}

export interface MeshRssiContextIndex {
  findExact(timestamp: string, radio?: number | null): MeshChartPoint | undefined
  findSwitchPoint(event: MeshChartEvent): MeshChartPoint | undefined
  findSegment(timestamp: string, radio?: number | null): MeshChartPoint | undefined
}

function macKey(value: string | null | undefined): string {
  return String(value || '').toLowerCase().replace(/[^0-9a-f]/g, '')
}

function pointKey(point: MeshChartPoint): string {
  return [
    point.source_file_id ?? '',
    point.local_radio ?? '',
    point.segment_sequence ?? '',
    point.segment_start || '',
    point.segment_end || '',
    macKey(point.peer_mac),
    macKey(point.peer_ap_mac),
    macKey(point.peer_radio_mac),
    point.peer_ap_name || '',
    point.station || '',
    point.section || '',
  ].join('|')
}

function candidatesFor(
  candidates: MeshChartPoint[] | undefined,
  radio?: number | null,
): MeshChartPoint[] {
  if (!candidates?.length) return []
  return radio == null
    ? candidates
    : candidates.filter((point) => point.local_radio === radio)
}

function upperBound(values: readonly number[], target: number): number {
  let low = 0
  let high = values.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (values[middle] <= target) low = middle + 1
    else high = middle
  }
  return low
}

export function createMeshRssiContextIndex(points: readonly MeshChartPoint[]): MeshRssiContextIndex {
  const byTimestamp = new Map<string, MeshChartPoint[]>()
  const byMillisAndRadio = new Map<string, MeshChartPoint[]>()
  const segmentByKey = new Map<string, MeshRssiSegmentContext>()

  for (const point of points) {
    const timestampItems = byTimestamp.get(point.timestamp) || []
    timestampItems.push(point)
    byTimestamp.set(point.timestamp, timestampItems)

    const millis = meshTimestampMillis(point.timestamp)
    if (millis !== null && point.local_radio != null) {
      const key = `${millis}|${point.local_radio}`
      const millisItems = byMillisAndRadio.get(key) || []
      millisItems.push(point)
      byMillisAndRadio.set(key, millisItems)
    }

    const start = meshTimestampMillis(point.segment_start)
    const end = meshTimestampMillis(point.segment_end)
    if (start === null || end === null || end < start) continue
    const key = pointKey(point)
    const current = segmentByKey.get(key)
    if (!current) {
      segmentByKey.set(key, {
        start,
        end,
        point,
        linkCount: point.link_count ?? null,
        key,
      })
      continue
    }
    current.start = Math.min(current.start, start)
    current.end = Math.max(current.end, end)
    if (current.linkCount !== (point.link_count ?? null)) current.linkCount = null
  }

  const segments = [...segmentByKey.values()].sort((left, right) => left.start - right.start || left.end - right.end)
  const starts = segments.map((segment) => segment.start)

  function findCandidates(timestamp: string, radio?: number | null): MeshChartPoint[] {
    const exact = candidatesFor(byTimestamp.get(timestamp), radio)
    if (exact.length) return exact
    const millis = meshTimestampMillis(timestamp)
    return millis === null ? [] : candidatesFor(byMillisAndRadio.get(`${millis}|${radio}`), radio)
  }

  function findExact(timestamp: string, radio?: number | null): MeshChartPoint | undefined {
    const candidates = findCandidates(timestamp, radio)
    return candidates.length === 1 ? candidates[0] : undefined
  }

  function findSegment(timestamp: string, radio?: number | null): MeshChartPoint | undefined {
    const millis = meshTimestampMillis(timestamp)
    if (millis === null || !segments.length) return undefined
    const candidates: MeshRssiSegmentContext[] = []
    const end = upperBound(starts, millis)
    for (let index = end - 1; index >= 0; index -= 1) {
      const segment = segments[index]
      if (segment.start > millis) continue
      if (segment.end < millis && segment.start < millis) break
      if (segment.end >= millis && (radio == null || segment.point.local_radio === radio)) candidates.push(segment)
    }
    if (candidates.length !== 1) return undefined
    const context = candidates[0]
    return context.linkCount === context.point.link_count
      ? context.point
      : { ...context.point, link_count: null }
  }

  function findSwitchPoint(event: MeshChartEvent): MeshChartPoint | undefined {
    if (event.render_aligned === false) return undefined
    const timestamp = event.render_point_timestamp || event.point_timestamp || event.timestamp
    if (!timestamp) return undefined
    const context = event.point_context
    const candidates = findCandidates(timestamp, event.local_radio)
    return candidates.find((point) => (
      (context?.link_id == null || point.link_id === context.link_id)
      && (context?.timestamp_tag == null || point.timestamp_tag === context.timestamp_tag)
      && point.local_rssi != null
      && point.local_rssi !== 0
      && !point.is_anomaly
    ))
  }

  return { findExact, findSwitchPoint, findSegment }
}

export function decodeMeshRssiLinePoint(point: MeshRssiLinePoint): MeshRssiLineSample {
  return {
    timestamp: point[0],
    rssi: point[1],
    peerRssi: point[3],
    localTxBusy: point[4],
    localRxBusy: point[5],
    peerTxBusy: point[6],
    peerRxBusy: point[7],
    radio: point[8],
  }
}

export interface ResolvedMeshRssiPoint {
  point: MeshChartPoint
  exact: boolean
}

export function resolveMeshRssiPoint(
  index: MeshRssiContextIndex,
  sample: MeshRssiLineSample,
  exactPoint?: MeshChartPoint,
): ResolvedMeshRssiPoint | undefined {
  const exact = exactPoint || index.findExact(sample.timestamp, sample.radio)
  const context = exact || index.findSegment(sample.timestamp, sample.radio)
  if (!context) return undefined
  const sampleValue = (lineValue: number | null | undefined, pointValue: number | null): number | null => (
    pointValue != null ? pointValue : lineValue ?? null
  )
  return {
    exact: Boolean(exact),
    point: {
      ...context,
      timestamp: sample.timestamp,
      timestamp_tag: exact?.timestamp_tag ?? null,
      local_rssi: sampleValue(sample.rssi, exact?.local_rssi ?? null),
      peer_rssi: sampleValue(sample.peerRssi, exact?.peer_rssi ?? null),
      local_tx_busy: sampleValue(sample.localTxBusy, exact?.local_tx_busy ?? null),
      local_rx_busy: sampleValue(sample.localRxBusy, exact?.local_rx_busy ?? null),
      peer_tx_busy: sampleValue(sample.peerTxBusy, exact?.peer_tx_busy ?? null),
      peer_rx_busy: sampleValue(sample.peerRxBusy, exact?.peer_rx_busy ?? null),
      backups: exact?.backups || [],
      local_rssi_zero_run: null,
      peer_rssi_zero_run: null,
      is_switch: exact?.is_switch || false,
    },
  }
}
