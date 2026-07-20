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
  routerPush: vi.fn(),
}))

vi.mock('../../api/meshAnalysis', () => ({
  applyMeshBundleImport: vi.fn(),
  createMeshProfile: vi.fn(),
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
  props: { data: { type: Array, default: () => [] }, tableId: { type: String, default: '' } },
  setup(props, { attrs, slots }) {
    return () => h('div', { ...attrs, 'data-table-id': props.tableId }, props.data.flatMap((row) => [
      slots.default?.({ row }),
      slots['cell-actions']?.({ row }),
    ]))
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
  MeshChannelBusyChart: true,
  MeshRssiChart: true,
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
  it('collapses sessions after opening a source, defaults to build order and lazily keeps charts unloaded', async () => {
    const session = {
      session_id: 'session-1', mr_name: '列车34-MR-CW', original_filename: '34-CW.log', first_sample_time: '2026-07-20 10:00:00.000', last_sample_time: '2026-07-20 11:00:00.000',
      parsed_status: 'ready', warning_count: 0, report_count: 0,
    }
    mocks.listSessions.mockResolvedValue({ items: [session], total: 1, page: 1, page_size: 50 })
    mocks.getSession.mockResolvedValue({ session, analysis_params: {}, available_radios: [1, 2], warnings: [], sources: [{ source_id: 'source-1', exists: true, rebuild_capability: 'ready' }] })
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
