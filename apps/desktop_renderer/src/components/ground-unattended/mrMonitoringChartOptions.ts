import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { t } from '../../i18n/runtime'
import type { NetConsoleChartTokens } from '../../theme/echarts'
import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'

const escape = (value: unknown): string => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
export const PEER_RAINBOW_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6'] as const
type PeerIntervalLike = GroundMrMonitoring['peer_intervals'][number]

function peerIntervalIdentity(row: PeerIntervalLike): string {
  return [row.bssid, row.peer_mac, row.peer_name, row.source].map((value) => String(value || '').trim().toLowerCase()).join('|')
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
  mode: 'all' | 'ping' | 'peer' | 'navigator' = 'all',
  viewportStart = start,
  viewportEnd = end,
): Record<string, unknown> {
  const begin = Date.parse(start), finish = Date.parse(end)
  const visibleBegin = Date.parse(viewportStart), visibleFinish = Date.parse(viewportEnd)
  const dataZoom = (xAxisIndex: number | number[] = 0, slider = false): Array<Record<string, unknown>> => [
    { type: 'inside', xAxisIndex, filterMode: 'none', startValue: visibleBegin, endValue: visibleFinish, minValueSpan: 1000 },
    ...(slider ? [{ type: 'slider', xAxisIndex, bottom: 8, filterMode: 'none', startValue: visibleBegin, endValue: visibleFinish, minValueSpan: 1000 }] : []),
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
      yAxis: { type: 'value', name: 'RSSI (dBm)', min: peerMin, max: peerMax },
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
            `车站：${escape(row.station || '未知车站')}`,
            `区间：${escape(row.section || '无数据')}`,
            `设备原始 RSSI：${escape(Number.isFinite(row.raw_rssi) ? row.raw_rssi : '无数据')}`,
            `归一化 RSSI：${escape(Number.isFinite(row.rssi) ? `${row.rssi} dBm` : '无数据')}`,
            `语义：${escape(row.rssi_semantics || 'UNKNOWN')}`,
            `切入：${escape(new Date(row.start).toLocaleString())}`,
            `切出：${escape(new Date(row.end).toLocaleString())}`,
            `持续：${escape(`${duration.toFixed(1)} 秒`)}`,
            `数据来源：${escape(row.source || 'UNKNOWN')}`,
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
  for (const ip of ips) {
    const rows = points.filter((point) => point.target_ip === ip).sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
    const rtt: Array<[number, number | null]> = [], loss: Array<[number, number | null]> = []
    for (let index = 0; index < rows.length; index++) {
      const row = rows[index]!, time = Date.parse(row.ts), previous = rows[index - 1]
      // Preserve gaps instead of drawing through absent telemetry. The fleet period is 1s.
      if (previous && time - Date.parse(previous.ts) > 3000) {
        rtt.push([Date.parse(previous.ts) + 1, null]); loss.push([Date.parse(previous.ts) + 1, null])
      }
      rtt.push([time, row.ok && Number.isFinite(row.rtt_ms) ? row.rtt_ms : null])
      loss.push([time, row.ok ? 0 : 100])
    }
    series.push({ id: `rtt:${ip}`, name: `${ip} RTT`, type: 'line', data: rtt, connectNulls: false, showSymbol: false,
      markLine: selectedTime ? { silent: true, symbol: 'none', data: [{ xAxis: Date.parse(selectedTime), label: { formatter: 'Mesh' } }] } : { data: [] } })
    series.push({ id: `loss:${ip}`, name: `${ip} ${t('ground.monitor.packet_loss', '单包丢包')}`, type: 'line', yAxisIndex: 1, data: loss, connectNulls: false, showSymbol: false, lineStyle: { opacity: 0.5 }, step: 'end' })
  }
  if (mode === 'ping') {
    return {
      ...createMultiSeriesTimeChartBaseOption(theme, { unit: 'ms', pointCount: points.length, showLegend: true }),
      toolbox: { show: false },
      legend: { top: 4, type: 'scroll' },
      grid: { left: 65, right: 50, top: 48, bottom: 64, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: { type: 'time', min: begin, max: finish, axisPointer: { show: true, snap: false } },
      yAxis: [{ type: 'value', name: 'RTT (ms)', min: 0 }, { type: 'value', name: `${t('ground.monitor.loss', '丢包')} (%)`, min: 0, max: 100, splitLine: { show: false } }],
      dataZoom: dataZoom(),
      tooltip: { trigger: 'axis', confine: true, appendToBody: false },
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
    yAxis: [{ type: 'value', name: 'RTT (ms)', min: 0 }, { type: 'value', name: `${t('ground.monitor.loss', '丢包')} (%)`, min: 0, max: 100, splitLine: { show: false } }, { type: 'category', gridIndex: 1, data: peers.length ? peers : ['UNKNOWN'], axisLabel: { width: 85, overflow: 'truncate' } }, { type: 'category', gridIndex: 2, data: ['Mesh / Syslog'], axisLabel: { width: 85, overflow: 'truncate' } }],
    dataZoom: dataZoom([0, 1, 2]),
    tooltip: { trigger: 'axis', confine: true, appendToBody: false, extraCssText: 'max-width:420px;max-height:260px;overflow:hidden',
      formatter: (params: Array<{ axisValue?: number; data?: [number, number | null]; seriesName: string; seriesIndex: number }>) => {
        const time = Number(params[0]?.axisValue)
        const evidence = intervals.find((row) => Date.parse(row.start) <= time && time < Date.parse(row.end))
        const values = params.filter((row) => row.data && row.data[0] === time && row.data[1] !== null).map((row) => `${escape(row.seriesName)}: ${escape(row.data![1])}${row.seriesName.includes('RTT') ? ' ms' : '%'}`)
        return [Number.isFinite(time) ? escape(new Date(time).toLocaleString()) : '', ...values,
          evidence ? `Peer: ${escape(evidence.peer_name || evidence.bssid)}<br>BSSID: ${escape(evidence.bssid || evidence.peer_mac || 'UNKNOWN')} / RSSI: ${escape(evidence.rssi ?? 'UNKNOWN')}<br>车站: ${escape(evidence.station || '未知车站')}<br>区间: ${escape(evidence.section || '无数据')}<br>${escape(evidence.source)}<br>device: ${escape(evidence.device_time || 'UNKNOWN')}<br>receive: ${escape(evidence.receive_time || 'UNKNOWN')}` : 'Peer: UNKNOWN'].join('<br>')
      } },
    series,
  }
}
