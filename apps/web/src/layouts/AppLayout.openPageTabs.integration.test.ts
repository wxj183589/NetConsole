// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import {
  createMemoryHistory,
  createRouter,
} from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceStore } from '../stores/workspace'

const counters = vi.hoisted(() => ({
  activeChartRequests: vi.fn(),
  cacheBuilds: vi.fn(),
  cacheDisposals: vi.fn(),
  chartDisposals: vi.fn(),
  chartInits: vi.fn(),
  sessionRequests: vi.fn(),
  tracksideChartRequests: vi.fn(),
}))
const sessionRequestControl = vi.hoisted(() => ({
  deferred: false,
  pending: new Map<string, { resolve: () => void; signal?: AbortSignal }>(),
}))

const session = {
  session_id: 'session-tabs-integration',
  site_id: 'site-test',
  analysis_time: '2026-07-24 14:30:00',
  train_name: '列车06',
  mr_name: 'MR-CT',
  mr_role: 'CT',
  source_type: 'meshlog',
  original_filename: '06-MR-CT.log',
  raw_log_count: 1,
  link_record_count: 2,
  active_link_count: 1,
  standby_link_count: 1,
  event_count: 0,
  data_integrity: 'complete',
  analysis_status: 'ready',
  parsed_status: 'ready' as const,
  parsed_message: '',
  schema_version: 'meshlog_compact_v3_tagged_samples',
  available_capabilities: [],
  missing_capabilities: [],
  warning_count: 0,
  report_count: 0,
  first_sample_time: '2026-07-24 14:23:20.000',
  last_sample_time: '2026-07-24 14:25:00.000',
}
const secondSession = {
  ...session,
  session_id: 'session-tabs-second',
  analysis_time: '2026-07-24 14:31:00',
  train_name: '列车34',
  mr_name: 'MR-CW',
  original_filename: '34-MR-CW.log',
}

function sessionDetail(selectedSession = session) {
  return {
    session: selectedSession,
    analysis_params: analysisParams,
    available_radios: [1],
    warnings: [],
    sources: [{
      source_file_id: 1,
      source_action_id: 'source-action-1',
      source_type: 'raw',
      name: selectedSession.original_filename,
      exists: true,
      size_bytes: 1024,
      modified_at: null,
      compressed: false,
      tail_available: true,
      recoverable: true,
      recovery_source: '',
      missing_reason: '',
      rebuild_capability: 'ready',
      package_name: '',
      package_sha256: '',
      bundle_member_id: '',
    }],
  }
}

