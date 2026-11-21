// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { readNetConsoleChartTokens } from '../../theme/echarts'
import { chronologicalPeerIntervals, mrMonitoringChartOption, peerIntervalColorMap, PEER_RAINBOW_COLORS } from './mrMonitoringChartOptions'

describe('MR monitoring evidence chart', () => {
  it('assigns rainbow colors by chronological interval, including repeated AP identities', () => {
    const rows = [
      { start: '2026-11-07T11:00:03Z', end: '2026-11-07T11:00:04Z', bssid: 'aa', peer_name: 'AP-A', source: 'MESH' },
      { start: '2026-11-07T11:00:01Z', end: '2026-11-07T11:00:02Z', bssid: 'bb', peer_name: 'AP-B', source: 'MESH' },
      { start: '2026-11-07T11:00:05Z', end: '2026-11-07T11:00:06Z', bssid: 'aa', peer_name: 'AP-A', source: 'MESH' },
    ] as GroundMrMonitoring['peer_intervals']
    const ordered = chronologicalPeerIntervals(rows)
    const colors = peerIntervalColorMap(rows)
    expect(ordered.map((row) => row.start)).toEqual([
      '2026-11-07T11:00:01Z', '2026-11-07T11:00:03Z', '2026-11-07T11:00:05Z',
    ])
    expect([...colors.values()]).toEqual([
      PEER_RAINBOW_COLORS[0], PEER_RAINBOW_COLORS[1], PEER_RAINBOW_COLORS[2],
    ])
  })
  it('restarts the seven-color cycle on the eighth chronological interval', () => {
    const rows = Array.from({ length: 8 }, (_, index) => ({
      start: `2026-11-07T11:00:${String(index).padStart(2, '0')}Z`, end: `2026-11-07T11:00:${String(index + 1).padStart(2, '0')}Z`,
      bssid: `ap-${index}`, peer_name: `AP-${index}`, source: 'MESH',
    })) as GroundMrMonitoring['peer_intervals']
    expect([...peerIntervalColorMap(rows).values()]).toEqual([...PEER_RAINBOW_COLORS, PEER_RAINBOW_COLORS[0]])
  })
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
    expect(series[2]?.data).toContainEqual([Date.parse('2026-11-07T11:00:01Z'), 100])
    const pingColors = mrMonitoringChartOption(data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', readNetConsoleChartTokens(), '', 'ping').color as string[]
    expect(pingColors.slice(0, 4)).toEqual(['#3B82F6', '#22C55E', '#EF4444', '#909399'])
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
      peer_name: 'AP 一', bssid: '00:11:22:33:44:55', rssi: -55, raw_rssi: 55, rssi_semantics: 'ABSOLUTE_MAGNITUDE',
      source: 'SYSLOG', device_time: '', receive_time: '',
    }] } as GroundMrMonitoring
    const theme = readNetConsoleChartTokens()
    const ping = mrMonitoringChartOption(data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', theme, '', 'ping')
    expect((ping.series as Array<{ id: string }>).map((row) => row.id)).toEqual(['rtt:192.0.2.1', 'success:192.0.2.1', 'loss:192.0.2.1', 'unknown:192.0.2.1'])

    const peer = mrMonitoringChartOption(data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', theme, '', 'peer')
    const peerSeries = (peer.series as Array<{ id: string; data: number[][] }>)[0]!
    expect(peerSeries.id).toBe('peer-rssi-intervals')
    expect(peerSeries.data[0]).toEqual([
      Date.parse('2026-11-07T11:00:00Z'), Date.parse('2026-11-07T11:00:30Z'), -55, 0,
    ])
    const tooltip = peer.tooltip as { formatter: (params: { data: number[] }) => string }
    expect(tooltip.formatter({ data: peerSeries.data[0]! })).toContain('设备原始 RSSI：55')
    expect(tooltip.formatter({ data: peerSeries.data[0]! })).toContain('归一化 RSSI：-55 dBm')
    expect(tooltip.formatter({ data: peerSeries.data[0]! })).toContain('持续：30.0 秒')
  })

  it('uses one externally-owned visible window without per-track sliders', () => {
    const data = { series: { points: [] }, peer_intervals: [] } as unknown as GroundMrMonitoring
    const theme = readNetConsoleChartTokens()
    const args = [data, '2026-11-07T11:00:00Z', '2026-11-07T12:00:00Z', theme, '', 'ping', '2026-11-07T11:10:00Z', '2026-11-07T11:20:00Z'] as const
    const ping = mrMonitoringChartOption(...args)
    expect(ping.dataZoom).toHaveLength(1)
    expect((ping.dataZoom as Array<Record<string, unknown>>)[0]).toMatchObject({
      startValue: Date.parse('2026-11-07T11:10:00Z'), endValue: Date.parse('2026-11-07T11:20:00Z'),
      zoomOnMouseWheel: true, moveOnMouseMove: true,
    })
    const navigator = mrMonitoringChartOption(data, args[1], args[2], theme, '', 'navigator', args[6], args[7])
    expect(navigator.dataZoom).toHaveLength(2)
  })
})
