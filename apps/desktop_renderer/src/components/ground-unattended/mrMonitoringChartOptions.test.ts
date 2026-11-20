// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { readNetConsoleChartTokens } from '../../theme/echarts'
import { mrMonitoringChartOption } from './mrMonitoringChartOptions'

describe('MR monitoring evidence chart', () => {
  it('keeps RTT milliseconds, loss percent, true timestamps and unknown gaps distinct', () => {
    const data = { series: { points: [
      { ts: '2026-11-07T11:00:00Z', target_ip: '192.0.2.1', ok: true, rtt_ms: 3 },
      { ts: '2026-11-07T11:00:01Z', target_ip: '192.0.2.1', ok: false, rtt_ms: null },
      { ts: '2026-11-07T11:00:20Z', target_ip: '192.0.2.1', ok: true, rtt_ms: 4 },
    ] }, peer_intervals: [{ start: '2026-11-07T11:00:00Z', end: '2026-11-07T11:00:02Z', peer_name: '<peer>', bssid: '', source: 'SYSLOG', device_time: '', receive_time: '' }] } as GroundMrMonitoring
    const option = mrMonitoringChartOption(data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', readNetConsoleChartTokens())
    const axes = option.yAxis as Array<Record<string, unknown>>
    expect(axes[0]?.name).toBe('RTT (ms)')
    expect(axes[1]).toMatchObject({ min: 0, max: 100 })
    const series = option.series as Array<{ id: string; data: unknown[]; connectNulls: boolean; yAxisIndex?: number }>
    expect(series[0]?.connectNulls).toBe(false)
    expect(series[0]?.data).toContainEqual([Date.parse('2026-11-07T11:00:01Z') + 1, null])
    expect(series[1]?.yAxisIndex).toBe(1)
    expect(series[1]?.data).toContainEqual([Date.parse('2026-11-07T11:00:01Z'), 100])
    const tooltip = option.tooltip as { formatter: (params: unknown[]) => string }
    expect(tooltip.formatter([{ axisValue: Date.parse('2026-11-07T11:00:00Z'), seriesName: 'RTT', data: [Date.parse('2026-11-07T11:00:00Z'), 3] }])).toContain('&lt;peer&gt;')
    expect(tooltip.formatter([{ axisValue: Date.parse('2026-11-07T11:00:21Z'), seriesName: 'RTT', data: [Date.parse('2026-11-07T11:00:20Z'), 4] }])).toContain('Peer: UNKNOWN')
    expect(tooltip.formatter([{ axisValue: Date.parse('2026-11-07T11:00:21Z'), seriesName: 'RTT', data: [Date.parse('2026-11-07T11:00:20Z'), 4] }])).not.toContain('4 ms')
  })

  it('separates per-address ping from the duration-width and RSSI-height Peer chart', () => {
    const data = { series: { points: [
      { ts: '2026-11-07T11:00:00Z', target_ip: '192.0.2.1', ok: true, rtt_ms: 3 },
    ] }, peer_intervals: [{
      start: '2026-11-07T11:00:00Z', end: '2026-11-07T11:00:30Z',
      peer_name: 'AP 一', bssid: '00:11:22:33:44:55', rssi: -55,
      source: 'SYSLOG', device_time: '', receive_time: '',
    }] } as GroundMrMonitoring
    const theme = readNetConsoleChartTokens()
    const ping = mrMonitoringChartOption(data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', theme, '', 'ping')
    expect((ping.series as Array<{ id: string }>).map((row) => row.id)).toEqual(['rtt:192.0.2.1', 'loss:192.0.2.1'])

    const peer = mrMonitoringChartOption(data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', theme, '', 'peer')
    const peerSeries = (peer.series as Array<{ id: string; data: number[][] }>)[0]!
    expect(peerSeries.id).toBe('peer-rssi-intervals')
    expect(peerSeries.data[0]).toEqual([
      Date.parse('2026-11-07T11:00:00Z'), Date.parse('2026-11-07T11:00:30Z'), 45, 0,
    ])
    const tooltip = peer.tooltip as { formatter: (params: { data: number[] }) => string }
    expect(tooltip.formatter({ data: peerSeries.data[0]! })).toContain('RSSI：-55 dBm')
    expect(tooltip.formatter({ data: peerSeries.data[0]! })).toContain('持续：30.0 秒')
  })
})
