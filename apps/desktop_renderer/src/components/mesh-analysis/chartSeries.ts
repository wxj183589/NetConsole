import type { MeshChartPoint, MeshCounterDeltaPoint, MeshLocationSegment, MeshRatePoint, MeshRssiLine, MeshRssiZeroRun, MeshSwitchEvent } from '../../types/meshAnalysis'
import { buildRssiDisplayPoints } from './rssiZeroRuns'

export interface MeshRssiSeries {
  name: string
  metric: 'local_rssi' | 'peer_rssi'
  data: Array<{ value: [string, number | null]; meta?: MeshChartPoint; zeroRun: MeshRssiZeroRun | null }>
}

export interface MeshBusySeries {
  name: string
  metric: 'local_tx_busy' | 'local_rx_busy' | 'peer_tx_busy' | 'peer_rx_busy'
  data: Array<{ value: [string, number | null]; meta: MeshChartPoint }>
}

export interface MeshRateSeries {
  name: string
  data: Array<{ value: [string, number | null]; meta: MeshRatePoint }>
}

export interface MeshCounterDeltaSeries {
  name: string
  data: Array<{ value: [string, number | null]; meta: MeshCounterDeltaPoint }>
}

export interface MeshSwitchRssiSeries {
  name: string
  data: Array<{ value: [string | null, number | null]; meta: MeshSwitchEvent }>
}

export interface MeshLocationBand {
  start_time: string
  end_time: string
  label: string
  station: string | null
  section: string | null
}

export function buildMeshLocationBands(segments: MeshLocationSegment[]): MeshLocationBand[] {
  return segments
    .filter((segment) => Boolean(segment.start_time && segment.end_time))
    .map((segment) => ({
      start_time: segment.start_time,
      end_time: segment.end_time,
      station: segment.station ?? null,
      section: segment.section ?? null,
      label: segment.label || [segment.station, segment.section].filter(Boolean).join(' / ') || '—',
    }))
}

function metricData(
  points: MeshChartPoint[],
  read: (point: MeshChartPoint) => number | null,
): Array<{ value: [string, number | null]; meta: MeshChartPoint }> {
  return points.flatMap((point, index) => [
    ...(index > 0 && point.gap_before ? [{ value: [point.timestamp, null] as [string, number | null], meta: point }] : []),
    { value: [point.timestamp, read(point)] as [string, number | null], meta: point },
  ])
}

function rssiMetricData(
  points: MeshChartPoint[],
  metric: 'local_rssi' | 'peer_rssi',
): MeshRssiSeries['data'] {
  const zeroRunField = metric === 'local_rssi' ? 'local_rssi_zero_run' : 'peer_rssi_zero_run'
  const displayPoints = buildRssiDisplayPoints(points
    .filter((point) => !point.bridge_ambiguous_active)
    .map((point) => ({
      timestamp: point.timestamp,
      value: point[metric],
      meta: point,
      zeroRun: point[zeroRunField],
      breakBefore: point.gap_before,
    })))
  return displayPoints.flatMap((point, index) => [
    ...(index > 0 && point.breakBefore && point.value !== null
      ? [{ value: [point.timestamp, null] as [string, number | null], meta: point.meta, zeroRun: null }]
      : []),
    { value: [point.timestamp, point.value] as [string, number | null], meta: point.meta, zeroRun: point.zeroRun },
  ])
}

export function buildMeshRssiSeries(points: MeshChartPoint[], showPeer = false, scope: 'active' | 'peer' = 'active'): MeshRssiSeries[] {
  const prefix = scope === 'peer' ? '选中 AP' : '当前 ACTIVE'
  const series: MeshRssiSeries[] = [{
    name: `${prefix} MR 侧 RSSI`,
    metric: 'local_rssi',
    data: rssiMetricData(points, 'local_rssi'),
  }]
  if (showPeer) series.push({
    name: `${prefix} Peer 侧 RSSI`,
    metric: 'peer_rssi',
    data: rssiMetricData(points, 'peer_rssi'),
  })
  return series
}

export function buildMeshFullRssiSeries(line: MeshRssiLine): MeshRssiSeries {
  return {
    name: '当前 ACTIVE MR 侧 RSSI',
    metric: 'local_rssi',
    data: line.points.flatMap(([timestamp, value, gapBefore], index) => [
      ...(index > 0 && gapBefore
        ? [{ value: [timestamp, null] as [string, number | null], zeroRun: null }]
        : []),
      { value: [timestamp, value] as [string, number | null], zeroRun: null },
    ]),
  }
}

