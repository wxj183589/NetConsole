import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'
import { formatTimelineMetricValue, timelineMetricDefinition } from '../rail-timeline/timelineMetricPresentation'
import type { NetConsoleChartTokens } from '../../theme/echarts'

export function quickPingChartOption(
  rows: Array<Record<string, unknown>>, intervalMs: number, theme: NetConsoleChartTokens,
  gapPolicy: { connectNulls: false } = { connectNulls: false },
  viewport?: { start: string; end: string }, selectedTime = '',
): Record<string, unknown> {
  const points = rows.flatMap((row) => {
    const sample = row.sample as Record<string, unknown> | undefined
    const time = Date.parse(String(row.received_at || ''))
    if (!Number.isFinite(time) || !sample) return []
    const target = String(row.target_ip || sample.target_ip || sample.mr_name || sample.mr_role || '目标')
    return [{ target, time, rtt: sample.ok && typeof sample.rtt_ms === 'number' && Number.isFinite(sample.rtt_ms) ? sample.rtt_ms : null, loss: sample.ok ? 0 : 100 }]
  }).sort((a, b) => a.time - b.time)
  const targetKeys = [...new Set(points.map((point) => point.target))]
  const buildSeriesData = (target: string) => {
    const targetPoints = points.filter((point) => point.target === target)
    const rtt: Array<[number, number | null]> = [], loss: Array<[number, number | null]> = []
    for (let index = 0; index < targetPoints.length; index++) {
      const point = targetPoints[index]!, previous = targetPoints[index - 1]
      if (previous && point.time - previous.time > Math.max(1000, intervalMs * 3)) {
        rtt.push([previous.time + 1, null]); loss.push([previous.time + 1, null])
      }
      rtt.push([point.time, point.rtt]); loss.push([point.time, point.loss])
    }
    return { rtt, loss }
  }
  const metric = timelineMetricDefinition('ping_rtt')!
  const dataZoom = viewport ? [{ type: 'inside', filterMode: 'none', startValue: Date.parse(viewport.start), endValue: Date.parse(viewport.end), minValueSpan: 1000 }] : undefined
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, { unit: metric.axisUnit, pointCount: points.length, showLegend: true })
  return {
    ...baseOption,
    // ECharts 6 modular builds use outer bounds to keep axis labels inside the grid.
    grid: { left: 58, right: 24, top: 32, bottom: 72, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
    toolbox: { show: false },
    ...(dataZoom ? { dataZoom } : {}),
    xAxis: { type: 'time', axisPointer: { show: true, snap: false } },
    tooltip: {
      trigger: 'axis', appendToBody: false, confine: true,
      extraCssText: 'pointer-events:none;max-width:360px;max-height:220px;overflow:hidden',
      valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_rtt', value),
    },
    yAxis: [
      { type: 'value', name: metric.axisUnit, min: metric.axisMin, axisLabel: { formatter: (value: number) => formatTimelineMetricValue('ping_rtt', value) } },
      { type: 'value', name: '%', min: 0, max: 100, axisLabel: { formatter: (value: number) => formatTimelineMetricValue('ping_loss', value) }, splitLine: { show: false } },
    ],
    series: targetKeys.flatMap((target) => {
      const data = buildSeriesData(target)
      const suffix = targetKeys.length > 1 ? ` · ${target}` : ''
      return [
        { id: `ping_rtt:${target}`, name: `RTT${suffix}`, type: 'line', showSymbol: false, ...gapPolicy, data: data.rtt, markLine: selectedTime ? { silent: true, symbol: 'none', data: [{ xAxis: Date.parse(selectedTime) }] } : { data: [] }, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_rtt', value) } },
        { id: `ping_loss:${target}`, name: `单包丢包${suffix}`, type: 'line', yAxisIndex: 1, showSymbol: false, ...gapPolicy, step: 'end', data: data.loss, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_loss', value) } },
      ]
    }),
  }
}
