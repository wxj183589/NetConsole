import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAcManagementStore } from './acManagement'
import {
  getAcApDetail,
  getAcConfigDiff,
  getAcConfigSnapshot,
  getAcSummary,
  listAcAps,
  listAcConfigSnapshots,
} from '../api/acManagement'

vi.mock('../api/acManagement', () => ({
  getAcApDetail: vi.fn(),
  getAcConfigDiff: vi.fn(),
  getAcConfigSnapshot: vi.fn(),
  getAcSummary: vi.fn(),
  listAcAps: vi.fn(),
  listAcConfigSnapshots: vi.fn(),
}))

describe('AC Management polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getAcSummary).mockReset().mockResolvedValue({
      site_id: 'demo', acs: [], ap_total: 0, online_aps: 0, offline_aps: 0,
      unauthenticated_aps: 0, radio_total: 0, optical_anomalies: 0, updated_at: '', message: '',
    })
    vi.mocked(listAcAps).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    vi.mocked(listAcConfigSnapshots).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30 })
    vi.mocked(getAcApDetail).mockReset()
    vi.mocked(getAcConfigDiff).mockReset()
    vi.mocked(getAcConfigSnapshot).mockReset()
    vi.stubGlobal('window', { setTimeout, clearTimeout })
  })

  it('does not overlap AP requests and reports after three failures', async () => {
    let rejectRequest: ((reason?: unknown) => void) | undefined
    vi.mocked(listAcAps).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject }))
    const store = useAcManagementStore()
    const first = store.refreshAps()
    void store.refreshAps()
    expect(listAcAps).toHaveBeenCalledOnce()
    rejectRequest?.(new Error('offline'))
    await first

    vi.mocked(listAcAps).mockRejectedValue(new Error('offline'))
    await store.refreshAps()
    await store.refreshAps()
    expect(store.error).toContain('AC 数据刷新失败')
  })

  it('stops every timer and exposes no write operation', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    const store = useAcManagementStore()
    store.startPolling()
    await vi.runAllTicks()
    await Promise.resolve()
    await Promise.resolve()
    const calls = vi.mocked(listAcAps).mock.calls.length
    store.stopPolling()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(listAcAps).toHaveBeenCalledTimes(calls)
    expect('collect' in store).toBe(false)
    expect('save' in store).toBe(false)
    expect('deleteAp' in store).toBe(false)
    vi.useRealTimers()
  })
})
