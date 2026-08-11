// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it } from 'vitest'

import OnlineMrRssiChart from './OnlineMrRssiChart.vue'
import source from './OnlineMrRssiChart.vue?raw'

const meshChartStub = defineComponent({
  name: 'MeshRssiChart',
  props: {
    points: { type: Array, default: () => [] },
    events: { type: Array, default: () => [] },
    locationSegments: { type: Array, default: () => [] },
    active: { type: Boolean, default: true },
    initialViewport: { type: Object, default: null },
    syncViewport: { type: Object, default: null },
  },
  setup: () => () => h('div'),
})
const tracksideChartStub = defineComponent({
  name: 'MeshTracksideSignalChart',
  props: {
    series: { type: Array, default: () => [] },
  },
  setup: () => () => h('div'),
})

describe('Online MR shared RSSI chart adapter', () => {
  it('delegates rendering to MeshRssiChart without a second ECharts option', () => {
    expect(source).toContain("import MeshRssiChart from '../mesh-analysis/MeshRssiChart.vue'")
    expect(source).not.toContain('dataZoom:')
    expect(source).not.toContain('xAxis:')
    expect(source).not.toContain('yAxis:')
  })

  it('renders the shared comparison workspace with main-link and trackside panes', () => {
    const wrapper = mount(OnlineMrRssiChart, {
      props: { rows: [] },
      global: { stubs: { MeshRssiChart: meshChartStub } },
    })

    expect(wrapper.find('.rail-rssi-comparison').exists()).toBe(true)
    expect(source).toContain("import RailRssiComparison from '../rail-timeline/RailRssiComparison.vue'")
    expect(source).toContain("import MeshTracksideSignalChart from '../mesh-analysis/MeshTracksideSignalChart.vue'")
    expect(source).toContain('<RailRssiComparison')
    expect(source).toContain('<MeshRssiChart')
    expect(source).toContain('<MeshTracksideSignalChart')
  })

  it('projects identity, location, and switch details into MeshRssiChart', () => {
    const wrapper = mount(OnlineMrRssiChart, {
      props: {
        active: true,
        rows: [{
          device_time: '2026-07-21 16:00:00',
          radio: 1,
          link_state: 'ACTIVE',
          peer_name: 'bc5a-3457-7080',
          peer_mac: 'bc5a-3457-709f',
          canonical_ap_mac: 'bc5a34577080',
          identity_status: 'matched',
          identity_source: 'ac_runtime',
          identity_reason: null,
          mr_rssi: -45,
          bssid: 'bc5a-3457-709f',
          belong_station: '横溪站',
          belong_section: null,
          online_time: null,
        }, {
          device_time: '2026-07-21 16:00:02',
          radio: 1,
          link_state: 'ACTIVE',
          peer_name: null,
          peer_mac: null,
          canonical_ap_mac: null,
          identity_status: 'legacy_unknown',
          identity_source: null,
          identity_reason: null,
          mr_rssi: -46,
          bssid: null,
          belong_station: null,
          belong_section: null,
          online_time: null,
        }],
        historyEvents: [],
        realtimeEvents: [{
          event_id: 'realtime-1',
          source: 'realtime',
          event_time: '2026-07-21 16:00:01',
          radio: 1,
          reason: 'Better RSSI',
          old_peer_name: 'bc5a-3457-61e0',
          old_peer_mac: 'bc5a-3457-61ff',
          old_ap_mac: 'bc5a345761e0',
          old_station: '横溪站',
          old_section: '',
          old_rssi_dbm: -55,
          new_peer_name: 'bc5a-3457-7080',
          new_peer_mac: 'bc5a-3457-709f',
          new_ap_mac: 'bc5a34577080',
          new_station: '横溪站',
          new_section: '',
          new_rssi_dbm: -45,
        }],
      },
      global: { stubs: { MeshRssiChart: meshChartStub } },
    })

    const chart = wrapper.findComponent(meshChartStub)
    const points = chart.props('points') as Array<Record<string, unknown>>
    const events = chart.props('events') as Array<Record<string, unknown>>
    const locations = chart.props('locationSegments') as Array<Record<string, unknown>>

    expect(points[0]).toEqual(expect.objectContaining({
      peer_ap_name: 'bc5a-3457-7080',
      peer_ap_mac: 'bc5a34577080',
      peer_radio_mac: 'bc5a-3457-709f',
      station: '横溪站',
      local_rssi: -45,
      identity_status: 'matched',
    }))
    expect(points[1]?.identity_status).toBeUndefined()
    expect(events[0]).toEqual(expect.objectContaining({
      event_type: 'ACTIVE_SWITCH',
      from_ap_name: 'bc5a-3457-61e0',
      to_ap_name: 'bc5a-3457-7080',
      reason: 'Better RSSI',
      from_station: '横溪站',
      to_station: '横溪站',
      render_aligned: true,
      render_point_timestamp: '2026-07-21 16:00:00',
    }))
    expect(locations).toEqual([
      expect.objectContaining({ station: '横溪站', start_time: '2026-07-21 16:00:00' }),
    ])
  })

  it('passes a stored viewport through and publishes user zoom changes', async () => {
    const viewport = {
      start_time: '2026-07-21 16:00:00',
      end_time: '2026-07-21 16:05:00',
      start_percent: 20,
      end_percent: 60,
      full_start_time: '2026-07-21 15:55:00',
      full_end_time: '2026-07-21 16:10:00',
      source: 'user_zoom' as const,
    }
    const wrapper = mount(OnlineMrRssiChart, {
      props: { rows: [], viewport },
      global: { stubs: { MeshRssiChart: meshChartStub } },
    })
    const chart = wrapper.findComponent(meshChartStub)

    expect(chart.props('initialViewport')).toEqual(viewport)
    expect(chart.props('syncViewport')).toEqual(viewport)
    await chart.vm.$emit('viewport-change', viewport)
    expect(wrapper.emitted('update:viewport')).toEqual([[viewport]])
  })

  it('maps Online MR trackside RSSI into the shared trackside chart value', () => {
    const wrapper = mount(OnlineMrRssiChart, {
      props: {
        tracksideSeries: [{
          metric_type: 'trackside_rssi',
          series_key: 'AP-A · Radio 1',
          unit: 'dBm',
          summary: { count: 1, minimum: -61, maximum: -61, average: -61 },
          points: [{
            timestamp: '2026-07-21 16:00:00',
            raw_timestamp: '2026-07-21 16:00:00',
            normalized_timestamp: '2026-07-21 16:00:00',
            timestamp_source: 'device',
            correction_method: 'none',
            correction_confidence: 'high',
            value: -61,
            text_value: null,
            dimensions: { radio: 1, link_state: 'STANDBY', peer_name: 'AP-A' },
          }],
        }],
      },
      global: { stubs: { MeshRssiChart: meshChartStub, MeshTracksideSignalChart: tracksideChartStub } },
    })

    const chart = wrapper.findComponent(tracksideChartStub)
    const series = chart.props('series') as Array<{ points: Array<Record<string, unknown>> }>
    expect(series[0].points[0]).toEqual(expect.objectContaining({
      peer_rssi: -61,
      local_rssi: null,
      role: 'STANDBY',
    }))
  })
})
