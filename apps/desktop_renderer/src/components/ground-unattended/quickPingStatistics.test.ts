import { describe, expect, it } from 'vitest'
import { selectedQuickPingStatistics } from './quickPingStatistics'

const row = (received_at: string, status: 'SUCCESS' | 'TIMEOUT' | 'PACKET_LOSS' | 'UNKNOWN', rtt_display_ms: number | null, extra: Record<string, unknown> = {}) => ({
  received_at,
  target_ip: '192.0.2.1',
  sample: { sample_id: `${received_at}-${status}`, seq: received_at, status, rtt_display_ms, ...extra },
})

describe('Quick Ping Backend statistics consumption', () => {
  it('does not count UNKNOWN as success and does not duplicate a repeated sample', () => {
    const sample = row('2026-11-22T00:00:00.100Z', 'UNKNOWN', null)
    const stats = selectedQuickPingStatistics([
      sample,
      sample,
      row('2026-11-22T00:00:00.200Z', 'TIMEOUT', null),
    ])
    expect(stats).toMatchObject({ ping_total: 2, ping_success: 0, ping_lost: 1, ping_unknown: 1, packet_loss_rate: 50 })
    expect(stats.min_rtt_ms).toBeNull()
  })

  it('returns no-data rate and RTT metrics for an empty window', () => {
    expect(selectedQuickPingStatistics([])).toEqual({
      ping_total: 0, ping_success: 0, ping_lost: 0, ping_unknown: 0,
      packet_loss_rate: null, min_rtt_ms: null, average_rtt_ms: null, max_rtt_ms: null,
    })
  })
})
