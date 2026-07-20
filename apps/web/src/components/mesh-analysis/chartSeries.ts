import type { MeshChannelBusy, MeshCounterDeltaPoint, MeshRatePoint, MeshSwitchEvent } from '../../types/meshAnalysis'

export interface MeshBusySeries {
  name: string
  metric: 'TxBusy' | 'RxBusy'
  data: Array<{ value: [string, number | null]; meta: MeshChannelBusy }>
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

export function buildMeshBusySeries(points: MeshChannelBusy[]): MeshBusySeries[] {
  const groups = new Map<string, MeshChannelBusy[]>()
  for (const point of points) {
    const peer = point.peer_ap_name || 'AP 未知'
    const key = `${peer} · Radio ${point.local_radio ?? '—'}`
    const group = groups.get(key) || []
    group.push(point)
    groups.set(key, group)
  }
  return [...groups.entries()].flatMap(([key, group]) => [
    { name: `${key} · TxBusy`, metric: 'TxBusy' as const, data: group.map((point) => ({ value: [point.timestamp, point.tx_busy], meta: point })) },
    { name: `${key} · RxBusy`, metric: 'RxBusy' as const, data: group.map((point) => ({ value: [point.timestamp, point.rx_busy], meta: point })) },
  ])
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
