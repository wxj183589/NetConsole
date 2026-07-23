// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import meshAnalysisViewSource from './MeshAnalysisView.vue?raw'

const mocks = vi.hoisted(() => ({
  listProfiles: vi.fn(),
  listVehicleMrs: vi.fn(),
  prepareContext: vi.fn(),
  recoverTasks: vi.fn(),
  getSession: vi.fn(),
  listSessions: vi.fn(),
  listBuildOrder: vi.fn(),
  listLinks: vi.fn(),
  getActivePath: vi.fn(),
  getPeerPath: vi.fn(),
  getTracksideSignal: vi.fn(),
  getRateSeries: vi.fn(),
  getCounterDeltas: vi.fn(),
  listAnomalies: vi.fn(),
  exportDetails: vi.fn(),
  chartApplyViewport: vi.fn(),
  chartResetViewport: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('../../api/meshAnalysis', () => ({
  applyMeshBundleImport: vi.fn(),
  createMeshProfile: vi.fn(),
  exportMeshLinkDetails: mocks.exportDetails,
  getMeshActivePathChart: mocks.getActivePath,
  getMeshAnalysisSession: mocks.getSession,
  getMeshAnalysisSummary: vi.fn().mockResolvedValue({ session_count: 0, train_count: 0, mr_count: 0 }),
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
  listMeshSwitchEvents: vi.fn(),
  meshArtifactDownloadRequest: vi.fn(),
  previewMeshImport: vi.fn(),
  rebuildMeshAnalysis: vi.fn(),
  prepareMeshImportContext: mocks.prepareContext,
}))
vi.mock('../../api/railTransitBaseData', () => ({ listVehicleMrs: mocks.listVehicleMrs }))
vi.mock('../../api/railTransitWeb', () => ({
  exportMeshAnalysisReport: vi.fn(),
  getRailTransitTask: vi.fn(),
  recoverRailTransitTasks: mocks.recoverTasks,
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true) }) }))
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.routerPush }) }))

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
  setup(props, { attrs, slots }) {
    return () => h('div', { ...attrs, 'data-table-id': props.tableId }, props.data.flatMap((row) => [
      slots.default?.({ row }),
      slots['cell-actions']?.({ row }),
    ]))
  },
})
const dialogStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) { const attrs = useAttrs(); return () => h('div', attrs, [slots.default?.(), slots.footer?.()]) },
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
  ElInput: passthrough,
  ElInputNumber: passthrough,
  ElIcon: passthrough,
  ElOption: optionStub,
  ElPagination: passthrough,
  ElSelect: selectStub,
  ElTabPane: passthrough,
  ElTabs: passthrough,
  ElTag: passthrough,
  MeshChannelBusyChart: meshChartStub,
  MeshRssiChart: meshChartStub,
  MeshTracksideSignalChart: meshChartStub,
  MeshSwitchRssiChart: true,
  NcDataTable: dataTableStub,
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  mocks.listProfiles.mockResolvedValue([])
  mocks.listVehicleMrs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 })
  mocks.prepareContext.mockResolvedValue({ site_id: 'demo', vehicle_mr_count: 0, profile_count: 0, created_count: 0, updated_count: 0 })
  mocks.recoverTasks.mockResolvedValue([])
  mocks.listSessions.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
  mocks.listBuildOrder.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  mocks.listLinks.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
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
})

afterEach(() => vi.unstubAllGlobals())

describe('Mesh analysis import context behavior', () => {
  it('prepares context, pages VehicleMr by 200, and keeps VehicleMr when profiles fail', async () => {
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

    expect(mocks.prepareContext).toHaveBeenCalledTimes(1)
    expect(mocks.listVehicleMrs).toHaveBeenCalledWith({ page: 1, page_size: 200 })
    expect(mocks.listVehicleMrs).toHaveBeenCalledWith({ page: 2, page_size: 200 })
    expect(wrapper.text()).toContain('内部 MESH 归属加载失败：profile unavailable')
    expect(wrapper.text()).not.toContain('车载 MR 加载失败')
    expect(wrapper.text()).not.toContain('当前局点没有可识别的车载 MR')
    wrapper.unmount()
  })
})

