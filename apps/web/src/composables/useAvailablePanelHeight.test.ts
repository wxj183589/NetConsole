// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  measureAvailablePanelHeight,
  useAvailablePanelHeight,
} from './useAvailablePanelHeight'

class ResizeObserverMock {
  static instances: ResizeObserverMock[] = []
  readonly observe = vi.fn()
  readonly disconnect = vi.fn()

  constructor(readonly callback: ResizeObserverCallback) {
    ResizeObserverMock.instances.push(this)
  }
}

describe('useAvailablePanelHeight', () => {
  beforeEach(() => {
    ResizeObserverMock.instances = []
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 1080 })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('uses the viewport remainder while preserving the minimum', () => {
    expect(measureAvailablePanelHeight(1080, 430, { minHeight: 420, bottomGap: 70 })).toBe(580)
    expect(measureAvailablePanelHeight(720, 430, { minHeight: 420, bottomGap: 70 })).toBe(420)
  })

  it('recalculates after layout and resize observer changes', async () => {
    const component = defineComponent({
      setup() {
        const host = ref<HTMLElement | null>(null)
        const panel = useAvailablePanelHeight(host, { minHeight: 420, bottomGap: 70 })
        return () => h('div', { ref: host, 'data-height': panel.height.value })
      },
    })
    const wrapper = mount(component, { attachTo: document.body })
    const element = wrapper.element as HTMLElement
    element.getBoundingClientRect = () => ({
      x: 0, y: 400, top: 400, left: 0, right: 900, bottom: 500,
      width: 900, height: 100, toJSON: () => ({}),
    })
    ResizeObserverMock.instances.at(-1)?.callback([], ResizeObserverMock.instances.at(-1) as unknown as ResizeObserver)
    await nextTick()

    expect(wrapper.attributes('data-height')).toBe('610')
    wrapper.unmount()
    expect(ResizeObserverMock.instances.at(-1)?.disconnect).toHaveBeenCalled()
  })
})
