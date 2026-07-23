import type { NetConsoleChartTokens } from '../../theme/echarts'
import {
  createNetConsoleAxisStyle,
  createNetConsoleDataZoomStyle,
  createNetConsoleLegendStyle,
  createNetConsoleTooltipStyle,
} from '../../theme/echarts'

export const LARGE_TIME_CHART_POINT_COUNT = 5_000
export const EXTREME_TIME_CHART_POINT_COUNT = 20_000
export const TIME_CHART_SYMBOL_THRESHOLD = 120
export const MIN_TIME_CHART_VIEWPORT_SPAN_MS = 1_000

export interface TimeChartDomain {
  full_start_time: string
  full_end_time: string
}

export interface TimeChartViewportValues {
  start_time: string
  end_time: string
}

export interface MultiSeriesTimeChartBaseOptions {
  title?: string
  unit: string
  pointCount: number
  fullDomain?: TimeChartDomain | null
  viewport?: TimeChartViewportValues | null
  showLegend?: boolean
  reserveLegendSpace?: boolean
}

export function isLargeTimeChart(pointCount: number): boolean {
  return pointCount >= LARGE_TIME_CHART_POINT_COUNT
}

export function resolveChartDevicePixelRatio(
  pointCount: number,
  devicePixelRatio = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1,
): number {
  const current = Math.max(1, devicePixelRatio)
  if (pointCount >= EXTREME_TIME_CHART_POINT_COUNT) return Math.min(current, 1)
  if (isLargeTimeChart(pointCount)) return Math.min(current, 1.5)
  return current
}

export interface TimeChartInitOverrides {
  useDirtyRect?: boolean
}

export function createTimeChartInitOptions(
  pointCount: number,
  overrides: TimeChartInitOverrides = {},
): {
  renderer: 'canvas'
  useDirtyRect: boolean
  devicePixelRatio: number
} {
  return {
    renderer: 'canvas',
    useDirtyRect: overrides.useDirtyRect ?? true,
    devicePixelRatio: resolveChartDevicePixelRatio(pointCount),
  }
}

export function stableTimeChartSeriesColor(
  key: string,
  palette: readonly string[],
): string | undefined {
  if (!palette.length) return undefined
  let hash = 2_166_136_261
  for (const character of key.trim().toLowerCase()) {
    hash ^= character.codePointAt(0) || 0
    hash = Math.imul(hash, 16_777_619)
  }
  return palette[Math.abs(hash) % palette.length]
}

export function normalizedApRadioColorKey(
  apMac: string | null | undefined,
  peerMac: string | null | undefined,
  radio: number | null | undefined,
): string {
  const mac = String(apMac || peerMac || 'unknown')
    .trim()
    .toLowerCase()
    .replace(/[^0-9a-f]/g, '')
  return `${mac || 'unknown'}:radio:${radio ?? 'unknown'}`
}

export function formatTimeChartAxisSecond(value: string | number): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = (item: number): string => String(item).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function createMultiSeriesTimeChartBaseOption(
  theme: NetConsoleChartTokens,
  options: MultiSeriesTimeChartBaseOptions,
): Record<string, unknown> {
  const axis = createNetConsoleAxisStyle(theme)
  const largeMode = isLargeTimeChart(options.pointCount)
  const showLegend = options.showLegend !== false
  const reserveLegendSpace = options.reserveLegendSpace !== false
  return {
    animation: false,
    color: theme.series,
    textStyle: { color: theme.text },
    title: options.title
      ? { text: options.title, left: 8, top: 0, textStyle: { color: theme.text, fontSize: 14, fontWeight: 600 } }
      : undefined,
    tooltip: {
      trigger: 'axis',
      appendToBody: true,
      confine: true,
      transitionDuration: largeMode ? 0 : 0.2,
      axisPointer: {
        type: 'line',
        snap: false,
        lineStyle: { color: theme.textSecondary, type: 'dashed', width: 1 },
      },
      ...createNetConsoleTooltipStyle(theme),
      textStyle: { color: theme.text, fontSize: 12, lineHeight: 20 },
    },
    legend: showLegend
      ? { type: 'scroll', bottom: 2, ...createNetConsoleLegendStyle(theme) }
      : { show: false, data: [] },
    toolbox: {
      right: 8,
      feature: {
        dataZoom: { yAxisIndex: 'none', title: { zoom: '框选缩放', back: '还原缩放' } },
        restore: { title: '恢复视图' },
        saveAsImage: { title: '保存图像', pixelRatio: 2 },
      },
    },
    grid: { left: 58, right: 24, top: 32, bottom: reserveLegendSpace ? 72 : 52, containLabel: true },
    xAxis: {
      type: 'time',
      min: options.fullDomain?.full_start_time,
      max: options.fullDomain?.full_end_time,
      minInterval: MIN_TIME_CHART_VIEWPORT_SPAN_MS,
      axisPointer: { snap: false },
      ...axis,
      axisLabel: {
        ...axis.axisLabel,
        formatter: formatTimeChartAxisSecond,
      },
    },
    yAxis: {
      type: 'value',
      name: options.unit,
      nameTextStyle: { color: theme.textSecondary },
      ...axis,
    },
    dataZoom: [
      {
        type: 'inside',
        filterMode: 'none',
        minValueSpan: MIN_TIME_CHART_VIEWPORT_SPAN_MS,
        startValue: options.viewport?.start_time,
        endValue: options.viewport?.end_time,
      },
      {
        type: 'slider',
        height: 18,
        bottom: reserveLegendSpace ? 28 : 12,
        filterMode: 'none',
        minValueSpan: MIN_TIME_CHART_VIEWPORT_SPAN_MS,
        startValue: options.viewport?.start_time,
        endValue: options.viewport?.end_time,
        ...createNetConsoleDataZoomStyle(theme),
      },
    ],
  }
}

export function createTimeChartLinePresentation(pointCount: number): {
  showSymbol: boolean
  symbol: 'circle' | 'none'
  symbolSize: number
  emphasis: { disabled: boolean }
  lineStyle: { width: number }
} {
  const largeMode = isLargeTimeChart(pointCount)
  const showSymbol = !largeMode && pointCount < TIME_CHART_SYMBOL_THRESHOLD
  return {
    showSymbol,
    symbol: showSymbol ? 'circle' : 'none',
    symbolSize: 5,
    emphasis: { disabled: largeMode },
    lineStyle: { width: 2 },
  }
}
