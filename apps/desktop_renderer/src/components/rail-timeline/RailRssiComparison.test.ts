// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import RailRssiComparison from './RailRssiComparison.vue'

class ResizeObserverMock {
  static instances: ResizeObserverMock[] = []
  observe = vi.fn()
  disconnect = vi.fn()

  constructor(readonly callback: ResizeObserverCallback) {
    ResizeObserverMock.instances.push(this)
  }
}

afterEach(() => {
  ResizeObserverMock.instances = []
  vi.unstubAllGlobals()
})

describe('Rail RSSI comparison sizing', () => {
  it('tracks the real container height with ResizeObserver and disconnects on unmount', async () => {
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
    const wrapper = mount(RailRssiComparison, {
      props: { mode: 'compare', splitRatio: 0.5, workspaceHeight: 760, minimumPaneHeight: 210 },
      slots: { active: '<div>active</div>', trackside: '<div>trackside</div>' },
    })
    const observer = ResizeObserverMock.instances.at(-1)!

    expect(observer.observe).toHaveBeenCalled()
    expect(wrapper.get('.rail-rssi-comparison__canvas').attributes('style')).toContain('height: 760px')
    observer.callback([{ contentRect: { height: 500 } } as ResizeObserverEntry], observer as unknown as ResizeObserver)
    await nextTick()
    expect(wrapper.get('.rail-rssi-comparison__canvas').attributes('style')).toContain('height: 500px')

    wrapper.unmount()
    expect(observer.disconnect).toHaveBeenCalled()
  })
})
