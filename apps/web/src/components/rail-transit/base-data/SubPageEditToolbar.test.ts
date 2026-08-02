// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SubPageEditToolbar from './SubPageEditToolbar.vue'

describe('subpage edit toolbar', () => {
  it('keeps locked, clean and dirty actions local to the rendered subpage', async () => {
    const wrapper = mount(SubPageEditToolbar, {
      props: { state: 'LOCKED', writable: true, dirty: false },
    })

    expect(wrapper.text()).toContain('当前子页已锁定')
    expect(wrapper.text()).toContain('解锁当前子页')
    expect(wrapper.text()).not.toContain('保存当前子页')

    await wrapper.setProps({ state: 'UNLOCKED_CLEAN' })
    expect(wrapper.text()).toContain('锁定当前子页')
    expect(wrapper.get('button:last-child').attributes('disabled')).toBeDefined()

    await wrapper.setProps({ state: 'UNLOCKED_DIRTY', dirty: true })
    expect(wrapper.text()).toContain('当前子页有未保存修改')
    expect(wrapper.text()).toContain('取消修改')
    const save = wrapper.findAll('button').find((item) => item.text().includes('保存当前子页'))!
    expect(save.attributes('disabled')).toBeUndefined()
    await save.trigger('click')
    expect(wrapper.emitted('save')).toHaveLength(1)
  })
})
