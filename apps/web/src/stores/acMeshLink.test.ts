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
} from '../api/acMeshLink'

vi.mock('../api/acMeshLink', () => ({
  getMeshLinkSummary: vi.fn(),
  getMeshMrDetail: vi.fn(),
  getMeshRawTail: vi.fn(),
  listMeshLinks: vi.fn(),
  listMeshMrs: vi.fn(),
  listMeshSnapshots: vi.fn(),
}))

const emptyPage = { items: [], total: 0, page: 1, page_size: 50 }

describe('AC Mesh-Link read-only polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getMeshLinkSummary).mockReset().mockResolvedValue({
      site_id: 'demo', registered_mrs: 0, online_mrs: 0, offline_mrs: 0,
      stale_mrs: 0, unknown_mrs: 0, active_links: 0, link_total: 0,
      unmatched_links: 0, offline_ap_links: 0, updated_at: '', age_seconds: null,
      data_status: 'no_data', source_type: 'vehicle_mr_online_snapshot', message: '',
    })
    vi.mocked(listMeshMrs).mockReset().mockResolvedValue(emptyPage)
    vi.mocked(listMeshLinks).mockReset().mockResolvedValue(emptyPage)
    vi.mocked(listMeshSnapshots).mockReset().mockResolvedValue({ ...emptyPage, page_size: 30 })
    vi.mocked(getMeshMrDetail).mockReset()
    vi.mocked(getMeshRawTail).mockReset().mockResolvedValue({
      snapshot_id: null, available: false, lines: [], line_count: 0,
      source_reference: '', updated_at: '', message: '暂无原始数据',
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
    expect('startTask' in store).toBe(false)
    expect('stopTask' in store).toBe(false)
    vi.useRealTimers()
  })
})
