export type PingChartStatus = 'SUCCESS' | 'TIMEOUT' | 'PACKET_LOSS' | 'UNKNOWN'

export const PING_CHART_COLORS = {
  rtt: '#3B82F6',
  success: '#22C55E',
  failure: '#EF4444',
  unknown: '#909399',
} as const

export interface PingChartPoint {
  target: string
  time: number
  rtt: number | null
  loss: number | null
  status: PingChartStatus
}

export interface HeartbeatStatusStatistics {
  success: number
  failure: number
  unknown: number
  valid: number
  connectivityRate: number | null
}

const STATUS_ALIASES: Record<string, PingChartStatus> = {
  SUCCESS: 'SUCCESS',
  OK: 'SUCCESS',
  CONNECTED: 'SUCCESS',
  TIMEOUT: 'TIMEOUT',
  TIMED_OUT: 'TIMEOUT',
  PACKET_LOSS: 'PACKET_LOSS',
  LOSS: 'PACKET_LOSS',
  LOST: 'PACKET_LOSS',
  UNKNOWN: 'UNKNOWN',
}

function normalizedStatus(value: unknown): PingChartStatus | undefined {
  const key = String(value ?? '').trim().toUpperCase().replace(/[ -]+/g, '_')
  return STATUS_ALIASES[key]
}

function numeric(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** Keep raw success/failure semantics separate from the plotted percentage. */
export function classifyPingStatus(sample: Record<string, unknown>): PingChartStatus {
  const explicit = normalizedStatus(sample.status ?? sample.state ?? sample.result ?? sample.outcome)
  if (explicit) return explicit
  if (typeof sample.ok !== 'boolean') return 'UNKNOWN'
  if (sample.timeout === true || sample.timed_out === true) return 'TIMEOUT'
  if (!sample.ok) {
    const reason = String(sample.error_code ?? sample.failure_code ?? sample.reason ?? sample.error ?? '').toUpperCase()
    return reason.includes('TIMEOUT') || reason.includes('TIMED_OUT') ? 'TIMEOUT' : 'PACKET_LOSS'
  }
  const loss = numeric(sample.loss_percent ?? sample.loss_rate_percent ?? sample.packet_loss_percent)
  if (loss !== null && loss > 0) return 'PACKET_LOSS'
  if (numeric(sample.rtt_ms) === null) return 'UNKNOWN'
  return 'SUCCESS'
}

export function pingStatusLabel(status: PingChartStatus): string {
  return ({ SUCCESS: '正常连通', TIMEOUT: '超时', PACKET_LOSS: '丢包/不通', UNKNOWN: '未知' } as const)[status]
}

export function pingStatusColor(status: PingChartStatus): string {
  return status === 'SUCCESS' ? PING_CHART_COLORS.success
    : status === 'TIMEOUT' || status === 'PACKET_LOSS' ? PING_CHART_COLORS.failure
      : PING_CHART_COLORS.unknown
}

export function pingPointValues(sample: Record<string, unknown>): { status: PingChartStatus; rtt: number | null; loss: number | null } {
  const status = classifyPingStatus(sample)
  const rtt = status === 'TIMEOUT' || status === 'UNKNOWN' ? null : numeric(sample.rtt_ms)
  const rawLoss = numeric(sample.loss_percent ?? sample.loss_rate_percent ?? sample.packet_loss_percent)
  const loss = rawLoss === null ? (status === 'SUCCESS' ? 0 : status === 'TIMEOUT' || status === 'PACKET_LOSS' ? 100 : null) : Math.max(0, Math.min(100, rawLoss))
  return { status, rtt, loss }
}

/** Heartbeat reachability is based on the persisted probe result, not RTT. */
export function heartbeatPointValues(sample: Record<string, unknown>): { status: PingChartStatus; rtt: number | null; loss: number | null } {
  const explicit = normalizedStatus(sample.status ?? sample.state ?? sample.result ?? sample.outcome)
  const status = explicit || (typeof sample.ok === 'boolean'
    ? (sample.ok ? 'SUCCESS' : (sample.timeout === true || sample.timed_out === true ? 'TIMEOUT' : 'PACKET_LOSS'))
      : 'UNKNOWN')
  const rtt = numeric(sample.rtt_ms)
  return { status, rtt, loss: status === 'SUCCESS' ? 0 : status === 'TIMEOUT' || status === 'PACKET_LOSS' ? 100 : null }
}

export function heartbeatStatusStatistics(samples: Array<Record<string, unknown>>): HeartbeatStatusStatistics {
  let success = 0, failure = 0, unknown = 0
  samples.filter((sample) => !sample.warmup_ignored).forEach((sample) => {
    const status = heartbeatPointValues(sample).status
    if (status === 'SUCCESS') success++
    else if (status === 'TIMEOUT' || status === 'PACKET_LOSS') failure++
    else unknown++
  })
  const valid = success + failure
  return { success, failure, unknown, valid, connectivityRate: valid ? success / valid * 100 : null }
}

function escape(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
}

function targetFromSeries(seriesName: string, targets: string[]): string {
  const suffix = seriesName.split(' · ').at(-1) || ''
  return targets.includes(suffix) ? suffix : targets[0] || ''
}

export function pingTooltipFormatter(points: PingChartPoint[], params: unknown): string {
  const rows = Array.isArray(params) ? params as Array<{ axisValue?: number | string; seriesName?: string }> : []
  const time = Number(rows[0]?.axisValue)
  const targets = [...new Set(points.map((point) => point.target))]
  const atTime = targets.map((target) => points.find((point) => point.target === target && point.time === time)).filter((point): point is PingChartPoint => Boolean(point))
  const body = atTime.map((point) => [
    targets.length > 1 ? `目标：${escape(point.target)}` : '',
    `RTT：${point.rtt === null ? (point.status === 'SUCCESS' || point.status === 'UNKNOWN' ? '无数据' : '超时') : `${escape(point.rtt)} ms`}`,
    `状态：${pingStatusLabel(point.status)}`,
    `丢包：${point.loss === null ? '无数据' : `${escape(point.loss)}%`}`,
  ].filter(Boolean).join('<br>'))
  if (!body.length && rows[0]?.seriesName) {
    const target = targetFromSeries(rows[0].seriesName, targets)
    const point = points.find((item) => item.target === target && item.time === time)
    if (point) body.push(`目标：${escape(point.target)}<br>RTT：${point.rtt === null ? (point.status === 'SUCCESS' || point.status === 'UNKNOWN' ? '无数据' : '超时') : `${escape(point.rtt)} ms`}<br>状态：${pingStatusLabel(point.status)}<br>丢包：${point.loss === null ? '无数据' : `${escape(point.loss)}%`}`)
  }
  return [Number.isFinite(time) ? escape(new Date(time).toLocaleString()) : '', ...body].filter(Boolean).join('<br>')
}
