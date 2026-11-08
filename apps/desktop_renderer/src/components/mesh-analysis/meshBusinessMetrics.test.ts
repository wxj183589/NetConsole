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
    local_retry_delta: 2, peer_retry_delta: 3, local_error_delta: 1, peer_error_delta: 0,
    local_tx_garp_delta: 4, peer_rx_garp_delta: 5, local_tx_mul_join_delta: 6, peer_rx_mul_join_delta: 7,
  },
]

describe('mesh business metric groups', () => {
  it('returns the eight business groups in stable display order', () => {
    const groups = buildMeshBusinessMetricGroups(samples)
    expect(groups.map((group) => group.key)).toEqual([
      'rssi', 'cpu', 'memory', 'busy', 'rate', 'noise', 'tx_des_free_cnt', 'counters',
    ])
    expect(groups.find((group) => group.key === 'busy')?.lines.map((line) => line.key)).toEqual([
      'tx_busy_local', 'tx_busy_peer', 'rx_busy_local', 'rx_busy_peer',
    ])
  })

  it('preserves null values and maps counter deltas without inventing zeros', () => {
    const groups = buildMeshBusinessMetricGroups([{ timestamp: 't', local_retry_delta: null, peer_retry_delta: 3 }])
    const retryLines = groups.find((group) => group.key === 'counters')!.lines.filter((line) => line.key.startsWith('retry_'))
    expect(retryLines[0]!.data[0]!.value).toEqual(['t', null])
    expect(retryLines[1]!.data[0]!.value).toEqual(['t', 3])
  })
})