const analysisParams = {
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

const chartPoint = {
  link_id: 1,
  timestamp: '2026-07-24 14:23:20.000',
  timestamp_tag: null,
  source_file_id: 1,
  local_radio: 1,
  link_state: 'ACTIVE',
  peer_mac: '00:00:00:00:00:01',
  peer_ap_name: 'AP-01',
  peer_ap_mac: '00:00:00:00:10:01',
  peer_radio: '1',
  peer_radio_mac: '00:00:00:00:20:01',
  station: '测试站',
  section: null,
  local_rssi: 36,
  peer_rssi: 34,
  local_signal: -54,
  peer_signal: -56,
  local_tx_busy: 10,
  peer_tx_busy: 12,
  local_rx_busy: 8,
  peer_rx_busy: 9,
  is_switch: false,
  is_anomaly: false,
  gap_before: false,
  backups: [],
}

const activeChart = {
  mode: 'active_path' as const,
  anchor: null,
  points: [chartPoint],
  events: [],
  location_segments: [],
  total_points: 1,
  returned_points: 1,
  downsampled: false,
  requested_max_points: 600,
  effective_max_points: 600,
  downsample_warning: null,
  summary: {
    current_peer_mac: chartPoint.peer_mac,
    current_peer_ap_name: chartPoint.peer_ap_name,
    current_radio: 1,
    earliest_sample_time: session.first_sample_time,
    latest_sample_time: session.last_sample_time,
    first_sample_time: session.first_sample_time,
    last_sample_time: session.last_sample_time,
    sample_count: 1,
    active_count: 1,
    standby_context_count: 1,
    switch_count: 0,
    estimated_interval_seconds: 1,
    continuity_gap_seconds: 5,
  },
  time_from: null,
  time_to: null,
  requested_time_from: null,
  requested_time_to: null,
  effective_time_from: session.first_sample_time,
  effective_time_to: session.last_sample_time,
  first_sample_time: session.first_sample_time,
  last_sample_time: session.last_sample_time,
  total_points_in_range: 1,
}

const tracksideChart = {
  source_id: session.session_id,
  radio: 1,
  time_range: { start: session.first_sample_time, end: session.last_sample_time },
  series: [{
    series_id: 'trackside-ap-01',
    peer_name: 'AP-01',
    peer_mac: chartPoint.peer_mac,
    ap_mac: chartPoint.peer_ap_mac,
    radio: 1,
    peer_radio_mac: chartPoint.peer_radio_mac,
    station: '测试站',
    section: null,
    roles_present: ['ACTIVE' as const],
    data_source: 'fixture',
    total_points: 1,
    returned_points: 1,
    points: [{
      timestamp: chartPoint.timestamp,
      timestamp_tag: '',
      source_file_id: 1,
      link_id: 1,
      sample_id: 1,
      local_radio: 1,
      role: 'ACTIVE' as const,
      peer_mac: chartPoint.peer_mac,
      peer_ap_name: chartPoint.peer_ap_name,
      peer_ap_mac: chartPoint.peer_ap_mac,
      peer_radio: '1',
      peer_radio_mac: chartPoint.peer_radio_mac,
      station: '测试站',
      section: null,
      peer_rssi: 34,
      local_rssi: 36,
      peer_signal: -56,
      local_signal: -54,
      run_id: 'run-1',
      segment_duration_seconds: 100,
      data_source: 'fixture',
    }],
  }],
  events: [],
  warnings: [],
  estimated_interval_seconds: 1,
  continuity_gap_seconds: 5,
  total_series: 1,
  returned_series: 1,
  total_points: 1,
  returned_points: 1,
  total_frames: 1,
  returned_frames: 1,
  total_link_points: 1,
  returned_link_points: 1,
  total_link_runs: 1,
  active_link_points: 1,
  standby_link_points: 0,
  returned_active_link_points: 1,
  returned_standby_link_points: 0,
  role_switch_count: 0,
  skipped_missing_signal_points: 0,
  skipped_missing_identity_points: 0,
  downsampled: false,
  requested_max_frames: 600,
  effective_max_frames: 600,
  requested_max_points: 600,
  effective_max_points: 600,
  top_n: 0,
  included_roles: ['ACTIVE' as const],
  include_standby: true,
}

vi.mock('../api/client', () => ({
  getHealth: vi.fn(async () => ({ status: 'ok', version: '1.4.3', build_id: 'test' })),
  getWebBuildMeta: vi.fn(async () => ({ build_id: 'test' })),
}))

vi.mock('../features', () => ({
  isFeatureEnabled: () => true,
  isFeatureVisible: () => true,
  loadWebFeatures: vi.fn(async () => undefined),
}))

vi.mock('../components/CurrentSiteIndicator.vue', () => ({
  default: { template: '<div data-current-site>测试局点</div>' },
}))

vi.mock('../components/DesktopRuntimeStatus.vue', () => ({
  default: { template: '<div data-runtime-status />' },
}))

vi.mock('../views/rail-transit/RailTransitBaseDataView.vue', () => ({
  default: {
    name: 'RailTransitBaseDataView',
    template: '<section data-base-data-page>基础资料真实路由</section>',
  },
}))

vi.mock('../platform/uiPreferences', () => ({
  loadUiPreference: vi.fn(async (_key: string, fallback: unknown) => fallback),
  saveUiPreference: vi.fn(async () => undefined),
}))

vi.mock('../components/feedback/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true) }),
}))

