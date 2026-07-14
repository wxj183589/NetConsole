import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useRailTransitBaseDataStore } from './railTransitBaseData'
import {
  getRailTransitSummary,
  listDataQualityIssues,
  listRelations,
  listSections,
  listStations,
  listTracksideAps,
  listTrains,
  listVehicleMrs,
  previewRailTransitImport,
} from '../api/railTransitBaseData'

vi.mock('../api/railTransitBaseData', () => ({
  getRailTransitSummary: vi.fn(),
  listDataQualityIssues: vi.fn(),
  listRelations: vi.fn(),
  listSections: vi.fn(),
  listStations: vi.fn(),
  listTracksideAps: vi.fn(),
  listTrains: vi.fn(),
  listVehicleMrs: vi.fn(),
  previewRailTransitImport: vi.fn(),
}))

const emptyPage = { items: [], total: 0, page: 1, page_size: 50 }

describe('Rail Transit base data polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getRailTransitSummary).mockReset().mockResolvedValue({
      site_id: 'demo', site_name: '测试局点', line_name: '测试线', project_type: 'PIS', network_type: 'default',
      remark: '', created_at: '', updated_at: '', station_count: 0, section_count: 0, ap_count: 0,
      train_count: 0, mr_count: 0, missing_location_ap_count: 0, invalid_mileage_count: 0,
      duplicate_ap_mac_count: 0, duplicate_static_ip_count: 0, unbound_mr_count: 0, issue_count: 0, message: '',
    })
    for (const mock of [listStations, listSections, listTracksideAps, listTrains, listVehicleMrs, listDataQualityIssues, listRelations]) {
      vi.mocked(mock).mockReset().mockResolvedValue(emptyPage)
    }
    vi.mocked(previewRailTransitImport).mockReset()
    vi.stubGlobal('window', { setTimeout, clearTimeout })
  })

  it('does not overlap summary requests and retains last data after repeated failures', async () => {
    let rejectRequest: ((reason?: unknown) => void) | undefined
    vi.mocked(getRailTransitSummary).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject }))
    const store = useRailTransitBaseDataStore()
    const first = store.refreshSummary()
    void store.refreshSummary()
    expect(getRailTransitSummary).toHaveBeenCalledOnce()
    rejectRequest?.(new Error('offline'))
    await first
    vi.mocked(getRailTransitSummary).mockRejectedValue(new Error('offline'))
    await store.refreshSummary(); await store.refreshSummary()
    expect(store.error).toContain('保留最后成功数据')
  })

  it('stops all polling timers and exposes preview but no persistence action', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    const store = useRailTransitBaseDataStore()
    store.startPolling()
    await vi.runAllTicks()
    const calls = vi.mocked(getRailTransitSummary).mock.calls.length
    store.stopPolling()
    await vi.advanceTimersByTimeAsync(180_000)
    expect(getRailTransitSummary).toHaveBeenCalledTimes(calls)
    expect('previewImport' in store).toBe(true)
    expect('commitImport' in store).toBe(false)
    expect('deleteAp' in store).toBe(false)
    expect('updateDevice' in store).toBe(false)
    vi.useRealTimers()
  })
})
