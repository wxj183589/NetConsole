export type MeshBusinessMetricKey =
  | 'rssi'
  | 'cpu'
  | 'memory'
  | 'busy'
  | 'rate'
  | 'noise'
  | 'tx_des_free_cnt'
  | 'counters'

export interface MeshBusinessMetricSample {
  timestamp: string
  local_rssi?: number | null
  peer_rssi?: number | null
  local_cpu_percent?: number | null
  peer_cpu_percent?: number | null
  local_mem_percent?: number | null
  peer_mem_percent?: number | null
  local_tx_busy?: number | null
  peer_tx_busy?: number | null
  local_rx_busy?: number | null
  peer_rx_busy?: number | null
  local_rate_raw?: number | null
  peer_rate_raw?: number | null
  local_noise_dbm?: number | null
  peer_noise_dbm?: number | null
  local_tx_des_free_cnt?: number | null
  peer_tx_des_free_cnt?: number | null
  local_tx_delta?: number | null
  peer_tx_delta?: number | null
  local_rx_delta?: number | null
  peer_rx_delta?: number | null
  local_retry_delta?: number | null
  peer_retry_delta?: number | null
  local_error_delta?: number | null
  peer_error_delta?: number | null
  local_tx_garp_delta?: number | null
  peer_rx_garp_delta?: number | null
  local_tx_mul_join_delta?: number | null
  peer_rx_mul_join_delta?: number | null
}

export interface MeshBusinessMetricLine {
  key: string
  label: string
  side: 'local' | 'peer'
  data: Array<{ value: [string, number | null]; sample: MeshBusinessMetricSample }>
}

export interface MeshBusinessMetricGroup {
  key: MeshBusinessMetricKey
  label: string
  lines: MeshBusinessMetricLine[]
}

type MetricField = keyof MeshBusinessMetricSample
type MetricLine = { key: string; label: string; local: MetricField; peer: MetricField }

const GROUPS: Array<{ key: MeshBusinessMetricKey; label: string; lines: MetricLine[] }> = [
  { key: 'rssi', label: 'RSSI', lines: [{ key: 'rssi', label: 'RSSI', local: 'local_rssi', peer: 'peer_rssi' }] },
  { key: 'cpu', label: 'CPU', lines: [{ key: 'cpu', label: 'CPU', local: 'local_cpu_percent', peer: 'peer_cpu_percent' }] },
  { key: 'memory', label: 'Memory', lines: [{ key: 'memory', label: 'Memory', local: 'local_mem_percent', peer: 'peer_mem_percent' }] },
  {
    key: 'busy', label: 'Tx/Rx Busy', lines: [
      { key: 'tx_busy', label: 'TxBusy', local: 'local_tx_busy', peer: 'peer_tx_busy' },
      { key: 'rx_busy', label: 'RxBusy', local: 'local_rx_busy', peer: 'peer_rx_busy' },
    ],
  },
  { key: 'rate', label: 'Rate', lines: [{ key: 'rate', label: 'Rate', local: 'local_rate_raw', peer: 'peer_rate_raw' }] },
  { key: 'noise', label: 'Noise', lines: [{ key: 'noise', label: 'Noise', local: 'local_noise_dbm', peer: 'peer_noise_dbm' }] },
  { key: 'tx_des_free_cnt', label: 'TxDesFreeCnt', lines: [{ key: 'tx_des_free_cnt', label: 'TxDesFreeCnt', local: 'local_tx_des_free_cnt', peer: 'peer_tx_des_free_cnt' }] },
  {
    key: 'counters', label: 'Tx/Rx/Retry/Err/GARP/MulJoin', lines: [
      { key: 'tx', label: 'Tx', local: 'local_tx_delta', peer: 'peer_tx_delta' },
      { key: 'rx', label: 'Rx', local: 'local_rx_delta', peer: 'peer_rx_delta' },
      { key: 'retry', label: 'Retry', local: 'local_retry_delta', peer: 'peer_retry_delta' },
      { key: 'error', label: 'Err', local: 'local_error_delta', peer: 'peer_error_delta' },
      { key: 'garp', label: 'GARP', local: 'local_tx_garp_delta', peer: 'peer_rx_garp_delta' },
      { key: 'mul_join', label: 'MulJoin', local: 'local_tx_mul_join_delta', peer: 'peer_rx_mul_join_delta' },
    ],
  },
]

function makeLine(samples: MeshBusinessMetricSample[], definition: MetricLine, side: 'local' | 'peer'): MeshBusinessMetricLine {
  const field = side === 'local' ? definition.local : definition.peer
  return {
    key: `${definition.key}_${side}`,
    label: `${side === 'local' ? 'MR' : 'Peer'} ${definition.label}`,
    side,
    data: samples.map((sample) => ({ value: [sample.timestamp, sample[field] == null ? null : Number(sample[field])] as [string, number | null], sample })),
  }
}

export function buildMeshBusinessMetricGroups(samples: MeshBusinessMetricSample[]): MeshBusinessMetricGroup[] {
  return GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    lines: group.lines.flatMap((line) => [makeLine(samples, line, 'local'), makeLine(samples, line, 'peer')]),
  }))
}
