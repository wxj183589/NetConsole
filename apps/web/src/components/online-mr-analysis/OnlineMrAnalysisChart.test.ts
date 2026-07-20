// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  dispose: vi.fn(),
  resize: vi.fn(),
  setOption: vi.fn(),
  disconnect: vi.fn(),
  unsubscribe: vi.fn(),
  use: vi.fn(),
  init: vi.fn(),
}))
mocks.init.mockReturnValue({ dispose: mocks.dispose, resize: mocks.resize, setOption: mocks.setOption })

vi.mock('echarts/core', () => ({ use: mocks.use, init: mocks.init }))
vi.mock('echarts/charts', () => ({ LineChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, LegendComponent: {}, TooltipComponent: {}, DataZoomComponent: {}, MarkLineComponent: {}, ToolboxComponent: {} }))
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
  mocks.init.mockReturnValue({ dispose: mocks.dispose, resize: mocks.resize, setOption: mocks.setOption })
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

    expect(mocks.setOption).toHaveBeenCalled()
    const option = mocks.setOption.mock.calls.at(-1)?.[0] as { series: Array<{ data: Array<{ value: [string, number | null] }>; markLine?: unknown }> }
    expect(option.series[0].data.map((row) => row.value[1])).toEqual([-60, null])
    expect(option.series[0].markLine).toBeDefined()

    wrapper.unmount()
    expect(mocks.disconnect).toHaveBeenCalledOnce()
    expect(mocks.unsubscribe).toHaveBeenCalledOnce()
    expect(mocks.dispose).toHaveBeenCalledOnce()
  })
})
