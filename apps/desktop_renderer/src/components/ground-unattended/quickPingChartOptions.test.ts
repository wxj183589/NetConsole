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
})
