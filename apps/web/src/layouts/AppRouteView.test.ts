// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, onMounted, onUnmounted } from 'vue'
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
})
