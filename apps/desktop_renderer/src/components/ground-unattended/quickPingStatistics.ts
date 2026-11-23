import type { PingChartStatus } from './pingChartStatus'

export interface QuickPingStatistics {
  ping_total: number
  ping_success: number
  ping_lost: number
  ping_unknown: number
  packet_loss_rate: number | null
  min_rtt_ms: number | null
  average_rtt_ms: number | null
  max_rtt_ms: number | null
}

function sampleOf(row: Record<string, unknown>): Record<string, unknown> {
  const nested = row.sample
  return nested && typeof nested === 'object' ? nested as Record<string, unknown> : row
}

function timestampOf(row: Record<string, unknown>): number {
  return Date.parse(String(row.received_at || row.ts || sampleOf(row).received_at || sampleOf(row).ts || ''))
}

function sampleKey(row: Record<string, unknown>, time: number): string {
  const sample = sampleOf(row)
  const id = String(row.sample_id || sample.sample_id || '')
  if (id) return `id:${id}`
  return [row.quick_run_id || sample.quick_ping_run_id || '', row.target_ip || sample.target_ip || '', sample.seq ?? row.seq ?? '', time].join('|')
}

function statusCounts(status: PingChartStatus): Pick<QuickPingStatistics, 'ping_success' | 'ping_lost' | 'ping_unknown'> {
  return {
    ping_success: status === 'SUCCESS' ? 1 : 0,
    ping_lost: status === 'TIMEOUT' || status === 'PACKET_LOSS' ? 1 : 0,
    ping_unknown: status === 'UNKNOWN' ? 1 : 0,
  }
}

function rate(total: number, lost: number): number | null {
  return total ? (lost / total) * 100 : null
}

/** Read Backend statistics while retaining only de-duplication for mixed pages. */
export function selectedQuickPingStatistics(rows: Array<Record<string, unknown>>): QuickPingStatistics {
  const seen = new Set<string>()
  let ping_total = 0
  let ping_success = 0
  let ping_lost = 0
  let ping_unknown = 0
  const rtts: number[] = []
  for (const row of rows) {
    const time = timestampOf(row)
    if (!Number.isFinite(time)) continue
    const key = sampleKey(row, time)
    if (seen.has(key)) continue
    seen.add(key)
    const sample = sampleOf(row)
    const status = (sample.status as PingChartStatus) || 'UNKNOWN'
    const counts = statusCounts(status)
    ping_total += 1
    ping_success += counts.ping_success
    ping_lost += counts.ping_lost
    ping_unknown += counts.ping_unknown
    const rtt = typeof sample.rtt_display_ms === 'number' ? sample.rtt_display_ms : null
    if (rtt !== null && status === 'SUCCESS') rtts.push(rtt)
  }
  return {
    ping_total,
    ping_success,
    ping_lost,
    ping_unknown,
    packet_loss_rate: rate(ping_total, ping_lost),
    min_rtt_ms: rtts.length ? Math.min(...rtts) : null,
    average_rtt_ms: rtts.length ? rtts.reduce((sum, value) => sum + value, 0) / rtts.length : null,
    max_rtt_ms: rtts.length ? Math.max(...rtts) : null,
  }
}
