import { describe, expect, it } from 'vitest'
import { naturalSecondLossBuckets, selectedQuickPingStatistics } from './quickPingStatistics'

const row = (received_at: string, ok: boolean, rtt_ms: number | null, extra: Record<string, unknown> = {}) => ({
  received_at,
  target_ip: '192.0.2.1',
  sample: { sample_id: `${received_at}-${ok}`, seq: received_at, ok, rtt_ms, ...extra },
})

describe('Quick Ping natural-second statistics', () => {
  it('uses half-open natural-second buckets and preserves millisecond boundaries', () => {
    const buckets = naturalSecondLossBuckets([
      row('2026-11-22T00:00:00.000Z', true, 2.5),
      row('2026-11-22T00:00:00.999Z', false, null, { timeout: true }),
      row('2026-11-22T00:00:01.000Z', true, 3.5),
    ])
    expect(buckets).toHaveLength(2)
    expect(buckets[0]).toMatchObject({ ping_total: 2, ping_success: 1, ping_lost: 1, packet_loss_rate: 50 })
    expect(buckets[1]).toMatchObject({ ping_total: 1, ping_success: 1, ping_lost: 0, packet_loss_rate: 0 })
  })

  it('does not count UNKNOWN as success and does not duplicate a repeated sample', () => {
    const sample = row('2026-11-22T00:00:00.100Z', true, null)
    const stats = selectedQuickPingStatistics([
      sample,
      sample,
      row('2026-11-22T00:00:00.200Z', false, null, { timeout: true }),
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
