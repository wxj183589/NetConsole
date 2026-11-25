// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { quickPingChartOption } from './quickPingChartOptions'
import { readNetConsoleChartTokens } from '../../theme/echarts'

describe('Quick Ping chart semantics', () => {
  it('uses real timestamps and retains loss and collection gap breaks', () => {
    const rows = [
      { received_at: '2026-11-07T00:00:00Z', sample: { status: 'SUCCESS', rtt_display_ms: 280, loss_percent: 0 } },
      { received_at: '2026-11-07T00:00:00.200Z', sample: { status: 'TIMEOUT', rtt_display_ms: null, loss_percent: 100 } },
      { received_at: '2026-11-07T00:00:00.400Z', sample: { status: 'SUCCESS', rtt_display_ms: 3, loss_percent: 0 } },
      { received_at: '2026-11-07T00:00:10Z', sample: { status: 'SUCCESS', rtt_display_ms: 4, loss_percent: 0 } },
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
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:00Z', sample: { status: 'SUCCESS', rtt_display_ms: 4, loss_percent: 0 } },
      { target_ip: '10.0.0.2', received_at: '2026-11-07T00:00:00.100Z', sample: { status: 'SUCCESS', rtt_display_ms: 8, loss_percent: 0 } },
    ], 200, readNetConsoleChartTokens()) as { series: Array<{ name: string; data: Array<[number, number | null]> }> }

    expect(option.series).toHaveLength(10)
    expect(option.series.map((series) => series.name)).toEqual([
      'RTT（ms） · 10.0.0.1', '连通 · 10.0.0.1', '丢包/超时 · 10.0.0.1', '自然秒丢包率 · 10.0.0.1', '未知 · 10.0.0.1',
      'RTT（ms） · 10.0.0.2', '连通 · 10.0.0.2', '丢包/超时 · 10.0.0.2', '自然秒丢包率 · 10.0.0.2', '未知 · 10.0.0.2',
    ])
    expect(option.series[0]!.data[0]![0]).toBe(Date.parse('2026-11-07T00:00:00Z'))
    expect(option.series[5]!.data[0]![0]).toBe(Date.parse('2026-11-07T00:00:00.100Z'))
  })

  it('renders Backend-provided natural-second buckets without recomputing them', () => {
    const option = quickPingChartOption([
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:00Z', sample: { status: 'SUCCESS', rtt_display_ms: 4, loss_percent: 0 } },
    ], 1000, readNetConsoleChartTokens(), { connectNulls: false }, undefined, '', undefined, [
      { target_ip: '10.0.0.1', start: '2026-11-07T00:00:00.000Z', packet_loss_rate: 37.5 },
    ]) as { series: Array<{ id: string; data: Array<[number, number | null]> }> }
    expect(option.series.find((series) => series.id === 'ping_loss_second:10.0.0.1')?.data).toEqual([[Date.parse('2026-11-07T00:00:00.000Z'), 37.5]])
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

  it('keeps timeout and probe-error timestamps as real gaps in RTT and connectivity lines', () => {
    const option = quickPingChartOption([
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:00Z', sample: { status: 'SUCCESS', rtt_display_ms: 4 } },
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:00.200Z', sample: { status: 'TIMEOUT', rtt_display_ms: null } },
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:00.400Z', sample: { status: 'SUCCESS', rtt_display_ms: 5 } },
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:10Z', sample: { status: 'ERROR', rtt_display_ms: null } },
      { target_ip: '10.0.0.1', received_at: '2026-11-07T00:00:10.200Z', sample: { status: 'SUCCESS', rtt_display_ms: 6 } },
    ], 200, readNetConsoleChartTokens()) as { series: Array<{ id: string; data: Array<[number, number | null]> }> }

    expect(option.series.find((series) => series.id === 'ping_rtt:10.0.0.1')?.data.map((point) => point[1]))
      .toEqual([4, null, 5, null, null, 6])
    expect(option.series.find((series) => series.id === 'ping_success:10.0.0.1')?.data.map((point) => point[1]))
      .toEqual([0, null, 0, null, null, 0])
  })

  it('limits rendered samples, preserves bucket extrema and failures, and clips rows to the logical time window', () => {
    const start = Date.parse('2026-11-07T00:00:00Z')
    const rows = Array.from({ length: 50_000 }, (_, index) => ({
      target_ip: '10.0.0.1',
      received_at: new Date(start + index * 200).toISOString(),
      sample: {
        status: index === 25_000 ? 'TIMEOUT' : 'SUCCESS',
        rtt_display_ms: index === 25_001 ? 9_999 : index % 10,
      },
    }))
    const option = quickPingChartOption(rows, 200, readNetConsoleChartTokens(), { connectNulls: false }, undefined, '', {
      start: new Date(start + 10_000).toISOString(),
      end: new Date(start + 9_990_000).toISOString(),
    }) as { series: Array<{ id: string; data: Array<[number, number | null]> }>; xAxis: { min: number; max: number } }
    const totalRenderedPoints = option.series.reduce((total, series) => total + series.data.length, 0)
    const rttData = option.series.find((series) => series.id === 'ping_rtt:10.0.0.1')?.data || []
    const times = rttData.map(([time]) => time)

    expect(totalRenderedPoints).toBeLessThanOrEqual(20_000)
    expect(times.every((time) => time >= start + 10_000 && time <= start + 9_990_000)).toBe(true)
    expect(rttData.some(([, value]) => value === 9_999)).toBe(true)
    expect(option.series.find((series) => series.id === 'ping_failure:10.0.0.1')?.data.some(([, value]) => value === 100)).toBe(true)
    expect(option.xAxis).toMatchObject({ min: start + 10_000, max: start + 9_990_000 })
  })
})
