// @vitest-environment happy-dom

import ElementPlus, { ElPopover } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import NcMultiValueFilter from './NcMultiValueFilter.vue'

afterEach(() => { document.body.innerHTML = '' })

describe('NcMultiValueFilter', () => {
  it('opens a WPS-style checklist and commits only explicitly confirmed selections', async () => {
    const wrapper = mount(NcMultiValueFilter, {
      attachTo: document.body,
      props: { modelValue: [], options: ['站点A', '站点B', '站点C'], placeholder: '全部站点' },
      global: { plugins: [ElementPlus] },
    })
    wrapper.getComponent(ElPopover).vm.$emit('update:visible', true)
    await flushPromises()
    const checkboxes = Array.from(document.querySelectorAll('.nc-multi-value-filter__list .el-checkbox'))
    expect(checkboxes).toHaveLength(3)
    expect(Array.from(document.querySelectorAll<HTMLInputElement>('.nc-multi-value-filter__list input')).map((input) => input.checked)).toEqual([true, true, true])
    ;(checkboxes[0]?.querySelector('input') as HTMLInputElement).click()
    await flushPromises()
    ;(checkboxes[2]?.querySelector('input') as HTMLInputElement).click()
    await flushPromises()
    expect(Array.from(document.querySelectorAll<HTMLInputElement>('.nc-multi-value-filter__list input')).map((input) => input.checked)).toEqual([false, true, false])
    expect(wrapper.emitted('change')).toBeUndefined()
    const confirm = Array.from(document.querySelectorAll('.nc-multi-value-filter__footer button')).find(
      (button) => button.textContent?.includes('确定'),
    )
    ;(confirm as HTMLElement).click()
    await flushPromises()
    expect(wrapper.emitted('change')?.at(-1)?.[0]).toEqual(['站点B'])
    wrapper.unmount()
  })

  it('searches by display labels and treats all selected as unrestricted', async () => {
    const wrapper = mount(NcMultiValueFilter, {
      attachTo: document.body,
      props: {
        modelValue: ['devices'], options: ['devices', 'rail'],
        labels: { devices: '设备管理', rail: '轨道交通' }, placeholder: '全部模块',
      },
      global: { plugins: [ElementPlus] },
    })
    wrapper.getComponent(ElPopover).vm.$emit('update:visible', true)
    await flushPromises()
    const search = document.querySelector('.nc-multi-value-filter__panel input') as HTMLInputElement
    search.value = '轨道'
    search.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    expect(document.querySelectorAll('.nc-multi-value-filter__list .el-checkbox')).toHaveLength(1)
    const choose = document.querySelector('.nc-multi-value-filter__list .el-checkbox') as HTMLElement
    ;(choose.querySelector('input') as HTMLInputElement).click()
    await flushPromises()
    const confirm = Array.from(document.querySelectorAll('.nc-multi-value-filter__footer button')).find(
      (button) => button.textContent?.includes('确定'),
    )
    ;(confirm as HTMLElement).click()
    await flushPromises()
    expect(wrapper.emitted('change')?.at(-1)?.[0]).toEqual([])
    wrapper.unmount()
  })

  it('only selects one option in the draft and commits it only after confirmation', async () => {
    const wrapper = mount(NcMultiValueFilter, {
      attachTo: document.body,
      props: { modelValue: ['站点A'], options: ['站点A', '站点B', '站点C'], placeholder: '全部站点' },
      global: { plugins: [ElementPlus] },
    })
    wrapper.getComponent(ElPopover).vm.$emit('update:visible', true)
    await flushPromises()
    const only = Array.from(document.querySelectorAll('.nc-multi-value-filter__only')).find(
      (button) => button.textContent?.includes('仅选择此项') && button.parentElement?.textContent?.includes('站点B'),
    ) as HTMLElement
    only.click()
    await flushPromises()
    expect(Array.from(document.querySelectorAll<HTMLInputElement>('.nc-multi-value-filter__list input')).map((input) => input.checked)).toEqual([false, true, false])
    expect(wrapper.emitted('change')).toBeUndefined()
    const cancel = Array.from(document.querySelectorAll('.nc-multi-value-filter__footer button')).find(
      (button) => button.textContent?.includes('取消'),
    ) as HTMLElement
    cancel.click()
    await flushPromises()
    expect(wrapper.emitted('change')).toBeUndefined()
    wrapper.getComponent(ElPopover).vm.$emit('update:visible', true)
    await flushPromises()
    expect(Array.from(document.querySelectorAll<HTMLInputElement>('.nc-multi-value-filter__list input')).map((input) => input.checked)).toEqual([true, false, false])
    wrapper.unmount()
  })

  it('preserves the former custom vendor filtering capability without broadening to all', async () => {
    const wrapper = mount(NcMultiValueFilter, {
      attachTo: document.body,
      props: { modelValue: [], options: ['H3C', 'ZTE'], allowCustom: true, placeholder: '全部厂商' },
      global: { plugins: [ElementPlus] },
    })
    wrapper.getComponent(ElPopover).vm.$emit('update:visible', true)
    await flushPromises()
    const search = document.querySelector('.nc-multi-value-filter__panel input') as HTMLInputElement
    search.value = 'CustomVendor'
    search.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    ;(document.querySelector('.nc-multi-value-filter__create') as HTMLElement).click()
    await flushPromises()
    const confirm = Array.from(document.querySelectorAll('.nc-multi-value-filter__footer button')).find(
      (button) => button.textContent?.includes('确定'),
    )
    ;(confirm as HTMLElement).click()
    await flushPromises()
    expect(wrapper.emitted('change')?.at(-1)?.[0]).toEqual(['CustomVendor'])
    wrapper.unmount()
  })
})
