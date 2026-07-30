// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import NcFloatingWindow from './NcFloatingWindow.vue'

const global = {
  stubs: {
    ElButton: {
      props: ['title'],
      emits: ['click'],
      template: '<button :title="title" @click="$emit(\'click\')"><slot /></button>',
    },
  },
}

describe('NcFloatingWindow', () => {
  beforeEach(() => {
    localStorage.clear()
    Object.defineProperty(document.documentElement, 'clientWidth', { configurable: true, value: 1_366 })
    Object.defineProperty(document.documentElement, 'clientHeight', { configurable: true, value: 768 })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('renders without a modal mask and leaves the surrounding layer click-through', async () => {
    const wrapper = mount(NcFloatingWindow, {
      props: {
        modelValue: true,
        title: '列车07',
        routeKey: '/rail/ground',
        windowId: 'ping',
      },
      slots: { default: '<button class="content-action">主内容操作</button>' },
      global,
    })
    await flushPromises()

    expect(document.body.querySelector('.el-overlay')).toBeNull()
    expect(document.body.querySelector('.nc-floating-layer')).not.toBeNull()
    expect(document.body.querySelectorAll('[data-resize-edge]')).toHaveLength(8)
    expect(wrapper.html()).not.toContain('el-overlay')
    expect(document.body.querySelector('.nc-floating-layer')?.classList).toContain('nc-floating-layer')
    wrapper.unmount()
  })

  it('clamps dragging, maximizes, restores, and persists the normal rectangle', async () => {
    const wrapper = mount(NcFloatingWindow, {
      props: {
        modelValue: true,
        title: '列车07',
        routeKey: '/rail/ground',
        windowId: 'ping',
      },
      global,
    })
    await flushPromises()
    const view = wrapper.vm as unknown as {
      rect: { left: number; top: number; width: number; height: number }
      maximized: boolean
      startDrag: (event: PointerEvent) => void
      toggleMaximize: () => void
    }
    view.startDrag(new PointerEvent('pointerdown', { button: 0, clientX: 500, clientY: 300 }))
    document.dispatchEvent(new PointerEvent('pointermove', { clientX: -2_000, clientY: -2_000 }))
    document.dispatchEvent(new PointerEvent('pointerup'))
    expect(view.rect.left).toBeGreaterThanOrEqual(8)
    expect(view.rect.top).toBeGreaterThanOrEqual(56)

    const normal = { ...view.rect }
    view.toggleMaximize()
    expect(view.maximized).toBe(true)
    expect(view.rect.top).toBe(56)
    view.toggleMaximize()
    expect(view.maximized).toBe(false)
    expect(view.rect).toMatchObject(normal)
    expect(localStorage.length).toBe(1)
    wrapper.unmount()
  })

  it('restores the persisted rectangle for the same user, route, and window', async () => {
    const props = {
      modelValue: true,
      title: '列车07',
      routeKey: '/rail/ground',
      windowId: 'ping',
      userKey: 'operator-a',
    }
    const first = mount(NcFloatingWindow, { props, global })
    await flushPromises()
    const firstView = first.vm as unknown as {
      rect: { left: number; top: number; width: number; height: number }
    }
    Object.assign(firstView.rect, { left: 144, top: 96, width: 920, height: 600 })
    first.unmount()

    const second = mount(NcFloatingWindow, { props, global })
    await flushPromises()
    const secondView = second.vm as unknown as {
      rect: { left: number; top: number; width: number; height: number }
    }
    expect(secondView.rect).toMatchObject({ left: 144, top: 96, width: 920, height: 600 })
    second.unmount()
  })

  it('removes active pointer and viewport listeners on unmount', async () => {
    const addDocument = vi.spyOn(document, 'addEventListener')
    const removeDocument = vi.spyOn(document, 'removeEventListener')
    const addWindow = vi.spyOn(window, 'addEventListener')
    const removeWindow = vi.spyOn(window, 'removeEventListener')
    const wrapper = mount(NcFloatingWindow, {
      props: {
        modelValue: true,
        title: '列车07',
        routeKey: '/rail/ground',
        windowId: 'ping',
      },
      global,
    })
    await flushPromises()
    ;(wrapper.vm as unknown as { startDrag: (event: PointerEvent) => void })
      .startDrag(new PointerEvent('pointerdown', { button: 0, clientX: 400, clientY: 300 }))
    const pointerMove = addDocument.mock.calls.find(([type]) => type === 'pointermove')
    const resize = addWindow.mock.calls.find(([type]) => type === 'resize')
    wrapper.unmount()

    expect(removeDocument).toHaveBeenCalledWith(...pointerMove!)
    expect(removeWindow).toHaveBeenCalledWith(...resize!)
  })
})
