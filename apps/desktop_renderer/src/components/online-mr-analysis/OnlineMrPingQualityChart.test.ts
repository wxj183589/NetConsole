// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import OnlineMrPingQualityChart from './OnlineMrPingQualityChart.vue'

const StubChart = {
  name: 'OnlineMrAnalysisChart',
  props: ['series', 'tooltipKind', 'viewport', 'cursorTime', 'selectedTime', 'sharedTimeDomain', 'active'],
  emits: ['update:viewport', 'pointer-change', 'select-time'],
  template: '<button class="metric-chart" @click="$emit(\'select-time\', \'2026-07-21 15:00:01\')"></button>',
}

describe('OnlineMrPingQualityChart', () => {
  it('renders loss and RTT panes and forwards shared timeline events', async () => {
    const wrapper = mount(OnlineMrPingQualityChart, {
      props: {
        lossSeries: [],
        rttSeries: [],
        viewport: {
          start_time: '2026-07-21 15:00:00',
          end_time: '2026-07-21 15:00:10',
          start_percent: 0,
          end_percent: 100,
          full_start_time: '2026-07-21 15:00:00',
          full_end_time: '2026-07-21 15:00:10',
          source: 'user_zoom',
        },
        cursorTime: '2026-07-21 15:00:02',
        selectedTime: '2026-07-21 15:00:03',
        active: true,
      },
      global: { stubs: { OnlineMrAnalysisChart: StubChart } },
    })

    const charts = wrapper.findAllComponents({ name: 'OnlineMrAnalysisChart' })
    expect(charts).toHaveLength(2)
    expect(charts[0].props('tooltipKind')).toBe('ping-loss')
    expect(charts[1].props('tooltipKind')).toBe('ping-rtt')
    expect(charts[0].props('viewport')).toEqual(charts[1].props('viewport'))

    await charts[0].vm.$emit('update:viewport', {
      start_time: '2026-07-21 15:00:01',
      end_time: '2026-07-21 15:00:05',
      start_percent: 10,
      end_percent: 50,
      full_start_time: '2026-07-21 15:00:00',
      full_end_time: '2026-07-21 15:00:10',
      source: 'user_zoom',
    })
    await charts[1].vm.$emit('pointer-change', { time: '2026-07-21 15:00:04', source_chart: 'timeline-metric' })
    await charts[0].vm.$emit('select-time', '2026-07-21 15:00:01')

    expect(wrapper.emitted('update:viewport')).toHaveLength(1)
    expect(wrapper.emitted('pointer-change')).toHaveLength(1)
    expect(wrapper.emitted('select-time')).toEqual([['2026-07-21 15:00:01']])
  })
})
