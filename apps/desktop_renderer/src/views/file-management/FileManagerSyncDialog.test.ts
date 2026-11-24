// @vitest-environment happy-dom
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import FileManagerSyncDialog from './FileManagerSyncDialog.vue'

const synchronize = vi.hoisted(() => vi.fn())
vi.mock('../../api/terminal', () => ({ synchronizeSftpDirectory: synchronize }))

const Button = defineComponent({
  props: ['disabled'],
  emits: ['click'],
  setup(props, { emit, slots }) {
    return () => h('button', { disabled: props.disabled, onClick: () => emit('click') }, slots.default?.())
  },
})

const Dialog = defineComponent({
  props: ['modelValue'],
  setup(props, { slots }) {
    return () => props.modelValue ? h('div', [slots.default?.(), slots.footer?.()]) : null
  },
})

it('requires a successful preview and clears an expired revision before allowing another apply', async () => {
  synchronize.mockResolvedValueOnce({ revision: 'first', rows: [], can_apply: true, transfer_count: 2, queued: [] })
    .mockRejectedValueOnce(new Error('Directory changed'))
    .mockResolvedValueOnce({ revision: 'second', rows: [], can_apply: true, transfer_count: 1, queued: [] })
    .mockResolvedValueOnce({ revision: 'second', rows: [], can_apply: true, transfer_count: 1, queued: [{}] })
  const wrapper = mount(FileManagerSyncDialog, {
    props: { sessionId: 'session', remoteDirectory: '/test', localDirectoryId: 'folder', localDirectoryLabel: 'test', allowDownload: true },
    global: { stubs: { ElButton: Button, ElDialog: Dialog, ElSelect: true, ElOption: true, ElTable: true, ElTableColumn: true, ElAlert: true } },
  })
  const button = (label: string) => wrapper.findAll('button').find(item => item.text().startsWith(label))!
  await button('Synchronize').trigger('click')
  expect(button('Queue missing files').attributes()).toHaveProperty('disabled')
  await button('Preview').trigger('click')
  await flushPromises()
  await button('Queue missing files').trigger('click')
  await flushPromises()
  expect(synchronize).toHaveBeenNthCalledWith(2, 'session', '/test', 'folder', 'both', 'modified', 'first')
  expect(button('Queue missing files').attributes()).toHaveProperty('disabled')
  await button('Preview').trigger('click')
  await flushPromises()
  await button('Queue missing files').trigger('click')
  await flushPromises()
  expect(synchronize).toHaveBeenNthCalledWith(4, 'session', '/test', 'folder', 'both', 'modified', 'second')
  expect(wrapper.emitted('submitted')).toHaveLength(1)
  wrapper.unmount()
})
