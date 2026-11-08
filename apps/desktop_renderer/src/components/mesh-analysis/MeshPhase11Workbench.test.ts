// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MeshPhase11Workbench from './MeshPhase11Workbench.vue'

const api = vi.hoisted(() => ({ summary: vi.fn(), aps: vi.fn(), links: vi.fn(), counter: vi.fn(), path: vi.fn(), issues: vi.fn() }))
vi.mock('../../api/meshAnalysis', () => ({
  getMeshBusinessSummary: api.summary, listMeshApSignalStatistics: api.aps, listMeshLinks: api.links,
  getMeshCounterDeltas: api.counter, getMeshActivePathChart: api.path, listMeshParseIssues: api.issues,
}))
vi.mock('./MeshMetricChart.vue', () => ({ default: defineComponent({ props: ['points'], emits: ['render-complete'], setup: (props, { emit }) => () => h('div', { class: 'metric-chart', onVnodeMounted: () => emit('render-complete') }, String(props.points?.length || 0)) }) }))

const session = { session_id: 'mesh-1', train_name: '列车01', mr_name: '列车01-MR-CT', first_sample_time: '2026-01-01 00:00:00', last_sample_time: '2026-01-01 00:01:00', raw_log_count: 10, link_record_count: 8, active_link_count: 4, standby_link_count: 4, error_count: 1, warning_count: 2, analysis_status: 'done', parsed_status: 'ready', data_integrity: 'complete' } as any
const stubs = {
  NcDataTable: defineComponent({ props: ['data'], setup: props => () => h('div', { class: 'table' }, String(props.data?.length || 0)) }),
  ElCheckbox: defineComponent({ setup: (_, { slots }) => () => h('label', slots.default?.()) }),
  ElButton: defineComponent({ setup: (_, { slots }) => () => h('button', slots.default?.()) }),
  ElSkeleton: defineComponent({ setup: () => () => h('div', 'skeleton') }),
  ElEmpty: defineComponent({ props: ['description'], setup: props => () => h('div', props.description) }),
  ElAlert: defineComponent({ props: ['title'], setup: props => () => h('div', props.title) }),
}

beforeEach(() => {
  vi.resetAllMocks()
  api.summary.mockResolvedValue({ ap_total: 2, grades: { GOOD: 1, WARNING: 1 }, single_link_count: 1, single_link_ap_count: 1 })
  api.aps.mockResolvedValue({ items: [{ peer_ap_name: 'AP-1' }], total: 1 })
  api.links.mockResolvedValue({ items: [{ timestamp: '2026-01-01 00:00:00', link_role: 'ACTIVE', peer_ap_name: 'AP-1' }], total: 1 })
  api.counter.mockResolvedValue({ items: [], total: 0 })
  api.path.mockResolvedValue({ points: [], events: [], location_segments: [], summary: {} })
  api.issues.mockResolvedValue({ items: [], total: 0 })
})

describe('Mesh Phase 11 workbench', () => {
  it('loads the overview first and lazy loads AP and main workspaces', async () => {
    const wrapper = mount(MeshPhase11Workbench, { props: { sessionId: 'mesh-1', session }, global: { stubs } })
    await flushPromises()
    expect(api.summary).toHaveBeenCalledOnce()
    expect(api.aps).not.toHaveBeenCalled()
    await wrapper.findAll('.phase11-nav button')[2]!.trigger('click')
    await flushPromises()
    expect(api.aps).toHaveBeenCalledOnce()
    await wrapper.findAll('.phase11-nav button')[3]!.trigger('click')
    await flushPromises()
    expect(api.path).toHaveBeenCalledOnce()
    expect(api.counter).toHaveBeenCalledOnce()
    expect(api.links).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
