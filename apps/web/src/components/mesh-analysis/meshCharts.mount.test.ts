// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MeshChannelBusyChart from './MeshChannelBusyChart.vue'
import MeshRssiChart from './MeshRssiChart.vue'
import MeshTracksideSignalChart from './MeshTracksideSignalChart.vue'
import MeshSwitchRssiChart from './MeshSwitchRssiChart.vue'
import type { MeshChartEvent, MeshChartPoint, MeshTracksideSignalPointData, MeshTracksideSignalSeriesData } from '../../types/meshAnalysis'

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
  render_busy_point_timestamp: chartPoint.timestamp,
  render_busy_point_index: 0,
  render_busy_tx_busy: chartPoint.local_tx_busy,
  render_busy_rx_busy: chartPoint.local_rx_busy,
  render_busy_aligned: true,
  busy_point_context: chartPoint,
}
const chartPointAfterGap: MeshChartPoint = {
  ...chartPoint,
  link_id: 3,
  timestamp: '2026-07-20T10:00:10.123Z',
  gap_before: true,
}
const tracksideChartPoint: MeshTracksideSignalPointData = {
  timestamp: chartPoint.timestamp,
  timestamp_tag: chartPoint.timestamp_tag || '',
  source_file_id: 1,
  link_id: 1,
  sample_id: 1,
  local_radio: 1,
  role: 'ACTIVE',
  peer_mac: 'peer-1',
  peer_ap_name: 'AP-1',
  peer_ap_mac: 'ap-1',
  peer_radio: 'Radio 1',
  peer_radio_mac: null,
  station: '站点一',
  section: '区间一',
  peer_rssi: -45,
  local_rssi: -40,
  peer_signal: -55,
  local_signal: -50,
  segment_duration_seconds: 1_000,
  data_source: 'peer_rssi_db',
}
const tracksideSecondPoint: MeshTracksideSignalPointData = {
  ...tracksideChartPoint,
  timestamp: chartPointAfterGap.timestamp,
  timestamp_tag: chartPointAfterGap.timestamp_tag || '',
  role: 'ACTIVE',
  peer_mac: 'peer-2',
  peer_ap_name: 'AP-2',
  peer_ap_mac: 'ap-2',
  peer_rssi: -62,
  local_rssi: -60,
}
const tracksideSeries: MeshTracksideSignalSeriesData[] = [{
  series_id: 'ap-1:radio:1',
  peer_name: 'AP-1',
  peer_mac: 'peer-1',
  ap_mac: 'ap-1',
  radio: 1,
  station: '站点一',
  section: '区间一',
  role: 'ACTIVE',
  data_source: 'peer_rssi_db',
  total_points: 1,
  returned_points: 1,
  points: [tracksideChartPoint],
}, {
  series_id: 'ap-2:radio:1',
  peer_name: 'AP-2',
  peer_mac: 'peer-2',
  ap_mac: 'ap-2',
  radio: 1,
  station: '站点一',
  section: '区间一',
  role: 'ACTIVE',
  data_source: 'peer_rssi_db',
  total_points: 1,
  returned_points: 1,
  points: [tracksideSecondPoint],
}]

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
    expect((echartsMock.chart.setOption.mock.calls[2][0] as { series: Array<{ markLine?: { silent: boolean }; markArea?: unknown }> }).series[0].markLine).toBeUndefined()
    expect((echartsMock.chart.setOption.mock.calls[2][0] as { series: Array<{ name: string }> }).series.map((item) => item.name)).not.toContain('切换节点')
    expect((echartsMock.chart.setOption.mock.calls[1][0] as { series: Array<{ markArea?: unknown }> }).series[0].markArea).toBeDefined()

    const rssiOption = echartsMock.chart.setOption.mock.calls[1][0] as { dataZoom: unknown[]; toolbox: { feature: { saveAsImage: unknown } }; tooltip: { formatter: (params: unknown) => string } }
    expect(rssiOption.dataZoom).toHaveLength(2)
    expect(rssiOption.toolbox.feature.saveAsImage).toBeDefined()
    const tooltipHtml = rssiOption.tooltip.formatter([{ data: { meta: chartPoint } }, { data: { meta: chartPoint, meshEvent: chartEvent } }])
    expect(tooltipHtml).toContain('<strong>备份链路</strong>')
    expect(tooltipHtml).toContain('MR / 轨旁 AP 接收信号：-40 / -45')
    expect(tooltipHtml).toContain('MR / 轨旁 AP 接收信号：-60 / -62')
    expect(tooltipHtml).not.toContain('MR / 轨旁 AP 接收信号：-50 / -55')
    expect(tooltipHtml).not.toContain('切换耗时')
    expect(tooltipHtml).not.toContain('切换类型')
    expect(tooltipHtml.match(/class="mesh-rssi-tooltip"/g)).toHaveLength(1)
    const switchOption = echartsMock.chart.setOption.mock.calls[0][0] as { tooltip: { formatter: (params: unknown) => string } }
    const switchTooltip = switchOption.tooltip.formatter({ seriesName: '切换前', data: { value: [chartPoint.timestamp, -40], meta: chartEvent } })
    expect(switchTooltip).not.toContain('ACTIVE_SWITCH')
    expect(switchTooltip).not.toContain('事件：')
    expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith({ type: 'showTip', seriesIndex: 0, dataIndex: 2 })
    const rssiClick = echartsMock.chart.on.mock.calls[0][1] as (payload: unknown) => void
    rssiClick({ data: { meshEvent: chartEvent } })
    expect(wrappers[1].emitted('selectSwitch')?.[0]).toEqual([chartEvent])

    wrappers.forEach((wrapper) => wrapper.unmount())
    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(3)
    expect(echartsMock.chart.off).toHaveBeenCalledTimes(4)
  })

  it('renders the trackside signal chart as active peer RSSI lines without default switch markers', async () => {
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: tracksideSeries,
        events: [chartEvent],
        locationSegments: [{ start_time: chartPoint.timestamp, end_time: chartPointAfterGap.timestamp, station: '站点一', section: '区间一', label: '站点一 / 区间一' }],
        continuityGapSeconds: 5,
      },
    })
    await flushPromises()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      legend: { type?: string }
      series: Array<{ name: string; showSymbol?: boolean; connectNulls?: boolean; markLine?: unknown; data?: Array<{ value: [string, number | null]; meta?: MeshTracksideSignalPointData; meshEvent?: MeshChartEvent }> }>
      tooltip: { formatter: (params: unknown) => string }
      toolbox: { feature: { dataZoom?: unknown; restore?: unknown; saveAsImage?: unknown } }
    }
    expect(option.series.map((item) => item.name)).toEqual([
      'AP-1 · Radio 1',
      'AP-2 · Radio 1',
    ])
    expect(option.series.map((item) => item.name)).not.toContain('切换节点')
    expect(option.series[0].markLine).toBeUndefined()
    expect(option.series[0].connectNulls).toBe(false)
    expect(option.series[0].showSymbol).toBe(true)
    expect(option.series[0].data?.[0]?.value).toEqual([tracksideChartPoint.timestamp, -45])
    expect(option.series[1].data?.[0]?.value).toEqual([tracksideSecondPoint.timestamp, -62])
    expect(option.legend.type).toBe('scroll')
    expect(option.toolbox.feature.dataZoom).toBeDefined()
    expect(option.toolbox.feature.restore).toBeDefined()
    expect(option.toolbox.feature.saveAsImage).toBeDefined()
    expect(option.tooltip.formatter([{ data: { value: [tracksideChartPoint.timestamp, -45], meta: tracksideChartPoint, seriesMeta: tracksideSeries[0] } }])).toContain('轨旁侧 RSSI：-45')
    expect(option.tooltip.formatter([{ data: { value: [tracksideChartPoint.timestamp, -45], meta: tracksideChartPoint, seriesMeta: tracksideSeries[0] } }])).toContain('链路状态：ACTIVE')
    const dedupedTooltip = option.tooltip.formatter([
      { data: { value: [tracksideChartPoint.timestamp, -45], meta: tracksideChartPoint, seriesMeta: tracksideSeries[0] } },
      { data: { value: [tracksideChartPoint.timestamp, -45], meta: tracksideChartPoint, seriesMeta: tracksideSeries[0], meshEvent: chartEvent } },
    ])
    expect(dedupedTooltip.split('AP-1 · Radio 1').length - 1).toBe(1)
    const click = echartsMock.chart.on.mock.calls.find(([event]) => event === 'click')?.[1] as (payload: unknown) => void
    click({ data: { meshEvent: chartEvent, meta: tracksideChartPoint } })
    expect(wrapper.emitted('selectSwitch')?.[0]).toEqual([chartEvent])
    const restore = echartsMock.chart.on.mock.calls.find(([event]) => event === 'restore')?.[1] as () => void
    restore()
    expect(wrapper.emitted('viewport-change')?.at(-1)?.[0]).toMatchObject({
      start_time: tracksideChartPoint.timestamp,
      end_time: tracksideSecondPoint.timestamp,
      source: 'user_zoom',
    })

    wrapper.unmount()
    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(1)
  })

  it('breaks a trackside series after a long time gap instead of bridging the same AP', async () => {
    const nextPoint = {
      ...tracksideChartPoint,
      timestamp: '2026-07-20T10:00:30.123Z',
      peer_rssi: -41,
      local_rssi: -36,
    }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{ ...tracksideSeries[0], points: [tracksideChartPoint, nextPoint] }],
        continuityGapSeconds: 5,
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: Array<{ value: [string, number | null] }> }>
    }
    expect(option.series[0].data?.map((item) => item.value)).toEqual([
      [tracksideChartPoint.timestamp, -45],
      [nextPoint.timestamp, null],
      [nextPoint.timestamp, -41],
    ])

    wrapper.unmount()
  })

  it('breaks a trackside series when a repeated AP starts a new ACTIVE run', async () => {
    const nextPoint = {
      ...tracksideChartPoint,
      link_id: 11,
      timestamp: '2026-07-20T10:00:02.123Z',
      peer_rssi: -41,
      local_rssi: -36,
      break_before: true,
    }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{ ...tracksideSeries[0], points: [tracksideChartPoint, nextPoint] }],
        continuityGapSeconds: 5,
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: Array<{ value: [string, number | null] }> }>
    }
    expect(option.series[0].data?.map((item) => item.value)).toEqual([
      [tracksideChartPoint.timestamp, -45],
      [nextPoint.timestamp, null],
      [nextPoint.timestamp, -41],
    ])

    wrapper.unmount()
  })

  it('renders trackside peer signal fallback without using local RSSI', async () => {
    const fallbackPoint = { ...tracksideChartPoint, peer_rssi: null, peer_signal: -55, local_rssi: -40, data_source: 'peer_signal_dbm' }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{ ...tracksideSeries[0], data_source: 'peer_signal_dbm', points: [fallbackPoint] }],
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: Array<{ value: [string, number | null] }> }>
    }
    expect(option.series[0].data?.[0]?.value).toEqual([fallbackPoint.timestamp, -55])
    expect(option.series[0].data?.[0]?.value[1]).not.toBe(-40)

    wrapper.unmount()
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

  it('anchors switch points to the rendered line point instead of event RSSI coordinates', async () => {
    const event: MeshChartEvent = {
      ...chartEvent,
      point_timestamp: chartPointAfterGap.timestamp,
      point_rssi: 0,
      point_context: chartPoint,
      render_point_timestamp: chartPoint.timestamp,
      render_point_rssi: -40,
      render_aligned: true,
      before_rssi: -40,
      after_rssi: -48,
    }
    const wrapper = mount(MeshRssiChart, { props: { points: [chartPoint], events: [event], showSwitchLines: true, showSwitchPoints: true } })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as { tooltip: { formatter: (params: unknown) => string }; series: Array<{ name: string; data?: Array<{ value: [string, number]; symbol?: string; meta?: MeshChartPoint; meshEvent?: MeshChartEvent }> ; markLine?: unknown }> }
    expect(option.series.map((item) => item.name)).toContain('切换节点')
    const nodes = option.series.find((item) => item.name === '切换节点')!
    expect(nodes.data?.[0]?.value).toEqual([chartPoint.timestamp, -40])
    expect(nodes.data?.[0]?.meta).toEqual(chartPoint)
    expect(nodes.data?.[0]?.symbol).toBe('emptyCircle')
    expect(option.series[0].markLine).toBeDefined()
    expect(nodes.data?.[0]?.value[1]).not.toBe(0)
    const tooltip = option.tooltip.formatter([{ data: nodes.data?.[0] }])
    expect(tooltip).toContain('<strong>主链路</strong>')
    expect(tooltip).toContain('<strong>备份链路</strong>')
    expect(tooltip).toContain('<strong>切换事件</strong>')
    wrapper.unmount()
  })

  it('draws channel busy switch lines and anchors switch nodes to returned Busy samples', async () => {
    const event: MeshChartEvent = {
      ...chartEvent,
      render_busy_point_timestamp: chartPoint.timestamp,
      render_busy_tx_busy: 20,
      render_busy_rx_busy: 25,
      render_busy_aligned: true,
      busy_point_context: chartPoint,
      point_timestamp: '2026-07-20T10:00:01.123Z',
      point_rssi: -99,
      render_point_timestamp: '2026-07-20T10:00:01.123Z',
      render_point_rssi: -99,
      render_aligned: true,
    }
    const wrapper = mount(MeshChannelBusyChart, { props: { points: [chartPoint], events: [event], showPeer: true, showSwitchLines: true, showSwitchPoints: true } })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as { tooltip: { formatter: (params: unknown) => string }; series: Array<{ name: string; data?: Array<{ value: [string, number]; meta?: MeshChartPoint; meshEvent?: MeshChartEvent }> ; markLine?: unknown }> }
    expect(option.series.map((item) => item.name)).toEqual([
      '当前 ACTIVE MR 侧 TxBusy',
      '当前 ACTIVE MR 侧 RxBusy',
      '当前 ACTIVE Peer 侧 TxBusy',
      '当前 ACTIVE Peer 侧 RxBusy',
      '切换节点',
    ])
    expect(option.series[0].markLine).toBeDefined()
    const nodes = option.series.find((item) => item.name === '切换节点')!
    expect(nodes.data).toHaveLength(1)
    expect(nodes.data?.[0]?.value).toEqual([chartPoint.timestamp, chartPoint.local_tx_busy])
    expect(nodes.data?.[0]?.meta).toEqual(chartPoint)
    expect(nodes.data?.[0]?.value[1]).not.toBe(-99)
    const tooltip = option.tooltip.formatter([{ data: nodes.data?.[0] }])
    expect(tooltip).toContain('<strong>切换事件</strong>')
    expect(tooltip).toContain('对齐空口采样时间')
    expect(tooltip).not.toContain('切换耗时')
    expect(tooltip).not.toContain('切换类型')
    wrapper.unmount()
  })

  it('preserves channel busy viewport when toggling switch presentation options', async () => {
    const points = [0, 1, 2, 3].map((index) => ({
      ...chartPoint,
      link_id: index + 1,
      timestamp: `2026-07-20T10:0${index}:00.123Z`,
    }))
    const wrapper = mount(MeshChannelBusyChart, { props: { points } })
    await flushPromises()
    const dataZoomHandler = echartsMock.chart.on.mock.calls.find(([event]) => event === 'datazoom')?.[1] as (payload: unknown) => void
    dataZoomHandler({ startValue: points[1].timestamp, endValue: points[2].timestamp })
    echartsMock.chart.dispatchAction.mockClear()

    await wrapper.setProps({ showSwitchLines: true, showSwitchPoints: true, showPeer: true })
    await flushPromises()

    expect(echartsMock.chart.dispatchAction).toHaveBeenLastCalledWith({
      type: 'dataZoom',
      batch: [0, 1].map((dataZoomIndex) => ({
        dataZoomIndex,
        startValue: points[1].timestamp,
        endValue: points[2].timestamp,
      })),
    })
    expect((wrapper.vm as unknown as { getVisibleTimeRange: () => { start_time: string; end_time: string } }).getVisibleTimeRange()).toMatchObject({
      start_time: points[1].timestamp,
      end_time: points[2].timestamp,
    })
    wrapper.unmount()
  })

  it('does not render unaligned, missing or zero RSSI switch nodes', async () => {
    const zeroPoint = { ...chartPoint, local_rssi: 0 }
    const events: MeshChartEvent[] = [
      { ...chartEvent, render_aligned: false, point_context: chartPoint, point_timestamp: chartPoint.timestamp, point_rssi: -40 },
      { ...chartEvent, event_id: 2, render_aligned: true, render_point_timestamp: zeroPoint.timestamp, render_point_rssi: 0, point_context: zeroPoint },
    ]
    const wrapper = mount(MeshRssiChart, { props: { points: [zeroPoint], events, showSwitchPoints: true } })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as { series: Array<{ name: string }> }
    expect(option.series.map((item) => item.name)).not.toContain('切换节点')
    wrapper.unmount()
  })

  it('preserves the real time viewport when presentation options rerender RSSI', async () => {
    const points = [0, 1, 2, 3].map((index) => ({
      ...chartPoint,
      link_id: index + 1,
      timestamp: `2026-07-20T10:0${index}:00.123Z`,
    }))
    const wrapper = mount(MeshRssiChart, { props: { points } })
    await flushPromises()
    const dataZoomHandler = echartsMock.chart.on.mock.calls.find(([event]) => event === 'datazoom')?.[1] as (payload: unknown) => void
    dataZoomHandler({ startValue: points[1].timestamp, endValue: points[2].timestamp })
    echartsMock.chart.dispatchAction.mockClear()

    await wrapper.setProps({ showPeer: true, showSwitchLines: true, showLocationBand: false })
    await flushPromises()

    expect(echartsMock.chart.dispatchAction).toHaveBeenLastCalledWith({
      type: 'dataZoom',
      batch: [0, 1].map((dataZoomIndex) => ({
        dataZoomIndex,
        startValue: points[1].timestamp,
        endValue: points[2].timestamp,
      })),
    })
    expect((wrapper.vm as unknown as { getVisibleTimeRange: () => { start_time: string; end_time: string } }).getVisibleTimeRange()).toMatchObject({
      start_time: points[1].timestamp,
      end_time: points[2].timestamp,
    })

    echartsMock.chart.dispatchAction.mockClear()
    window.dispatchEvent(new CustomEvent('netconsole:theme-change'))
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(echartsMock.chart.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'dataZoom' }))
    expect((wrapper.vm as unknown as { getVisibleTimeRange: () => { start_time: string; end_time: string } }).getVisibleTimeRange()).toMatchObject({
      start_time: points[1].timestamp,
      end_time: points[2].timestamp,
    })
    wrapper.unmount()
  })
})
