import { describe, expect, it } from 'vitest'

import type { MeshChartPoint, MeshCounterDeltaPoint, MeshRatePoint, MeshSwitchEvent } from '../../types/meshAnalysis'
import {
  buildMeshBusySeries,
  buildMeshCounterDeltaSeries,
  buildMeshRateSeries,
  buildMeshRssiSeries,
  buildMeshSwitchRssiSeries,
} from './chartSeries'

function point(index: number): MeshChartPoint {
  return {
    link_id: index, timestamp: `2026-07-20T10:00:${String(index).padStart(2, '0')}.123Z`, timestamp_tag: `tag-${index}`, source_file_id: 1,
    local_radio: index % 2 + 1, link_state: 'ACTIVE', peer_mac: `peer-${index}`, peer_ap_name: `AP-${index}`, peer_ap_mac: `ap-${index}`,
    peer_radio: 'Radio 1', peer_radio_mac: null, station: null, local_rssi: -40 - index, peer_rssi: -45 - index,
    local_signal: -50, peer_signal: -55, local_tx_busy: 20, peer_tx_busy: 30, local_rx_busy: null, peer_rx_busy: 40,
    is_switch: false, is_anomaly: false, gap_before: false, backups: [],
  }
}

describe('mesh ACTIVE chart series', () => {
  it('keeps 100 AP on one default RSSI main line', () => {
    const series = buildMeshRssiSeries(Array.from({ length: 100 }, (_, index) => point(index)))
    expect(series).toHaveLength(1)
    expect(series[0].name).toBe('当前 ACTIVE MR 侧 RSSI')
    expect(series[0].data).toHaveLength(100)
  })

  it('adds only one optional Peer RSSI line', () => {
    expect(buildMeshRssiSeries([point(1)], true).map((item) => item.name)).toEqual([
      '当前 ACTIVE MR 侧 RSSI', '当前 ACTIVE Peer 侧 RSSI',
    ])
    expect(buildMeshRssiSeries([point(1)], false, 'peer')[0].name).toBe('选中 AP MR 侧 RSSI')
  })

  it('uses two MR Busy lines by default and at most four with Peer enabled', () => {
    const sample = point(1)
    const defaults = buildMeshBusySeries([sample])
    expect(defaults.map((item) => item.name)).toEqual(['当前 ACTIVE MR 侧 TxBusy', '当前 ACTIVE MR 侧 RxBusy'])
    expect(defaults[1].data[0].value).toEqual([sample.timestamp, null])
    expect(buildMeshBusySeries([sample], true)).toHaveLength(4)
  })

  it('inserts explicit null breakpoints before a new visit or backend gap', () => {
    const firstVisit = point(1)
    const secondVisit = { ...point(2), gap_before: true }
    const rssi = buildMeshRssiSeries([firstVisit, secondVisit])[0].data
    const busy = buildMeshBusySeries([firstVisit, secondVisit])[0].data

    expect(rssi.map((item) => item.value)).toEqual([
      [firstVisit.timestamp, firstVisit.local_rssi],
      [secondVisit.timestamp, null],
      [secondVisit.timestamp, secondVisit.local_rssi],
    ])
    expect(busy[1].value).toEqual([secondVisit.timestamp, null])
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
