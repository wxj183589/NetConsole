// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MeshPhase11Workbench from './MeshPhase11Workbench.vue'

const api = vi.hoisted(() => ({ summary: vi.fn(), aps: vi.fn(), links: vi.fn(), issues: vi.fn(), builds: vi.fn() }))
vi.mock('../../api/meshAnalysis', () => ({ getMeshBusinessSummary: api.summary, listMeshApSignalStatistics: api.aps, listMeshLinks: api.links, listMeshParseIssues: api.issues, listMeshActiveBuildOrder: api.builds }))
vi.mock('./MeshMetricChart.vue', () => ({ default: defineComponent({ name: 'MeshMetricChart', props: ['lines', 'unit', 'domain', 'window', 'pointer', 'selectedTime', 'navigator'], emits: ['viewport-change', 'pointer-change', 'sample-select', 'render-complete', 'render-error'], setup: () => () => h('div', { class: 'metric-chart' }) }) }))

const metricKeys = ['rssi', 'cpu', 'memory', 'busy', 'rate', 'noise', 'tx_des_free_cnt', 'counters']
const session = { session_id: 'mesh-1', train_name: '列车01', mr_name: '列车01-MR-CT', first_sample_time: '2026-11-09 10:00:00.000', last_sample_time: '2026-11-09 10:30:00.000', raw_log_count: 10, link_record_count: 8, active_link_count: 4, standby_link_count: 4, error_count: 1, warning_count: 2, analysis_status: 'done', parsed_status: 'ready', data_integrity: 'complete' } as any
const sample = { timestamp: '2026-11-09 10:27:00.000', link_role: 'ACTIVE', peer_ap_name: 'AP-1', peer_ap_mac: 'aa:bb:cc:dd:ee:01', peer_mac: 'aa:bb:cc:dd:ff:01', local_radio: 1, peer_radio: 'Radio 2', link_count: 1, local_rssi_db: -45, peer_rssi_db: -50, local_cpu_percent: 23, peer_cpu_percent: 32, local_mem_percent: 45, peer_mem_percent: 54, local_rate_raw: '120', peer_rate_raw: '100', local_err_delta: 3, peer_err_delta: 4 }
const standby = { ...sample, timestamp: '2026-11-09 10:28:00.000', peer_ap_name: 'AP-STANDBY', link_role: 'STANDBY' }
const zero = { ...sample, timestamp: '2026-11-09 10:29:00.000', peer_ap_name: '', link_count: 0, link_role: '' }
const table = defineComponent({ name: 'NcDataTable', props: ['data', 'columns', 'tableId', 'loading'], emits: ['row-click'], setup: (props, { emit }) => () => h('div', { class: 'table', 'data-table-id': props.tableId }, (props.data || []).map((row: any, index: number) => h('button', { 'data-row': index, onClick: () => emit('row-click', row) }, (row.peer_ap_name || '未连接') + ' ' + (row.link_role || '')))) })
const model = (name: string) => defineComponent({ name, props: ['modelValue'], emits: ['update:modelValue', 'change'], setup: (props, { slots }) => () => h('div', { class: name, 'data-value': String(props.modelValue ?? '') }, slots.default?.()) })
const stubs = { NcDataTable: table, ElCheckbox: model('ElCheckbox'), ElInput: model('ElInput'), ElSelect: model('ElSelect'), ElOption: true, ElPagination: true, ElButton: defineComponent({ setup: (_, { slots }) => () => h('button', slots.default?.()) }), ElSkeleton: defineComponent({ setup: () => () => h('div', { class: 'skeleton' }) }), ElEmpty: defineComponent({ props: ['description'], setup: props => () => h('div', props.description) }), ElAlert: defineComponent({ props: ['title'], setup: props => () => h('div', props.title) }) }
let wrappers: VueWrapper[] = []
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function mounted() { const wrapper = mount(MeshPhase11Workbench, { props: { sessionId: session.session_id, session }, global: { stubs } }); wrappers.push(wrapper); return wrapper }
async function nav(wrapper: VueWrapper, index: number) { await wrapper.findAll('.phase11-nav button')[index]!.trigger('click'); await flushPromises() }
function charts(wrapper: VueWrapper) { return wrapper.findAllComponents({ name: 'MeshMetricChart' }) }
function metrics() { return api.links.mock.calls.filter(([, query]) => query.metric_group) }
async function control(wrapper: VueWrapper, name: string, index: number, value: unknown) { const component = wrapper.findAllComponents({ name })[index]!; component.vm.$emit('update:modelValue', value); component.vm.$emit('change', value); await flushPromises() }
async function context(wrapper: VueWrapper, value: Record<string, unknown>) { const result = (wrapper.vm as any).openContext(value); await flushPromises(); await result; await flushPromises() }
const range = (minute: string) => ({ start: '2026-11-09 10:' + minute + ':00.000', end: '2026-11-09 10:' + (Number(minute) + 1) + ':00.000' })
beforeEach(() => {
  vi.useRealTimers(); vi.resetAllMocks(); wrappers = []
  api.summary.mockResolvedValue({ ap_total: 2, grades: { GOOD: 1, WARNING: 1 }, single_link_count: 1, single_link_ap_count: 1 })
  api.aps.mockResolvedValue({ items: [{ peer_ap_name: 'AP-1', peer_ap_mac: sample.peer_ap_mac }], total: 1 })
  api.links.mockImplementation(async (_id, query) => ({ items: query.metric_group ? [sample] : [sample, standby, zero], total: query.metric_group ? 1 : 3, zero_link_count: 1 }))
  api.issues.mockResolvedValue({ items: [{ code: 'MISSING_SAMPLE', message: '采样缺失' }], total: 1 })
  api.builds.mockResolvedValue({ items: [], total: 0 })
  HTMLElement.prototype.scrollIntoView = vi.fn()
})
afterEach(() => { wrappers.forEach(wrapper => wrapper.unmount()); vi.useRealTimers() })

