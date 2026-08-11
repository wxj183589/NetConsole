// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { defineComponent, h, useAttrs } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import OnlineMrAnalysisInfoPanel from './OnlineMrAnalysisInfoPanel.vue'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('button', attrs, slots.default?.())
  },
})

function mediaQuery(matches: boolean) {
  return {
    matches,
    media: '(max-width: 1399px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Online MR analysis information panel', () => {
  it('shows fixed analysis sections and emits unlock for a locked time', async () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery(false) as unknown as MediaQueryList)
    const wrapper = mount(OnlineMrAnalysisInfoPanel, {
      props: {
        locked: true,
        parserLabel: '解析可用',
        sections: [{ key: 'current', title: '当前分析时刻', fields: [{ label: '站点', value: '高桥西站' }] }],
      },
      global: { stubs: { ElButton: passthrough, ElTag: passthrough, ElTooltip: true } },
    })

    expect(wrapper.text()).toContain('已锁定')
    expect(wrapper.text()).toContain('当前分析时刻')
    expect(wrapper.text()).toContain('高桥西站')
    await wrapper.get('[title="解除时刻锁定"]').trigger('click')
    expect(wrapper.emitted('unlock')).toHaveLength(1)
    wrapper.unmount()
  })

  it('collapses into an overlay drawer below 1400px', async () => {
    const media = mediaQuery(false)
    vi.spyOn(window, 'matchMedia').mockReturnValue(media as unknown as MediaQueryList)
    const wrapper = mount(OnlineMrAnalysisInfoPanel, {
      props: { sections: [] },
      global: { stubs: { ElButton: passthrough, ElTag: passthrough, ElTooltip: true } },
    })

    expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 1399px)')
    const listener = media.addEventListener.mock.calls[0][1] as (event: MediaQueryListEvent) => void
    listener({ matches: true } as MediaQueryListEvent)
    await wrapper.vm.$nextTick()
    expect(wrapper.classes()).toContain('is-narrow')
    expect(wrapper.classes()).not.toContain('is-open')
    expect(wrapper.find('[title="展开分析信息"]').exists()).toBe(true)
    await wrapper.get('[title="展开分析信息"]').trigger('click')
    expect(wrapper.classes()).toContain('is-open')
    await wrapper.get('[title="收起分析信息"]').trigger('click')
    expect(wrapper.classes()).not.toContain('is-open')
    wrapper.unmount()
    expect(media.removeEventListener).toHaveBeenCalled()
  })
})
