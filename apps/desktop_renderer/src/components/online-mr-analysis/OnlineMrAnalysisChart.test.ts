// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  dispose: vi.fn(),
  resize: vi.fn(),
  setOption: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  dispatchAction: vi.fn(),
  zrOn: vi.fn(),
  zrOff: vi.fn(),
  disconnect: vi.fn(),
  unsubscribe: vi.fn(),
  use: vi.fn(),
  init: vi.fn(),
}))
mocks.init.mockReturnValue({
  dispose: mocks.dispose,
  resize: mocks.resize,
  setOption: mocks.setOption,
  on: mocks.on,
  off: mocks.off,
  dispatchAction: mocks.dispatchAction,
  getZr: () => ({ on: mocks.zrOn, off: mocks.zrOff }),
})

vi.mock('echarts/core', () => ({ use: mocks.use, init: mocks.init }))
vi.mock('echarts/charts', () => ({ LineChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, LegendComponent: {}, TooltipComponent: {}, DataZoomComponent: {}, MarkLineComponent: {}, MarkPointComponent: {}, ToolboxComponent: {}, TitleComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('../../theme/echarts', () => ({
  createNetConsoleAxisStyle: () => ({}),
  createNetConsoleDataZoomStyle: () => ({}),
  createNetConsoleLegendStyle: () => ({}),
  createNetConsoleTooltipStyle: () => ({}),
  readNetConsoleChartTokens: () => ({ series: [], text: '#000', textSecondary: '#666', warning: '#f90', danger: '#f00' }),
  subscribeNetConsoleChartTheme: () => mocks.unsubscribe,
}))

import OnlineMrAnalysisChart from './OnlineMrAnalysisChart.vue'

beforeEach(() => {
  vi.clearAllMocks()
  mocks.init.mockReturnValue({
    dispose: mocks.dispose,
    resize: mocks.resize,
    setOption: mocks.setOption,
    on: mocks.on,
    off: mocks.off,
    dispatchAction: mocks.dispatchAction,
    getZr: () => ({ on: mocks.zrOn, off: mocks.zrOff }),
  })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() { mocks.disconnect() } })
})

describe('Online MR analysis chart behavior', () => {
  it('renders real null-aware series and releases chart subscriptions on unmount', async () => {
    const wrapper = mount(OnlineMrAnalysisChart, {
      props: {
        title: 'RSSI',
        unit: 'dBm',
        series: [{ metric_type: 'rssi', series_key: 'radio=1', unit: 'dBm', points: [{ timestamp: '2026-07-20 10:00:00', value: -60, text_value: null, dimensions: { radio: 1 } }, { timestamp: '2026-07-20 10:00:01', value: null, text_value: null, dimensions: { radio: 1 } }], summary: { count: 2, minimum: -60, maximum: -60, average: -60 } }],
        events: [{ time: '2026-07-20 10:00:01', label: '切换' }],
      },
      global: { stubs: { ElEmpty: true } },
    })
    await flushPromises()

    expect(mocks.init).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      undefined,
      expect.objectContaining({ renderer: 'canvas', useDirtyRect: false }),
    )
    expect(mocks.setOption).toHaveBeenCalled()
    const option = mocks.setOption.mock.calls.at(-1)?.[0] as {
      grid: Record<string, unknown>
      legend: { type: string }
      yAxis: { name: string }
      series: Array<{ data: Array<{ value: [string, number | null] }>; markLine?: unknown }>
    }
    expect(option.legend.type).toBe('scroll')
    expect(option.grid).toEqual({ left: 58, right: 24, top: 32, bottom: 72, containLabel: true })
    expect(option.yAxis.name).toBe('dBm')
    expect(option.series[0].data.map((row) => row.value[1])).toEqual([-60, null])
    expect(option.series[0].markLine).toBeDefined()
    expect(option).not.toHaveProperty('graphic')
    const tooltip = mocks.setOption.mock.calls.at(-1)?.[0]?.tooltip as Record<string, unknown>
    expect(tooltip).toMatchObject({ renderMode: 'html', appendToBody: false, confine: true, transitionDuration: 0 })
    expect(String(tooltip.extraCssText)).toContain('width:max-content')
    expect(mocks.setOption.mock.calls.at(-1)?.[1]).toEqual({ replaceMerge: ['series', 'dataZoom'] })

    wrapper.unmount()
    expect(mocks.off).toHaveBeenCalledTimes(3)
    expect(mocks.zrOff).toHaveBeenCalledOnce()
    expect(mocks.disconnect).toHaveBeenCalledOnce()
    expect(mocks.unsubscribe).toHaveBeenCalledOnce()
    expect(mocks.dispose).toHaveBeenCalledOnce()
  })

  it('replaces metric series without creating another instance or retaining a graphic overlay', async () => {
    const wrapper = mount(OnlineMrAnalysisChart, {
      props: {
        unit: 'Mbps',
        tooltipKind: 'traffic',
        series: [{ metric_type: 'iperf_bitrate', series_key: 'upload', unit: 'Mbps', points: [{ timestamp: '2026-07-20 10:00:00', value: 13.5, text_value: null, dimensions: { direction: 'upload' } }], summary: { count: 1, minimum: 13.5, maximum: 13.5, average: 13.5 } }],
      },
      global: { stubs: { ElEmpty: true } },
    })
    await flushPromises()
    const firstOptionCount = mocks.setOption.mock.calls.length
    await wrapper.setProps({
      unit: '%',
      tooltipKind: 'channel-busy',
      series: [{ metric_type: 'ctl_busy', series_key: 'radio=1', unit: '%', points: [{ timestamp: '2026-07-20 10:00:01', value: null, text_value: null, dimensions: { radio: 1 } }], summary: { count: 1, minimum: null, maximum: null, average: null } }],
    })
    await flushPromises()
    expect(mocks.init).toHaveBeenCalledOnce()
    expect(mocks.setOption.mock.calls.length).toBeGreaterThan(firstOptionCount)
    const option = mocks.setOption.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(option).not.toHaveProperty('graphic')
    expect((option.series as Array<{ data: Array<{ value: [string, number | null] }> }>)[0].data[0].value[1]).toBeNull()
    wrapper.unmount()
  })

  it('maps the real RTT point to 44.7 ms without entering the loss formatter', async () => {
    const wrapper = mount(OnlineMrAnalysisChart, {
      props: {
        title: 'Ping RTT',
        unit: 'ms',
        tooltipKind: 'ping-rtt',
        series: [{ metric_type: 'ping_rtt', series_key: '10.122.2.249', unit: 'ms', points: [{ timestamp: '2026-08-10 02:54:56.670', value: 44.7, text_value: null, dimensions: { target_ip: '10.122.2.249' } }], summary: { count: 1, minimum: 44.7, maximum: 44.7, average: 44.7 } }],
      },
      global: { stubs: { ElEmpty: true } },
    })
    await flushPromises()

    const option = mocks.setOption.mock.calls.at(-1)?.[0] as { yAxis: Record<string, unknown>; series: Array<{ data: Array<{ value: [string, number] }> }>; tooltip: { formatter: (rows: unknown[]) => string } }
    expect(option.yAxis).toMatchObject({ name: 'ms', min: 0 })
    expect(option.yAxis.max).toBeUndefined()
    expect(option.series[0].data[0].value).toEqual(['2026-08-10 02:54:56.670', 44.7])
    const html = option.tooltip.formatter([{
      seriesName: '10.122.2.249',
      value: ['2026-08-10 02:54:56.670', 44.7],
      data: { metricType: 'ping_rtt', point: { timestamp: '2026-08-10 02:54:56.670', value: 44.7, text_value: null, dimensions: { target_ip: '10.122.2.249' } } },
    }])
    expect(html).toContain('RTT')
    expect(html).toContain('44.7 ms')
    expect(html).not.toContain('44.7%')
    wrapper.unmount()
  })

  it('keeps a 280 ms RTT point on a dynamically sized axis', async () => {
    const wrapper = mount(OnlineMrAnalysisChart, {
      props: {
        title: 'Ping RTT',
        unit: 'ms',
        tooltipKind: 'ping-rtt',
        series: [{ metric_type: 'ping_rtt', series_key: '10.122.2.249', unit: 'ms', points: [{ timestamp: '2026-08-10 02:56:22.906', value: 280, text_value: null, dimensions: { target_ip: '10.122.2.249' } }], summary: { count: 1, minimum: 280, maximum: 280, average: 280 } }],
      },
      global: { stubs: { ElEmpty: true } },
    })
    await flushPromises()

    const option = mocks.setOption.mock.calls.at(-1)?.[0] as { yAxis: Record<string, unknown>; tooltip: { formatter: (rows: unknown[]) => string } }
    expect(option.yAxis).toMatchObject({ name: 'ms', min: 0 })
    expect(option.yAxis.max).toBeUndefined()
    const html = option.tooltip.formatter([{ value: ['2026-08-10 02:56:22.906', 280], data: { metricType: 'ping_rtt' } }])
    expect(html).toContain('280 ms')
    expect(html).not.toContain('280%')
    wrapper.unmount()
  })

  it('keeps Ping loss at 0% on a 0~100 percent axis', async () => {
    const wrapper = mount(OnlineMrAnalysisChart, {
      props: {
        title: 'Ping 丢包率',
        unit: '%',
        tooltipKind: 'ping-loss',
        series: [{ metric_type: 'ping_loss', series_key: '10.122.2.249', unit: '%', points: [{ timestamp: '2026-08-10 02:54:56.670', value: 0, text_value: null, dimensions: { target_ip: '10.122.2.249', sent: 1, received: 1, lost: 0 } }], summary: { count: 1, minimum: 0, maximum: 0, average: 0 } }],
      },
      global: { stubs: { ElEmpty: true } },
    })
    await flushPromises()

    const option = mocks.setOption.mock.calls.at(-1)?.[0] as { yAxis: Record<string, unknown>; series: Array<{ data: Array<{ value: [string, number] }> }>; tooltip: { formatter: (rows: unknown[]) => string } }
    expect(option.yAxis).toMatchObject({ name: '%', min: 0, max: 100 })
    expect(option.series[0].data[0].value[1]).toBe(0)
    const html = option.tooltip.formatter([{ value: ['2026-08-10 02:54:56.670', 0], data: { metricType: 'ping_loss' } }])
    expect(html).toContain('0%')
    expect(html).not.toContain('44.7')
    wrapper.unmount()
  })
})
