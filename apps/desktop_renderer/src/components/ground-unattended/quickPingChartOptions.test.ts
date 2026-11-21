// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { quickPingChartOption } from './quickPingChartOptions'
import { readNetConsoleChartTokens } from '../../theme/echarts'

describe('Quick Ping chart semantics', () => {
  it('uses real timestamps and retains loss and collection gap breaks', () => {
    const rows = [
      { received_at: '2026-11-07T00:00:00Z', sample: { ok: true, rtt_ms: 280 } },
      { received_at: '2026-11-07T00:00:00.200Z', sample: { ok: false, rtt_ms: null } },
      { received_at: '2026-11-07T00:00:00.400Z', sample: { ok: true, rtt_ms: 3 } },
      { received_at: '2026-11-07T00:00:10Z', sample: { ok: true, rtt_ms: 4 } },
    ]
    const option = quickPingChartOption(rows, 200, readNetConsoleChartTokens()) as {
      series: Array<{ data: Array<[number, number | null]>; connectNulls: boolean; tooltip: { valueFormatter: (value: number) => string } }>
      yAxis: Array<{ max?: number; name: string }>; tooltip: { appendToBody: boolean; confine: boolean }
    }
    expect(option.series[0]!.data.map((point) => point[1])).toEqual([280, null, 3, null, 4])
    expect(option.series[0]!.data[0]![0]).toBe(Date.parse('2026-11-07T00:00:00Z'))
    expect(option.series.every((series) => !series.connectNulls)).toBe(true)
    expect(option.series[0]!.tooltip.valueFormatter(280)).toBe('280 ms')
    expect(option.series[1]!.tooltip.valueFormatter(0)).toBe('0%')
    expect(option.yAxis[0]!.name).toBe('ms')
    expect(option.yAxis[0]!.max).toBeUndefined()
    expect(option.yAxis[1]!.max).toBe(100)
    expect(option.tooltip).toMatchObject({ appendToBody: false, confine: true })
  })

  it('keeps multiple target series on the same time axis', () => {
    const option = quickPingChartOption([
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:00Z', sample: { ok: true, rtt_ms: 4 } },
      { target_ip: '10.0.0.2', received_at: '2026-11-07T00:00:00.100Z', sample: { ok: true, rtt_ms: 8 } },
    ], 200, readNetConsoleChartTokens()) as { series: Array<{ name: string; data: Array<[number, number | null]> }> }

    expect(option.series).toHaveLength(8)
    expect(option.series.map((series) => series.name)).toEqual([
      'RTT（ms） · 10.0.0.1', '连通 · 10.0.0.1', '丢包/超时 · 10.0.0.1', '未知 · 10.0.0.1',
      'RTT（ms） · 10.0.0.2', '连通 · 10.0.0.2', '丢包/超时 · 10.0.0.2', '未知 · 10.0.0.2',
    ])
    expect(option.series[0]!.data[0]![0]).toBe(Date.parse('2026-11-07T00:00:00Z'))
    expect(option.series[4]!.data[0]![0]).toBe(Date.parse('2026-11-07T00:00:00.100Z'))
  })

  it('pins the chart domain to the playback run while zooming the shared viewport', () => {
    const option = quickPingChartOption([
      { received_at: '2026-11-07T00:10:00Z', sample: { ok: true, rtt_ms: 4 } },
    ], 1000, readNetConsoleChartTokens(), { connectNulls: false }, {
      start: '2026-11-07T00:05:00Z', end: '2026-11-07T00:15:00Z',
    }, '', {
      start: '2026-11-07T00:00:00Z', end: '2026-11-07T01:00:00Z',
    }) as {
      xAxis: { min: number; max: number }
      dataZoom: Array<{ startValue: number; endValue: number; zoomOnMouseWheel: boolean; moveOnMouseMove: boolean }>
    }
    expect(option.xAxis).toMatchObject({
      min: Date.parse('2026-11-07T00:00:00Z'),
      max: Date.parse('2026-11-07T01:00:00Z'),
    })
    expect(option.dataZoom[0]).toMatchObject({
      startValue: Date.parse('2026-11-07T00:05:00Z'),
      endValue: Date.parse('2026-11-07T00:15:00Z'),
      zoomOnMouseWheel: true,
      moveOnMouseMove: true,
    })
  })
})
