// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getOnlineMrBusinessSummary: vi.fn(),
  getOnlineMrSession: vi.fn(),
  listRecentOnlineMrSessions: vi.fn(),
  queryOnlineMrMetrics: vi.fn(),
  queryOnlineMrBusinessTable: vi.fn(),
  queryOnlineMrSwitchRssiWindows: vi.fn(),
  queryOnlineMrTimeline: vi.fn(),
  deleteOnlineMrSession: vi.fn(),
  exportOnlineMrReport: vi.fn(),
  getRailTransitTask: vi.fn(),
  recoverRailTransitTasks: vi.fn(),
  parseOnlineMrSession: vi.fn(),
  confirm: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
  messageError: vi.fn(),
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
  deleteOnlineMrSession: mocks.deleteOnlineMrSession,
  exportOnlineMrReport: mocks.exportOnlineMrReport,
  getRailTransitTask: mocks.getRailTransitTask,
  parseOnlineMrSession: mocks.parseOnlineMrSession,
  recoverRailTransitTasks: mocks.recoverRailTransitTasks,
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: mocks.confirm }) }))
vi.mock('../../composables/useAvailablePanelHeight', () => ({
  useAvailablePanelHeight: () => ({ height: { value: 520 } }),
}))
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessage: {
      success: mocks.messageSuccess,
      warning: mocks.messageWarning,
      error: mocks.messageError,
    },
  }
})
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
    const mainTabs = new Set(['session-history', 'mesh-link', 'mesh-detail', 'channel-busy', 'switch-history', 'active-switch', 'interface-rate', 'fping', 'iperf', 'diagnosis', 'raw', 'logs', 'charts'])
    return () => h('div', mainTabs.has(props.modelValue)
      ? [
          h('button', { 'data-testid': 'main-link-tab', onClick: () => emit('tab-change', 'mesh-link') }, '主链路信息'),
          h('button', { 'data-testid': 'link-detail-tab', onClick: () => emit('tab-change', 'mesh-detail') }, '链路明细'),
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
  props: {
    data: { type: Array, default: () => [] },
    emptyText: { type: String, default: '' },
    columns: { type: Array, default: () => [] },
    currentRowKey: { type: String, default: '' },
  },
  emits: ['row-click'],
  setup(props, { emit }) {
    return () => h('div', { 'data-current-row-key': props.currentRowKey }, [
      h('div', props.columns.map((column: any) => column.label).join('|')),
      h('div', props.data.length ? `${props.data.length} rows` : props.emptyText),
      ...props.data
        .filter((row: any) => typeof row?.session_id === 'string')
        .map((row: any) => h('button', {
          'data-testid': `table-row-${row.session_id}`,
          onClick: () => emit('row-click', row),
        }, row.session_id)),
    ])
  },
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
  Reflect.deleteProperty(window, 'netconsoleDesktop')
  mocks.confirm.mockResolvedValue(true)
  mocks.listRecentOnlineMrSessions.mockResolvedValue([{ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', started_at: '2026-07-20 10:00:00' }])
  mocks.getOnlineMrSession.mockResolvedValue({ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', started_at: '2026-07-20 10:00:00', duration_minutes: 18.5, data_integrity: 'complete', has_raw_data: true, database_summary: { status: 'ready', compatible: true, parser_version: 'online_mr_business_tables_v9_no_source_fields', missing_capabilities: [], message: '解析数据库可用。' } })
  mocks.getOnlineMrBusinessSummary.mockResolvedValue({ session_id: 'session-1', sample_count: 0, active_count: 0, standby_count: 0, active_segment_count: 0, switch_count: 0, fping_point_count: 0, iperf_point_count: 0, channel_busy_count: 0, interface_pps_count: 0, diagnosis_count: 0, first_sample_time: null, last_sample_time: null, estimated_interval_seconds: null, time_sync_status: 'unknown', time_sync_avg_offset_ms: null, current_radio: null, current_link_state: '', current_peer_mac: '', current_peer_name: '', current_ap_mac: '', current_peer_radio_mac: '', current_station: '', current_section: '', current_rssi: null, current_segment_start: null, current_segment_end: null, current_segment_duration_seconds: null })
  mocks.queryOnlineMrMetrics.mockResolvedValue({ series: [], limit: 1000, offset: 0, page_size_per_metric: 1000, next_offset: 1000, returned_points: 0, has_more: false })
  mocks.queryOnlineMrBusinessTable.mockResolvedValue({ table: 'main_link', rows: [], limit: 500, offset: 0, returned_count: 0, next_offset: 500, has_more: false })
  mocks.queryOnlineMrSwitchRssiWindows.mockResolvedValue({ items: [], limit: 200, offset: 0, has_more: false })
  mocks.queryOnlineMrTimeline.mockResolvedValue([])
  mocks.recoverRailTransitTasks.mockResolvedValue([])
  mocks.parseOnlineMrSession.mockResolvedValue({ task_id: 'parse-1', action: 'online_mr_parse', status: 'COMPLETED' })
  mocks.exportOnlineMrReport.mockResolvedValue({ task_id: 'report-1', action: 'online_mr_report', status: 'PENDING', result_summary: {} })
  mocks.deleteOnlineMrSession.mockResolvedValue({ task_id: 'delete-1', action: 'online_mr_session_delete', status: 'PENDING', result_summary: {} })
})

afterEach(() => {
  vi.useRealTimers()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
})

async function renderView() {
  const wrapper = mount(OnlineMrAnalysisView, { global: { stubs, directives: { loading: () => undefined } } })
  await flushPromises()
  return wrapper
}

describe('Online MR analysis view behavior', () => {
  it('uses refactored business labels without radio statistics or source columns', () => {
    expect(source).toContain('主链路信息')
    expect(source).toContain('链路明细')
    expect(source).toContain('主链路切换历史')
    expect(source).toContain('主链路切换日志')
    expect(source).toContain('接口速率')
    expect(source).toContain('fping 1s 聚合')
    expect(source).toContain('打流测试')
    expect(source).not.toContain('无线统计')
    expect(source).not.toContain('来源文件')
    expect(source).not.toContain('raw_file')
    expect(source).not.toContain('raw_line')
    expect(source).not.toContain('TCP 限速')
  })

  it('keeps only the bounded Search icon and moves report creation into the top action row', async () => {
    const wrapper = await renderView()

    expect(wrapper.findAll('.inline-icon')).toHaveLength(1)
    expect(wrapper.find('.query-hint > svg').exists()).toBe(false)
    expect(wrapper.find('.report-card').exists()).toBe(false)
    expect(wrapper.get('[data-testid="open-session-location"]').text()).toContain('打开本地目录')
    expect(wrapper.get('[data-testid="generate-report"]').text()).toContain('生成 XLSX 报告')
    expect(wrapper.get('[data-testid="delete-session"]').text()).toBe('删除')
    wrapper.unmount()
  })

  it('submits one report task from the top action and leaves progress in the task window', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="generate-report"]').trigger('click')
    await flushPromises()

    expect(mocks.exportOnlineMrReport).toHaveBeenCalledOnce()
    expect(mocks.exportOnlineMrReport).toHaveBeenCalledWith('session-1', '')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('分析报告任务已提交，请在任务窗口查看进度。')
    expect(mocks.routerPush).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('disables all session-dependent actions when no session is selected', async () => {
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([])
    const wrapper = await renderView()

    for (const testId of [
      'parse-session',
      'force-reparse-session',
      'open-session-location',
      'generate-report',
      'delete-session',
    ]) {
      expect(wrapper.get(`[data-testid="${testId}"]`).attributes('disabled')).toBeDefined()
    }
    expect(mocks.getOnlineMrSession).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps selector and table highlight synchronized when a row is selected', async () => {
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([
      { session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'STOPPED', started_at: '2026-07-20 10:00:00' },
      { session_id: 'session-2', device_name: 'MR-2', mr_name: 'MR-2', status: 'STOPPED', started_at: '2026-07-20 11:00:00' },
    ])
    mocks.getOnlineMrSession.mockImplementation(async (value: string) => ({
      session_id: value,
      device_name: value === 'session-1' ? 'MR-1' : 'MR-2',
      status: 'STOPPED',
      data_integrity: 'complete',
      has_raw_data: true,
      database_summary: { status: 'ready', compatible: true, parser_version: 'v9', missing_capabilities: [], message: '解析数据库可用。' },
    }))
    const wrapper = await renderView()
    expect(wrapper.find('[data-current-row-key="session-1"]').exists()).toBe(true)

    await wrapper.get('[data-testid="table-row-session-2"]').trigger('click')
    await flushPromises()

    expect(mocks.getOnlineMrSession).toHaveBeenLastCalledWith('session-2', expect.any(AbortSignal))
    expect(wrapper.find('[data-current-row-key="session-2"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('disables local location in Browser and sends only the stable session id through Electron', async () => {
    let wrapper = await renderView()
    expect(wrapper.get('[data-testid="open-session-location"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()

    const openLocation = vi.fn().mockResolvedValue({ success: true })
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openOnlineMrSessionLocation: openLocation, openTaskWindow: vi.fn() },
    })
    wrapper = await renderView()
    await wrapper.get('[data-testid="open-session-location"]').trigger('click')
    await flushPromises()

    expect(openLocation).toHaveBeenCalledWith('session-1')
    wrapper.unmount()
  })

  it('keeps data unchanged when deletion is cancelled', async () => {
    mocks.confirm.mockResolvedValueOnce(false)
    const wrapper = await renderView()
    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    await flushPromises()

    expect(mocks.confirm).toHaveBeenCalledWith(expect.objectContaining({
      type: 'DESTRUCTIVE',
      confirmText: '确认删除',
      message: expect.stringContaining('会话 ID：session-1'),
    }))
    expect(mocks.deleteOnlineMrSession).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('session-1')
    wrapper.unmount()
  })

  it('refreshes and selects an adjacent session after background deletion completes', async () => {
    vi.useFakeTimers()
    mocks.listRecentOnlineMrSessions
      .mockResolvedValueOnce([
        { session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'STOPPED', started_at: '2026-07-20 10:00:00' },
        { session_id: 'session-2', device_name: 'MR-2', mr_name: 'MR-2', status: 'STOPPED', started_at: '2026-07-20 11:00:00' },
      ])
      .mockResolvedValueOnce([
        { session_id: 'session-2', device_name: 'MR-2', mr_name: 'MR-2', status: 'STOPPED', started_at: '2026-07-20 11:00:00' },
      ])
    mocks.getRailTransitTask.mockResolvedValue({
      task_id: 'delete-1',
      action: 'online_mr_session_delete',
      status: 'COMPLETED',
      result_summary: {
        session_id: 'session-1',
        session_deleted: true,
        warnings: [],
        failed_items: [],
      },
    })
    const wrapper = await renderView()
    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(mocks.deleteOnlineMrSession).toHaveBeenCalledWith('session-1')
    expect(mocks.listRecentOnlineMrSessions).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-current-row-key="session-2"]').exists()).toBe(true)
    expect(mocks.messageSuccess).toHaveBeenCalledWith('会话及其受管本地数据已删除。')
    wrapper.unmount()
  })

  it('queries main link and link detail with the new business table keys', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="main-link-tab"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="link-detail-tab"]').trigger('click')
    await flushPromises()

    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledWith('session-1', 'main_link', expect.objectContaining({ limit: 500, offset: 0 }))
    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledWith('session-1', 'link_detail', expect.objectContaining({ limit: 500, offset: 0 }))
    expect(wrapper.text()).toContain('暂无链路明细')
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
      ? { session_id: sessionId, device_name: 'MR-1', status: 'STOPPED', has_raw_data: true, data_integrity: 'partial', database_summary: { status: 'ready', compatible: true, parser_version: 'online_mr_business_tables_v9_no_source_fields', missing_capabilities: [], message: '解析数据库可用。' } }
      : { session_id: sessionId, device_name: 'MR-2', status: 'ABORTED', has_raw_data: true, data_integrity: 'partial', database_summary: { status: 'missing', compatible: false, parser_version: null, missing_capabilities: ['main_link'], message: '当前会话尚未生成解析数据库，原始日志仍可查看。' } })
    mocks.queryOnlineMrMetrics.mockResolvedValueOnce({ series: [{ metric_type: 'rssi', series_key: 'AP-A', unit: 'dBm', points: [{ timestamp: 't', value: -61, text_value: null, dimensions: {} }], summary: { count: 1, minimum: -61, maximum: -61, average: -61 } }], limit: 1000, offset: 0, page_size_per_metric: 1000, next_offset: 1000, returned_points: 1, has_more: false })
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('-61')

    await wrapper.get('[data-testid="session-b"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('-61')
    expect(wrapper.get('.parsed-status').attributes('title')).toContain('当前会话尚未生成解析数据库')
    expect(wrapper.text()).toContain('解析当前会话')
    expect(mocks.queryOnlineMrMetrics).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-testid="parse-session"]').trigger('click')
    await flushPromises()
    expect(mocks.parseOnlineMrSession).toHaveBeenCalledWith('session-2', false)
    wrapper.unmount()
  })
})
