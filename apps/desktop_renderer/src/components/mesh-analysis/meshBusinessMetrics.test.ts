import { describe, expect, it } from 'vitest'
import { buildMeshBusinessMetricGroups, type MeshBusinessMetricSample } from './meshBusinessMetrics'

const samples: MeshBusinessMetricSample[] = [
  {
    timestamp: '2026-07-20T10:00:00Z', local_rssi: -42, peer_rssi: -48,
    local_cpu_percent: 12, peer_cpu_percent: 22, local_mem_percent: 34, peer_mem_percent: 44,
    local_tx_busy: 15, peer_tx_busy: 25, local_rx_busy: 16, peer_rx_busy: 26,
    local_rate_raw: 54, peer_rate_raw: 36, local_noise_dbm: -90, peer_noise_dbm: -88,
    local_tx_des_free_cnt: 8, peer_tx_des_free_cnt: 6,
    local_tx_delta: 10, peer_tx_delta: 9, local_rx_delta: 11, peer_rx_delta: 12,
    counter_samples: Object.fromEntries(['local_tx', 'peer_tx', 'local_rx', 'peer_rx', 'local_retry', 'peer_retry', 'local_err', 'peer_err', 'local_tx_garp', 'peer_rx_garp', 'local_tx_mul_join', 'peer_rx_mul_join'].map((key, index) => [key, { current: 100 + index * 2, previous: 100, delta: index * 2, interval_seconds: 0.5, per_second: index * 4, status: 'valid' }])),
    local_retry_delta: 2, peer_retry_delta: 3, local_error_delta: 1, peer_error_delta: 0,
    local_tx_garp_delta: 4, peer_rx_garp_delta: 5, local_tx_mul_join_delta: 6, peer_rx_mul_join_delta: 7,
  },
]

describe('mesh business metric groups', () => {
  it('returns twelve business charts in stable display order', () => {
    const groups = buildMeshBusinessMetricGroups(samples)
    expect(groups.map((group) => group.key)).toEqual([
      'rssi', 'cpu', 'memory', 'rate', 'noise', 'tx_des_free_cnt', 'tx_busy', 'rx_busy', 'tx_rx', 'retry', 'error', 'control',
    ])
    expect(groups.find((group) => group.key === 'tx_busy')?.lines.map((line) => line.key)).toEqual([
      'tx_busy_local', 'tx_busy_peer',
    ])
  })

  it('preserves missing rates without treating legacy deltas as per-second values', () => {
    const groups = buildMeshBusinessMetricGroups([{ timestamp: 't', local_retry_delta: null, peer_retry_delta: 3 }])
    const retryLines = groups.find((group) => group.key === 'retry')!.lines
    expect(retryLines[0]!.data[0]!.value).toEqual(['t', null])
    expect(retryLines[1]!.data[0]!.value).toEqual(['t', null])
  })

  it('uses API per-second metadata for all twelve counter lines including Err aliases', () => {
    const lines = buildMeshBusinessMetricGroups(samples).flatMap(group => group.lines).filter(line => line.counterField)
    expect(lines).toHaveLength(12)
    for (const line of lines) {
      expect(line.data[0]!.value).toEqual([samples[0]!.timestamp, samples[0]!.counter_samples![line.counterField!]!.per_second])
      expect(line.data[0]!.sample).toBe(samples[0])
    }
    expect(lines.find(line => line.key === 'error_local')!.counterField).toBe('local_err')
    expect(lines.find(line => line.key === 'tx_local')!.data[0]!.value[1]).toBe(0)
  })

  it.each(['local_radio', 'peer_mac', 'link_role', 'establish_time', 'monitor_gap_before'] as const)('breaks gauges and counters at a %s boundary', key => {
    const first = { ...samples[0]!, local_radio: 1, peer_mac: 'aabbccddeeff', link_role: 'ACTIVE', establish_time: 'first' }
    const next = { ...first, timestamp: '2026-07-20T10:00:01Z', [key]: key === 'monitor_gap_before' ? true : key === 'local_radio' ? 2 : 'changed' }
    for (const group of buildMeshBusinessMetricGroups([first, next])) {
      for (const line of group.lines) expect(line.data.map(point => point.value[1])).toEqual([line.data[0]!.value[1], null, line.data[0]!.value[1]])
    }
  })

  it('leaves zero-link observations empty and continuous samples connected', () => {
    expect(buildMeshBusinessMetricGroups([{ ...samples[0]!, link_count: 0 }]).flatMap(group => group.lines).every(line => line.data[0]!.value[1] === null)).toBe(true)
    expect(buildMeshBusinessMetricGroups([samples[0]!, { ...samples[0]!, timestamp: 'next' }]).flatMap(group => group.lines).every(line => line.data.length === 2)).toBe(true)
  })
})
