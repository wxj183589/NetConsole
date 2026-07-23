// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MeshChannelBusyChart from './MeshChannelBusyChart.vue'
import MeshRssiChart from './MeshRssiChart.vue'
import MeshTracksideSignalChart from './MeshTracksideSignalChart.vue'
import MeshSwitchRssiChart from './MeshSwitchRssiChart.vue'
import type { MeshChartEvent, MeshChartPoint, MeshTracksideSignalPointData, MeshTracksideSignalSeriesData } from '../../types/meshAnalysis'
import { buildTracksideSeriesCache } from './tracksideSeriesCache'

const echartsMock = vi.hoisted(() => {
  const zrender = { on: vi.fn(), off: vi.fn() }
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    dispatchAction: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    convertToPixel: vi.fn(() => 320),
    getZr: vi.fn(() => zrender),
  }
  return { chart, zrender, init: vi.fn(() => chart), use: vi.fn() }
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
  peer_radio_mac: null,
  radio: 1,
  station: '站点一',
  section: '区间一',
  roles_present: ['ACTIVE'],
  data_source: 'peer_rssi_db',
  total_points: 1,
  returned_points: 1,
  points: [tracksideChartPoint],
}, {
  series_id: 'ap-2:radio:1',
  peer_name: 'AP-2',
  peer_mac: 'peer-2',
  ap_mac: 'ap-2',
  peer_radio_mac: null,
  radio: 1,
  station: '站点一',
  section: '区间一',
  roles_present: ['ACTIVE'],
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
    expect(options[1].series.map((item) => item.name)).toEqual(['当前 ACTIVE MR 侧 RSSI', '切换节点'])
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
    expect(echartsMock.chart.off).toHaveBeenCalledTimes(6)
  })

  it('renders the trackside link RSSI chart without default switch markers', async () => {
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
      series: Array<{ name: string; showSymbol?: boolean; connectNulls?: boolean; markLine?: unknown; data?: Array<[number, number | null, number, number]> }>
      tooltip: {
        formatter: (params: unknown) => string
        position: (
          point: [number, number],
          params: unknown,
          dom: HTMLElement,
          rect: unknown,
          size: { contentSize: [number, number]; viewSize: [number, number] },
        ) => [number, number]
      }
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
    expect(option.series[0].data?.[0]?.slice(0, 2)).toEqual([Date.parse(tracksideChartPoint.timestamp), -45])
    expect(option.series[1].data?.[0]?.slice(0, 2)).toEqual([Date.parse(tracksideSecondPoint.timestamp), -62])
    expect(option.legend.type).toBe('scroll')
    expect(option.toolbox.feature.dataZoom).toBeDefined()
    expect(option.toolbox.feature.restore).toBeDefined()
    expect(option.toolbox.feature.saveAsImage).toBeDefined()
    expect(option.tooltip.formatter([{ axisValue: tracksideChartPoint.timestamp }])).toContain('轨旁 / MR RSSI：-45 / -40 dBm')
    expect(option.tooltip.formatter([{ axisValue: tracksideChartPoint.timestamp }])).toContain('● ACTIVE　AP-1 · Radio 1')
    const dedupedTooltip = option.tooltip.formatter([
      { axisValue: tracksideChartPoint.timestamp },
      { axisValue: tracksideChartPoint.timestamp },
    ])
    expect(dedupedTooltip.split('AP-1 · Radio 1').length - 1).toBe(1)
    const tooltipElement = document.createElement('div')
    tooltipElement.className = 'mesh-trackside-signal-tooltip'
    document.body.append(tooltipElement)
    option.tooltip.formatter([{ axisValue: tracksideChartPoint.timestamp }])
    option.tooltip.position([100, 0], [], tooltipElement, null, {
      contentSize: [340, 300],
      viewSize: [900, 430],
    })
    const bubbledWheel = vi.fn()
    document.body.addEventListener('wheel', bubbledWheel)
    tooltipElement.dispatchEvent(new WheelEvent('wheel', { bubbles: true }))
    expect(bubbledWheel).not.toHaveBeenCalled()
    document.body.removeEventListener('wheel', bubbledWheel)
    tooltipElement.remove()
    const click = echartsMock.chart.on.mock.calls.find(([event]) => event === 'click')?.[1] as (payload: unknown) => void
    click({ seriesId: option.series[0].name, data: option.series[0].data?.[0] })
    expect(wrapper.emitted('selectSwitch')?.[0]).toEqual([chartEvent])
    const restore = echartsMock.chart.on.mock.calls.find(([event]) => event === 'restore')?.[1] as () => void
    restore()
    const restoredViewport = wrapper.emitted('viewport-change')?.at(-1)?.[0] as {
      start_time: string
      end_time: string
      source: string
    }
    expect(Date.parse(restoredViewport.start_time)).toBe(Date.parse(tracksideChartPoint.timestamp))
    expect(Date.parse(restoredViewport.end_time)).toBe(Date.parse(tracksideSecondPoint.timestamp))
    expect(restoredViewport.source).toBe('user_zoom')

    wrapper.unmount()
    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(1)
  })

  it('disposes chart, cache, pointer listeners, and resize listeners across ten session mounts', async () => {
    const addListener = vi.spyOn(window, 'addEventListener')
    const removeListener = vi.spyOn(window, 'removeEventListener')
    const caches = []
    for (let sessionIndex = 0; sessionIndex < 10; sessionIndex += 1) {
      const cache = buildTracksideSeriesCache(tracksideSeries.map((item) => ({
        ...item,
        series_id: `${item.series_id}:session-${sessionIndex}`,
        points: item.points.map((itemPoint) => ({
          ...itemPoint,
          sample_id: sessionIndex,
        })),
      })))
      caches.push(cache)
      const wrapper = mount(MeshTracksideSignalChart, { props: { seriesCache: cache } })
      await flushPromises()
      wrapper.unmount()
    }

    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(10)
    expect(echartsMock.zrender.on).toHaveBeenCalledTimes(10)
    expect(echartsMock.zrender.off).toHaveBeenCalledTimes(10)
    expect(addListener.mock.calls.filter(([event]) => event === 'resize')).toHaveLength(10)
    expect(removeListener.mock.calls.filter(([event]) => event === 'resize')).toHaveLength(10)
    expect(caches.every((cache) => cache.disposed && cache.pointMetaById.size === 0)).toBe(true)
  })

  it('keeps a trackside series connected when delayed samples still belong to the same link run', async () => {
    const nextPoint = {
      ...tracksideChartPoint,
      timestamp: '2026-07-20T10:00:30.123Z',
      peer_rssi: -41,
      local_rssi: -36,
      run_id: 'run-1',
      run_sequence: 1,
    }
    const firstPoint = { ...tracksideChartPoint, run_id: 'run-1', run_sequence: 1 }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{ ...tracksideSeries[0], points: [firstPoint, nextPoint] }],
        continuityGapSeconds: 5,
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: Array<[number, number | null, number, number]> }>
    }
    expect(option.series[0].data?.map((item) => item.slice(0, 2))).toEqual([
      [Date.parse(firstPoint.timestamp), -45],
      [Date.parse(nextPoint.timestamp), -41],
    ])

    wrapper.unmount()
  })

  it('breaks a trackside series when a repeated AP starts a new link run', async () => {
    const firstPoint = {
      ...tracksideChartPoint,
      run_id: 'run-1',
      run_sequence: 1,
    }
    const nextPoint = {
      ...tracksideChartPoint,
      link_id: 11,
      timestamp: '2026-07-20T10:00:02.123Z',
      peer_rssi: -41,
      local_rssi: -36,
      run_id: 'run-2',
      run_sequence: 2,
      break_before: true,
    }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{ ...tracksideSeries[0], points: [firstPoint, nextPoint] }],
        continuityGapSeconds: 5,
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: Array<[number, number | null, number, number]> }>
    }
    expect(option.series[0].data?.map((item) => item.slice(0, 2))).toEqual([
      [Date.parse(firstPoint.timestamp), -45],
      [Date.parse(nextPoint.timestamp), null],
      [Date.parse(nextPoint.timestamp), -41],
    ])

    wrapper.unmount()
  })

  it('does not insert repeated nulls when a point is flagged inside the same run', async () => {
    const firstPoint = { ...tracksideChartPoint, run_id: 'run-1', run_sequence: 1 }
    const middlePoint = {
      ...tracksideChartPoint,
      link_id: 12,
      timestamp: '2026-07-20T10:00:01.123Z',
      peer_rssi: -42,
      run_id: 'run-1',
      run_sequence: 1,
      break_before: true,
    }
    const lastPoint = {
      ...tracksideChartPoint,
      link_id: 13,
      timestamp: '2026-07-20T10:00:02.123Z',
      peer_rssi: -41,
      run_id: 'run-1',
      run_sequence: 1,
    }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{ ...tracksideSeries[0], points: [firstPoint, middlePoint, lastPoint] }],
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ connectNulls?: boolean; data?: Array<[number, number | null, number, number]> }>
    }
    expect(option.series[0].connectNulls).toBe(false)
    expect(option.series[0].data?.map((item) => item.slice(0, 2))).toEqual([
      [Date.parse(firstPoint.timestamp), -45],
      [Date.parse(middlePoint.timestamp), -42],
      [Date.parse(lastPoint.timestamp), -41],
    ])

    wrapper.unmount()
  })

  it('renders interleaved trackside AP inputs as independent continuous line series', async () => {
    const apA = [
      { ...tracksideChartPoint, timestamp: '2026-07-20T10:00:00.000Z', peer_rssi: -40, run_id: 'radio1-run-a', run_sequence: 1 },
      { ...tracksideChartPoint, timestamp: '2026-07-20T10:00:01.000Z', peer_rssi: -42, run_id: 'radio1-run-a', run_sequence: 1 },
      { ...tracksideChartPoint, timestamp: '2026-07-20T10:00:02.000Z', peer_rssi: -41, run_id: 'radio1-run-a', run_sequence: 1 },
    ]
    const apB = [
      { ...tracksideSecondPoint, timestamp: '2026-07-20T10:00:00.000Z', peer_rssi: -50, run_id: 'radio2-run-b', run_sequence: 2 },
      { ...tracksideSecondPoint, timestamp: '2026-07-20T10:00:01.000Z', peer_rssi: -52, run_id: 'radio2-run-b', run_sequence: 2 },
      { ...tracksideSecondPoint, timestamp: '2026-07-20T10:00:02.000Z', peer_rssi: -51, run_id: 'radio2-run-b', run_sequence: 2 },
    ]
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [
          { ...tracksideSeries[0], points: apA },
          { ...tracksideSeries[1], points: apB },
        ],
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ type?: string; data?: Array<[number, number | null, number, number]> }>
    }
    expect(option.series.every((item) => item.type === 'line')).toBe(true)
    expect(option.series[0].data?.map((item) => item.slice(0, 2))).toEqual([
      [Date.parse(apA[0].timestamp), -40],
      [Date.parse(apA[1].timestamp), -42],
      [Date.parse(apA[2].timestamp), -41],
    ])
    expect(option.series[1].data?.map((item) => item.slice(0, 2))).toEqual([
      [Date.parse(apB[0].timestamp), -50],
      [Date.parse(apB[1].timestamp), -52],
      [Date.parse(apB[2].timestamp), -51],
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
      series: Array<{ data?: Array<[number, number | null, number, number]> }>
    }
    expect(option.series[0].data?.[0]?.slice(0, 2)).toEqual([Date.parse(fallbackPoint.timestamp), -55])
    expect(option.series[0].data?.[0]?.[1]).not.toBe(-40)

    wrapper.unmount()
  })

  it('anchors one trackside switch node to the target ACTIVE peer signal fallback', async () => {
    const timestamp = '2026-07-20T10:00:00.181Z'
    const standby = {
      ...tracksideChartPoint,
      timestamp,
      role: 'STANDBY' as const,
      peer_mac: 'peer-standby',
      peer_ap_name: 'AP-STANDBY',
      peer_rssi: -20,
    }
    const active = {
      ...tracksideChartPoint,
      timestamp,
      role: 'ACTIVE' as const,
      peer_mac: 'peer-target',
      peer_ap_name: 'AP-TARGET',
      peer_ap_mac: 'ap-target',
      peer_rssi: null,
      peer_signal: -55,
      local_rssi: -40,
    }
    const event: MeshChartEvent = {
      ...chartEvent,
      timestamp: '2026-07-20T10:00:00.010Z',
      point_timestamp: '2026-07-20T10:00:00.100Z',
      render_point_timestamp: timestamp,
      render_aligned: true,
      to_peer_mac: active.peer_mac,
      to_ap_name: active.peer_ap_name,
      point_context: null,
    }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [
          { ...tracksideSeries[0], series_id: 'standby', peer_name: standby.peer_ap_name, peer_mac: standby.peer_mac, points: [standby] },
          { ...tracksideSeries[0], series_id: 'active', peer_name: active.peer_ap_name, peer_mac: active.peer_mac, points: [active] },
        ],
        events: [event, { ...event }],
        showSwitchLines: true,
        showSwitchPoints: true,
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{
        type: string
        markLine?: { data: Array<{ xAxis: string }> }
        data?: Array<{ value: [number, number, number] }>
      }>
    }
    expect(option.series[0].markLine?.data).toHaveLength(1)
    expect(option.series[0].markLine?.data[0].xAxis).toBe(timestamp)
    const scatter = option.series.find((item) => item.type === 'scatter')
    expect(scatter?.data).toHaveLength(1)
    expect(scatter?.data?.[0].value.slice(0, 2)).toEqual([Date.parse(timestamp), -55])
    expect(scatter?.data?.[0].value[1]).not.toBe(active.local_rssi)
    expect(scatter?.data?.[0].value[1]).not.toBe(standby.peer_rssi)
    const click = echartsMock.chart.on.mock.calls.find(([name]) => name === 'click')?.[1] as (payload: unknown) => void
    click({ seriesId: 'active', data: { eventIndex: 0 } })
    expect(wrapper.emitted('selectSwitch')?.[0]).toEqual([event])

    wrapper.unmount()
  })

  it('keeps ACTIVE and STANDBY role changes in one legend and one color', async () => {
    const points: MeshTracksideSignalPointData[] = [
      { ...tracksideChartPoint, timestamp: '2026-07-20T10:00:00.000Z', role: 'ACTIVE', run_id: 'link-run-1', run_sequence: 1 },
      { ...tracksideChartPoint, timestamp: '2026-07-20T10:00:01.000Z', role: 'STANDBY', run_id: 'link-run-1', run_sequence: 1 },
      { ...tracksideChartPoint, timestamp: '2026-07-20T10:00:02.000Z', role: 'ACTIVE', run_id: 'link-run-1', run_sequence: 1 },
    ]
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{
          ...tracksideSeries[0],
          roles_present: ['ACTIVE', 'STANDBY'],
          total_points: points.length,
          returned_points: points.length,
          points,
        }],
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{
        name: string
        type: string
        itemStyle: { color: string }
        symbol: (value: [number, number | null, number, number]) => string
        data: Array<[number, number | null, number, number]>
      }>
    }
    expect(option.series).toHaveLength(1)
    expect(option.series[0].name).toBe('AP-1 · Radio 1')
    expect(option.series[0].name).not.toMatch(/ACTIVE|STANDBY|MIXED/)
    expect(option.series[0].type).toBe('line')
    expect(option.series[0].itemStyle.color).toBeTruthy()
    expect(option.series[0].data.map((item) => item[1])).toEqual([-45, -45, -45])
    expect(option.series[0].data.map((item) => option.series[0].symbol(item))).toEqual(['circle', 'emptyCircle', 'circle'])
    expect(option.series[0].data.every((item) => item[1] !== null)).toBe(true)

    wrapper.unmount()
  })

  it('shows every ACTIVE and STANDBY link in one frame tooltip in role and AP order', async () => {
    const frameTime = '2026-07-20T10:05:00.000Z'
    const framePoints: MeshTracksideSignalPointData[] = [
      { ...tracksideChartPoint, timestamp: frameTime, peer_ap_name: 'AP-A', peer_mac: 'peer-a', peer_ap_mac: 'ap-a', peer_radio_mac: 'radio-a', role: 'ACTIVE' },
      { ...tracksideChartPoint, timestamp: frameTime, peer_ap_name: 'AP-D', peer_mac: 'peer-d', peer_ap_mac: 'ap-d', peer_radio_mac: 'radio-d', role: 'STANDBY' },
      { ...tracksideChartPoint, timestamp: frameTime, peer_ap_name: 'AP-B', peer_mac: 'peer-b', peer_ap_mac: 'ap-b', peer_radio_mac: 'radio-b', role: 'STANDBY' },
      { ...tracksideChartPoint, timestamp: frameTime, peer_ap_name: 'AP-C', peer_mac: 'peer-c', peer_ap_mac: 'ap-c', peer_radio_mac: 'radio-c', role: 'STANDBY' },
    ]
    const frameSeries: MeshTracksideSignalSeriesData[] = framePoints.map((point, index) => ({
      ...tracksideSeries[0],
      series_id: `frame-series-${index}`,
      peer_name: point.peer_ap_name,
      peer_mac: point.peer_mac,
      ap_mac: point.peer_ap_mac,
      peer_radio_mac: point.peer_radio_mac,
      roles_present: [point.role],
      points: [point],
    }))
    const wrapper = mount(MeshTracksideSignalChart, { props: { series: frameSeries } })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{
        name: string
        type: string
        markLine?: unknown
        data: Array<[number, number | null, number, number]>
      }>
      tooltip: {
        formatter: (params: unknown) => string
        position: (
          point: [number, number],
          params: unknown,
          dom: HTMLElement,
          rect: unknown,
          size: { contentSize: [number, number]; viewSize: [number, number] },
        ) => [number, number]
      }
    }
    expect(option.series).toHaveLength(4)
    expect(option.series.every((item) => item.type === 'line')).toBe(true)
    expect(option.series.every((item) => item.markLine === undefined)).toBe(true)
    expect(option.series.map((item) => item.name).join(' ')).not.toMatch(/ACTIVE|STANDBY|MIXED/)
    expect(option.series.flatMap((item) => item.data).every((item) => Array.isArray(item))).toBe(true)
    expect(JSON.stringify(option.series)).not.toContain('peer_ap_name')
    const tooltip = option.tooltip.formatter(option.series.map((item) => ({ axisValue: frameTime, data: item.data[0] })))
    expect(tooltip.match(/● ACTIVE/g)).toHaveLength(1)
    expect(tooltip.match(/○ STANDBY/g)).toHaveLength(3)
    expect(tooltip.indexOf('AP-A')).toBeLessThan(tooltip.indexOf('AP-B'))
    expect(tooltip.indexOf('AP-B')).toBeLessThan(tooltip.indexOf('AP-C'))
    expect(tooltip.indexOf('AP-C')).toBeLessThan(tooltip.indexOf('AP-D'))
    expect(tooltip).not.toContain('Peer Radio MAC：')

    wrapper.unmount()
  })

  it('keeps switch scatter and one markLine config enabled in large mode', async () => {
    const points: MeshTracksideSignalPointData[] = Array.from({ length: 5_000 }, (_, index) => ({
      ...tracksideChartPoint,
      link_id: index + 1,
      timestamp: new Date(Date.UTC(2026, 6, 20, 10, 0, 0, index)).toISOString(),
      role: index % 2 === 0 ? 'ACTIVE' : 'STANDBY',
      run_id: 'large-link-run',
      run_sequence: 1,
    }))
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: [{
          ...tracksideSeries[0],
          roles_present: ['ACTIVE', 'STANDBY'],
          total_points: points.length,
          returned_points: points.length,
          points,
        }],
        events: [{ ...chartEvent, render_point_timestamp: points[0].timestamp, render_aligned: true }],
        showSwitchLines: true,
        showSwitchPoints: true,
      },
    })
    await flushPromises()

    const option = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ type: string; showSymbol: boolean; markLine?: unknown; data: unknown[] }>
    }
    expect(option.series).toHaveLength(2)
    expect(option.series[0].type).toBe('line')
    expect(option.series[0].showSymbol).toBe(false)
    expect(option.series[0].markLine).toBeDefined()
    expect(option.series[0].data).toHaveLength(5_000)
    expect(option.series.filter((item) => item.type === 'scatter')).toHaveLength(1)

    wrapper.unmount()
  })

  it('uses one scatter overlay and one markLine config for 481 series and 708 events', async () => {
    const baseMillis = Date.parse('2026-07-20T10:00:00.000Z')
    const seriesCount = 481
    const extraPointSeries = 334
    const largeSeries = Array.from({ length: seriesCount }, (_, seriesIndex) => {
      const pointCount = 15 + (seriesIndex < extraPointSeries ? 1 : 0)
      const peerMac = `peer-${seriesIndex}`
      const peerName = `AP-${seriesIndex}`
      const role = seriesIndex === 0 ? 'ACTIVE' as const : 'STANDBY' as const
      const points = Array.from({ length: pointCount }, (_, pointIndex) => ({
        ...tracksideChartPoint,
        link_id: seriesIndex * 100 + pointIndex,
        timestamp: new Date(baseMillis + pointIndex).toISOString(),
        role,
        peer_mac: peerMac,
        peer_ap_name: peerName,
        peer_ap_mac: `ap-${seriesIndex}`,
        peer_rssi: -40 - seriesIndex % 20,
        run_id: `run-${seriesIndex}`,
        run_sequence: seriesIndex + 1,
      }))
      return {
        ...tracksideSeries[0],
        series_id: `series-${seriesIndex}`,
        peer_name: peerName,
        peer_mac: peerMac,
        ap_mac: `ap-${seriesIndex}`,
        roles_present: [role],
        total_points: pointCount,
        returned_points: pointCount,
        points,
      }
    })
    const events = Array.from({ length: 708 }, (_, eventIndex): MeshChartEvent => ({
      ...chartEvent,
      event_id: eventIndex + 1,
      timestamp: new Date(baseMillis + eventIndex).toISOString(),
      render_point_timestamp: new Date(baseMillis + eventIndex).toISOString(),
      render_aligned: true,
      from_peer_mac: `from-${eventIndex}`,
      to_peer_mac: 'peer-0',
      to_ap_name: 'AP-0',
      point_context: null,
    }))
    expect(largeSeries.reduce((sum, item) => sum + item.points.length, 0)).toBe(7_549)

    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: largeSeries,
        events,
        showSwitchLines: false,
        showSwitchPoints: false,
      },
    })
    await flushPromises()

    const initialOption = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{
        type: string
        data?: unknown[]
      }>
    }
    expect(initialOption.series.filter((item) => item.type === 'line')).toHaveLength(481)
    expect(initialOption.series.filter((item) => item.type === 'scatter')).toHaveLength(0)
    const businessData = initialOption.series.map((item) => item.data)
    const beforeOverlaySetOptionCount = echartsMock.chart.setOption.mock.calls.length
    const overlayStarted = performance.now()
    await wrapper.setProps({ showSwitchLines: true, showSwitchPoints: true })
    await flushPromises()
    const overlayUpdateMs = performance.now() - overlayStarted
    console.info(`trackside overlay profile: ${overlayUpdateMs.toFixed(3)}ms`)
    expect(overlayUpdateMs).toBeLessThan(50)
    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(beforeOverlaySetOptionCount + 1)
    const openedOverlay = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ id?: string; type?: string; data?: unknown[]; markLine?: { data: unknown[] } }>
    }
    expect(openedOverlay.series.filter((item) => item.type === 'scatter')).toHaveLength(1)
    expect(openedOverlay.series[0].data).toBeUndefined()
    expect(openedOverlay.series[0].markLine?.data).toHaveLength(708)
    expect(openedOverlay.series.find((item) => item.id === 'trackside-switch-nodes')?.data).toHaveLength(16)
    expect(initialOption.series.every((item, index) => item.data === businessData[index])).toBe(true)

    await wrapper.setProps({ showSwitchLines: false, showSwitchPoints: false })
    await flushPromises()
    const closedOverlay = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ id?: string; data?: unknown[]; markLine?: { data: unknown[] } }>
    }
    expect(closedOverlay.series[0].data).toBeUndefined()
    expect(closedOverlay.series[0].markLine?.data).toEqual([])
    expect(closedOverlay.series.find((item) => item.id === 'trackside-switch-nodes')?.data).toEqual([])

    wrapper.unmount()
  })

  it('updates the shared absolute viewport without rebuilding trackside series data', async () => {
    const sharedTimeDomain = {
      full_start_time: '2026-07-20T09:00:00.000Z',
      full_end_time: '2026-07-20T12:00:00.000Z',
    }
    const wrapper = mount(MeshTracksideSignalChart, {
      props: {
        series: tracksideSeries,
        sharedTimeDomain,
      },
    })
    await flushPromises()

    const initialSetOptionCount = echartsMock.chart.setOption.mock.calls.length
    const initialData = (echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: unknown[] }>
    }).series[0].data
    const dataZoom = echartsMock.chart.on.mock.calls.find(([event]) => event === 'datazoom')?.[1] as (payload: unknown) => void
    dataZoom({
      startValue: '2026-07-20T10:00:00.500Z',
      endValue: '2026-07-20T10:00:03.500Z',
    })
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))

    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(initialSetOptionCount)
    expect(wrapper.emitted('viewport-change')).toHaveLength(1)
    expect(wrapper.emitted('viewport-change')?.[0]?.[0]).toMatchObject({
      start_time: '2026-07-20T10:00:00.500Z',
      end_time: '2026-07-20T10:00:03.500Z',
      ...sharedTimeDomain,
      source_chart: 'trackside-rssi',
    })
    dataZoom({
      startValue: '2026-07-20T10:00:00.500Z',
      endValue: '2026-07-20T10:00:00.600Z',
    })
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    const correctedViewport = wrapper.emitted('viewport-change')?.at(-1)?.[0] as {
      start_time: string
      end_time: string
    }
    expect(Date.parse(correctedViewport.end_time) - Date.parse(correctedViewport.start_time)).toBe(1_000)
    expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'dataZoom' }),
      { silent: true },
    )

    await wrapper.setProps({
      syncViewport: {
        start_time: '2026-07-20T10:00:01.500Z',
        end_time: '2026-07-20T10:00:02.500Z',
        start_percent: 0,
        end_percent: 100,
        ...sharedTimeDomain,
        source: 'programmatic',
        source_chart: 'active-rssi',
        revision: 9,
      },
    })
    await flushPromises()
    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(initialSetOptionCount)
    expect(echartsMock.chart.dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'dataZoom' }),
      { silent: true },
    )
    expect(initialData).toBe((echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: unknown[] }>
    }).series[0].data)

    await wrapper.setProps({ showLocationBand: false })
    await flushPromises()
    const displayOption = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ id?: string; data?: unknown[] }>
    }
    expect(displayOption.series.find((item) => item.id === tracksideSeries[0].series_id)?.data).toBeUndefined()

    window.dispatchEvent(new CustomEvent('netconsole:theme-change'))
    await flushPromises()
    const themeOption = echartsMock.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data?: unknown[] }>
    }
    expect(themeOption.series.every((item) => item.data === undefined)).toBe(true)

    const axisPointer = echartsMock.chart.on.mock.calls.find(([event]) => event === 'updateAxisPointer')?.[1] as (payload: unknown) => void
    axisPointer({ axesInfo: [{ value: '2026-07-20T10:00:02.500Z' }] })
    expect(wrapper.emitted('pointer-change')?.at(-1)?.[0]).toEqual({
      time: '2026-07-20T10:00:02.500Z',
      source_chart: 'trackside-rssi',
    })
    await wrapper.setProps({ syncPointerTime: '2026-07-20T10:00:02.500Z' })
    await flushPromises()
    expect(echartsMock.chart.dispatchAction).toHaveBeenLastCalledWith(
      { type: 'updateAxisPointer', x: 320, y: 1 },
      { silent: true },
    )
    await wrapper.setProps({ syncPointerTime: null })
    await flushPromises()
    expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith(
      { type: 'updateAxisPointer', currTrigger: 'leave' },
      { silent: true },
    )
    expect(echartsMock.chart.dispatchAction).toHaveBeenLastCalledWith(
      { type: 'hideTip' },
      { silent: true },
    )
    expect(wrapper.emitted('viewport-change')).toHaveLength(2)
    wrapper.unmount()
  })

  it('silently corrects a main RSSI dataZoom before emitting one shared 1-second viewport', async () => {
    const sharedTimeDomain = {
      full_start_time: '2026-07-20T09:00:00.000Z',
      full_end_time: '2026-07-20T12:00:00.000Z',
    }
    const wrapper = mount(MeshRssiChart, {
      props: {
        points: [chartPoint, chartPointAfterGap],
        sharedTimeDomain,
      },
    })
    await flushPromises()
    echartsMock.chart.dispatchAction.mockClear()
    const dataZoom = echartsMock.chart.on.mock.calls.find(([event]) => event === 'datazoom')?.[1] as (payload: unknown) => void
    dataZoom({
      startValue: '2026-07-20T10:00:00.500Z',
      endValue: '2026-07-20T10:00:00.600Z',
    })
    expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'dataZoom' }),
      { silent: true },
    )
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))

    const emitted = wrapper.emitted('viewport-change')?.[0]?.[0] as {
      start_time: string
      end_time: string
    }
    expect(Date.parse(emitted.end_time) - Date.parse(emitted.start_time)).toBe(1_000)
    expect(wrapper.emitted('viewport-change')).toHaveLength(1)
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

    expect(echartsMock.chart.dispatchAction.mock.calls.some(([action]) => action.type === 'dataZoom')).toBe(false)
    expect((wrapper.vm as unknown as { getVisibleTimeRange: () => { start_time: string; end_time: string } }).getVisibleTimeRange()).toMatchObject({
      start_time: points[1].timestamp,
      end_time: points[2].timestamp,
    })

    echartsMock.chart.dispatchAction.mockClear()
    window.dispatchEvent(new CustomEvent('netconsole:theme-change'))
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(echartsMock.chart.dispatchAction.mock.calls.some(([action]) => action.type === 'dataZoom')).toBe(false)
    expect((wrapper.vm as unknown as { getVisibleTimeRange: () => { start_time: string; end_time: string } }).getVisibleTimeRange()).toMatchObject({
      start_time: points[1].timestamp,
      end_time: points[2].timestamp,
    })
    wrapper.unmount()
  })
})
