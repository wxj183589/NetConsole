import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { t } from '../../i18n/runtime'
import type { NetConsoleChartTokens } from '../../theme/echarts'
import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'
import { PING_CHART_COLORS, heartbeatPointValues, pingPointValues, pingTooltipFormatter, type PingChartPoint } from './pingChartStatus'

const escape = (value: unknown): string => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
const sourceLabel = (value: unknown): string => ({ SYSLOG: 'Syslog', AC: 'AC Mesh-Link' } as Record<string, string>)[String(value || '').toUpperCase()] || '无数据'
export const PEER_RAINBOW_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6'] as const
type PeerIntervalLike = GroundMrMonitoring['peer_intervals'][number]

function peerIntervalIdentity(row: PeerIntervalLike): string {
  const normalizeMac = (value: unknown): string => String(value || '').trim().toLowerCase().replace(/[^0-9a-f]/g, '')
  return [normalizeMac(row.bssid), normalizeMac(row.peer_mac), String(row.peer_name || '').trim().toLowerCase(), String(row.source || '').trim().toLowerCase()].join('|')
}

/**
 * Build the color order from the complete queried run, before any viewport filter.
 * This makes colors represent interval chronology rather than AP identity or page order.
 */
export function chronologicalPeerIntervals(rows: PeerIntervalLike[]): PeerIntervalLike[] {
  const unique = new Map<string, { row: PeerIntervalLike; index: number }>()
  rows.forEach((row, index) => {
    const key = [row.start, row.end, peerIntervalIdentity(row)].join('|')
    if (!unique.has(key)) unique.set(key, { row, index })
  })
  return [...unique.values()]
    .sort((left, right) => {
      const start = Date.parse(left.row.start) - Date.parse(right.row.start)
      if (Number.isFinite(start) && start !== 0) return start
      const end = Date.parse(left.row.end) - Date.parse(right.row.end)
      if (Number.isFinite(end) && end !== 0) return end
      const identity = peerIntervalIdentity(left.row).localeCompare(peerIntervalIdentity(right.row))
      return identity || left.index - right.index
    })
    .map(({ row }) => row)
}

export function peerIntervalColorMap(rows: PeerIntervalLike[]): Map<string, string> {
  return new Map(chronologicalPeerIntervals(rows).map((row, index) => [
    [row.start, row.end, peerIntervalIdentity(row)].join('|'),
    PEER_RAINBOW_COLORS[index % PEER_RAINBOW_COLORS.length]!,
  ]))
}

function peerIntervalColor(row: PeerIntervalLike, colors: Map<string, string>): string {
  return colors.get([row.start, row.end, peerIntervalIdentity(row)].join('|')) || PEER_RAINBOW_COLORS[0]
}

