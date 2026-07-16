import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAcMeshLinkStore } from './acMeshLink'
import {
  getMeshLinkSummary,
  getMeshMrDetail,
  getMeshRawTail,
  listMeshLinks,
  listMeshMrs,
  listMeshSnapshots,
  startMeshLinkRefresh,
} from '../api/acMeshLink'
import { getAcSummary } from '../api/acManagement'
import { getTask } from '../api/tasks'

vi.mock('../api/acMeshLink', () => ({
  getMeshLinkSummary: vi.fn(),
  getMeshMrDetail: vi.fn(),
  getMeshRawTail: vi.fn(),
  listMeshLinks: vi.fn(),
  listMeshMrs: vi.fn(),
  listMeshSnapshots: vi.fn(),
  startMeshLinkRefresh: vi.fn(),
}))

vi.mock('../api/acManagement', () => ({ getAcSummary: vi.fn() }))
vi.mock('../api/tasks', () => ({ getTask: vi.fn() }))

const emptyPage = { items: [], total: 0, page: 1, page_size: 50 }

describe('AC Mesh-Link read-only polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getMeshLinkSummary).mockReset().mockResolvedValue({
      site_id: 'demo', controller_id: 'ac-1', controller_name: '测试 AC',
      registered_mrs: 0, online_mrs: 0, offline_mrs: 0,
      stale_mrs: 0, unknown_mrs: 0, active_links: 0, link_total: 0,
      unmatched_links: 0, offline_ap_links: 0, updated_at: '', age_seconds: null,
      data_status: 'no_data', source_type: 'vehicle_mr_online_snapshot', raw_available: false, message: '',
    })
    vi.mocked(listMeshMrs).mockReset().mockResolvedValue(emptyPage)
    vi.mocked(listMeshLinks).mockReset().mockResolvedValue(emptyPage)
    vi.mocked(listMeshSnapshots).mockReset().mockResolvedValue({ ...emptyPage, page_size: 30 })
    vi.mocked(getMeshMrDetail).mockReset()
    vi.mocked(getMeshRawTail).mockReset().mockResolvedValue({
      snapshot_id: null, available: false, lines: [], line_count: 0,
      source_reference: '', updated_at: '', message: '暂无原始数据',
    })
    vi.mocked(getAcSummary).mockReset().mockResolvedValue({
      site_id: 'demo', acs: [{
        id: 'ac-1', name: '测试 AC', management_ip: '10.0.0.1', model: '', software_version: '',
        ap_total: 0, online_aps: 0, offline_aps: 0, unauthenticated_aps: 0,
        radio_total: 0, optical_anomalies: 0, updated_at: '', data_source: 'SQLite 已采集数据',
      }], ap_total: 0, online_aps: 0, offline_aps: 0, unauthenticated_aps: 0,
      radio_total: 0, optical_anomalies: 0, updated_at: '', message: '',
    })
    vi.mocked(startMeshLinkRefresh).mockReset().mockResolvedValue({
      success: true, task_id: 'refresh-1', status: 'RUNNING', already_running: false, message: '已创建',
    })
    vi.mocked(getTask).mockReset().mockResolvedValue({
      id: 'refresh-1', type: 'ac_mesh_link_refresh', name: 'AC Mesh-Link 刷新', status: 'RUNNING',
      progress: 20, phase: '', stage: '', message: '', site_name: 'demo', owner: 'web_ac_mesh_link',
      executor: 'LOCAL', source: 'local', device_id: 'ac-1', device_name: '测试 AC', agent: '', mr_name: '',
      session_id: '', mapping_state: '', created_time: '', started_time: '', finished_time: '', updated_time: '',
      duration_seconds: 0, error_code: '', error_summary: '', has_warning: false,
      snapshot_id: null, records_count: null, parser_version: '',
    })
    vi.stubGlobal('window', { setTimeout, clearTimeout })
  })

  it('does not overlap core refreshes and reports repeated failures', async () => {
    let rejectRequest: ((reason?: unknown) => void) | undefined
    vi.mocked(getMeshLinkSummary).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject }))
    const store = useAcMeshLinkStore()
    const first = store.refreshCore()
    void store.refreshCore()
    expect(getMeshLinkSummary).toHaveBeenCalledOnce()
    rejectRequest?.(new Error('offline'))
    await first

    vi.mocked(getMeshLinkSummary).mockRejectedValue(new Error('offline'))
    await store.refreshCore()
    await store.refreshCore()
    expect(store.error).toContain('Mesh-Link 数据刷新失败')
  })

  it('polls raw output only while expanded and stops every timer', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    const store = useAcMeshLinkStore()
    store.startPolling()
    await vi.runAllTicks()
    expect(getMeshRawTail).not.toHaveBeenCalled()

    store.setRawExpanded(true)
    await vi.runAllTicks()
    expect(getMeshRawTail).toHaveBeenCalledOnce()
    store.setRawExpanded(false)
    const rawCalls = vi.mocked(getMeshRawTail).mock.calls.length
    store.stopPolling()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(getMeshRawTail).toHaveBeenCalledTimes(rawCalls)
    expect('collect' in store).toBe(false)
    expect('stopTask' in store).toBe(false)
    vi.useRealTimers()
  })

  it('creates one controlled refresh task and does not cancel it when polling stops', async () => {
    const store = useAcMeshLinkStore()
    await store.refreshCore()
    const first = store.startRefresh()
    const second = store.startRefresh()
    await Promise.all([first, second])

    expect(startMeshLinkRefresh).toHaveBeenCalledOnce()
    expect(startMeshLinkRefresh).toHaveBeenCalledWith('ac-1', false)
    expect(store.refreshTask?.id).toBe('refresh-1')
    store.stopPolling()
    expect('cancelRefresh' in store).toBe(false)
  })
})
