import { describe, expect, it } from 'vitest'

import type { MeshChartEvent, MeshChartPoint } from '../../types/meshAnalysis'
import { buildMeshRssiTooltip, buildMeshSwitchPointTooltip } from './meshRssiTooltip'

const point: MeshChartPoint = {
  link_id: 1,
  timestamp: '2024-10-22 14:31:50.201',
  timestamp_tag: null,
  source_file_id: 1,
  local_radio: 1,
  link_state: 'ACTIVE',
  peer_mac: 'main-peer',
  peer_ap_name: '<主 AP>',
  peer_ap_mac: 'main-ap',
  peer_radio: 'radio1',
  peer_radio_mac: null,
  station: '站点&一',
  section: null,
  segment_duration_seconds: 1,
  local_rssi: 31,
  peer_rssi: 29,
  local_signal: -49,
  peer_signal: -45,
  local_tx_busy: null,
  peer_tx_busy: null,
  local_rx_busy: null,
  peer_rx_busy: null,
  is_switch: true,
  is_anomaly: false,
  gap_before: false,
  backups: [{
    link_id: 2,
    timestamp: '2024-10-22 14:31:50.201',
    timestamp_tag: '',
    local_radio: 1,
    peer_mac: 'backup-peer',
    peer_ap_name: '备份 AP',
    peer_ap_mac: 'backup-ap',
    peer_radio: 'radio1',
    peer_radio_mac: null,
    local_rssi: 30,
    peer_rssi: 28,
    local_signal: -60,
    peer_signal: -63,
    station: '站点二',
    section: '区间二',
    local_tx_busy: null,
    peer_tx_busy: null,
    local_rx_busy: null,
    peer_rx_busy: null,
  }],
}
const event: MeshChartEvent = {
  event_id: 1,
  timestamp: point.timestamp,
  event_type: 'ACTIVE_SWITCH',
  local_radio: 1,
  from_peer_mac: 'from-mac',
  to_peer_mac: 'to-mac',
  from_ap_name: '原 AP',
  to_ap_name: '目标 AP',
  duration_ms: 20,
  render_aligned: true,
  render_point_timestamp: point.timestamp,
  render_point_rssi: point.local_rssi,
}

describe('MESH RSSI tooltip', () => {
  it('uses RSSI deltas, separates sections, escapes HTML and hides unreliable switch fields', () => {
    const html = buildMeshRssiTooltip(point, event)

    expect(html.match(/class="mesh-rssi-tooltip"/g)).toHaveLength(1)
    expect(html.match(/class="mesh-rssi-tooltip__divider"/g)).toHaveLength(3)
    expect(html).toContain('MR / 轨旁 AP 接收信号：31 / 29')
    expect(html).toContain('MR / 轨旁 AP 接收信号：30 / 28')
    expect(html).not.toContain('MR / 轨旁 AP 接收信号：-31 / -29')
    expect(html.toLowerCase()).not.toContain('dbm')
    expect(html).not.toContain('-49')
    expect(html).not.toContain('-45')
    expect(html).not.toContain('切换耗时')
    expect(html).not.toContain('切换类型')
    expect(html).toContain('&lt;主 AP&gt;')
    expect(html).toContain('站点&amp;一')
    expect(html).toContain(`切换事件时间：${point.timestamp}`)
    expect(html).toContain(`对齐采样时间：${point.timestamp}`)
  })

  it('keeps missing RSSI values missing without signal fallback or zero fill', () => {
    const html = buildMeshRssiTooltip({ ...point, local_rssi: null, peer_rssi: null, backups: [] })
    expect(html).toContain('MR / 轨旁 AP 接收信号：— / —')
    expect(html).toContain('<strong>备份链路：无</strong>')
    expect(html).not.toContain('：0 / 0')
  })

  it('keeps positive RSSI values unchanged and unitless', () => {
    const html = buildMeshRssiTooltip({
      ...point,
      local_rssi: 29,
      peer_rssi: 21,
      backups: [],
    })
    expect(html).toContain('MR / 轨旁 AP 接收信号：29 / 21')
    expect(html).not.toContain('-29')
    expect(html.toLowerCase()).not.toContain('dbm')
  })

  it('removes event type and duration from the independent switch RSSI chart tooltip', () => {
    const html = buildMeshSwitchPointTooltip({
      event_id: 1, timestamp: point.timestamp, event_type: 'ACTIVE_SWITCH', mr_name: 'MR', local_radio: 1,
      from_peer_mac: 'from', to_peer_mac: 'to', from_ap_name: '<原>', to_ap_name: '目标', before_rssi: 31, after_rssi: 29,
      duration_ms: 20, is_short_link: false, is_pingpong: false, station: null, section: null, warning: null,
    }, '切换前', 31)
    expect(html).not.toContain('ACTIVE_SWITCH')
    expect(html).not.toContain('耗时')
    expect(html).toContain('&lt;原&gt;')
  })

  it('explains why an event without an aligned RSSI point has no red node', () => {
    const html = buildMeshRssiTooltip(undefined, { ...event, render_aligned: false, render_point_timestamp: null })
    expect(html).toContain('该切换事件无有效 RSSI 点，未作为折线节点显示。')
  })

  it('keeps the shared pointer time instead of snapping an empty chart to another sample', () => {
    const pointerTime = '2024-10-22 14:31:50.500'
    const html = buildMeshRssiTooltip(undefined, undefined, pointerTime)
    expect(html).toContain(`采样时间：${pointerTime}`)
    expect(html).toContain('当前时刻无有效采样')
    expect(html).not.toContain(point.timestamp)
  })
})