export function mrMonitoringChartOption(
  data: GroundMrMonitoring,
  start: string,
  end: string,
  theme: NetConsoleChartTokens,
  selectedTime = '',
  mode: 'all' | 'ping' | 'peer' | 'navigator' | 'heartbeat' = 'all',
  viewportStart = start,
  viewportEnd = end,
): Record<string, unknown> {
  const begin = Date.parse(start), finish = Date.parse(end)
  const visibleBegin = Date.parse(viewportStart), visibleFinish = Date.parse(viewportEnd)
  const dataZoom = (xAxisIndex: number | number[] = 0, slider = false): Array<Record<string, unknown>> => [
    { type: 'inside', xAxisIndex, filterMode: 'none', zoomOnMouseWheel: true, moveOnMouseMove: true, startValue: visibleBegin, endValue: visibleFinish, minValueSpan: 1000 },
    ...(slider ? [{ type: 'slider', xAxisIndex, bottom: 8, filterMode: 'none', zoomOnMouseWheel: true, moveOnMouseMove: true, startValue: visibleBegin, endValue: visibleFinish, minValueSpan: 1000 }] : []),
  ]
  const points = data.series.points.filter((point) => !point.warmup_ignored && Date.parse(point.ts) >= begin && Date.parse(point.ts) <= finish)
  const ips = [...new Set(points.map((point) => point.target_ip))]
  const intervalColors = peerIntervalColorMap(data.peer_intervals)
  const intervals = chronologicalPeerIntervals(data.peer_intervals).filter((row) => Date.parse(row.end) >= begin && Date.parse(row.start) <= finish)
  const peers = [...new Set(intervals.map((row) => row.peer_name || row.bssid || 'UNKNOWN'))]
  const meshEvents = (data.mesh_events || []).filter((row) => Date.parse(row.event_time || row.receive_time) >= begin && Date.parse(row.event_time || row.receive_time) <= finish)
  if (mode === 'navigator') {
    return {
      ...createMultiSeriesTimeChartBaseOption(theme, { unit: '', pointCount: 2, showLegend: false, reserveLegendSpace: false }),
      toolbox: { show: false }, tooltip: { show: false },
      grid: { left: 65, right: 50, top: 4, bottom: 42 },
      xAxis: { type: 'time', min: begin, max: finish, axisLabel: { show: false }, axisTick: { show: false } },
      yAxis: { type: 'value', min: 0, max: 1, show: false },
      dataZoom: dataZoom(0, true),
      series: [{ id: 'global-window', type: 'line', data: [[begin, 0], [finish, 0]], symbol: 'none', lineStyle: { opacity: 0 }, silent: true,
        markLine: selectedTime ? { silent: true, symbol: 'none', data: [{ xAxis: Date.parse(selectedTime), label: { show: false } }] } : { data: [] } }],
    }
  }
  if (mode === 'heartbeat') {
    const statusRows = ips.flatMap((ip) => points
      .filter((point) => point.target_ip === ip)
      .sort((left, right) => Date.parse(left.ts) - Date.parse(right.ts)))
    const statusSeries = ips.flatMap((ip) => {
      const rows = statusRows.filter((point) => point.target_ip === ip)
      const suffix = ips.length > 1 ? ` · ${ip}` : ''
      const online: Array<[number, number | null]> = [], offline: Array<[number, number | null]> = [], unknown: Array<[number, number | null]> = []
      rows.forEach((row) => {
        const status = heartbeatPointValues(row as unknown as Record<string, unknown>).status
        online.push([Date.parse(row.ts), status === 'SUCCESS' ? 1 : null])
        offline.push([Date.parse(row.ts), status === 'TIMEOUT' || status === 'PACKET_LOSS' ? 0 : null])
        unknown.push([Date.parse(row.ts), status === 'UNKNOWN' ? 0.5 : null])
      })
      return [
        { id: `heartbeat-online:${ip}`, name: `正常连通${suffix}`, type: 'line', data: online, connectNulls: false, showSymbol: true, symbolSize: 7, lineStyle: { color: PING_CHART_COLORS.success, width: 2 }, itemStyle: { color: PING_CHART_COLORS.success } },
        { id: `heartbeat-offline:${ip}`, name: `不通/超时${suffix}`, type: 'line', data: offline, connectNulls: false, showSymbol: true, symbolSize: 7, lineStyle: { color: PING_CHART_COLORS.failure, width: 2 }, itemStyle: { color: PING_CHART_COLORS.failure } },
        { id: `heartbeat-unknown:${ip}`, name: `未知${suffix}`, type: 'scatter', data: unknown, symbol: 'diamond', symbolSize: 8, itemStyle: { color: PING_CHART_COLORS.unknown } },
      ]
    })
    return {
      ...createMultiSeriesTimeChartBaseOption(theme, { unit: '', pointCount: statusRows.length, showLegend: true }),
      color: [PING_CHART_COLORS.success, PING_CHART_COLORS.failure, PING_CHART_COLORS.unknown], toolbox: { show: false },
      legend: { top: 4, type: 'scroll' }, grid: { left: 65, right: 50, top: 44, bottom: 64, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
      xAxis: { type: 'time', min: begin, max: finish, axisPointer: { show: true, snap: false } },
      yAxis: { type: 'value', min: 0, max: 1, interval: 1, name: '通断', axisLabel: { formatter: (value: number) => value === 1 ? '连通' : '不通' }, splitLine: { show: false } },
      dataZoom: dataZoom(),
      tooltip: { trigger: 'axis', confine: true, appendToBody: false, formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params as Array<{ axisValue?: number | string; data?: [number, number | null] }> : []
        const time = Number(rows[0]?.axisValue)
        const samples = statusRows.filter((point) => Date.parse(point.ts) === time)
        const details = samples.length
          ? samples.map((point) => {
            const status = heartbeatPointValues(point as unknown as Record<string, unknown>).status
            const label = status === 'SUCCESS' ? '正常连通' : status === 'UNKNOWN' ? '未知' : '超时/不通'
            const rawResult = typeof point.ok === 'boolean' ? (point.ok ? '成功响应' : '失败/超时') : '状态缺失'
            return `管理地址：${escape(point.target_ip)}<br>状态：${label}<br>原始采集结果：${rawResult}<br>采样来源：Heartbeat`
          }).join('<br>')
          : '管理地址：无数据<br>状态：未知<br>采样来源：Heartbeat'
        return `采样时间：${Number.isFinite(time) ? escape(new Date(time).toLocaleString()) : '无数据'}<br>${details}`
      } },
      series: statusSeries,
    }
  }
  if (mode === 'peer') {
    const peerData = intervals.map((row, index) => {
      const rssi = Number.isFinite(row.rssi) ? Number(row.rssi) : null
      return [Math.max(begin, Date.parse(row.start)), Math.min(finish, Date.parse(row.end)), rssi, index]
    })
    const observed = intervals.map((row) => row.rssi).filter((value): value is number => Number.isFinite(value))
    const peerMin = Math.min(-100, ...(observed.length ? observed : [-100]))
    const peerMax = Math.max(-30, ...(observed.length ? observed : [-30]))
    return {
      ...createMultiSeriesTimeChartBaseOption(theme, { unit: 'RSSI', pointCount: intervals.length, showLegend: true }),
      toolbox: { show: false },
      legend: { top: 4, type: 'scroll', data: peers },
      grid: { left: 65, right: 36, top: 28, bottom: 64, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
      xAxis: { type: 'time', min: begin, max: finish, axisPointer: { show: true, snap: false } },
      yAxis: { type: 'value', name: 'RSSI', min: peerMin, max: peerMax },
      dataZoom: dataZoom(),
      tooltip: {
        trigger: 'item', confine: true, appendToBody: false,
        formatter: (params: { data?: [number, number, number, number] }) => {
          const row = intervals[Number(params.data?.[3])]
          if (!row) return 'Peer AP：无数据'
          const duration = Math.max(0, Date.parse(row.end) - Date.parse(row.start)) / 1000
          return [
            `Peer AP：${escape(row.peer_name || row.bssid || 'UNKNOWN')}`,
            `MAC：${escape(row.bssid || row.peer_mac || 'UNKNOWN')}`,
            `接入站点：${escape(row.station || '无记录')}`,
            `接入区间：${escape(row.section || '无记录')}`,
            `切入时间：${escape(new Date(row.start).toLocaleString())}`,
            `切出时间：${escape(new Date(row.end).toLocaleString())}`,
            `持续时间：${escape(`${duration.toFixed(1)} 秒`)}`,
            `切入 RSSI：${escape(row.entry_rssi ?? row.raw_rssi ?? '无记录')}`,
            `切出 RSSI：${escape(row.exit_rssi ?? '无记录')}`,
            `数据来源：${escape(sourceLabel(row.source))}`,
          ].join('<br>')
        },
      },
      series: [{
        id: 'peer-rssi-intervals', name: 'Peer AP 主用区间', type: 'custom', data: peerData,
        encode: { x: [0, 1], y: 2 },
        markLine: selectedTime ? { silent: true, symbol: 'none', data: [{ xAxis: Date.parse(selectedTime), label: { show: false } }] } : { data: [] },
        renderItem: (_params: unknown, api: { value: (index: number) => number; coord: (values: number[]) => number[]; style: (value?: object) => object }) => {
          const startPoint = api.coord([api.value(0), peerMin])
          const endPoint = api.coord([api.value(1), Number.isFinite(api.value(2)) ? api.value(2) : peerMin])
          const hasRssi = Number.isFinite(intervals[api.value(3)]?.rssi)
          return {
            type: 'rect',
            shape: {
              x: startPoint[0], y: hasRssi ? endPoint[1] : startPoint[1]! - 3,
              width: Math.max(1, endPoint[0]! - startPoint[0]!),
              height: hasRssi ? Math.max(2, startPoint[1]! - endPoint[1]!) : 6,
            },
            style: api.style({ fill: peerIntervalColor(intervals[api.value(3)]!, intervalColors), opacity: hasRssi ? 1 : 0.35 }),
          }
        },
      }],
    }
  }
  const series: Array<Record<string, unknown>> = []
  const pingPoints: PingChartPoint[] = []
  for (const ip of ips) {
    const rows = points.filter((point) => point.target_ip === ip).sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
    const rtt: Array<[number, number | null]> = [], success: Array<[number, number | null]> = [], failure: Array<[number, number | null]> = [], unknown: Array<[number, string]> = []
    for (let index = 0; index < rows.length; index++) {
      const row = rows[index]!, time = Date.parse(row.ts), previous = rows[index - 1]
      const values = pingPointValues(row as unknown as Record<string, unknown>)
      pingPoints.push({ target: ip, time, ...values })
      // Preserve gaps instead of drawing through absent telemetry. The fleet period is 1s.
      if (previous && time - Date.parse(previous.ts) > 3000) {
        rtt.push([Date.parse(previous.ts) + 1, null]); success.push([Date.parse(previous.ts) + 1, null]); failure.push([Date.parse(previous.ts) + 1, null])
      }
      rtt.push([time, values.rtt])
      success.push([time, values.status === 'SUCCESS' ? 0 : null])
      failure.push([time, values.status === 'TIMEOUT' || values.status === 'PACKET_LOSS' ? values.loss : null])
      if (values.status === 'UNKNOWN') unknown.push([time, 'UNKNOWN'])
    }
    const suffix = ips.length > 1 ? ` · ${ip}` : ''
    series.push({ id: `rtt:${ip}`, name: `RTT（ms）${suffix}`, type: 'line', data: rtt, connectNulls: false, showSymbol: false, lineStyle: { color: PING_CHART_COLORS.rtt }, itemStyle: { color: PING_CHART_COLORS.rtt },
      markLine: selectedTime ? { silent: true, symbol: 'none', data: [{ xAxis: Date.parse(selectedTime), label: { formatter: 'Mesh' } }] } : { data: [] } })
    series.push({ id: `success:${ip}`, name: `连通${suffix}`, type: 'line', yAxisIndex: 1, data: success, connectNulls: false, showSymbol: true, symbolSize: 6, lineStyle: { color: PING_CHART_COLORS.success, width: 2 }, itemStyle: { color: PING_CHART_COLORS.success } })
    series.push({ id: `loss:${ip}`, name: `丢包/超时${suffix}`, type: 'line', yAxisIndex: 1, data: failure, connectNulls: false, showSymbol: true, symbolSize: 7, lineStyle: { color: PING_CHART_COLORS.failure, width: 2 }, itemStyle: { color: PING_CHART_COLORS.failure } })
    series.push({ id: `unknown:${ip}`, name: `未知${suffix}`, type: 'scatter', yAxisIndex: mode === 'all' ? 4 : 2, symbol: 'diamond', symbolSize: 8, data: unknown, itemStyle: { color: PING_CHART_COLORS.unknown } })
  }
  if (mode === 'ping') {
    return {
      ...createMultiSeriesTimeChartBaseOption(theme, { unit: 'ms', pointCount: points.length, showLegend: true }),
      color: [PING_CHART_COLORS.rtt, PING_CHART_COLORS.success, PING_CHART_COLORS.failure, PING_CHART_COLORS.unknown],
      toolbox: { show: false },
      legend: { top: 4, type: 'scroll' },
      grid: { left: 65, right: 50, top: 48, bottom: 64, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: { type: 'time', min: begin, max: finish, axisPointer: { show: true, snap: false } },
      yAxis: [{ type: 'value', name: 'RTT (ms)', min: 0 }, { type: 'value', name: `${t('ground.monitor.loss', '丢包')} (%)`, min: 0, max: 100, splitLine: { show: false } }, { type: 'category', data: ['UNKNOWN'], show: false }],
      dataZoom: dataZoom(),
      tooltip: { trigger: 'axis', confine: true, appendToBody: false, formatter: (params: unknown) => pingTooltipFormatter(pingPoints, params) },
      series,
    }
  }
  series.push({ id: 'peer-intervals', name: 'Peer AP', type: 'custom', xAxisIndex: 1, yAxisIndex: 2,
    data: intervals.map((row, index) => [peers.indexOf(row.peer_name || row.bssid || 'UNKNOWN'), Math.max(begin, Date.parse(row.start)), Math.min(finish, Date.parse(row.end)), index]),
    encode: { x: [1, 2], y: 0 },
    renderItem: (_params: unknown, api: { value: (index: number) => number; coord: (values: number[]) => number[]; size: (values: number[]) => number[]; style: (value?: object) => object }) => {
      const a = api.coord([api.value(1), api.value(0)]), b = api.coord([api.value(2), api.value(0)])
      const height = Math.min(24, api.size([0, 1])[1]! * 0.7)
      return { type: 'rect', shape: { x: a[0], y: a[1]! - height / 2, width: Math.max(0, b[0]! - a[0]!), height }, style: api.style({ fill: peerIntervalColor(intervals[api.value(3)]!, intervalColors) }) }
    }, tooltip: { show: false } })
  series.push({ id: 'mesh-events', name: 'Mesh / Syslog', type: 'custom', xAxisIndex: 2, yAxisIndex: 3,
    data: meshEvents.map((row) => [Date.parse(row.event_time || row.receive_time), 0, row.event_type]),
    encode: { x: 0, y: 1 },
    renderItem: (_params: unknown, api: { value: (index: number) => number; coord: (values: number[]) => number[]; style: () => object }) => {
      const point = api.coord([api.value(0), api.value(1)])
      return { type: 'circle', shape: { cx: point[0], cy: point[1], r: 5 }, style: api.style() }
    },
    tooltip: { formatter: (params: { data?: [number, number, string] }) => {
      const event = meshEvents.find((row) => Date.parse(row.event_time || row.receive_time) === params.data?.[0])
      return event ? `${escape(event.event_time || event.receive_time)}<br>${escape(event.event_type)}<br>${escape(event.new_ap_name || event.bssid || 'UNKNOWN')}` : 'Mesh / Syslog'
    } },
  })
  return {
    ...createMultiSeriesTimeChartBaseOption(theme, { unit: 'ms', pointCount: points.length, showLegend: true }),
    toolbox: { show: false },
    legend: { top: 4, type: 'scroll' },
    grid: [{ left: 65, right: 50, top: 48, height: '38%', outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' }, { left: 95, right: 50, top: '56%', height: '18%', outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' }, { left: 95, right: 50, top: '79%', bottom: 72, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' }],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [0, 1, 2].map((gridIndex) => ({ type: 'time', gridIndex, min: begin, max: finish, axisPointer: { show: true, snap: false } })),
    yAxis: [{ type: 'value', name: 'RTT (ms)', min: 0 }, { type: 'value', name: `${t('ground.monitor.loss', '丢包')} (%)`, min: 0, max: 100, splitLine: { show: false } }, { type: 'category', gridIndex: 1, data: peers.length ? peers : ['UNKNOWN'], axisLabel: { width: 85, overflow: 'truncate' } }, { type: 'category', gridIndex: 2, data: ['Mesh / Syslog'], axisLabel: { width: 85, overflow: 'truncate' } }, { type: 'category', data: ['UNKNOWN'], show: false }],
    dataZoom: dataZoom([0, 1, 2]),
    tooltip: { trigger: 'axis', confine: true, appendToBody: false, extraCssText: 'max-width:420px;max-height:260px;overflow:hidden',
      formatter: (params: Array<{ axisValue?: number; data?: [number, number | null]; seriesName: string; seriesIndex: number }>) => {
        const time = Number(params[0]?.axisValue)
        const evidence = intervals.find((row) => Date.parse(row.start) <= time && time < Date.parse(row.end))
        const values = params.filter((row) => row.data && row.data[0] === time && row.data[1] !== null).map((row) => `${escape(row.seriesName)}: ${escape(row.data![1])}${row.seriesName.includes('RTT') ? ' ms' : '%'}`)
        return [Number.isFinite(time) ? escape(new Date(time).toLocaleString()) : '', ...values,
          evidence ? `Peer AP：${escape(evidence.peer_name || evidence.bssid || '无记录')}<br>MAC：${escape(evidence.bssid || evidence.peer_mac || '无记录')}<br>切入 RSSI：${escape(evidence.entry_rssi ?? evidence.raw_rssi ?? '无记录')}<br>切出 RSSI：${escape(evidence.exit_rssi ?? '无记录')}<br>接入站点：${escape(evidence.station || '无记录')}<br>接入区间：${escape(evidence.section || '无记录')}<br>数据来源：${escape(sourceLabel(evidence.source))}` : 'Peer AP：无记录'].join('<br>')
      } },
    series,
  }
}
