// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getOnlineMrBusinessSummary: vi.fn(),
  getOnlineMrSession: vi.fn(),
  listRecentOnlineMrSessions: vi.fn(),
  queryOnlineMrMetrics: vi.fn(),
  queryOnlineMrBusinessTable: vi.fn(),
  queryOnlineMrSwitchRssiWindows: vi.fn(),
  queryOnlineMrTimeline: vi.fn(),
  recoverRailTransitTasks: vi.fn(),
  parseOnlineMrSession: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('../../api/onlineMr', () => ({
  getOnlineMrRawTail: vi.fn(),
  getOnlineMrBusinessSummary: mocks.getOnlineMrBusinessSummary,
  getOnlineMrSession: mocks.getOnlineMrSession,
  listOnlineMrRawFiles: vi.fn(),
  listRecentOnlineMrSessions: mocks.listRecentOnlineMrSessions,
  queryOnlineMrMetrics: mocks.queryOnlineMrMetrics,
  queryOnlineMrBusinessTable: mocks.queryOnlineMrBusinessTable,
  queryOnlineMrSwitchRssiWindows: mocks.queryOnlineMrSwitchRssiWindows,
  queryOnlineMrTimeline: mocks.queryOnlineMrTimeline,
}))
vi.mock('../../api/railTransitWeb', () => ({
  exportOnlineMrReport: vi.fn(),
  getRailTransitTask: vi.fn(),
  parseOnlineMrSession: mocks.parseOnlineMrSession,
  recoverRailTransitTasks: mocks.recoverRailTransitTasks,
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true) }) }))
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: mocks.routerPush }),
}))

