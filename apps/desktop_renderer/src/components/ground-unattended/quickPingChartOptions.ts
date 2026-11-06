import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'
import { formatTimelineMetricValue, timelineMetricDefinition } from '../rail-timeline/timelineMetricPresentation'
import type { NetConsoleChartTokens } from '../../theme/echarts'

export function quickPingChartOption(
  rows: Array<Record<string, unknown>>, intervalMs: number, theme: NetConsoleChartTokens,
  gapPolicy: { connectNulls: false } = { connectNulls: false },
): Record<string, unknown> {
  const points = rows.flatMap((row) => {
    const sample = row.sample as Record<string, unknown> | undefined
    const time = Date.parse(String(row.received_at || ''))
    if (!Number.isFinite(time) || !sample) return []
    return [{ time, rtt: sample.ok && typeof sample.rtt_ms === 'number' && Number.isFinite(sample.rtt_ms) ? sample.rtt_ms : null, loss: sample.ok ? 0 : 100 }]
  }).sort((a, b) => a.time - b.time)
  const rtt: Array<[number, number | null]> = [], loss: Array<[number, number | null]> = []
  for (let index = 0; index < points.length; index++) {
    const point = points[index]!, previous = points[index - 1]
    if (previous && point.time - previous.time > Math.max(1000, intervalMs * 3)) {
      rtt.push([previous.time + 1, null]); loss.push([previous.time + 1, null])
    }
    rtt.push([point.time, point.rtt]); loss.push([point.time, point.loss])
  }
  const metric = timelineMetricDefinition('ping_rtt')!
  return {
    ...createMultiSeriesTimeChartBaseOption(theme, { unit: metric.axisUnit, pointCount: points.length, showLegend: true }),
    // ECharts 6 modular builds use outer bounds to keep axis labels inside the grid.
    grid: { left: 58, right: 24, top: 32, bottom: 72, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
    toolbox: { show: false },
    tooltip: {
      trigger: 'axis', appendToBody: false, confine: true,
      extraCssText: 'pointer-events:none;max-width:360px;max-height:220px;overflow:hidden',
      valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_rtt', value),
    },
    yAxis: [
      { type: 'value', name: metric.axisUnit, min: metric.axisMin, axisLabel: { formatter: (value: number) => formatTimelineMetricValue('ping_rtt', value) } },
      { type: 'value', name: '%', min: 0, max: 100, axisLabel: { formatter: (value: number) => formatTimelineMetricValue('ping_loss', value) }, splitLine: { show: false } },
    ],
    series: [
      { id: 'ping_rtt', name: 'RTT', type: 'line', showSymbol: false, ...gapPolicy, data: rtt, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_rtt', value) } },
      { id: 'ping_loss', name: '单包丢包', type: 'line', yAxisIndex: 1, showSymbol: false, ...gapPolicy, step: 'end', data: loss, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_loss', value) } },
    ],
  }
}
