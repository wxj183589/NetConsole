// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../api/siteStorage'
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
  getPlatformAdapter: () => ({
    hostType: 'electron',
    onBackendStatusChanged: runtime.onBackendStatusChanged,
  }),
}))

function activeSite(displayName = '测试局点-A网', siteId = 'legacy-123456789abc') {
  return {
    site_id: siteId,
    display_name: displayName,
    created_at: '',
    updated_at: '',
    remark: '',
    active: true,
    size_bytes: 0,
    site_kind: 'formal' as const,
    classification: 'active_site',
    managed_demo: false,
    demo_seed_version: '',
    migration_status: 'current',
    data_integrity: 'ok' as const,
    recommended_action: 'keep_and_review',
    audited_at: '',
  }
}

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
  runtime.listener = undefined
  vi.mocked(api.getActiveSite).mockResolvedValue(activeSite())
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
    let resolveSite: ((value: ReturnType<typeof activeSite>) => void) | undefined
    vi.mocked(api.getActiveSite).mockReturnValueOnce(new Promise((resolve) => { resolveSite = resolve }))
    const loading = await mounted()
    expect(loading.wrapper.text()).toContain('当前局点：加载中…')
    resolveSite?.(activeSite('', ''))
    await flushPromises()
    expect(loading.wrapper.text()).toContain('当前局点：未选择')
    loading.wrapper.unmount()

    vi.mocked(api.getActiveSite).mockRejectedValueOnce(new Error('offline'))
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

    vi.mocked(api.getActiveSite).mockResolvedValueOnce(activeSite('测试局点-B网', 'site-b'))
    runtime.listener?.({ state: 'starting' })
    await nextTick()
    expect(wrapper.text()).toContain('当前局点：加载中…')
    expect(wrapper.text()).not.toContain('测试局点-A网')

    runtime.listener?.({ state: 'ready' })
    await flushPromises()
    expect(wrapper.text()).toContain('当前局点：测试局点-B网')
    expect(api.getActiveSite).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    expect(runtime.unsubscribe).toHaveBeenCalledOnce()
  })

  it('reloads the current name after site information changes without restarting Backend', async () => {
    const { wrapper } = await mounted()
    await flushPromises()
    vi.mocked(api.getActiveSite).mockResolvedValueOnce(activeSite('已重命名局点'))

    window.dispatchEvent(new CustomEvent('netconsole:site-context-changed'))
    await flushPromises()

    expect(wrapper.text()).toContain('当前局点：已重命名局点')
    expect(api.getActiveSite).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('keeps long names in one truncatable span with the complete label in the tooltip', async () => {
    const longName = '测试地铁线路-信号系统-A网超长联调环境名称'
    vi.mocked(api.getActiveSite).mockResolvedValueOnce(activeSite(longName))
    const { wrapper } = await mounted()
    await flushPromises()

    expect(wrapper.get('.current-site-name').text()).toBe(longName)
    expect(wrapper.get('.current-site-name').attributes('class')).toContain('current-site-name')
    expect(wrapper.get('button').attributes('title')).toBe(`当前局点：${longName}`)
    wrapper.unmount()
  })
})
