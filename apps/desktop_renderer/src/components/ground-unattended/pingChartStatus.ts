export type PingChartStatus = 'SUCCESS' | 'TIMEOUT' | 'PACKET_LOSS' | 'UNREACHABLE' | 'ERROR' | 'NOT_SCHEDULED' | 'UNKNOWN'

export const PING_CHART_COLORS = {
  rtt: '#3B82F6',
  success: '#22C55E',
  failure: '#EF4444',
  unknown: '#909399',
} as const

export interface PingChartPoint {
  errorReason?: string
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

export function pingStatusLabel(status: PingChartStatus): string {
  return ({
    SUCCESS: '正常连通',
    TIMEOUT: '单包超时',
    PACKET_LOSS: '单包丢失',
    UNREACHABLE: '持续不可达',
    ERROR: '探测错误',
    NOT_SCHEDULED: '本周期未调度',
    UNKNOWN: '未知',
  } as const)[status]
}

export function pingStatusColor(status: PingChartStatus): string {
  return status === 'SUCCESS' ? PING_CHART_COLORS.success
    : isPingFailureStatus(status) ? PING_CHART_COLORS.failure
      : PING_CHART_COLORS.unknown
}

export function isPingFailureStatus(status: PingChartStatus): boolean {
  return status === 'TIMEOUT' || status === 'PACKET_LOSS' || status === 'UNREACHABLE'
}

export function isPingUncertainStatus(status: PingChartStatus): boolean {
  return status === 'ERROR' || status === 'NOT_SCHEDULED' || status === 'UNKNOWN'
}

export function pingPointValues(sample: Record<string, unknown>): Pick<PingChartPoint, 'status' | 'rtt' | 'loss' | 'errorReason'> {
  const errorReason = typeof sample.error_reason === 'string' ? sample.error_reason : ''
  return {
    status: (sample.status as PingChartStatus) || 'UNKNOWN',
    rtt: (sample.rtt_display_ms as number | null) ?? null,
    loss: (sample.loss_percent as number | null) ?? null,
    ...(errorReason ? { errorReason } : {}),
  }
}

/** Heartbeat reachability is based on the persisted probe result, not RTT. */
export function heartbeatPointValues(sample: Record<string, unknown>): { status: PingChartStatus; rtt: number | null; loss: number | null } {
  const status = (sample.heartbeat_status as PingChartStatus) || (sample.status as PingChartStatus) || 'UNKNOWN'
  const rtt = typeof sample.rtt_ms === 'number' ? sample.rtt_ms : null
  return { status, rtt, loss: status === 'SUCCESS' ? 0 : isPingFailureStatus(status) ? 100 : null }
}

export function heartbeatStatusStatistics(samples: Array<Record<string, unknown>>): HeartbeatStatusStatistics {
  let success = 0, failure = 0, unknown = 0
  samples.filter((sample) => !sample.warmup_ignored).forEach((sample) => {
    const status = heartbeatPointValues(sample).status
    if (status === 'SUCCESS') success++
    else if (isPingFailureStatus(status)) failure++
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
    `RTT：${point.rtt === null ? '无数据' : `${escape(point.rtt)} ms`}`,
    `状态：${pingStatusLabel(point.status)}`,
    `丢包：${point.loss === null ? '无数据' : `${escape(point.loss)}%`}`,
    point.errorReason ? `原因：${escape(point.errorReason)}` : '',
  ].filter(Boolean).join('<br>'))
  if (!body.length && rows[0]?.seriesName) {
    const target = targetFromSeries(rows[0].seriesName, targets)
    const point = points.find((item) => item.target === target && item.time === time)
    if (point) body.push(`目标：${escape(point.target)}<br>RTT：${point.rtt === null ? (point.status === 'SUCCESS' || point.status === 'UNKNOWN' ? '无数据' : '超时') : `${escape(point.rtt)} ms`}<br>状态：${pingStatusLabel(point.status)}<br>丢包：${point.loss === null ? '无数据' : `${escape(point.loss)}%`}`)
  }
  return [Number.isFinite(time) ? escape(new Date(time).toLocaleString()) : '', ...body].filter(Boolean).join('<br>')
}
