export type MeshBusinessMetricKey =
  | 'rssi'
  | 'cpu'
  | 'memory'
  | 'busy'
  | 'rate'
  | 'noise'
  | 'tx_des_free_cnt'
  | 'counters'
  | 'tx_rx' | 'retry' | 'error' | 'garp' | 'mul_join' | 'tx_busy' | 'rx_busy'

export interface MeshBusinessMetricSample {
  [key: string]: unknown
  counter_samples?: Record<string, { current: number | null; previous: number | null; delta: number | null; interval_seconds: number | null; per_second: number | null; status: string }>
  local_radio?: number | null
  peer_mac?: string | null
  link_role?: string
  establish_time?: string | null
  monitor_gap_before?: boolean
  link_count?: number | null
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
  sampleField?: string
  counterField?: string
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

const counterDefinition = GROUPS.find(group => group.key === 'counters')!
GROUPS.push(
  { key: 'tx_busy', label: '发送空口忙时（TxBusy）', lines: GROUPS.find(group => group.key === 'busy')!.lines.slice(0, 1) },
  { key: 'rx_busy', label: '接收空口忙时（RxBusy）', lines: GROUPS.find(group => group.key === 'busy')!.lines.slice(1) },
  { key: 'tx_rx', label: '发送/接收报文（Tx / Rx）', lines: counterDefinition.lines.slice(0, 2) },
  { key: 'retry', label: '重传次数（Retry）', lines: counterDefinition.lines.slice(2, 3) },
  { key: 'error', label: '错误报文数（Err）', lines: counterDefinition.lines.slice(3, 4) },
  { key: 'garp', label: 'GARP 报文（GARP）', lines: counterDefinition.lines.slice(4, 5) },
  { key: 'mul_join', label: '组播加入报文（MulJoin）', lines: counterDefinition.lines.slice(5, 6) },
)
export const meshMetricLabels: Record<string, string> = { rssi: '信号质量（RSSI）', cpu: 'CPU 利用率（CPU）', memory: '内存利用率（Memory）', busy: '发送/接收空口忙时（TxBusy / RxBusy）', tx_busy: '发送空口忙时（TxBusy）', rx_busy: '接收空口忙时（RxBusy）', rate: '协商速率（Rate）', noise: '无线底噪（Noise）', tx_des_free_cnt: '发送描述符空闲计数（TxDesFreeCnt）', tx: '发送报文（Tx）', rx: '接收报文（Rx）', retry: '重传次数（Retry）', error: '错误报文数（Err）', garp: 'GARP 报文（GARP）', mul_join: '组播加入报文（MulJoin）' }

type MetricSampleLike = {
  timestamp: string
  monitor_gap_before?: boolean
  local_radio?: unknown
  peer_mac?: unknown
  link_role?: unknown
  establish_time?: unknown
}
const continuityKeys: Array<keyof MetricSampleLike> = ['local_radio', 'peer_mac', 'link_role', 'establish_time']
function metricBoundary(previous: MetricSampleLike | undefined, current: MetricSampleLike): boolean {
  return Boolean(previous && (current.monitor_gap_before || continuityKeys.some(key => previous[key] !== current[key])))
}

/** Keeps raw samples complete while bounding points handed to ECharts. */
export function sampleMeshBusinessMetricSamples<T extends MetricSampleLike>(samples: T[], maxPoints = 4000): T[] {
  const limit = Math.max(2, Math.floor(maxPoints))
  if (samples.length <= limit) return samples
  const retained = new Set<number>([0, samples.length - 1])
  const boundaries: number[] = []
  const gaps: number[] = []
  for (let index = 1; index < samples.length; index += 1) {
    if (metricBoundary(samples[index - 1], samples[index]!)) {
      boundaries.push(index)
      if (samples[index]!.monitor_gap_before) gaps.push(index)
    }
  }
  const evenly = (values: number[], count: number): number[] => {
    if (count <= 0 || !values.length) return []
    if (values.length <= count) return values
    if (count === 1) return [values[0]!]
    return Array.from({ length: count }, (_, index) => values[Math.round(index * (values.length - 1) / (count - 1))]!)
  }
  const selectedBoundaries = [...evenly(gaps, limit - 2), ...evenly(boundaries.filter(index => !gaps.includes(index)), limit - 2 - Math.min(gaps.length, limit - 2))]
  for (const index of selectedBoundaries) if (retained.size < limit) retained.add(index)
  for (const index of evenly(Array.from({ length: samples.length }, (_, value) => value).filter(index => !retained.has(index)), limit - retained.size)) {
    if (retained.size >= limit) break
    retained.add(index)
  }
  return [...retained].sort((a, b) => a - b).map(index => samples[index]!)
}

function makeLine(samples: MeshBusinessMetricSample[], definition: MetricLine, side: 'local' | 'peer'): MeshBusinessMetricLine {
  const field = side === 'local' ? definition.local : definition.peer
  return {
    key: `${definition.key}_${side}`,
    sampleField: String(field),
    label: `${side === 'local' ? '本端' : '对端'} ${meshMetricLabels[definition.key] || definition.label}`,
    counterField: String(field).endsWith('_delta') ? String(field).replace('_error_delta', '_err_delta').replace(/_delta$/, '') : undefined,
    side,
    data: samples.flatMap((sample, index) => {
      const previous = samples[index - 1]
      const boundary = metricBoundary(previous, sample)
      const counterField = String(field).replace('_error_delta', '_err_delta').replace(/_delta$/, '')
      const value = String(field).endsWith('_delta') ? sample.counter_samples?.[counterField]?.per_second : sample[field]
      const point = { value: [sample.timestamp, sample.link_count === 0 || value == null ? null : Number(value)] as [string, number | null], sample }
      return boundary ? [{ value: [sample.timestamp, null] as [string, number | null], sample }, point] : [point]
    }),
  }
}

export function buildMeshBusinessMetricGroups(samples: MeshBusinessMetricSample[], key?: MeshBusinessMetricKey): MeshBusinessMetricGroup[] {
  return GROUPS.filter(group => key ? group.key === key : !['counters', 'busy'].includes(group.key)).map((group) => ({
    key: group.key,
    label: meshMetricLabels[group.key] || group.label,
    lines: group.lines.flatMap((line) => [makeLine(samples, line, 'local'), makeLine(samples, line, 'peer')]),
  }))
}
