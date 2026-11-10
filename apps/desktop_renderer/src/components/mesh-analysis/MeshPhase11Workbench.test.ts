// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MeshPhase11Workbench from './MeshPhase11Workbench.vue'
import { meshQueryTrace } from './meshQueryTrace'

const api = vi.hoisted(() => ({ summary: vi.fn(), aps: vi.fn(), links: vi.fn(), issues: vi.fn(), builds: vi.fn() }))
vi.mock('../../api/meshAnalysis', () => ({ getMeshBusinessSummary: api.summary, listMeshApSignalStatistics: api.aps, listMeshLinks: api.links, listMeshParseIssues: api.issues, listMeshActiveBuildOrder: api.builds }))
vi.mock('./MeshMetricChart.vue', () => ({ default: defineComponent({ name: 'MeshMetricChart', props: ['lines', 'unit', 'domain', 'window', 'pointer', 'selectedTime', 'selectedSample', 'selectionActive', 'navigator'], emits: ['viewport-change', 'pointer-change', 'sample-select', 'time-select', 'selection-clear', 'render-complete', 'render-error'], setup: () => () => h('div', { class: 'metric-chart' }) }) }))

const metricKeys = ['rssi', 'cpu', 'memory', 'busy', 'rate', 'noise', 'tx_des_free_cnt', 'counters']
const session = { session_id: 'mesh-1', train_name: '列车01', mr_name: '列车01-MR-CT', first_sample_time: '2026-11-09 10:00:00.000', last_sample_time: '2026-11-09 10:30:00.000', raw_log_count: 10, link_record_count: 8, active_link_count: 4, standby_link_count: 4, error_count: 1, warning_count: 2, analysis_status: 'done', parsed_status: 'ready', data_integrity: 'complete' } as any
const sample = { timestamp: '2026-11-09 10:27:00.000', link_role: 'ACTIVE', peer_ap_name: 'AP-1', peer_ap_mac: 'aa:bb:cc:dd:ee:01', peer_mac: 'aa:bb:cc:dd:ff:01', local_radio: 1, peer_radio: 'Radio 2', link_count: 1, local_rssi_db: -45, peer_rssi_db: -50, local_cpu_percent: 23, peer_cpu_percent: 32, local_mem_percent: 45, peer_mem_percent: 54, local_rate_raw: '120', peer_rate_raw: '100', local_err_delta: 3, peer_err_delta: 4 }
const standby = { ...sample, timestamp: '2026-11-09 10:28:00.000', peer_ap_name: 'AP-STANDBY', link_role: 'STANDBY' }
const zero = { ...sample, timestamp: '2026-11-09 10:29:00.000', peer_ap_name: '', link_count: 0, link_role: '' }
const table = defineComponent({ name: 'NcDataTable', props: ['data', 'columns', 'tableId', 'loading'], emits: ['row-click'], setup: (props, { emit }) => () => h('div', { class: 'table', 'data-table-id': props.tableId }, (props.data || []).map((row: any, index: number) => h('button', { 'data-row': index, onClick: () => emit('row-click', row) }, (row.peer_ap_name || '未连接') + ' ' + (row.link_role || '')))) })
const model = (name: string) => defineComponent({ name, props: ['modelValue'], emits: ['update:modelValue', 'change'], setup: (props, { slots }) => () => h('div', { class: name, 'data-value': String(props.modelValue ?? '') }, slots.default?.()) })
const stubs = { NcDataTable: table, ElCheckbox: model('ElCheckbox'), ElInput: model('ElInput'), ElSelect: model('ElSelect'), ElOption: true, ElPagination: true, ElButton: defineComponent({ setup: (_, { slots }) => () => h('button', slots.default?.()) }), ElSkeleton: defineComponent({ setup: () => () => h('div', { class: 'skeleton' }) }), ElEmpty: defineComponent({ props: ['description'], setup: props => () => h('div', props.description) }), ElAlert: defineComponent({ props: ['title'], setup: props => () => h('div', props.title) }) }
let wrappers: VueWrapper[] = []
let autoVisible = true
let observers: Array<{ callback: IntersectionObserverCallback; observed: Set<Element>; disconnect: ReturnType<typeof vi.fn>; options?: IntersectionObserverInit }> = []
function intersect(keys: string[], isIntersecting = true) {
  const observer = observers.at(-1)!
  const entries = [...observer.observed].filter(element => keys.includes((element as HTMLElement).dataset.metric!)).map(target => ({ target, isIntersecting } as IntersectionObserverEntry))
  expect(entries).toHaveLength(keys.length)
  observer.callback(entries, observer as unknown as IntersectionObserver)
}
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function mounted() { const wrapper = mount(MeshPhase11Workbench, { props: { sessionId: session.session_id, session }, global: { stubs } }); wrappers.push(wrapper); return wrapper }
async function nav(wrapper: VueWrapper, index: number) { await wrapper.findAll('.phase11-nav button')[index]!.trigger('click'); await flushPromises() }
function charts(wrapper: VueWrapper) { return wrapper.findAllComponents({ name: 'MeshMetricChart' }) }
function metrics() { return api.links.mock.calls.filter(([, query]) => query.metric_group) }
function timeQueries() { return api.links.mock.calls.filter(([, query]) => query.nearest_time) }
async function control(wrapper: VueWrapper, name: string, index: number, value: unknown) { const component = wrapper.findAllComponents({ name })[index]!; component.vm.$emit('update:modelValue', value); component.vm.$emit('change', value); await flushPromises() }
async function context(wrapper: VueWrapper, value: Record<string, unknown>) { const result = (wrapper.vm as any).openContext(value); await flushPromises(); await result; await flushPromises() }
const range = (minute: string) => ({ start: '2026-11-09 10:' + minute + ':00.000', end: '2026-11-09 10:' + (Number(minute) + 1) + ':00.000' })
beforeEach(() => {
  vi.useRealTimers(); vi.resetAllMocks(); wrappers = []
  autoVisible = true; observers = []
  // happy-dom's built-in observer never reports intersections. Routine scenarios
  // explicitly expose all panels; the controlled test below models real scrolling.
  vi.stubGlobal('IntersectionObserver', class {
    observed = new Set<Element>()
    disconnect = vi.fn(() => this.observed.clear())
    constructor(public callback: IntersectionObserverCallback, public options?: IntersectionObserverInit) { observers.push(this) }
    observe(element: Element) { this.observed.add(element); if (autoVisible) void Promise.resolve().then(() => { if (this.observed.has(element)) this.callback([{ target: element, isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver) }) }
    unobserve(element: Element) { this.observed.delete(element) }
  })
  api.summary.mockResolvedValue({ ap_total: 2, grades: { GOOD: 1, WARNING: 1 }, single_link_count: 1, single_link_ap_count: 1 })
  api.aps.mockResolvedValue({ items: [{ peer_ap_name: 'AP-1', peer_ap_mac: sample.peer_ap_mac }], total: 1 })
  api.links.mockImplementation(async (_id, query) => ({ items: query.metric_group ? [sample] : [sample, standby, zero], total: query.metric_group ? 1 : 3, zero_link_count: 1 }))
  api.issues.mockResolvedValue({ items: [{ code: 'MISSING_SAMPLE', message: '采样缺失' }], total: 1 })
  api.builds.mockResolvedValue({ items: [], total: 0 })
  HTMLElement.prototype.scrollIntoView = vi.fn()
})
afterEach(() => { wrappers.forEach(wrapper => wrapper.unmount()); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('Mesh Phase 11 workbench business behavior', () => {
  it('queries only visible panels and coalesces four counter panels into one pending request', async () => {
    autoVisible = false
    const counter = deferred<any>()
    api.links.mockImplementation(async (_id, query) => query.metric_group === 'counters' ? counter.promise : { items: [sample], total: 1 })
    const wrapper = mounted(); await nav(wrapper, 4)
    expect(api.links).toHaveBeenCalledOnce()
    expect(api.links.mock.calls[0]![1].metric_group).toBeUndefined()
    expect(api.builds).toHaveBeenCalledOnce()
    expect(metrics()).toHaveLength(0); expect(charts(wrapper)).toHaveLength(0)
    expect(observers.at(-1)!.options).toEqual({ rootMargin: '240px' })
    intersect(['rssi']); await flushPromises()
    expect(metrics().map(([, query]) => query.metric_group)).toEqual(['rssi'])
    expect(charts(wrapper)).toHaveLength(1)
    expect(wrapper.find('#monitor-cpu .skeleton').exists()).toBe(true)
    intersect(['rssi'], false)
    intersect(['tx_rx', 'retry', 'error', 'garp', 'mul_join']); await flushPromises()
    expect(metrics().map(([, query]) => query.metric_group)).toEqual(['rssi', 'counters'])
    intersect(['tx_rx', 'retry', 'error', 'garp', 'mul_join']); await flushPromises()
    expect(metrics()).toHaveLength(2)
    counter.resolve({ items: [sample], total: 1 }); await flushPromises()
    expect(charts(wrapper)).toHaveLength(6)
    expect(metrics().some(([, query]) => query.metric_group === 'cpu')).toBe(false)
    wrapper.unmount(); expect(observers.at(-1)!.disconnect).toHaveBeenCalledOnce()
  })

  it('reuses completed counter source data when counter panels enter sequentially', async () => {
    autoVisible = false
    const wrapper = mounted(); await nav(wrapper, 4)
    for (const key of ['tx_rx', 'retry', 'error', 'garp', 'mul_join']) {
      intersect([key]); await flushPromises()
      expect(metrics().map(([, query]) => query.metric_group)).toEqual(['counters'])
      expect(wrapper.find(`#monitor-${key} .metric-chart`).exists()).toBe(true)
      intersect([key], false)
    }
    expect(charts(wrapper)).toHaveLength(5)
    expect(api.links).toHaveBeenCalledTimes(2)
  })

  it('opens seven business entries lazily and confines six cards to overview', async () => {
    const wrapper = mounted(); await flushPromises()
    expect(wrapper.findAll('.phase11-nav button').map(button => button.text())).toEqual(['分析概览', '链路明细', 'RSSI 分析', 'AP 情况', '主链路监控', '切换事件', '报告与来源'])
    expect(wrapper.findAll('.phase11-cards button')).toHaveLength(6)
    expect(api.summary).toHaveBeenCalledOnce(); expect(api.aps).not.toHaveBeenCalled(); expect(api.links).not.toHaveBeenCalled(); expect(api.issues).not.toHaveBeenCalled(); expect(api.builds).not.toHaveBeenCalled()
    await nav(wrapper, 1); expect(api.issues).not.toHaveBeenCalled(); expect(api.links).not.toHaveBeenCalled(); expect(wrapper.find('.phase11-cards').exists()).toBe(false)
    await nav(wrapper, 2); expect(api.links).not.toHaveBeenCalled()
    await nav(wrapper, 3); expect(api.aps).toHaveBeenCalledOnce(); expect(api.links).not.toHaveBeenCalled(); expect(wrapper.find('.phase11-cards').exists()).toBe(false)
    await nav(wrapper, 4); expect(metrics().map(([, query]) => query.metric_group)).toEqual(metricKeys); expect(api.links).toHaveBeenCalledTimes(9); expect(api.builds).toHaveBeenCalledOnce(); expect(wrapper.find('.phase11-cards').exists()).toBe(false)
    await nav(wrapper, 0); expect(wrapper.findAll('.phase11-cards button')).toHaveLength(6); expect(api.summary).toHaveBeenCalledOnce()
  })

  it('deduplicates an in-flight parse query and caches an empty result across scope changes', async () => {
    const pending = deferred<any>(); api.issues.mockReturnValue(pending.promise)
    const wrapper = mounted(); await flushPromises()
    const details = wrapper.find('.phase11-parse')
    ;(details.element as HTMLDetailsElement).open = true; await details.trigger('toggle'); await details.trigger('toggle')
    expect(api.issues).toHaveBeenCalledOnce()
    const signal = api.issues.mock.calls[0]![2] as AbortSignal
    await control(wrapper, 'ElCheckbox', 0, false); expect(signal.aborted).toBe(false)
    pending.resolve({ items: [], total: 0 }); await flushPromises()
    await details.trigger('toggle'); await nav(wrapper, 3); await nav(wrapper, 0)
    expect(api.issues).toHaveBeenCalledOnce()
  })

  it('resets parse cache on session change and ignores an older session result', async () => {
    const pending = deferred<any>(); api.issues.mockReturnValueOnce(pending.promise).mockResolvedValue({ items: [], total: 0 })
    const wrapper = mounted(); await flushPromises()
    ;(wrapper.find('.phase11-parse').element as HTMLDetailsElement).open = true; await wrapper.find('.phase11-parse').trigger('toggle')
    const signal = api.issues.mock.calls[0]![2] as AbortSignal
    await wrapper.setProps({ sessionId: 'mesh-2', session: { ...session, session_id: 'mesh-2' } }); await flushPromises()
    expect(signal.aborted).toBe(true)
    await wrapper.find('.phase11-parse').trigger('toggle'); expect(api.issues).toHaveBeenCalledTimes(2); expect(api.issues.mock.calls[1]![0]).toBe('mesh-2')
    pending.resolve({ items: [{ code: 'OLD_SESSION', message: '旧任务异常' }], total: 1 }); await flushPromises()
    const parseTable = wrapper.findAllComponents({ name: 'NcDataTable' }).find(component => component.props('tableId') === 'mesh-phase11-parse:v2')!
    expect(parseTable.props('data')).toEqual([])
  })

  it('shows Chinese role labels in business summaries and the historical-role column', async () => {
    const wrapper = mounted(); await flushPromises()
    expect(wrapper.find('.phase11-secondary').text()).toContain('主用（ACTIVE）'); expect(wrapper.find('.phase11-secondary').text()).toContain('备用（STANDBY）')
    await nav(wrapper, 4)
    const historyTable = wrapper.findAllComponents({ name: 'NcDataTable' }).find(component => component.props('tableId') === 'mesh-phase11-history:v1')!
    const roleColumn = historyTable.props('columns').find((column: any) => column.key === 'link_role')
    expect(roleColumn.displayValue(sample)).toBe('主用（ACTIVE）'); expect(roleColumn.displayValue(standby)).toBe('备用（STANDBY）'); expect(roleColumn.displayValue(zero)).toBe('未连接（LinkCnt=0）')
    expect(wrapper.find('.phase11-detail').text()).toContain('主用（ACTIVE）')
  })

  it('uses the latest five minutes and binds twelve charts from eight queries to one domain and window', async () => {
    const wrapper = mounted(); await nav(wrapper, 4)
    expect(charts(wrapper)).toHaveLength(13)
    charts(wrapper).forEach((chart, index) => {
      expect(chart.props('domain')).toEqual({ start: session.first_sample_time, end: session.last_sample_time })
      expect(chart.props('window')).toEqual({ start: '2026-11-09 10:25:00.000', end: session.last_sample_time })
      expect(chart.props('lines')).toHaveLength(index === 8 ? 4 : 2)
    })
    expect(charts(wrapper).map(chart => chart.props('navigator'))).toEqual([...Array(12).fill(false), true])
    for (const [, query] of metrics()) expect(query).toMatchObject({ time_from: '2026-11-09 10:25:00.000', time_to: session.last_sample_time, radio: 1, link_role: 'ACTIVE', exact_ap: true, max_points: 1000, page_size: 1000 })
    expect(wrapper.text()).toContain('0/13 图表完成')
    charts(wrapper)[0]!.vm.$emit('render-complete'); await flushPromises(); expect(wrapper.text()).toContain('1/13 图表完成')
  })

  it('uses one complete raw response for charts, history and time selection', async () => {
    const raw = { ...sample, record_id: 1, source_file_id: 1, establish_time: '2026-11-09 10:26:00.000' }
    api.links.mockImplementation(async (_id, query) => query.raw_samples
      ? { items: [raw], total: 1, page: 1, page_size: 1000, downsampled: false, raw_sample_complete: true, raw_sample_version: 'mesh-raw-v1', raw_context_count: 0, sql_query_count: 3, query_kind: 'raw_samples' }
      : { items: [], total: 0 })
    const wrapper = mounted(); await nav(wrapper, 4)
    expect(api.links).toHaveBeenCalledOnce()
    expect(api.links.mock.calls[0]![1]).toMatchObject({ raw_samples: true, include_context: true, raw_max_rows: 50000 })
    expect(api.links.mock.calls[0]![1].metric_group).toBeUndefined()
    expect(charts(wrapper)).toHaveLength(13)
    const calls = api.links.mock.calls.length
    charts(wrapper)[0]!.vm.$emit('time-select', raw.timestamp); await flushPromises()
    expect(api.links.mock.calls.length).toBe(calls)
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-1')
  })

  it('throttles repeated zoom to 180ms and queries every section for the final window', async () => {
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    const first = range('20'), final = range('22')
    charts(wrapper)[0]!.vm.$emit('viewport-change', first); await flushPromises()
    await vi.advanceTimersByTimeAsync(100)
    charts(wrapper)[1]!.vm.$emit('viewport-change', final); await flushPromises()
    expect(charts(wrapper).every(chart => JSON.stringify(chart.props('window')) === JSON.stringify(final))).toBe(true)
    await vi.advanceTimersByTimeAsync(179); expect(api.links).toHaveBeenCalledTimes(9)
    await vi.advanceTimersByTimeAsync(1); await flushPromises()
    expect(api.links).toHaveBeenCalledTimes(19); expect(api.builds).toHaveBeenCalledTimes(2); expect(timeQueries()).toHaveLength(1)
    expect(api.links.mock.calls.slice(9).every(([, query]) => query.time_from === final.start && query.time_to === final.end)).toBe(true)
    expect(charts(wrapper).every(chart => JSON.stringify(chart.props('window')) === JSON.stringify(final))).toBe(true)
  })

  it('reuses complete metric responses within their original window', async () => {
    api.links.mockImplementation(async (_id, query) => ({ items: [sample], total: 1, downsampled: query.metric_group ? false : undefined }))
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    const initialMetrics = metrics().length
    charts(wrapper)[0]!.vm.$emit('viewport-change', { start: '2026-11-09 10:26:00.000', end: '2026-11-09 10:28:00.000' })
    await vi.advanceTimersByTimeAsync(180); await flushPromises()
    expect(metrics()).toHaveLength(initialMetrics)
    expect(api.builds).toHaveBeenCalledTimes(2)
    // One raw request covers the original window and the narrower window.
    expect(api.links.mock.calls.filter(([, query]) => !query.metric_group && !query.nearest_time)).toHaveLength(1)
  })

  it('reuses complete history and build pages when the window narrows', async () => {
    api.links.mockImplementation(async (_id, query) => ({ items: [sample], total: 1, page: query.page ?? 1, page_size: query.page_size, downsampled: false, zero_link_count: 0 }))
    api.builds.mockImplementation(async (_id, query) => ({ items: [], total: 0, page: query.page, page_size: query.page_size }))
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    const initialLinks = api.links.mock.calls.length
    charts(wrapper)[0]!.vm.$emit('viewport-change', { start: '2026-11-09 10:26:00.000', end: '2026-11-09 10:28:00.000' })
    await vi.advanceTimersByTimeAsync(180); await flushPromises()
    expect(api.links).toHaveBeenCalledTimes(initialLinks + 1)
    expect(timeQueries()).toHaveLength(1)
    expect(api.links.mock.calls.filter(([, query]) => !query.metric_group && !query.nearest_time)).toHaveLength(1)
    expect(api.builds).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('AP 历史采样 · 1 条')
  })

  it('keeps one fully cached range at zero HTTP and SQL for 100 workbench interactions', async () => {
    const rawPage = { items: [sample], total: 1, page: 1, page_size: 1000, downsampled: false, raw_sample_complete: true, raw_sample_version: 'mesh-raw-v1', raw_context_count: 0, sql_query_count: 3, query_kind: 'raw_samples' }
    api.links.mockImplementation(async (_id, query) => query.raw_samples ? rawPage : { items: [sample], total: 1 })
    api.builds.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
    const wrapper = mounted()
    await context(wrapper, range('20'))
    const warmLinks = api.links.mock.calls.length
    const warmBuilds = api.builds.mock.calls.length
    meshQueryTrace.clear()
    for (let index = 0; index < 100; index += 1) await context(wrapper, range('20'))
    await flushPromises()
    const events = meshQueryTrace.snapshot()
    expect(api.links.mock.calls.length).toBe(warmLinks)
    expect(api.builds.mock.calls.length).toBe(warmBuilds)
    expect(events.filter(event => event.stage === 'http')).toHaveLength(0)
    expect(events.filter(event => event.stage === 'sql').reduce((total, event) => total + (event.sql_queries || 0), 0)).toBe(0)
    expect(events.filter(event => event.stage === 'cache' && event.cache_status === 'hit').length).toBeGreaterThanOrEqual(100)
  })

  it('uses the shared raw contract for LinkCnt=0 metrics and history', async () => {
    const rawZero = { ...zero, raw_sample_version: 'mesh-raw-v1', is_boundary_context: false }
    api.links.mockImplementation(async (_id, query) => query.raw_samples
      ? { items: [rawZero], total: 1, page: 1, page_size: 1000, zero_link_count: 1, downsampled: false, raw_sample_complete: true, raw_sample_version: 'mesh-raw-v1', raw_context_count: 0, sql_query_count: 3, query_kind: 'raw_samples' }
      : { items: [rawZero], total: 1 })
    const wrapper = mounted(); await nav(wrapper, 4)
    await control(wrapper, 'ElCheckbox', 2, true)
    const includeZeroCalls = api.links.mock.calls.filter(([, query]) => query.include_zero)
    expect(includeZeroCalls.length).toBeGreaterThan(0)
    expect(includeZeroCalls.every(([, query]) => query.raw_samples === true)).toBe(true)
    expect(includeZeroCalls.some(([, query]) => query.metric_group)).toBe(false)
  })

  it('caches AP statistics pages without mixing role or radio scopes', async () => {
    const wrapper = mounted(); await nav(wrapper, 3)
    expect(api.aps).toHaveBeenCalledOnce()
    await nav(wrapper, 3)
    expect(api.aps).toHaveBeenCalledTimes(2)
    await nav(wrapper, 3)
    expect(api.aps).toHaveBeenCalledTimes(2)
    await control(wrapper, 'ElSelect', 0, 'STANDBY')
    expect(api.aps).toHaveBeenCalledTimes(3)
    await control(wrapper, 'ElSelect', 1, 2)
    expect(api.aps).toHaveBeenCalledTimes(4)
    await control(wrapper, 'ElSelect', 0, 'ACTIVE')
    expect(api.aps).toHaveBeenCalledTimes(5)
  })

  it('shares pointer movement without querying and selects chart samples into right detail', async () => {
    const wrapper = mounted(); await nav(wrapper, 4)
    charts(wrapper)[2]!.vm.$emit('pointer-change', standby.timestamp); await flushPromises()
    expect(charts(wrapper).every(chart => chart.props('pointer') === standby.timestamp)).toBe(true)
    expect(api.links).toHaveBeenCalledTimes(9)
    charts(wrapper)[2]!.vm.$emit('sample-select', standby); await flushPromises()
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-STANDBY'); expect(wrapper.find('.phase11-detail').text()).toContain('STANDBY')
    expect(charts(wrapper).every(chart => chart.props('selectedTime') === standby.timestamp)).toBe(true)
    charts(wrapper)[0]!.vm.$emit('pointer-change', null); await flushPromises(); expect(charts(wrapper).every(chart => chart.props('pointer') === null)).toBe(true)
  })

  it('shows historical roles on history selection including an unconnected sample', async () => {
    const wrapper = mounted(); await nav(wrapper, 4)
    const history = wrapper.find('[data-table-id="mesh-phase11-history:v1"]')
    await history.findAll('button')[1]!.trigger('click'); expect(wrapper.find('.phase11-detail').text()).toContain('STANDBY')
    await history.findAll('button')[2]!.trigger('click'); expect(wrapper.find('.phase11-detail').text()).toContain('未连接（LinkCnt=0）')
    expect(wrapper.find('.phase11-history summary').text()).toContain('未连接 1 条')
    expect(api.links).toHaveBeenCalledTimes(9)
  })

  it('applies exact AP, Radio, historical role and zero-link filters to all requests', async () => {
    const wrapper = mounted(); await nav(wrapper, 4)
    await control(wrapper, 'ElInput', 0, sample.peer_ap_mac)
    await control(wrapper, 'ElSelect', 0, 2)
    await control(wrapper, 'ElSelect', 1, 'STANDBY')
    await control(wrapper, 'ElCheckbox', 2, true)
    const expected = { peer_ap_mac: sample.peer_ap_mac, exact_ap: true, radio: 2, link_role: 'STANDBY', include_zero: true, exclude_depot: true, exclude_parking: true }
    const recent = api.links.mock.calls.slice(-9)
    for (const [, query] of recent.filter(([, query]) => query.raw_samples)) expect(query).toMatchObject({ ...expected, link_role: '', include_zero: true })
    for (const [, query] of recent.filter(([, query]) => !query.raw_samples)) expect(query).toMatchObject({ ...expected, include_zero: expect.any(Boolean) })
    expect(api.builds.mock.calls.at(-1)?.[1]).toMatchObject(expected)
    expect(api.links).toHaveBeenCalledTimes(43)
  })

  it('opens an AP using its exact physical MAC and all historical roles', async () => {
    const wrapper = mounted(); await nav(wrapper, 3)
    await wrapper.find('[data-table-id="mesh-phase11-aps:v3"] button').trigger('click'); await flushPromises()
    expect(wrapper.find('.phase11-monitor').exists()).toBe(true)
    for (const [, query] of api.links.mock.calls) expect(query).toMatchObject({ peer_ap_mac: sample.peer_ap_mac, exact_ap: true, link_role: '' })
  })

  it('ignores stale filter responses and aborts the previous request generation', async () => {
    const old = deferred<any>(); api.links.mockImplementation(() => old.promise)
    const wrapper = mounted(); await nav(wrapper, 4)
    const oldSignals = api.links.mock.calls.map(call => call[2] as AbortSignal)
    api.links.mockResolvedValue({ items: [{ ...sample, peer_ap_name: 'AP-NEW' }], total: 1 })
    await control(wrapper, 'ElInput', 0, 'new-mac')
    expect(oldSignals.every(signal => signal.aborted)).toBe(true)
    old.resolve({ items: [{ ...sample, peer_ap_name: 'AP-STALE' }], total: 1 }); await flushPromises()
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-NEW'); expect(wrapper.text()).not.toContain('AP-STALE')
    expect(charts(wrapper)).toHaveLength(13)
  })

  it('aborts requests and pending zoom when the page closes', async () => {
    const pending = deferred<any>(); api.links.mockImplementation(() => pending.promise)
    const wrapper = mounted(); await nav(wrapper, 4)
    const signals = [...api.links.mock.calls.map(call => call[2] as AbortSignal), api.builds.mock.calls[0]![2] as AbortSignal]
    wrapper.unmount(); expect(signals.every(signal => signal.aborted)).toBe(true)
    pending.resolve({ items: [sample], total: 1 }); await flushPromises(); expect(api.links).toHaveBeenCalledTimes(1)
    const second = mounted(); api.links.mockResolvedValue({ items: [sample], total: 1 }); await nav(second, 4); vi.useFakeTimers()
    charts(second)[0]!.vm.$emit('viewport-change', range('20')); second.unmount(); const calls = api.links.mock.calls.length
    await vi.advanceTimersByTimeAsync(200); expect(api.links).toHaveBeenCalledTimes(calls)
  })

  it('cancels an AP statistics request when leaving the AP workspace', async () => {
    const pending = deferred<any>(); api.aps.mockReturnValue(pending.promise)
    const wrapper = mounted(); await nav(wrapper, 3)
    const signal = api.aps.mock.calls[0]![2] as AbortSignal
    expect(signal.aborted).toBe(false)
    await nav(wrapper, 0)
    expect(signal.aborted).toBe(true)
    wrapper.unmount()
  })

  it('isolates a failed metric query and retries only that metric', async () => {
    api.links.mockImplementation(async (_id, query) => { if (query.metric_group === 'cpu') throw new Error('CPU 查询失败'); return { items: [sample], total: 1 } })
    const wrapper = mounted(); await nav(wrapper, 4)
    expect(charts(wrapper)).toHaveLength(12); expect(wrapper.find('#monitor-cpu .phase-error').text()).toContain('CPU 查询失败')
    charts(wrapper)[0]!.vm.$emit('render-complete'); await flushPromises(); expect(wrapper.find('#monitor-rssi .phase-completed').exists()).toBe(true)
    api.links.mockResolvedValue({ items: [sample], total: 1 })
    await wrapper.find('#monitor-cpu button').trigger('click'); await flushPromises()
    expect(api.links).toHaveBeenCalledTimes(11); expect(api.links.mock.calls.at(-1)?.[1].metric_group).toBe('cpu'); expect(charts(wrapper)).toHaveLength(13)
    expect(wrapper.find('#monitor-cpu .phase-rendering').exists()).toBe(true)
  })

  it('isolates rendering errors and completes empty results without infinite loading', async () => {
    api.links.mockResolvedValue({ items: [], total: 0 })
    const wrapper = mounted(); await nav(wrapper, 4)
    expect(charts(wrapper)).toHaveLength(13); expect(wrapper.find('#monitor-rssi .phase-rendering').text()).toContain('空数据')
    charts(wrapper)[0]!.vm.$emit('render-error', 'RSSI 绘图失败'); charts(wrapper)[1]!.vm.$emit('render-complete'); await flushPromises()
    expect(wrapper.find('#monitor-rssi .phase-error').text()).toContain('RSSI 绘图失败'); expect(wrapper.find('#monitor-cpu .phase-completed').exists()).toBe(true)
    expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
  })

  it('reuses source cache on navigation and keeps explicit refresh querying after old finished events', async () => {
    const wrapper = mounted(); await nav(wrapper, 4); await nav(wrapper, 0)
    const pending = deferred<any>(); api.links.mockImplementation(() => pending.promise)
    await nav(wrapper, 4)
    expect(charts(wrapper)).toHaveLength(13); expect(wrapper.find('#monitor-rssi .phase-rendering').text()).toContain('缓存命中')
    expect(metrics()).toHaveLength(8)
    ;(wrapper.vm as any).refreshData(); await flushPromises()
    expect(charts(wrapper)).toHaveLength(13); expect(wrapper.find('#monitor-rssi .phase-querying').exists()).toBe(true)
    // A refresh invalidates the shared raw scope first; legacy metric
    // fallbacks start only after that raw request returns.
    expect(metrics()).toHaveLength(8)
    charts(wrapper).forEach(chart => chart.vm.$emit('render-complete')); await flushPromises()
    expect(wrapper.find('#monitor-rssi .phase-querying').exists()).toBe(true); expect(wrapper.text()).toContain('0/13 图表完成')
    pending.resolve({ items: [{ ...sample, local_rssi_db: -65 }], total: 1 }); await flushPromises()
    expect(wrapper.find('#monitor-rssi .phase-rendering').exists()).toBe(true)
    expect(charts(wrapper)[0]!.props('lines')[0].data[0].value[1]).toBe(-65)
    charts(wrapper)[0]!.vm.$emit('render-complete'); await flushPromises(); expect(wrapper.find('#monitor-rssi .phase-completed').exists()).toBe(true)
  })

  it('opens exact AP, Radio, window and focus without querying outside that context', async () => {
    const wrapper = mounted(); await flushPromises()
    const value = { ap: sample.peer_ap_mac, radio: 2, start: '2026-11-09 10:26:00.000', end: '2026-11-09 10:29:00.000', focus: standby.timestamp }
    const focused = { ...sample, timestamp: value.focus, peer_ap_name: 'AP-FOCUS', local_radio: 2 }
    api.links.mockImplementation(async (_id, query) => ({ items: query.page_size === 1 ? [focused] : [], total: query.page_size === 1 ? 1 : 0 }))
    await context(wrapper, value)
    expect(api.links).toHaveBeenCalledTimes(10)
    for (const [, query] of api.links.mock.calls.filter(([, query]) => query.raw_samples)) expect(query).toMatchObject({ peer_ap_mac: value.ap, exact_ap: true, radio: 2, link_role: '', include_zero: true })
    for (const [, query] of api.links.mock.calls.filter(([, query]) => !query.raw_samples)) expect(query).toMatchObject({ peer_ap_mac: value.ap, exact_ap: true, radio: 2, link_role: 'ACTIVE', include_zero: false })
    expect(api.links.mock.calls.find(([, query]) => query.page_size === 1)?.[1]).toMatchObject({ time_from: value.focus, time_to: value.focus })
    for (const [, query] of api.links.mock.calls.filter(([, query]) => query.page_size !== 1)) expect(query).toMatchObject({ time_from: value.start, time_to: value.end })
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-FOCUS'); expect(charts(wrapper).every(chart => chart.props('selectedTime') === value.focus)).toBe(true)
  })

  it.each([['STANDBY', standby], ['zero-link', zero]])('rejects an invalid %s focus sample without broadening the query', async (_name, invalid) => {
    const wrapper = mounted(); await flushPromises()
    api.links.mockImplementation(async (_id, query) => ({ items: query.page_size === 1 ? [invalid] : [], total: query.page_size === 1 ? 1 : 0 }))
    await context(wrapper, { ap: sample.peer_ap_mac, radio: 2, ...range('20'), focus: invalid.timestamp })
    expect(api.links).toHaveBeenCalledTimes(10); expect(api.links.mock.calls.filter(([, query]) => query.page_size === 1)).toHaveLength(1)
    expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
    expect(charts(wrapper).every(chart => chart.props('selectedTime') == null && chart.props('selectedSample') == null)).toBe(true)
  })

  it('does not broaden an empty focus query into a cross-window fallback', async () => {
    const wrapper = mounted(); api.links.mockResolvedValue({ items: [], total: 0 })
    await context(wrapper, { ap: sample.peer_ap_mac, radio: 2, ...range('20'), focus: '2026-11-09 10:20:30.000' })
    expect(api.links).toHaveBeenCalledTimes(10); expect(api.links.mock.calls.filter(([, query]) => query.page_size === 1)).toHaveLength(1)
    expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
  })

  it('bounds chart and source caches separately to sixteen entries and evicts older windows', async () => {
    const wrapper = mounted(); await flushPromises()
    await context(wrapper, range('20')); await context(wrapper, range('22')); await context(wrapper, range('24'))
    const pending = deferred<any>(); api.links.mockImplementation(() => pending.promise)
    await context(wrapper, range('22'))
    expect(charts(wrapper)).toHaveLength(13); expect(wrapper.find('#monitor-garp [role="status"]').text()).toContain('缓存命中')
    expect(wrapper.find('#monitor-rssi [role="status"]').text()).not.toContain('缓存命中')
    expect(metrics()).toHaveLength(24)
    await context(wrapper, range('20'))
    expect(charts(wrapper)).toHaveLength(13); expect(wrapper.find('#monitor-rssi [role="status"]').text()).not.toContain('缓存命中')
    expect(metrics()).toHaveLength(24)
    pending.resolve({ items: [], total: 0 }); await flushPromises()
  })

  it('throttles time selection to the latest time and queries ACTIVE within the exact current context', async () => {
    api.links.mockImplementation(async (_id, query) => ({ items: [sample], total: query.metric_group ? 100 : 1, downsampled: Boolean(query.metric_group) }))
    const wrapper = mounted(); await nav(wrapper, 4)
    await control(wrapper, 'ElInput', 0, sample.peer_ap_mac); await control(wrapper, 'ElSelect', 0, 2)
    vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', '2026-11-09 10:26:00.100'); await flushPromises()
    await vi.advanceTimersByTimeAsync(40)
    charts(wrapper)[1]!.vm.$emit('time-select', '2026-11-09 10:26:30.250'); await flushPromises()
    await vi.advanceTimersByTimeAsync(39); expect(timeQueries()).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(1); await flushPromises()
    expect(timeQueries()).toHaveLength(1)
    expect(timeQueries()[0]![1]).toMatchObject({ nearest_time: '2026-11-09 10:26:30.250', page_size: 1, time_from: '2026-11-09 10:25:00.000', time_to: session.last_sample_time, peer_ap_mac: sample.peer_ap_mac, exact_ap: true, radio: 2, link_role: 'ACTIVE', include_zero: false, exclude_depot: true, exclude_parking: true })
    expect(charts(wrapper).every(chart => chart.props('selectedTime') === sample.timestamp && chart.props('pointer') === sample.timestamp)).toBe(true)
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-1')
  })

  it('uses a complete millisecond window index and excludes STANDBY and zero-link samples', async () => {
    const earlier = { ...sample, timestamp: '2026-11-09 10:27:00.100', peer_ap_name: 'AP-EARLY' }
    const later = { ...sample, timestamp: '2026-11-09 10:27:00.900', peer_ap_name: 'AP-LATE' }
    api.links.mockImplementation(async (_id, query) => query.metric_group === 'counters'
      ? { items: [later, { ...standby, timestamp: '2026-11-09 10:27:00.790' }, { ...zero, timestamp: '2026-11-09 10:27:00.800' }, earlier], total: 4, downsampled: false }
      : { items: [{ ...sample, timestamp: '2026-11-09 10:27:00.800', peer_ap_name: 'AP-GAUGE' }], total: 1 })
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', '2026-11-09 10:27:00.800')
    await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(timeQueries()).toHaveLength(0); expect(api.links).toHaveBeenCalledTimes(9)
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-LATE')
    expect(charts(wrapper).every(chart => chart.props('selectedTime') === later.timestamp)).toBe(true)
  })

  it('uses the selected counter record for every chart and all twelve detail metadata cells', async () => {
    const fields = ['local_tx', 'peer_tx', 'local_rx', 'peer_rx', 'local_retry', 'peer_retry', 'local_err', 'peer_err', 'local_tx_garp', 'peer_rx_garp', 'local_tx_mul_join', 'peer_rx_mul_join']
    const counter_samples = Object.fromEntries(fields.map((field, index) => [field, { current: 9000 + index, previous: 8000 + index, delta: 1000, interval_seconds: 0.5, per_second: 2000, status: 'valid' }]))
    const selected = { ...sample, timestamp: '2026-11-09 10:27:00.987', peer_ap_name: 'AP-COUNTER-RAW', ...Object.fromEntries(fields.map(field => [field, counter_samples[field]!.current])), counter_samples }
    api.links.mockImplementation(async (_id, query) => ({ items: [query.metric_group === 'counters' ? selected : { ...sample, peer_ap_name: 'AP-GAUGE-OLD' }], total: 1, downsampled: false }))
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', selected.timestamp)
    await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(timeQueries()).toHaveLength(0)
    expect(charts(wrapper).every(chart => JSON.stringify(chart.props('selectedSample')) === JSON.stringify(selected))).toBe(true)
    const detail = wrapper.find('.phase11-detail')
    expect(detail.text()).toContain(selected.timestamp); expect(detail.text()).toContain('AP-COUNTER-RAW'); expect(detail.text()).not.toContain('AP-GAUGE-OLD')
    const cells = detail.findAll('.counter-detail')
    expect(cells).toHaveLength(12)
    cells.forEach((cell, index) => {
      expect(cell.text()).toContain(`上次 ${8000 + index} · 增量 1000 · 间隔 0.5 s · 速率 2000 次/s`)
      expect(cell.element.parentElement!.textContent).toContain(String(9000 + index))
    })
  })

  it('keeps Shift selection fixed until selection-clear and resumes pointer movement', async () => {
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', sample.timestamp, true)
    await vi.advanceTimersByTimeAsync(0); await flushPromises()
    expect(wrapper.find('.phase11-selection').text()).toContain('已固定'); expect(wrapper.find('.phase11-selection').text()).toContain('Esc')
    charts(wrapper)[1]!.vm.$emit('pointer-change', standby.timestamp); charts(wrapper)[1]!.vm.$emit('time-select', standby.timestamp)
    await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(charts(wrapper).every(chart => chart.props('pointer') === sample.timestamp)).toBe(true)
    charts(wrapper)[1]!.vm.$emit('selection-clear'); await flushPromises()
    expect(wrapper.find('.phase11-selection').text()).toBe(''); expect(charts(wrapper).every(chart => chart.props('pointer') === null)).toBe(true)
    expect(charts(wrapper).every(chart => chart.props('selectedTime') == null && chart.props('selectedSample') == null && chart.props('selectionActive') === false)).toBe(true)
    expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
    charts(wrapper)[1]!.vm.$emit('pointer-change', standby.timestamp); await flushPromises()
    expect(charts(wrapper).every(chart => chart.props('pointer') === standby.timestamp)).toBe(true)
  })

  it('aborts old time queries, ignores stale results and reuses the same time cache', async () => {
    const old = deferred<any>(), latest = deferred<any>()
    const firstTime = '2026-11-09 10:26:00.000', nextTime = '2026-11-09 10:28:00.000'
    api.links.mockImplementation(async (_id, query) => query.nearest_time ? (query.nearest_time === firstTime ? old.promise : latest.promise) : { items: [sample], total: 100, downsampled: true })
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', firstTime); await vi.advanceTimersByTimeAsync(80)
    const oldSignal = timeQueries()[0]![2] as AbortSignal
    charts(wrapper)[0]!.vm.$emit('time-select', nextTime); await vi.advanceTimersByTimeAsync(80)
    expect(oldSignal.aborted).toBe(true)
    latest.resolve({ items: [{ ...sample, timestamp: nextTime, peer_ap_name: 'AP-LATEST' }], total: 1 }); await flushPromises()
    old.resolve({ items: [{ ...sample, timestamp: firstTime, peer_ap_name: 'AP-STALE' }], total: 1 }); await flushPromises()
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-LATEST'); expect(wrapper.find('.phase11-detail').text()).not.toContain('AP-STALE')
    charts(wrapper)[0]!.vm.$emit('time-select', nextTime); await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(timeQueries()).toHaveLength(2); expect(charts(wrapper).every(chart => chart.props('selectedTime') === nextTime)).toBe(true)
  })

  it('distinguishes an empty ACTIVE time result from query failure and supports a later retry', async () => {
    let attempt = 0
    api.links.mockImplementation(async (_id, query) => {
      if (!query.nearest_time) return { items: [sample], total: 100, downsampled: true }
      attempt++; if (attempt === 1) return { items: [standby, zero], total: 2 }
      if (attempt === 2) throw new Error('时间点查询失败')
      return { items: [sample], total: 1 }
    })
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', '2026-11-09 10:26:00.000'); await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(wrapper.find('.phase11-selection').text()).toContain('无有效主用链路'); expect(wrapper.find('.phase11-detail').text()).toContain('当前窗口暂无选中样本')
    charts(wrapper)[0]!.vm.$emit('time-select', '2026-11-09 10:26:30.000'); await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(wrapper.find('.phase11-selection').text()).toContain('时间点查询失败')
    charts(wrapper)[0]!.vm.$emit('time-select', '2026-11-09 10:26:30.000'); await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-1'); expect(timeQueries()).toHaveLength(3)
  })

  it('invalidates an old time response as soon as a newer time enters the throttle window', async () => {
    const pending = deferred<any>()
    api.links.mockImplementation(async (_id, query) => query.nearest_time ? pending.promise : { items: [sample], total: 100, downsampled: true })
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', sample.timestamp); await vi.advanceTimersByTimeAsync(80)
    const signal = timeQueries()[0]![2] as AbortSignal
    charts(wrapper)[0]!.vm.$emit('time-select', standby.timestamp); await flushPromises()
    pending.resolve({ items: [{ ...sample, peer_ap_name: 'AP-STALE' }], total: 1 }); await flushPromises()
    expect(signal.aborted).toBe(true); expect(wrapper.find('.phase11-detail').text()).not.toContain('AP-STALE')
    expect(charts(wrapper).every(chart => chart.props('pointer') === standby.timestamp)).toBe(true)
  })

  it('cancels active time lookup and a pending selection timer on page close', async () => {
    const pending = deferred<any>()
    api.links.mockImplementation(async (_id, query) => query.nearest_time ? pending.promise : { items: [sample], total: 100, downsampled: true })
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('time-select', sample.timestamp); await vi.advanceTimersByTimeAsync(80)
    const signal = timeQueries()[0]![2] as AbortSignal
    charts(wrapper)[0]!.vm.$emit('time-select', standby.timestamp); wrapper.unmount()
    expect(signal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(100); expect(timeQueries()).toHaveLength(1)
    pending.resolve({ items: [sample], total: 1 }); await flushPromises()
  })

  it('re-locates an out-of-window selection within the new window after zoom', async () => {
    const relocated = { ...sample, timestamp: '2026-11-09 10:23:00.000', peer_ap_name: 'AP-WINDOW' }
    api.links.mockImplementation(async (_id, query) => query.nearest_time ? { items: [relocated], total: 1 } : { items: [sample], total: 100, downsampled: true })
    const wrapper = mounted(); await nav(wrapper, 4); vi.useFakeTimers()
    charts(wrapper)[0]!.vm.$emit('viewport-change', range('22')); await vi.advanceTimersByTimeAsync(180); await flushPromises()
    expect(timeQueries()).toHaveLength(1)
    expect(timeQueries()[0]![1]).toMatchObject({ time_from: '2026-11-09 10:22:00.000', time_to: '2026-11-09 10:23:00.000', nearest_time: relocated.timestamp, link_role: 'ACTIVE' })
    expect(wrapper.find('.phase11-detail').text()).toContain('AP-WINDOW'); expect(charts(wrapper).every(chart => chart.props('selectedTime') === relocated.timestamp)).toBe(true)
  })
})
