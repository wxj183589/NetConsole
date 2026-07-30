// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  measureAdaptiveTableHeight,
  useAdaptiveTableHeight,
} from './useAdaptiveTableHeight'

class ResizeObserverMock {
  static instances: ResizeObserverMock[] = []
  readonly observe = vi.fn()
  readonly disconnect = vi.fn()

  constructor(readonly callback: ResizeObserverCallback) {
    ResizeObserverMock.instances.push(this)
  }
}

describe('useAdaptiveTableHeight', () => {
  beforeEach(() => {
    ResizeObserverMock.instances = []
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 768 })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('keeps short tables compact and caps long tables to the viewport', () => {
    const short = measureAdaptiveTableHeight(900, 250, 5, { maxVisibleRows: 18 })
    expect(short.contentHeight).toBe(206)
    expect(short.needsInternalScroll).toBe(false)

    const regular = measureAdaptiveTableHeight(1_080, 220, 18, { maxVisibleRows: 18 })
    expect(regular.contentHeight).toBe(648)
    expect(regular.needsInternalScroll).toBe(false)

    const long = measureAdaptiveTableHeight(768, 280, 100, { maxVisibleRows: 18 })
    expect(long.maxHeight).toBe(464)
    expect(long.needsInternalScroll).toBe(true)
  })

  it('recomputes when the row count or container geometry changes', async () => {
    const component = defineComponent({
      setup() {
        const host = ref<HTMLElement | null>(null)
        const rows = ref(5)
        const table = useAdaptiveTableHeight(host, rows, { maxVisibleRows: 18 })
        return { rows, host, maxHeight: table.maxHeight, needsInternalScroll: table.needsInternalScroll }
      },
      render() {
        return h('div', {
          ref: 'host',
          'data-max-height': this.maxHeight,
          'data-scroll': this.needsInternalScroll,
        })
      },
    })
    const wrapper = mount(component, { attachTo: document.body })
    const element = wrapper.element as HTMLElement
    element.getBoundingClientRect = () => ({
      x: 0, y: 280, top: 280, left: 0, right: 900, bottom: 380,
      width: 900, height: 100, toJSON: () => ({}),
    })
    ResizeObserverMock.instances.at(-1)?.callback([], ResizeObserverMock.instances.at(-1) as unknown as ResizeObserver)
    await nextTick()
    expect(wrapper.attributes('data-scroll')).toBe('false')

    wrapper.vm.rows = 100
    await nextTick()
    expect(wrapper.attributes('data-max-height')).toBe('464')
    expect(wrapper.attributes('data-scroll')).toBe('true')
    wrapper.unmount()
    expect(ResizeObserverMock.instances.at(-1)?.disconnect).toHaveBeenCalled()
  })
})
