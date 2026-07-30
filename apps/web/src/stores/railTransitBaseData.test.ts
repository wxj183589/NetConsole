import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiRequestError, getHealth } from '../api/client'
import { useRailTransitBaseDataStore } from './railTransitBaseData'
import {
  applyRailTransitImport,
  getRailTransitBaseDataEditSession,
  getRailTransitImportPolicies,
  getRailTransitSummary,
  getStationSourcePreview,
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
  previewSectionGeneration,
  previewStationTemplate,
  rollbackRailTransitImport,
  saveRailTransitBaseDataChanges,
  validateRailTransitBaseDataChanges,
} from '../api/railTransitBaseData'

vi.mock('../api/railTransitBaseData', () => ({
  applyRailTransitImport: vi.fn(),
  getRailTransitBaseDataEditSession: vi.fn(),
  getRailTransitImportPolicies: vi.fn(),
  getRailTransitSummary: vi.fn(),
  getStationSourcePreview: vi.fn(),
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
  previewSectionGeneration: vi.fn(),
  previewStationTemplate: vi.fn(),
  rollbackRailTransitImport: vi.fn(),
  saveRailTransitBaseDataChanges: vi.fn(),
  validateRailTransitBaseDataChanges: vi.fn(),
}))
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getHealth: vi.fn() }
})

const emptyPage = { items: [], total: 0, page: 1, page_size: 50 }

