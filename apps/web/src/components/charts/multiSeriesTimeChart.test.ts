import { describe, expect, it } from 'vitest'

import type { NetConsoleChartTokens } from '../../theme/echarts'
import {
  createMultiSeriesTimeChartBaseOption,
  createTimeChartInitOptions,
  createTimeChartLinePresentation,
  formatTimeChartAxisSecond,
  normalizedApRadioColorKey,
  resolveChartDevicePixelRatio,
  stableTimeChartSeriesColor,
} from './multiSeriesTimeChart'

const theme: NetConsoleChartTokens = {
  series: ['#1', '#2', '#3'],
  text: '#text',
  textSecondary: '#secondary',
  background: '#background',
  backgroundMuted: '#muted',
  border: '#border',
  splitLine: '#split',
  active: '#active',
  primary: '#primary',
  warning: '#warning',
  danger: '#danger',
  info: '#info',
}

describe('shared multi-series time chart core', () => {
  it('uses Canvas dirty rectangles and caps only high-volume chart DPR', () => {
    expect(createTimeChartInitOptions(14_581)).toMatchObject({
      renderer: 'canvas',
      useDirtyRect: true,
    })
    expect(createTimeChartInitOptions(14_581, { useDirtyRect: false })).toEqual({
      renderer: 'canvas',
      useDirtyRect: false,
      devicePixelRatio: 1,
    })
    expect(resolveChartDevicePixelRatio(1_000, 2.5)).toBe(2.5)
    expect(resolveChartDevicePixelRatio(14_581, 2.5)).toBe(1.5)
    expect(resolveChartDevicePixelRatio(25_000, 2.5)).toBe(1)
  })

  it('shares the Online MR layout and absolute time domain', () => {
    const option = createMultiSeriesTimeChartBaseOption(theme, {
      title: '主链路 RSSI',
      unit: 'dBm',
      pointCount: 14_581,
      fullDomain: {
        full_start_time: '2026-07-20 09:00:00.000',
        full_end_time: '2026-07-20 12:00:00.000',
      },
      viewport: {
        start_time: '2026-07-20 10:00:00.500',
        end_time: '2026-07-20 10:00:03.500',
      },
    }) as {
      animation: boolean
      grid: Record<string, unknown>
      legend: { type: string }
      toolbox: { feature: Record<string, unknown> }
      xAxis: { min: string; max: string; minInterval: number; axisLabel: { formatter: (value: string | number) => string } }
      yAxis: { name: string }
      dataZoom: Array<{ startValue: string; endValue: string; minValueSpan: number }>
    }
    expect(option.animation).toBe(false)
    expect(option.legend.type).toBe('scroll')
    expect(option.grid).toEqual({ left: 58, right: 24, top: 32, bottom: 72, containLabel: true })
    expect(option.toolbox.feature).toHaveProperty('restore')
    expect(option.xAxis).toMatchObject({
      min: '2026-07-20 09:00:00.000',
      max: '2026-07-20 12:00:00.000',
      minInterval: 1_000,
    })
    expect(option.yAxis.name).toBe('dBm')
    expect(option.dataZoom[0]).toMatchObject({
      startValue: '2026-07-20 10:00:00.500',
      endValue: '2026-07-20 10:00:03.500',
      minValueSpan: 1_000,
    })
    expect(option.dataZoom[1].minValueSpan).toBe(1_000)
    expect(option.xAxis.axisLabel.formatter('2026-07-20T10:00:00.181Z')).not.toContain('.181')
    expect(formatTimeChartAxisSecond('2026-07-20T10:00:00.181Z')).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })

  it('can hide one chart legend and release its reserved bottom space without changing defaults', () => {
    const hidden = createMultiSeriesTimeChartBaseOption(theme, {
      unit: 'RSSI',
      pointCount: 481,
      showLegend: false,
      reserveLegendSpace: false,
    }) as {
      legend: { show: boolean; data: unknown[] }
      grid: { bottom: number }
      dataZoom: Array<{ bottom?: number }>
    }
    expect(hidden.legend).toEqual({ show: false, data: [] })
    expect(hidden.grid.bottom).toBe(52)
    expect(hidden.dataZoom[1].bottom).toBe(12)

    const regular = createMultiSeriesTimeChartBaseOption(theme, {
      unit: 'Mbps',
      pointCount: 2,
    }) as {
      legend: { show?: boolean }
      grid: { bottom: number }
      dataZoom: Array<{ bottom?: number }>
    }
    expect(regular.legend.show).not.toBe(false)
    expect(regular.grid.bottom).toBe(72)
    expect(regular.dataZoom[1].bottom).toBe(28)
  })

  it('disables symbols and emphasis in large mode and keeps AP/Radio colors stable', () => {
    expect(createTimeChartLinePresentation(14_581)).toMatchObject({
      showSymbol: false,
      symbol: 'none',
      emphasis: { disabled: true },
    })
    const firstKey = normalizedApRadioColorKey('bc5a-3457-3a00', null, 1)
    const sameKey = normalizedApRadioColorKey('BC:5A:34:57:3A:00', null, 1)
    expect(firstKey).toBe(sameKey)
    expect(stableTimeChartSeriesColor(firstKey, theme.series)).toBe(
      stableTimeChartSeriesColor(sameKey, theme.series),
    )
  })
})
