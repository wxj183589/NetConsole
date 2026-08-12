// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref, useAttrs, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from '../../api/client'
import meshAnalysisViewSource from './MeshAnalysisView.vue?raw'
import type { TracksideSeriesCache } from '../../components/mesh-analysis/tracksideSeriesCache'

const mocks = vi.hoisted(() => ({
  listProfiles: vi.fn(),
  listVehicleMrs: vi.fn(),
  prepareContext: vi.fn(),
  getImportContext: vi.fn(),
  createProfile: vi.fn(),
  previewImport: vi.fn(),
  recoverTasks: vi.fn(),
  getTask: vi.fn(),
  getOverview: vi.fn(),
  getSession: vi.fn(),
  getAnalysisParams: vi.fn(),
  getAnalysisParamsTemplate: vi.fn(),
  saveAnalysisParams: vi.fn(),
  listSessions: vi.fn(),
  listBuildOrder: vi.fn(),
  listLinks: vi.fn(),
  listSwitchEvents: vi.fn(),
  getActivePath: vi.fn(),
  getPeerPath: vi.fn(),
  getTracksideSignal: vi.fn(),
  getRateSeries: vi.fn(),
  getCounterDeltas: vi.fn(),
  listAnomalies: vi.fn(),
  exportDetails: vi.fn(),
  deleteSource: vi.fn(),
  batchDeleteSources: vi.fn(),
  rebuildAnalysis: vi.fn(),
  startMaintenance: vi.fn(),
  chartApplyViewport: vi.fn(),
  chartResetViewport: vi.fn(),
  chartResize: vi.fn(),
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  platformAdapter: {
    hostType: 'browser' as 'browser' | 'electron',
    openMeshAnalysisSessionLocation: vi.fn(),
  },
  taskStore: null as null | {
    tasks: Array<Record<string, unknown>>
    refresh: ReturnType<typeof vi.fn>
    acquirePolling: ReturnType<typeof vi.fn>
    releasePolling: ReturnType<typeof vi.fn>
  },
  taskStoreRefresh: vi.fn(),
  taskStoreAcquirePolling: vi.fn(),
  taskStoreReleasePolling: vi.fn(),
  currentRoute: {
    value: {
      name: 'mesh-analysis',
      path: '/rail-transit/mesh-analysis',
      fullPath: '/rail-transit/mesh-analysis',
      query: {} as Record<string, string>,
    },
  },
}))

vi.mock('../../api/meshAnalysis', () => ({
  applyMeshBundleImport: vi.fn(),
  batchDeleteMeshSources: mocks.batchDeleteSources,
  createMeshProfile: mocks.createProfile,
  deleteMeshSource: mocks.deleteSource,
  exportMeshLinkDetails: mocks.exportDetails,
  getMeshActivePathChart: mocks.getActivePath,
  getMeshAnalysisParams: mocks.getAnalysisParams,
  getMeshAnalysisParamsTemplate: mocks.getAnalysisParamsTemplate,
  getMeshAnalysisSession: mocks.getSession,
  getMeshAnalysisOverview: mocks.getOverview,
  getMeshAnalysisSummary: vi.fn().mockResolvedValue({ session_count: 0, train_count: 0, mr_count: 0 }),
  getMeshImportContext: mocks.getImportContext,
  getMeshPeerSegmentChart: mocks.getPeerPath,
  getMeshTracksideSignalChart: mocks.getTracksideSignal,
  getMeshRawTail: vi.fn(),
  getMeshCounterDeltas: mocks.getCounterDeltas,
  getMeshRateSeries: mocks.getRateSeries,
  listMeshActiveBuildOrder: mocks.listBuildOrder,
  listMeshAnalysisSessions: mocks.listSessions,
  listMeshAnomalies: mocks.listAnomalies,
  listMeshArtifacts: vi.fn(),
  listMeshLinks: mocks.listLinks,
  listMeshProfiles: mocks.listProfiles,
  listMeshSwitchEvents: mocks.listSwitchEvents,
  meshArtifactDownloadRequest: vi.fn(),
  previewMeshImport: mocks.previewImport,
  rebuildMeshAnalysis: mocks.rebuildAnalysis,
  prepareMeshImportContext: mocks.prepareContext,
  saveMeshAnalysisParams: mocks.saveAnalysisParams,
  startMeshMaintenance: mocks.startMaintenance,
}))
vi.mock('../../api/railTransitBaseData', () => ({ listVehicleMrs: mocks.listVehicleMrs }))
vi.mock('../../api/railTransitWeb', () => ({
  exportMeshAnalysisReport: vi.fn(),
  getRailTransitTask: mocks.getTask,
  recoverRailTransitTasks: mocks.recoverTasks,
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true) }) }))
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: vi.fn(),
  getPlatformAdapter: () => mocks.platformAdapter,
}))
vi.mock('../../stores/tasks', async () => {
  const { reactive } = await import('vue')
  const store = reactive({
    tasks: [] as Array<Record<string, unknown>>,
    refresh: mocks.taskStoreRefresh,
    acquirePolling: mocks.taskStoreAcquirePolling,
    releasePolling: mocks.taskStoreReleasePolling,
  })
  mocks.taskStore = store
  return { useTaskStore: () => store }
})
vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mocks.routerPush,
    replace: mocks.routerReplace,
    currentRoute: mocks.currentRoute,
  }),
}))

import MeshAnalysisView from './MeshAnalysisView.vue'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) { const attrs = useAttrs(); return () => h('div', attrs, slots.default?.()) },
})
const buttonStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) { const attrs = useAttrs(); return () => h('button', attrs, slots.default?.()) },
})
const alertStub = defineComponent({
  props: { title: { type: String, default: '' } },
  setup(props, { slots }) { return () => h('div', [props.title, slots.default?.()]) },
})
const optionStub = defineComponent({
  props: { label: { type: String, default: '' }, value: { type: [String, Number, Boolean], default: '' } },
  setup(props) { return () => h('option', { value: props.value, 'data-option-label': props.label }, props.label) },
})
const inputStub = defineComponent({
  inheritAttrs: false,
  props: {
    modelValue: { type: [String, Number], default: '' },
    placeholder: { type: String, default: '' },
  },
  emits: ['input', 'update:modelValue'],
  setup(props, { attrs, emit }) {
    return () => h('input', {
      ...attrs,
      value: props.modelValue,
      placeholder: props.placeholder,
      onInput: (event: Event) => {
        const value = (event.target as HTMLInputElement).value
        emit('update:modelValue', value)
        emit('input', value)
      },
    })
  },
})
const selectStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: [String, Number, Boolean, Object], default: '' }, placeholder: { type: String, default: '' } },
  emits: ['change', 'update:modelValue'],
  setup(props, { attrs, slots, emit }) {
    return () => h('select', {
      ...attrs,
      value: props.modelValue as string | number | boolean,
      'data-placeholder': props.placeholder,
      onChange: (event: Event) => {
        const raw = (event.target as HTMLSelectElement).value
        const value = raw !== '' && !Number.isNaN(Number(raw)) ? Number(raw) : raw
        emit('update:modelValue', value)
        emit('change', value)
      },
    }, slots.default?.())
  },
})
const dataTableStub = defineComponent({
  inheritAttrs: false,
  props: { data: { type: Array, default: () => [] }, columns: { type: Array, default: () => [] }, tableId: { type: String, default: '' } },
  emits: ['row-click', 'row-dblclick', 'sort-change', 'selection-change'],
  setup(props, { attrs, slots }) {
    return () => h('div', { ...attrs, 'data-table-id': props.tableId }, props.data.flatMap((row) => [
      slots.default?.({ row }),
      slots['cell-actions']?.({ row }),
    ]))
  },
})
const paginationStub = defineComponent({
  inheritAttrs: false,
  props: {
    currentPage: { type: Number, default: 1 },
    pageSize: { type: Number, default: 0 },
    total: { type: Number, default: 0 },
  },
  emits: ['current-change', 'size-change'],
  setup(props, { attrs }) {
    return () => h('div', {
      ...attrs,
      class: 'pagination-stub',
      'data-current-page': props.currentPage,
      'data-page-size': props.pageSize,
      'data-total': props.total,
    })
  },
})
const dialogStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) { const attrs = useAttrs(); return () => h('div', attrs, [slots.default?.(), slots.footer?.()]) },
})
const popoverStub = defineComponent({
  setup(_props, { slots }) { return () => h('div', [slots.reference?.(), slots.default?.()]) },
})
const tabsStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { attrs, slots }) {
    return () => h('div', { ...attrs, modelvalue: props.modelValue }, slots.default?.())
  },
})
const chartViewport = {
  start_time: '2026-07-20 10:00:01.123',
  end_time: '2026-07-20 10:00:03.456',
  start_percent: 10,
  end_percent: 30,
  full_start_time: '2026-07-20 10:00:00.000',
  full_end_time: '2026-07-20 10:00:10.000',
  source: 'user_zoom' as const,
}
const meshChartStub = defineComponent({
  name: 'MeshChartStub',
  props: {
    points: { type: Array, default: () => [] },
    series: { type: Array, default: () => [] },
    seriesCache: { type: Object, default: null },
    events: { type: Array, default: () => [] },
    scope: { type: String, default: '' },
    initialViewport: { type: Object, default: null },
    syncViewport: { type: Object, default: null },
    sharedTimeDomain: { type: Object, default: null },
    syncPointerTime: { type: String, default: null },
    syncPointerSource: { type: String, default: null },
    active: { type: Boolean, default: true },
  },
  setup(_props, { expose }) {
    expose({
      getViewport: () => chartViewport,
      getVisibleTimeRange: () => chartViewport,
      applyViewport: mocks.chartApplyViewport,
      resetViewport: mocks.chartResetViewport,
      resize: mocks.chartResize,
    })
    return () => h('div', { class: 'mesh-chart-stub' })
  },
})
const stubs: Record<string, Component | boolean> = {
  ElAlert: alertStub,
  ElButton: buttonStub,
  ElCheckbox: passthrough,
  ElCollapse: passthrough,
  ElCollapseItem: passthrough,
  ElDialog: dialogStub,
  ElDivider: passthrough,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: inputStub,
  ElInputNumber: passthrough,
  ElIcon: passthrough,
  ElOption: optionStub,
  ElPagination: paginationStub,
  ElPopover: popoverStub,
  ElSelect: selectStub,
  ElTabPane: passthrough,
  ElTabs: tabsStub,
  ElTag: passthrough,
  MeshChannelBusyChart: meshChartStub,
  MeshRssiChart: meshChartStub,
  MeshTracksideSignalChart: meshChartStub,
  MeshSwitchRssiChart: true,
  NcDataTable: dataTableStub,
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getOverview.mockReset()
  mocks.listSessions.mockReset()
  mocks.platformAdapter.hostType = 'browser'
  mocks.platformAdapter.openMeshAnalysisSessionLocation.mockResolvedValue({ success: true })
  mocks.taskStore?.tasks.splice(0)
  vi.stubGlobal('IntersectionObserver', undefined)
  let frameId = 0
  const cancelledFrames = new Set<number>()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = ++frameId
    queueMicrotask(() => {
      if (!cancelledFrames.has(id)) callback(performance.now())
    })
    return id
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { cancelledFrames.add(id) })
  let idleId = 0
  const cancelledIdleCallbacks = new Set<number>()
  vi.stubGlobal('requestIdleCallback', (callback: IdleRequestCallback) => {
    const id = ++idleId
    queueMicrotask(() => {
      if (!cancelledIdleCallbacks.has(id)) {
        callback({ didTimeout: false, timeRemaining: () => 50 } as IdleDeadline)
      }
    })
    return id
  })
  vi.stubGlobal('cancelIdleCallback', (id: number) => { cancelledIdleCallbacks.add(id) })
  sessionStorage.clear()
  localStorage.clear()
  mocks.currentRoute.value = {
    name: 'mesh-analysis',
    path: '/rail-transit/mesh-analysis',
    fullPath: '/rail-transit/mesh-analysis',
    query: {},
  }
  mocks.routerPush.mockResolvedValue(undefined)
  mocks.routerReplace.mockImplementation(async (target: { name?: string; path?: string; query?: Record<string, string> }) => {
    const path = target.path || '/rail-transit/mesh-analysis'
    const query = { ...(target.query || {}) }
    const encoded = new URLSearchParams(query).toString()
    mocks.currentRoute.value = {
      name: target.name || 'mesh-analysis',
      path,
      fullPath: `${path}${encoded ? `?${encoded}` : ''}`,
      query,
    }
    return undefined
  })
  mocks.listProfiles.mockResolvedValue([])
  mocks.listVehicleMrs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 })
  mocks.getImportContext.mockImplementation(async () => {
    const [profiles, vehiclePage] = await Promise.all([
      mocks.listProfiles(),
      mocks.listVehicleMrs({ page: 1, page_size: 200 }),
    ])
    return {
      site_id: 'demo',
      revision: 'test',
      profiles,
      vehicle_mrs: vehiclePage.items,
    }
  })
  mocks.prepareContext.mockResolvedValue({
    site_id: 'demo',
    vehicle_mr_count: 0,
    profile_count: 0,
    created_count: 0,
    updated_count: 0,
    skipped_count: 0,
    warnings: [],
  })
  mocks.createProfile.mockResolvedValue({
    mr_id: 'profile-new',
    display_name: '列车34-MR-CT',
    safe_folder_name: '列车34-MR-CT',
    linked_device_id: 34,
    linked_device_uuid: 'uuid-34-ct',
  })
  mocks.previewImport.mockResolvedValue({
    preview_id: 'preview-1',
    items: [],
  })
  mocks.recoverTasks.mockResolvedValue([])
  mocks.getTask.mockResolvedValue(null)
  mocks.getAnalysisParams.mockResolvedValue({ link_time_window: 4000 })
  mocks.getAnalysisParamsTemplate.mockResolvedValue({ link_time_window: 4000 })
  mocks.saveAnalysisParams.mockImplementation(async (params: unknown) => params)
  mocks.listSessions.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
  mocks.getOverview.mockImplementation(async (values) => {
    const sessions = await mocks.listSessions(values)
    return {
      summary: {
        site_id: 'demo',
        index_status: 'ready',
        indexed_session_count: sessions.total,
        pending_session_count: 0,
        index_updated_at: null,
        session_count: sessions.total,
        train_count: sessions.total ? 1 : 0,
        mr_count: sessions.total ? 1 : 0,
      },
      sessions,
    }
  })
  mocks.listBuildOrder.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  mocks.listLinks.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  mocks.listSwitchEvents.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  mocks.getActivePath.mockResolvedValue({ mode: 'active_path', anchor: null, points: [], events: [], total_points: 0, downsampled: false, summary: {}, time_from: null, time_to: null })
  mocks.getPeerPath.mockResolvedValue({ mode: 'peer_segment', anchor: null, points: [], events: [], total_points: 0, downsampled: false, summary: {}, time_from: null, time_to: null })
  mocks.getTracksideSignal.mockResolvedValue({
    source_id: 'session',
    radio: null,
    time_range: { start: null, end: null },
    series: [],
    events: [],
    warnings: [],
    estimated_interval_seconds: null,
    continuity_gap_seconds: null,
    total_series: 0,
    returned_series: 0,
    total_frames: 0,
    returned_frames: 0,
    total_link_points: 0,
    returned_link_points: 0,
    total_link_runs: 0,
    active_link_points: 0,
    standby_link_points: 0,
    returned_active_link_points: 0,
    returned_standby_link_points: 0,
    role_switch_count: 0,
    skipped_missing_signal_points: 0,
    skipped_missing_identity_points: 0,
    total_points: 0,
    returned_points: 0,
    downsampled: false,
    requested_max_frames: 600,
    effective_max_frames: 600,
    requested_max_points: 600,
    effective_max_points: 600,
    top_n: 0,
    included_roles: ['ACTIVE', 'STANDBY'],
    include_standby: true,
  })
  mocks.exportDetails.mockResolvedValue({ action: 'mesh_link_detail_export', task_id: 'mesh-export-1', status: 'RUNNING' })
  mocks.batchDeleteSources.mockResolvedValue({
    action: 'mesh_analysis_sources_delete',
    task_id: 'mesh-delete-batch-1',
    status: 'RUNNING',
    result_summary: {},
  })
  mocks.rebuildAnalysis.mockResolvedValue({
    action: 'mesh_source_rebuild',
    task_id: 'mesh-identity-remap-1',
    status: 'RUNNING',
    result_summary: {},
  })
  mocks.startMaintenance.mockResolvedValue({
    action: 'mesh_analysis_maintenance',
    task_id: 'mesh-identity-refresh-1',
    status: 'RUNNING',
    result_summary: {},
  })
})