export function buildMeshBusySeries(points: MeshChartPoint[], showPeer = false, scope: 'active' | 'peer' = 'active'): MeshBusySeries[] {
  const prefix = scope === 'peer' ? '选中 AP' : '当前 ACTIVE'
  const series: MeshBusySeries[] = [
    { name: `${prefix} MR 侧 TxBusy`, metric: 'local_tx_busy', data: metricData(points, (point) => point.local_tx_busy) },
    { name: `${prefix} MR 侧 RxBusy`, metric: 'local_rx_busy', data: metricData(points, (point) => point.local_rx_busy) },
  ]
  if (showPeer) series.push(
    { name: `${prefix} Peer 侧 TxBusy`, metric: 'peer_tx_busy', data: metricData(points, (point) => point.peer_tx_busy) },
    { name: `${prefix} Peer 侧 RxBusy`, metric: 'peer_rx_busy', data: metricData(points, (point) => point.peer_rx_busy) },
  )
  return series
}

function peerRadioKey(peerName: string | null, peerMac: string | null, radio: number | null): string {
  return `${peerName || peerMac || 'AP 未知'} · Radio ${radio ?? '—'}`
}

export function buildMeshRateSeries(points: MeshRatePoint[]): MeshRateSeries[] {
  const groups = new Map<string, MeshRatePoint[]>()
  for (const point of points) {
    const key = peerRadioKey(point.peer_ap_name, point.peer_ap_mac, point.local_radio)
    const group = groups.get(key) || []
    group.push(point)
    groups.set(key, group)
  }
  return [...groups.entries()].flatMap(([key, group]) => [
    { name: `${key} · Local Rate 原始值`, data: group.map((point) => ({ value: [point.timestamp, point.local_rate_raw], meta: point })) },
    { name: `${key} · Peer Rate 原始值`, data: group.map((point) => ({ value: [point.timestamp, point.peer_rate_raw], meta: point })) },
  ])
}

export function buildMeshCounterDeltaSeries(points: MeshCounterDeltaPoint[]): MeshCounterDeltaSeries[] {
  const groups = new Map<string, MeshCounterDeltaPoint[]>()
  for (const point of points) {
    const key = peerRadioKey(point.peer_ap_name, point.peer_ap_mac, point.local_radio)
    const group = groups.get(key) || []
    group.push(point)
    groups.set(key, group)
  }
  return [...groups.entries()].flatMap(([key, group]) => [
    { name: `${key} · Local Retry 增量`, data: group.map((point) => ({ value: [point.timestamp, point.local_retry_delta], meta: point })) },
    { name: `${key} · Peer Retry 增量`, data: group.map((point) => ({ value: [point.timestamp, point.peer_retry_delta], meta: point })) },
    { name: `${key} · Local Error 增量`, data: group.map((point) => ({ value: [point.timestamp, point.local_error_delta], meta: point })) },
    { name: `${key} · Peer Error 增量`, data: group.map((point) => ({ value: [point.timestamp, point.peer_error_delta], meta: point })) },
  ])
}

export function buildMeshSwitchRssiSeries(events: MeshSwitchEvent[]): MeshSwitchRssiSeries[] {
  const before = new Map<string, MeshSwitchEvent[]>()
  const after = new Map<string, MeshSwitchEvent[]>()
  for (const event of events) {
    const radio = `Radio ${event.local_radio ?? '—'}`
    const beforeKey = `${event.from_ap_name || event.from_peer_mac || '原 AP 未知'} · ${radio} · 切换前`
    const afterKey = `${event.to_ap_name || event.to_peer_mac || '目标 AP 未知'} · ${radio} · 切换后`
    before.set(beforeKey, [...(before.get(beforeKey) || []), event])
    after.set(afterKey, [...(after.get(afterKey) || []), event])
  }
  return [
    ...[...before.entries()].map(([name, rows]) => ({ name, data: rows.map((event) => ({ value: [event.timestamp, event.before_rssi] as [string | null, number | null], meta: event })) })),
    ...[...after.entries()].map(([name, rows]) => ({ name, data: rows.map((event) => ({ value: [event.timestamp, event.after_rssi] as [string | null, number | null], meta: event })) })),
  ]
}

export function hasMeshChartSamples(series: Array<{ data: Array<{ value: [string | null, number | null] }> }>): boolean {
  return series.some((item) => item.data.some((point) => point.value[0] !== null && point.value[1] !== null))
}
