// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SubPageEditToolbar from './SubPageEditToolbar.vue'

describe('subpage edit toolbar', () => {
  it('requires the rendered subpage to unlock before draft actions are available', async () => {
    const wrapper = mount(SubPageEditToolbar, {
      props: { state: 'VIEW', dirty: false },
    })

    expect(wrapper.text()).toContain('当前子页查看中')
    const unlock = wrapper.findAll('button').find((item) => item.text().includes('解锁当前子页'))!
    expect(unlock.attributes('disabled')).toBeUndefined()
    await unlock.trigger('click')
    expect(wrapper.emitted('unlock')).toHaveLength(1)
    expect(wrapper.text()).toContain('保存当前子页')
    expect(wrapper.findAll('button').find((item) => item.text().includes('保存当前子页'))?.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ state: 'EDITING', dirty: false })
    expect(wrapper.text()).toContain('当前子页编辑中')
    expect(wrapper.text()).toContain('放弃修改')
    await wrapper.setProps({ state: 'DIRTY', dirty: true })
    expect(wrapper.text()).toContain('当前子页有未保存修改')
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