describe('Mesh Phase 11 workbench business behavior', () => {
  it('opens four independent entries lazily and confines six cards to overview', async () => {
    const wrapper = mounted(); await flushPromises()
    expect(wrapper.findAll('.phase11-nav button').map(button => button.text())).toEqual(['分析概览', '日志解析', 'AP 情况', '主链路监控'])
    expect(wrapper.findAll('.phase11-cards button')).toHaveLength(6)
    expect(api.summary).toHaveBeenCalledOnce(); expect(api.aps).not.toHaveBeenCalled(); expect(api.links).not.toHaveBeenCalled(); expect(api.issues).not.toHaveBeenCalled(); expect(api.builds).not.toHaveBeenCalled()
    await nav(wrapper, 1); expect(api.issues).toHaveBeenCalledOnce(); expect(api.links).not.toHaveBeenCalled(); expect(wrapper.find('.phase11-cards').exists()).toBe(false)
    await nav(wrapper, 2); expect(api.aps).toHaveBeenCalledOnce(); expect(api.links).not.toHaveBeenCalled(); expect(wrapper.find('.phase11-cards').exists()).toBe(false)
    await nav(wrapper, 3); expect(metrics().map(([, query]) => query.metric_group)).toEqual(metricKeys); expect(api.links).toHaveBeenCalledTimes(9); expect(api.builds).toHaveBeenCalledOnce(); expect(wrapper.find('.phase11-cards').exists()).toBe(false)
    await nav(wrapper, 0); expect(wrapper.findAll('.phase11-cards button')).toHaveLength(6); expect(api.summary).toHaveBeenCalledOnce()
  })

  it('uses the latest five minutes and binds eight metric groups to one domain and window', async () => {
    const wrapper = mounted(); await nav(wrapper, 3)
    expect(charts(wrapper)).toHaveLength(8)
    charts(wrapper).forEach((chart, index) => {
      expect(chart.props('domain')).toEqual({ start: session.first_sample_time, end: session.last_sample_time })
      expect(chart.props('window')).toEqual({ start: '2026-11-09 10:25:00.000', end: session.last_sample_time })
      expect(chart.props('lines')).toHaveLength(index === 3 ? 4 : index === 7 ? 12 : 2)
    })
    expect(charts(wrapper).map(chart => chart.props('navigator'))).toEqual([false, false, false, false, false, false, false, true])
    for (const [, query] of metrics()) expect(query).toMatchObject({ time_from: '2026-11-09 10:25:00.000', time_to: session.last_sample_time, radio: 1, link_role: 'ACTIVE', exact_ap: true, max_points: 1000, page_size: 1000 })
    expect(wrapper.text()).toContain('0/8 图表完成')
    charts(wrapper)[0]!.vm.$emit('render-complete'); await flushPromises(); expect(wrapper.text()).toContain('1/8 图表完成')
  })

  it('throttles repeated zoom to 180ms and queries every section for the final window', async () => {
    const wrapper = mounted(); await nav(wrapper, 3); vi.useFakeTimers()
    const first = range('20'), final = range('22')
    charts(wrapper)[0]!.vm.$emit('viewport-change', first); await flushPromises()
    await vi.advanceTimersByTimeAsync(100)
    charts(wrapper)[1]!.vm.$emit('viewport-change', final); await flushPromises()
    expect(charts(wrapper).every(chart => JSON.stringify(chart.props('window')) === JSON.stringify(final))).toBe(true)
    await vi.advanceTimersByTimeAsync(179); expect(api.links).toHaveBeenCalledTimes(9)
    await vi.advanceTimersByTimeAsync(1); await flushPromises()
    expect(api.links).toHaveBeenCalledTimes(18); expect(api.builds).toHaveBeenCalledTimes(2)
    expect(api.links.mock.calls.slice(9).every(([, query]) => query.time_from === final.start && query.time_to === final.end)).toBe(true)
    expect(charts(wrapper).every(chart => JSON.stringify(chart.props('window')) === JSON.stringify(final))).toBe(true)
  })

  it('shares pointer movement without querying and selects chart samples into right detail', async () => {
    const wrapper = mounted(); await nav(wrapper, 3)
    charts(wrapper)[2]!.vm.$emit('pointer-change', standby.timestamp); await flushPromises()
    expect(charts(wrapper).every(chart => chart.props('pointer') === standby.timestamp)).toBe(true)
    expect(api.links).toHaveBeenCalledTimes(9)
    charts(wrapper)[2]!.vm.$emit('sample-select', standby); await flushPromises()
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-STANDBY'); expect(wrapper.find('.phase11-detail').text()).toContain('STANDBY')
    expect(charts(wrapper).every(chart => chart.props('selectedTime') === standby.timestamp)).toBe(true)
    charts(wrapper)[0]!.vm.$emit('pointer-change', null); await flushPromises(); expect(charts(wrapper).every(chart => chart.props('pointer') === null)).toBe(true)
  })

  it('shows historical roles on history selection including an unconnected sample', async () => {
    const wrapper = mounted(); await nav(wrapper, 3)
    const history = wrapper.find('[data-table-id="mesh-phase11-history:v1"]')
    await history.findAll('button')[1]!.trigger('click'); expect(wrapper.find('.phase11-detail').text()).toContain('STANDBY')
    await history.findAll('button')[2]!.trigger('click'); expect(wrapper.find('.phase11-detail').text()).toContain('未连接（LinkCnt=0）')
    expect(wrapper.find('.phase11-history summary').text()).toContain('未连接 1 条')
    expect(api.links).toHaveBeenCalledTimes(9)
  })

  it('applies exact AP, Radio, historical role and zero-link filters to all requests', async () => {
    const wrapper = mounted(); await nav(wrapper, 3)
    await control(wrapper, 'ElInput', 0, sample.peer_ap_mac)
    await control(wrapper, 'ElSelect', 0, 2)
    await control(wrapper, 'ElSelect', 1, 'STANDBY')
    await control(wrapper, 'ElCheckbox', 2, true)
    const expected = { peer_ap_mac: sample.peer_ap_mac, exact_ap: true, radio: 2, link_role: 'STANDBY', include_zero: true, exclude_depot: true, exclude_parking: true }
    for (const [, query] of api.links.mock.calls.slice(-9)) expect(query).toMatchObject(expected)
    expect(api.builds.mock.calls.at(-1)?.[1]).toMatchObject(expected)
    expect(api.links).toHaveBeenCalledTimes(45)
  })

  it('opens an AP using its exact physical MAC and all historical roles', async () => {
    const wrapper = mounted(); await nav(wrapper, 2)
    await wrapper.find('[data-table-id="mesh-phase11-aps:v2"] button').trigger('click'); await flushPromises()
    expect(wrapper.find('.phase11-monitor').exists()).toBe(true)
    for (const [, query] of api.links.mock.calls) expect(query).toMatchObject({ peer_ap_mac: sample.peer_ap_mac, exact_ap: true, link_role: '' })
  })

  it('ignores stale filter responses and aborts the previous request generation', async () => {
    const old = deferred<any>(); api.links.mockImplementation(() => old.promise)
    const wrapper = mounted(); await nav(wrapper, 3)
    const oldSignals = api.links.mock.calls.map(call => call[2] as AbortSignal)
    api.links.mockResolvedValue({ items: [{ ...sample, peer_ap_name: 'AP-NEW' }], total: 1 })
    await control(wrapper, 'ElInput', 0, 'new-mac')
    expect(oldSignals.every(signal => signal.aborted)).toBe(true)
    old.resolve({ items: [{ ...sample, peer_ap_name: 'AP-STALE' }], total: 1 }); await flushPromises()
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-NEW'); expect(wrapper.text()).not.toContain('AP-STALE')
    expect(charts(wrapper)).toHaveLength(8)
  })

  it('aborts requests and pending zoom when the page closes', async () => {
    const pending = deferred<any>(); api.links.mockImplementation(() => pending.promise)
    const wrapper = mounted(); await nav(wrapper, 3)
    const signals = [...api.links.mock.calls.map(call => call[2] as AbortSignal), api.builds.mock.calls[0]![2] as AbortSignal]
    wrapper.unmount(); expect(signals.every(signal => signal.aborted)).toBe(true)
    pending.resolve({ items: [sample], total: 1 }); await flushPromises(); expect(api.links).toHaveBeenCalledTimes(9)
    const second = mounted(); api.links.mockResolvedValue({ items: [sample], total: 1 }); await nav(second, 3); vi.useFakeTimers()
    charts(second)[0]!.vm.$emit('viewport-change', range('20')); second.unmount(); const calls = api.links.mock.calls.length
    await vi.advanceTimersByTimeAsync(200); expect(api.links).toHaveBeenCalledTimes(calls)
  })

  it('isolates a failed metric query and retries only that metric', async () => {
    api.links.mockImplementation(async (_id, query) => { if (query.metric_group === 'cpu') throw new Error('CPU 查询失败'); return { items: [sample], total: 1 } })
    const wrapper = mounted(); await nav(wrapper, 3)
    expect(charts(wrapper)).toHaveLength(7); expect(wrapper.find('#monitor-cpu .phase-error').text()).toContain('CPU 查询失败')
    charts(wrapper)[0]!.vm.$emit('render-complete'); await flushPromises(); expect(wrapper.find('#monitor-rssi .phase-completed').exists()).toBe(true)
    api.links.mockResolvedValue({ items: [sample], total: 1 })
    await wrapper.find('#monitor-cpu button').trigger('click'); await flushPromises()
    expect(api.links).toHaveBeenCalledTimes(10); expect(api.links.mock.calls.at(-1)?.[1].metric_group).toBe('cpu'); expect(charts(wrapper)).toHaveLength(8)
    expect(wrapper.find('#monitor-cpu .phase-rendering').exists()).toBe(true)
  })

  it('isolates rendering errors and completes empty results without infinite loading', async () => {
    api.links.mockResolvedValue({ items: [], total: 0 })
    const wrapper = mounted(); await nav(wrapper, 3)
    expect(charts(wrapper)).toHaveLength(8); expect(wrapper.find('#monitor-rssi .phase-rendering').text()).toContain('空数据')
    charts(wrapper)[0]!.vm.$emit('render-error', 'RSSI 绘图失败'); charts(wrapper)[1]!.vm.$emit('render-complete'); await flushPromises()
    expect(wrapper.find('#monitor-rssi .phase-error').text()).toContain('RSSI 绘图失败'); expect(wrapper.find('#monitor-cpu .phase-completed').exists()).toBe(true)
    expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
  })

  it('reuses cache immediately and keeps background refresh querying after old finished events', async () => {
    const wrapper = mounted(); await nav(wrapper, 3); await nav(wrapper, 0)
    const pending = deferred<any>(); api.links.mockImplementation(() => pending.promise)
    await nav(wrapper, 3)
    expect(charts(wrapper)).toHaveLength(8); expect(wrapper.find('#monitor-rssi .phase-querying').text()).toContain('缓存命中')
    charts(wrapper).forEach(chart => chart.vm.$emit('render-complete')); await flushPromises()
    expect(wrapper.find('#monitor-rssi .phase-querying').exists()).toBe(true); expect(wrapper.text()).toContain('0/8 图表完成')
    pending.resolve({ items: [{ ...sample, local_rssi_db: -65 }], total: 1 }); await flushPromises()
    expect(wrapper.find('#monitor-rssi .phase-rendering').exists()).toBe(true)
    expect(charts(wrapper)[0]!.props('lines')[0].data[0].value[1]).toBe(-65)
    charts(wrapper)[0]!.vm.$emit('render-complete'); await flushPromises(); expect(wrapper.find('#monitor-rssi .phase-completed').exists()).toBe(true)
  })

  it('opens exact AP, Radio, window and focus without querying outside that context', async () => {
    const wrapper = mounted(); await flushPromises()
    const value = { ap: sample.peer_ap_mac, radio: 2, start: '2026-11-09 10:26:00.000', end: '2026-11-09 10:29:00.000', focus: standby.timestamp }
    api.links.mockImplementation(async (_id, query) => ({ items: query.page_size === 1 ? [standby] : [], total: query.page_size === 1 ? 1 : 0 }))
    await context(wrapper, value)
    expect(api.links).toHaveBeenCalledTimes(10)
    for (const [, query] of api.links.mock.calls) expect(query).toMatchObject({ peer_ap_mac: value.ap, exact_ap: true, radio: 2, link_role: 'ACTIVE', include_zero: false })
    expect(api.links.mock.calls.find(([, query]) => query.page_size === 1)?.[1]).toMatchObject({ time_from: value.focus, time_to: value.focus })
    for (const [, query] of api.links.mock.calls.filter(([, query]) => query.page_size !== 1)) expect(query).toMatchObject({ time_from: value.start, time_to: value.end })
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-STANDBY'); expect(charts(wrapper).every(chart => chart.props('selectedTime') === value.focus)).toBe(true)
  })

  it('does not broaden an empty focus query into a cross-window fallback', async () => {
    const wrapper = mounted(); api.links.mockResolvedValue({ items: [], total: 0 })
    await context(wrapper, { ap: sample.peer_ap_mac, radio: 2, ...range('20'), focus: '2026-11-09 10:20:30.000' })
    expect(api.links).toHaveBeenCalledTimes(10); expect(api.links.mock.calls.filter(([, query]) => query.page_size === 1)).toHaveLength(1)
    expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
  })

  it('evicts older windows after the sixteen-entry metric cache budget', async () => {
    const wrapper = mounted(); await flushPromises()
    await context(wrapper, range('20')); await context(wrapper, range('22')); await context(wrapper, range('24'))
    const pending = deferred<any>(); api.links.mockImplementation(() => pending.promise)
    await context(wrapper, range('22'))
    expect(charts(wrapper)).toHaveLength(8); expect(wrapper.find('#monitor-rssi [role="status"]').text()).toContain('缓存命中')
    await context(wrapper, range('20'))
    expect(charts(wrapper)).toHaveLength(0); expect(wrapper.find('#monitor-rssi [role="status"]').text()).not.toContain('缓存命中')
    pending.resolve({ items: [], total: 0 }); await flushPromises()
  })
})
