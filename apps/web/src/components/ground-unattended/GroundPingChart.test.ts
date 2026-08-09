// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { GroundPingSeries } from '../../types/groundUnattended'

const mocks = vi.hoisted(() => ({
  disconnect: vi.fn(),
  dispose: vi.fn(),
  init: vi.fn(),
  dispatchAction: vi.fn(),
  off: vi.fn(),
  on: vi.fn(),
  resize: vi.fn(),
  setOption: vi.fn(),
  unsubscribe: vi.fn(),
  use: vi.fn(),
}))

vi.mock('echarts/core', () => ({ init: mocks.init, use: mocks.use }))
vi.mock('echarts/charts', () => ({ LineChart: {}, ScatterChart: {} }))
vi.mock('echarts/components', () => ({
  DataZoomComponent: {},
  GridComponent: {},
  LegendComponent: {},
  MarkLineComponent: {},
  MarkAreaComponent: {},
  TooltipComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('../../theme/echarts', () => ({
  readNetConsoleChartTokens: () => ({
    border: '#ddd',
    danger: '#c00',
    primary: '#06c',
    series: ['#06c', '#090'],
    textSecondary: '#666',
    warning: '#d80',
  }),
  subscribeNetConsoleChartTheme: () => mocks.unsubscribe,
}))

import GroundPingChart from './GroundPingChart.vue'

const series = {
  raw_sample_count: 1,
  effective_sample_count: 1,
  ignored_sample_count: 0,
  success_count: 1,
  loss_count: 0,
  rtt_sample_count: 1,
  rtt_sum_ms: 2,
  current_rtt_ms: 2,
  average_rtt_ms: 2,
  max_rtt_ms: 2,
  points: [{
    sample_id: 'sample-1',
    ts: '2026-07-28T08:00:00+08:00',
    target_ip: '192.0.2.10',
    train_id: 'train-1',
    train_no: '01',
    mr_id: 'mr-ct',
    mr_name: '列车01-MR-CT',
    mr_position_code: 'CT',
    seq: 1,
    ok: true,
    rtt_ms: 2,
    timeout_ms: 1_000,
    packet_size: 64,
    current_ap_identity: 'ap-1',
    current_ap_name: '站点A-AP01',
    current_ap_mac: '00:11:22:33:44:55',
    station: '站点A',
    section: '站点A-站点B',
    mileage: '',
    rssi: -50,
    ac_snapshot_id: 1,
    ac_received_at: '2026-07-28T08:00:00+08:00',
    position_quality: 'MATCHED',
    ap_transition_context: '',
    warmup_ignored: false,
    target_activation_started_at: '2026-07-28T07:59:00+08:00',
    archive_entry: '',
    data_source: 'ACTIVE',
  }],
  loss_windows: [],
  ap_transitions: [],
  position_segments: [],
  diagnostics: {
    request_id: 'request-1',
    requested_run_id: 'run-1',
    resolved_train_ids: ['train-1'],
    resolved_mr_ids: ['mr-ct'],
    resolved_start_time: '2026-07-28T07:00:00+08:00',
    resolved_end_time: '2026-07-28T23:00:00+08:00',
    source_kind: 'ACTIVE',
    data_availability: 'ACTIVE_RAW',
    raw_file_registry_hit_count: 1,
    files_considered: 1,
    files_scanned: 1,
    records_scanned: 1,
    matched_count: 1,
    bytes_scanned: 100,
    malformed_record_count: 0,
    duplicate_record_count: 0,
    truncated: false,
    legacy_archive: false,
    no_data_reason: '',
  },
  next_cursor: 'cursor-1',
  latest_sequence: 1,
  latest_timestamp: '2026-07-28T08:00:00+08:00',
  server_time: '2026-07-28T08:00:01+08:00',
  active: true,
  target_state: 'RUNNING',
  has_more: false,
  query_identity: 'gpq1.stable-target',
} satisfies GroundPingSeries

beforeEach(() => {
  vi.clearAllMocks()
  mocks.init.mockImplementation(() => ({
    dispose: mocks.dispose,
    dispatchAction: mocks.dispatchAction,
    off: mocks.off,
    on: mocks.on,
    resize: mocks.resize,
    setOption: mocks.setOption,
  }))
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() { mocks.disconnect() }
  })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ground Ping chart lifecycle', () => {
  it('does not register resources when unmounted before async imports resolve', async () => {
    const wrapper = mount(GroundPingChart, { props: { series } })
    wrapper.unmount()
    await flushPromises()

    expect(mocks.init).not.toHaveBeenCalled()
    expect(mocks.disconnect).not.toHaveBeenCalled()
    expect(mocks.unsubscribe).not.toHaveBeenCalled()
    window.dispatchEvent(new Event('resize'))
    expect(mocks.resize).not.toHaveBeenCalled()
  })

  it('initializes only while mounted, resizes after opening, and releases all resources', async () => {
    const wrapper = mount(GroundPingChart, { props: { series } })
    await flushPromises()

    expect(mocks.init).toHaveBeenCalledTimes(2)
    expect(mocks.setOption).toHaveBeenCalledTimes(2)
    expect(mocks.dispatchAction).toHaveBeenCalledTimes(2)
    expect(mocks.resize).toHaveBeenCalledTimes(2)

    window.dispatchEvent(new Event('resize'))
    expect(mocks.resize).toHaveBeenCalledTimes(4)

    wrapper.unmount()
    expect(mocks.disconnect).toHaveBeenCalledOnce()
    expect(mocks.unsubscribe).toHaveBeenCalledOnce()
    expect(mocks.dispose).toHaveBeenCalledTimes(2)

    const reopened = mount(GroundPingChart, { props: { series } })
    await flushPromises()
    expect(mocks.init).toHaveBeenCalledTimes(4)
    reopened.unmount()
    expect(mocks.dispose).toHaveBeenCalledTimes(4)
  })

  it('keeps dataZoom after initialization and reports user zoom without rebuilding charts', async () => {
    const wrapper = mount(GroundPingChart, { props: { series, followLatest: true } })
    await flushPromises()
    const initialOptions = mocks.setOption.mock.calls.map(([value]) => value)
    expect(initialOptions.every((value) => value.dataZoom)).toBe(true)
    const dataZoomHandler = mocks.on.mock.calls.find(([name]) => name === 'datazoom')?.[1] as (() => void)

    const updated = {
      ...series,
      points: [...series.points, { ...series.points[0], sample_id: 'sample-2', seq: 2, ts: '2026-07-28T08:00:01+08:00' }],
    }
    await wrapper.setProps({ series: updated })
    await flushPromises()

    expect(mocks.init).toHaveBeenCalledTimes(2)
    const incrementalOptions = mocks.setOption.mock.calls.slice(2).map(([value]) => value)
    expect(incrementalOptions.every((value) => value.dataZoom === undefined)).toBe(true)
    dataZoomHandler()
    expect(wrapper.emitted('user-zoom')).toHaveLength(1)
    wrapper.unmount()
  })

  it('keeps real flap events while aggregating dense markers in the chart layer', async () => {
    const transitions = [0, 1, 2].map((index) => ({
      event_id: `switch-${index}`,
      run_id: 'run-1',
      ts: `2026-07-28T08:00:00.${index + 1}00+08:00`,
      event_time: `2026-07-28T08:00:00.${index + 1}00+08:00`,
      event_type: 'MESH_ACTIVELINK_SWITCH',
      context: 'wmesh_active_link_switch',
      train_id: 'train-1',
      mr_id: 'mr-ct',
      mr_role: 'CT',
      management_ip: '192.0.2.10',
      old_ap_raw: index % 2 ? 'AP-B' : 'AP-A',
      new_ap_raw: index % 2 ? 'AP-A' : 'AP-B',
      source: 'MR Syslog / WMESH',
      source_type: 'SYSLOG',
    })) as GroundPingSeries['ap_transitions']
    const wrapper = mount(GroundPingChart, {
      props: { series: { ...series, ap_transitions: transitions } },
    })
    await flushPromises()

    const rttOptions = mocks.setOption.mock.calls[0]?.[0]
    const markLine = rttOptions.series[0].markLine
    expect(markLine.data).toHaveLength(1)
    expect(markLine.data[0].transitions).toHaveLength(3)
    expect(markLine.label.formatter({ data: markLine.data[0] })).toBe('AP 切换 ×3')
    const tooltip = rttOptions.tooltip.formatter({ data: markLine.data[0] })
    expect(tooltip).toContain('AP 主链路切换 ×3')
    expect(tooltip).toContain('AP-A → AP-B')
    wrapper.unmount()
  })

  it('shows the shared dual-endpoint identity evidence in switch tooltips', async () => {
    const transitions = [{
      event_id: 'switch-resolved',
      run_id: 'run-1',
      ts: '2026-07-28T08:00:00.100+08:00',
      event_time: '2026-07-28T08:00:00.100+08:00',
      event_type: 'MESH_ACTIVELINK_SWITCH',
      context: 'wmesh_active_link_switch',
      train_id: 'train-1',
      mr_id: 'mr-ct',
      mr_role: 'CT',
      management_ip: '192.0.2.10',
      old_ap_raw: 'bc5a-3457-5d00',
      new_ap_raw: 'bc5a-3457-5f60',
      old_ap_name: '象山贤庠-AP01',
      new_ap_name: '大徐站-AP02',
      old_ap_mac: 'bc:5a:34:57:5c:f0',
      new_ap_mac: 'bc:5a:34:57:5f:50',
      old_station: '象山贤庠',
      new_station: '大徐站',
      old_section: '象山贤庠-大徐站',
      new_section: '大徐站-塘溪站',
      old_ap_identity_status: 'MATCHED',
      new_ap_identity_status: 'MATCHED',
      identity_status: 'BOTH_MATCHED',
      source: 'MR Syslog / WMESH',
      source_type: 'SYSLOG',
    }] as GroundPingSeries['ap_transitions']
    const wrapper = mount(GroundPingChart, {
      props: { series: { ...series, ap_transitions: transitions } },
    })
    await flushPromises()

    const rttOptions = mocks.setOption.mock.calls[0]?.[0]
    const content = rttOptions.tooltip.formatter({
      data: rttOptions.series[0].markLine.data[0],
    })
    expect(content).toContain('AP 解析：两端已解析')
    expect(content).toContain('象山贤庠-AP01 → 大徐站-AP02')
    expect(content).toContain('bc:5a:34:57:5c:f0')
    expect(content).toContain('象山贤庠-大徐站')
    wrapper.unmount()
  })

  it('does not retain chart or observer resources across 100 open-close cycles', async () => {
    for (let cycle = 0; cycle < 100; cycle += 1) {
      const wrapper = mount(GroundPingChart, { props: { series } })
      await flushPromises()
      wrapper.unmount()
    }

    expect(mocks.init).toHaveBeenCalledTimes(200)
    expect(mocks.dispose).toHaveBeenCalledTimes(200)
    expect(mocks.disconnect).toHaveBeenCalledTimes(100)
    expect(mocks.unsubscribe).toHaveBeenCalledTimes(100)
  })
})