vi.mock('../api/railTransitBaseData', () => ({
  listVehicleMrs: vi.fn(async () => []),
}))

vi.mock('../api/railTransitWeb', () => ({
  exportMeshAnalysisReport: vi.fn(),
  getRailTransitTask: vi.fn(),
  recoverRailTransitTasks: vi.fn(async () => []),
}))

vi.mock('../api/meshAnalysis', () => ({
  applyMeshBundleImport: vi.fn(),
  createMeshProfile: vi.fn(),
  deleteMeshArtifact: vi.fn(),
  exportMeshLinkDetails: vi.fn(),
  getMeshActivePathChart: vi.fn(async () => {
    counters.activeChartRequests()
    return activeChart
  }),
  getMeshAnalysisParamsTemplate: vi.fn(async () => analysisParams),
  getMeshAnalysisSession: vi.fn(async (id: string, signal?: AbortSignal) => {
    counters.sessionRequests(id, signal)
    const detail = sessionDetail(id === secondSession.session_id ? secondSession : session)
    if (!sessionRequestControl.deferred) return detail
    return new Promise<typeof detail>((resolve, reject) => {
      const abort = () => {
        sessionRequestControl.pending.delete(id)
        reject(new DOMException('aborted', 'AbortError'))
      }
      if (signal?.aborted) {
        abort()
        return
      }
      signal?.addEventListener('abort', abort, { once: true })
      sessionRequestControl.pending.set(id, {
        signal,
        resolve: () => {
          signal?.removeEventListener('abort', abort)
          sessionRequestControl.pending.delete(id)
          resolve(detail)
        },
      })
    })
  }),
  getMeshAnalysisSummary: vi.fn(async () => ({
    site_id: 'site-test',
    session_count: 1,
    train_count: 1,
    mr_count: 1,
    link_record_count: 2,
    active_link_count: 1,
    standby_link_count: 1,
    switch_event_count: 0,
    short_link_count: 0,
    pingpong_count: 0,
    rssi_anomaly_count: 0,
    channel_busy_anomaly_count: 0,
    unmatched_ap_count: 0,
    warning_session_count: 0,
    latest_analysis_time: session.analysis_time,
  })),
  getMeshAnalysisOverview: vi.fn(async () => ({
    summary: {
      site_id: 'site-test',
      index_status: 'ready',
      indexed_session_count: 2,
      pending_session_count: 0,
      index_updated_at: session.analysis_time,
      session_count: 2,
      train_count: 1,
      mr_count: 1,
      link_record_count: 2,
      active_link_count: 1,
      standby_link_count: 1,
      switch_event_count: 0,
      short_link_count: 0,
      pingpong_count: 0,
      rssi_anomaly_count: 0,
      channel_busy_anomaly_count: 0,
      unmatched_ap_count: 0,
      warning_session_count: 0,
      latest_analysis_time: session.analysis_time,
    },
    sessions: {
      items: [session, secondSession],
      total: 2,
      page: 1,
      page_size: 50,
    },
  })),
  getMeshImportContext: vi.fn(async () => ({
    site_id: 'site-test',
    revision: 'test',
    profiles: [],
    vehicle_mrs: [],
  })),
  getMeshPeerSegmentChart: vi.fn(async () => activeChart),
  getMeshRawTail: vi.fn(),
  getMeshTracksideSignalChart: vi.fn(async () => {
    counters.tracksideChartRequests()
    return tracksideChart
  }),
  listMeshActiveBuildOrder: vi.fn(async () => ({
    items: [{
      sequence: 1,
      source_file_id: 1,
      local_radio: 1,
      active_peer_mac: chartPoint.peer_mac,
      peer_ap_name: chartPoint.peer_ap_name,
      peer_ap_mac: chartPoint.peer_ap_mac,
      station: '测试站',
      section: null,
      mileage: null,
      line_side: null,
      peer_radio: '1',
      peer_radio_mac: chartPoint.peer_radio_mac,
      anchor_link_id: 1,
      build_start_time: session.first_sample_time,
      build_end_time: session.last_sample_time,
      main_link_duration_seconds: 100,
      reported_duration_seconds: 100,
      sample_count: 1,
      avg_mr_rssi: 36,
      min_mr_rssi: 36,
      max_mr_rssi: 36,
      p10_mr_rssi: 36,
      avg_tx_busy: 10,
      avg_rx_busy: 8,
      avg_peer_tx_busy: 12,
      avg_peer_rx_busy: 9,
      build_result: '正常',
      judge_reason: '',
      pingpong_type: '',
      source_file: '06-MR-CT.log',
    }],
    total: 1,
    page: 1,
    page_size: 100,
  })),
  listMeshAnalysisSessions: vi.fn(async () => ({
    items: [session, secondSession],
    total: 2,
    page: 1,
    page_size: 50,
  })),
  listMeshArtifacts: vi.fn(async () => []),
  listMeshLinks: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 100 })),
  listMeshProfiles: vi.fn(async () => []),
  listMeshSwitchEvents: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 500 })),
  meshArtifactDownloadRequest: vi.fn(),
  previewMeshImport: vi.fn(),
  prepareMeshImportContext: vi.fn(),
  rebuildMeshAnalysis: vi.fn(),
  saveMeshAnalysisParams: vi.fn(),
}))

