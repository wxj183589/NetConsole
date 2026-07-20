// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listProfiles: vi.fn(),
  listVehicleMrs: vi.fn(),
  prepareContext: vi.fn(),
  recoverTasks: vi.fn(),
  getSession: vi.fn(),
  listSessions: vi.fn(),
  listBuildOrder: vi.fn(),
  getActivePath: vi.fn(),
  getPeerPath: vi.fn(),
  getRateSeries: vi.fn(),
  getCounterDeltas: vi.fn(),
  listAnomalies: vi.fn(),
  exportDetails: vi.fn(),
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
  getMeshRawTail: vi.fn(),
  getMeshCounterDeltas: mocks.getCounterDeltas,
  getMeshRateSeries: mocks.getRateSeries,
  listMeshActiveBuildOrder: mocks.listBuildOrder,
  listMeshAnalysisSessions: mocks.listSessions,
  listMeshAnomalies: mocks.listAnomalies,
  listMeshArtifacts: vi.fn(),
  listMeshLinks: vi.fn(),
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
  props: { label: { type: String, default: '' } },
  setup(props) { return () => h('span', { 'data-option-label': props.label }, props.label) },
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
  setup(_props, { expose }) {
    expose({
      getViewport: () => chartViewport,
      getVisibleTimeRange: () => chartViewport,
      applyViewport: vi.fn(),
      resetViewport: vi.fn(),
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
  ElDialog: passthrough,
  ElDivider: passthrough,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: passthrough,
  ElIcon: passthrough,
  ElOption: optionStub,
  ElPagination: passthrough,
  ElSelect: passthrough,
  ElTabPane: passthrough,
  ElTabs: passthrough,
  ElTag: passthrough,
  MeshChannelBusyChart: meshChartStub,
  MeshRssiChart: meshChartStub,
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
  mocks.getActivePath.mockResolvedValue({ mode: 'active_path', anchor: null, points: [], events: [], total_points: 0, downsampled: false, summary: {}, time_from: null, time_to: null })
  mocks.getPeerPath.mockResolvedValue({ mode: 'peer_segment', anchor: null, points: [], events: [], total_points: 0, downsampled: false, summary: {}, time_from: null, time_to: null })
  mocks.exportDetails.mockResolvedValue({ action: 'mesh_link_detail_export', task_id: 'mesh-export-1', status: 'RUNNING' })
})

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

    expect(mocks.exportDetails).toHaveBeenCalledWith('session-1', 1)
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
    mocks.getPeerPath.mockResolvedValue({
      mode: 'peer_segment', anchor: null, points, events: [], location_segments: [], total_points: 3, returned_points: 3,
      downsampled: false, summary: { sample_count: 3 }, time_from: build.build_start_time, time_to: build.build_end_time,
    })
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '查看')!.trigger('click')
    await flushPromises()
    await wrapper.find('.sessions-toggle').trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === '查看动态图')!.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '锁定当前时间范围')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(`已锁定 ${chartViewport.start_time} — ${chartViewport.end_time}`)

    await wrapper.findAll('button').find((button) => button.text() === '查看同期空口负载')!.trigger('click')
    await flushPromises()

    expect(mocks.getPeerPath).toHaveBeenLastCalledWith('session-locked', {
      anchor_link_id: 10,
      max_points: 600,
      all_visits: null,
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
    const session = {
      session_id: 'session-1', mr_name: '列车34-MR-CW', original_filename: '34-CW.log', first_sample_time: '2026-07-20 10:00:00.000', last_sample_time: '2026-07-20 11:00:00.000',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1, 2], warnings: [], sources: [{ source_file_id: 7, source_action_id: 'source-1', source_id: 'source-1', exists: true, rebuild_capability: 'ready' }] })
    mocks.listBuildOrder.mockResolvedValue({ items: [{ sequence: 1, anchor_link_id: 10, peer_ap_name: 'AP-1', active_peer_mac: 'aa', build_start_time: '2026-07-20 10:00:00.000', build_end_time: '2026-07-20 10:00:10.000', build_result: 'normal' }], total: 1, page: 1, page_size: 100 })

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
    expect(mocks.getPeerPath).toHaveBeenCalledWith('session-1', {
      anchor_link_id: 10,
      max_points: 600,
      all_visits: null,
      time_from: '2026-07-20 10:00:00.000',
      time_to: '2026-07-20 10:00:10.000',
    })

    mocks.listBuildOrder.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 100 })
    const queryButtons = wrapper.findAll('button').filter((button) => button.text() === '查询')
    await queryButtons[1].trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-option-label]').some((option) => option.text().includes('第 1 次 · Radio'))).toBe(true)

    const openAgain = wrapper.findAll('button').find((button) => button.text() === '查看')
    await openAgain!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
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

  it('keeps the no-selection session list expanded even when this window previously stored collapse', async () => {
    sessionStorage.setItem('netconsole.mesh-analysis.session-expanded', 'false')
    const wrapper = mount(MeshAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    expect(wrapper.find('.sessions-toggle').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })
})
