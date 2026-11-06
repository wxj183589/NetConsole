import type { GroundMrMonitoring } from '../../types/groundUnattended'
import { t } from '../../i18n/runtime'
import type { NetConsoleChartTokens } from '../../theme/echarts'
import { createMultiSeriesTimeChartBaseOption } from '../charts/multiSeriesTimeChart'

const escape = (value: unknown): string => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)

export function mrMonitoringChartOption(data: GroundMrMonitoring, start: string, end: string, theme: NetConsoleChartTokens, selectedTime = ''): Record<string, unknown> {
  const begin = Date.parse(start), finish = Date.parse(end)
  const points = data.series.points.filter((point) => !point.warmup_ignored && Date.parse(point.ts) >= begin && Date.parse(point.ts) <= finish)
  const ips = [...new Set(points.map((point) => point.target_ip))]
  const intervals = data.peer_intervals.filter((row) => Date.parse(row.end) >= begin && Date.parse(row.start) <= finish)
  const peers = [...new Set(intervals.map((row) => row.peer_name || row.bssid || 'UNKNOWN'))]
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
  series.push({ id: 'peer-intervals', name: 'Peer AP', type: 'custom', xAxisIndex: 1, yAxisIndex: 2,
    data: intervals.map((row) => [peers.indexOf(row.peer_name || row.bssid || 'UNKNOWN'), Math.max(begin, Date.parse(row.start)), Math.min(finish, Date.parse(row.end))]),
    encode: { x: [1, 2], y: 0 },
    renderItem: (_params: unknown, api: { value: (index: number) => number; coord: (values: number[]) => number[]; size: (values: number[]) => number[]; style: () => object }) => {
      const a = api.coord([api.value(1), api.value(0)]), b = api.coord([api.value(2), api.value(0)])
      const height = Math.min(24, api.size([0, 1])[1]! * 0.7)
      return { type: 'rect', shape: { x: a[0], y: a[1]! - height / 2, width: Math.max(0, b[0]! - a[0]!), height }, style: api.style() }
    }, tooltip: { show: false } })
  return {
    ...createMultiSeriesTimeChartBaseOption(theme, { unit: 'ms', pointCount: points.length, showLegend: true }),
    toolbox: { show: false },
    legend: { top: 4, type: 'scroll' },
    grid: [{ left: 65, right: 50, top: 48, height: '46%', outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' }, { left: 95, right: 50, top: '66%', bottom: 72, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' }],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [0, 1].map((gridIndex) => ({ type: 'time', gridIndex, min: begin, max: finish, axisPointer: { show: true, snap: false } })),
    yAxis: [{ type: 'value', name: 'RTT (ms)', min: 0 }, { type: 'value', name: `${t('ground.monitor.loss', '丢包')} (%)`, min: 0, max: 100, splitLine: { show: false } }, { type: 'category', gridIndex: 1, data: peers.length ? peers : ['UNKNOWN'], axisLabel: { width: 85, overflow: 'truncate' } }],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], filterMode: 'weakFilter' }, { type: 'slider', xAxisIndex: [0, 1], bottom: 8, filterMode: 'weakFilter' }],
    tooltip: { trigger: 'axis', confine: true, appendToBody: false, extraCssText: 'max-width:420px;max-height:260px;overflow:hidden',
      formatter: (params: Array<{ axisValue?: number; data?: [number, number | null]; seriesName: string; seriesIndex: number }>) => {
        const time = Number(params[0]?.axisValue)
        const evidence = intervals.find((row) => Date.parse(row.start) <= time && time < Date.parse(row.end))
        const values = params.filter((row) => row.data && row.data[0] === time && row.data[1] !== null).map((row) => `${escape(row.seriesName)}: ${escape(row.data![1])}${row.seriesName.includes('RTT') ? ' ms' : '%'}`)
        return [Number.isFinite(time) ? escape(new Date(time).toLocaleString()) : '', ...values,
          evidence ? `Peer: ${escape(evidence.peer_name || evidence.bssid)}<br>BSSID: ${escape(evidence.bssid || 'UNKNOWN')} / RSSI: ${escape(evidence.rssi ?? 'UNKNOWN')}<br>${escape(evidence.source)}<br>device: ${escape(evidence.device_time || 'UNKNOWN')}<br>receive: ${escape(evidence.receive_time || 'UNKNOWN')}` : 'Peer: UNKNOWN'].join('<br>')
      } },
    series,
  }
}
