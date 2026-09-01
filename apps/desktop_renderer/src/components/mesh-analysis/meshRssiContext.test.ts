import { describe, expect, it, vi } from 'vitest'

import type { MeshChartPoint } from '../../types/meshAnalysis'
import {
  createMeshRssiContextIndex,
  resolveMeshRssiPoint,
} from './meshRssiContext'

function point(overrides: Partial<MeshChartPoint> = {}): MeshChartPoint {
  return {
    link_id: 1,
    link_count: 1,
    timestamp: '2026-08-31 07:42:50.000',
    timestamp_tag: 'T1',
    source_file_id: 1,
    segment_sequence: 1,
    local_radio: 1,
    link_state: 'ACTIVE',
    peer_mac: '0000-0000-0128',
    peer_ap_name: 'AP0128',
    peer_ap_mac: '000000001128',
    peer_radio: 'radio1',
    peer_radio_mac: '000000002128',
    station: '高桥西',
    section: '高桥西-高桥-下行',
    segment_start: '2026-08-31 07:42:50.000',
    segment_end: '2026-08-31 07:42:52.000',
    segment_duration_seconds: 14.294,
    local_rssi: 39,
    peer_rssi: 43,
    local_signal: null,
    peer_signal: null,
    local_tx_busy: 31,
    local_rx_busy: 22,
    peer_tx_busy: 45,
    peer_rx_busy: 27,
    is_switch: false,
    is_anomaly: false,
    gap_before: false,
    backups: [],
    ...overrides,
  }
}

describe('MESH RSSI context index', () => {
  it('resolves a full-line point from its own segment and never crosses the AP boundary', () => {
    const index = createMeshRssiContextIndex([
      point(),
      point({
        link_id: 4,
        timestamp: '2026-08-31 07:42:53.000',
        timestamp_tag: 'T4',
        segment_sequence: 2,
        segment_start: '2026-08-31 07:42:53.000',
        segment_end: '2026-08-31 07:42:55.000',
        peer_mac: '0000-0000-1407',
        peer_ap_name: 'AP1407',
        peer_ap_mac: '000000002407',
        peer_radio_mac: '000000003407',
      }),
    ])

    expect(index.findSegment('2026-08-31 07:42:51.000', 1)?.peer_ap_name).toBe('AP0128')
    expect(index.findSegment('2026-08-31 07:42:52.000', 1)?.peer_ap_name).toBe('AP0128')
    expect(index.findSegment('2026-08-31 07:42:53.000', 1)?.peer_ap_name).toBe('AP1407')

    const resolved = resolveMeshRssiPoint(index, {
      timestamp: '2026-08-31 07:42:51.000',
      rssi: 41,
      peerRssi: 44,
      localTxBusy: 31,
      localRxBusy: 22,
      peerTxBusy: 45,
      peerRxBusy: 27,
      radio: 1,
    })
    expect(resolved?.exact).toBe(false)
    expect(resolved?.point.peer_ap_name).toBe('AP0128')
    expect(resolved?.point.local_rssi).toBe(41)
    expect(resolved?.point.peer_rssi).toBe(44)
    expect(resolved?.point.local_tx_busy).toBe(31)
    expect(resolved?.point.peer_rx_busy).toBe(27)
  })

  it('keeps sample-level busy fields unknown when the compact full-line point has nulls', () => {
    const index = createMeshRssiContextIndex([point()])
    const resolved = resolveMeshRssiPoint(index, {
      timestamp: '2026-08-31 07:42:51.000',
      rssi: 41,
      peerRssi: null,
      localTxBusy: null,
      localRxBusy: undefined,
      peerTxBusy: null,
      peerRxBusy: undefined,
      radio: 1,
    })

    expect(resolved?.point.peer_ap_name).toBe('AP0128')
    expect(resolved?.point.local_tx_busy).toBeNull()
    expect(resolved?.point.local_rx_busy).toBeNull()
    expect(resolved?.point.peer_tx_busy).toBeNull()
    expect(resolved?.point.peer_rx_busy).toBeNull()
  })

  it('uses a binary-searchable segment index instead of scanning all overlay points per hover', () => {
    const points = Array.from({ length: 50_000 }, (_, index) => point({
      timestamp: `2026-08-31 07:42:${String(index % 60).padStart(2, '0')}.${String(index).padStart(3, '0')}`,
    }))
    const index = createMeshRssiContextIndex(points)
    const findSpy = vi.spyOn(Array.prototype, 'find')

    expect(index.findSegment('2026-08-31 07:42:51.000', 1)?.peer_ap_name).toBe('AP0128')
    expect(findSpy).not.toHaveBeenCalled()
    findSpy.mockRestore()
  })
})