describe('Mesh analysis detail behavior', () => {
  it('keeps the large trackside payload outside Vue deep reactivity', () => {
    expect(meshAnalysisViewSource).toContain('const tracksideSignal = shallowRef<MeshTracksideSignalChartData | null>(null)')
    expect(meshAnalysisViewSource).toContain('markRaw(await getMeshTracksideSignalChart(')
  })

  it('places RSSI deltas before AP MAC and hides unreliable switch type and duration columns', async () => {
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
    const resolvedLinkColumns = linkTable.props('columns') as Array<{ key: string; fixed?: string }>
    const linkKeys = resolvedLinkColumns.map((column) => column.key)
    expect(linkKeys.slice(0, 10)).toEqual([
      'record_id', 'timestamp', 'timestamp_tag', 'local_radio', 'link_role', 'peer_mac', 'peer_ap_name',
      'local_rssi_db', 'peer_rssi_db', 'peer_ap_mac',
    ])
    expect(resolvedLinkColumns.find((column) => column.key === 'timestamp_tag')?.fixed).toBe('left')
    const switchTable = tables.find((table) => table.props('tableId') === 'mesh-analysis-switch-events:v3')!
    const switchKeys = (switchTable.props('columns') as Array<{ key: string }>).map((column) => column.key)
    expect(switchKeys).toEqual([
      'timestamp', 'local_radio', 'from_ap_name', 'from_peer_mac', 'to_ap_name', 'to_peer_mac',
      'rssi_change', 'is_short_link', 'is_pingpong', 'station', 'section',
    ])
    expect(switchKeys).not.toContain('event_type')
    expect(switchKeys).not.toContain('duration_ms')
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
      max_points: 600,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
    })
    expect(mocks.getTracksideSignal).toHaveBeenLastCalledWith('session-locked', {
      max_points: 600,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
    }, expect.anything())
    const tracksideChart = wrapper.findAllComponents(meshChartStub).find((chart) => chart.props('scope') === '')
    expect(tracksideChart?.props('events')).toEqual([])

    await wrapper.findAll('button').find((button) => button.text() === '锁定当前时间范围')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(`已锁定 ${chartViewport.start_time} — ${chartViewport.end_time}`)

    await wrapper.findAll('button').find((button) => button.text() === '查看同期空口负载')!.trigger('click')
    await flushPromises()

    expect(mocks.getActivePath).toHaveBeenLastCalledWith('session-locked', {
      max_points: 600,
      radio: 1,
      time_from: chartViewport.start_time,
      time_to: chartViewport.end_time,
    })
    expect(wrapper.text()).toContain('已使用 RSSI 锁定时间')

    await wrapper.findAll('button').filter((button) => button.text() === '查看')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('已锁定 2026-07-20 10:00:01.123')
    expect(wrapper.findAll('button').some((button) => button.text() === '锁定当前时间范围')).toBe(true)
    wrapper.unmount()
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

    expect(mocks.getSession).toHaveBeenCalledWith('session-1')
    expect(mocks.listBuildOrder).toHaveBeenCalledWith('session-1', expect.objectContaining({ page: 1, page_size: 100, sort_order: 'desc' }))
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
      max_points: 600,
      radio: 1,
    })

    expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-1', {
      max_points: 600,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
    }, expect.anything())
    const activeRssiChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      chart.props('scope') === 'active' && (chart.props('points') as unknown[]).length > 0
    ))
    expect(activeRssiChart?.props('syncViewport')).toMatchObject({
      start_time: fullStart,
      end_time: '2026-07-20 10:00:15.000',
      full_start_time: fullStart,
      full_end_time: fullEnd,
    })
    const tracksideChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      ((chart.props('seriesCache') as { series?: unknown[] } | null)?.series?.length ?? 0) > 0
    ))
    expect(tracksideChart?.props('active')).toBe(false)
    intersectionCallbacks[0]?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
    await flushPromises()
    expect(tracksideChart?.props('active')).toBe(true)
    expect(wrapper.text()).toContain(`最早 ${fullStart}`)
    expect(wrapper.text()).toContain(`最新 ${fullEnd}`)

    mocks.getActivePath.mockClear()
    mocks.getTracksideSignal.mockClear()
    mocks.chartApplyViewport.mockClear()
    const targetPointSelect = wrapper.findAllComponents(selectStub).find((select) => (
      select.findAll('[data-option-label]').some((option) => option.text() === '目标 1200 点')
    ))
    await targetPointSelect!.vm.$emit('update:modelValue', 1200)
    await targetPointSelect!.vm.$emit('change', 1200)
    await flushPromises()
    expect(mocks.getActivePath).toHaveBeenCalledWith('session-1', {
      max_points: 1200,
      radio: 1,
    })
    expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-1', {
      max_points: 1200,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
    }, expect.anything())
    expect(activeRssiChart?.props('syncViewport')).toMatchObject({
      start_time: fullStart,
      end_time: '2026-07-20 10:00:15.000',
    })

    await wrapper.findAll('button').find((button) => button.text() === '重置视图')!.trigger('click')
    await flushPromises()
    expect(mocks.chartResetViewport).not.toHaveBeenCalled()
    const rssiChart = wrapper.findAllComponents(meshChartStub).find((chart) => (
      chart.props('scope') === 'active' && (chart.props('points') as unknown[]).length > 0
    ))
    expect(rssiChart?.props('syncViewport')).toMatchObject({
      start_time: fullStart,
      end_time: fullEnd,
    })

    const openAgain = wrapper.findAll('button').find((button) => button.text() === '查看')
    await openAgain!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
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
      max_points: 600,
      radio: 1,
    })
    expect(mocks.getTracksideSignal).toHaveBeenCalledWith('session-link', {
      max_points: 600,
      radio: 1,
      time_from: undefined,
      time_to: undefined,
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
    await wrapper.findAll('button').find((button) => button.text() === '打开任务窗口')!.trigger('click')
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

    await wrapper.findAll('button').find((button) => button.text() === '重新加载轨旁信号图')!.trigger('click')
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

  it('keeps the no-selection session list expanded even when this window previously stored collapse', async () => {
    sessionStorage.setItem('netconsole.mesh-analysis.session-expanded', 'false')
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })
})
