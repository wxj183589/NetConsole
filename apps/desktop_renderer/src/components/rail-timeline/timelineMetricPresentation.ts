import { formatRssiValue } from './rssiPresentation'

export type TimelineMetricId =
  | 'ping_rtt'
  | 'ping_loss'
  | 'ctl_busy'
  | 'tx_busy'
  | 'rx_busy'
  | 'iperf_bitrate'
  | 'iperf_loss'
  | 'iperf_jitter'
  | 'interface_in_pps'
  | 'interface_out_pps'
  | 'interface_bps'
  | 'rssi'
  | 'trackside_rssi'

export interface TimelineMetricDefinition {
  metricId: TimelineMetricId
  label: string
  displayLabel: string
  unit: string
  axisUnit: string
  axisMin?: number
  axisMax?: number
}

const definitions: Record<TimelineMetricId, TimelineMetricDefinition> = {
  ping_rtt: { metricId: 'ping_rtt', label: 'Ping RTT', displayLabel: 'RTT', unit: 'ms', axisUnit: 'ms', axisMin: 0 },
  ping_loss: { metricId: 'ping_loss', label: 'Ping 丢包率', displayLabel: '丢包率', unit: '%', axisUnit: '%', axisMin: 0, axisMax: 100 },
  ctl_busy: { metricId: 'ctl_busy', label: '信道繁忙度', displayLabel: '信道繁忙度', unit: '%', axisUnit: '%', axisMin: 0, axisMax: 100 },
  tx_busy: { metricId: 'tx_busy', label: '发送占用', displayLabel: '发送占用', unit: '%', axisUnit: '%', axisMin: 0, axisMax: 100 },
  rx_busy: { metricId: 'rx_busy', label: '接收占用', displayLabel: '接收占用', unit: '%', axisUnit: '%', axisMin: 0, axisMax: 100 },
  iperf_bitrate: { metricId: 'iperf_bitrate', label: '业务吞吐', displayLabel: '吞吐', unit: 'Mbps', axisUnit: 'Mbps', axisMin: 0 },
  iperf_loss: { metricId: 'iperf_loss', label: '流量丢失率', displayLabel: '流量丢失率', unit: '%', axisUnit: '%', axisMin: 0, axisMax: 100 },
  iperf_jitter: { metricId: 'iperf_jitter', label: 'Jitter', displayLabel: 'Jitter', unit: 'ms', axisUnit: 'ms', axisMin: 0 },
  interface_in_pps: { metricId: 'interface_in_pps', label: '接口接收包速率', displayLabel: '接收包速率', unit: 'pps', axisUnit: 'pps', axisMin: 0 },
  interface_out_pps: { metricId: 'interface_out_pps', label: '接口发送包速率', displayLabel: '发送包速率', unit: 'pps', axisUnit: 'pps', axisMin: 0 },
  interface_bps: { metricId: 'interface_bps', label: '接口比特率', displayLabel: '接口速率', unit: 'bps', axisUnit: 'bps', axisMin: 0 },
  rssi: { metricId: 'rssi', label: '主链路 RSSI', displayLabel: 'RSSI', unit: '', axisUnit: '' },
  trackside_rssi: { metricId: 'trackside_rssi', label: '轨旁 AP RSSI', displayLabel: '轨旁 RSSI', unit: '', axisUnit: '' },
}

function trimNumber(value: number, digits = 2): string {
  return (Number.isInteger(value) ? String(value) : value.toFixed(digits))
    .replace(/\.0+$/, '')
    .replace(/(\.\d*?)0+$/, '$1')
}

function formatRate(value: number, unit: string): string {
  if (unit !== 'bps') return `${trimNumber(value)} ${unit}`
  const units = ['bps', 'Kbps', 'Mbps', 'Gbps']
  let current = value
  let index = 0
  while (current >= 1_000 && index < units.length - 1) { current /= 1_000; index += 1 }
  return `${trimNumber(current)} ${units[index]}`
}

export function timelineMetricDefinition(metricId: string | null | undefined): TimelineMetricDefinition | null {
  return metricId && metricId in definitions ? definitions[metricId as TimelineMetricId] : null
}

/** 由 metricId 而非页面、图种或数值大小决定展示单位。 */
export function formatTimelineMetricValue(metricId: string | null | undefined, value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '无数据'
  const definition = timelineMetricDefinition(metricId)
  if (!definition) return trimNumber(value)
  if (definition.unit === '%') return `${trimNumber(value)}%`
  if (definition.unit === '') return formatRssiValue(value)
  return formatRate(value, definition.unit)
}
