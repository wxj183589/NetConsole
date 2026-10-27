// @vitest-environment happy-dom

import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TrafficLogViewer from './TrafficLogViewer.vue'
import type { TrafficEvent } from '../../types/traffic'

describe('TrafficLogViewer WPS multi-filter', () => {
  it('filters multiple event types and keeps the empty selection equivalent to all logs', async () => {
    const events = ['stdout', 'stderr', 'system', 'error'].map((type, index): TrafficEvent => ({
      sequence: index + 1,
      type,
      timestamp: '2026-10-27T10:00:00Z',
      traffic_run_id: 'test',
      controller_task_id: 'task',
      source: 'local',
      payload: { message: `${type}-message` },
      remote_sequence: null,
    }))
    const wrapper = shallowMount(TrafficLogViewer, { props: { events } })
    expect(wrapper.findAll('.log-row')).toHaveLength(4)
    const filter = wrapper.findComponent({ name: 'NcMultiValueFilter' })
    filter.vm.$emit('update:modelValue', ['stdout', 'error'])
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.log-row').map((row) => row.text())).toEqual([
      expect.stringContaining('stdout-message'), expect.stringContaining('error-message'),
    ])
    filter.vm.$emit('update:modelValue', [])
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.log-row')).toHaveLength(4)
    wrapper.unmount()
  })
})
