import { describe, expect, it } from 'vitest'

import type { MeshCounterDeltaPoint, MeshRatePoint, MeshSwitchEvent } from '../../types/meshAnalysis'
import {
  buildMeshBusySeries,
  buildMeshCounterDeltaSeries,
  buildMeshRateSeries,
  buildMeshSwitchRssiSeries,
} from './chartSeries'

describe('mesh busy chart series', () => {
  it('keeps AP and Radio dimensions and null samples', () => {
    const series = buildMeshBusySeries([
      { timestamp: '2026-07-20T10:00:00.123Z', local_radio: 1, tx_busy: 20, rx_busy: null, ctl_busy: null, total_busy: null, peer_ap_name: 'AP-1', station: null, section: null, source_type: 'mesh_link_metrics', warning: null },
      { timestamp: '2026-07-20T10:00:00.123Z', local_radio: 2, tx_busy: 30, rx_busy: 40, ctl_busy: null, total_busy: null, peer_ap_name: 'AP-1', station: null, section: null, source_type: 'mesh_link_metrics', warning: null },
    ])

    expect(series.map((item) => item.name)).toEqual([
      'AP-1 · Radio 1 · TxBusy', 'AP-1 · Radio 1 · RxBusy',
      'AP-1 · Radio 2 · TxBusy', 'AP-1 · Radio 2 · RxBusy',
    ])
    expect(series[1].data[0].value).toEqual(['2026-07-20T10:00:00.123Z', null])
  })
})

describe('mesh rate and counter chart series', () => {
  const rate: MeshRatePoint = {
    timestamp: '2026-07-20T10:00:00.123Z', local_radio: 1, peer_ap_name: 'AP-1', peer_ap_mac: 'aa', local_rate_raw: 54, peer_rate_raw: null,
  }
  const counter: MeshCounterDeltaPoint = {
    timestamp: '2026-07-20T10:00:00.123Z', local_radio: 1, peer_ap_name: 'AP-1', peer_ap_mac: 'aa', local_retry_delta: 2, peer_retry_delta: null, local_error_delta: 1, peer_error_delta: 0,
  }

  it('maps raw Rate fields without assigning units or filling nulls', () => {
    const series = buildMeshRateSeries([rate])
    expect(series.map((item) => item.name)).toEqual(['AP-1 · Radio 1 · Local Rate 原始值', 'AP-1 · Radio 1 · Peer Rate 原始值'])
    expect(series[0].data[0].value).toEqual(['2026-07-20T10:00:00.123Z', 54])
    expect(series[1].data[0].value).toEqual(['2026-07-20T10:00:00.123Z', null])
  })

  it('uses backend counter deltas as-is for all four dimensions', () => {
    const series = buildMeshCounterDeltaSeries([counter])
    expect(series.map((item) => item.name)).toEqual([
      'AP-1 · Radio 1 · Local Retry 增量', 'AP-1 · Radio 1 · Peer Retry 增量',
      'AP-1 · Radio 1 · Local Error 增量', 'AP-1 · Radio 1 · Peer Error 增量',
    ])
    expect(series[1].data[0].value[1]).toBeNull()
    expect(series[3].data[0].value[1]).toBe(0)
  })
})

describe('mesh switch RSSI event series', () => {
  it('keeps before/after RSSI as separate event scatter series', () => {
    const event: MeshSwitchEvent = {
      event_id: 1, timestamp: '2026-07-20T10:00:00.123Z', event_type: 'switch', mr_name: 'MR-1', local_radio: 2,
      from_peer_mac: 'from-mac', to_peer_mac: 'to-mac', from_ap_name: 'AP-1', to_ap_name: 'AP-2', before_rssi: -42, after_rssi: -48,
      duration_ms: 100, is_short_link: false, is_pingpong: false, station: null, section: null, warning: null,
    }
    const series = buildMeshSwitchRssiSeries([event])
    expect(series.map((item) => item.name)).toEqual(['AP-1 · Radio 2 · 切换前', 'AP-2 · Radio 2 · 切换后'])
    expect(series[0].data[0].value).toEqual(['2026-07-20T10:00:00.123Z', -42])
    expect(series[1].data[0].value).toEqual(['2026-07-20T10:00:00.123Z', -48])
  })
})
