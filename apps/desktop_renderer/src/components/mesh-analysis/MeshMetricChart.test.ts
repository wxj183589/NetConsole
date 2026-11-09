// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MeshMetricChart from './MeshMetricChart.vue'
import { formatMeshViewportTimestamp as stamp, meshTimestampMillis as millis } from './meshChartViewport'

const echarts = vi.hoisted(() => {
  type Listener = (event?: any) => void
  function createChart() {
    const listeners = new Map<string, Set<Listener>>()
    const zrListeners = new Map<string, Set<Listener>>()
    const emit = (name: string, event?: unknown) => [...(listeners.get(name) ?? [])].forEach(listener => listener(event))
    const zr = {
      on: vi.fn((name: string, listener: Listener) => { zrListeners.set(name, new Set([listener])) }),
      off: vi.fn((name: string, listener: Listener) => { zrListeners.get(name)?.delete(listener) }),
    }
    return {
      listeners, zrListeners, emit, zr,
      setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(),
      on: vi.fn((name: string, listener: Listener) => {
        if (!listeners.has(name)) listeners.set(name, new Set())
        listeners.get(name)!.add(listener)
      }),
      off: vi.fn((name: string, listener: Listener) => { listeners.get(name)?.delete(listener) }),
      dispatchAction: vi.fn((action: any, _options?: unknown) => {
        // Echo even silent actions to verify the component's own loop guard.
        if (action.type === 'dataZoom') emit('datazoom', action)
        if (action.type === 'updateAxisPointer') emit('updateAxisPointer', { axesInfo: [{ value: 0 }] })
      }),
      convertToPixel: vi.fn(() => 120), getHeight: vi.fn(() => 190), getZr: vi.fn(() => zr),
    }
  }
  return { createChart, init: vi.fn(() => createChart()), use: vi.fn() }
})
vi.mock('echarts/core', () => ({ init: echarts.init, use: echarts.use }))
vi.mock('echarts/charts', () => ({ LineChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, DataZoomComponent: {}, LegendComponent: {}, AxisPointerComponent: {}, MarkLineComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const domain = { start: '2026-11-09 10:00:00.000', end: '2026-11-09 10:10:00.000' }
const point = { timestamp: domain.start, value: -45 }
let wrappers: VueWrapper[] = []
let resizeObservers: Array<{ callback: () => void; observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = []
let intersections: Array<{ callback: (entries: Array<{ isIntersecting: boolean }>) => void; observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = []
function mounted(props = {}) {
  const wrapper = mount(MeshMetricChart, { props: { points: [point], domain, ...props } })
  wrappers.push(wrapper)
  return wrapper
}
async function visible(wrapper: VueWrapper) {
  await flushPromises()
  intersections[wrappers.indexOf(wrapper)].callback([{ isIntersecting: true }])
  await flushPromises()
  return echarts.init.mock.results.at(-1)!.value as ReturnType<typeof echarts.createChart>
}
beforeEach(() => {
  vi.clearAllMocks()
  wrappers = []; resizeObservers = []; intersections = []
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn(); disconnect = vi.fn()
    constructor(public callback: () => void) { resizeObservers.push(this) }
  })
  vi.stubGlobal('IntersectionObserver', class {
    observe = vi.fn(); disconnect = vi.fn()
    constructor(public callback: (entries: Array<{ isIntersecting: boolean }>) => void) { intersections.push(this) }
  })
})
afterEach(() => { wrappers.forEach(wrapper => wrapper.unmount()); vi.unstubAllGlobals() })

describe('MeshMetricChart lifecycle and shared timeline', () => {
  it('lazily creates the chart and completes only after ECharts finished', async () => {
    const wrapper = mounted()
    await flushPromises()
    expect(echarts.init).not.toHaveBeenCalled()
    const chart = await visible(wrapper)
    expect(chart.setOption).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('render-complete')).toBeUndefined()
    chart.emit('finished')
    chart.emit('finished')
    expect(wrapper.emitted('render-complete')).toHaveLength(1)
    expect(chart.listeners.get('finished')?.size).toBe(0)
  })

  it('does not let an obsolete render finish the current render', async () => {
    const wrapper = mounted()
    const chart = await visible(wrapper)
    const oldFinished = [...chart.listeners.get('finished')!][0]
    await wrapper.setProps({ points: [{ ...point, value: -60 }] })
    await flushPromises()
    oldFinished()
    expect(wrapper.emitted('render-complete')).toBeUndefined()
    chart.emit('finished')
    expect(wrapper.emitted('render-complete')).toHaveLength(1)
    expect(chart.setOption).toHaveBeenCalledTimes(2)
    expect(echarts.init).toHaveBeenCalledTimes(1)
  })

  it('shows empty data explicitly and still waits for its real render completion', async () => {
    const wrapper = mounted({ points: [] })
    const chart = await visible(wrapper)
    expect(wrapper.text()).toContain('暂无有效数据')
    expect(wrapper.emitted('render-complete')).toBeUndefined()
    chart.emit('finished')
    expect(wrapper.emitted('render-complete')).toHaveLength(1)
    await wrapper.setProps({ points: [{ ...point, value: null }] })
    expect(wrapper.text()).toContain('暂无有效数据')
  })

  it('lets independent charts complete independently', async () => {
    const first = mounted(); const second = mounted()
    const firstChart = await visible(first); const secondChart = await visible(second)
    secondChart.emit('finished')
    expect(second.emitted('render-complete')).toHaveLength(1)
    expect(first.emitted('render-complete')).toBeUndefined()
    firstChart.emit('finished')
    expect(first.emitted('render-complete')).toHaveLength(1)
  })

  it('keeps Vue empty overlays outside the ECharts-owned host across empty and populated updates', async () => {
    const wrapper = mounted({ points: [] })
    await visible(wrapper)
    const host = wrapper.get('.mesh-metric-chart')
    expect(host.find('.metric-empty').exists()).toBe(false)
    expect(wrapper.get('.metric-empty').element.parentElement).toBe(wrapper.element)
    // ECharts owns and may replace all children of its host.
    host.element.replaceChildren(document.createElement('canvas'))
    await wrapper.setProps({ points: [point] })
    expect(wrapper.find('.metric-empty').exists()).toBe(false)
    await wrapper.setProps({ points: [{ ...point, value: null }] })
    expect(wrapper.get('.metric-empty').element.parentElement).toBe(wrapper.element)
    expect(host.find('canvas').exists()).toBe(true)
  })

  it('converts percentage and explicit datazoom bounds into actual domain times', async () => {
    const wrapper = mounted(); const chart = await visible(wrapper)
    chart.emit('datazoom', { batch: [{ start: 25, end: 75 }] })
    expect(wrapper.emitted('viewport-change')?.[0]).toEqual([{ start: '2026-11-09 10:02:30.000', end: '2026-11-09 10:07:30.000' }])
    const start = millis(domain.start)! + 1234; const end = millis(domain.end)! - 5678
    chart.emit('datazoom', { startValue: start, endValue: end, start: 0, end: 100 })
    expect(wrapper.emitted('viewport-change')?.[1]).toEqual([{ start: stamp(start), end: stamp(end) }])
    chart.emit('datazoom', { startValue: end, endValue: start })
    expect(wrapper.emitted('viewport-change')).toHaveLength(2)
  })

  it('silently applies shared windows and pointers without emitting feedback loops', async () => {
    const wrapper = mounted(); const chart = await visible(wrapper)
    await wrapper.setProps({ window: domain, pointer: domain.start })
    expect(chart.dispatchAction).toHaveBeenCalledWith({ type: 'dataZoom', startValue: millis(domain.start), endValue: millis(domain.end) }, { silent: true })
    expect(chart.dispatchAction).toHaveBeenCalledWith(expect.objectContaining({ type: 'updateAxisPointer', x: 120, y: 95 }), { silent: true })
    expect(wrapper.emitted('viewport-change')).toBeUndefined()
    expect(wrapper.emitted('pointer-change')).toBeUndefined()
    await wrapper.setProps({ pointer: null })
    expect(chart.dispatchAction).toHaveBeenLastCalledWith({ type: 'hideTip' }, { silent: true })
  })

  it('emits user pointer, sample selection and pointer leave events', async () => {
    const wrapper = mounted(); const chart = await visible(wrapper)
    chart.emit('updateAxisPointer', { axesInfo: [{ value: millis(domain.start) }] })
    chart.emit('updateAxisPointer', { axesInfo: [] })
    expect(wrapper.emitted('pointer-change')).toEqual([[domain.start]])
    chart.emit('click', { data: { sample: point } })
    chart.emit('click', { data: {} })
    expect(wrapper.emitted('sample-select')).toEqual([[point]])
    chart.zrListeners.get('globalout')!.forEach(listener => listener())
    expect(wrapper.emitted('pointer-change')?.at(-1)).toEqual([null])
  })

  it('reuses the chart on resize and removes all observers and events on unmount', async () => {
    const wrapper = mounted(); const chart = await visible(wrapper)
    const staleFinished = [...chart.listeners.get('finished')!][0]
    resizeObservers[0].callback()
    expect(chart.resize).toHaveBeenCalledTimes(1)
    expect(echarts.init).toHaveBeenCalledTimes(1)
    wrapper.unmount()
    expect(resizeObservers[0].disconnect).toHaveBeenCalledTimes(1)
    expect(intersections[0].disconnect).toHaveBeenCalledTimes(1)
    for (const name of ['finished', 'datazoom', 'updateAxisPointer', 'click']) expect(chart.listeners.get(name)?.size).toBe(0)
    expect(chart.zrListeners.get('globalout')?.size).toBe(0)
    expect(chart.dispose).toHaveBeenCalledTimes(1)
    staleFinished(); resizeObservers[0].callback()
    expect(wrapper.emitted('render-complete')).toBeUndefined()
    expect(chart.resize).toHaveBeenCalledTimes(1)
  })

  it('does not initialize if unmounted while its asynchronous render is pending', async () => {
    const wrapper = mounted()
    await flushPromises()
    intersections[0].callback([{ isIntersecting: true }])
    wrapper.unmount()
    await flushPromises()
    expect(echarts.init).not.toHaveBeenCalled()
  })

  it('renders without IntersectionObserver support', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const wrapper = mounted()
    await flushPromises()
    expect(echarts.init).toHaveBeenCalledTimes(1)
    const chart = echarts.init.mock.results[0].value
    chart.emit('finished')
    expect(wrapper.emitted('render-complete')).toHaveLength(1)
  })

  it('cleans up failed render completion and allows a later retry', async () => {
    const wrapper = mounted(); const chart = await visible(wrapper)
    chart.emit('finished')
    chart.setOption.mockImplementationOnce(() => { throw new Error('绘图失败') })
    await wrapper.setProps({ points: [{ ...point, value: -70 }] })
    await flushPromises()
    expect(wrapper.emitted('render-error')).toEqual([['绘图失败']])
    expect(chart.listeners.get('finished')?.size).toBe(0)
    chart.emit('finished')
    expect(wrapper.emitted('render-complete')).toHaveLength(1)
    await wrapper.setProps({ points: [point] })
    await flushPromises()
    chart.emit('finished')
    expect(wrapper.emitted('render-complete')).toHaveLength(2)
  })
})
