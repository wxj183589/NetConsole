// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useOpenPageTabsStore, type OpenPageTabDefinition } from '../../stores/openPageTabs'
import OpenPageTabs from './OpenPageTabs.vue'

function tab(
  routeName: string,
  path: string,
  keepAlive = false,
): OpenPageTabDefinition {
  return {
    routeName,
    path,
    title: routeName === 'mesh-analysis' ? 'MR 原始 MESH 日志分析' : routeName,
    fullTitle: routeName === 'mesh-analysis'
      ? '轨道交通 / MR 原始 MESH 日志分析'
      : routeName,
    navigationId: routeName,
    closable: routeName !== 'dashboard',
    keepAlive,
    componentName: keepAlive ? 'MeshAnalysisView' : undefined,
  }
}

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { template: '<div />' } },
      { path: '/mesh', name: 'mesh-analysis', component: { template: '<div />' } },
      { path: '/base', name: 'base-data', component: { template: '<div />' } },
    ],
  })
}

beforeEach(() => sessionStorage.clear())

describe('OpenPageTabs', () => {
  it('closes an inactive MESH tab without changing the current route', async () => {
    const pinia = createPinia()
    const router = createTestRouter()
    const store = useOpenPageTabsStore(pinia)
    store.restoreTabs(() => null)
    store.openOrActivate(tab('mesh-analysis', '/mesh', true))
    store.openOrActivate(tab('base-data', '/base'))
    await router.push('/base')

    const wrapper = mount(OpenPageTabs, {
      global: { plugins: [pinia, router, ElementPlus] },
    })
    await flushPromises()
    const meshTab = wrapper.findAll('.open-page-tab')
      .find((item) => item.text().includes('MR 原始 MESH 日志分析'))
    expect(meshTab).toBeDefined()

    await meshTab!.get('.open-page-tab__close').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('base-data')
    expect(store.tabs.some((item) => item.routeName === 'mesh-analysis')).toBe(false)
    expect(store.cachedComponentNames).toEqual([])
  })

  it('closes the current tab by activating its left neighbor first', async () => {
    const pinia = createPinia()
    const router = createTestRouter()
    const store = useOpenPageTabsStore(pinia)
    store.restoreTabs(() => null)
    store.openOrActivate(tab('mesh-analysis', '/mesh', true))
    store.openOrActivate(tab('base-data', '/base'))
    await router.push('/base')

    const wrapper = mount(OpenPageTabs, {
      global: { plugins: [pinia, router, ElementPlus] },
    })
    await flushPromises()
    const baseTab = wrapper.findAll('.open-page-tab')
      .find((item) => item.text().includes('base-data'))
    await baseTab!.get('.open-page-tab__close').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('mesh-analysis')
    expect(store.activeRouteName).toBe('mesh-analysis')
    expect(store.tabs.map((item) => item.routeName)).toEqual(['dashboard', 'mesh-analysis'])
  })
})
