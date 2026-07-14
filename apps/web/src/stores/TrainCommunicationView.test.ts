import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useTrainCommunicationStore } from './trainCommunication'
import {
  getMrCommunication,
  getMrCommunicationPreview,
  getTrainCommunication,
  getTrainCommunicationSummary,
  listTrainCommunications,
} from '../api/trainCommunication'
import { getOnlineMrRawTail } from '../api/onlineMr'
import type { MrCommunicationDetail, MrCommunicationStatus, TrainCommunicationDetail, TrainCommunicationRow } from '../types/trainCommunication'

vi.mock('../api/trainCommunication', () => ({
  getMrCommunication: vi.fn(),
  getMrCommunicationPreview: vi.fn(),
  getTrainCommunication: vi.fn(),
  getTrainCommunicationSummary: vi.fn(),
  listTrainCommunications: vi.fn(),
}))
vi.mock('../api/onlineMr', () => ({ getOnlineMrRawTail: vi.fn() }))

function mr(role: 'CT' | 'TC'): MrCommunicationStatus {
  return {
    train_id: '01', train_name: '01车', mr_id: `mr-${role}`, mr_name: `列车01-MR-${role}`, mr_role: role,
    device_id: role === 'CT' ? 1 : 2, management_ip: '', mac: '', executor: 'LOCAL', agent_id: null,
    collection_status: 'COLLECTING', session_id: 'session-1', task_id: 'task-1', mesh_link_status: 'Forwarding',
    peer_ap_id: '', peer_ap_name: role === 'CT' ? 'AP-01' : 'AP-02', peer_ap_mac: '', mesh_radio: 'Radio 1',
    rssi: -55, station: '车站A', section: 'A-B区间', mileage: '', line_side: '', ap_online_status: 'online', optical_status: 'normal',
    fping_status: 'running', fping_latest_rtt_ms: 2, fping_avg_rtt_ms: 2, fping_loss_percent: 0,
    iperf_status: 'running', iperf_latest_mbps: 10, iperf_avg_mbps: 9, iperf_threshold_mbps: null,
    data_integrity: 'unknown', collected_at: null, data_age_seconds: 1, communication_status: 'normal', is_active: true,
    warnings: [], data_sources: [],
    fping: { status: 'running', target: null, protocol: null, direction: null, sent: null, received: null, loss_percent: 0, latest_value: 2, average_value: 2, maximum_value: null, threshold_value: null, updated_at: null },
    iperf: { status: 'running', target: null, protocol: null, direction: null, sent: null, received: null, loss_percent: null, latest_value: 10, average_value: 9, maximum_value: null, threshold_value: null, updated_at: null },
  }
}

const row: TrainCommunicationRow = {
  train_id: '01', train_no: '01', train_name: '01车', communication_status: 'normal',
  mrs: [mr('CT'), mr('TC')], current_mesh_links: 2, active_sessions: 2, warning_count: 0, last_updated_at: null,
}
const trainDetail: TrainCommunicationDetail = { train: row, site_id: 'demo', sources: [], warnings: [] }
const mrDetail: MrCommunicationDetail = { mr: row.mrs[0], collectors: [], raw_sources: [], tasks: [], packages: [] }

describe('TrainCommunicationView read-only polling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getTrainCommunicationSummary).mockReset().mockResolvedValue({
      site_id: 'demo', registered_trains: 1, registered_mrs: 2, normal_trains: 1, warning_trains: 0,
      critical_trains: 0, stale_trains: 0, unknown_trains: 0, current_mesh_links: 2,
      active_online_mr_sessions: 1, agent_imported_sessions: 0, latest_updated_at: null,
    })
    vi.mocked(listTrainCommunications).mockReset().mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 50 })
    vi.mocked(getTrainCommunication).mockReset().mockResolvedValue(trainDetail)
    vi.mocked(getMrCommunication).mockReset().mockResolvedValue(mrDetail)
    vi.mocked(getMrCommunicationPreview).mockReset().mockResolvedValue(row.mrs[0])
    vi.mocked(getOnlineMrRawTail).mockReset().mockResolvedValue({ success: true, name: 'mesh_link', exists: true, lines: ['ok'], message: '', size_bytes: 2, modified_at: null, summary: {} })
    vi.stubGlobal('window', { setTimeout, clearTimeout })
    vi.stubGlobal('document', { hidden: false })
  })

  it('loads summary and keeps MR-CT/MR-TC as independent rows', async () => {
    const store = useTrainCommunicationStore()
    await store.refreshCore()

    expect(store.summary?.registered_mrs).toBe(2)
    expect(store.trains[0].mrs.map((item) => item.mr_role)).toEqual(['CT', 'TC'])
    expect(store.trains[0].mrs.map((item) => item.peer_ap_name)).toEqual(['AP-01', 'AP-02'])
    expect('collect' in store).toBe(false)
    expect('cancelTask' in store).toBe(false)
  })

  it('polls raw only while expanded and stops when page is hidden', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    const store = useTrainCommunicationStore()
    await store.selectMr('mr-CT')
    store.startPolling()
    store.setRawExpanded(true)
    await vi.runAllTicks()
    expect(getOnlineMrRawTail).toHaveBeenCalledOnce()

    const calls = vi.mocked(getOnlineMrRawTail).mock.calls.length
    store.setPageVisible(false)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(getOnlineMrRawTail).toHaveBeenCalledTimes(calls)
    store.stopPolling()
    vi.useRealTimers()
  })

  it('retains last data and reports only after three refresh failures', async () => {
    const store = useTrainCommunicationStore()
    await store.refreshCore()
    vi.mocked(getTrainCommunicationSummary).mockRejectedValue(new Error('offline'))
    await store.refreshCore()
    await store.refreshCore()
    expect(store.error).toBe('')
    await store.refreshCore()
    expect(store.error).toContain('降低刷新频率')
    expect(store.trains).toHaveLength(1)
  })
})
