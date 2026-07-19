import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useRailTransitBaseDataStore } from './railTransitBaseData'
import {
  applyRailTransitImport,
  getRailTransitBaseDataEditSession,
  getRailTransitImportPolicies,
  getRailTransitSummary,
  listRailTransitImportChanges,
  listRailTransitImportOperations,
  listDataQualityIssueGroups,
  listRelations,
  listSections,
  listStations,
  listTracksideAps,
  listTrains,
  listVehicleMrs,
  previewRailTransitImport,
  rollbackRailTransitImport,
  saveRailTransitBaseDataChanges,
  validateRailTransitBaseDataChanges,
} from '../api/railTransitBaseData'

vi.mock('../api/railTransitBaseData', () => ({
  applyRailTransitImport: vi.fn(),
  getRailTransitBaseDataEditSession: vi.fn(),
  getRailTransitImportPolicies: vi.fn(),
  getRailTransitSummary: vi.fn(),
  listRailTransitImportChanges: vi.fn(),
  listRailTransitImportOperations: vi.fn(),
  listDataQualityIssueGroups: vi.fn(),
  listRelations: vi.fn(),
  listSections: vi.fn(),
  listStations: vi.fn(),
  listTracksideAps: vi.fn(),
  listTrains: vi.fn(),
  listVehicleMrs: vi.fn(),
  previewRailTransitImport: vi.fn(),
  rollbackRailTransitImport: vi.fn(),
  saveRailTransitBaseDataChanges: vi.fn(),
  validateRailTransitBaseDataChanges: vi.fn(),
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
    for (const mock of [listStations, listSections, listTracksideAps, listTrains, listVehicleMrs, listRelations]) {
      vi.mocked(mock).mockReset().mockResolvedValue(emptyPage)
    }
    vi.mocked(listDataQualityIssueGroups).mockReset().mockResolvedValue({
      ...emptyPage, issue_total: 0, blocking_total: 0, warning_total: 0, info_total: 0, code_counts: {},
    })
    vi.mocked(previewRailTransitImport).mockReset()
    vi.mocked(getRailTransitImportPolicies).mockReset().mockResolvedValue({
      feature_enabled: false, write_enabled: false, copy_write_authorized: false,
      real_write_authorized: false, rollback_enabled: false, write_scope: 'real',
      identity_boundaries: {}, items: [],
    })
    vi.mocked(getRailTransitBaseDataEditSession).mockReset().mockResolvedValue({
      site_id: 'demo', base_revision: 'a'.repeat(64), loaded_at: '', can_write: false, write_scope: 'real',
    })
    vi.mocked(listRailTransitImportOperations).mockReset().mockResolvedValue([])
    vi.mocked(listRailTransitImportChanges).mockReset().mockResolvedValue([])
    vi.mocked(applyRailTransitImport).mockReset()
    vi.mocked(rollbackRailTransitImport).mockReset()
    vi.mocked(saveRailTransitBaseDataChanges).mockReset()
    vi.mocked(validateRailTransitBaseDataChanges).mockReset()
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

  it('stops all polling timers and keeps persistence unauthorized by default', async () => {
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
    await store.refreshImportGovernance()
    expect(store.canApplyImport()).toBe(false)
    expect('deleteAp' in store).toBe(false)
    expect('updateDevice' in store).toBe(false)
    expect(store.editSession?.can_write).toBe(false)
    vi.useRealTimers()
  })

  it('applies only after copy-write authorization and refreshes the audit list', async () => {
    vi.mocked(getRailTransitImportPolicies).mockResolvedValue({
      feature_enabled: true, write_enabled: true, copy_write_authorized: true,
      real_write_authorized: false, rollback_enabled: false, write_scope: 'copy_validation',
      identity_boundaries: {}, items: [],
    })
    vi.mocked(previewRailTransitImport).mockResolvedValue({
      preview_id: '11111111-1111-4111-8111-111111111111', file_name: 'preview.json', file_size: 10,
      template_type: 'json', confidence_score: 100, total_rows: 1, valid_rows: 1, error_count: 0,
      warning_count: 0, rows: [], database_hash: 'a'.repeat(64), preview_expires_at: '',
      write_enabled: true, message: '', merge_plan: {
        plan_id: '11111111-1111-4111-8111-111111111111', site_id: 'demo', source_file_name: 'preview.json',
        source_file_sha256: 'b'.repeat(64), source_type: 'json', created_at: '', database_hash: 'a'.repeat(64),
        preview_expires_at: '', write_enabled: true, items: [], summary: {
          create_count: 1, update_count: 0, unchanged_count: 0, skip_count: 0,
          conflict_count: 0, needs_confirmation_count: 0, blocking_count: 0,
        },
      },
    })
    vi.mocked(applyRailTransitImport).mockResolvedValue({
      operation_id: 'op-1', status: 'APPLIED', created_count: 1, updated_count: 0, skipped_count: 0,
      warning_count: 0, backup_id: 'op-1', database_sha256_before: 'a', database_sha256_after: 'b', audit_id: 'op-1',
    })
    const store = useRailTransitBaseDataStore()
    await store.refreshImportGovernance()
    await store.previewImport(new File(['{}'], 'preview.json'))
    expect(store.canApplyImport()).toBe(true)
    await expect(store.applyImport([])).resolves.toBe('op-1')
    expect(applyRailTransitImport).toHaveBeenCalledOnce()
  })
})
