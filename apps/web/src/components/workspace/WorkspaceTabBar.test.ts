// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceStore } from '../../stores/workspace'
import WorkspaceTabBar from './WorkspaceTabBar.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
  Element.prototype.scrollIntoView = vi.fn()
})

describe('WorkspaceTabBar', () => {
  it('renders, activates, pins, and closes workspace tabs', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'dashboard', component: {}, meta: { title: 'Dashboard' } },
        { path: '/devices', name: 'devices', component: {}, meta: { title: '设备管理' } },
      ],
    })
    await router.push('/')
    const store = useWorkspaceStore()
    await store.initialize(router)
    const devices = await store.openOrActivateRoute('/devices')
    const wrapper = mount(WorkspaceTabBar, {
      global: { plugins: [ElementPlus, router] },
      attachTo: document.body,
    })

    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    expect(wrapper.get('.workspace-tab.active').text()).toContain('设备管理')
    await wrapper.findAll('.workspace-tab')[0].trigger('contextmenu')
    await wrapper.findAll('.workspace-tab-context button')[2].trigger('click')
    expect(store.tabs[0].pinned).toBe(true)

    await wrapper.get('.workspace-tab.active .workspace-tab__close').trigger('click')
    await flushPromises()
    expect(store.tabs.some((tab) => tab.id === devices.id)).toBe(false)
    expect(store.activeTab?.pinned).toBe(true)
    wrapper.unmount()
  })

  it('disables duplicate for routes that do not explicitly allow it', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'dashboard', component: {}, meta: { title: 'Dashboard' } },
        { path: '/mesh', name: 'mesh', component: {}, meta: { title: 'MESH', workspace: { cache: true, allowDuplicate: false } } },
      ],
    })
    await router.push('/')
    const store = useWorkspaceStore()
    await store.initialize(router)
    await store.openOrActivateRoute('/mesh?session_id=mr-id%3A1')
    const wrapper = mount(WorkspaceTabBar, {
      global: { plugins: [ElementPlus, router] },
      attachTo: document.body,
    })

    await wrapper.get('.workspace-tab.active').trigger('contextmenu')
    const duplicate = wrapper.findAll('.workspace-tab-context button')[1]
    expect(duplicate.attributes('disabled')).toBeDefined()
    expect(await store.duplicateTab()).toBeNull()
    expect(store.tabs.filter((tab) => tab.routeName === 'mesh')).toHaveLength(1)
    wrapper.unmount()
  })
})
