import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'
import { formatTimelineMetricValue, timelineMetricDefinition } from '../rail-timeline/timelineMetricPresentation'
import type { NetConsoleChartTokens } from '../../theme/echarts'
import { PING_CHART_COLORS, isPingFailureStatus, isPingUncertainStatus, pingPointValues, pingTooltipFormatter, type PingChartPoint } from './pingChartStatus'

const MAX_RENDERED_PING_SAMPLES = 4_000
const MAX_SAMPLES_PER_BUCKET = 8

export function quickPingChartOption(
  rows: Array<Record<string, unknown>>, intervalMs: number, theme: NetConsoleChartTokens,
  gapPolicy: { connectNulls: false } = { connectNulls: false },
  viewport?: { start: string; end: string }, selectedTime = '', fullDomain?: { start: string; end: string },
  secondLossBuckets: Array<Record<string, unknown>> = [],
): Record<string, unknown> {
  const axisStart = Date.parse(fullDomain?.start || '')
  const axisEnd = Date.parse(fullDomain?.end || '')
  const hasFullDomain = Number.isFinite(axisStart) && Number.isFinite(axisEnd) && axisStart < axisEnd
  const points: PingChartPoint[] = rows.flatMap((row) => {
    // Archived samples are flat DTOs; live harness rows may wrap the sample.
    const nested = row.sample
    const sample = nested && typeof nested === 'object' ? nested as Record<string, unknown> : row
    const time = Date.parse(String(row.received_at || row.ts || sample.received_at || sample.ts || ''))
    if (!Number.isFinite(time) || (hasFullDomain && (time < axisStart || time > axisEnd))) return []
    const target = String(row.target_ip || sample.target_ip || sample.mr_name || sample.mr_role || '目标')
    return [{ target, time, ...pingPointValues(sample) }]
  }).sort((a, b) => a.time - b.time || a.target.localeCompare(b.target))
  const targetKeys = [...new Set(points.map((point) => point.target))]
  const renderedPoints = boundPointsByTime(points, targetKeys)
  const buildSeriesData = (target: string) => {
    const targetPoints = renderedPoints.filter((point) => point.target === target)
    const failures: Array<[{ name: string; xAxis: number }, { xAxis: number }]> = []
    let firstFailure: PingChartPoint | undefined
    let lastFailure: PingChartPoint | undefined
    function closeFailures(recovered?: PingChartPoint): void {
      if (firstFailure && lastFailure && firstFailure.time !== lastFailure.time) {
        const recovery = recovered ? new Date(recovered.time).toLocaleString() : '未观测到恢复'
        failures.push([{ name: `连续失败 · ${recovery}`, xAxis: firstFailure.time }, { xAxis: recovered?.time ?? lastFailure.time }])
      }
      firstFailure = lastFailure = undefined
    }
    for (const point of points) {
      if (point.target !== target) continue
      if (lastFailure && point.time - lastFailure.time > Math.max(1000, intervalMs * 3)) closeFailures()
      if (isPingFailureStatus(point.status)) {
        firstFailure ??= point
        lastFailure = point
      } else closeFailures(point.status === 'SUCCESS' ? point : undefined)
    }
    closeFailures()
    const rtt: Array<[number, number | null]> = [], success: Array<[number, number | null]> = [], failure: Array<[number, number | null]> = [], unknown: Array<[number, string]> = []
    for (let index = 0; index < targetPoints.length; index++) {
      const point = targetPoints[index]!, previous = targetPoints[index - 1]
      if (previous && point.time - previous.time > Math.max(1000, intervalMs * 3)) {
        rtt.push([previous.time + 1, null]); success.push([previous.time + 1, null]); failure.push([previous.time + 1, null])
      }
      const failureStatus = isPingFailureStatus(point.status)
      const uncertainStatus = isPingUncertainStatus(point.status)
      rtt.push([point.time, point.status === 'SUCCESS' ? point.rtt : null])
      success.push([point.time, point.status === 'SUCCESS' ? 0 : null])
      failure.push([point.time, failureStatus ? point.loss ?? 100 : null])
      if (uncertainStatus) unknown.push([point.time, point.status])
    }
    const secondLossPoints = secondLossBuckets
      .filter((bucket) => !bucket.target_ip || String(bucket.target_ip) === target)
      .map((bucket) => [Date.parse(String(bucket.start || '')), typeof bucket.packet_loss_rate === 'number' ? bucket.packet_loss_rate : null] as [number, number | null])
      .filter(([time]) => Number.isFinite(time))
      .sort((left, right) => left[0] - right[0])
    const secondLoss: Array<[number, number | null]> = []
    secondLossPoints.forEach((point, index) => {
      const previous = secondLossPoints[index - 1]
      if (previous && point[0] - previous[0] > 1_000) secondLoss.push([previous[0] + 1, null])
      secondLoss.push(point)
    })
    return { rtt, success, failure, unknown, secondLoss, failures }
  }
  const metric = timelineMetricDefinition('ping_rtt')!
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
        { id: `ping_failure:${target}`, name: `丢包/超时${suffix}`, type: 'line', yAxisIndex: 1, showSymbol: true, symbolSize: 7, ...gapPolicy, data: data.failure, lineStyle: { color: PING_CHART_COLORS.failure, width: 2 }, itemStyle: { color: PING_CHART_COLORS.failure }, markArea: { itemStyle: { color: PING_CHART_COLORS.failure, opacity: 0.12 }, label: { show: false }, data: data.failures }, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_loss', value) } },
        { id: `ping_loss_second:${target}`, name: `自然秒丢包率${suffix}`, type: 'line', yAxisIndex: 1, showSymbol: false, ...gapPolicy, data: data.secondLoss, lineStyle: { color: PING_CHART_COLORS.failure, width: 1, type: 'dashed' }, itemStyle: { color: PING_CHART_COLORS.failure }, tooltip: { valueFormatter: (value: number | null) => formatTimelineMetricValue('ping_loss', value) } },
        { id: `ping_unknown:${target}`, name: `未知${suffix}`, type: 'scatter', yAxisIndex: 2, symbol: 'diamond', symbolSize: 8, data: data.unknown, itemStyle: { color: PING_CHART_COLORS.unknown } },
      ]
    }),
  }
}

