// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, onMounted, onUnmounted } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceStore } from '../stores/workspace'
import AppRouteView from './AppRouteView.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
})

describe('AppRouteView cache boundary', () => {
  it('unmounts ordinary pages and retains only routes with workspace.cache enabled', async () => {
    const ordinary = { mounted: vi.fn(), unmounted: vi.fn() }
    const cached = { mounted: vi.fn(), unmounted: vi.fn() }
    const OrdinaryPage = defineComponent({
      name: 'OrdinaryPage',
      setup() {
        onMounted(ordinary.mounted)
        onUnmounted(ordinary.unmounted)
        return () => 'ordinary'
      },
    })
    const CachedPage = defineComponent({
      name: 'CachedPage',
      setup() {
        onMounted(cached.mounted)
        onUnmounted(cached.unmounted)
        return () => 'cached'
      },
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'dashboard', component: OrdinaryPage, meta: { title: 'Dashboard' } },
        { path: '/cached', name: 'cached', component: CachedPage, meta: { title: 'Cached', workspace: { cache: true } } },
      ],
    })
    await router.push('/')
    await router.isReady()
    const workspace = useWorkspaceStore()
    await workspace.initialize(router)
    const wrapper = mount(AppRouteView, { global: { plugins: [router] } })
    await flushPromises()

    const cachedTab = await workspace.openOrActivateRoute('/cached')
    await flushPromises()
    expect(ordinary.unmounted).toHaveBeenCalledOnce()
    expect(cached.mounted).toHaveBeenCalledOnce()
    expect(workspace.cachedTabs.map((tab) => tab.id)).toEqual([cachedTab.id])

    await workspace.openOrActivateRoute('/')
    await flushPromises()
    expect(ordinary.mounted).toHaveBeenCalledTimes(2)
    expect(cached.unmounted).not.toHaveBeenCalled()

    await workspace.closeTab(cachedTab.id)
    await flushPromises()
    expect(cached.unmounted).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('does not reuse a stale page wrapper when direct router navigation changes a tab route', async () => {
    const DevicePage = defineComponent({
      name: 'DeviceManagementView',
      setup: () => () => h('section', { 'data-device-page': '' }, '设备管理页面'),
    })
    const MeshPage = defineComponent({
      name: 'MeshAnalysisView',
      setup: () => () => h('section', { 'data-mesh-page': '' }, 'MESH 页面'),
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'dashboard', component: DevicePage, meta: { title: 'Dashboard' } },
        { path: '/network/devices', name: 'device-management', component: DevicePage, meta: { title: '设备管理' } },
        { path: '/rail-transit/mesh-analysis', name: 'mesh-analysis', component: MeshPage, meta: {
          title: 'MR 原始 MESH 日志分析',
          workspace: { cache: true },
        } },
      ],
    })
    await router.push('/network/devices')
    await router.isReady()
    const workspace = useWorkspaceStore()
    await workspace.initialize(router)
    const wrapper = mount(AppRouteView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.get('[data-device-page]').text()).toBe('设备管理页面')
    const deviceCacheKey = workspace.activeTab?.cacheKey

    await router.push('/rail-transit/mesh-analysis')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('mesh-analysis')
    expect(workspace.activeTab?.routeName).toBe('mesh-analysis')
    expect(workspace.activeTab?.cacheKey).toBe(deviceCacheKey)
    expect(wrapper.find('[data-device-page]').exists()).toBe(false)
    expect(wrapper.get('[data-mesh-page]').text()).toBe('MESH 页面')
    wrapper.unmount()
  })
})
