import { describe, expect, it } from 'vitest'
import type { MeshLinkDetail } from '../../types/meshAnalysis'
import { MESH_RAW_SAMPLE_VERSION, MeshRawSampleCache, deriveMeshRawSamples, meshRawSampleKey } from './meshRawSampleCache'
import type { Interval } from './meshCompleteMetricCache'
import { formatMeshViewportTimestamp } from './meshChartViewport'

const BASE = Date.parse('2026-11-10T10:00:00.000')

function row(id: number, second: number, overrides: Partial<MeshLinkDetail> = {}): MeshLinkDetail {
  return {
    record_id: id,
    source_file_id: 1,
    timestamp: formatMeshViewportTimestamp(BASE + second * 1_000),
    timestamp_tag: String(id),
    sample_group_index: id,
    train_name: 'T01', mr_name: 'MR-CT', mr_role: 'CT',
    local_radio: 1, peer_mac: 'peer-a', peer_ap_name: 'AP-A', peer_ap_mac: 'ap-a', peer_radio: 'R1', peer_radio_mac: 'radio-a',
    link_role: 'ACTIVE', link_status: 'ACTIVE', link_count: 1,
    establish_time: '2026-11-10 09:59:00.000', duration_text: '1s', duration_seconds: 1,
    local_rssi_db: 40, peer_rssi_db: 40, local_noise_dbm: null, peer_noise_dbm: null, local_signal_dbm: null, peer_signal_dbm: null,
    local_rate_raw: null, peer_rate_raw: null, local_tx_busy: null, peer_tx_busy: null, local_rx_busy: null, peer_rx_busy: null,
    rssi: 40, channel: null, bandwidth: null, station: null, section: null, mileage: null, line_side: null,
    event_type: null, duration_ms: 1000, source_file: 'mesh.log', source_record_index: id, source_line_number: id,
    local_cpu_percent: null, peer_cpu_percent: null, local_mem_percent: null, peer_mem_percent: null,
    local_tx_des_free_cnt: null, peer_tx_des_free_cnt: null, local_tx: 100 + id * 10, peer_tx: 200 + id * 10,
    local_rx: 300 + id * 10, peer_rx: 400 + id * 10, local_retry: id, peer_retry: id,
    local_err: id, peer_err: id, local_tx_garp: id, peer_rx_garp: id, local_tx_mul_join: id, peer_rx_mul_join: id,
    raw_line_start: null, raw_line_end: null, raw_offset_start: null, raw_offset_end: null, match_method: null, warning: null,
    ...overrides,
  }
}

function page(items: MeshLinkDetail[], complete = true) {
  return { items, total: items.filter(item => !item.is_boundary_context).length, page: 1, page_size: 1000, downsampled: false, raw_sample_complete: complete, raw_sample_version: MESH_RAW_SAMPLE_VERSION }
}

