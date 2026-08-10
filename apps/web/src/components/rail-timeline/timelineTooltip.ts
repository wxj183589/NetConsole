import type { OnlineMrMetricPoint } from '../../types/onlineMr'
import { formatDbmValue, formatRssiValue } from './rssiPresentation'
import { formatTimelineMetricValue, timelineMetricDefinition } from './timelineMetricPresentation'

export type TimelineTooltipKind =
  | 'generic'
  | 'ping-loss'
  | 'ping-rtt'
  | 'interface'
  | 'traffic'
  | 'traffic-loss'
  | 'traffic-jitter'
  | 'traffic-retransmits'
  | 'channel-busy'
  | 'switch-rssi'

export interface TimelineTooltipRow {
  seriesName?: string
  value?: [string | number, number | null]
  data?: {
    point?: OnlineMrMetricPoint
    metricType?: string
  }
}

const EMPTY = '无数据'

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function number(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function trimNumber(value: number, digits = 2): string {
  return (Number.isInteger(value) ? String(value) : value.toFixed(digits))
    .replace(/\.0+$/, '')
    .replace(/(\.\d*?)0+$/, '$1')
}

export function formatTimelineTime(value: string | number | null | undefined, withMilliseconds = true): string {
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value)
  const parsed = new Date(typeof value === 'number' ? value : text.replace(' ', 'T'))
  if (!Number.isFinite(parsed.getTime())) return text
  const pad = (item: number, size = 2): string => String(item).padStart(size, '0')
  const base = `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`
  return withMilliseconds && (parsed.getMilliseconds() > 0 || /\.\d+/.test(text)) ? `${base}.${pad(parsed.getMilliseconds(), 3)}` : base
}

export function formatRate(value: number | null | undefined, unit = 'Mbps'): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY
  const normalized = unit.toLowerCase()
  if (normalized === 'pps') return value >= 1_000 ? `${trimNumber(value / 1_000)} Kpps` : `${trimNumber(value)} pps`
  if (normalized === 'bps') {
    const units = ['bps', 'Kbps', 'Mbps', 'Gbps']
    let current = value
    let index = 0
    while (current >= 1_000 && index < units.length - 1) { current /= 1_000; index += 1 }
    return `${trimNumber(current)} ${units[index]}`
  }
  return `${trimNumber(value)} ${unit}`
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let current = value
  let index = 0
  while (Math.abs(current) >= 1024 && index < units.length - 1) { current /= 1024; index += 1 }
  return `${trimNumber(current, index === 0 ? 0 : 2)} ${units[index]}`
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? EMPTY : `${trimNumber(value)}%`
}

export const formatRssi = formatRssiValue

export function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY
  if (value < 60) return `${trimNumber(value)} s`
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes} min ${seconds} s`
}

function field(label: string, value: unknown): string {
  return value === null || value === undefined || value === ''
    ? ''
    : `<div><span class="timeline-tooltip__label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`
}

function pointOf(row: TimelineTooltipRow | undefined): OnlineMrMetricPoint | null {
  return row?.data?.point || null
}

function valueOf(row: TimelineTooltipRow | undefined): number | null {
  return number(row?.value?.[1] ?? pointOf(row)?.value)
}

function timeOf(rows: TimelineTooltipRow[]): string | number | null {
  return rows[0]?.value?.[0] ?? pointOf(rows[0])?.timestamp ?? null
}

function correction(point: OnlineMrMetricPoint | null): string {
  if (!point || !point.raw_timestamp || point.raw_timestamp === point.timestamp) return ''
  return field('原始采集时间', formatTimelineTime(point.raw_timestamp, false)) + field(
    '时间校正',
    point.correction_confidence === 'low' ? '未可靠校正' : `已校正（${point.correction_confidence === 'high' ? '高' : '中'}置信度）`,
  )
}

function shell(time: string | number | null, body: string, point: OnlineMrMetricPoint | null = null): string {
  return `<div class="timeline-tooltip"><div class="timeline-tooltip__time">时间：${escapeHtml(formatTimelineTime(time))}</div>${body}${correction(point)}</div>`
}

