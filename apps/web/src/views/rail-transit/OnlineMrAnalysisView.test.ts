// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getOnlineMrSession: vi.fn(),
  listRecentOnlineMrSessions: vi.fn(),
  queryOnlineMrMetrics: vi.fn(),
  queryOnlineMrSwitchRssiWindows: vi.fn(),
  queryOnlineMrTimeline: vi.fn(),
  recoverRailTransitTasks: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('../../api/onlineMr', () => ({
  getOnlineMrRawTail: vi.fn(),
  getOnlineMrSession: mocks.getOnlineMrSession,
  listOnlineMrRawFiles: vi.fn(),
  listRecentOnlineMrSessions: mocks.listRecentOnlineMrSessions,
  queryOnlineMrMetrics: mocks.queryOnlineMrMetrics,
  queryOnlineMrSwitchRssiWindows: mocks.queryOnlineMrSwitchRssiWindows,
  queryOnlineMrTimeline: mocks.queryOnlineMrTimeline,
}))
vi.mock('../../api/railTransitWeb', () => ({
  exportOnlineMrReport: vi.fn(),
  getRailTransitTask: vi.fn(),
  recoverRailTransitTasks: mocks.recoverRailTransitTasks,
}))
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: mocks.routerPush }),
}))

import OnlineMrAnalysisView from './OnlineMrAnalysisView.vue'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) { const attrs = useAttrs(); return () => h('div', attrs, slots.default?.()) },
})
const tabsStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['tab-change'],
  setup(props, { emit, slots }) {
    return () => h('div', props.modelValue === 'session-history' || props.modelValue === 'statistics' || props.modelValue === 'charts'
      ? [
          h('button', { 'data-testid': 'statistics-tab', onClick: () => emit('tab-change', 'statistics') }, '无线统计'),
          h('button', { 'data-testid': 'charts-tab', onClick: () => emit('tab-change', 'charts') }, '动态图'),
          slots.default?.(),
        ]
      : [
          h('button', { 'data-testid': 'switch-history-chart', onClick: () => emit('tab-change', 'switch-rssi') }, '切换历史图'),
          h('button', { 'data-testid': 'switch-realtime-chart', onClick: () => emit('tab-change', 'switch-log-rssi') }, '实时切换图'),
          slots.default?.(),
        ])
  },
})
const tableStub = defineComponent({
  props: { data: { type: Array, default: () => [] }, emptyText: { type: String, default: '' } },
  setup(props) { return () => h('div', props.data.length ? `${props.data.length} rows` : props.emptyText) },
})
const stubs: Record<string, Component | boolean> = {
  ElAlert: passthrough,
  ElButton: passthrough,
  ElDatePicker: passthrough,
  ElEmpty: passthrough,
  ElInput: passthrough,
  ElInputNumber: passthrough,
  ElOption: passthrough,
  ElSelect: passthrough,
  ElTabPane: passthrough,
  ElTabs: tabsStub,
  NcDataTable: tableStub,
  OnlineMrAnalysisChart: passthrough,
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listRecentOnlineMrSessions.mockResolvedValue([{ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', started_at: '2026-07-20 10:00:00' }])
  mocks.getOnlineMrSession.mockResolvedValue({ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', data_integrity: 'complete', database_summary: {} })
  mocks.queryOnlineMrMetrics.mockResolvedValue({ series: [], limit: 1000, offset: 0, page_size_per_metric: 1000, next_offset: 1000, returned_points: 0, has_more: false })
  mocks.queryOnlineMrSwitchRssiWindows.mockResolvedValue({ items: [], limit: 200, offset: 0, has_more: false })
  mocks.queryOnlineMrTimeline.mockResolvedValue([])
  mocks.recoverRailTransitTasks.mockResolvedValue([])
})

async function renderView() {
  const wrapper = mount(OnlineMrAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
  await flushPromises()
  return wrapper
}

describe('Online MR analysis view behavior', () => {
  it('queries real radio statistics with bounded paging instead of row counts', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="statistics-tab"]').trigger('click')
    await flushPromises()

    expect(mocks.queryOnlineMrMetrics).toHaveBeenCalledWith('session-1', ['radio_statistics'], expect.objectContaining({ limit: 1000, offset: 0 }))
    expect(wrapper.text()).toContain('暂无统计数据')
    wrapper.unmount()
  })

  it('uses source-specific switch snapshots and clears report polling on unmount', async () => {
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout')
    mocks.recoverRailTransitTasks.mockResolvedValueOnce([{ task_id: 'report-1', action: 'online_mr_report', status: 'RUNNING' }])
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    mocks.queryOnlineMrMetrics.mockClear()
    mocks.queryOnlineMrSwitchRssiWindows.mockClear()
    await wrapper.get('[data-testid="switch-history-chart"]').trigger('click')
    await wrapper.get('[data-testid="switch-realtime-chart"]').trigger('click')
    await flushPromises()

    expect(mocks.queryOnlineMrSwitchRssiWindows).toHaveBeenCalledWith('session-1', 'history', expect.objectContaining({ limit: 200, offset: 0 }))
    expect(mocks.queryOnlineMrSwitchRssiWindows).toHaveBeenCalledWith('session-1', 'realtime', expect.objectContaining({ limit: 200, offset: 0 }))
    expect(mocks.queryOnlineMrMetrics).not.toHaveBeenCalledWith('session-1', ['rssi'], expect.anything())
    wrapper.unmount()
    expect(clearTimeoutSpy).toHaveBeenCalled()
  })
})