vi.mock('../components/mesh-analysis/tracksideSeriesCache', async () => {
  const actual = await vi.importActual<typeof import('../components/mesh-analysis/tracksideSeriesCache')>(
    '../components/mesh-analysis/tracksideSeriesCache',
  )
  return {
    ...actual,
    buildTracksideSeriesCache: (series: Parameters<typeof actual.buildTracksideSeriesCache>[0]) => {
      counters.cacheBuilds()
      return actual.buildTracksideSeriesCache(series)
    },
    disposeTracksideSeriesCache: (cache: Parameters<typeof actual.disposeTracksideSeriesCache>[0]) => {
      counters.cacheDisposals()
      return actual.disposeTracksideSeriesCache(cache)
    },
  }
})

function fakeChart() {
  const zrender = { on: vi.fn(), off: vi.fn() }
  return {
    clear: vi.fn(),
    dispatchAction: vi.fn(),
    dispose: vi.fn(() => counters.chartDisposals()),
    getZr: vi.fn(() => zrender),
    off: vi.fn(),
    on: vi.fn(),
    resize: vi.fn(),
    setOption: vi.fn(),
  }
}

vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    counters.chartInits()
    return fakeChart()
  }),
  use: vi.fn(),
}))

vi.mock('echarts/charts', () => ({
  LineChart: {},
  ScatterChart: {},
}))

vi.mock('echarts/components', () => ({
  DataZoomComponent: {},
  GridComponent: {},
  LegendComponent: {},
  MarkAreaComponent: {},
  MarkLineComponent: {},
  ToolboxComponent: {},
  TooltipComponent: {},
}))

vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

import { appRoutes } from '../router/routes'

const Root = defineComponent({ template: '<RouterView />' })
const NcDataTableStub = defineComponent({
  name: 'NcDataTable',
  props: { data: { type: Array, default: () => [] } },
  emits: ['row-dblclick'],
  template: `
    <div v-if="data.length" data-first-row>
      <slot name="cell-actions" :row="data[0]" />
    </div>
  `,
})

function findButtonByText(wrapper: ReturnType<typeof mount>, selector: string, text: string) {
  return wrapper.findAll(selector).find((item) => item.text().trim() === text)
}

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  vi.clearAllMocks()
  sessionRequestControl.deferred = false
  sessionRequestControl.pending.clear()
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1920 })
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 960 })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 420 })
  vi.stubGlobal('IntersectionObserver', undefined)
  let frameId = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = ++frameId
    queueMicrotask(() => callback(performance.now()))
    return id
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  let idleId = 0
  vi.stubGlobal('requestIdleCallback', (callback: IdleRequestCallback) => {
    const id = ++idleId
    queueMicrotask(() => callback({ didTimeout: false, timeRemaining: () => 50 } as IdleDeadline))
    return id
  })
  vi.stubGlobal('cancelIdleCallback', () => undefined)
})

