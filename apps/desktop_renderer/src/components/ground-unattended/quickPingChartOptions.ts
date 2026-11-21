import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'
import { formatTimelineMetricValue, timelineMetricDefinition } from '../rail-timeline/timelineMetricPresentation'
import type { NetConsoleChartTokens } from '../../theme/echarts'
import { PING_CHART_COLORS, pingPointValues, pingTooltipFormatter, type PingChartPoint } from './pingChartStatus'

export function quickPingChartOption(
  rows: Array<Record<string, unknown>>, intervalMs: number, theme: NetConsoleChartTokens,
  gapPolicy: { connectNulls: false } = { connectNulls: false },
  viewport?: { start: string; end: string }, selectedTime = '', fullDomain?: { start: string; end: string },
): Record<string, unknown> {
  const points: PingChartPoint[] = rows.flatMap((row) => {
    const sample = row.sample as Record<string, unknown> | undefined
    const time = Date.parse(String(row.received_at || ''))
    if (!Number.isFinite(time) || !sample) return []
    const target = String(row.target_ip || sample.target_ip || sample.mr_name || sample.mr_role || '目标')
    return [{ target, time, ...pingPointValues(sample) }]
  }).sort((a, b) => a.time - b.time)
  const targetKeys = [...new Set(points.map((point) => point.target))]
  const buildSeriesData = (target: string) => {
    const targetPoints = points.filter((point) => point.target === target)
    const rtt: Array<[number, number | null]> = [], success: Array<[number, number | null]> = [], failure: Array<[number, number | null]> = [], unknown: Array<[number, string]> = []
    for (let index = 0; index < targetPoints.length; index++) {
      const point = targetPoints[index]!, previous = targetPoints[index - 1]
      if (previous && point.time - previous.time > Math.max(1000, intervalMs * 3)) {
        rtt.push([previous.time + 1, null]); success.push([previous.time + 1, null]); failure.push([previous.time + 1, null])
      }
      rtt.push([point.time, point.rtt]); success.push([point.time, point.status === 'SUCCESS' ? 0 : null]); failure.push([point.time, point.status === 'TIMEOUT' || point.status === 'PACKET_LOSS' ? point.loss : null]); if (point.status === 'UNKNOWN') unknown.push([point.time, 'UNKNOWN'])
    }
    return { rtt, success, failure, unknown }
  }
  const metric = timelineMetricDefinition('ping_rtt')!
  const axisStart = Date.parse(fullDomain?.start || '')
  const axisEnd = Date.parse(fullDomain?.end || '')
  const fallbackStart = points[0]?.time
  const fallbackEnd = points[points.length - 1]?.time
  const fullStart = Number.isFinite(axisStart) ? axisStart : fallbackStart
  const fullEnd = Number.isFinite(axisEnd) ? axisEnd : fallbackEnd
  const dataZoom = viewport ? [{ type: 'inside', filterMode: 'none', zoomOnMouseWheel: true, moveOnMouseMove: true, startValue: Date.parse(viewport.start), endValue: Date.parse(viewport.end), minValueSpan: 1000 }] : undefined
  const baseOption = createMultiSeriesTimeChartBaseOption(theme, { unit: metric.axisUnit, pointCount: points.length, showLegend: true })
  return {
    ...baseOption,
    // ECharts 6 modular builds use outer bounds to keep axis labels inside the grid.
    grid: { left: 58, right: 24, top: 32, bottom: 72, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
    toolbox: { show: false },
    ...(dataZoom ? { dataZoom } : {}),
    color: [PING_CHART_COLORS.rtt, PING_CHART_COLORS.success, PING_CHART_COLORS.failure, PING_CHART_COLORS.unknown],
    xAxis: { type: 'time', min: fullStart, max: fullEnd, axisPointer: { show: true, snap: false } },
    tooltip: {
      trigger: 'axis', appendToBody: false, confine: true,
      extraCssText: 'pointer-events:none;max-width:360px;max-height:220px;overflow:hidden',
      formatter: (params: unknown) => pingTooltipFormatter(points, params),
    },
    yAxis: [
      { type: 'value', name: metric.axisUnit, min: metric.axisMin, axisLabel: { formatter: (value: number) => formatTimelineMetricValue('ping_rtt', value) } },
      { type: 'value', name: '%', min: 0, max: 100, axisLabel: { formatter: (value: number) => formatTimelineMetricValue('ping_loss', value) }, splitLine: { show: false } },
      { type: 'category', data: ['UNKNOWN'], show: false },
    ],
    series: targetKeys.flatMap((target) => {
      const data = buildSeriesData(target)
      const suffix = targetKeys.length > 1 ? ` · ${target}` : ''
      return [
        { id: `ping_rtt:${target}`, name: `RTT（ms）${suffix}`, type: 'line', showSymbol: false, ...gapPolicy, data: data.rtt, lineStyle: { color: PING_CHART_COLORS.rtt }, itemStyle: { color: PING_CHART_COLORS.rtt }, markLine: selectedTime ? { silent: true, symbol: 'none', data: [{ xAxis: Date.parse(selectedTime) }] } : { data: [] }, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_rtt', value) } },
        { id: `ping_success:${target}`, name: `连通${suffix}`, type: 'line', yAxisIndex: 1, showSymbol: true, symbolSize: 6, ...gapPolicy, data: data.success, lineStyle: { color: PING_CHART_COLORS.success, width: 2 }, itemStyle: { color: PING_CHART_COLORS.success }, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_loss', value) } },
        { id: `ping_failure:${target}`, name: `丢包/超时${suffix}`, type: 'line', yAxisIndex: 1, showSymbol: true, symbolSize: 7, ...gapPolicy, data: data.failure, lineStyle: { color: PING_CHART_COLORS.failure, width: 2 }, itemStyle: { color: PING_CHART_COLORS.failure }, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_loss', value) } },
        { id: `ping_unknown:${target}`, name: `未知${suffix}`, type: 'scatter', yAxisIndex: 2, symbol: 'diamond', symbolSize: 8, data: data.unknown, itemStyle: { color: PING_CHART_COLORS.unknown } },
      ]
    }),
  }
}