function boundPointsByTime(points: PingChartPoint[], targets: string[]): PingChartPoint[] {
  if (points.length <= MAX_RENDERED_PING_SAMPLES || targets.length === 0) return points

  const sampleBudget = Math.max(1, Math.floor(MAX_RENDERED_PING_SAMPLES / targets.length))
  const pointsByTarget = new Map(targets.map((target) => [target, [] as PingChartPoint[]]))
  points.forEach((point) => pointsByTarget.get(point.target)?.push(point))
  const bounded: PingChartPoint[] = []

  for (const target of targets) {
    const targetPoints = pointsByTarget.get(target) || []
    if (targetPoints.length <= sampleBudget) {
      bounded.push(...targetPoints)
      continue
    }

    const bucketCount = Math.max(1, Math.floor(sampleBudget / MAX_SAMPLES_PER_BUCKET))
    for (let bucketIndex = 0; bucketIndex < bucketCount; bucketIndex += 1) {
      const start = Math.floor(bucketIndex * targetPoints.length / bucketCount)
      const end = Math.floor((bucketIndex + 1) * targetPoints.length / bucketCount)
      const bucket = targetPoints.slice(start, end)
      if (!bucket.length) continue

      const successes = bucket.filter((point) => point.status === 'SUCCESS' && point.rtt !== null)
      const failures = bucket.filter((point) => isPingFailureStatus(point.status))
      const uncertain = bucket.filter((point) => isPingUncertainStatus(point.status))
      const selected = new Set<PingChartPoint>([
        bucket[0]!,
        bucket[bucket.length - 1]!,
        ...edgePoints(successes),
        ...edgePoints(failures),
        ...edgePoints(uncertain),
      ])
      if (successes.length) {
        selected.add(successes.reduce((lowest, point) => point.rtt! < lowest.rtt! ? point : lowest))
        selected.add(successes.reduce((highest, point) => point.rtt! > highest.rtt! ? point : highest))
      }
      bounded.push(...[...selected].sort((left, right) => left.time - right.time))
    }
  }

  return bounded.sort((left, right) => left.time - right.time || left.target.localeCompare(right.target))
}

function edgePoints(points: PingChartPoint[]): PingChartPoint[] {
  return points.length > 1 ? [points[0]!, points[points.length - 1]!] : points
}
