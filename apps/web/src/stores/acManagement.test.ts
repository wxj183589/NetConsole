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
import { deleteAcFitAps, recoverAcWebTasks, startAcResourceRefresh } from '../api/acWebParity'

vi.mock('../api/acManagement', () => ({
  getAcApDetail: vi.fn(),
  getAcConfigDiff: vi.fn(),
  getAcConfigSnapshot: vi.fn(),
  getAcSummary: vi.fn(),
  listAcAps: vi.fn(),
  listAcConfigSnapshots: vi.fn(),
}))
vi.mock('../api/acWebParity', () => ({
  cancelAcWebTask: vi.fn(),
  deleteAcFitAps: vi.fn(),
  getAcWebTask: vi.fn(),
  recoverAcWebTasks: vi.fn(),
  startAcResourceRefresh: vi.fn(),
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
    vi.mocked(recoverAcWebTasks).mockReset().mockResolvedValue([])
    vi.mocked(deleteAcFitAps).mockReset()
    vi.mocked(startAcResourceRefresh).mockReset()
    vi.stubGlobal('window', { setTimeout, clearTimeout, localStorage: { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() } })
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

  it('stops every timer and exposes the approved resource operations', async () => {
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
    expect('startFitApRefresh' in store).toBe(true)
    expect('save' in store).toBe(false)
    expect('startFitApDelete' in store).toBe(true)
    vi.useRealTimers()
  })

  it('starts the fixed FIT-AP collection task for the selected AC', async () => {
    vi.mocked(startAcResourceRefresh).mockResolvedValue({
      task_id: 'task-fit-ap', action: 'ac_fit_ap_resources_refresh', status: 'QUEUED',
      progress: 0, stage: 'queued', current: 0, total: 0,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    })
    const store = useAcManagementStore()
    store.filters.ac_id = 'ac-1'

    await store.startFitApRefresh()

    expect(startAcResourceRefresh).toHaveBeenCalledWith('fit-ap', 'ac-1', '')
    expect(store.refreshTask?.task_id).toBe('task-fit-ap')
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'netconsole.ac.active-task',
      'task-fit-ap',
    )
  })

  it('starts confirmed FIT-AP batch deletion through the persistent task API', async () => {
    vi.mocked(deleteAcFitAps).mockResolvedValue({
      task_id: 'task-delete', action: 'ac_fit_ap_delete_many', status: 'QUEUED',
      progress: 0, stage: 'queued', current: 0, total: 0,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    })
    const store = useAcManagementStore()
    store.filters.ac_id = 'ac-1'

    await store.startFitApDelete(['ap-1', 'ap-2'])

    expect(deleteAcFitAps).toHaveBeenCalledWith('ac-1', ['ap-1', 'ap-2'])
    expect(store.refreshTask?.task_id).toBe('task-delete')
  })
})
