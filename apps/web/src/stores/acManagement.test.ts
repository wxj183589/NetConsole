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
import { deleteAcFitAps, getAcWebTask, importAcFitApMetadata, recoverAcWebTasks, saveAcFitApMetadata, startAcResourceRefresh } from '../api/acWebParity'

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
  importAcFitApMetadata: vi.fn(),
  saveAcFitApMetadata: vi.fn(),
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
    vi.mocked(importAcFitApMetadata).mockReset()
    vi.mocked(saveAcFitApMetadata).mockReset()
    vi.mocked(startAcResourceRefresh).mockReset()
    vi.mocked(getAcWebTask).mockReset()
    vi.stubGlobal('window', { setTimeout, clearTimeout, localStorage: { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() } })
  })

  it('uses switch and logical interface topology as the default AP order', () => {
    const store = useAcManagementStore()

    expect(store.filters.sort_by).toBe('topology')
    expect(store.filters.sort_order).toBe('asc')
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

  it('keeps successful partial refresh data and its AP error independently', async () => {
    const store = useAcManagementStore()
    store.aps = [{ id: 'ap-existing', name: 'existing' }] as never
    vi.mocked(listAcAps).mockRejectedValue(new Error('AP refresh unavailable'))
    await store.refreshAps()
    await store.refreshAps()

    vi.mocked(listAcConfigSnapshots).mockResolvedValue({
      items: [{ id: 1 }] as never,
      total: 1,
      page: 1,
      page_size: 30,
    })
    await store.manualRefresh()

    expect(store.aps).toEqual([{ id: 'ap-existing', name: 'existing' }])
    expect(store.snapshots).toEqual([{ id: 1 }])
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

  it('starts a single-AP optical refresh without changing refresh task semantics', async () => {
    vi.mocked(startAcResourceRefresh).mockResolvedValue({
      task_id: 'task-optical-one', action: 'ac_fit_ap_optical_refresh', status: 'QUEUED',
      progress: 0, stage: 'queued', current: 0, total: 0,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    })
    const store = useAcManagementStore()
    store.filters.ac_id = 'ac-1'

    await store.startApOpticalRefresh('ap-1')

    expect(startAcResourceRefresh).toHaveBeenCalledWith('optical', 'ac-1', 'ap-1')
  })

  it('tracks AC configuration actions in an independent recoverable task slot', async () => {
    vi.mocked(getAcWebTask).mockResolvedValue({
      task_id: 'action-1', action: 'ac_command_action_execute', status: 'RUNNING',
      progress: 10, stage: 'connect', current: 0, total: 1,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    })
    const store = useAcManagementStore()

    await store.trackActionTask('action-1')

    expect(store.actionTask?.task_id).toBe('action-1')
    expect(store.refreshTask).toBeNull()
    expect(window.localStorage.setItem).toHaveBeenCalledWith('netconsole.ac.active-action-task', 'action-1')
    store.stopPolling()
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

  it('starts FIT-AP metadata import through the persistent task API', async () => {
    vi.mocked(importAcFitApMetadata).mockResolvedValue({
      task_id: 'task-import', action: 'fit_ap_metadata_import', status: 'QUEUED',
      progress: 0, stage: 'queued', current: 0, total: 0,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    })
    const file = new File(['metadata'], 'metadata.csv', { type: 'text/csv' })
    const store = useAcManagementStore()

    await store.startFitApMetadataImport(file)

    expect(importAcFitApMetadata).toHaveBeenCalledWith(file)
    expect(store.refreshTask?.task_id).toBe('task-import')
  })

  it('saves selected FIT-AP metadata through the persistent task API', async () => {
    vi.mocked(saveAcFitApMetadata).mockResolvedValue({
      task_id: 'task-save', action: 'fit_ap_metadata_save', status: 'QUEUED',
      progress: 0, stage: 'queued', current: 0, total: 0,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    })
    const store = useAcManagementStore()
    store.filters.ac_id = 'ac-1'
    store.selected = { ap: { id: 'ap-1' } } as never
    const metadata = { site_name: 'Web站', mileage: 'ZDK1+200', location_note: '站台', direction: '上行' }

    await store.startFitApMetadataSave(metadata)

    expect(saveAcFitApMetadata).toHaveBeenCalledWith('ac-1', 'ap-1', metadata)
    expect(store.refreshTask?.task_id).toBe('task-save')
  })

  it('recovers an active FIT-AP metadata save after the page restarts', async () => {
    vi.mocked(recoverAcWebTasks).mockResolvedValue([{
      task_id: 'task-save-recovered', action: 'fit_ap_metadata_save', status: 'RUNNING',
      progress: 50, stage: 'running', current: 0, total: 0,
      artifact_id: '', available: false, sha256: '', size_bytes: 0,
      message: '', error_message: '', result_summary: {},
    }])
    const store = useAcManagementStore()

    await store.recoverRefreshTask()

    expect(store.refreshTask?.task_id).toBe('task-save-recovered')
    store.stopPolling()
  })
})
