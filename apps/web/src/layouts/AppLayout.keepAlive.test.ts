// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import {
  defineComponent,
  getCurrentInstance,
  h,
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
} from 'vue'
import {
  createMemoryHistory,
  createRouter,
  RouterView,
} from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  loadChart: vi.fn(),
}))

import AppRouteView from './AppRouteView.vue'

const lifecycle = {
  activated: 0,
  deactivated: 0,
  mounted: 0,
  unmounted: 0,
}
const ordinaryLifecycle = {
  mounted: 0,
  unmounted: 0,
}

const MeshPage = defineComponent({
  name: 'MeshAnalysisView',
  setup() {
    const instance = getCurrentInstance()
    const count = ref(0)
    onMounted(() => {
      lifecycle.mounted += 1
      mocks.loadChart()
    })
    onActivated(() => { lifecycle.activated += 1 })
    onDeactivated(() => { lifecycle.deactivated += 1 })
    onBeforeUnmount(() => { lifecycle.unmounted += 1 })
    return () => h('section', {
      'data-mesh-page': '',
      'data-uid': String(instance?.uid),
    }, [
      h('button', { onClick: () => { count.value += 1 } }, '更新状态'),
      h('span', { 'data-mesh-count': '' }, String(count.value)),
    ])
  },
})

const OrdinaryPage = defineComponent({
  name: 'OrdinaryPage',
  setup() {
    onMounted(() => { ordinaryLifecycle.mounted += 1 })
    onBeforeUnmount(() => { ordinaryLifecycle.unmounted += 1 })
    return () => h('section', { 'data-ordinary-page': '' }, '普通页面')
  },
})

const root = defineComponent({
  setup: () => () => h(RouterView),
})

beforeEach(() => {
  vi.clearAllMocks()
  lifecycle.activated = 0
  lifecycle.deactivated = 0
  lifecycle.mounted = 0
  lifecycle.unmounted = 0
  ordinaryLifecycle.mounted = 0
  ordinaryLifecycle.unmounted = 0
})

describe('AppLayout controlled route cache', () => {
  it('keeps one mesh analysis instance while ordinary routes still unmount', async () => {
    const cachedComponentNames = ref(['MeshAnalysisView'])
    const CacheHost = defineComponent({
      setup: () => () => h(AppRouteView, {
        cachedComponentNames: cachedComponentNames.value,
      }),
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/',
        component: CacheHost,
        children: [
          {
            path: 'rail-transit/mesh-analysis',
            name: 'mesh-analysis',
            component: MeshPage,
            meta: { title: 'MESH', keepAlive: true },
          },
          {
            path: 'rail-transit/base-data',
            name: 'rail-transit-base-data',
            component: OrdinaryPage,
            meta: { title: '基础资料' },
          },
        ],
      }],
    })
    await router.push('/rail-transit/mesh-analysis')
    const wrapper = mount(root, {
      global: {
        plugins: [router],
      },
    })
    await flushPromises()

    const initialUid = wrapper.get('[data-mesh-page]').attributes('data-uid')
    await wrapper.get('[data-mesh-page] button').trigger('click')
    expect(wrapper.get('[data-mesh-count]').text()).toBe('1')

    for (let index = 0; index < 20; index += 1) {
      await router.push('/rail-transit/base-data')
      await flushPromises()
      expect(wrapper.find('[data-mesh-page]').exists()).toBe(false)
      await router.push('/rail-transit/mesh-analysis')
      await flushPromises()
      expect(wrapper.get('[data-mesh-page]').attributes('data-uid')).toBe(initialUid)
      expect(wrapper.get('[data-mesh-count]').text()).toBe('1')
    }

    expect(lifecycle.mounted).toBe(1)
    expect(lifecycle.activated).toBe(21)
    expect(lifecycle.deactivated).toBe(20)
    expect(lifecycle.unmounted).toBe(0)
    expect(mocks.loadChart).toHaveBeenCalledTimes(1)
    expect(ordinaryLifecycle.mounted).toBe(20)
    expect(ordinaryLifecycle.unmounted).toBe(20)

    wrapper.unmount()
    expect(lifecycle.unmounted).toBe(1)
  })

  it('unmounts an inactive MESH instance when its tab removes the cache allowlist entry', async () => {
    const cachedComponentNames = ref(['MeshAnalysisView'])
    const CacheHost = defineComponent({
      setup: () => () => h(AppRouteView, {
        cachedComponentNames: cachedComponentNames.value,
      }),
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/',
        component: CacheHost,
        children: [
          {
            path: 'rail-transit/mesh-analysis',
            name: 'mesh-analysis',
            component: MeshPage,
            meta: { title: 'MESH', keepAlive: true },
          },
          {
            path: 'rail-transit/base-data',
            name: 'rail-transit-base-data',
            component: OrdinaryPage,
            meta: { title: '基础资料' },
          },
        ],
      }],
    })
    await router.push('/rail-transit/mesh-analysis')
    const wrapper = mount(root, { global: { plugins: [router] } })
    await flushPromises()
    await router.push('/rail-transit/base-data')
    await flushPromises()

    cachedComponentNames.value = []
    await nextTick()
    await flushPromises()

    expect(lifecycle.mounted).toBe(1)
    expect(lifecycle.deactivated).toBe(1)
    expect(lifecycle.unmounted).toBe(1)

    wrapper.unmount()
    expect(lifecycle.unmounted).toBe(1)
  })
})
