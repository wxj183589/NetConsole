// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent, h, KeepAlive, nextTick, ref, useAttrs, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getOnlineMrBusinessSummary: vi.fn(),
  getOnlineMrSession: vi.fn(),
  listRecentOnlineMrSessions: vi.fn(),
  queryOnlineMrMetrics: vi.fn(),
  queryOnlineMrTimelineMetrics: vi.fn(),
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
  routerReplace: vi.fn(),
  routeQuery: {} as Record<string, string>,
}))

vi.mock('../../api/onlineMr', () => ({
  getOnlineMrRawTail: vi.fn(),
  getOnlineMrBusinessSummary: mocks.getOnlineMrBusinessSummary,
  getOnlineMrSession: mocks.getOnlineMrSession,
  listOnlineMrRawFiles: vi.fn(),
  listRecentOnlineMrSessions: mocks.listRecentOnlineMrSessions,
  queryOnlineMrMetrics: mocks.queryOnlineMrMetrics,
  queryOnlineMrTimelineMetrics: mocks.queryOnlineMrTimelineMetrics,
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
  useRoute: () => ({ query: mocks.routeQuery }),
  useRouter: () => ({ push: mocks.routerPush, replace: mocks.routerReplace }),
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
    return () => h('div', { 'data-tabs-model': props.modelValue }, mainTabs.has(props.modelValue)
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
  setup(props, { emit, slots }) {
    return () => h('div', { 'data-current-row-key': props.currentRowKey }, [
      h('div', props.columns.map((column: any) => column.label).join('|')),
      h('div', props.data.length ? `${props.data.length} rows` : props.emptyText),
      ...props.data
        .filter((row: any) => typeof row?.session_id === 'string')
        .map((row: any, index: number) => h('div', { 'data-testid': `table-row-shell-${row.session_id}` }, [
          h('button', {
            'data-testid': `table-row-${row.session_id}`,
            onClick: () => emit('row-click', row),
          }, row.session_id),
          ...(slots['cell-actions']?.({ row, column: { key: 'actions' }, index }) || []),
        ])),
    ])
  },
})
const selectStub = defineComponent({
  props: { modelValue: { type: [String, Number], default: '' }, placeholder: { type: String, default: '' } },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) { return () => h('div', [slots.default?.(), props.placeholder === '选择 Online MR 会话' ? h('button', { 'data-testid': 'session-b', onClick: () => { emit('update:modelValue', 'session-2'); emit('change', 'session-2') } }, '切换会话') : null]) },
})
const chartStub = defineComponent({
  props: { series: { type: Array, default: () => [] } },
  setup(props) { return () => h('div', { 'data-testid': 'chart-series' }, JSON.stringify(props.series)) },
})
const rssiChartStub = defineComponent({
  props: {
    rows: { type: Array, default: () => [] },
    mainSeries: { type: Array, default: () => [] },
    tracksideSeries: { type: Array, default: () => [] },
    historyEvents: { type: Array, default: () => [] },
    realtimeEvents: { type: Array, default: () => [] },
    selectedTime: { type: String, default: '' },
    viewport: { type: Object, default: null },
  },
  emits: ['update:viewport'],
  setup(props) {
    return () => h('div', { 'data-testid': 'rssi-chart-series' }, JSON.stringify({
      rows: props.rows,
      main: props.mainSeries,
      trackside: props.tracksideSeries,
      historyEvents: props.historyEvents,
      realtimeEvents: props.realtimeEvents,
      selectedTime: props.selectedTime,
    }))
  },
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
  OnlineMrRssiChart: rssiChartStub,
}

beforeEach(() => {
  vi.clearAllMocks()
  for (const key of Object.keys(mocks.routeQuery)) delete mocks.routeQuery[key]
  Reflect.deleteProperty(window, 'netconsoleDesktop')
  mocks.confirm.mockResolvedValue(true)
  mocks.listRecentOnlineMrSessions.mockResolvedValue([{ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', started_at: '2026-07-20 10:00:00' }])
  mocks.getOnlineMrSession.mockResolvedValue({ session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'COMPLETED', started_at: '2026-07-20 10:00:00', duration_minutes: 18.5, data_integrity: 'complete', has_raw_data: true, database_summary: { status: 'ready', compatible: true, parser_version: 'online_mr_business_tables_v9_no_source_fields', missing_capabilities: [], message: '解析数据库可用。' } })
  mocks.getOnlineMrBusinessSummary.mockResolvedValue({ session_id: 'session-1', sample_count: 0, active_count: 0, standby_count: 0, active_segment_count: 0, switch_count: 0, fping_point_count: 0, iperf_point_count: 0, channel_busy_count: 0, interface_pps_count: 0, diagnosis_count: 0, first_sample_time: null, last_sample_time: null, estimated_interval_seconds: null, time_sync_status: 'unknown', time_sync_avg_offset_ms: null, current_radio: null, current_link_state: '', current_peer_mac: '', current_peer_name: '', current_ap_mac: '', current_peer_radio_mac: '', current_station: '', current_section: '', current_rssi: null, current_segment_start: null, current_segment_end: null, current_segment_duration_seconds: null })
  mocks.queryOnlineMrMetrics.mockResolvedValue({ series: [], limit: 1000, offset: 0, page_size_per_metric: 1000, next_offset: 1000, returned_points: 0, has_more: false })
  mocks.queryOnlineMrTimelineMetrics.mockResolvedValue([])
  mocks.queryOnlineMrBusinessTable.mockResolvedValue({ table: 'main_link', rows: [], limit: 500, offset: 0, returned_count: 0, next_offset: 500, has_more: false })
  mocks.queryOnlineMrSwitchRssiWindows.mockResolvedValue({ items: [], limit: 200, offset: 0, has_more: false })
  mocks.queryOnlineMrTimeline.mockResolvedValue([])
  mocks.recoverRailTransitTasks.mockResolvedValue([])
  mocks.parseOnlineMrSession.mockResolvedValue({ task_id: 'parse-1', action: 'online_mr_parse', status: 'COMPLETED' })
  mocks.exportOnlineMrReport.mockResolvedValue({ task_id: 'report-1', action: 'online_mr_report', status: 'PENDING', result_summary: {} })
  mocks.deleteOnlineMrSession.mockResolvedValue({ task_id: 'delete-1', action: 'online_mr_session_delete', status: 'PENDING', result_summary: {} })
  mocks.routerPush.mockResolvedValue(undefined)
  mocks.routerReplace.mockImplementation(async (target: { query?: Record<string, string> }) => {
    for (const key of Object.keys(mocks.routeQuery)) delete mocks.routeQuery[key]
    Object.assign(mocks.routeQuery, target.query || {})
  })
})

afterEach(() => {
  vi.useRealTimers()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
})

async function renderView(pinia = createPinia()) {
  const wrapper = mount(OnlineMrAnalysisView, { global: { plugins: [pinia], stubs, directives: { loading: () => undefined } } })
  await flushPromises()
  return wrapper
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function timelineRssiSeries(sessionId: string, values: number[]) {
  return [{
    metric_type: 'rssi',
    series_key: `radio=1|${sessionId}`,
    unit: 'dBm',
    points: values.map((value, index) => ({
      timestamp: `2026-07-21 16:0${index}:00`,
      raw_timestamp: `2026-07-21 16:0${index}:00`,
      normalized_timestamp: `2026-07-21 16:0${index}:00`,
      timestamp_source: 'device',
      correction_ms: 0,
      correction_method: 'none',
      correction_confidence: 'high',
      value,
      text_value: null,
      dimensions: { radio: 1, link_state: 'ACTIVE', peer_name: sessionId },
    })),
    summary: {
      count: values.length,
      minimum: Math.min(...values),
      maximum: Math.max(...values),
      average: values.reduce((total, value) => total + value, 0) / values.length,
    },
  }, {
    metric_type: 'trackside_rssi',
    series_key: `radio=1|ap=${sessionId}`,
    unit: 'dBm',
    points: values.slice(0, 1).map((value) => ({
      timestamp: '2026-07-21 16:00:00',
      raw_timestamp: '2026-07-21 16:00:00',
      normalized_timestamp: '2026-07-21 16:00:00',
      timestamp_source: 'device',
      correction_ms: 0,
      correction_method: 'none',
      correction_confidence: 'high',
      value,
      text_value: null,
      dimensions: { radio: 1, link_state: 'ACTIVE', peer_name: sessionId },
    })),
    summary: {
      count: values.length ? 1 : 0,
      minimum: values[0] ?? null,
      maximum: values[0] ?? null,
      average: values[0] ?? null,
    },
  }]
}

function sessionRow(sessionId: string, status = 'STOPPED') {
  return {
    session_id: sessionId,
    device_name: `MR-${sessionId}`,
    mr_name: `MR-${sessionId}`,
    status,
    phase: status === 'STOPPED' ? 'TERMINAL' : status,
    started_at: `2026-07-20 ${sessionId === 'A' ? '10' : sessionId === 'B' ? '11' : '12'}:00:00`,
    task_status: status === 'STOPPED' ? 'COMPLETED' : 'RUNNING',
    mapping_state: status === 'STOPPED' ? 'TERMINAL' : 'LINKED',
    has_raw_data: true,
    has_package: true,
    finalization_complete: true,
  }
}

function sessionDetail(sessionId: string) {
  return {
    ...sessionRow(sessionId),
    data_integrity: 'complete',
    database_summary: { status: 'ready', compatible: true, parser_version: 'v9', missing_capabilities: [], message: '解析数据库可用。' },
  }
}

function completedDeleteTask(sessionId: string) {
  return {
    task_id: 'delete-1',
    action: 'online_mr_session_delete',
    status: 'COMPLETED',
    result_summary: { session_id: sessionId, session_deleted: true, warnings: [], failed_items: [] },
  }
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
    expect(wrapper.text()).toContain('打开本地目录')
    expect(wrapper.text()).toContain('操作')
    expect(wrapper.text()).not.toContain('打开任务中心')
    wrapper.unmount()
  })

  it('submits one report task from the top action and leaves progress in the task window', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="generate-report"]').trigger('click')
    await flushPromises()

    expect(mocks.exportOnlineMrReport).toHaveBeenCalledOnce()
    expect(mocks.exportOnlineMrReport).toHaveBeenCalledWith(
      'session-1',
      expect.stringMatching(/^MR-1-分析报告-\d{8}_\d{6}\.xlsx$/),
    )
    expect(mocks.messageSuccess).toHaveBeenCalledWith('分析报告任务已提交，完成后将写入所选位置。')
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

  it('opens and deletes sessions from the history row action column', async () => {
    const openLocation = vi.fn().mockResolvedValue({ success: true })
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openOnlineMrSessionLocation: openLocation, openTaskWindow: vi.fn() },
    })
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([
      { session_id: 'session-1', device_name: 'MR-1', mr_name: 'MR-1', status: 'STOPPED', started_at: '2026-07-20 10:00:00' },
      { session_id: 'session-2', device_name: 'MR-2', mr_name: 'MR-2', status: 'STOPPED', started_at: '2026-07-20 11:00:00' },
    ])
    const wrapper = await renderView()

    await wrapper.get('[data-testid="row-open-session-location-session-2"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="row-delete-session-session-2"]').trigger('click')
    await flushPromises()

    expect(openLocation).toHaveBeenCalledWith('session-2')
    expect(mocks.deleteOnlineMrSession).toHaveBeenCalledWith('session-2')
    expect(mocks.getOnlineMrSession).toHaveBeenCalledWith('session-1', expect.any(AbortSignal))
    wrapper.unmount()
  })

  it('opens an unselected row with target-only loading and preserves the selected detail', async () => {
    const opening = deferred<{ success: boolean }>()
    const openLocation = vi.fn(() => opening.promise)
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openOnlineMrSessionLocation: openLocation, openTaskWindow: vi.fn() },
    })
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A'), sessionRow('B')])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    const wrapper = await renderView()
    mocks.getOnlineMrSession.mockClear()
    mocks.routerReplace.mockClear()

    await wrapper.get('[data-testid="row-open-session-location-B"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect(openLocation).toHaveBeenCalledWith('B')
    expect(wrapper.get('[data-testid="row-open-session-location-B"]').attributes('loading')).toBe('true')
    expect(wrapper.get('[data-testid="row-open-session-location-A"]').attributes('loading')).toBe('false')
    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(true)
    expect(mocks.getOnlineMrSession).not.toHaveBeenCalled()
    expect(mocks.routerReplace).not.toHaveBeenCalled()

    opening.resolve({ success: true })
    await flushPromises()
    expect(wrapper.get('[data-testid="row-open-session-location-B"]').attributes('loading')).toBe('false')
    wrapper.unmount()
  })

  it('reports a missing unselected row location without changing selection', async () => {
    const openLocation = vi.fn().mockResolvedValue({ success: false, availability: 'MISSING' as const, error: '该会话的本地文件已不存在。' })
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openOnlineMrSessionLocation: openLocation, openTaskWindow: vi.fn() },
    })
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A'), sessionRow('B')])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    const wrapper = await renderView()
    mocks.getOnlineMrSession.mockClear()

    await wrapper.get('[data-testid="row-open-session-location-B"]').trigger('click')
    await flushPromises()

    expect(mocks.messageWarning).toHaveBeenCalledWith('MR-B：该会话的本地文件已不存在。')
    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(true)
    expect(mocks.getOnlineMrSession).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="row-open-session-location-B"]').attributes('loading')).toBe('false')
    wrapper.unmount()
  })

  it('removes an unselected session without reloading or changing the selected detail', async () => {
    vi.useFakeTimers()
    mocks.listRecentOnlineMrSessions
      .mockResolvedValueOnce([sessionRow('A'), sessionRow('B'), sessionRow('C')])
      .mockResolvedValueOnce([sessionRow('A'), sessionRow('C')])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    mocks.getRailTransitTask.mockResolvedValue(completedDeleteTask('B'))
    const wrapper = await renderView()
    mocks.getOnlineMrSession.mockClear()
    mocks.routerReplace.mockClear()

    await wrapper.get('[data-testid="row-delete-session-B"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(mocks.deleteOnlineMrSession).toHaveBeenCalledOnce()
    expect(mocks.deleteOnlineMrSession).toHaveBeenCalledWith('B')
    expect(wrapper.find('[data-testid="table-row-B"]').exists()).toBe(false)
    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(true)
    expect(mocks.getOnlineMrSession).not.toHaveBeenCalled()
    expect(mocks.routerReplace).not.toHaveBeenCalledWith(expect.objectContaining({ query: expect.objectContaining({ session_id: 'B' }) }))
    wrapper.unmount()
  })

  it('selects the next session after deleting the current row, then falls back to the previous row', async () => {
    vi.useFakeTimers()
    mocks.listRecentOnlineMrSessions
      .mockResolvedValueOnce([sessionRow('A'), sessionRow('B'), sessionRow('C')])
      .mockResolvedValueOnce([sessionRow('A'), sessionRow('C')])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    mocks.getRailTransitTask.mockResolvedValue(completedDeleteTask('B'))
    const wrapper = await renderView()
    await wrapper.get('[data-testid="table-row-B"]').trigger('click')
    await flushPromises()
    mocks.getOnlineMrSession.mockClear()

    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(wrapper.find('[data-current-row-key="C"]').exists()).toBe(true)
    expect(mocks.getOnlineMrSession).toHaveBeenCalledWith('C', expect.any(AbortSignal))
    expect(mocks.routerReplace).toHaveBeenCalledWith(expect.objectContaining({ query: expect.objectContaining({ session_id: 'C' }) }))
    wrapper.unmount()
  })

  it('clears selection and route after deleting the final session', async () => {
    vi.useFakeTimers()
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A')]).mockResolvedValueOnce([])
    mocks.getOnlineMrSession.mockResolvedValue(sessionDetail('A'))
    mocks.getRailTransitTask.mockResolvedValue(completedDeleteTask('A'))
    const wrapper = await renderView()
    mocks.routerReplace.mockClear()

    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(wrapper.find('[description="当前局点暂无 Online MR 会话"]').exists()).toBe(true)
    expect(mocks.routerReplace).toHaveBeenCalledWith({ query: {} })
    wrapper.unmount()
  })

  it('ignores duplicate deletion clicks while confirmation is pending', async () => {
    const confirmation = deferred<boolean>()
    mocks.confirm.mockReturnValue(confirmation.promise)
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A')])
    mocks.getOnlineMrSession.mockResolvedValue(sessionDetail('A'))
    const wrapper = await renderView()

    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    expect(mocks.confirm).toHaveBeenCalledOnce()
    confirmation.resolve(false)
    await flushPromises()
    expect(mocks.deleteOnlineMrSession).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps the row and selection when deletion submission fails', async () => {
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A')])
    mocks.getOnlineMrSession.mockResolvedValue(sessionDetail('A'))
    mocks.deleteOnlineMrSession.mockRejectedValueOnce(new Error('会话资源正在使用，无法删除'))
    const wrapper = await renderView()

    await wrapper.get('[data-testid="delete-session"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="table-row-A"]').exists()).toBe(true)
    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(true)
    expect(wrapper.find('[title="会话资源正在使用，无法删除"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="delete-session"]').attributes('loading')).toBe('false')
    wrapper.unmount()
  })

  it('keeps a successful deletion local when the server refresh fails', async () => {
    vi.useFakeTimers()
    mocks.listRecentOnlineMrSessions
      .mockResolvedValueOnce([sessionRow('A'), sessionRow('B')])
      .mockRejectedValueOnce(new Error('list offline'))
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    mocks.getRailTransitTask.mockResolvedValue(completedDeleteTask('B'))
    const wrapper = await renderView()

    await wrapper.get('[data-testid="row-delete-session-B"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(wrapper.find('[data-testid="table-row-B"]').exists()).toBe(false)
    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(true)
    expect(mocks.messageWarning).toHaveBeenCalledWith('会话已删除，但会话列表刷新失败，可手动刷新。')
    expect(mocks.messageError).not.toHaveBeenCalledWith(expect.stringContaining('删除失败'))
    wrapper.unmount()
  })

  it('uses target IDs instead of page booleans for row action loading', () => {
    expect(source).toContain('const openingSessionId = ref<string | null>(null)')
    expect(source).toContain('const deletingSessionId = ref<string | null>(null)')
    expect(source).not.toMatch(/const\s+openingLocation\s*=\s*ref\(false\)/)
    expect(source).not.toMatch(/const\s+deleting\s*=\s*ref\(false\)/)
  })

  it('restores deletion loading on the task target without changing selection', async () => {
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A'), sessionRow('B')])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    mocks.recoverRailTransitTasks.mockResolvedValueOnce([{
      task_id: 'delete-B',
      action: 'online_mr_session_delete',
      status: 'RUNNING',
      result_summary: { session_id: 'B' },
    }])

    const wrapper = await renderView()

    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="row-delete-session-A"]').attributes('loading')).toBe('false')
    expect(wrapper.get('[data-testid="row-delete-session-B"]').attributes('loading')).toBe('true')
    wrapper.unmount()
  })

  it('invalidates selection and late requests before a site switch', async () => {
    const loading = deferred<ReturnType<typeof sessionDetail>>()
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('A')])
    mocks.getOnlineMrSession.mockReturnValueOnce(loading.promise)
    const wrapper = await renderView()

    window.dispatchEvent(new CustomEvent('netconsole:before-site-switch', { detail: { targetSiteId: 'site-b' } }))
    loading.resolve(sessionDetail('A'))
    await flushPromises()

    expect(wrapper.find('[data-current-row-key="A"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="table-row-A"]').exists()).toBe(false)
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

  it('keeps the selected session, active tab, and loaded tables across KeepAlive navigation', async () => {
    const active = ref(true)
    const host = mount(defineComponent({
      setup: () => () => h(KeepAlive, null, {
        default: () => active.value ? h(OnlineMrAnalysisView) : h('div', 'FIT-AP'),
      }),
    }), { global: { plugins: [createPinia()], stubs, directives: { loading: () => undefined } } })
    await flushPromises()
    await host.get('[data-testid="main-link-tab"]').trigger('click')
    await flushPromises()
    await host.get('[data-testid="link-detail-tab"]').trigger('click')
    await flushPromises()
    const sessionCalls = mocks.getOnlineMrSession.mock.calls.length
    const tableCalls = mocks.queryOnlineMrBusinessTable.mock.calls.length

    active.value = false
    await nextTick()
    active.value = true
    await nextTick()
    await flushPromises()

    expect(mocks.getOnlineMrSession).toHaveBeenCalledTimes(sessionCalls)
    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledTimes(tableCalls)
    expect(host.find('[data-tabs-model="mesh-detail"]').exists()).toBe(true)
    host.unmount()
  })

  it('restores a cached tab and empty business result after a real unmount without refetching', async () => {
    const pinia = createPinia()
    let wrapper = await renderView(pinia)
    await wrapper.get('[data-testid="link-detail-tab"]').trigger('click')
    await flushPromises()
    const listCalls = mocks.listRecentOnlineMrSessions.mock.calls.length
    const detailCalls = mocks.getOnlineMrSession.mock.calls.length
    const tableCalls = mocks.queryOnlineMrBusinessTable.mock.calls.length
    wrapper.unmount()

    wrapper = await renderView(pinia)

    expect(wrapper.find('[data-tabs-model="mesh-detail"]').exists()).toBe(true)
    expect(mocks.listRecentOnlineMrSessions).toHaveBeenCalledTimes(listCalls)
    expect(mocks.getOnlineMrSession).toHaveBeenCalledTimes(detailCalls)
    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledTimes(tableCalls)
    wrapper.unmount()
  })

  it('invalidates and reloads the selected session only on manual refresh', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="main-link-tab"]').trigger('click')
    await flushPromises()
    expect(mocks.listRecentOnlineMrSessions).toHaveBeenCalledOnce()
    expect(mocks.getOnlineMrSession).toHaveBeenCalledOnce()
    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledOnce()

    await wrapper.get('[data-testid="refresh-session"]').trigger('click')
    await flushPromises()

    expect(mocks.listRecentOnlineMrSessions).toHaveBeenCalledTimes(2)
    expect(mocks.getOnlineMrSession).toHaveBeenCalledTimes(2)
    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-tabs-model="mesh-link"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('clears cached analysis before reparsing and reloads it after immediate completion', async () => {
    const wrapper = await renderView()
    await wrapper.get('[data-testid="main-link-tab"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="parse-session"]').trigger('click')
    await flushPromises()

    expect(mocks.parseOnlineMrSession).toHaveBeenCalledWith('session-1', false)
    expect(mocks.getOnlineMrSession).toHaveBeenCalledTimes(2)
    expect(mocks.queryOnlineMrBusinessTable).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('restores the unified RSSI timeline and DataZoom from the session cache after remount', async () => {
    mocks.queryOnlineMrTimelineMetrics.mockResolvedValueOnce(timelineRssiSeries('AP-A', [-51, -52]))
    const viewport = {
      start_time: '2026-07-21 16:00:10', end_time: '2026-07-21 16:00:50',
      start_percent: 20, end_percent: 60,
      full_start_time: '2026-07-21 16:00:00', full_end_time: '2026-07-21 16:01:00',
      source: 'user_zoom' as const,
    }
    const pinia = createPinia()
    let wrapper = await renderView(pinia)
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    expect(mocks.queryOnlineMrTimelineMetrics).toHaveBeenCalledOnce()
    expect(mocks.queryOnlineMrTimelineMetrics).toHaveBeenCalledWith(
      'session-1',
      expect.arrayContaining(['rssi', 'trackside_rssi', 'ping_loss', 'iperf_bitrate']),
      expect.objectContaining({ limit: 10_000, downsample: 'MIN_MAX' }),
    )
    expect(wrapper.text()).toContain('-51')
    expect(wrapper.text()).toContain('-52')
    const rssiChart = wrapper.findComponent(rssiChartStub)
    expect(rssiChart.props('mainSeries')).toHaveLength(1)
    expect((rssiChart.props('mainSeries') as Array<{ points: unknown[] }>)[0].points).toHaveLength(2)
    expect(rssiChart.props('tracksideSeries')).toHaveLength(1)
    await rssiChart.vm.$emit('update:viewport', viewport)
    const timelineCalls = mocks.queryOnlineMrTimelineMetrics.mock.calls.length
    const detailCalls = mocks.getOnlineMrSession.mock.calls.length
    wrapper.unmount()

    wrapper = await renderView(pinia)

    const restored = wrapper.findComponent(rssiChartStub)
    expect(wrapper.find('[data-tabs-model="charts"]').exists()).toBe(true)
    expect((restored.props('mainSeries') as Array<{ points: unknown[] }>)[0].points).toHaveLength(2)
    expect(restored.props('viewport')).toEqual(viewport)
    expect(mocks.queryOnlineMrTimelineMetrics).toHaveBeenCalledTimes(timelineCalls)
    expect(mocks.getOnlineMrSession).toHaveBeenCalledTimes(detailCalls)
    wrapper.unmount()
  })

  it('keeps the newest target-point request when older timeline data resolves last', async () => {
    mocks.queryOnlineMrTimelineMetrics.mockResolvedValueOnce(timelineRssiSeries('initial', [-60]))
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()

    const older = deferred<ReturnType<typeof timelineRssiSeries>>()
    const newer = deferred<ReturnType<typeof timelineRssiSeries>>()
    mocks.queryOnlineMrTimelineMetrics
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)

    const pointSelect = wrapper.findAllComponents(selectStub).find((item) => item.props('modelValue') === 600)!
    await pointSelect.vm.$emit('update:modelValue', 300)
    await pointSelect.vm.$emit('change', 300)
    await nextTick()
    const updatedPointSelect = wrapper.findAllComponents(selectStub).find((item) => item.props('modelValue') === 300)!
    await updatedPointSelect.vm.$emit('update:modelValue', 1200)
    await updatedPointSelect.vm.$emit('change', 1200)
    await nextTick()

    newer.resolve(timelineRssiSeries('newest', [-42]))
    await flushPromises()
    older.resolve(timelineRssiSeries('older', [-81]))
    await flushPromises()

    expect(wrapper.text()).toContain('-42')
    expect(wrapper.text()).not.toContain('-81')
    expect(mocks.queryOnlineMrTimelineMetrics).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('excludes switch-history snapshots outside the unified Session time domain', async () => {
    mocks.queryOnlineMrTimelineMetrics.mockResolvedValueOnce(timelineRssiSeries('AP-A', [-51, -52]))
    mocks.queryOnlineMrSwitchRssiWindows.mockImplementation(async (_sessionId: string, source: string) => ({
      items: source === 'history'
        ? [{ source: 'history', event_id: 'history-old', event_time: '2026-07-21 11:36:06' }]
        : [
            { source: 'realtime', event_id: 'realtime-before-range', event_time: '2026-07-21 16:00:00' },
            { source: 'realtime', event_id: 'realtime-current', event_time: '2026-07-21 16:00:30' },
          ],
      limit: 200,
      offset: 0,
      has_more: false,
    }))
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()

    const chart = wrapper.findComponent(rssiChartStub)
    expect(chart.props('historyEvents')).toEqual([])
    expect(chart.props('realtimeEvents')).toEqual([
      expect.objectContaining({ event_id: 'realtime-before-range' }),
      expect.objectContaining({ event_id: 'realtime-current' }),
    ])
    await chart.vm.$emit('update:viewport', {
      start_time: '2026-07-21 16:00:10', end_time: '2026-07-21 16:00:50',
      start_percent: 20, end_percent: 80,
      full_start_time: '2026-07-21 16:00:00', full_end_time: '2026-07-21 16:01:00',
      source: 'user_zoom',
    })
    await wrapper.get('[data-testid="next-timeline-switch"]').trigger('click')
    expect(chart.props('selectedTime')).toBe('2026-07-21 16:00:30')
    wrapper.unmount()
  })

  it('keeps A and B table caches isolated and restores A without refetching', async () => {
    mocks.listRecentOnlineMrSessions.mockResolvedValueOnce([sessionRow('session-1'), sessionRow('session-2')])
    mocks.getOnlineMrSession.mockImplementation(async (sessionId: string) => sessionDetail(sessionId))
    mocks.queryOnlineMrTimelineMetrics.mockImplementation(async (sessionId: string) => timelineRssiSeries(
      sessionId,
      [sessionId === 'session-1' ? -51 : -71],
    ))
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="session-b"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-tabs-model="session-history"]').exists()).toBe(true)
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="table-row-session-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-tabs-model="charts"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('-51')
    expect(wrapper.text()).not.toContain('-71')
    expect(mocks.queryOnlineMrTimelineMetrics).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('loads source-specific switch snapshots once and treats empty pages as cached', async () => {
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout')
    mocks.recoverRailTransitTasks.mockResolvedValueOnce([{ task_id: 'report-1', action: 'online_mr_report', status: 'RUNNING' }])
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    expect(mocks.queryOnlineMrSwitchRssiWindows).toHaveBeenCalledWith('session-1', 'history', expect.objectContaining({ limit: 200, offset: 0 }))
    expect(mocks.queryOnlineMrSwitchRssiWindows).toHaveBeenCalledWith('session-1', 'realtime', expect.objectContaining({ limit: 200, offset: 0 }))
    mocks.queryOnlineMrMetrics.mockClear()
    mocks.queryOnlineMrSwitchRssiWindows.mockClear()
    await wrapper.get('[data-testid="switch-history-chart"]').trigger('click')
    await wrapper.get('[data-testid="switch-realtime-chart"]').trigger('click')
    await flushPromises()

    expect(mocks.queryOnlineMrSwitchRssiWindows).not.toHaveBeenCalled()
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
    mocks.queryOnlineMrTimelineMetrics.mockResolvedValueOnce(timelineRssiSeries('AP-A', [-61]))
    const wrapper = await renderView()
    await wrapper.get('[data-testid="charts-tab"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('-61')

    await wrapper.get('[data-testid="session-b"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('-61')
    expect(wrapper.get('.parser-status-tag').attributes('title')).toContain('当前会话尚未生成解析数据库')
    expect(wrapper.text()).toContain('解析当前会话')
    expect(mocks.queryOnlineMrMetrics).not.toHaveBeenCalledWith('session-1', ['rssi'], expect.anything())
    await wrapper.get('[data-testid="parse-session"]').trigger('click')
    await flushPromises()
    expect(mocks.parseOnlineMrSession).toHaveBeenCalledWith('session-2', false)
    wrapper.unmount()
  })
})