afterEach(() => vi.unstubAllGlobals())

describe('AppLayout workspace tabs with real async routes', () => {
  it('keeps the real async MESH view and its loaded charts across 20 tab round trips', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: appRoutes,
    })
    await router.push('/rail-transit/mesh-analysis')
    await router.isReady()
    const pinia = createPinia()
    const workspace = useWorkspaceStore(pinia)
    await workspace.initialize(router)
    const wrapper = mount(Root, {
      attachTo: document.body,
      global: {
        plugins: [pinia, router, ElementPlus],
        stubs: { NcDataTable: NcDataTableStub },
      },
    })
    await flushPromises()

    expect(wrapper.findComponent({ name: 'MeshAnalysisView' }).exists()).toBe(true)
    await findButtonByText(wrapper, '[data-first-row] button', '查看')!.trigger('click')
    await flushPromises()
    const rssiTab = findButtonByText(wrapper, '.el-tabs__item', 'RSSI 分析')
    expect(rssiTab).toBeDefined()
    await rssiTab!.trigger('click')
    await flushPromises()
    await new Promise((resolve) => window.setTimeout(resolve, 20))
    await flushPromises()

    const initialUid = wrapper.findComponent({ name: 'MeshAnalysisView' }).vm.$.uid
    expect(wrapper.find('.mesh-page').classes()).toContain('is-rssi-workspace')
    const initialCounts = {
      activeChartRequests: counters.activeChartRequests.mock.calls.length,
      cacheBuilds: counters.cacheBuilds.mock.calls.length,
      chartInits: counters.chartInits.mock.calls.length,
      sessionRequests: counters.sessionRequests.mock.calls.length,
      tracksideChartRequests: counters.tracksideChartRequests.mock.calls.length,
    }
    expect(initialCounts).toMatchObject({
      activeChartRequests: 1,
      sessionRequests: 1,
      tracksideChartRequests: 1,
    })
    expect(initialCounts.cacheBuilds).toBeGreaterThan(0)
    expect(initialCounts.chartInits).toBeGreaterThan(0)
    await wrapper.get('.sessions-toggle').trigger('click')
    await flushPromises()
    const openButton = findButtonByText(wrapper, '[data-first-row] button', '查看')!
    for (let index = 0; index < 10; index += 1) await openButton.trigger('click')
    await flushPromises()
    expect(counters.sessionRequests).toHaveBeenCalledTimes(1)
    const meshTabId = workspace.activeTabId
    const heapBefore = process.memoryUsage().heapUsed

    for (let index = 0; index < 20; index += 1) {
      const baseDataMenu = findButtonByText(wrapper, '.el-menu-item', '基础资料')
      await baseDataMenu!.trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-base-data-page]').exists()).toBe(true)
      const meshPageTab = wrapper.get(`[data-workspace-tab="${meshTabId}"]`)
      await meshPageTab.trigger('click')
      await flushPromises()
      expect(wrapper.findComponent({ name: 'MeshAnalysisView' }).vm.$.uid).toBe(initialUid)
      expect(wrapper.find('.mesh-page').classes()).toContain('is-rssi-workspace')
    }

    const heapAfter = process.memoryUsage().heapUsed
    expect({
      activeChartRequests: counters.activeChartRequests.mock.calls.length,
      cacheBuilds: counters.cacheBuilds.mock.calls.length,
      chartInits: counters.chartInits.mock.calls.length,
      sessionRequests: counters.sessionRequests.mock.calls.length,
      tracksideChartRequests: counters.tracksideChartRequests.mock.calls.length,
    }).toEqual(initialCounts)
    console.info('[mesh-tabs-20x]', JSON.stringify({
      ...initialCounts,
      heapBefore,
      heapAfter,
      heapDelta: heapAfter - heapBefore,
    }))

    const baseDataMenu = findButtonByText(wrapper, '.el-menu-item', '基础资料')
    await baseDataMenu!.trigger('click')
    await flushPromises()
    const meshPageTab = wrapper.get(`[data-workspace-tab="${meshTabId}"]`)
    await meshPageTab.get('.workspace-tab__close').trigger('click')
    await flushPromises()

    expect(counters.cacheDisposals).toHaveBeenCalled()
    expect(counters.chartDisposals).toHaveBeenCalled()
    expect(wrapper.find(`[data-workspace-tab="${meshTabId}"]`).exists()).toBe(false)

    wrapper.unmount()
    workspace.dispose()
  }, 30_000)

  it('applies a background MESH session intent once and aborts stale detail requests', async () => {
    sessionRequestControl.deferred = true
    const router = createRouter({ history: createMemoryHistory(), routes: appRoutes })
    await router.push('/rail-transit/mesh-analysis')
    await router.isReady()
    const pinia = createPinia()
    const workspace = useWorkspaceStore(pinia)
    await workspace.initialize(router)
    const wrapper = mount(Root, {
      attachTo: document.body,
      global: { plugins: [pinia, router, ElementPlus], stubs: { NcDataTable: NcDataTableStub } },
    })
    await flushPromises()
    const meshUid = wrapper.getComponent({ name: 'MeshAnalysisView' }).vm.$.uid

    await workspace.openOrActivateRoute(`/rail-transit/mesh-analysis?session_id=${session.session_id}`)
    await flushPromises()
    const firstRequest = sessionRequestControl.pending.get(session.session_id)
    expect(firstRequest).toBeDefined()

    await workspace.openOrActivateRoute(`/rail-transit/mesh-analysis?session_id=${secondSession.session_id}`)
    await flushPromises()
    expect(firstRequest?.signal?.aborted).toBe(true)
    expect(sessionRequestControl.pending.has(session.session_id)).toBe(false)
    expect(sessionRequestControl.pending.has(secondSession.session_id)).toBe(true)
    sessionRequestControl.pending.get(secondSession.session_id)?.resolve()
    await flushPromises()

    expect(workspace.tabs.filter((tab) => tab.routeName === 'mesh-analysis')).toHaveLength(1)
    expect(workspace.activeTab?.routeFullPath).toContain(`session_id=${secondSession.session_id}`)
    expect(wrapper.getComponent({ name: 'MeshAnalysisView' }).vm.$.uid).toBe(meshUid)
    expect(wrapper.get('.detail-heading h2').text()).toBe(secondSession.mr_name)
    expect(counters.sessionRequests.mock.calls.map(([id]) => id)).toEqual([
      session.session_id,
      secondSession.session_id,
    ])
    expect(counters.tracksideChartRequests).not.toHaveBeenCalled()

    sessionRequestControl.deferred = false
    await workspace.openOrActivateRoute('/rail-transit/base-data')
    await flushPromises()
    expect(wrapper.find('[data-base-data-page]').exists()).toBe(true)
    await workspace.openOrActivateRoute(`/rail-transit/mesh-analysis?session_id=${session.session_id}`)
    await flushPromises()
    expect(wrapper.getComponent({ name: 'MeshAnalysisView' }).vm.$.uid).toBe(meshUid)
    expect(wrapper.get('.detail-heading h2').text()).toBe(session.mr_name)
    expect(workspace.tabs.filter((tab) => tab.routeName === 'mesh-analysis')).toHaveLength(1)
    expect(counters.sessionRequests.mock.calls.map(([id]) => id)).toEqual([
      session.session_id,
      secondSession.session_id,
      session.session_id,
    ])

    wrapper.unmount()
    workspace.dispose()
  }, 30_000)
})