describe('Rail Transit base data polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getRailTransitSummary).mockReset().mockResolvedValue({
      site_id: 'demo', site_name: '测试局点', line_name: '测试线', project_type: 'PIS', network_type: 'default',
      main_path_code: 'MAIN', increasing_direction_name: '上行', decreasing_direction_name: '下行',
      increasing_direction_line_side: '右线', decreasing_direction_line_side: '左线',
      increasing_direction_leading_end: 'unknown',
      station_source_group_name: '车站', station_source_field: 'station',
      remark: '', created_at: '', updated_at: '', station_count: 0,
      normal_station_count: 0, special_node_count: 0, source_pending_count: 0, source_conflict_count: 0,
      source_stale_count: 0, section_count: 0, ap_count: 0,
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
    vi.mocked(previewSectionGeneration).mockReset()
    vi.mocked(getStationSourcePreview).mockReset().mockResolvedValue({
      site_id: 'demo',
      source_group_name: '车站',
      source_field: 'station',
      group_found: true,
      scanned_device_count: 0,
      empty_station_device_count: 0,
      unique_station_value_count: 0,
      normal_station_count: 0,
      special_node_count: 0,
      create_count: 0,
      match_count: 0,
      conflict_count: 0,
      manual_review_count: 0,
      canonical_match_count: 0,
      recommended_overwrite_count: 0,
      recommended_create_count: 0,
      recommended_merge_count: 0,
      remaining_manual_count: 0,
      warning_count: 0,
      candidates: [],
      issues: [],
    })
    vi.mocked(previewStationTemplate).mockReset().mockResolvedValue({
      valid: true,
      line_metadata: {},
      rows: [],
      section_rows: [],
      section_sheet_present: true,
      create_count: 0,
      update_count: 0,
      unchanged_count: 0,
      conflict_count: 0,
      blocking_count: 0,
      issues: [],
    })
    vi.mocked(getRailTransitImportPolicies).mockReset().mockResolvedValue({
      feature_enabled: false, write_enabled: false, copy_write_authorized: false,
      real_write_authorized: false, rollback_enabled: false, write_scope: 'real',
      identity_boundaries: {}, items: [],
    })
    vi.mocked(getRailTransitBaseDataEditSession).mockReset().mockResolvedValue({
      site_id: 'demo', base_revision: 'a'.repeat(64), loaded_at: '', can_write: false, write_scope: 'real',
      storage_mode: 'persistent', write_denial_code: 'BASE_DATA_WRITE_DISABLED',
      write_denial_reason: '轨道交通基础资料正式写入未启用',
    })
    vi.mocked(listRailTransitImportOperations).mockReset().mockResolvedValue([])
    vi.mocked(listRailTransitImportChanges).mockReset().mockResolvedValue([])
    vi.mocked(applyRailTransitImport).mockReset()
    vi.mocked(rollbackRailTransitImport).mockReset()
    vi.mocked(saveRailTransitBaseDataChanges).mockReset()
    vi.mocked(validateRailTransitBaseDataChanges).mockReset()
    vi.mocked(getHealth).mockReset().mockResolvedValue({
      status: 'ok',
      version: 'test',
      build_id: 'test',
    })
    vi.stubGlobal('window', { setTimeout, clearTimeout })
  })

  it('updates stations and sections when data quality issues fail', async () => {
    const station = { id: 'station:1', name: '站点A' }
    const section = { id: 'section:1', name: '站点A-站点B' }
    vi.mocked(listStations).mockResolvedValue({
      ...emptyPage,
      items: [station],
      total: 1,
    } as never)
    vi.mocked(listSections).mockResolvedValue({
      ...emptyPage,
      items: [section],
      total: 1,
    } as never)
    vi.mocked(listDataQualityIssueGroups).mockRejectedValue(
      new ApiRequestError('数据质量服务不可用', 503, 'ISSUES_UNAVAILABLE'),
    )
    const store = useRailTransitBaseDataStore()

    await store.refreshStatic()

    expect(store.stations).toEqual([station])
    expect(store.sections).toEqual([section])
    expect(store.staticError.map((item) => item.label)).toEqual(['数据质量问题'])
    expect(store.error).toBe('部分基础资料刷新失败，已保留最后成功数据。')
    expect(store.backendOffline).toBe(false)
  })

  it('updates APs, trains and relations when vehicle MR loading fails', async () => {
    const ap = { id: 'ap:1', name: 'AP-A' }
    const train = { id: 'train:1', train_no: 'T001' }
    const relation = { id: 'relation:1' }
    vi.mocked(listTracksideAps).mockResolvedValue({
      ...emptyPage,
      items: [ap],
      total: 1,
    } as never)
    vi.mocked(listTrains).mockResolvedValue({
      ...emptyPage,
      items: [train],
      total: 1,
    } as never)
    vi.mocked(listRelations).mockResolvedValue({
      ...emptyPage,
      items: [relation],
      total: 1,
    } as never)
    vi.mocked(listVehicleMrs).mockRejectedValue(new Error('MR 请求失败'))
    const store = useRailTransitBaseDataStore()

    await store.refreshRuntime()

    expect(store.aps).toEqual([ap])
    expect(store.trains).toEqual([train])
    expect(store.relations).toEqual([relation])
    expect(store.runtimeError.map((item) => item.label)).toEqual(['车载 MR'])
  })

  it('keeps last successful data and clears only the recovered endpoint error', async () => {
    const previousMr = { id: 'mr:old', name: 'MR-OLD' }
    vi.mocked(listVehicleMrs).mockResolvedValueOnce({
      ...emptyPage,
      items: [previousMr],
      total: 1,
    } as never)
    const store = useRailTransitBaseDataStore()
    await store.refreshRuntime()

    vi.mocked(listVehicleMrs).mockRejectedValueOnce(new Error('MR 瞬时失败'))
    vi.mocked(listRelations).mockRejectedValue(new Error('关系持续失败'))
    await store.refreshRuntime()
    expect(store.mrs).toEqual([previousMr])
    expect(store.runtimeError.map((item) => item.label)).toEqual([
      '车载 MR',
      '关联运行状态',
    ])

    const currentMr = { id: 'mr:new', name: 'MR-NEW' }
    vi.mocked(listVehicleMrs).mockResolvedValue({
      ...emptyPage,
      items: [currentMr],
      total: 1,
    } as never)
    await store.refreshRuntime()

    expect(store.mrs).toEqual([currentMr])
    expect(store.runtimeError.map((item) => item.label)).toEqual(['关联运行状态'])
    expect(store.error).toContain('保留最后成功数据')
  })

  it('keeps Backend online semantics for one failed business endpoint', async () => {
    vi.mocked(listVehicleMrs).mockRejectedValue(new Error('connection reset'))
    const store = useRailTransitBaseDataStore()

    await store.manualRefresh()

    expect(store.error).toBe('部分基础资料刷新失败，已保留最后成功数据。')
    expect(store.error).not.toContain('Backend 连接中断')
    expect(store.backendOffline).toBe(false)
    expect(getHealth).not.toHaveBeenCalled()
  })

  it('reports Backend interruption only after persistent core failures and a failed health probe', async () => {
    vi.mocked(getRailTransitSummary).mockRejectedValue(new Error('connection reset'))
    vi.mocked(listStations).mockRejectedValue(new Error('connection reset'))
    vi.mocked(getHealth).mockRejectedValue(new Error('connection reset'))
    const store = useRailTransitBaseDataStore()

    await store.manualRefresh()
    await store.manualRefresh()
    expect(store.backendOffline).toBe(false)
    await store.manualRefresh()

    expect(getHealth).toHaveBeenCalledOnce()
    expect(store.backendOffline).toBe(true)
    expect(store.error).toBe('Backend 连接中断，请重试。')
  })

  it('retains structured API error diagnostics', async () => {
    vi.mocked(listVehicleMrs).mockRejectedValue(new ApiRequestError(
      '读取车载 MR 失败',
      503,
      'CONNECTION_RESET',
      {
        path: '/api/custom/mrs',
        request_id: 'request-123',
        original_message: 'socket hang up',
      },
    ))
    const store = useRailTransitBaseDataStore()

    await store.refreshRuntime()

    expect(store.runtimeError[0]).toMatchObject({
      label: '车载 MR',
      path: '/api/custom/mrs',
      code: 'CONNECTION_RESET',
      status: 503,
      requestId: 'request-123',
      originalMessage: 'socket hang up',
    })
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
          total_rows: 1, importable_count: 1,
          create_count: 1, update_count: 0, unchanged_count: 0, skip_count: 0,
          conflict_count: 0, invalid_count: 0, warning_count: 0, unmatched_fit_ap_count: 0,
          needs_confirmation_count: 0, blocking_count: 0,
        },
      },
    })
    vi.mocked(applyRailTransitImport).mockResolvedValue({
      total_rows: 1, imported_rows: 1, created_rows: 1, updated_rows: 0, unchanged_rows: 0,
      warning_rows: 0, skipped_conflict_rows: 0, skipped_invalid_rows: 0,
      unmatched_fit_ap_rows: 0, issues: [],
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

  it('stores station source and template previews without invoking save', async () => {
    vi.mocked(getStationSourcePreview).mockResolvedValue({
      site_id: 'demo',
      source_group_name: '车站',
      source_field: 'station',
      group_found: true,
      scanned_device_count: 2,
      empty_station_device_count: 0,
      unique_station_value_count: 1,
      normal_station_count: 1,
      special_node_count: 0,
      create_count: 1,
      match_count: 0,
      conflict_count: 0,
      manual_review_count: 0,
      canonical_match_count: 0,
      recommended_overwrite_count: 0,
      recommended_create_count: 1,
      recommended_merge_count: 0,
      remaining_manual_count: 0,
      warning_count: 0,
      candidates: [{
        candidate_id: 'station-source:wuxiang',
        source_station_value: '32-五乡',
        source_station_key: '五乡',
        source_order_text: '32',
        source_order: 32,
        code: '32',
        name: '五乡',
        canonical_name: '五乡',
        order_parse_method: 'explicit_delimiter',
        parse_confidence: 'high',
        parse_warning: '',
        canonical_station_name: '五乡',
        node_type: 'station',
        path_code: 'MAIN',
        sort_order: 32,
        participates_in_direction: true,
        source_device_count: 2,
        match_status: 'create',
        matched_station_id: '',
        matched_station_name: '',
        matched_station_ids: [],
        matched_station_names: [],
        match_basis: 'new_station',
        suggested_action: '新增',
        processing_strategy: 'create',
        processing_options: ['create', 'ignore', 'manual_target'],
        cleanup_name_prefix_recommended: false,
        proposed_station: {
          id: 'new:source:wuxiang',
          node_uid: 'node-wuxiang',
          name: '五乡',
          code: '32',
          line_name: '',
          sort_order: 32,
          ap_count: 0,
          section_count: 0,
          mileage_min: null,
          mileage_max: null,
          remark: '',
          source_station_value: '32-五乡',
          source_station_key: '五乡',
          source_order_text: '32',
          source_order: 32,
          canonical_station_name: '五乡',
          node_type: 'station',
          path_code: 'MAIN',
          participates_in_direction: true,
          structure_type: 'unknown',
          platform_layout: 'unknown',
          center_mileage_text: '',
          center_mileage_m: null,
          is_line_terminal: false,
          is_service_terminal: false,
          turnback_capable: false,
          turnback_type: 'none',
          track_facilities: [],
          turnback_direction: 'none',
          terminal_extension_enabled: false,
          terminal_endpoint_label: '端点',
          terminal_extension_distance_m: null,
          terminal_endpoint_mileage_text: '',
          enabled: true,
          source_kind: 'device_station_field',
          source_device_count: 2,
          source_sync_status: 'matched',
          source_last_seen_at: '',
        },
        issues: [],
      }],
      issues: [],
    })
    vi.mocked(previewStationTemplate).mockResolvedValue({
      valid: true,
      line_metadata: { station_source_field: 'station' },
      rows: [{
        row_number: 2,
        source_station_value: '33-宝幢',
        source_station_key: '33-宝幢',
        code: '33',
        name: '宝幢',
        node_type: 'station',
        path_code: 'MAIN',
        sort_order: 33,
        participates_in_direction: true,
        proposed_station: null,
        action: 'create',
        valid: true,
        issues: [],
      }],
      section_rows: [],
      section_sheet_present: true,
      create_count: 1,
      update_count: 0,
      unchanged_count: 0,
      conflict_count: 0,
      blocking_count: 0,
      issues: [],
    })
    const store = useRailTransitBaseDataStore()

    await expect(store.refreshStationSourcePreview()).resolves.toMatchObject({ unique_station_value_count: 1 })
    await expect(store.previewStationTemplateFile(new File(['xlsx'], 'stations.xlsx'))).resolves.toMatchObject({ create_count: 1 })

    expect(store.stationSourcePreview?.candidates[0].name).toBe('五乡')
    expect(store.stationTemplatePreview?.rows[0].name).toBe('宝幢')
    expect(saveRailTransitBaseDataChanges).not.toHaveBeenCalled()
  })

  it('forwards the current draft to section generation preview without saving', async () => {
    vi.mocked(previewSectionGeneration).mockResolvedValue({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      generated_sections: [],
      create_count: 0,
      update_count: 0,
      unchanged_count: 0,
      conflict_count: 0,
      stale_count: 0,
      blocking_count: 0,
      issues: [],
    })
    const store = useRailTransitBaseDataStore()

    await expect(store.previewSectionsFromDraft(
      {
        main_path_code: 'MAIN',
        increasing_direction_name: '上行',
        decreasing_direction_name: '下行',
        increasing_direction_line_side: '右线',
        decreasing_direction_line_side: '左线',
      },
      [],
      [],
    )).resolves.toMatchObject({ site_id: 'demo', generated_sections: [] })

    expect(previewSectionGeneration).toHaveBeenCalledWith({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      line_metadata: {
        main_path_code: 'MAIN',
        increasing_direction_name: '上行',
        decreasing_direction_name: '下行',
        increasing_direction_line_side: '右线',
        decreasing_direction_line_side: '左线',
      },
      stations: [],
      current_sections: [],
    })
    expect(saveRailTransitBaseDataChanges).not.toHaveBeenCalled()
  })
})
