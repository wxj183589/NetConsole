// @vitest-environment happy-dom

import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import NcConfirmDialog from './NcConfirmDialog.vue'
import { confirmState, resolveConfirm, useConfirm } from './useConfirm'

const DialogStub = defineComponent({
  name: 'ElDialog',
  props: { modelValue: Boolean, title: String, width: String, alignCenter: Boolean },
  setup(props, { slots }) {
    return () => props.modelValue
      ? h('section', { class: 'dialog-stub', 'data-title': props.title, 'data-width': props.width, 'data-align-center': props.alignCenter }, [
        slots.default?.(),
        slots.footer?.(),
      ])
      : null
  },
})
const ButtonStub = defineComponent({
  name: 'ElButton',
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { emit, slots }) {
    return () => h('button', { disabled: props.disabled || props.loading, onClick: () => emit('click') }, slots.default?.())
  },
})
const Passthrough = defineComponent({ name: 'ElementStub', setup(_props, { slots }) { return () => h('span', slots.default?.()) } })
const CheckboxStub = defineComponent({
  name: 'ElCheckbox',
  props: { modelValue: Boolean },
  emits: ['update:modelValue'],
  setup(props, { emit, slots }) {
    return () => h('label', { class: 'checkbox-stub' }, [
      h('input', { type: 'checkbox', checked: props.modelValue, onChange: () => emit('update:modelValue', true) }),
      slots.default?.(),
    ])
  },
})

describe('NcConfirmDialog', () => {
  beforeEach(() => {
    confirmState.request = null
    confirmState.providerReady = false
  })

  it('renders a centered, bounded dialog and resolves an explicit action', async () => {
    const wrapper = mount(NcConfirmDialog, {
      global: {
        stubs: {
          ElDialog: DialogStub,
          ElButton: ButtonStub,
          ElAlert: Passthrough,
          ElCheckbox: CheckboxStub,
          ElIcon: Passthrough,
        },
      },
    })
    const promise = useConfirm().confirm({ type: 'DANGER', title: '删除设备', message: '确认删除？', confirmText: '确认删除' })
    await flushPromises()

    const dialog = wrapper.get('.dialog-stub')
    expect(dialog.attributes('data-align-center')).toBe('true')
    expect(dialog.attributes('data-width')).toContain('620px')
    expect(dialog.attributes('data-title')).toBe('删除设备')
    expect(wrapper.text()).toContain('确认删除？')
    await wrapper.findAll('button').find((button) => button.text() === '确认删除')!.trigger('click')
    await expect(promise).resolves.toBe(true)
    expect(confirmState.request).toBeNull()
    wrapper.unmount()
  })

  it('requires acknowledgement for security confirmations', async () => {
    const wrapper = mount(NcConfirmDialog, {
      global: {
        stubs: {
          ElDialog: DialogStub,
          ElButton: ButtonStub,
          ElAlert: Passthrough,
          ElCheckbox: CheckboxStub,
          ElIcon: Passthrough,
        },
      },
    })
    const promise = useConfirm().confirm({
      type: 'SECURITY',
      title: '传递终端密码',
      message: '密码可能被本机进程查看。',
      requireAcknowledgement: true,
      acknowledgementText: '我已了解风险',
      confirmText: '确认启用',
    })
    await flushPromises()
    const confirmButton = wrapper.findAll('button').find((button) => button.text() === '确认启用')
    expect(confirmButton?.attributes('disabled')).toBeDefined()
    await wrapper.get('.checkbox-stub input').setValue(true)
    await wrapper.findAll('button').find((button) => button.text() === '确认启用')!.trigger('click')
    await expect(promise).resolves.toBe(true)
    wrapper.unmount()
  })

  it('cancels through the close path', async () => {
    const wrapper = mount(NcConfirmDialog, {
      global: { stubs: { ElDialog: DialogStub, ElButton: ButtonStub, ElAlert: Passthrough, ElCheckbox: CheckboxStub, ElIcon: Passthrough } },
    })
    const promise = useConfirm().confirm({ title: '操作', message: '确认？' })
    await flushPromises()
    resolveConfirm('cancel')
    await expect(promise).resolves.toBe(false)
    wrapper.unmount()
  })
})