function pingLoss(rows: TimelineTooltipRow[]): string {
  const grouped = new Map<string, TimelineTooltipRow[]>()
  for (const row of rows) {
    const point = pointOf(row)
    const key = String(point?.dimensions.target_ip || point?.dimensions.target_name || row.seriesName || '目标')
    grouped.set(key, [...(grouped.get(key) || []), row])
  }
  const body = [...grouped.entries()].map(([target, values]) => {
    const point = pointOf(values[0])
    const dimensions = point?.dimensions || {}
    const loss = valueOf(values.find((row) => valueOf(row) !== null))
    const sent = number(dimensions.sent)
    const received = number(dimensions.received)
    const lost = number(dimensions.lost) ?? (sent !== null && received !== null ? sent - received : null)
    return `<section>${field('目标', target)}${field('丢包率', formatTimelineMetricValue('ping_loss', loss))}${field('发送', sent)}${field('接收', received)}${field('丢失', lost)}</section>`
  }).join('')
  return shell(timeOf(rows), body, pointOf(rows[0]))
}

function pingRtt(rows: TimelineTooltipRow[]): string {
  const body = rows.map((row) => {
    const point = pointOf(row)
    const dimensions = point?.dimensions || {}
    return `<section>${field('目标', dimensions.target_ip || dimensions.target_name || row.seriesName || '目标')}${field('RTT', formatTimelineMetricValue('ping_rtt', valueOf(row)))}</section>`
  }).join('')
  return shell(timeOf(rows), body, pointOf(rows[0]))
}

function interfaceRate(rows: TimelineTooltipRow[]): string {
  const grouped = new Map<string, { inbound?: TimelineTooltipRow; outbound?: TimelineTooltipRow }>()
  for (const row of rows) {
    const point = pointOf(row)
    const dimensions = point?.dimensions || {}
    const key = String(dimensions.interface_normalized || dimensions.interface_name || row.seriesName || '接口')
    const value = grouped.get(key) || {}
    if (row.data?.metricType === 'interface_in_pps') value.inbound = row
    else value.outbound = row
    grouped.set(key, value)
  }
  const body = [...grouped.entries()].map(([name, value]) => `<section>${field('接口', name)}${value.inbound ? field('接收包速率', formatRate(valueOf(value.inbound), 'pps')) : ''}${value.outbound ? field('发送包速率', formatRate(valueOf(value.outbound), 'pps')) : ''}</section>`).join('')
  return shell(timeOf(rows), body, pointOf(rows[0]))
}

function traffic(rows: TimelineTooltipRow[], kind: TimelineTooltipKind): string {
  const body = rows.map((row) => {
    const point = pointOf(row)
    const dimensions = point?.dimensions || {}
    const direction = dimensions.direction === 'upload' ? 'MR → Server' : dimensions.direction === 'download' ? 'Server → MR' : dimensions.direction || row.seriesName || '未注明'
    const value = valueOf(row)
    const metric = kind === 'traffic-loss' ? field('流量丢失率', formatPercent(value))
      : kind === 'traffic-jitter' ? field('Jitter', value === null ? EMPTY : `${trimNumber(value)} ms`)
        : kind === 'traffic-retransmits' ? field('TCP 重传', value)
          : field('吞吐', formatRate(value, 'Mbps'))
    return `<section>${field('测试方向', direction)}${metric}${kind === 'traffic' ? field('发送数据', formatBytes(number(dimensions.transfer_bytes))) : ''}${kind === 'traffic' ? field('丢失率', formatPercent(number(dimensions.loss_percent))) : ''}</section>`
  }).join('')
  return shell(timeOf(rows), body, pointOf(rows[0]))
}

