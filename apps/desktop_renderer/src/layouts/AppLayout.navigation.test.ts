// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceStore } from '../stores/workspace'
import AppLayout from './AppLayout.vue'

vi.mock('../api/client', () => ({
  getHealth: vi.fn(async () => ({
    status: 'ok',
    version: '1.5.0',
    build_id: 'v1.5.0+99bba059c3359d409673286a9093503fe9d09255',
  })),
  getRendererBuildMeta: vi.fn(async () => ({
    app_version: 'v1.4.9',
    git_commit_full: '29541dda879049c54ace0730c44fc6f3eb92b872',
    build_id: 'v1.4.9+29541dda879049c54ace0730c44fc6f3eb92b872',
  })),
}))

vi.mock('../features', () => ({
  isFeatureEnabled: () => true,
  isFeatureVisible: () => true,
  loadRendererFeatures: vi.fn(async () => undefined),
}))

const MeshPage = defineComponent({ template: '<div data-test="mesh-page">MESH 页面</div>' })
const BaseDataPage = defineComponent({ template: '<div data-test="base-data-page">基础资料页面</div>' })

describe('AppLayout 轨道交通导航', () => {
  afterEach(() => vi.unstubAllEnvs())

  it('从 MESH 页面真实点击基础资料后同步路由、标题和页面', async () => {
    vi.stubEnv('DEV', false)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1920 })
    sessionStorage.clear()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/',
        component: AppLayout,
        children: [
          {
            path: 'rail-transit/mesh-analysis',
            name: 'mesh-analysis',
            component: MeshPage,
            meta: { navigationId: 'rail.mesh-analysis', title: '轨道交通 / MR 原始 MESH 日志分析' },
          },
          {
            path: 'rail-transit/base-data',
            name: 'rail-transit-base-data',
            component: BaseDataPage,
            meta: { navigationId: 'rail.base-data', title: '轨道交通 / 基础资料' },
          },
        ],
      }],
    })
    await router.push('/rail-transit/mesh-analysis')
    await router.isReady()
    const pinia = createPinia()
    const workspace = useWorkspaceStore(pinia)
    await workspace.initialize(router)
    const Root = defineComponent({ template: '<RouterView />' })
    const wrapper = mount(Root, {
      global: {
        plugins: [pinia, router, ElementPlus],
        stubs: {
          DesktopRuntimeStatus: true,
          AppRouteView: { template: '<RouterView />' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="mesh-page"]').exists()).toBe(true)
    expect(wrapper.find('.header-status').text()).toContain('v1.4.9+29541dda')
    expect(wrapper.text()).toContain('当前 Desktop Renderer 资源与后端版本不一致')
    const baseDataMenu = wrapper.findAll('.el-menu-item').find((item) => item.text().trim() === '基础资料')
    expect(baseDataMenu).toBeDefined()
    await baseDataMenu!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
    expect(wrapper.find('.header-title').text()).toBe('轨道交通 / 基础资料')
    expect(wrapper.find('[data-test="base-data-page"]').exists()).toBe(true)
    wrapper.unmount()
    workspace.dispose()
  })
})
