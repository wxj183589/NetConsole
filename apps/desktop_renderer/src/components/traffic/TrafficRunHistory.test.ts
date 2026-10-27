// @vitest-environment happy-dom

import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TrafficRunHistory from './TrafficRunHistory.vue'
import source from './TrafficRunHistory.vue?raw'

describe('Traffic run history table contract', () => {
  it('uses the shared table without changing task actions', () => {
    expect(source).toContain('table-id="traffic-run-history"')
    expect(source).toContain(':columns="columns"')
    expect(source).not.toContain('<el-table')
    expect(source).toContain("$emit('select', row)")
    expect(source).toContain("$emit('task', row)")
    expect(source).toContain("$emit('cancel', row)")
    expect(source).toContain("$emit('retry', row)")
  })

  it('combines selected task types and statuses before binding shared table rows', async () => {
    const runs = [
      { traffic_run_id: 'a', test_type: 'IPERF_CLIENT', status: 'COMPLETED' },
      { traffic_run_id: 'b', test_type: 'HIGH_FREQUENCY_PING', status: 'FAILED' },
      { traffic_run_id: 'c', test_type: 'TCP_PORT_TEST', status: 'FAILED' },
    ]
    const wrapper = shallowMount(TrafficRunHistory, { props: { runs: runs as never[], loading: false } })
    const filters = wrapper.findAllComponents({ name: 'NcMultiValueFilter' })
    const table = wrapper.findComponent({ name: 'NcDataTable' })
    expect(table.props('data')).toHaveLength(3)
    filters[0].vm.$emit('update:modelValue', ['IPERF_CLIENT', 'HIGH_FREQUENCY_PING'])
    filters[1].vm.$emit('update:modelValue', ['FAILED'])
    await wrapper.vm.$nextTick()
    expect((table.props('data') as typeof runs).map((run) => run.traffic_run_id)).toEqual(['b'])
    filters[0].vm.$emit('update:modelValue', [])
    await wrapper.vm.$nextTick()
    expect((table.props('data') as typeof runs).map((run) => run.traffic_run_id)).toEqual(['b', 'c'])
    wrapper.unmount()
  })
})
