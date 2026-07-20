// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getBackendStatus: vi.fn(async () => ({ state: 'ready' })),
  getSystemSettings: vi.fn(async () => ({ current_site_name: '宁波地铁测试局点' })),
}))

vi.mock('../platform/runtime', () => ({
  getPlatformAdapter: () => ({ getBackendStatus: mocks.getBackendStatus }),
}))
vi.mock('../api/systemSettings', () => ({ getSystemSettings: mocks.getSystemSettings }))

import TaskWindowLayout from './TaskWindowLayout.vue'

describe('TaskWindowLayout', () => {
  it('renders a compact shell and the shared routed Job Center surface', async () => {
    const routerView = defineComponent(() => () => h('div', { 'data-job-center': 'shared' }, '共享任务中心'))
    const wrapper = mount(TaskWindowLayout, {
      global: {
        stubs: {
          ElContainer: defineComponent((_props, { slots }) => () => h('section', slots.default?.())),
          ElHeader: defineComponent((_props, { slots }) => () => h('header', slots.default?.())),
          ElMain: defineComponent((_props, { slots }) => () => h('main', slots.default?.())),
          RouterView: routerView,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('任务中心')
    expect(wrapper.text()).toContain('宁波地铁测试局点')
    expect(wrapper.text()).toContain('Backend Online')
    expect(wrapper.find('[data-job-center="shared"]').exists()).toBe(true)
  })
})