afterEach(() => vi.unstubAllGlobals())

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function refreshTestSession(sessionId: string, mrName = '列车24-MR-CT') {
  return {
    session_id: sessionId,
    mr_name: mrName,
    train_name: '列车24',
    original_filename: '2026_07_24_1meshlog.log',
    first_sample_time: '2026-07-24 10:00:00.000',
    last_sample_time: '2026-07-24 10:01:00.000',
    parsed_status: 'ready',
    warning_count: 0,
    report_count: 0,
  }
}

function refreshTestDetail(session: ReturnType<typeof refreshTestSession>) {
  return {
    session,
    analysis_params: {},
    available_radios: [1],
    warnings: [],
    sources: [{
      source_file_id: 24,
      source_action_id: 'source-refresh-test',
      exists: true,
      rebuild_capability: 'ready',
      identity_mapping_status: 'ready',
    }],
  }
}

function refreshTestBuildOrder(peerApName: string) {
  return {
    items: [{
      sequence: 1,
      anchor_link_id: 24,
      source_file_id: 24,
      local_radio: 1,
      peer_ap_name: peerApName,
      active_peer_mac: '642f-c778-ef5f',
      build_start_time: '2026-07-24 10:00:00.000',
      build_end_time: '2026-07-24 10:00:10.000',
      build_result: 'normal',
      identity_status: peerApName ? 'matched' : 'unresolved',
    }],
    total: 1,
    page: 1,
    page_size: 100,
  }
}

function mountRefreshTestView() {
  return mount(MeshAnalysisView, {
    global: { stubs, directives: { loading: () => undefined } },
  })
}

function hotfixActivePayload(
  sessionId: string,
  marker: number,
  timeFrom: string | null = null,
  timeTo: string | null = null,
  viewMode: 'overview' | 'window' = timeFrom && timeTo ? 'window' : 'overview',
) {
  const timestamp = timeFrom || '2026-07-24 10:00:00.000'
  return {
    mode: 'active_path',
    view_mode: viewMode,
    anchor: null,
    points: [{ timestamp, local_radio: 2, local_rssi: marker }],
    events: [],
    location_segments: [],
    total_points: 1,
    returned_points: 1,
    requested_max_points: 600,
    effective_max_points: 600,
    downsampled: false,
    downsample_warning: null,
    summary: {
      sample_count: 1,
      active_count: 1,
      standby_context_count: 0,
      switch_count: 0,
      current_radio: 2,
      first_sample_time: timestamp,
      last_sample_time: timeTo || timestamp,
    },
    time_from: timeFrom,
    time_to: timeTo,
    source_id: sessionId,
  }
}

function hotfixTracksidePayload(
  sessionId: string,
  marker: number,
  timeFrom = '2026-07-24 10:00:00.000',
  timeTo = '2026-07-24 11:00:00.000',
  viewMode: 'overview' | 'window' = 'overview',
) {
  return {
    source_id: sessionId,
    view_mode: viewMode,
    radio: 2,
    time_range: { start: timeFrom, end: timeTo },
    series: [{
      series_id: `ap-${marker}:radio:2`,
      peer_name: `AP-${marker}`,
      peer_mac: `0000-0000-${String(marker).padStart(4, '0')}`,
      ap_mac: null,
      peer_radio_mac: null,
      radio: 2,
      station: null,
      section: null,
      roles_present: ['ACTIVE'],
      data_source: 'peer_rssi_db',
      total_points: 1,
      returned_points: 1,
      points: [{
        timestamp: timeFrom,
        timestamp_tag: '',
        source_file_id: 35,
        link_id: marker,
        sample_id: marker,
        local_radio: 2,
        role: 'ACTIVE',
        peer_mac: `0000-0000-${String(marker).padStart(4, '0')}`,
        peer_ap_name: `AP-${marker}`,
        peer_ap_mac: null,
        peer_radio: null,
        peer_radio_mac: null,
        station: null,
        section: null,
        peer_rssi: marker,
        local_rssi: marker - 2,
        peer_signal: null,
        local_signal: null,
        segment_duration_seconds: 10,
        data_source: 'peer_rssi_db',
      }],
    }],
    events: [],
    warnings: [],
    estimated_interval_seconds: 1,
    continuity_gap_seconds: 5,
    total_series: 1,
    returned_series: 1,
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
    total_points: 1,
    returned_points: 1,
    downsampled: false,
    requested_max_frames: 600,
    effective_max_frames: 600,
    requested_max_points: 600,
    effective_max_points: 600,
    top_n: 0,
    included_roles: ['ACTIVE', 'STANDBY'],
    include_standby: true,
    payload_bytes: 1,
    query_duration_ms: 1,
  }
}

async function mountHotfixRssiSession(sessionId: string) {
  const session = {
    session_id: sessionId,
    mr_name: '列车35-MR-CT',
    original_filename: '2026_07_24_1meshlog.log',
    first_sample_time: '2026-07-24 10:00:00.000',
    last_sample_time: '2026-07-24 11:00:00.000',
    parsed_status: 'ready',
    warning_count: 0,
    report_count: 0,
  }
  mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
  mocks.getSession.mockResolvedValue({
    session,
    analysis_params: {},
    available_radios: [2],
    warnings: [],
    sources: [{ source_file_id: 35, raw_sha256: 'hotfix-source' }],
  })
  mocks.listBuildOrder.mockResolvedValue({
    items: [{
      sequence: 1,
      anchor_link_id: 35,
      local_radio: 2,
      peer_ap_name: 'AP1608',
      active_peer_mac: '0000-0000-1608',
      build_start_time: session.first_sample_time,
      build_end_time: session.last_sample_time,
      build_result: 'normal',
    }],
    total: 1,
    page: 1,
    page_size: 100,
  })
  mocks.getActivePath.mockResolvedValue(hotfixActivePayload(sessionId, 30))
  mocks.getTracksideSignal.mockResolvedValue(hotfixTracksidePayload(sessionId, 28))

  const wrapper = mount(MeshAnalysisView, {
    global: { stubs, directives: { loading: () => undefined } },
  })
  await flushPromises()
  await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
  await vi.waitFor(() => expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(1))
  await flushPromises()
  await vi.waitFor(() => expect(
    wrapper.findAllComponents(meshChartStub).some((chart) => chart.props('scope') === ''),
  ).toBe(true))

  const activeChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === 'active')!
  const tracksideChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === '')!
  return { wrapper, session, activeChart, tracksideChart }
}

async function toggleRssiPresentation(wrapper: ReturnType<typeof mount>, label: string): Promise<void> {
  await wrapper.findAll('button').find((button) => button.text() === label)!.trigger('click')
  await flushPromises()
}

