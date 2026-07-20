// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MeshCounterDeltaChart from './MeshCounterDeltaChart.vue'
import MeshRateChart from './MeshRateChart.vue'
import MeshSwitchRssiChart from './MeshSwitchRssiChart.vue'

const echartsMock = vi.hoisted(() => {
  const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  return { chart, init: vi.fn(() => chart), use: vi.fn() }
})

vi.mock('echarts/core', () => ({ init: echartsMock.init, use: echartsMock.use }))
vi.mock('echarts/charts', () => ({ LineChart: {}, ScatterChart: {} }))
vi.mock('echarts/components', () => ({ DataZoomComponent: {}, GridComponent: {}, LegendComponent: {}, TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

describe('MESH charts mount and render', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mounts all new charts, renders real series and disposes ECharts', async () => {
    const wrappers = [
      mount(MeshRateChart, { props: { points: [{ timestamp: '2026-07-20T10:00:00.123Z', local_radio: 1, peer_ap_name: 'AP-1', peer_ap_mac: null, local_rate_raw: 54, peer_rate_raw: null }] } }),
      mount(MeshCounterDeltaChart, { props: { points: [{ timestamp: '2026-07-20T10:00:00.123Z', local_radio: 1, peer_ap_name: 'AP-1', peer_ap_mac: null, local_retry_delta: 2, peer_retry_delta: null, local_error_delta: 1, peer_error_delta: 0 }] } }),
      mount(MeshSwitchRssiChart, { props: { events: [{ event_id: 1, timestamp: '2026-07-20T10:00:00.123Z', event_type: 'switch', mr_name: 'MR-1', local_radio: 1, from_peer_mac: null, to_peer_mac: null, from_ap_name: 'AP-1', to_ap_name: 'AP-2', before_rssi: -40, after_rssi: -45, duration_ms: null, is_short_link: false, is_pingpong: false, station: null, section: null, warning: null }] } }),
    ]
    await flushPromises()

    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(3)
    const options = echartsMock.chart.setOption.mock.calls.map(([option]) => option as { series: Array<{ name: string; type: string }> })
    expect(options[0].series[0].name).toContain('Rate 原始值')
    expect(options[1].series[0].name).toContain('Retry 增量')
    expect(options[2].series.every((item) => item.type === 'scatter')).toBe(true)

    wrappers.forEach((wrapper) => wrapper.unmount())
    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(3)
  })
})
