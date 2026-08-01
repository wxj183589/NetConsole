// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NcLogWorkspace from './NcLogWorkspace.vue'

describe('NcLogWorkspace', () => {
  it('keeps controls and pagination outside the single flexible table area', () => {
    const wrapper = mount(NcLogWorkspace, {
      props: { loading: true },
      slots: {
        header: '<div data-slot="header">筛选</div>',
        summary: '<div data-slot="summary">诊断</div>',
        actions: '<div data-slot="actions">批量操作</div>',
        default: '<div data-slot="table">日志表格</div>',
        pagination: '<div data-slot="pagination">分页</div>',
      },
    })

    expect(wrapper.attributes('aria-busy')).toBe('true')
    expect(wrapper.get('.nc-log-workspace__header [data-slot="header"]').text()).toBe('筛选')
    expect(wrapper.get('.nc-log-workspace__summary [data-slot="summary"]').text()).toBe('诊断')
    expect(wrapper.get('.nc-log-workspace__actions [data-slot="actions"]').text()).toBe('批量操作')
    expect(wrapper.get('.nc-log-workspace__table [data-slot="table"]').text()).toBe('日志表格')
    expect(wrapper.get('.nc-log-workspace__pagination [data-slot="pagination"]').text()).toBe('分页')
  })

  it('omits optional fixed areas while preserving the table area', () => {
    const wrapper = mount(NcLogWorkspace, {
      slots: { default: '<div data-slot="table">日志表格</div>' },
    })

    expect(wrapper.find('.nc-log-workspace__header').exists()).toBe(false)
    expect(wrapper.find('.nc-log-workspace__summary').exists()).toBe(false)
    expect(wrapper.find('.nc-log-workspace__actions').exists()).toBe(false)
    expect(wrapper.find('.nc-log-workspace__pagination').exists()).toBe(false)
    expect(wrapper.get('.nc-log-workspace__table [data-slot="table"]').text()).toBe('日志表格')
  })
})