import OnlineMrAnalysisView from './OnlineMrAnalysisView.vue'
import source from './OnlineMrAnalysisView.vue?raw'

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
const selectStub = defineComponent({
  props: { modelValue: { type: String, default: '' }, placeholder: { type: String, default: '' } },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) { return () => h('div', [slots.default?.(), props.placeholder === '选择 Online MR 会话' ? h('button', { 'data-testid': 'session-b', onClick: () => { emit('update:modelValue', 'session-2'); emit('change', 'session-2') } }, '切换会话') : null]) },
})
const chartStub = defineComponent({
  props: { series: { type: Array, default: () => [] } },
  setup(props) { return () => h('div', { 'data-testid': 'chart-series' }, JSON.stringify(props.series)) },
})
const stubs: Record<string, Component | boolean> = {
  ElAlert: passthrough,
  ElButton: passthrough,
  ElDatePicker: passthrough,
  ElEmpty: passthrough,
  ElInput: passthrough,
  ElInputNumber: passthrough,
  ElIcon: passthrough,
  ElOption: passthrough,
  ElSelect: selectStub,
  ElTabPane: passthrough,
  ElTabs: tabsStub,
  NcDataTable: tableStub,
  OnlineMrAnalysisChart: chartStub,
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listRecentOnlineMrSessions.mockResolvedValue([{ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', started_at: '2026-07-20 10:00:00' }])
  mocks.getOnlineMrSession.mockResolvedValue({ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', data_integrity: 'complete', has_raw_data: true, database_summary: { status: 'ready', compatible: true, parser_version: 'v8', missing_capabilities: [], message: '解析数据库可用。' } })
  mocks.getOnlineMrBusinessSummary.mockResolvedValue({ session_id: 'session-1', sample_count: 0, active_count: 0, standby_count: 0, active_segment_count: 0, switch_count: 0, fping_point_count: 0, iperf_point_count: 0, channel_busy_count: 0, interface_pps_count: 0, diagnosis_count: 0, first_sample_time: null, last_sample_time: null, estimated_interval_seconds: null, time_sync_status: 'unknown', time_sync_avg_offset_ms: null, current_radio: null, current_link_state: '', current_peer_mac: '', current_peer_name: '', current_ap_mac: '', current_peer_radio_mac: '', current_station: '', current_section: '', current_rssi: null, current_segment_start: null, current_segment_end: null, current_segment_duration_seconds: null })
  mocks.queryOnlineMrMetrics.mockResolvedValue({ series: [], limit: 1000, offset: 0, page_size_per_metric: 1000, next_offset: 1000, returned_points: 0, has_more: false })
  mocks.queryOnlineMrBusinessTable.mockResolvedValue({ table: 'radio_statistics', rows: [], limit: 500, offset: 0, returned_count: 0, next_offset: 500, has_more: false })
  mocks.queryOnlineMrSwitchRssiWindows.mockResolvedValue({ items: [], limit: 200, offset: 0, has_more: false })
  mocks.queryOnlineMrTimeline.mockResolvedValue([])
  mocks.recoverRailTransitTasks.mockResolvedValue([])
  mocks.parseOnlineMrSession.mockResolvedValue({ task_id: 'parse-1', action: 'online_mr_parse', status: 'COMPLETED' })
})

async function renderView() {
  const wrapper = mount(OnlineMrAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
  await flushPromises()
  return wrapper
}

describe('Online MR analysis view behavior', () => {
  it('shows TCP rate limit as an unlimited TCP field in iPerf tables', () => {
    expect(source).toContain('TCP 限速')
    expect(source).toContain('iperfRateLimitLabel')
    expect(source).toContain('不限速')
    expect(source).not.toContain('TCP 总限速')
  })

  it('wraps inline Search and Document SVGs in bounded icon containers', async () => {
    const wrapper = await renderView()

    expect(wrapper.findAll('.inline-icon')).toHaveLength(2)
    expect(wrapper.find('.query-hint > svg').exists()).toBe(false)
    expect(wrapper.find('.report-card h2 > svg').exists()).toBe(false)
    expect(wrapper.find('.report-card').exists()).toBe(true)
    wrapper.unmount()
  })

  it('queries real radio statistics with bounded paging instead of row counts', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="statistics-tab"]').trigger('click')
    await flushPromises()

    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledWith('session-1', 'radio_statistics', expect.objectContaining({ limit: 500, offset: 0 }))
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

  it('clears session A charts before session B missing parsed detail is applied', async () => {
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([
      { session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'STOPPED', started_at: '2026-07-20 10:00:00' },
      { session_id: 'session-2', device_name: 'MR-2', mr_name: 'MR-2', status: 'ABORTED', started_at: '2026-07-20 11:00:00' },
    ])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionId === 'session-1'
      ? { session_id: sessionId, device_name: 'MR-1', status: 'STOPPED', has_raw_data: true, data_integrity: 'partial', database_summary: { status: 'ready', compatible: true, parser_version: 'v8', missing_capabilities: [], message: '解析数据库可用。' } }
      : { session_id: sessionId, device_name: 'MR-2', status: 'ABORTED', has_raw_data: true, data_integrity: 'partial', database_summary: { status: 'missing', compatible: false, parser_version: null, missing_capabilities: ['mesh_link'], message: '当前会话尚未生成解析数据库，原始日志仍可查看。' } })
    mocks.queryOnlineMrMetrics.mockResolvedValueOnce({ series: [{ metric_type: 'rssi', series_key: 'AP-A', unit: 'dBm', points: [{ timestamp: 't', value: -61, text_value: null, dimensions: {} }], summary: { count: 1, minimum: -61, maximum: -61, average: -61 } }], limit: 1000, offset: 0, page_size_per_metric: 1000, next_offset: 1000, returned_points: 1, has_more: false })
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('-61')

    await wrapper.get('[data-testid="session-b"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('-61')
    expect(wrapper.text()).toContain('当前会话尚未生成解析数据库')
    expect(wrapper.text()).toContain('解析当前会话')
    expect(mocks.queryOnlineMrMetrics).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-testid="parse-session"]').trigger('click')
    await flushPromises()
    expect(mocks.parseOnlineMrSession).toHaveBeenCalledWith('session-2', false)
    wrapper.unmount()
  })
})
