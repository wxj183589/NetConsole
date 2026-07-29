// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { GroundPingSeries } from '../../types/groundUnattended'

const mocks = vi.hoisted(() => ({
  disconnect: vi.fn(),
  dispose: vi.fn(),
  init: vi.fn(),
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
    requested_run_id: 'run-1',
    resolved_start_time: '2026-07-28T07:00:00+08:00',
    resolved_end_time: '2026-07-28T23:00:00+08:00',
    source_kind: 'ACTIVE',
    data_availability: 'ACTIVE_RAW',
    files_considered: 1,
    files_scanned: 1,
    records_scanned: 1,
    bytes_scanned: 100,
    malformed_record_count: 0,
    duplicate_record_count: 0,
    truncated: false,
    legacy_archive: false,
    no_data_reason: '',
  },
} satisfies GroundPingSeries

beforeEach(() => {
  vi.clearAllMocks()
  mocks.init.mockImplementation(() => ({
    dispose: mocks.dispose,
    resize: mocks.resize,
    setOption: mocks.setOption,
  }))
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() { mocks.disconnect() }
  })
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
