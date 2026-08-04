// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SubPageEditToolbar from './SubPageEditToolbar.vue'

describe('subpage edit toolbar', () => {
  it('keeps ready, dirty and failed draft actions local to the rendered subpage', async () => {
    const wrapper = mount(SubPageEditToolbar, {
      props: { state: 'READY', dirty: false },
    })

    expect(wrapper.text()).toContain('当前子页已保存')
    expect(wrapper.text()).toContain('保存当前子页')
    expect(wrapper.findAll('button').filter((item) => ['放弃修改', '保存当前子页'].includes(item.text())).every((item) => item.attributes('disabled') !== undefined)).toBe(true)

    await wrapper.setProps({ state: 'DIRTY', dirty: true })
    expect(wrapper.text()).toContain('当前子页有未保存修改')
    expect(wrapper.text()).toContain('放弃修改')
    const save = wrapper.findAll('button').find((item) => item.text().includes('保存当前子页'))!
    expect(save.attributes('disabled')).toBeUndefined()
    await save.trigger('click')
    expect(wrapper.emitted('save')).toHaveLength(1)

    await wrapper.setProps({ state: 'SAVE_FAILED' })
    expect(wrapper.text()).toContain('保存失败，草稿已保留')
    const discard = wrapper.findAll('button').find((item) => item.text().includes('放弃修改'))!
    await discard.trigger('click')
    expect(wrapper.emitted('discard')).toHaveLength(1)
  })

  it('shows read-only state without draft actions', () => {
    const wrapper = mount(SubPageEditToolbar, {
      props: { state: 'READ_ONLY', dirty: false },
    })

    expect(wrapper.text()).toContain('只读')
    expect(wrapper.text()).not.toContain('保存当前子页')
    expect(wrapper.text()).not.toContain('放弃修改')
  })
})
