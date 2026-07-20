// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MeshChannelBusyChart from './MeshChannelBusyChart.vue'
import MeshRssiChart from './MeshRssiChart.vue'
import MeshSwitchRssiChart from './MeshSwitchRssiChart.vue'
import type { MeshChartEvent, MeshChartPoint } from '../../types/meshAnalysis'

const echartsMock = vi.hoisted(() => {
  const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), dispatchAction: vi.fn(), on: vi.fn(), off: vi.fn() }
  return { chart, init: vi.fn(() => chart), use: vi.fn() }
})

vi.mock('echarts/core', () => ({ init: echartsMock.init, use: echartsMock.use }))
vi.mock('echarts/charts', () => ({ LineChart: {}, ScatterChart: {} }))
vi.mock('echarts/components', () => ({ DataZoomComponent: {}, GridComponent: {}, LegendComponent: {}, MarkAreaComponent: {}, MarkLineComponent: {}, ToolboxComponent: {}, TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const chartPoint: MeshChartPoint = {
  link_id: 1, timestamp: '2026-07-20T10:00:00.123Z', timestamp_tag: 'sample-1', source_file_id: 1,
  local_radio: 1, link_state: 'ACTIVE', peer_mac: 'peer-1', peer_ap_name: 'AP-1', peer_ap_mac: 'ap-1', peer_radio: 'Radio 1', peer_radio_mac: null,
  station: '站点一', section: '区间一', local_rssi: -40, peer_rssi: -45, local_signal: -50, peer_signal: -55,
  local_tx_busy: 20, peer_tx_busy: 30, local_rx_busy: 25, peer_rx_busy: 35, is_switch: true, is_anomaly: false, gap_before: false,
  backups: [{ link_id: 2, timestamp: '2026-07-20T10:00:00.123Z', timestamp_tag: 'sample-1', local_radio: 1, peer_mac: 'backup', peer_ap_name: '备链 AP', peer_ap_mac: null, peer_radio: null, peer_radio_mac: null, local_rssi: -60, peer_rssi: -62, local_signal: -65, peer_signal: -67, local_tx_busy: 10, peer_tx_busy: 11, local_rx_busy: 12, peer_rx_busy: 13 }],
}
const chartEvent: MeshChartEvent = {
  event_id: 1,
  timestamp: chartPoint.timestamp,
  event_type: 'ACTIVE_SWITCH',
  local_radio: 1,
  from_peer_mac: 'peer-0',
  to_peer_mac: 'peer-1',
  from_ap_name: 'AP-0',
  to_ap_name: 'AP-1',
  segment_sequence: 2,
  duration_ms: 1_000,
}
const chartPointAfterGap: MeshChartPoint = {
  ...chartPoint,
  link_id: 3,
  timestamp: '2026-07-20T10:00:10.123Z',
  gap_before: true,
}

describe('MESH charts mount and render', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 900 })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 430 })
  })

  it('mounts active charts, renders real series and disposes ECharts', async () => {
    const wrappers = [
      mount(MeshSwitchRssiChart, { props: { events: [{ event_id: 1, timestamp: '2026-07-20T10:00:00.123Z', event_type: 'switch', mr_name: 'MR-1', local_radio: 1, from_peer_mac: null, to_peer_mac: null, from_ap_name: 'AP-1', to_ap_name: 'AP-2', before_rssi: -40, after_rssi: -45, duration_ms: null, is_short_link: false, is_pingpong: false, station: null, section: null, warning: null }] } }),
      mount(MeshRssiChart, { props: { points: [chartPoint, chartPointAfterGap], events: [chartEvent], locationSegments: [{ start_time: chartPoint.timestamp, end_time: chartPointAfterGap.timestamp, station: '站点一', section: '区间一', label: '站点一 / 区间一' }], focusTimestamp: chartPointAfterGap.timestamp } }),
      mount(MeshChannelBusyChart, { props: { points: [chartPoint], events: [chartEvent], locationSegments: [{ start_time: chartPoint.timestamp, end_time: chartPoint.timestamp, station: '站点一', section: '区间一', label: '站点一 / 区间一' }] } }),
    ]
    await flushPromises()

    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(3)
    const options = echartsMock.chart.setOption.mock.calls.map(([option]) => option as { series: Array<{ name: string; type: string }> })
    expect(options[0].series.every((item) => item.type === 'scatter')).toBe(true)
    expect(options[1].series.map((item) => item.name)).toEqual(['当前 ACTIVE MR 侧 RSSI'])
    expect(options[2].series.map((item) => item.name)).toEqual(['当前 ACTIVE MR 侧 TxBusy', '当前 ACTIVE MR 侧 RxBusy'])
    expect((echartsMock.chart.setOption.mock.calls[1][0] as { series: Array<{ markLine?: { silent: boolean }; markArea?: unknown }> }).series[0].markLine).toBeUndefined()
    expect((echartsMock.chart.setOption.mock.calls[1][0] as { series: Array<{ markArea?: unknown }> }).series[0].markArea).toBeDefined()

    const rssiOption = echartsMock.chart.setOption.mock.calls[1][0] as { dataZoom: unknown[]; toolbox: { feature: { saveAsImage: unknown } }; tooltip: { formatter: (params: unknown) => string } }
    expect(rssiOption.dataZoom).toHaveLength(2)
    expect(rssiOption.toolbox.feature.saveAsImage).toBeDefined()
    expect(rssiOption.tooltip.formatter([{ data: { meta: chartPoint } }])).toContain('备份链路：')
    expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith({ type: 'showTip', seriesIndex: 0, dataIndex: 2 })
    const rssiClick = echartsMock.chart.on.mock.calls[0][1] as (payload: unknown) => void
    rssiClick({ data: { meshEvent: chartEvent } })
    expect(wrappers[1].emitted('selectSwitch')?.[0]).toEqual([chartEvent])

    wrappers.forEach((wrapper) => wrapper.unmount())
    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(3)
    expect(echartsMock.chart.off).toHaveBeenCalledTimes(2)
  })

  it('waits for a visible active container before initializing ECharts', async () => {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 0 })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 0 })
    const wrapper = mount(MeshRssiChart, { props: { points: [chartPoint], active: false } })
    await flushPromises()
    expect(echartsMock.init).not.toHaveBeenCalled()

    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 900 })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 430 })
    await wrapper.setProps({ active: true })
    window.dispatchEvent(new Event('resize'))
    await vi.waitFor(() => expect(echartsMock.init).toHaveBeenCalledOnce())
    expect(echartsMock.chart.resize).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('renders formal switch points only at backend-provided coordinates', async () => {
    const event: MeshChartEvent = {
      ...chartEvent,
      point_timestamp: chartPoint.timestamp,
      point_rssi: -40,
      before_rssi: -40,
      after_rssi: -48,
    }
    const wrapper = mount(MeshRssiChart, { props: { points: [chartPoint], events: [event], showSwitchLines: true, showSwitchPoints: true } })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as { series: Array<{ name: string; data?: Array<{ value: [string, number]; symbol?: string }> ; markLine?: unknown }> }
    expect(option.series.map((item) => item.name)).toContain('切换节点')
    const nodes = option.series.find((item) => item.name === '切换节点')!
    expect(nodes.data?.[0]?.value).toEqual([chartPoint.timestamp, -40])
    expect(nodes.data?.[0]?.symbol).toBe('emptyCircle')
    expect(option.series[0].markLine).toBeDefined()
    expect(nodes.data?.[0]?.value[1]).not.toBe(0)
    wrapper.unmount()
  })
})
