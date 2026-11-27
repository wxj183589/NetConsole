// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../api/siteStorage'
import { clearSiteContext } from '../stores/siteContext'
import { useWorkspaceStore } from '../stores/workspace'
import CurrentSiteIndicator from './CurrentSiteIndicator.vue'

vi.mock('../api/siteStorage')

const runtime = vi.hoisted(() => ({
  listener: undefined as undefined | ((status: { state: 'starting' | 'ready' | 'stopped' | 'failed' }) => void),
  unsubscribe: vi.fn(),
  onBackendStatusChanged: vi.fn((listener: (status: { state: 'starting' | 'ready' | 'stopped' | 'failed' }) => void) => {
    runtime.listener = listener
    return runtime.unsubscribe
  }),
}))

vi.mock('../platform/runtime', () => ({
  onPlatformRuntimeStatusChanged: runtime.onBackendStatusChanged,
}))

async function mounted() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { template: '<div />' } },
      {
        path: '/settings',
        name: 'system-settings',
        component: { template: '<div />' },
        meta: { navigationId: 'settings' },
      },
    ],
  })
  await router.push('/')
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  await useWorkspaceStore(pinia).initialize(router)
  const wrapper = mount(CurrentSiteIndicator, {
    global: {
      plugins: [pinia, router],
      stubs: { ElIcon: { template: '<span><slot /></span>' } },
    },
  })
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  clearSiteContext()
  runtime.listener = undefined
  vi.mocked(api.getActiveSiteRuntimeContext).mockResolvedValue({
    active_site_id: 'legacy-123456789abc',
    registry_revision: 'revision-1',
    sites: [{ site_id: 'legacy-123456789abc', display_name: '测试局点-A网', active: true }],
  })
})

describe('CurrentSiteIndicator', () => {
  it('shows the real display name and reuses the system settings workspace tab', async () => {
    const { wrapper, router } = await mounted()
    await flushPromises()

    expect(wrapper.text()).toContain('当前局点：测试局点-A网')
    expect(wrapper.text()).not.toContain('legacy-123456789abc')
    expect(wrapper.get('[data-testid="current-site-indicator"]').attributes('title')).toBe('当前局点：测试局点-A网')
    expect(wrapper.find('select').exists()).toBe(false)

    await wrapper.get('[data-testid="current-site-indicator"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('system-settings')
    expect(router.currentRoute.value.query.section).toBe('site-storage')
    expect(String(router.currentRoute.value.query.site_focus)).toMatch(/^\d+-1$/)
    const workspace = useWorkspaceStore()
    expect(workspace.tabs.filter((tab) => tab.routeName === 'system-settings')).toHaveLength(1)

    await workspace.openOrActivateRoute('/')
    await wrapper.get('[data-testid="current-site-indicator"]').trigger('click')
    await flushPromises()
    expect(workspace.tabs.filter((tab) => tab.routeName === 'system-settings')).toHaveLength(1)
    expect(String(router.currentRoute.value.query.site_focus)).toMatch(/^\d+-2$/)
    wrapper.unmount()
  })

  it('keeps stable loading, empty and failure labels without hiding the navigation target', async () => {
    let resolveSite: ((value: Awaited<ReturnType<typeof api.getActiveSiteRuntimeContext>>) => void) | undefined
    vi.mocked(api.getActiveSiteRuntimeContext).mockReturnValueOnce(new Promise((resolve) => { resolveSite = resolve }))
    const loading = await mounted()
    expect(loading.wrapper.text()).toContain('当前局点：加载中…')
    resolveSite?.({ active_site_id: '', registry_revision: 'revision-1', sites: [] })
    await flushPromises()
    expect(loading.wrapper.text()).toContain('当前局点：未选择')
    loading.wrapper.unmount()

    vi.mocked(api.getActiveSiteRuntimeContext).mockRejectedValueOnce(new Error('offline'))
    const failed = await mounted()
    await flushPromises()
    expect(failed.wrapper.text()).toContain('当前局点：读取失败')
    expect(failed.wrapper.get('button').attributes('class')).toContain('is-error')
    failed.wrapper.unmount()
  })

  it('clears stale data during a backend restart and reloads the new active site when ready', async () => {
    const { wrapper } = await mounted()
    await flushPromises()
    expect(wrapper.text()).toContain('测试局点-A网')

    vi.mocked(api.getActiveSiteRuntimeContext).mockResolvedValueOnce({
      active_site_id: 'site-b', registry_revision: 'revision-2',
      sites: [{ site_id: 'site-b', display_name: '测试局点-B网', active: true }],
    })
    runtime.listener?.({ state: 'starting' })
    await nextTick()
    expect(wrapper.text()).toContain('当前局点：加载中…')
    expect(wrapper.text()).not.toContain('测试局点-A网')

    runtime.listener?.({ state: 'ready' })
    await flushPromises()
    expect(wrapper.text()).toContain('当前局点：测试局点-B网')
    expect(api.getActiveSiteRuntimeContext).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    expect(runtime.unsubscribe).toHaveBeenCalledOnce()
  })

  it('keeps the previous site visible while the warm Backend starts in the background', async () => {
    const { wrapper } = await mounted()
    await flushPromises()

    window.dispatchEvent(new CustomEvent('netconsole:site-switch-metadata', {
      detail: { siteId: 'site-b', displayName: '测试局点-B网', state: 'loading' },
    }))
    await nextTick()

    expect(wrapper.text()).toContain('当前局点：测试局点-A网（切换中…）')
    expect(wrapper.text()).not.toContain('测试局点-B网')
    expect(wrapper.get('button').attributes('class')).toContain('is-switching')
    expect(api.getActiveSiteRuntimeContext).toHaveBeenCalledOnce()

    vi.mocked(api.getActiveSiteRuntimeContext).mockResolvedValueOnce({
      active_site_id: 'site-b', registry_revision: 'revision-2',
      sites: [{ site_id: 'site-b', display_name: '测试局点-B网', active: true }],
    })
    runtime.listener?.({ state: 'ready' })
    await flushPromises()
    expect(wrapper.text()).toContain('当前局点：测试局点-B网')
    expect(wrapper.text()).not.toContain('（加载中…）')
    wrapper.unmount()
  })

  it('reloads the current name after site information changes without restarting Backend', async () => {
    const { wrapper } = await mounted()
    await flushPromises()
    vi.mocked(api.getActiveSiteRuntimeContext).mockResolvedValueOnce({
      active_site_id: 'legacy-123456789abc', registry_revision: 'revision-2',
      sites: [{ site_id: 'legacy-123456789abc', display_name: '已重命名局点', active: true }],
    })

    window.dispatchEvent(new CustomEvent('netconsole:site-context-changed'))
    await flushPromises()

    expect(wrapper.text()).toContain('当前局点：已重命名局点')
    expect(api.getActiveSiteRuntimeContext).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('keeps long names in one truncatable span with the complete label in the tooltip', async () => {
    const longName = '测试地铁线路-信号系统-A网超长联调环境名称'
    vi.mocked(api.getActiveSiteRuntimeContext).mockResolvedValueOnce({
      active_site_id: 'legacy-123456789abc', registry_revision: 'revision-2',
      sites: [{ site_id: 'legacy-123456789abc', display_name: longName, active: true }],
    })
    const { wrapper } = await mounted()
    await flushPromises()

    expect(wrapper.get('.current-site-name').text()).toBe(longName)
    expect(wrapper.get('.current-site-name').attributes('class')).toContain('current-site-name')
    expect(wrapper.get('button').attributes('title')).toBe(`当前局点：${longName}`)
    wrapper.unmount()
  })
})
