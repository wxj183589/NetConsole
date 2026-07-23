// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import AppLayout from './AppLayout.vue'
import { OPEN_PAGE_TABS_STORAGE_KEY } from '../stores/openPageTabs'

vi.mock('../api/client', () => ({
  getHealth: vi.fn(async () => ({ status: 'ok', version: '1.3.9', build_id: 'test' })),
  getWebBuildMeta: vi.fn(async () => ({ build_id: 'test' })),
}))

vi.mock('../features', () => ({
  isFeatureEnabled: () => true,
  isFeatureVisible: () => true,
  loadWebFeatures: vi.fn(async () => undefined),
}))

const MeshPage = defineComponent({ name: 'MeshAnalysisView', template: '<div data-test="mesh-page">MESH 页面</div>' })
const BaseDataPage = defineComponent({ template: '<div data-test="base-data-page">基础资料页面</div>' })

describe('AppLayout 轨道交通导航', () => {
  it('从 MESH 页面真实点击基础资料后同步路由、标题和页面', async () => {
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
            meta: {
              navigationId: 'rail.mesh-analysis',
              title: '轨道交通 / MR 原始 MESH 日志分析',
              tabTitle: 'MR 原始 MESH 日志分析',
              keepAlive: true,
              cacheComponentName: 'MeshAnalysisView',
            },
          },
          {
            path: 'rail-transit/base-data',
            name: 'rail-transit-base-data',
            component: BaseDataPage,
            meta: {
              navigationId: 'rail.base-data',
              title: '轨道交通 / 基础资料',
              tabTitle: '基础资料',
            },
          },
        ],
      }],
    })
    await router.push('/rail-transit/mesh-analysis')
    await router.isReady()
    const Root = defineComponent({ template: '<RouterView />' })
    const wrapper = mount(Root, {
      global: {
        plugins: [createPinia(), router, ElementPlus],
        stubs: { DesktopRuntimeStatus: true },
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="mesh-page"]').exists()).toBe(true)
    const baseDataMenu = wrapper.findAll('.el-menu-item').find((item) => item.text().trim() === '基础资料')
    expect(baseDataMenu).toBeDefined()
    await baseDataMenu!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/rail-transit/base-data')
    expect(wrapper.find('.header-title').text()).toBe('轨道交通 / 基础资料')
    expect(wrapper.find('[data-test="base-data-page"]').exists()).toBe(true)
    expect(wrapper.findAll('.open-page-tab').map((item) => item.text())).toEqual([
      'Dashboard',
      'MR 原始 MESH 日志分析',
      '基础资料',
    ])
    wrapper.unmount()
  })

  it('restores the last active valid business route from session tabs on Dashboard startup', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1920 })
    sessionStorage.clear()
    sessionStorage.setItem(OPEN_PAGE_TABS_STORAGE_KEY, JSON.stringify({
      version: 1,
      tabs: [
        { routeName: 'dashboard', path: '/', title: 'Dashboard', navigationId: 'dashboard' },
        {
          routeName: 'mesh-analysis',
          path: '/rail-transit/mesh-analysis',
          title: 'MR 原始 MESH 日志分析',
          navigationId: 'rail.mesh-analysis',
        },
      ],
      activeRouteName: 'mesh-analysis',
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/',
        component: AppLayout,
        children: [
          {
            path: '',
            name: 'dashboard',
            component: defineComponent({ template: '<div data-test="dashboard-page" />' }),
            meta: { navigationId: 'dashboard', title: 'Dashboard', tabTitle: 'Dashboard' },
          },
          {
            path: 'rail-transit/mesh-analysis',
            name: 'mesh-analysis',
            component: MeshPage,
            meta: {
              navigationId: 'rail.mesh-analysis',
              title: '轨道交通 / MR 原始 MESH 日志分析',
              tabTitle: 'MR 原始 MESH 日志分析',
              keepAlive: true,
              cacheComponentName: 'MeshAnalysisView',
            },
          },
        ],
      }],
    })
    await router.push('/')
    await router.isReady()
    const Root = defineComponent({ template: '<RouterView />' })
    const wrapper = mount(Root, {
      global: {
        plugins: [createPinia(), router, ElementPlus],
        stubs: { DesktopRuntimeStatus: true },
      },
    })
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('mesh-analysis')
    expect(wrapper.find('[data-test="mesh-page"]').exists()).toBe(true)
    expect(wrapper.find('.open-page-tab.is-active').text()).toContain('MR 原始 MESH 日志分析')
    wrapper.unmount()
  })
})