describe('Mesh analysis import context behavior', () => {
  it('keeps four duplicate basenames as independent member mappings', async () => {
    mocks.listProfiles.mockResolvedValueOnce([{
      mr_id: 'profile-1',
      display_name: '列车34-MR-CT',
      safe_folder_name: '列车34-MR-CT',
      linked_device_id: 34,
      linked_device_uuid: 'uuid-34-ct',
    }])
    mocks.previewImport.mockResolvedValueOnce({
      preview_id: 'preview-duplicate-names',
      items: Array.from({ length: 4 }, (_, index) => ({
        member_id: `member-${index + 1}`,
        original_name: 'meshlog.log',
        original_relative_path: '',
        safe_name: 'meshlog.log',
        size_bytes: 100 + index,
        sha256: String(index + 1).repeat(64),
        raw_sha256: String(index + 1).repeat(64),
        content_sha256: String(index + 5).repeat(64),
        first_log_timestamp: `2026-07-${27 + index}T00:18:56.311000`,
        last_log_timestamp: `2026-07-${27 + index}T00:19:56.311000`,
        log_date: `2026-07-${27 + index}`,
        stored_filename: `2026_07_${27 + index}_1meshlog.log`,
        daily_sequence: 1,
        rename_status: 'renamed_by_log_date_sequence',
        rename_warning: '',
        duplicate_status: 'new',
        batch_duplicate_of: '',
        import_allowed: true,
        existing_source_id: null,
        existing_stored_filename: '',
        existing_session_id: '',
        existing_profile_id: '',
        existing_profile_name: '',
        train_number: '34',
        role: 'CT',
        match_status: 'matched',
        selected_profile_id: 'profile-1',
        selected_profile_name: '列车34-MR-CT',
        profile_import_states: [{
          profile_id: 'profile-1',
          profile_name: '列车34-MR-CT',
          stored_filename: `2026_07_${27 + index}_1meshlog.log`,
          daily_sequence: 1,
          rename_status: 'renamed_by_log_date_sequence',
          rename_warning: '',
          duplicate_status: 'new',
          import_allowed: true,
          existing_source_id: null,
          existing_stored_filename: '',
          existing_session_id: '',
          existing_profile_id: '',
          existing_profile_name: '',
        }],
        candidates: [{ profile_id: 'profile-1', display_name: '列车34-MR-CT' }],
      })),
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('导入原始 MESH 日志'))!.trigger('click')
    await flushPromises()
    const files = Array.from(
      { length: 4 },
      (_, index) => new File([`mesh-${index}`], 'meshlog.log', { type: 'text/plain' }),
    )
    const fileInput = wrapper.findAll('input[type="file"]')[0]
    Object.defineProperty(fileInput.element, 'files', { configurable: true, value: files })

    await fileInput.trigger('change')
    await flushPromises()

    expect(mocks.previewImport).toHaveBeenCalledWith(files, expect.any(AbortSignal))
    expect(wrapper.findAll('.bundle-table tbody tr')).toHaveLength(4)
    expect(wrapper.text()).toContain('成员 1')
    expect(wrapper.text()).toContain('成员 4')
    expect(wrapper.text()).toContain('我已核对以上文件的列车号、端位和车载 MR 归属')
    const submit = wrapper.findAll('button').find((button) => button.text() === '确认导入并分析')!
    expect(submit.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('shows structured preview errors inside the dialog and retries without clearing files', async () => {
    mocks.previewImport.mockRejectedValueOnce(
      new ApiRequestError(
        '存在重复文件名：meshlog.log',
        422,
        'DUPLICATE_MEMBER',
      ),
    )
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('导入原始 MESH 日志'))!.trigger('click')
    await flushPromises()
    const file = new File(['mesh'], 'meshlog.log', { type: 'text/plain' })
    const fileInput = wrapper.findAll('input[type="file"]')[0]
    Object.defineProperty(fileInput.element, 'files', { configurable: true, value: [file] })

    await fileInput.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('日志预览失败：DUPLICATE_MEMBER：存在重复文件名：meshlog.log')
    expect(wrapper.text()).toContain('已选择 1 个文件')
    const retry = wrapper.findAll('button').find((button) => button.text() === '重新预览')!
    await retry.trigger('click')
    await flushPromises()

    expect(mocks.previewImport).toHaveBeenCalledTimes(2)
    expect(mocks.previewImport).toHaveBeenLastCalledWith([file], expect.any(AbortSignal))
    expect(wrapper.text()).toContain('已选择 1 个文件')
    wrapper.unmount()
  })

  it('loads the lightweight import context once without starting a full profile sync', async () => {
    const firstPage = Array.from({ length: 200 }, (_, index) => ({ id: `uuid-${index}`, device_id: index + 1, name: `列车${index + 1}-MR-CT`, train_no: String(index + 1), role: 'CT' }))
    mocks.listVehicleMrs
      .mockResolvedValueOnce({ items: firstPage, total: 201, page: 1, page_size: 200 })
      .mockResolvedValueOnce({ items: [{ id: 'uuid-201', device_id: 201, name: '列车201-MR-CW', train_no: '201', role: 'CW' }], total: 201, page: 2, page_size: 200 })
    mocks.listProfiles.mockRejectedValueOnce(new Error('profile unavailable'))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入原始 MESH 日志'))
    expect(importButton).toBeDefined()
    await importButton!.trigger('click')
    await flushPromises()

    expect(mocks.prepareContext).not.toHaveBeenCalled()
    expect(mocks.getImportContext).toHaveBeenCalledTimes(1)
    expect(mocks.listVehicleMrs).toHaveBeenCalledWith({ page: 1, page_size: 200 })
    expect(wrapper.text()).toContain('内部 MESH 归属加载失败：profile unavailable')
    expect(wrapper.text()).toContain('车载 MR 加载失败：profile unavailable')
    wrapper.unmount()
  })

  it('keeps selected files usable and does not wait for a full profile sync before preview', async () => {
    mocks.listProfiles.mockResolvedValueOnce([{
      mr_id: 'profile-1',
      display_name: '列车34-MR-CT',
      safe_folder_name: '列车34-MR-CT',
      linked_device_id: 34,
      linked_device_uuid: 'uuid-34-ct',
    }])
    mocks.previewImport.mockResolvedValueOnce({
      preview_id: 'preview-1',
      items: [{
        member_id: '34CT.log',
        original_name: '34CT.log',
        safe_name: '34CT.log',
        size_bytes: 4,
        sha256: 'a'.repeat(64),
        raw_sha256: 'a'.repeat(64),
        content_sha256: 'b'.repeat(64),
        first_log_timestamp: '2026-07-28T00:18:56.311000',
        last_log_timestamp: '2026-07-28T00:19:56.311000',
        log_date: '2026-07-28',
        stored_filename: '2026_07_28_1meshlog.log',
        daily_sequence: 1,
        rename_status: 'renamed_by_log_date_sequence',
        rename_warning: '',
        duplicate_status: 'new',
        batch_duplicate_of: '',
        import_allowed: true,
        existing_source_id: null,
        existing_stored_filename: '',
        existing_session_id: '',
        existing_profile_id: '',
        existing_profile_name: '',
        train_number: '34',
        role: 'CT',
        match_status: 'matched',
        selected_profile_id: 'profile-1',
        selected_profile_name: '列车34-MR-CT',
        profile_import_states: [{
          profile_id: 'profile-1',
          profile_name: '列车34-MR-CT',
          stored_filename: '2026_07_28_1meshlog.log',
          daily_sequence: 1,
          rename_status: 'renamed_by_log_date_sequence',
          rename_warning: '',
          duplicate_status: 'new',
          import_allowed: true,
          existing_source_id: null,
          existing_stored_filename: '',
          existing_session_id: '',
          existing_profile_id: '',
          existing_profile_name: '',
        }],
        candidates: [{ profile_id: 'profile-1', display_name: '列车34-MR-CT' }],
      }],
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入原始 MESH 日志'))!
    void importButton.trigger('click')
    await flushPromises()

    const file = new File(['mesh'], '34CT.log', { type: 'text/plain' })
    const fileInput = wrapper.findAll('input[type="file"]')[0]
    Object.defineProperty(fileInput.element, 'files', { configurable: true, value: [file] })
    await fileInput.trigger('change')
    await flushPromises()
    expect(mocks.listProfiles).toHaveBeenCalled()
    expect(mocks.prepareContext).not.toHaveBeenCalled()
    expect(mocks.previewImport).toHaveBeenCalledWith([file], expect.any(AbortSignal))
    expect(wrapper.text()).toContain('已选择 1 个文件')
    expect(wrapper.text()).toContain('2026_07_28_1meshlog.log')
    expect(wrapper.text()).toContain('2026-07-28T00:18:56.311000')
    expect(wrapper.text()).toContain('bbbbbbbbbbbb')
    wrapper.unmount()
  })

  it('auto-fills linked MR names, updates untouched values, and preserves manual edits', async () => {
    const vehicleMrs = [
      {
        id: 'uuid-34-ct',
        device_id: 34,
        name: '列车34-MR-CT',
        train_no: '34',
        role: 'CT',
        mr_position_code: 'CT',
      },
      {
        id: 'uuid-34-cw',
        device_id: 35,
        name: '',
        train_no: '34',
        role: 'cw',
        mr_position_code: 'CW',
      },
    ]
    mocks.listVehicleMrs.mockResolvedValue({ items: vehicleMrs, total: 2, page: 1, page_size: 200 })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('导入原始 MESH 日志'))!.trigger('click')
    await flushPromises()

    const linkedSelect = wrapper.findAllComponents(selectStub).find((select) => (
      select.findAll('[data-option-label]').some((option) => option.text().includes('列车34-MR-CT'))
    ))!
    const nameInput = wrapper.get('input[placeholder="例如：列车01-MR-CT"]')
    await linkedSelect.vm.$emit('update:modelValue', 'uuid-34-ct')
    await flushPromises()
    expect((nameInput.element as HTMLInputElement).value).toBe('列车34-MR-CT')

    await linkedSelect.vm.$emit('update:modelValue', 'uuid-34-cw')
    await flushPromises()
    expect((nameInput.element as HTMLInputElement).value).toBe('列车34-MR-CW')

    await nameInput.setValue('34车尾端测试日志')
    await linkedSelect.vm.$emit('update:modelValue', 'uuid-34-ct')
    await flushPromises()
    expect((nameInput.element as HTMLInputElement).value).toBe('34车尾端测试日志')

    await wrapper.findAll('button').find((button) => button.text() === '创建内部归属')!.trigger('click')
    await flushPromises()
    expect(mocks.createProfile).toHaveBeenCalledWith({
      display_name: '34车尾端测试日志',
      linked_mr_id: 'uuid-34-ct',
      notes: '',
    })
    wrapper.unmount()
  })

  it('shares one in-flight lightweight context request across rapid repeated opens', async () => {
    let resolveContext!: (value: unknown) => void
    mocks.getImportContext.mockReturnValueOnce(new Promise((resolve) => {
      resolveContext = resolve
    }))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入原始 MESH 日志'))!
    void importButton.trigger('click')
    void importButton.trigger('click')
    await flushPromises()
    expect(mocks.getImportContext).toHaveBeenCalledTimes(1)
    expect(mocks.prepareContext).not.toHaveBeenCalled()

    resolveContext({
      site_id: 'demo',
      revision: 'test',
      profiles: [],
      vehicle_mrs: [],
    })
    await flushPromises()
    wrapper.unmount()
  })
})

describe('Mesh analysis detail behavior', () => {
  it('keeps both RSSI datasets and the shared viewport while only presentation overlays change', async () => {
    const { wrapper, session, activeChart, tracksideChart } = await mountHotfixRssiSession('session-overlay-state')
    const activeCalls = mocks.getActivePath.mock.calls.length
    const tracksideCalls = mocks.getTracksideSignal.mock.calls.length
    const viewport = activeChart.props('syncViewport')
    const cache = tracksideChart.props('seriesCache')

    for (const label of ['显示切换时刻线', '显示切换节点', '显示站点/区间']) {
      await toggleRssiPresentation(wrapper, label)
    }

    expect(mocks.getActivePath).toHaveBeenCalledTimes(activeCalls)
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(tracksideCalls)
    expect(tracksideChart.props('seriesCache')).toBe(cache)
    expect(activeChart.props('syncViewport')).toEqual(viewport)
    expect(wrapper.text()).not.toContain('等待主链 RSSI 图加载完成')

    mocks.getActivePath.mockResolvedValueOnce(hotfixActivePayload(session.session_id, 31))
    ;(wrapper.vm as unknown as { showRssiPeer: boolean }).showRssiPeer = true
    await flushPromises()

    expect(mocks.getActivePath).toHaveBeenLastCalledWith(session.session_id, {
      max_points: 2000,
      radio: 2,
      view_mode: 'overview',
      include_peer: true,
      include_standby_context: true,
      include_events: true,
      include_station_band: true,
    }, expect.any(AbortSignal))
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(tracksideCalls)
    expect(tracksideChart.props('seriesCache')).toBe(cache)

    ;(wrapper.vm as unknown as { showRssiPeer: boolean }).showRssiPeer = false
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledTimes(activeCalls + 1)
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(tracksideCalls)
    wrapper.unmount()
  })

  it('opens a backend compound session id with one click', async () => {
    const session = {
      session_id: 'c4682b2a-ba83-44f2-8bc9-3d2b37c37237:1',
      mr_name: '列车06-MR-CT',
      original_filename: '6CTmeshlog.log',
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [] })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    expect(mocks.routerReplace).toHaveBeenCalledWith({
      name: 'mesh-analysis',
      query: { session_id: session.session_id },
    })
    expect(mocks.getSession).toHaveBeenCalledWith(session.session_id, expect.any(AbortSignal))
    expect(wrapper.text()).not.toContain('分析会话标识无效')
    expect(wrapper.text()).toContain('列车06-MR-CT')
    wrapper.unmount()
  })

  it('makes different session clicks last-wins and reuses one in-flight request for repeats', async () => {
    const sessions = ['mr-a:1', 'mr-b:2', 'mr-c:3', 'mr-d:4'].map((sessionId, index) => ({
      session_id: sessionId,
      mr_name: `列车0${index + 1}-MR-CT`,
      original_filename: `${index + 1}CTmeshlog.log`,
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }))
    const pending = new Map<string, (value: unknown) => void>()
    mocks.listSessions.mockResolvedValue({ items: sessions, total: 4, page: 1, page_size: 50 })
    mocks.getSession.mockImplementation((id: string, signal: AbortSignal) => new Promise((resolve, reject) => {
      pending.set(id, resolve)
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    const buttons = wrapper.findAll('button').filter((button) => button.text() === '查看')

    for (const button of buttons) {
      await button.trigger('click')
      await flushPromises()
    }
    const last = sessions.at(-1)!
    pending.get(last.session_id)?.({ session: last, analysis_params: {}, available_radios: [1], warnings: [], sources: [] })
    await flushPromises()

    expect(mocks.getSession.mock.calls.map((call) => call[0])).toEqual(sessions.map((item) => item.session_id))
    expect(wrapper.text()).toContain(last.mr_name)
    expect(mocks.currentRoute.value.query.session_id).toBe(last.session_id)

    mocks.getSession.mockClear()
    const repeated = sessions[0]
    mocks.currentRoute.value.query = {}
    const repeatedPending: Array<(value: unknown) => void> = []
    mocks.getSession.mockImplementation((_id: string, _signal: AbortSignal) => new Promise((resolve) => { repeatedPending.push(resolve) }))
    await wrapper.find('.sessions-toggle').trigger('click')
    await nextTick()
    const firstButton = wrapper.findAll('button').filter((button) => button.text() === '查看')[0]
    for (let index = 0; index < 10; index += 1) void firstButton.trigger('click')
    await flushPromises()
    expect(mocks.getSession).toHaveBeenCalledTimes(1)
    repeatedPending[0]?.({ session: repeated, analysis_params: {}, available_radios: [1], warnings: [], sources: [] })
    await flushPromises()
    wrapper.unmount()
  })

  it('keeps the loaded RSSI session, cache, viewport state, and scroll position across 20 route deactivations', async () => {
    let frameId = 0
    const cancelledFrames = new Set<number>()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++frameId
      queueMicrotask(() => {
        if (!cancelledFrames.has(id)) callback(performance.now())
      })
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => { cancelledFrames.add(id) })
    vi.stubGlobal('IntersectionObserver', undefined)

    const session = {
      session_id: 'session-keep-alive',
      mr_name: '列车06-MR-CT',
      original_filename: '6CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:10:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 7, source_action_id: 'source-1', source_id: 'source-1' }],
    })
    mocks.listBuildOrder.mockResolvedValue({
      items: [{
        sequence: 1,
        anchor_link_id: 10,
        source_file_id: 7,
        local_radio: 1,
        peer_ap_name: 'AP-1',
        active_peer_mac: '0000-0000-0010',
        build_start_time: chartViewport.full_start_time,
        build_end_time: chartViewport.full_end_time,
        build_result: 'normal',
      }],
      total: 1,
      page: 1,
      page_size: 100,
    })
    mocks.getActivePath.mockResolvedValue({
      mode: 'active_path',
      anchor: null,
      points: [
        { timestamp: chartViewport.full_start_time, local_radio: 1, local_rssi: 30 },
        { timestamp: chartViewport.start_time, local_radio: 1, local_rssi: 32 },
        { timestamp: chartViewport.end_time, local_radio: 1, local_rssi: 34 },
        { timestamp: chartViewport.full_end_time, local_radio: 1, local_rssi: 31 },
      ],
      events: [],
      location_segments: [],
      total_points: 4,
      returned_points: 4,
      downsampled: false,
      summary: {},
      time_from: null,
      time_to: null,
    })

    const meshVisible = ref(true)
    const OrdinaryPage = defineComponent(() => () => h('div', { 'data-ordinary-page': '' }))
    const RouteHost = defineComponent({
      setup() {
        return () => h('main', { class: 'app-main' }, [
          h(KeepAlive, { max: 1 }, {
            default: () => meshVisible.value
              ? h(MeshAnalysisView, { key: 'mesh-analysis' })
              : null,
          }),
          meshVisible.value ? null : h(OrdinaryPage),
        ])
      },
    })
    const wrapper = mount(RouteHost, {
      attachTo: document.body,
      global: { stubs, directives: { loading: () => undefined } },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()

    const meshUid = wrapper.getComponent(MeshAnalysisView).vm.$.uid
    const activeRssiChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === 'active')!
    const tracksideChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === '')!
    const initialCache = tracksideChart.props('seriesCache') as TracksideSeriesCache
    const initialActiveCalls = mocks.getActivePath.mock.calls.length
    const initialTracksideCalls = mocks.getTracksideSignal.mock.calls.length
    const initialSessionCalls = mocks.getSession.mock.calls.length
    const initialResizeCalls = mocks.chartResize.mock.calls.length
    const appMain = wrapper.get('.app-main').element as HTMLElement
    appMain.scrollTop = 720

    for (let index = 0; index < 20; index += 1) {
      meshVisible.value = false
      await nextTick()
      await flushPromises()
      expect(activeRssiChart.props('active')).toBe(false)
      expect(tracksideChart.props('active')).toBe(false)
      expect(initialCache.disposed).toBe(false)
      appMain.scrollTop = 0

      meshVisible.value = true
      await nextTick()
      await flushPromises()
      expect(wrapper.getComponent(MeshAnalysisView).vm.$.uid).toBe(meshUid)
      expect(wrapper.get('.detail-tabs').attributes('modelvalue')).toBe('rssi')
      expect(activeRssiChart.props('active')).toBe(true)
      expect(tracksideChart.props('active')).toBe(true)
      expect(tracksideChart.props('seriesCache')).toBe(initialCache)
      expect(appMain.scrollTop).toBe(720)
    }

    expect(mocks.getActivePath).toHaveBeenCalledTimes(initialActiveCalls)
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(initialTracksideCalls)
    expect(mocks.getSession).toHaveBeenCalledTimes(initialSessionCalls)
    expect(mocks.chartResize.mock.calls.length).toBeGreaterThanOrEqual(initialResizeCalls + 40)

    window.dispatchEvent(new CustomEvent('netconsole:before-site-switch', { detail: { targetSiteId: 'line-b' } }))
    await flushPromises()
    expect(initialCache.disposed).toBe(true)
    wrapper.unmount()
    expect(initialCache.disposed).toBe(true)
  })

  it('restarts an aborted active RSSI request after KeepAlive resumes the page', async () => {
    const session = {
      session_id: 'session-resume-active-request',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: chartViewport.full_start_time,
      last_sample_time: chartViewport.full_end_time,
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const requestSignals: AbortSignal[] = []
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 7, source_action_id: 'source-resume' }],
    })
    mocks.listBuildOrder.mockResolvedValue({
      items: [{
        sequence: 1,
        anchor_link_id: 10,
        local_radio: 1,
        peer_ap_name: 'AP-1',
        active_peer_mac: '0000-0000-0010',
        build_start_time: session.first_sample_time,
        build_end_time: session.last_sample_time,
        build_result: 'normal',
      }],
      total: 1,
      page: 1,
      page_size: 100,
    })
    mocks.getActivePath.mockImplementation((_id, _values, signal: AbortSignal) => {
      requestSignals.push(signal)
      if (requestSignals.length === 1) {
        return new Promise((_resolve, reject) => {
          signal.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          )
        })
      }
      return Promise.resolve({
        mode: 'active_path',
        anchor: null,
        points: [{ timestamp: session.first_sample_time, local_radio: 1, local_rssi: 30 }],
        events: [],
        location_segments: [],
        total_points: 1,
        returned_points: 1,
        downsampled: false,
        summary: { sample_count: 1 },
        time_from: null,
        time_to: null,
      })
    })

    const meshVisible = ref(true)
    const RouteHost = defineComponent({
      setup() {
        return () => h('main', { class: 'app-main' }, [
          h(KeepAlive, { max: 1 }, {
            default: () => meshVisible.value
              ? h(MeshAnalysisView, { key: 'mesh-analysis' })
              : null,
          }),
          meshVisible.value ? null : h('div', { 'data-ordinary-page': '' }),
        ])
      },
    })
    const wrapper = mount(RouteHost, {
      attachTo: document.body,
      global: { stubs, directives: { loading: () => undefined } },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledTimes(1)

    meshVisible.value = false
    await nextTick()
    await flushPromises()
    expect(requestSignals[0]?.aborted).toBe(true)

    meshVisible.value = true
    await nextTick()
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('主链 RSSI 数据尚未加载')
    wrapper.unmount()
  })

  it('resumes task polling and automatically refreshes the current session after a background rebuild', async () => {
    vi.useFakeTimers()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++frameId
      queueMicrotask(() => callback(performance.now()))
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', () => undefined)
    vi.stubGlobal('IntersectionObserver', undefined)
    const session = {
      session_id: 'session-background-update',
      mr_name: '列车06-MR-CW',
      original_filename: '6CWmeshlog.log',
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const runningTask = {
      task_id: 'mesh-rebuild-1',
      action: 'mesh_source_rebuild',
      status: 'RUNNING',
      message: '',
      error_message: '',
      result_summary: {},
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 8, source_action_id: 'source-2', source_id: 'source-2' }],
    })
    mocks.recoverTasks.mockResolvedValue([runningTask])
    mocks.getTask.mockResolvedValue({
      ...runningTask,
      status: 'COMPLETED',
      result_summary: { session_id: session.session_id },
    })
    mocks.listBuildOrder
      .mockResolvedValueOnce({
        items: [{ sequence: 1, peer_ap_name: '', identity_status: 'unresolved' }],
        total: 1,
        page: 1,
        page_size: 100,
      })
      .mockResolvedValue({
        items: [{ sequence: 1, peer_ap_name: '轨旁AP-24', identity_status: 'matched' }],
        total: 1,
        page: 1,
        page_size: 100,
      })

    const meshVisible = ref(true)
    const RouteHost = defineComponent({
      setup() {
        return () => h('main', { class: 'app-main' }, [
          h(KeepAlive, { max: 1 }, {
            default: () => meshVisible.value
              ? h(MeshAnalysisView, { key: 'mesh-analysis' })
              : null,
          }),
          meshVisible.value ? null : h('div', { 'data-ordinary-page': '' }),
        ])
      },
    })
    const wrapper = mount(RouteHost, {
      attachTo: document.body,
      global: { stubs, directives: { loading: () => undefined } },
    })
    try {
      await flushPromises()
      await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
      await flushPromises()
      expect(mocks.getSession).toHaveBeenCalledTimes(1)

      meshVisible.value = false
      await nextTick()
      await flushPromises()
      await vi.advanceTimersByTimeAsync(10_000)
      expect(mocks.getTask).not.toHaveBeenCalled()

      meshVisible.value = true
      await nextTick()
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1_000)
      await flushPromises()

      expect(mocks.getTask).toHaveBeenCalledTimes(1)
      expect(mocks.getSession).toHaveBeenCalledTimes(2)
      expect(wrapper.text()).not.toContain('当前仍显示离开页面前的结果')
      expect(wrapper.text()).not.toContain('立即重试')
      const buildOrderTable = wrapper.findAllComponents(dataTableStub).find(
        (table) => table.props('tableId') === 'mesh-analysis-active-build-order:v2',
      )!
      expect(buildOrderTable.props('data')).toEqual([
        expect.objectContaining({ peer_ap_name: '轨旁AP-24', identity_status: 'matched' }),
      ])
      expect(wrapper.getComponent(MeshAnalysisView).find('.detail-tabs').attributes('modelvalue')).toBe('build-order')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('automatically refreshes the selected session when a rebuild completes on the active page', async () => {
    vi.useFakeTimers()
    const session = refreshTestSession('session-active-completion')
    const runningTask = {
      task_id: 'mesh-active-completion',
      action: 'mesh_source_rebuild',
      status: 'RUNNING',
      message: '',
      error_message: '',
      result_summary: {},
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue(refreshTestDetail(session))
    mocks.listBuildOrder
      .mockResolvedValueOnce(refreshTestBuildOrder(''))
      .mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    mocks.recoverTasks.mockResolvedValue([runningTask])
    mocks.getTask.mockResolvedValue({
      ...runningTask,
      status: 'COMPLETED',
      result_summary: {
        session_id: session.session_id,
        identity_remap: { matched_mapping_count: 2, updated_link_row_count: 6473 },
      },
    })

    const wrapper = mountRefreshTestView()
    try {
      await flushPromises()
      await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      await flushPromises()

      expect(mocks.getSession).toHaveBeenCalledTimes(2)
      const buildOrderTable = wrapper.findAllComponents(dataTableStub).find(
        (table) => table.props('tableId') === 'mesh-analysis-active-build-order:v2',
      )!
      expect(buildOrderTable.props('data')).toEqual([
        expect.objectContaining({ peer_ap_name: '轨旁AP-24', identity_status: 'matched' }),
      ])
      expect(wrapper.text()).not.toContain('立即重试')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('queues a completed rebuild received while inactive and consumes it on activation', async () => {
    vi.useFakeTimers()
    const session = refreshTestSession('session-inactive-completion')
    const runningTask = {
      task_id: 'mesh-inactive-completion',
      action: 'mesh_source_rebuild',
      status: 'RUNNING',
      message: '',
      error_message: '',
      result_summary: {},
    }
    const taskRequest = deferred<Record<string, unknown>>()
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue(refreshTestDetail(session))
    mocks.listBuildOrder
      .mockResolvedValueOnce(refreshTestBuildOrder(''))
      .mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    mocks.recoverTasks.mockResolvedValue([runningTask])
    mocks.getTask.mockImplementation(() => taskRequest.promise)

    const meshVisible = ref(true)
    const RouteHost = defineComponent({
      setup() {
        return () => h(KeepAlive, { max: 1 }, {
          default: () => meshVisible.value ? h(MeshAnalysisView, { key: 'mesh-analysis' }) : null,
        })
      },
    })
    const wrapper = mount(RouteHost, {
      global: { stubs, directives: { loading: () => undefined } },
    })
    try {
      await flushPromises()
      await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      meshVisible.value = false
      await nextTick()
      taskRequest.resolve({
        ...runningTask,
        status: 'COMPLETED',
        result_summary: { session_id: session.session_id },
      })
      await flushPromises()
      expect(mocks.getSession).toHaveBeenCalledTimes(1)

      meshVisible.value = true
      await nextTick()
      await flushPromises()

      expect(mocks.getSession).toHaveBeenCalledTimes(2)
      expect(wrapper.text()).not.toContain('立即重试')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('uses the top refresh action for both overview and the current session detail', async () => {
    const session = refreshTestSession('session-manual-refresh')
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue(refreshTestDetail(session))
    mocks.listBuildOrder
      .mockResolvedValueOnce(refreshTestBuildOrder(''))
      .mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    const wrapper = mountRefreshTestView()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    mocks.getOverview.mockClear()
    mocks.getSession.mockClear()
    mocks.listBuildOrder.mockClear()
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(mocks.getOverview).toHaveBeenCalledTimes(1)
    expect(mocks.getSession).toHaveBeenCalledWith(session.session_id, expect.any(AbortSignal))
    expect(mocks.listBuildOrder).toHaveBeenCalledWith(
      session.session_id,
      expect.objectContaining({ page: 1 }),
      expect.any(AbortSignal),
    )
    const buildOrderTable = wrapper.findAllComponents(dataTableStub).find(
      (table) => table.props('tableId') === 'mesh-analysis-active-build-order:v2',
    )!
    expect(buildOrderTable.props('data')).toEqual([
      expect.objectContaining({ peer_ap_name: '轨旁AP-24' }),
    ])
    wrapper.unmount()
  })

  it('refreshes only the overview when no session is selected', async () => {
    const wrapper = mountRefreshTestView()
    await flushPromises()
    mocks.getOverview.mockClear()
    mocks.getSession.mockClear()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(mocks.getOverview).toHaveBeenCalledTimes(1)
    expect(mocks.getSession).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not interrupt the current session when another session rebuild completes', async () => {
    vi.useFakeTimers()
    const current = refreshTestSession('session-current')
    const other = refreshTestSession('session-other', '列车24-MR-CW')
    const runningTask = {
      task_id: 'mesh-other-session',
      action: 'mesh_source_rebuild',
      status: 'RUNNING',
      message: '',
      error_message: '',
      result_summary: {},
    }
    mocks.listSessions.mockResolvedValue({ items: [current, other], total: 2, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue(refreshTestDetail(current))
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    mocks.recoverTasks.mockResolvedValue([runningTask])
    mocks.getTask.mockResolvedValue({
      ...runningTask,
      status: 'COMPLETED',
      result_summary: { session_id: other.session_id },
    })
    const wrapper = mountRefreshTestView()
    try {
      await flushPromises()
      await wrapper.findAll('button').filter((button) => button.text() === '查看')[0].trigger('click')
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      await flushPromises()

      expect(mocks.getSession).toHaveBeenCalledTimes(1)
      expect(wrapper.text()).toContain(current.mr_name)
      expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('build-order')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('processes one terminal task only once across repeated activations', async () => {
    vi.useFakeTimers()
    const session = refreshTestSession('session-terminal-once')
    const runningTask = {
      task_id: 'mesh-terminal-once',
      action: 'mesh_source_rebuild',
      status: 'RUNNING',
      message: '',
      error_message: '',
      result_summary: {},
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue(refreshTestDetail(session))
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    mocks.recoverTasks.mockResolvedValue([runningTask])
    mocks.getTask.mockResolvedValue({
      ...runningTask,
      status: 'COMPLETED',
      result_summary: { session_id: session.session_id },
    })
    const meshVisible = ref(true)
    const RouteHost = defineComponent({
      setup() {
        return () => h(KeepAlive, { max: 1 }, {
          default: () => meshVisible.value ? h(MeshAnalysisView, { key: 'mesh-analysis' }) : null,
        })
      },
    })
    const wrapper = mount(RouteHost, { global: { stubs, directives: { loading: () => undefined } } })
    try {
      await flushPromises()
      await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      await flushPromises()
      expect(mocks.getSession).toHaveBeenCalledTimes(2)

      for (let index = 0; index < 2; index += 1) {
        meshVisible.value = false
        await nextTick()
        meshVisible.value = true
        await nextTick()
        await flushPromises()
      }

      expect(mocks.getSession).toHaveBeenCalledTimes(2)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('keeps links and RSSI active while refreshing their latest data', async () => {
    const session = refreshTestSession('session-tab-refresh')
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue(refreshTestDetail(session))
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    mocks.listLinks
      .mockResolvedValueOnce({ items: [{ record_id: 1, peer_ap_name: '' }], total: 1, page: 1, page_size: 100 })
      .mockResolvedValue({ items: [{ record_id: 1, peer_ap_name: '轨旁AP-24' }], total: 1, page: 1, page_size: 100 })
    const wrapper = mountRefreshTestView()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    const detailTabs = wrapper.findAllComponents(tabsStub).find((tabs) => tabs.classes().includes('detail-tabs'))!
    const linkTable = wrapper.findAllComponents(dataTableStub).find(
      (table) => table.props('tableId') === 'mesh-analysis-link-details:v3',
    )!
    detailTabs.vm.$emit('update:modelValue', 'links')
    await flushPromises()
    await vi.waitFor(() => expect(mocks.listLinks).toHaveBeenCalledTimes(1))
    mocks.listLinks.mockClear()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('links')
    expect(mocks.listLinks).toHaveBeenCalledTimes(1)
    const refreshedLinkTable = wrapper.findAllComponents(dataTableStub).find(
      (table) => table.props('tableId') === 'mesh-analysis-link-details:v3',
    )!
    expect(refreshedLinkTable.props('data')).toEqual([
      expect.objectContaining({ peer_ap_name: '轨旁AP-24' }),
    ])

    detailTabs.vm.$emit('update:modelValue', 'build-order')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()
    mocks.getActivePath.mockClear()
    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('rssi')
    expect(mocks.getActivePath).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('prevents a late refresh response from replacing a newly selected session', async () => {
    const first = refreshTestSession('session-refresh-race-a')
    const second = refreshTestSession('session-refresh-race-b', '列车24-MR-CW')
    const lateRefresh = deferred<ReturnType<typeof refreshTestDetail>>()
    let firstRequestCount = 0
    mocks.listSessions.mockResolvedValue({ items: [first, second], total: 2, page: 1, page_size: 50 })
    mocks.getSession.mockImplementation((id: string) => {
      if (id === first.session_id) {
        firstRequestCount += 1
        if (firstRequestCount === 2) return lateRefresh.promise
        return Promise.resolve(refreshTestDetail(first))
      }
      return Promise.resolve(refreshTestDetail(second))
    })
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    const wrapper = mountRefreshTestView()
    await flushPromises()
    const viewButtons = wrapper.findAll('button').filter((button) => button.text() === '查看')
    await viewButtons[0].trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()
    await viewButtons[1].trigger('click')
    await flushPromises()
    lateRefresh.resolve(refreshTestDetail(first))
    await flushPromises()

    expect(wrapper.text()).toContain(second.mr_name)
    expect(wrapper.text()).not.toContain('当前：列车24-MR-CT')
    expect(mocks.currentRoute.value.query.session_id).toBe(second.session_id)
    wrapper.unmount()
  })

  it('keeps a failed result refresh retryable and clears the warning after retry succeeds', async () => {
    const session = refreshTestSession('session-refresh-retry')
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession
      .mockResolvedValueOnce(refreshTestDetail(session))
      .mockRejectedValueOnce(new Error('当前详情请求失败'))
      .mockResolvedValue(refreshTestDetail(session))
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    const wrapper = mountRefreshTestView()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('AP 身份映射已完成，但当前页面刷新失败')
    expect(wrapper.text()).toContain('立即重试')

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()
    expect(mocks.getSession).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).not.toContain('AP 身份映射已完成，但当前页面刷新失败')
    expect(wrapper.text()).not.toContain('立即重试')
    wrapper.unmount()
  })

  it('closes a selected session that no longer exists during a result refresh', async () => {
    const session = refreshTestSession('session-refresh-deleted')
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession
      .mockResolvedValueOnce(refreshTestDetail(session))
      .mockRejectedValueOnce(new ApiRequestError('来源不存在', 404, 'MESH_SESSION_NOT_FOUND'))
    mocks.listBuildOrder.mockResolvedValue(refreshTestBuildOrder('轨旁AP-24'))
    const wrapper = mountRefreshTestView()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前 MESH 分析来源已不存在')
    expect(wrapper.find('.detail-card').exists()).toBe(false)
    expect(mocks.currentRoute.value.query.session_id).toBeUndefined()
    wrapper.unmount()
  })

  it('refreshes imported sources after the catalog index catches up', async () => {
    vi.useFakeTimers()
    const session = {
      session_id: 'profile-1:7',
      mr_name: '列车34-MR-CT',
      train_name: '列车34',
      original_filename: '2026_07_28_1meshlog.log',
      first_sample_time: '2026-07-28 10:00:00.000',
      last_sample_time: '2026-07-28 10:00:01.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const pendingOverview = {
      summary: {
        site_id: 'demo', index_status: 'pending', indexed_session_count: 0,
        pending_session_count: 1, index_updated_at: null, session_count: 0,
        train_count: 0, mr_count: 0, link_record_count: 0, active_link_count: 0,
        standby_link_count: 0, switch_event_count: 0, short_link_count: 0,
        pingpong_count: 0, rssi_anomaly_count: 0, channel_busy_anomaly_count: 0,
        unmatched_ap_count: 0, warning_session_count: 0, latest_analysis_time: null,
      },
      sessions: { items: [], total: 0, page: 1, page_size: 50 },
    }
    const readyOverview = {
      summary: {
        ...pendingOverview.summary, index_status: 'ready', indexed_session_count: 1,
        pending_session_count: 0, session_count: 1, train_count: 1, mr_count: 1,
        link_record_count: 10, active_link_count: 8, standby_link_count: 2,
      },
      sessions: { items: [session], total: 1, page: 1, page_size: 50 },
    }
    mocks.getOverview
      .mockResolvedValueOnce(pendingOverview)
      .mockResolvedValueOnce(pendingOverview)
      .mockResolvedValue(readyOverview)
    const runningTask = {
      task_id: 'mesh-bundle-refresh-1',
      action: 'mesh_bundle_import',
      status: 'RUNNING',
      message: '',
      error_message: '',
      result_summary: {},
    }
    mocks.recoverTasks.mockResolvedValueOnce([runningTask])
    mocks.getTask.mockResolvedValueOnce({
      ...runningTask,
      status: 'COMPLETED',
      result_summary: { created_session_ids: [session.session_id] },
    })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [],
    })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    try {
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      await flushPromises()
      await vi.advanceTimersByTimeAsync(500)
      await flushPromises()

      expect(mocks.getOverview.mock.calls.length).toBeGreaterThanOrEqual(3)
      expect(wrapper.text()).toContain('分析会话 · 1 个来源 · 1 列车 / 1 MR')
      expect(wrapper.text()).toContain('列车34-MR-CT')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('keeps the large trackside payload outside Vue deep reactivity', () => {
    expect(meshAnalysisViewSource).toContain('const tracksideSignal = shallowRef<MeshTracksideSignalChartData | null>(null)')
    expect(meshAnalysisViewSource).toContain('markRaw(await getMeshTracksideSignalChart(')
  })

  it('separates route pause from final cache disposal', () => {
    const pauseBody = meshAnalysisViewSource.match(
      /function pauseMeshAnalysisPage\(\): void \{([\s\S]*?)\n\}/,
    )?.[1] || ''
    const disposeBody = meshAnalysisViewSource.match(
      /function disposeMeshAnalysisPage\(\): void \{([\s\S]*?)\n\}/,
    )?.[1] || ''
    expect(meshAnalysisViewSource).toContain('onDeactivated(pauseMeshAnalysisPage)')
    expect(meshAnalysisViewSource).toContain('onBeforeUnmount(disposeMeshAnalysisPage)')
    expect(pauseBody).toContain('stopOverviewRefresh()')
    expect(pauseBody).toContain('stopTaskPolling()')
    expect(pauseBody).not.toMatch(/releaseTracksideResources|disposeTracksideSeriesCache|openSession|loadFullRssiCharts/)
    expect(disposeBody).toContain('releaseTracksideResources()')
    expect(meshAnalysisViewSource).toContain(':active="pageActive && activeTab === \'rssi\'')
  })

  it('places RSSI deltas before AP MAC and shows the unified switch classification', async () => {
    const session = {
      session_id: 'session-1', mr_name: '列车06-MR-CT', original_filename: '6CTmeshlog.log', first_sample_time: '', last_sample_time: '',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [] })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    const tables = wrapper.findAllComponents(dataTableStub)
    const linkTable = tables.find((table) => table.props('tableId') === 'mesh-analysis-link-details:v3')!
    const resolvedLinkColumns = linkTable.props('columns') as Array<{ key: string; fixed?: string; width?: number }>
    const linkKeys = resolvedLinkColumns.map((column) => column.key)
    expect(linkKeys.slice(0, 10)).toEqual([
      'record_id', 'timestamp', 'timestamp_tag', 'local_radio', 'link_role', 'peer_mac_raw', 'peer_mac',
      'peer_ap_name', 'local_rssi_db', 'peer_rssi_db',
    ])
    expect(linkKeys).toContain('peer_ap_mac')
    expect(resolvedLinkColumns.filter((column) => column.fixed === 'left').map((column) => column.key)).toEqual(['record_id'])
    expect(resolvedLinkColumns.find((column) => column.key === 'section')?.width).toBe(190)
    const switchTable = tables.find((table) => table.props('tableId') === 'mesh-analysis-switch-events:v3')!
    const switchKeys = (switchTable.props('columns') as Array<{ key: string }>).map((column) => column.key)
    expect(switchKeys).toEqual([
      'timestamp', 'local_radio', 'from_ap_name', 'from_peer_mac', 'to_ap_name', 'to_peer_mac',
      'rssi_change', 'new_active_duration_ms', 'stability_threshold_ms', 'switch_result', 'is_pingpong', 'station', 'section',
    ])
    expect(switchKeys).not.toContain('event_type')
    expect(switchKeys).not.toContain('is_short_link')
    wrapper.unmount()
  })

  it('starts the independent link detail export for the selected source', async () => {
    const session = {
      session_id: 'session-1', mr_name: '列车34-MR-CW', original_filename: '34-CW.log', first_sample_time: '', last_sample_time: '',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [], warnings: [], sources: [{ source_file_id: 1, source_action_id: 'source-action-1', source_id: 'source-action-1', exists: true, rebuild_capability: 'ready' }] })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '导出链路明细')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '开始导出')!.trigger('click')
    await flushPromises()

    expect(mocks.exportDetails).toHaveBeenCalledWith('session-1', 1, expect.objectContaining({ link_time_window: 4000, link_hold_rssi: 22, link_establish_threshold: 4 }))
    expect(mocks.routerPush).toHaveBeenCalledWith({ name: 'tasks', query: { module: 'rail', task_id: 'mesh-export-1' } })
    wrapper.unmount()
  })

  it('pages switch events through the backend and uses the available table height', async () => {
    const session = {
      session_id: 'session-switch-page', mr_name: '列车34-MR-CW', original_filename: '34-CW.log', first_sample_time: '', last_sample_time: '',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 1, source_action_id: 'source-switch-page', exists: true, rebuild_capability: 'ready' }],
    })
    mocks.listSwitchEvents.mockImplementation(async (_sessionId: string, values: { page: number; page_size: number }) => ({
      items: [{ event_id: `switch-${values.page}`, timestamp: '2026-07-20 10:00:00.000' }],
      total: 8_490,
      page: values.page,
      page_size: values.page_size,
    }))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    const detailTabs = wrapper.findAllComponents(tabsStub)
      .find((tabs) => tabs.classes().includes('detail-tabs'))!
    await detailTabs.vm.$emit('update:modelValue', 'switches')
    await flushPromises()

    expect(mocks.listSwitchEvents).toHaveBeenLastCalledWith('session-switch-page', {
      page: 1,
      page_size: 100,
      radio: null,
      result_filter: null,
    })
    const switchPane = wrapper.get('#pane-switches')
    const switchTable = switchPane.getComponent(dataTableStub)
    expect(switchTable.attributes('height')).not.toBe('430')
    const pagination = switchPane.getComponent(paginationStub)
    expect(pagination.attributes('data-total')).toBe('8490')
    expect(pagination.attributes('data-page-size')).toBe('100')

    await pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(mocks.listSwitchEvents).toHaveBeenLastCalledWith('session-switch-page', {
      page: 2,
      page_size: 100,
      radio: null,
      result_filter: null,
    })

    await pagination.vm.$emit('size-change', 200)
    await flushPromises()
    expect(mocks.listSwitchEvents).toHaveBeenLastCalledWith('session-switch-page', {
      page: 1,
      page_size: 200,
      radio: null,
      result_filter: null,
    })

    const radioSelect = switchPane.get('select[data-placeholder="Radio"]')
    await radioSelect.setValue('1')
    await flushPromises()
    expect(mocks.listSwitchEvents).toHaveBeenLastCalledWith('session-switch-page', {
      page: 1,
      page_size: 200,
      radio: 1,
      result_filter: null,
    })

    const resultSelect = switchPane.get('select[data-placeholder="切换分类"]')
    await resultSelect.setValue('pingpong')
    await flushPromises()
    expect(mocks.listSwitchEvents).toHaveBeenLastCalledWith('session-switch-page', {
      page: 1,
      page_size: 200,
      radio: 1,
      result_filter: 'pingpong',
    })
    wrapper.unmount()
  })

  it('submits parsed-only deletion from a source row after the second confirmation', async () => {
    const session = {
      session_id: 'session-delete',
      mr_name: '列车34-MR-CW',
      train_name: '列车34',
      original_filename: '34-CW.log',
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 1,
      link_record_count: 974,
    }
    const source = {
      source_file_id: 7,
      source_action_id: 'source-delete-1',
      source_id: 'source-delete-1',
      size_bytes: 1024,
      exists: true,
      rebuild_capability: 'ready',
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [source],
    })
    mocks.batchDeleteSources.mockResolvedValueOnce({
      action: 'mesh_analysis_sources_delete',
      task_id: 'mesh-delete-batch-1',
      status: 'COMPLETED',
      result_summary: {
        requested_count: 1,
        success_count: 1,
        failed_count: 0,
        skipped_count: 0,
        delete_raw_archive: false,
        items: [{
          session_id: session.session_id,
          status: 'parsed_deleted',
          success: true,
          delete_raw_archive: false,
        }],
      },
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '删除当前来源')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('仅删除解析结果')
    expect(wrapper.text()).toContain('解析记录 974')

    await wrapper.findAll('button').find((button) => button.text() === '继续并二次确认')!.trigger('click')
    await flushPromises()

    expect(mocks.batchDeleteSources).toHaveBeenCalledOnce()
    expect(mocks.batchDeleteSources).toHaveBeenCalledWith(['session-delete'], {
      deleteRawArchive: false,
      deleteParsedData: true,
      deleteGeneratedReports: true,
    })
    expect(mocks.deleteSource).not.toHaveBeenCalled()
    expect(mocks.routerPush).toHaveBeenCalledWith({ name: 'tasks', query: { module: 'rail', task_id: 'mesh-delete-batch-1' } })
    expect(wrapper.text()).toContain('分析会话 · 1 个来源 · 1 列车 / 1 MR')
    expect(wrapper.find('.detail-card').exists()).toBe(true)
    wrapper.unmount()
  })

  it('submits one batch task for multiple sources and keeps rows until the task finishes', async () => {
    const sessions = ['session-delete-a', 'session-delete-b'].map((sessionId, index) => ({
      session_id: sessionId,
      mr_name: `列车3${index + 4}-MR-CW`,
      train_name: `列车3${index + 4}`,
      original_filename: `${index + 34}-CW.log`,
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
      link_record_count: 10,
    }))
    mocks.listSessions.mockResolvedValue({ items: sessions, total: 2, page: 1, page_size: 50 })
    mocks.getSession.mockImplementation(async (sessionId: string) => ({
      session: sessions.find((item) => item.session_id === sessionId),
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{
        source_file_id: sessionId.endsWith('a') ? 1 : 2,
        source_action_id: `source-${sessionId}`,
        exists: true,
        rebuild_capability: 'ready',
      }],
    }))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    const sessionTable = wrapper.findAllComponents(dataTableStub)
      .find((table) => table.props('tableId') === 'mesh-analysis-sessions:v3')!
    await sessionTable.vm.$emit('selection-change', sessions)
    await wrapper.findAll('button').find((button) => button.text() === '删除选中')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '继续并二次确认')!.trigger('click')
    await flushPromises()

    expect(mocks.batchDeleteSources).toHaveBeenCalledOnce()
    expect(mocks.batchDeleteSources).toHaveBeenCalledWith(
      ['session-delete-a', 'session-delete-b'],
      { deleteRawArchive: false, deleteParsedData: true, deleteGeneratedReports: true },
    )
    expect(mocks.deleteSource).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('共 2 个来源')
    wrapper.unmount()
  })

  it('removes the local MESH task card when the global task store dismisses it', async () => {
    mocks.recoverTasks.mockResolvedValueOnce([{
      task_id: 'mesh-failed-dismissed',
      action: 'mesh_link_detail_export',
      status: 'FAILED',
      message: '历史导出失败',
      error_message: '历史导出失败',
      result_summary: {},
    }])
    mocks.taskStore?.tasks.push({
      id: 'mesh-failed-dismissed',
      type: 'mesh_link_detail_export',
      name: 'MESH 链路明细导出',
      status: 'FAILED',
      progress: 100,
      message: '历史导出失败',
      error_summary: '历史导出失败',
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    expect(wrapper.text()).toContain('mesh-failed-dismissed')
    mocks.taskStore?.tasks.splice(0)
    await nextTick()

    expect(wrapper.text()).not.toContain('mesh-failed-dismissed')
    wrapper.unmount()
    expect(mocks.taskStoreAcquirePolling).toHaveBeenCalledWith('mesh-analysis-view')
    expect(mocks.taskStoreReleasePolling).toHaveBeenCalledWith('mesh-analysis-view')
  })

  it('waits for an explicit identity projection refresh when a healthy source revision is stale', async () => {
    const session = {
      session_id: 'session-identity-stale',
      mr_name: '列车07-MR-CT',
      train_name: '列车07',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 1,
      report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [{ code: 'identity_mapping_stale', message: '身份映射需要刷新', severity: 'warning' }],
      sources: [{
        source_file_id: 7,
        source_action_id: 'source-stale-1',
        source_id: 'source-stale-1',
        exists: true,
        rebuild_capability: 'ready',
        identity_mapping_status: 'identity_stale',
      }],
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.detail-heading .warning-summary-trigger').exists()).toBe(true)
    expect(wrapper.find('.warning-summary').exists()).toBe(false)
    expect(wrapper.text()).toContain('打开页面不会自动提交任务')
    expect(mocks.startMaintenance).not.toHaveBeenCalled()
    expect(mocks.rebuildAnalysis).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text() === '立即刷新身份映射')!.trigger('click')
    await flushPromises()

    expect(mocks.startMaintenance).toHaveBeenCalledOnce()
    expect(mocks.startMaintenance).toHaveBeenCalledWith(
      'session-identity-stale',
      { kind: 'identity_projection_refresh' },
    )
    expect(mocks.taskStoreRefresh).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not restore a deleted source when an older overview request finishes later', async () => {
    const session = {
      session_id: 'session-delete',
      mr_name: '列车34-MR-CW',
      train_name: '列车34',
      original_filename: '34-CW.log',
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
      link_record_count: 10,
    }
    const source = {
      source_file_id: 7,
      source_action_id: 'source-delete-1',
      source_id: 'source-delete-1',
      size_bytes: 1024,
      exists: true,
      rebuild_capability: 'ready',
    }
    let resolveStaleOverview!: (value: unknown) => void
    const staleOverview = new Promise((resolve) => { resolveStaleOverview = resolve })
    mocks.getOverview
      .mockResolvedValueOnce({
        summary: {
          site_id: 'demo', index_status: 'ready', indexed_session_count: 1,
          pending_session_count: 0, index_updated_at: null, session_count: 1,
          train_count: 1, mr_count: 1,
        },
        sessions: { items: [session], total: 1, page: 1, page_size: 50 },
      })
      .mockImplementationOnce(() => staleOverview)
      .mockResolvedValue({
        summary: {
          site_id: 'demo', index_status: 'ready', indexed_session_count: 0,
          pending_session_count: 0, index_updated_at: null, session_count: 0,
          train_count: 0, mr_count: 0,
        },
        sessions: { items: [], total: 0, page: 1, page_size: 50 },
      })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [],
      warnings: [],
      sources: [source],
    })
    mocks.batchDeleteSources.mockResolvedValueOnce({
      action: 'mesh_analysis_sources_delete',
      task_id: 'mesh-delete-race-1',
      status: 'COMPLETED',
      result_summary: {
        requested_count: 1,
        success_count: 1,
        failed_count: 0,
        skipped_count: 0,
        delete_raw_archive: true,
        items: [{
          session_id: session.session_id,
          status: 'deleted',
          success: true,
          delete_raw_archive: true,
        }],
      },
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === '删除')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '继续并二次确认')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('共 0 个来源')

    resolveStaleOverview({
      summary: {
        site_id: 'demo', index_status: 'ready', indexed_session_count: 1,
        pending_session_count: 0, index_updated_at: null, session_count: 1,
        train_count: 1, mr_count: 1,
      },
      sessions: { items: [session], total: 1, page: 1, page_size: 50 },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('共 0 个来源')
    expect(wrapper.text()).not.toContain('34-CW.log')
    wrapper.unmount()
  })

  it('shows the normal empty state when a missing MESH directory returns an empty overview', async () => {
    mocks.getOverview.mockResolvedValueOnce({
      summary: {
        site_id: 'demo', index_status: 'ready', indexed_session_count: 0,
        pending_session_count: 0, index_updated_at: null, session_count: 0,
        train_count: 0, mr_count: 0,
      },
      sessions: { items: [], total: 0, page: 1, page_size: 50 },
    })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    expect(wrapper.text()).toContain('分析会话 · 0 个来源 · 0 列车 / 0 MR')
    expect(wrapper.text()).toContain('共 0 个来源')
    expect(wrapper.text()).not.toContain('请求失败')
    expect(wrapper.text()).not.toContain('(500)')
    wrapper.unmount()
  })

  it('keeps the last successful overview and distinguishes an HTTP failure from a backend outage', async () => {
    const session = {
      session_id: 'session-existing', mr_name: '列车35-MR-CT', train_name: '列车35',
      original_filename: '2026_07_24_1meshlog.log', first_sample_time: '', last_sample_time: '',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.getOverview
      .mockResolvedValueOnce({
        summary: {
          site_id: 'demo', index_status: 'ready', indexed_session_count: 1,
          pending_session_count: 0, index_updated_at: null, session_count: 1,
          train_count: 1, mr_count: 1,
        },
        sessions: { items: [session], total: 1, page: 1, page_size: 50 },
      })
      .mockRejectedValueOnce(new ApiRequestError(
        '目录摘要读取失败',
        500,
        'MESH_ANALYSIS_OVERVIEW_FAILED',
        { request_id: 'request-mesh-500' },
      ))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('共 1 个来源')
    expect(wrapper.text()).toContain('MESH 来源查询失败，Backend 仍在线')
    expect(wrapper.text()).toContain('MESH_ANALYSIS_OVERVIEW_FAILED')
    expect(wrapper.text()).toContain('request-mesh-500')
    expect(wrapper.text()).not.toContain('Backend 连接中断')
    wrapper.unmount()
  })

  it('does not show an error when an overview request is aborted', async () => {
    mocks.getOverview
      .mockResolvedValueOnce({
        summary: {
          site_id: 'demo', index_status: 'ready', indexed_session_count: 0,
          pending_session_count: 0, index_updated_at: null, session_count: 0,
          train_count: 0, mr_count: 0,
        },
        sessions: { items: [], total: 0, page: 1, page_size: 50 },
      })
      .mockRejectedValueOnce(new ApiRequestError(
        '请求已取消',
        0,
        'REQUEST_ABORTED',
      ))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '刷新结果')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('请求已取消')
    expect(wrapper.text()).not.toContain('Backend 已停止')
    wrapper.unmount()
  })

  it('locks the real RSSI viewport and requeries Busy with the same peer context', async () => {
    const session = {
      session_id: 'session-locked', mr_name: '列车06-MR-CT', original_filename: '6CTmeshlog.log', first_sample_time: '', last_sample_time: '',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    const otherSession = { ...session, session_id: 'session-other', mr_name: '列车06-MR-CW', original_filename: '6CWmeshlog.log' }
    const build = {
      anchor_link_id: 10, sequence: 2, source_file_id: 7, local_radio: 1, peer_ap_name: '轨旁AP-1', active_peer_mac: '0000-0000-0010',
      build_start_time: '2026-07-20 10:00:00.000', build_end_time: '2026-07-20 10:00:10.000',
    }
    const points = [
      { timestamp: chartViewport.start_time },
      { timestamp: '2026-07-20 10:00:02.000' },
      { timestamp: chartViewport.end_time },
    ]
    mocks.listSessions.mockResolvedValue({ items: [session, otherSession], total: 2, page: 1, page_size: 50 })
    mocks.getSession.mockImplementation(async (id: string) => ({ session: id === session.session_id ? session : otherSession, analysis_params: {}, available_radios: [1], warnings: [], sources: [{ source_file_id: id === session.session_id ? 7 : 8 }] }))
    mocks.listBuildOrder.mockResolvedValue({ items: [build], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockResolvedValue({
      mode: 'active_path', anchor: null, points, events: [], location_segments: [], total_points: 3, returned_points: 3,
      downsampled: false, summary: { sample_count: 3 }, time_from: build.build_start_time, time_to: build.build_end_time,
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.find('.sessions-toggle').trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenLastCalledWith('session-locked', {
      max_points: 2000,
      radio: 1,
      view_mode: 'overview',
      include_peer: false,
      include_standby_context: true,
      include_events: true,
      include_station_band: true,
    }, expect.any(AbortSignal))
    expect(mocks.getTracksideSignal).toHaveBeenLastCalledWith('session-locked', {
      max_points: 2000,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
      view_mode: 'overview',
    }, expect.anything())
    const tracksideChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === '')
    expect(tracksideChart?.props('events')).toEqual([])

    await wrapper.findAll('button').find((button) => button.text() === '锁定当前时间范围')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(`已锁定 ${chartViewport.start_time} — ${chartViewport.end_time}`)

    await wrapper.findAll('button').find((button) => button.text() === '查看同期空口负载')!.trigger('click')
    await flushPromises()

    expect(mocks.getActivePath).toHaveBeenLastCalledWith('session-locked', {
      max_points: 2000,
      radio: 1,
      time_from: chartViewport.start_time,
      time_to: chartViewport.end_time,
      include_peer: false,
      include_standby_context: true,
      include_events: true,
      include_station_band: true,
    })
    expect(wrapper.text()).toContain('已使用 RSSI 锁定时间')

    await wrapper.findAll('button').filter((button) => button.text() === '查看')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('已锁定 2026-07-20 10:00:01.123')
    expect(wrapper.findAll('button').some((button) => button.text() === '锁定当前时间范围')).toBe(true)
    wrapper.unmount()
  })

  it('waits for two active chart frames and an idle turn before requesting trackside data', async () => {
    const frameCallbacks = new Map<number, FrameRequestCallback>()
    const idleCallbacks = new Map<number, IdleRequestCallback>()
    let frameId = 0
    let idleId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++frameId
      frameCallbacks.set(id, callback)
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => { frameCallbacks.delete(id) })
    vi.stubGlobal('requestIdleCallback', (callback: IdleRequestCallback) => {
      const id = ++idleId
      idleCallbacks.set(id, callback)
      return id
    })
    vi.stubGlobal('cancelIdleCallback', (id: number) => { idleCallbacks.delete(id) })
    vi.stubGlobal('IntersectionObserver', undefined)

    const session = {
      session_id: 'session-staged-rssi',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    let resolveActive!: (value: Record<string, unknown>) => void
    let activeRunning = false
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{
        source_file_id: 7,
        source_action_id: 'source-staged',
        raw_sha256: 'sha-staged',
        identity_index_revision: 4,
        identity_current_revision: 4,
        identity_mapped_at: '2026-07-20T10:02:00',
      }],
    })
    mocks.listBuildOrder.mockResolvedValue({
      items: [{
        sequence: 1,
        anchor_link_id: 10,
        local_radio: 1,
        peer_ap_name: 'AP-1',
        active_peer_mac: '0000-0000-0010',
        build_start_time: session.first_sample_time,
        build_end_time: session.last_sample_time,
        build_result: 'normal',
      }],
      total: 1,
      page: 1,
      page_size: 100,
    })
    mocks.getActivePath.mockImplementation(() => {
      activeRunning = true
      return new Promise((resolve) => { resolveActive = resolve })
    })
    mocks.getTracksideSignal.mockImplementation(async () => {
      expect(activeRunning).toBe(false)
      return {
        source_id: session.session_id,
        radio: 1,
        time_range: { start: session.first_sample_time, end: session.last_sample_time },
        series: [],
        events: [],
        warnings: [],
        total_series: 0,
        returned_series: 0,
        total_frames: 0,
        returned_frames: 0,
        total_link_points: 0,
        returned_link_points: 0,
      }
    })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    const chartButton = wrapper.findAll('button').find((button) => button.text() === '查看动态图')!
    await chartButton.trigger('click')
    await chartButton.trigger('click')
    await flushPromises()

    expect(mocks.getActivePath).toHaveBeenCalledTimes(1)
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    resolveActive({
      mode: 'active_path',
      anchor: null,
      points: [{ timestamp: session.first_sample_time, local_radio: 1, local_rssi: 30 }],
      events: [],
      location_segments: [],
      total_points: 1,
      returned_points: 1,
      downsampled: false,
      summary: { sample_count: 1 },
      time_from: null,
      time_to: null,
    })
    activeRunning = false
    await flushPromises()

    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    expect(frameCallbacks.size).toBeGreaterThan(0)
    const firstFrameTurn = [...frameCallbacks.values()]
    frameCallbacks.clear()
    firstFrameTurn.forEach((callback) => callback(performance.now()))
    await flushPromises()
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    expect(frameCallbacks.size).toBeGreaterThan(0)
    const secondFrameTurn = [...frameCallbacks.values()]
    frameCallbacks.clear()
    secondFrameTurn.forEach((callback) => callback(performance.now()))
    await flushPromises()
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    expect(idleCallbacks.size).toBe(1)
    const idle = idleCallbacks.entries().next().value as [number, IdleRequestCallback]
    idleCallbacks.delete(idle[0])
    idle[1]({ didTimeout: false, timeRemaining: () => 50 } as IdleDeadline)
    await flushPromises()

    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does not automatically request trackside data when the active RSSI request fails', async () => {
    const session = {
      session_id: 'session-active-failed',
      mr_name: '列车07-MR-CW',
      original_filename: '7CWmeshlog.log',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [{ source_file_id: 8 }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [{ sequence: 1, anchor_link_id: 11, local_radio: 1, build_result: 'normal' }], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockRejectedValue(new Error('主链查询失败'))

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()

    expect(mocks.getActivePath).toHaveBeenCalledTimes(1)
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('主链 RSSI 数据加载失败：主链查询失败')
    expect(wrapper.text()).toContain('等待主链 RSSI 图加载完成')
    wrapper.unmount()
  })

  it('keeps the initial RSSI Overview when the chart reports a full-range viewport', async () => {
    const { wrapper, session, activeChart } = await mountHotfixRssiSession('session-overview-init')
    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    const fullViewport = {
      start_time: '2026-07-24 10:00:00.500',
      end_time: '2026-07-24 10:59:59.500',
      start_percent: 0,
      end_percent: 100,
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source: 'user_zoom' as const,
      source_chart: 'active-rssi' as const,
      revision: 5,
    }

    await activeChart.vm.$emit('viewport-ready', fullViewport)
    await activeChart.vm.$emit('viewport-change', fullViewport)
    await flushPromises()

    expect(mocks.getActivePath).not.toHaveBeenCalled()
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('publishes a zoom window only after both RSSI responses are ready', async () => {
    const { wrapper, session, activeChart, tracksideChart } = await mountHotfixRssiSession('session-window-atomic')
    const previousPoints = activeChart.props('points')
    const previousCache = tracksideChart.props('seriesCache')
    const activeWindow = deferred<ReturnType<typeof hotfixActivePayload>>()
    const tracksideWindow = deferred<ReturnType<typeof hotfixTracksidePayload>>()
    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.getActivePath.mockImplementationOnce(() => activeWindow.promise)
    mocks.getTracksideSignal.mockImplementationOnce(() => tracksideWindow.promise)
    vi.useFakeTimers()
    const viewport = {
      start_time: '2026-07-24 10:10:00.000',
      end_time: '2026-07-24 10:13:00.000',
      start_percent: 16,
      end_percent: 22,
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source: 'user_zoom' as const,
      source_chart: 'active-rssi' as const,
      revision: 31,
    }

    try {
      await activeChart.vm.$emit('viewport-change', viewport)
      await vi.advanceTimersByTimeAsync(500)
      expect(mocks.getActivePath).toHaveBeenCalledWith(session.session_id, {
        max_points: 2000,
        radio: 2,
        time_from: viewport.start_time,
        time_to: viewport.end_time,
        view_mode: 'window',
        include_peer: false,
        include_standby_context: true,
        include_events: true,
        include_station_band: true,
      }, expect.any(AbortSignal))
      expect(mocks.getTracksideSignal).toHaveBeenCalledWith(session.session_id, {
        max_points: 2000,
        radio: 2,
        time_from: viewport.start_time,
        time_to: viewport.end_time,
        view_mode: 'window',
      }, expect.any(AbortSignal))

      activeWindow.resolve(hotfixActivePayload(session.session_id, 41, viewport.start_time, viewport.end_time, 'window'))
      await flushPromises()
      expect(activeChart.props('points')).toBe(previousPoints)
      expect(tracksideChart.props('seriesCache')).toBe(previousCache)
      expect(wrapper.findAllComponents(meshChartStub).some((chart) => chart.props('scope') === '')).toBe(true)

      tracksideWindow.resolve(hotfixTracksidePayload(session.session_id, 39, viewport.start_time, viewport.end_time, 'window'))
      await flushPromises()
      expect(activeChart.props('points')).not.toBe(previousPoints)
      expect((activeChart.props('points') as Array<{ local_rssi: number }>)[0].local_rssi).toBe(41)
      expect(tracksideChart.props('seriesCache')).not.toBe(previousCache)
      expect(activeChart.props('syncViewport')).toMatchObject({
        start_time: viewport.start_time,
        end_time: viewport.end_time,
        full_start_time: viewport.full_start_time,
        full_end_time: viewport.full_end_time,
      })
      expect(tracksideChart.props('syncViewport')).toEqual(activeChart.props('syncViewport'))
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('reuses a bounded RSSI window cache when returning to a recent viewport', async () => {
    const { wrapper, session, activeChart } = await mountHotfixRssiSession('session-window-lru')
    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    const viewportA = {
      start_time: '2026-07-24 10:10:00.000',
      end_time: '2026-07-24 10:13:00.000',
      start_percent: 16,
      end_percent: 22,
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source: 'user_zoom' as const,
      source_chart: 'active-rssi' as const,
      revision: 41,
    }
    const viewportB = {
      ...viewportA,
      start_time: '2026-07-24 10:20:00.000',
      end_time: '2026-07-24 10:23:00.000',
      revision: 42,
    }
    mocks.getActivePath.mockImplementation((_id, values) => Promise.resolve(
      hotfixActivePayload(
        session.session_id,
        values.time_from === viewportA.start_time ? 41 : 51,
        String(values.time_from),
        String(values.time_to),
        values.view_mode === 'overview' ? 'overview' : 'window',
      ),
    ))
    mocks.getTracksideSignal.mockImplementation((_id, values) => Promise.resolve(
      hotfixTracksidePayload(
        session.session_id,
        values.time_from === viewportA.start_time ? 39 : 49,
        String(values.time_from),
        String(values.time_to),
        values.view_mode === 'overview' ? 'overview' : 'window',
      ),
    ))
    vi.useFakeTimers()

    try {
      for (const viewport of [viewportA, viewportB, { ...viewportA, revision: 43 }]) {
        await activeChart.vm.$emit('viewport-change', viewport)
        await vi.advanceTimersByTimeAsync(500)
        await flushPromises()
      }

      expect(mocks.getActivePath).toHaveBeenCalledTimes(2)
      expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(2)
      expect((activeChart.props('points') as Array<{ local_rssi: number }>)[0].local_rssi).toBe(41)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('previews every drag viewport but submits only the final window after pointer release', async () => {
    const { wrapper, session, activeChart, tracksideChart } = await mountHotfixRssiSession('session-window-drag')
    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.getActivePath.mockResolvedValue(hotfixActivePayload(session.session_id, 45))
    mocks.getTracksideSignal.mockResolvedValue(hotfixTracksidePayload(session.session_id, 43))
    vi.useFakeTimers()
    const viewports = [0, 1, 2].map((index) => ({
      start_time: `2026-07-24 10:2${index}:00.000`,
      end_time: `2026-07-24 10:2${index}:30.000`,
      start_percent: 30 + index,
      end_percent: 31 + index,
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source: 'user_zoom' as const,
      source_chart: 'trackside-rssi' as const,
      revision: 40 + index,
    }))

    try {
      await tracksideChart.vm.$emit('viewport-interaction-start')
      for (const viewport of viewports) {
        await tracksideChart.vm.$emit('viewport-change', viewport)
        await nextTick()
      }
      expect(activeChart.props('syncViewport')).toMatchObject({
        start_time: viewports[2].start_time,
        end_time: viewports[2].end_time,
      })
      expect(tracksideChart.props('syncViewport')).toMatchObject({
        start_time: viewports[2].start_time,
        end_time: viewports[2].end_time,
      })
      await vi.advanceTimersByTimeAsync(1_000)
      expect(mocks.getActivePath).not.toHaveBeenCalled()
      expect(mocks.getTracksideSignal).not.toHaveBeenCalled()

      await tracksideChart.vm.$emit('viewport-interaction-end')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      expect(mocks.getActivePath).toHaveBeenCalledTimes(1)
      expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(1)
      expect(mocks.getActivePath).toHaveBeenCalledWith(session.session_id, expect.objectContaining({
        time_from: viewports[2].start_time,
        time_to: viewports[2].end_time,
      }), expect.any(AbortSignal))
      expect(mocks.getTracksideSignal).toHaveBeenCalledWith(session.session_id, expect.objectContaining({
        time_from: viewports[2].start_time,
        time_to: viewports[2].end_time,
      }), expect.any(AbortSignal))
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('aborts an obsolete RSSI window batch and rejects its late responses', async () => {
    const { wrapper, session, activeChart } = await mountHotfixRssiSession('session-window-race')
    const requests = new Map<string, {
      active: ReturnType<typeof deferred<ReturnType<typeof hotfixActivePayload>>>
      trackside: ReturnType<typeof deferred<ReturnType<typeof hotfixTracksidePayload>>>
      signals: AbortSignal[]
    }>()
    const requestFor = (start: string) => {
      let request = requests.get(start)
      if (!request) {
        request = { active: deferred(), trackside: deferred(), signals: [] }
        requests.set(start, request)
      }
      return request
    }
    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.getActivePath.mockImplementation((_id, values, signal: AbortSignal) => {
      const request = requestFor(String(values.time_from))
      request.signals.push(signal)
      return request.active.promise
    })
    mocks.getTracksideSignal.mockImplementation((_id, values, signal: AbortSignal) => {
      const request = requestFor(String(values.time_from))
      request.signals.push(signal)
      return request.trackside.promise
    })
    vi.useFakeTimers()
    const viewportA = {
      ...chartViewport,
      start_time: '2026-07-24 10:30:00.000',
      end_time: '2026-07-24 10:32:00.000',
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source_chart: 'active-rssi' as const,
      revision: 51,
    }
    const viewportB = {
      ...viewportA,
      start_time: '2026-07-24 10:40:00.000',
      end_time: '2026-07-24 10:42:00.000',
      revision: 52,
    }

    try {
      await activeChart.vm.$emit('viewport-change', viewportA)
      await vi.advanceTimersByTimeAsync(500)
      expect(requests.get(viewportA.start_time)?.signals).toHaveLength(2)

      await activeChart.vm.$emit('viewport-interaction-start')
      await activeChart.vm.$emit('viewport-change', viewportB)
      await activeChart.vm.$emit('viewport-interaction-end')
      expect(requests.get(viewportA.start_time)?.signals.every((signal) => signal.aborted)).toBe(true)
      await vi.advanceTimersByTimeAsync(250)
      expect(requests.get(viewportB.start_time)?.signals).toHaveLength(2)

      requests.get(viewportB.start_time)!.active.resolve(hotfixActivePayload(session.session_id, 52, viewportB.start_time, viewportB.end_time))
      requests.get(viewportB.start_time)!.trackside.resolve(hotfixTracksidePayload(session.session_id, 50, viewportB.start_time, viewportB.end_time))
      await flushPromises()
      expect((activeChart.props('points') as Array<{ local_rssi: number }>)[0].local_rssi).toBe(52)

      requests.get(viewportA.start_time)!.active.resolve(hotfixActivePayload(session.session_id, 31, viewportA.start_time, viewportA.end_time))
      requests.get(viewportA.start_time)!.trackside.resolve(hotfixTracksidePayload(session.session_id, 29, viewportA.start_time, viewportA.end_time))
      await flushPromises()
      expect((activeChart.props('points') as Array<{ local_rssi: number }>)[0].local_rssi).toBe(52)
      expect(activeChart.props('syncViewport')).toMatchObject({
        start_time: viewportB.start_time,
        end_time: viewportB.end_time,
      })
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('keeps the previous RSSI snapshot and viewport when a window request fails', async () => {
    const { wrapper, session, activeChart, tracksideChart } = await mountHotfixRssiSession('session-window-failure')
    const previousPoints = activeChart.props('points')
    const previousCache = tracksideChart.props('seriesCache')
    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.getActivePath.mockRejectedValueOnce(new ApiRequestError('当前窗口关键帧超过安全上限', 413, 'MESH_CHART_LIMIT'))
    mocks.getTracksideSignal.mockResolvedValueOnce(hotfixTracksidePayload(session.session_id, 48))
    vi.useFakeTimers()
    const viewport = {
      ...chartViewport,
      start_time: '2026-07-24 10:50:00.000',
      end_time: '2026-07-24 10:53:00.000',
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source_chart: 'active-rssi' as const,
      revision: 61,
    }

    try {
      await activeChart.vm.$emit('viewport-change', viewport)
      await vi.advanceTimersByTimeAsync(500)
      await flushPromises()
      expect(activeChart.props('points')).toBe(previousPoints)
      expect(tracksideChart.props('seriesCache')).toBe(previousCache)
      expect(activeChart.props('syncViewport')).toMatchObject({
        start_time: viewport.start_time,
        end_time: viewport.end_time,
      })
      expect(tracksideChart.props('syncViewport')).toMatchObject({
        start_time: viewport.start_time,
        end_time: viewport.end_time,
      })
      expect(wrapper.text()).toContain('当前窗口关键帧超过安全上限')
      expect(wrapper.findAllComponents(meshChartStub).some((chart) => chart.props('scope') === '')).toBe(true)

      mocks.getActivePath.mockResolvedValueOnce(hotfixActivePayload(session.session_id, 49))
      mocks.getTracksideSignal.mockRejectedValueOnce(new Error('Backend 临时断开'))
      await activeChart.vm.$emit('viewport-change', { ...viewport, start_time: '2026-07-24 10:54:00.000', end_time: '2026-07-24 10:57:00.000', revision: 62 })
      await vi.advanceTimersByTimeAsync(500)
      await flushPromises()
      expect(activeChart.props('points')).toBe(previousPoints)
      expect(tracksideChart.props('seriesCache')).toBe(previousCache)
      expect(wrapper.text()).toContain('Backend 临时断开')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('collapses sessions after opening a source, defaults to build order and lazily keeps charts unloaded', async () => {
    const intersectionCallbacks: IntersectionObserverCallback[] = []
    vi.stubGlobal('IntersectionObserver', class {
      constructor(callback: IntersectionObserverCallback) { intersectionCallbacks.push(callback) }
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords(): IntersectionObserverEntry[] { return [] }
      root = null
      rootMargin = '600px 0px'
      thresholds = [0]
    })
    const fullStart = '2026-07-20 10:00:00.000'
    const fullMiddle = '2026-07-20 10:30:00.000'
    const fullEnd = '2026-07-20 11:00:00.000'
    const session = {
      session_id: 'session-1', mr_name: '列车34-MR-CW', original_filename: '34-CW.log', first_sample_time: fullStart, last_sample_time: fullEnd,
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1, 2], warnings: [], sources: [{ source_file_id: 7, source_action_id: 'source-1', source_id: 'source-1', exists: true, rebuild_capability: 'ready' }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [{ sequence: 1, anchor_link_id: 10, local_radio: 1, peer_ap_name: 'AP-1', active_peer_mac: 'aa', build_start_time: fullStart, build_end_time: '2026-07-20 10:00:10.000', build_result: 'normal' }], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockResolvedValue({
      mode: 'active_path',
      anchor: null,
      points: [
        { timestamp: fullStart, local_radio: 1, local_rssi: 30 },
        { timestamp: fullMiddle, local_radio: 1, local_rssi: 36 },
        { timestamp: fullEnd, local_radio: 1, local_rssi: 34 },
      ],
      events: [],
      location_segments: [],
      total_points: 3,
      returned_points: 3,
      downsampled: false,
      summary: {
        sample_count: 3,
        active_count: 3,
        standby_context_count: 1,
        switch_count: 0,
        current_radio: 1,
        first_sample_time: fullStart,
        last_sample_time: fullEnd,
      },
      time_from: null,
      time_to: null,
    })
    mocks.getTracksideSignal.mockResolvedValue({
      source_id: 'session-1',
      radio: 1,
      time_range: { start: fullStart, end: fullEnd },
      series: [{
        series_id: 'ap-1:radio:1',
        peer_name: 'AP-1',
        peer_mac: 'aa',
        ap_mac: null,
        radio: 1,
        station: null,
        section: null,
        roles_present: ['ACTIVE'],
        data_source: 'peer_rssi_db',
        total_points: 2,
        returned_points: 2,
        points: [{ timestamp: fullStart, timestamp_tag: '', peer_rssi: 28 }, { timestamp: fullEnd, timestamp_tag: '', peer_rssi: 31 }],
      }],
      events: [],
      warnings: [],
      estimated_interval_seconds: null,
      continuity_gap_seconds: null,
      total_series: 1,
      returned_series: 1,
      total_frames: 2,
      returned_frames: 2,
      total_link_points: 2,
      returned_link_points: 2,
      total_link_runs: 1,
      active_link_points: 2,
      standby_link_points: 0,
      returned_active_link_points: 2,
      returned_standby_link_points: 0,
      role_switch_count: 0,
      skipped_missing_signal_points: 0,
      skipped_missing_identity_points: 0,
      total_points: 2,
      returned_points: 2,
      downsampled: false,
      requested_max_frames: 600,
      effective_max_frames: 600,
      requested_max_points: 600,
      effective_max_points: 600,
      top_n: 0,
      included_roles: ['ACTIVE', 'STANDBY'],
      include_standby: true,
    })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
    const openButton = wrapper.findAll('button').find((button) => button.text() === '查看')
    await openButton!.trigger('click')
    await flushPromises()

    expect(mocks.getSession).toHaveBeenCalledWith('session-1', expect.any(AbortSignal))
    expect(mocks.listBuildOrder).toHaveBeenCalledWith('session-1', expect.objectContaining({ page: 1, page_size: 100, sort_order: 'desc' }), expect.any(AbortSignal))
    expect(mocks.getActivePath).not.toHaveBeenCalled()
    expect(mocks.getRateSeries).not.toHaveBeenCalled()
    expect(mocks.getCounterDeltas).not.toHaveBeenCalled()
    expect(mocks.listAnomalies).not.toHaveBeenCalled()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('false')
    expect(sessionStorage.getItem('netconsole.mesh-analysis.session-expanded')).toBeNull()
    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('build-order')
    expect(wrapper.findAll('[data-option-label]').some((option) => option.text() === 'Radio 2')).toBe(true)

    await wrapper.find('.sessions-toggle').trigger('click')
    expect(sessionStorage.getItem('netconsole.mesh-analysis.session-expanded')).toBe('true')
    const chartButton = wrapper.findAll('button').find((button) => button.text() === '查看动态图')
    await chartButton!.trigger('click')
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledWith('session-1', {
      max_points: 2000,
      radio: 1,
      view_mode: 'overview',
      include_peer: false,
      include_standby_context: true,
      include_events: true,
      include_station_band: true,
    }, expect.any(AbortSignal))

    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    const activeRssiChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      chart.props('scope') === 'active' && (chart.props('points') as unknown[]).length > 0
    ))
    expect(activeRssiChart?.props('syncViewport')).toMatchObject({
      start_time: fullStart,
      end_time: '2026-07-20 10:00:15.000',
      full_start_time: fullStart,
      full_end_time: fullEnd,
    })
    intersectionCallbacks[0]?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
    await flushPromises()
    expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-1', {
      max_points: 2000,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
      view_mode: 'overview',
    }, expect.anything())
    const tracksideChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      ((chart.props('seriesCache') as { series?: unknown[] } | null)?.series?.length ?? 0) > 0
    ))
    expect(tracksideChart?.props('active')).toBe(true)
    expect(wrapper.text()).toContain(`最早 ${fullStart}`)
    expect(wrapper.text()).toContain(`最新 ${fullEnd}`)
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('false')

    const zoomStart = '2026-07-20 10:00:05.000'
    const zoomEnd = '2026-07-20 10:00:20.000'
    await activeRssiChart!.vm.$emit('viewport-change', {
      start_time: zoomStart,
      end_time: zoomEnd,
      start_percent: 5,
      end_percent: 20,
      full_start_time: fullStart,
      full_end_time: fullEnd,
      source: 'user_zoom',
      source_chart: 'active',
      revision: 10,
    })
    await vi.waitFor(() => {
      expect(mocks.getActivePath).toHaveBeenCalledWith('session-1', {
        max_points: 2000,
        radio: 1,
        time_from: zoomStart,
        time_to: zoomEnd,
        view_mode: 'window',
        include_peer: false,
        include_standby_context: true,
        include_events: true,
        include_station_band: true,
      }, expect.any(AbortSignal))
      expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-1', {
        max_points: 2000,
        radio: 1,
        time_from: zoomStart,
        time_to: zoomEnd,
        view_mode: 'window',
      }, expect.anything())
    })

    const initialActiveCalls = mocks.getActivePath.mock.calls.length
    const initialTracksideCalls = mocks.getTracksideSignal.mock.calls.length
    const initialCache = tracksideChart?.props('seriesCache')
    const layoutButton = (label: string) => wrapper.findAll('button')
      .find((button) => button.text() === label)!
    expect(wrapper.find('[data-layout-mode="compare"]').exists()).toBe(true)
    for (let index = 0; index < 20; index += 1) {
      await layoutButton(index % 2 === 0 ? '主链' : '轨旁').trigger('click')
      await flushPromises()
    }
    expect(wrapper.find('[data-layout-mode="trackside-focus"]').exists()).toBe(true)
    expect(activeRssiChart?.props('active')).toBe(false)
    expect(tracksideChart?.props('active')).toBe(true)
    expect(tracksideChart?.props('seriesCache')).toBe(initialCache)
    expect(mocks.getActivePath).toHaveBeenCalledTimes(initialActiveCalls)
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(initialTracksideCalls)
    expect(mocks.chartResize).toHaveBeenCalled()

    await layoutButton('对比').trigger('click')
    await layoutButton('沉浸对比').trigger('click')
    await flushPromises()
    expect(wrapper.find('.mesh-page').classes()).toContain('is-rssi-immersive')
    expect(tracksideChart?.props('seriesCache')).toBe(initialCache)
    expect(mocks.getActivePath).toHaveBeenCalledTimes(initialActiveCalls)
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(initialTracksideCalls)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('.mesh-page').classes()).not.toContain('is-rssi-immersive')

    await layoutButton('主链').trigger('click')
    await flushPromises()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('[data-layout-mode="compare"]').exists()).toBe(true)
    expect(activeRssiChart?.props('active')).toBe(true)
    expect(tracksideChart?.props('active')).toBe(true)

    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.chartApplyViewport.mockClear()
    const targetPointSelect = wrapper.findAllComponents(selectStub).find((select) => (
      select.findAll('[data-option-label]').some((option) => option.text() === '概览精度 1200 点')
    ))
    await targetPointSelect!.vm.$emit('update:modelValue', 1200)
    await targetPointSelect!.vm.$emit('change', 1200)
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledWith('session-1', {
      max_points: 1200,
      radio: 1,
      view_mode: 'overview',
      include_peer: false,
      include_standby_context: true,
      include_events: true,
      include_station_band: true,
    }, expect.any(AbortSignal))
    expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-1', {
      max_points: 1200,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
      view_mode: 'overview',
    }, expect.anything())
    expect(activeRssiChart?.props('syncViewport')).toMatchObject({
      start_time: zoomStart,
      end_time: zoomEnd,
    })

    await wrapper.findAll('button').find((button) => button.text() === '重置视图')!.trigger('click')
    await vi.waitFor(() => {
      expect(mocks.getActivePath).toHaveBeenCalledWith('session-1', {
        max_points: 1200,
        radio: 1,
        view_mode: 'overview',
        include_peer: false,
        include_standby_context: true,
        include_events: true,
        include_station_band: true,
      }, expect.any(AbortSignal))
      expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-1', {
        max_points: 1200,
        radio: 1,
        time_from: undefined,
        time_to: undefined,
        view_mode: 'overview',
      }, expect.any(AbortSignal))
    })
    await flushPromises()
    expect(mocks.chartResetViewport).not.toHaveBeenCalled()
    const rssiChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      chart.props('scope') === 'active' && (chart.props('points') as unknown[]).length > 0
    ))
    expect(rssiChart?.props('syncViewport')).toMatchObject({
      start_time: fullStart,
      end_time: fullEnd,
    })

    await wrapper.find('.sessions-toggle').trigger('click')
    await flushPromises()
    const openAgain = wrapper.findAll('button').find((button) => button.text() === '查看')
    await openAgain!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })

  it('does not open RSSI for build-order row click or double click', async () => {
    const session = {
      session_id: 'session-row-click',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const row = {
      sequence: 1,
      anchor_link_id: 88,
      source_file_id: 7,
      local_radio: 1,
      peer_ap_name: '轨旁AP-1',
      active_peer_mac: 'bc5a-3457-9c8f',
      build_start_time: '2026-07-20 10:00:10.000',
      build_end_time: '2026-07-20 10:00:20.000',
      build_result: 'normal',
    }
    mocks.listSessions.mockResolvedValueOnce({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [{ source_file_id: 7 }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 100 })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    const table = wrapper.findAllComponents(dataTableStub).find((item) => item.props('tableId') === 'mesh-analysis-active-build-order:v2')!
    await table.vm.$emit('row-click', row, { property: 'peer_ap_name' }, new MouseEvent('click'))
    await flushPromises()

    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('build-order')
    expect((wrapper.vm as unknown as { selectedSegment: unknown }).selectedSegment).toEqual(row)
    expect(mocks.getActivePath).not.toHaveBeenCalled()
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()

    await table.vm.$emit('row-dblclick', row)
    await flushPromises()
    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('build-order')
    expect(mocks.getActivePath).not.toHaveBeenCalled()
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('rssi')
    expect(mocks.getActivePath).toHaveBeenCalledWith(
      'session-row-click',
      {
        max_points: 2000,
        radio: 1,
        view_mode: 'overview',
        include_peer: false,
        include_standby_context: true,
        include_events: true,
        include_station_band: true,
      },
      expect.any(AbortSignal),
    )
    wrapper.unmount()
  })

  it('offers an explicit unloaded trackside action and requests the current viewport first', async () => {
    class IdleIntersectionObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords(): IntersectionObserverEntry[] { return [] }
      readonly root = null
      readonly rootMargin = '0px'
      readonly thresholds = [0]
    }
    vi.stubGlobal('IntersectionObserver', IdleIntersectionObserver)
    const session = {
      session_id: 'session-trackside-unloaded',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 7, source_action_id: 'source-trackside-unloaded', exists: true, rebuild_capability: 'ready' }],
    })
    mocks.listBuildOrder.mockResolvedValue({
      items: [{
        sequence: 1,
        anchor_link_id: 7,
        local_radio: 1,
        build_start_time: session.first_sample_time,
        build_end_time: session.last_sample_time,
        build_result: 'normal',
      }],
      total: 1,
      page: 1,
      page_size: 100,
    })
    mocks.getActivePath.mockResolvedValue(hotfixActivePayload(session.session_id, 30))
    mocks.getTracksideSignal.mockResolvedValue(hotfixTracksidePayload(session.session_id, 28))
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()

    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()
    const viewport = {
      ...chartViewport,
      start_time: '2026-07-20 10:00:10.000',
      end_time: '2026-07-20 10:00:20.000',
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
      source: 'programmatic' as const,
    }
    const activeChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === 'active')!
    await activeChart.vm.$emit('viewport-change', viewport)
    await nextTick()
    const loadButton = wrapper.findAll('button').find((button) => button.text() === '加载当前窗口')
    expect(loadButton?.exists()).toBe(true)

    await loadButton!.trigger('click')
    await flushPromises()
    expect(mocks.getTracksideSignal).toHaveBeenCalledWith(session.session_id, {
      max_points: 2000,
      radio: 1,
      time_from: viewport.start_time,
      time_to: viewport.end_time,
      view_mode: 'window',
    }, expect.any(AbortSignal))
    wrapper.unmount()
  })

  it('keeps the active RSSI chart when trackside loading fails and retries only trackside', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const session = {
      session_id: 'session-rssi-isolated',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const row = {
      sequence: 1,
      anchor_link_id: 88,
      source_file_id: 7,
      local_radio: 1,
      peer_ap_name: '轨旁AP-1',
      active_peer_mac: 'bc5a-3457-9c8f',
      build_start_time: '2026-07-20 10:00:10.000',
      build_end_time: '2026-07-20 10:00:20.000',
      build_result: 'normal',
    }
    mocks.listSessions.mockResolvedValueOnce({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [{ source_file_id: 7 }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockResolvedValue({
      mode: 'active_path',
      anchor: null,
      points: [{ timestamp: session.first_sample_time, local_radio: 1, local_rssi: 30 }],
      events: [],
      location_segments: [],
      total_points: 1,
      returned_points: 1,
      downsampled: false,
      summary: { sample_count: 1, active_count: 1, standby_context_count: 0, switch_count: 0 },
      time_from: null,
      time_to: null,
    })
    mocks.getTracksideSignal.mockRejectedValueOnce(new Error('请求超时，请重试。')).mockResolvedValueOnce({
      source_id: session.session_id,
      radio: 1,
      time_range: { start: session.first_sample_time, end: session.last_sample_time },
      series: [],
      events: [],
      warnings: [],
      estimated_interval_seconds: null,
      continuity_gap_seconds: null,
      total_series: 0,
      returned_series: 0,
      total_frames: 0,
      returned_frames: 0,
      total_link_points: 0,
      returned_link_points: 0,
      total_link_runs: 0,
      active_link_points: 0,
      standby_link_points: 0,
      returned_active_link_points: 0,
      returned_standby_link_points: 0,
      role_switch_count: 0,
      skipped_missing_signal_points: 0,
      skipped_missing_identity_points: 0,
      total_points: 0,
      returned_points: 0,
      downsampled: false,
      requested_max_frames: 600,
      effective_max_frames: 600,
      requested_max_points: 600,
      effective_max_points: 600,
      top_n: 0,
      included_roles: ['ACTIVE', 'STANDBY'],
      include_standby: true,
    })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()

    const activeChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === 'active')
    expect(activeChart?.props('points')).toHaveLength(1)
    expect(wrapper.text()).toContain('轨旁AP信号图加载失败：请求超时，请重试。')
    const activeCalls = mocks.getActivePath.mock.calls.length
    await wrapper.findAll('button').find((button) => button.text() === '重新加载轨旁AP信号图')!.trigger('click')
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledTimes(activeCalls)
    expect(mocks.getTracksideSignal).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('shows an active RSSI timeout as an error instead of a zero-point success summary', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const session = {
      session_id: 'session-rssi-timeout',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const row = {
      sequence: 1,
      anchor_link_id: 88,
      source_file_id: 7,
      local_radio: 1,
      peer_ap_name: '轨旁AP-1',
      active_peer_mac: 'bc5a-3457-9c8f',
      build_start_time: '2026-07-20 10:00:10.000',
      build_end_time: '2026-07-20 10:00:20.000',
      build_result: 'normal',
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [{ source_file_id: 7 }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockRejectedValue(new Error('请求超时，请重试。'))

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('主链 RSSI 数据加载失败：请求超时，请重试。')
    expect(wrapper.text()).not.toContain('采样点 0')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('aborts the previous active RSSI request when the Radio changes', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const session = {
      session_id: 'session-rssi-radio-abort',
      mr_name: '列车07-MR-CT',
      original_filename: '7CTmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const row = {
      sequence: 1,
      anchor_link_id: 88,
      source_file_id: 7,
      local_radio: 1,
      peer_ap_name: '轨旁AP-1',
      active_peer_mac: 'bc5a-3457-9c8f',
      build_start_time: '2026-07-20 10:00:10.000',
      build_end_time: '2026-07-20 10:00:20.000',
      build_result: 'normal',
    }
    const signals: AbortSignal[] = []
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1, 2], warnings: [], sources: [{ source_file_id: 7 }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockImplementation((_id: string, _values: Record<string, unknown>, signal?: AbortSignal) => new Promise((_resolve, reject) => {
      if (signal) {
        signals.push(signal)
        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
      }
    }))

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()
    expect(signals).toHaveLength(1)

    const radioSelect = wrapper.findAllComponents(selectStub).find((select) => (
      select.props('modelValue') === 1
      &&
      select.findAll('[data-option-label]').some((option) => option.text() === 'Radio 2')
    ))!
    await radioSelect.vm.$emit('update:modelValue', 2)
    await radioSelect.vm.$emit('change', 2)
    await flushPromises()

    expect(signals[0].aborted).toBe(true)
    expect(signals).toHaveLength(2)
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('opens link detail RSSI view with full-log API requests and only applies the row window to charts', async () => {
    const session = {
      session_id: 'session-link', mr_name: '列车07-MR-CT', original_filename: '7CTmeshlog.log', first_sample_time: '2026-07-20 09:00:00.000', last_sample_time: '2026-07-20 12:00:00.000',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    const linkRow = {
      record_id: 88,
      timestamp: '2026-07-20 10:00:00.000',
      timestamp_tag: '',
      local_radio: 1,
      link_role: 'ACTIVE',
      peer_mac: '3052-77a8-7200',
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1], warnings: [], sources: [{ source_file_id: 7 }] })
    mocks.getActivePath.mockResolvedValue({
      mode: 'active_path',
      anchor: null,
      points: [
        { timestamp: session.first_sample_time, local_radio: 1, local_rssi: 30 },
        { timestamp: linkRow.timestamp, local_radio: 1, local_rssi: 42 },
        { timestamp: session.last_sample_time, local_radio: 1, local_rssi: 33 },
      ],
      events: [],
      location_segments: [],
      total_points: 3,
      returned_points: 3,
      downsampled: false,
      summary: { sample_count: 3, first_sample_time: session.first_sample_time, last_sample_time: session.last_sample_time },
      time_from: null,
      time_to: null,
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()

    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.chartApplyViewport.mockClear()
    const tables = wrapper.findAllComponents(dataTableStub)
    const linkTable = tables.find((table) => table.props('tableId') === 'mesh-analysis-link-details:v3')!
    await linkTable.vm.$emit('row-dblclick', linkRow)
    await flushPromises()

    expect(mocks.getActivePath).toHaveBeenCalledWith('session-link', {
      max_points: 2000,
      radio: 1,
      view_mode: 'overview',
      include_peer: false,
      include_standby_context: true,
      include_events: true,
      include_station_band: true,
    }, expect.any(AbortSignal))
    expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-link', {
      max_points: 2000,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
      view_mode: 'overview',
    }, expect.anything())
    const activeRssiChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      chart.props('scope') === 'active' && (chart.props('points') as unknown[]).length > 0
    ))
    expect(activeRssiChart?.props('syncViewport')).toMatchObject({
      start_time: '2026-07-20 09:59:45.000',
      end_time: '2026-07-20 10:00:15.000',
      full_start_time: session.first_sample_time,
      full_end_time: session.last_sample_time,
    })
    expect(wrapper.text()).toContain(`最早 ${session.first_sample_time}`)
    expect(wrapper.text()).toContain(`最新 ${session.last_sample_time}`)
    wrapper.unmount()
  })

  it('falls back to the main task route when the Electron task window reports failure', async () => {
    const session = {
      session_id: 'session-1', mr_name: '列车34-MR-CW', original_filename: '34-CW.log', first_sample_time: '', last_sample_time: '',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [], warnings: [], sources: [] })
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openTaskWindow: vi.fn(async () => ({ success: false, error: '任务中心加载失败' })) },
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '打开任务中心')!.trigger('click')
    await flushPromises()

    expect(mocks.routerPush).toHaveBeenCalledWith({ name: 'tasks', query: { module: 'rail' } })
    wrapper.unmount()
    Reflect.deleteProperty(window, 'netconsoleDesktop')
  })

  it('restores the crashed session safely and waits for an explicit trackside reload', async () => {
    const session = {
      session_id: 'session-safe',
      mr_name: '列车06-MR-CW',
      original_filename: '6CWmeshlog.log',
      first_sample_time: '2026-07-20 10:00:00.000',
      last_sample_time: '2026-07-20 10:01:00.000',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    const build = {
      anchor_link_id: 10,
      sequence: 1,
      source_file_id: 7,
      local_radio: 1,
      peer_ap_name: '轨旁AP-1',
      active_peer_mac: '0000-0000-0010',
      build_start_time: session.first_sample_time,
      build_end_time: '2026-07-20 10:00:10.000',
    }
    const reportRendererWorkload = vi.fn()
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: {
        getRendererRecoveryState: vi.fn(async () => ({
          mode: 'safe',
          previousReason: 'oom',
          module: 'mesh-analysis',
          route: '/rail-transit/mesh-analysis',
          sessionId: session.session_id,
          sourceFileId: 7,
          radio: 1,
        })),
        reportRendererWorkload,
      },
    })
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 7 }],
    })
    mocks.listBuildOrder.mockResolvedValue({ items: [build], total: 1, page: 1, page_size: 100 })
    mocks.getActivePath.mockResolvedValue({
      mode: 'active_path',
      anchor: null,
      points: [{ timestamp: session.first_sample_time, local_radio: 1, local_rssi: 30 }],
      events: [],
      location_segments: [],
      total_points: 1,
      returned_points: 1,
      downsampled: false,
      summary: { sample_count: 1 },
      time_from: null,
      time_to: null,
    })

    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    expect(wrapper.find('.detail-tabs').attributes('modelvalue')).toBe('build-order')
    expect(wrapper.text()).toContain('上次轨旁图因渲染进程内存不足退出')
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalled()
    expect(mocks.getTracksideSignal).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text() === '重新加载轨旁AP信号图')!.trigger('click')
    await flushPromises()
    expect(mocks.getTracksideSignal).toHaveBeenCalledOnce()
    expect(reportRendererWorkload).toHaveBeenCalledWith(expect.objectContaining({
      module: 'mesh-analysis',
      phase: 'trackside-request-started',
      sessionId: session.session_id,
    }))
    wrapper.unmount()
    Reflect.deleteProperty(window, 'netconsoleDesktop')
  })

  it('shows the source directory action only in Electron and passes no path to it', async () => {
    const session = {
      session_id: '12345678-1234-1234-1234-123456789abc:1',
      mr_name: '列车08-MR-CT',
      original_filename: '8CTmeshlog.log',
      first_sample_time: '',
      last_sample_time: '',
      parsed_status: 'ready',
      warning_count: 0,
      report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({
      session,
      analysis_params: {},
      available_radios: [1],
      warnings: [],
      sources: [{ source_file_id: 1, exists: true }],
    })

    const browserWrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await browserWrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    expect(browserWrapper.findAll('button').some((button) => button.text() === '打开本地目录')).toBe(false)
    browserWrapper.unmount()

    mocks.platformAdapter.hostType = 'electron'
    const desktopWrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    if (!desktopWrapper.findAll('button').some((button) => button.text() === '打开本地目录')) {
      const viewButton = desktopWrapper.findAll('button').find((button) => button.text() === '查看')
      if (viewButton) await viewButton.trigger('click')
    }
    await flushPromises()
    await desktopWrapper.findAll('button').find((button) => button.text() === '打开本地目录')!.trigger('click')
    expect(mocks.platformAdapter.openMeshAnalysisSessionLocation).toHaveBeenCalledWith(session.session_id)
    desktopWrapper.unmount()
  })

  it('keeps the no-selection session list expanded even when this window previously stored collapse', async () => {
    sessionStorage.setItem('netconsole.mesh-analysis.session-expanded', 'false')
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })
})
