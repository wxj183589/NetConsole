// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import FixedTrainTopology from './FixedTrainTopology.vue'
import type { TrainCommunicationTopology } from '../../types/trainCommunication'

const topology: TrainCommunicationTopology = {
  train_id: 'train-1', train_name: '列车 1', train_status: 'normal', checked_at: '2026-07-19T10:00:00Z',
  point_table_status: 'configured', point_table_message: '', point_table_revision: 'rev-1', point_table_missing_nodes: [],
  tc1_nodes: [
    { node_id: 'TC1-MR', side: 'TC1', role: 'MR', name: 'TC1-MR', device_id: '1', ip_address: '10.0.0.1', status: 'normal', message: '', updated_at: null },
    { node_id: 'TC1-SW', side: 'TC1', role: 'SWITCH', name: '', device_id: null, ip_address: null, status: 'not_configured', message: '未配置', updated_at: null },
    { node_id: 'TC1-SRV', side: 'TC1', role: 'SERVER', name: '', device_id: null, ip_address: null, status: 'not_configured', message: '未配置', updated_at: null },
  ],
  tc2_nodes: [
    { node_id: 'TC2-MR', side: 'TC2', role: 'MR', name: 'TC2-MR', device_id: '2', ip_address: '10.0.0.2', status: 'abnormal', message: '', updated_at: null },
    { node_id: 'TC2-SW', side: 'TC2', role: 'SWITCH', name: '', device_id: null, ip_address: null, status: 'not_configured', message: '未配置', updated_at: null },
    { node_id: 'TC2-SRV', side: 'TC2', role: 'SERVER', name: '', device_id: null, ip_address: null, status: 'not_configured', message: '未配置', updated_at: null },
  ],
  links: [
    { link_id: 'tc1-mr-sw', source: 'TC1-MR', target: 'TC1-SW', label: 'MR 与交换机', status: 'not_configured', message: '' },
    { link_id: 'tc1-sw-tc2-sw', source: 'TC1-SW', target: 'TC2-SW', label: 'TC1-SW ↔ TC2-SW', status: 'normal', message: '' },
  ],
  vrrp: { status: 'normal', master_side: 'TC1', virtual_ip: '10.122.1.254', master_device: 'TC1-SW', backup_device: 'TC2-SW', message: '未检测', updated_at: null },
  cross_end: { status: 'not_detected', message: '未检测', updated_at: null },
}

describe('FixedTrainTopology', () => {
  it('renders six fixed nodes and the cross-end status', () => {
    const wrapper = mount(FixedTrainTopology, { props: { topology } })
    expect(wrapper.findAll('.topology-node')).toHaveLength(6)
    expect(wrapper.findAll('.topology-node')[0].classes()).toContain('is-normal')
    expect(wrapper.findAll('.topology-node')[3].classes()).toContain('is-abnormal')
    expect(wrapper.find('.topology-links line').classes()).toContain('is-not-configured')
    expect(wrapper.text()).toContain('VRRP')
    expect(wrapper.text()).toContain('跨 TC 通信')
    expect(wrapper.text()).not.toMatch(/unknown|no_data|RSSI|fping|iPerf/i)
  })

  it('renders VRRP as static virtual IP configuration only', async () => {
    const wrapper = mount(FixedTrainTopology, { props: { topology } })
    const panel = wrapper.find('.vrrp-panel')
    const staticLink = wrapper.findAll('.topology-links line')[4]

    expect(panel.text()).toContain('VRRP')
    expect(panel.text()).toContain('虚拟 IP：10.122.1.254')
    expect(panel.text()).not.toMatch(/正常|异常|未检测|主端|TC1-SW|TC2-SW/)
    expect(staticLink.classes()).toContain('is-static')
    expect(staticLink.classes()).not.toContain('is-normal')
    expect(wrapper.find('.topology-links-legend').text()).not.toContain('VRRP：正常')
    expect(wrapper.find('.cross-end').text()).toContain('跨 TC 通信：未检测')

    await wrapper.setProps({ checking: true })
    expect(panel.classes()).not.toContain('is-checking')
    expect(panel.text()).not.toContain('检测中')
    expect(staticLink.classes()).toContain('is-static')
  })

  it('does not render an empty VRRP virtual IP placeholder', () => {
    const withoutVirtualIp = { ...topology, vrrp: { ...topology.vrrp, virtual_ip: null } }
    const wrapper = mount(FixedTrainTopology, { props: { topology: withoutVirtualIp } })

    expect(wrapper.find('.vrrp-panel').text()).toBe('VRRP')
  })

  it('emits a selected node with a device id', async () => {
    const wrapper = mount(FixedTrainTopology, { props: { topology } })
    await wrapper.find('.topology-node').trigger('click')
    expect(wrapper.emitted('selectNode')?.[0]?.[0]).toMatchObject({ node_id: 'TC1-MR', device_id: '1' })
  })

  it('shows configured nodes as checking without hiding unconfigured nodes', async () => {
    const wrapper = mount(FixedTrainTopology, { props: { topology } })
    await wrapper.setProps({ checking: true })
    expect(wrapper.findAll('.topology-node')[0].classes()).toContain('is-checking')
    expect(wrapper.findAll('.topology-node')[1].classes()).toContain('is-not-configured')
  })

  it('shows safe empty states when topology is missing', () => {
    const wrapper = mount(FixedTrainTopology, { props: { topology: null } })
    expect(wrapper.findAll('.topology-node')).toHaveLength(6)
    expect(wrapper.text()).toContain('未检测')
    expect(wrapper.text()).not.toMatch(/unknown|no_data/i)
  })
})