function channelBusy(rows: TimelineTooltipRow[]): string {
  const body = rows.map((row) => {
    const point = pointOf(row)
    const dimensions = point?.dimensions || {}
    const radio = dimensions.radio == null ? null : `Radio ${dimensions.radio}`
    return `<section>${field('Radio', radio)}${field('信道', dimensions.ctl_channel)}${field('频宽', dimensions.bandwidth_mhz || dimensions.bandwidth ? `${dimensions.bandwidth_mhz || dimensions.bandwidth} MHz` : null)}${field('信道繁忙度', row.data?.metricType === 'ctl_busy' ? formatPercent(valueOf(row)) : null)}${field('发送占用', row.data?.metricType === 'tx_busy' ? formatPercent(valueOf(row)) : null)}${field('接收占用', row.data?.metricType === 'rx_busy' ? formatPercent(valueOf(row)) : null)}</section>`
  }).join('')
  return shell(timeOf(rows), body, pointOf(rows[0]))
}

function switchRssi(rows: TimelineTooltipRow[]): string {
  const event = pointOf(rows[0])?.dimensions.switch_event as Record<string, unknown> | undefined
  if (!event) return shell(timeOf(rows), rows.map((row) => field(row.seriesName || 'RSSI', formatRssi(valueOf(row)))).join(''), pointOf(rows[0]))
  const reason = String(event.reason || '')
  return shell(timeOf(rows), `<section>${field('切出 AP', event.old_peer_name)}${field('切出 RSSI', formatDbmValue(number(event.old_rssi_dbm)))}${field('切入 AP', event.new_peer_name)}${field('切入 RSSI', formatDbmValue(number(event.new_rssi_dbm)))}${field('切出站点', event.old_station)}${field('切入站点', event.new_station)}${field('Radio', event.radio == null ? null : `Radio ${event.radio}`)}${field('原因', reason)}</section>`, pointOf(rows[0]))
}

export function buildTimelineTooltip(kind: TimelineTooltipKind, rows: TimelineTooltipRow[], detailed = false): string {
  if (!rows.length) return shell(null, '')
  if (!detailed) {
    const values = rows.slice(0, 3).map((row) => {
      const value = valueOf(row)
      const definition = timelineMetricDefinition(row.data?.metricType)
      const fallbackUnit = kind.includes('loss') || kind === 'channel-busy' ? '%'
        : kind.includes('jitter') || kind === 'ping-rtt' ? ' ms'
          : kind === 'traffic' ? ' Mbps'
            : kind === 'interface' ? ' pps'
              : ''
      return field(row.seriesName || definition?.displayLabel || '指标', definition ? formatTimelineMetricValue(definition.metricId, value) : value === null ? EMPTY : `${trimNumber(value)}${fallbackUnit}`)
    }).join('')
    return `<div class="timeline-tooltip timeline-tooltip--quick"><div class="timeline-tooltip__time">${escapeHtml(formatTimelineTime(timeOf(rows)).split(' ').at(-1) || EMPTY)}</div>${values}</div>`
  }
  if (kind === 'ping-loss') return pingLoss(rows)
  if (kind === 'ping-rtt') return pingRtt(rows)
  if (kind === 'interface') return interfaceRate(rows)
  if (kind === 'traffic' || kind.startsWith('traffic-')) return traffic(rows, kind)
  if (kind === 'channel-busy') return channelBusy(rows)
  if (kind === 'switch-rssi') return switchRssi(rows)
  return shell(timeOf(rows), rows.map((row) => field(row.seriesName || '指标', valueOf(row) === null ? EMPTY : valueOf(row))).join(''), pointOf(rows[0]))
}

export function timelineTooltipPosition(
  point: [number, number],
  _params: unknown,
  _dom: unknown,
  _rect: unknown,
  size: { contentSize: [number, number]; viewSize: [number, number] },
): [number, number] {
  const margin = 12
  const [contentWidth, contentHeight] = size.contentSize
  const [viewWidth, viewHeight] = size.viewSize
  const x = point[0] + contentWidth + margin > viewWidth ? point[0] - contentWidth - margin : point[0] + margin
  const y = point[1] + contentHeight + margin > viewHeight ? point[1] - contentHeight - margin : point[1] + margin
  return [Math.max(margin, x), Math.max(margin, y)]
}