describe('MESH raw sample cache', () => {
  it('keeps identities and duplicate timestamps separate while planning millisecond gaps', () => {
    const cache = new MeshRawSampleCache({ maxScopes: 4 })
    const first = row(1, 0)
    const sameTimeOtherLink = row(2, 0, { peer_mac: 'peer-b', peer_ap_mac: 'ap-b' })
    cache.put('session-a', { start: BASE, end: BASE + 5_000 }, page([first, sameTimeOtherLink]))
    cache.put('session-a', { start: BASE + 10_000, end: BASE + 15_000 }, page([row(3, 10), row(4, 11)]))
    expect(cache.missing('session-a', { start: BASE, end: BASE + 15_000 })).toEqual([{ start: BASE + 5_001, end: BASE + 9_999 }])
    expect(cache.visible('session-a', { start: BASE, end: BASE + 5_000 })).toHaveLength(2)
    expect(meshRawSampleKey(first)).not.toBe(meshRawSampleKey(sameTimeOtherLink))
    expect(cache.missing('session-b', { start: BASE, end: BASE + 5_000 })).toEqual([{ start: BASE, end: BASE + 5_000 }])
  })

  it('fills only the missing middle interval and then serves the full range from cache', () => {
    const cache = new MeshRawSampleCache()
    const requested: Interval[] = []
    const a = { start: BASE, end: BASE + 1_000 }
    const c = { start: BASE + 2_000, end: BASE + 3_000 }
    cache.put('scope', a, page([row(1, 0), row(2, 1)]))
    cache.put('scope', c, page([row(3, 2), row(4, 3)]))
    const missing = cache.missing('scope', { start: BASE, end: BASE + 3_000 })
    expect(missing).toEqual([{ start: BASE + 1_001, end: BASE + 1_999 }])
    for (const interval of missing) {
      requested.push(interval)
      cache.put('scope', interval, page([row(5, 1.5)]))
    }
    expect(requested).toEqual([{ start: BASE + 1_001, end: BASE + 1_999 }])
    expect(cache.missing('scope', { start: BASE, end: BASE + 3_000 })).toEqual([])
    expect(cache.all('scope')).toHaveLength(5)
  })

  it('does not advance coverage for incomplete responses and evicts the least recently used scope', () => {
    const cache = new MeshRawSampleCache({ maxScopes: 2 })
    expect(cache.put('incomplete', { start: BASE, end: BASE + 1 }, page([row(1, 0)], false))).toBe(false)
    expect(cache.missing('incomplete', { start: BASE, end: BASE + 1 })).toEqual([{ start: BASE, end: BASE + 1 }])
    cache.put('a', { start: BASE, end: BASE + 1 }, page([row(2, 0)]))
    cache.put('b', { start: BASE, end: BASE + 1 }, page([row(3, 0)]))
    cache.put('c', { start: BASE, end: BASE + 1 }, page([row(4, 0)]))
    expect(cache.missing('a', { start: BASE, end: BASE + 1 })).toEqual([{ start: BASE, end: BASE + 1 }])
  })

  it('produces identical counter deltas when the second segment only carries a predecessor context row', () => {
    const all = [row(1, 0), row(2, 1), row(3, 2), row(4, 3)]
    const full = deriveMeshRawSamples(all, { start: BASE, end: BASE + 3_000 })
    const cache = new MeshRawSampleCache()
    cache.put('scope', { start: BASE, end: BASE + 1_000 }, page(all.slice(0, 2)))
    cache.put('scope', { start: BASE + 2_000, end: BASE + 3_000 }, page([{ ...all[1]!, is_boundary_context: true }, all[2]!, all[3]!]))
    const segmented = deriveMeshRawSamples(cache.all('scope'), { start: BASE, end: BASE + 3_000 })
    expect(segmented.map(item => [item.record_id, item.counter_samples?.local_tx?.previous, item.counter_samples?.local_tx?.delta, item.counter_samples?.local_tx?.per_second])).toEqual(
      full.map(item => [item.record_id, item.counter_samples?.local_tx?.previous, item.counter_samples?.local_tx?.delta, item.counter_samples?.local_tx?.per_second]),
    )
    expect(segmented.map(item => item.is_boundary_context)).toEqual([undefined, undefined, undefined, undefined])
  })

  it('marks reset, role changes and long gaps without mutating raw rows', () => {
    const source = [
      row(1, 0, { local_tx: 100 }),
      row(2, 1, { local_tx: 120 }),
      row(3, 2, { local_tx: 10 }),
      row(4, 3, { local_tx: 20, link_role: 'STANDBY' }),
      row(5, 20, { local_tx: 30, link_role: 'STANDBY' }),
    ]
    const snapshot = JSON.stringify(source)
    const result = deriveMeshRawSamples(source, { start: BASE, end: BASE + 20_000 })
    expect(result[1]!.counter_samples?.local_tx?.delta).toBe(20)
    expect(result[2]!.counter_samples?.local_tx?.status).toBe('reset')
    expect(result[2]!.counter_samples?.local_tx?.delta).toBeNull()
    expect(result[3]!.counter_samples?.local_tx?.status).toBe('link_changed')
    expect(result[4]!.monitor_gap_before).toBe(true)
    expect(JSON.stringify(source)).toBe(snapshot)
  })
})
