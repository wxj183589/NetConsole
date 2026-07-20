// @vitest-environment happy-dom

import { mount, shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NcCard from './NcCard.vue'
import NcStatusTag from './NcStatusTag.vue'
import NcTable from './NcTable.vue'
import NcLayout from '../layouts/NcLayout.vue'

describe('NetConsole design system foundations', () => {
  it('renders cards with stable header, actions and content regions', () => {
    const wrapper = mount(NcCard, {
      props: { title: '在线 MR', subtitle: '实时指标' },
      slots: { actions: '<button>刷新</button>', default: '<p>RSSI -67 dBm</p>' },
    })
    expect(wrapper.get('h2').text()).toBe('在线 MR')
    expect(wrapper.get('.nc-card__actions').text()).toBe('刷新')
    expect(wrapper.get('.nc-card__body').text()).toContain('RSSI')
  })

  it('normalizes status values and keeps running distinct from completion', () => {
    const wrapper = mount(NcStatusTag, { props: { status: 'running' } })
    const tag = wrapper.findComponent({ name: 'ElTag' })
    expect(wrapper.text()).toContain('运行中')
    expect(tag.props('type')).toBe('primary')
    expect(wrapper.find('.nc-status-tag__dot').exists()).toBe(true)
  })

  it('keeps a missing backend status from crashing the page', () => {
    const wrapper = mount(NcStatusTag)
    expect(wrapper.text()).toContain('未知')
  })

  it('forwards data and density defaults to the Element Plus table', () => {
    const rows = [{ name: 'AP01' }]
    const wrapper = shallowMount(NcTable, { props: { data: rows } })
    const table = wrapper.findComponent({ name: 'ElTable' })
    expect(table.props('data')).toEqual(rows)
    expect(table.props('stripe')).toBe(true)
    expect(wrapper.classes()).toContain('nc-table')
  })

  it('provides a responsive page frame without replacing the application shell', () => {
    const wrapper = mount(NcLayout, {
      props: { eyebrow: 'AC 管理', title: 'FIT-AP 资源', description: '当前局点资源' },
      slots: { actions: '<button>更新</button>', default: '<div>列表</div>' },
    })
    expect(wrapper.get('h1').text()).toBe('FIT-AP 资源')
    expect(wrapper.get('.nc-layout__actions').text()).toBe('更新')
    expect(wrapper.get('.nc-layout__body').text()).toBe('列表')
  })
})
