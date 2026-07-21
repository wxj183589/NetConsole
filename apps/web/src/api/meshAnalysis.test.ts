import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  applyMeshBundleImport, createMeshProfile, deleteMeshArtifact, exportMeshLinkDetails, getMeshActivePathChart, getMeshAnalysisParamsTemplate,
  getMeshCounterDeltas, getMeshPeerSegmentChart, getMeshRateSeries, listMeshActiveBuildOrder, listMeshProfiles, listMeshSwitchEvents,
  previewMeshBundle, saveMeshAnalysisParams,
} from './meshAnalysis'

describe('Mesh profile API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the independent Mesh profile boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await listMeshProfiles()
    await createMeshProfile({ display_name: '列车01-MR-CT', linked_mr_id: 'mr-1', notes: 'fixture' })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/mesh-analysis/profiles',
      '/api/rail-transit/mesh-analysis/profiles',
    ])
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ display_name: '列车01-MR-CT', linked_mr_id: 'mr-1', notes: 'fixture' })
  })

  it('previews ZIP as multipart and applies only preview mappings', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ preview_id: 'preview-token' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)
    const archive = new File(['zip-bytes'], 'mesh.zip', { type: 'application/zip' })

    await previewMeshBundle(archive)
    await applyMeshBundleImport({
      preview_id: 'preview-token',
      mappings: [{ member_id: '001-ctmeshlog.log', train_number: '01', role: 'CT', profile_id: 'profile-1' }],
      explicit_confirmation: true,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/rail-transit/mesh-analysis/bundles/preview')
    expect(fetchMock.mock.calls[0][1].body).toBeInstanceOf(FormData)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/rail-transit/mesh-analysis/bundles/import')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      preview_id: 'preview-token',
      mappings: [{ member_id: '001-ctmeshlog.log', train_number: '01', role: 'CT', profile_id: 'profile-1' }],
      explicit_confirmation: true,
    })
  })

  it('queries Rate, counter deltas and switch events through formal Query APIs', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, downsampled: false }) })
    vi.stubGlobal('fetch', fetchMock)

    await getMeshRateSeries('session/1', { time_from: '2026-07-20T10:00:00.123Z', time_to: '2026-07-20T11:00:00.123Z', max_points: 2000 })
    await getMeshCounterDeltas('session/1', { max_points: 2000 })
    await listMeshSwitchEvents('session/1', { page: 1, page_size: 500 })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/rate-series?time_from=2026-07-20T10%3A00%3A00.123Z&time_to=2026-07-20T11%3A00%3A00.123Z&max_points=2000',
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/counter-deltas?max_points=2000',
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/switch-events?page=1&page_size=500',
    ])
  })

  it('encodes build order and chart query contracts without client-side analysis', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0 }) })
    vi.stubGlobal('fetch', fetchMock)

    await listMeshActiveBuildOrder('session/1', { page: 2, page_size: 500, sort_order: 'desc', radio: 1, pingpong_only: true })
    await getMeshActivePathChart('session/1', { radio: 1, time_from: '2026-07-20 10:00:00.123', time_to: '2026-07-20 10:02:00.456', max_points: 600 })
    await getMeshPeerSegmentChart('session/1', { anchor_link_id: 42, time_from: '2026-07-20 10:00:00.123', time_to: '2026-07-20 10:02:00.456', max_points: 300, all_visits: true })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/active-build-order?page=2&page_size=500&sort_order=desc&radio=1&pingpong_only=true',
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/charts/active-path?radio=1&time_from=2026-07-20+10%3A00%3A00.123&time_to=2026-07-20+10%3A02%3A00.456&max_points=600',
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/charts/peer-segment?anchor_link_id=42&time_from=2026-07-20+10%3A00%3A00.123&time_to=2026-07-20+10%3A02%3A00.456&max_points=300&all_visits=true',
    ])
  })

  it('starts the parameterized link detail export for a selected source', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)
    const params = {
      link_time_window: 4000,
      link_switch_threshold: 10,
      link_hold_rssi: 22,
      link_establish_threshold: 4,
      main_link_switch_time_ms: 4000,
      short_link_tolerance_ms: 500,
      pingpong_tolerance_ms: 500,
      pingpong_return_window_ms: 500,
      merge_same_physical_ap_dual_radio: true,
      include_log_boundary_segments: false,
      sample_interval_ms: null,
      service_type: 'PIS' as const,
      wifi_type: 'WiFi6' as const,
    }

    await exportMeshLinkDetails('mr-id:1', 7, params)

    expect(fetchMock.mock.calls[0][0]).toBe('/api/rail-transit/mesh-analysis/sessions/mr-id%3A1/link-details/export')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ source_file_id: 7, analysis_params_override: params })
  })

  it('uses typed site parameter and derived artifact delete endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const params = {
      link_time_window: 4000,
      link_switch_threshold: 10,
      link_hold_rssi: 22,
      link_establish_threshold: 4,
      main_link_switch_time_ms: 4000,
      short_link_tolerance_ms: 500,
      pingpong_tolerance_ms: 500,
      pingpong_return_window_ms: 500,
      merge_same_physical_ap_dual_radio: true,
      include_log_boundary_segments: false,
      sample_interval_ms: null,
      service_type: 'CBTC' as const,
      wifi_type: 'WiFi6' as const,
    }

    await getMeshAnalysisParamsTemplate('CBTC')
    await saveMeshAnalysisParams(params)
    await deleteMeshArtifact('session/1', 'artifact/1')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/mesh-analysis/analysis-params/templates/CBTC',
      '/api/rail-transit/mesh-analysis/analysis-params',
      '/api/rail-transit/mesh-analysis/sessions/session%2F1/artifacts/artifact%2F1',
    ])
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PUT' })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ params })
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'DELETE' })
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ explicit_confirmation: true })
  })
})
