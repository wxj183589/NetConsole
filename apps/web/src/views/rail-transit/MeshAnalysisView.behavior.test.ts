// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listProfiles: vi.fn(),
  listVehicleMrs: vi.fn(),
  prepareContext: vi.fn(),
  recoverTasks: vi.fn(),
}))

vi.mock('../../api/meshAnalysis', () => ({
  applyMeshBundleImport: vi.fn(),
  createMeshProfile: vi.fn(),
  getMeshAnalysisSession: vi.fn(),
  getMeshAnalysisSummary: vi.fn().mockResolvedValue({ session_count: 0, train_count: 0, mr_count: 0 }),
  getMeshChannelBusy: vi.fn(),
  getMeshRawTail: vi.fn(),
  getMeshCounterDeltas: vi.fn(),
  getMeshRssi: vi.fn(),
  getMeshRateSeries: vi.fn(),
  getMeshTimeline: vi.fn(),
  listMeshAnalysisSessions: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 }),
  listMeshAnomalies: vi.fn(),
  listMeshApStatistics: vi.fn(),
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
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

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
  ElOption: passthrough,
  ElPagination: passthrough,
  ElSelect: passthrough,
  ElTabPane: passthrough,
  ElTabs: passthrough,
  ElTag: passthrough,
  MeshChannelBusyChart: true,
  MeshCounterDeltaChart: true,
  MeshRateChart: true,
  MeshRssiChart: true,
  MeshSwitchRssiChart: true,
  NcDataTable: passthrough,
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listProfiles.mockResolvedValue([])
  mocks.listVehicleMrs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 })
  mocks.prepareContext.mockResolvedValue({ site_id: 'demo', vehicle_mr_count: 0, profile_count: 0, created_count: 0, updated_count: 0 })
  mocks.recoverTasks.mockResolvedValue([])
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
