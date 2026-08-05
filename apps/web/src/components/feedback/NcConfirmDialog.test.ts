// @vitest-environment happy-dom

import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NcConfirmDialog from './NcConfirmDialog.vue'
import { confirmState, useConfirm } from './useConfirm'

const DialogStub = defineComponent({
  name: 'ElDialog',
  props: {
    modelValue: Boolean,
    title: String,
    width: String,
    alignCenter: Boolean,
    showClose: Boolean,
    closeOnPressEscape: Boolean,
  },
  emits: ['update:modelValue', 'close', 'opened'],
  setup(props, { emit, slots }) {
    const close = () => {
      emit('update:modelValue', false)
      emit('close')
    }
    return () => props.modelValue
      ? h('section', {
          class: 'dialog-stub',
          role: 'dialog',
          'aria-modal': 'true',
          'data-title': props.title,
          'data-width': props.width,
          'data-align-center': props.alignCenter,
          'data-close-on-escape': props.closeOnPressEscape,
          onKeydown: (event: KeyboardEvent) => {
            if (event.key === 'Escape' && props.closeOnPressEscape) close()
          },
        }, [
        props.showClose ? h('button', { class: 'dialog-close', onClick: close }, '关闭') : null,
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
    return () => h('button', {
      disabled: props.disabled || props.loading,
      'data-loading': props.loading ? 'true' : 'false',
      onClick: () => emit('click'),
    }, slots.default?.())
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

  it('focuses cancel, highlights dynamic content, and locks duplicate async confirmation', async () => {
    let finishCleanup!: () => void
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => { finishCleanup = resolve }))
    const wrapper = mount(NcConfirmDialog, {
      attachTo: document.body,
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
      type: 'DANGER',
      title: '清理任务记录',
      message: '将从任务中心移除 5 个已处理的失败或警告任务。',
      highlight: '5 个',
      notice: '不会影响运行中或等待中的任务，也不会删除日志、采集文件或导出结果。',
      width: 'min(468px, calc(100vw - 32px))',
      confirmText: '确认清理',
      confirmLoadingText: '正在清理…',
      onConfirm,
    })
    await flushPromises()

    const dialog = wrapper.get('.dialog-stub')
    expect(dialog.attributes('role')).toBe('dialog')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('data-width')).toContain('468px')
    expect(wrapper.get('.nc-confirm-message strong').text()).toBe('5 个')
    expect(wrapper.get('.nc-confirm-notice').text()).toContain('不会影响运行中或等待中的任务')
    expect(document.activeElement?.textContent).toBe('取消')

    const confirmButton = wrapper.findAll('button').find((button) => button.text() === '确认清理')!
    await confirmButton.trigger('click')
    await confirmButton.trigger('click')
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('正在清理…')
    expect(wrapper.findAll('button').find((button) => button.text() === '正在清理…')?.attributes('disabled')).toBeDefined()
    expect(wrapper.find('.dialog-close').exists()).toBe(false)

    finishCleanup()
    await flushPromises()
    await expect(promise).resolves.toBe(true)
    expect(confirmState.request).toBeNull()
    wrapper.unmount()
  })

  it('keeps the dialog open after a failed async action and allows cancellation', async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error('清理失败'))
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
      type: 'DANGER',
      title: '清理任务记录',
      message: '确认清理？',
      confirmText: '确认清理',
      onConfirm,
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '确认清理')!.trigger('click')
    await flushPromises()

    expect(onConfirm).toHaveBeenCalledOnce()
    expect(confirmState.request).not.toBeNull()
    expect(wrapper.find('.dialog-stub').exists()).toBe(true)
    expect(wrapper.findAll('button').find((button) => button.text() === '确认清理')?.attributes('disabled')).toBeUndefined()

    await wrapper.findAll('button').find((button) => button.text() === '取消')!.trigger('click')
    await expect(promise).resolves.toBe(false)
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

  it('requires an exact typed name for destructive confirmations', async () => {
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
      type: 'DESTRUCTIVE',
      title: '删除局点',
      message: '局点将移入 .trash。',
      confirmationText: '杭州地铁10号线',
      confirmationLabel: '输入完整局点名称',
      confirmText: '移入 .trash',
    })
    await flushPromises()
    const confirmButton = wrapper.findAll('button').find((button) => button.text() === '移入 .trash')!
    expect(confirmButton.attributes('disabled')).toBeDefined()

    await wrapper.get('[data-testid="nc-confirm-typed-input"]').setValue('杭州地铁10号')
    expect(confirmButton.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="nc-confirm-typed-input"]').setValue('杭州地铁10号线')
    await confirmButton.trigger('click')

    await expect(promise).resolves.toBe(true)
    wrapper.unmount()
  })

  it('cancels through the close button and Escape without running the action', async () => {
    const wrapper = mount(NcConfirmDialog, {
      global: { stubs: { ElDialog: DialogStub, ElButton: ButtonStub, ElAlert: Passthrough, ElCheckbox: CheckboxStub, ElIcon: Passthrough } },
    })
    const onConfirm = vi.fn()
    const promise = useConfirm().confirm({ title: '操作', message: '确认？', onConfirm })
    await flushPromises()
    await wrapper.get('.dialog-close').trigger('click')
    await expect(promise).resolves.toBe(false)
    expect(onConfirm).not.toHaveBeenCalled()

    const escapePromise = useConfirm().confirm({ title: '操作', message: '确认？', onConfirm })
    await flushPromises()
    await wrapper.get('.dialog-stub').trigger('keydown', { key: 'Escape' })
    await expect(escapePromise).resolves.toBe(false)
    expect(onConfirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
