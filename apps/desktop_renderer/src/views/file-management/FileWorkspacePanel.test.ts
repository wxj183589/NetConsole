// @vitest-environment happy-dom
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FileWorkspacePanel from './FileWorkspacePanel.vue'

const api = vi.hoisted(() => ({
  browseFileWorkspace: vi.fn(),
  cancelFileWorkspaceTask: vi.fn(),
  listFileWorkspaceTasks: vi.fn(),
  operateFileWorkspace: vi.fn(),
  uploadFileWorkspace: vi.fn(),
  workspaceFileRequest: vi.fn(entry => ({ apiPath: `/api/file-management/workspace/files/${entry.id}`, suggestedName: entry.name })),
  downloadBackendResource: vi.fn(),
  prepareFileDesktopAction: vi.fn(),
}))
vi.mock('../../api/fileWorkspace', () => api)
vi.mock('../../platform/runtime', () => api)
vi.mock('../../api/fileManagement', () => api)
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('element-plus', async importOriginal => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: { info: vi.fn(), error: vi.fn() },
  ElMessageBox: { confirm: vi.fn(async () => undefined), prompt: vi.fn(async () => ({ value: 'new.cfg' })) },
}))

const entry = { id: 'opaque-file', name: 'startup.cfg', directory: false, size: 20, modified: 0, mode: '-rw-r--r--' }
const Button = defineComponent({
  props: ['disabled'], emits: ['click'],
  setup(props, { emit, slots }) {
    return () => h('button', { disabled: props.disabled, onClick: () => emit('click') }, slots.default?.())
  },
})
const Table = defineComponent({
  props: ['data'], emits: ['current-change'],
  setup(props, { emit }) {
    return () => h('button', { class: 'select-entry', onClick: () => emit('current-change', props.data[0]) }, 'select')
  },
})
const Select = defineComponent({
  props: ['modelValue'], emits: ['update:modelValue', 'change'],
  setup(_props, { emit }) {
    return () => h('button', { class: 'change-root', onClick: () => { emit('update:modelValue', 'ftp'); emit('change', 'ftp') } }, 'FTP')
  },
})
function render() {
  return mount(FileWorkspacePanel, { global: {
    directives: { loading: () => undefined },
    stubs: { ElButton: Button, ElTable: Table, ElSelect: Select, ElOption: true, ElTableColumn: true, ElAlert: true, ElProgress: true, RouterLink: true },
  } })
}
function button(wrapper: ReturnType<typeof render>, pane: number, label: string) {
  return wrapper.findAll('.workspace-file-pane')[pane]!.findAll('button').find(item => item.text() === label)!
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  api.browseFileWorkspace.mockImplementation(async kind => ({ kind, directory_id: `${kind}-root`, parent_id: '', label: '.', writable: true, items: kind === 'downloads' ? [entry] : [] }))
  api.listFileWorkspaceTasks.mockResolvedValue({ items: [] })
  api.operateFileWorkspace.mockResolvedValue({ task_id: 'copy-task', action: 'copy', status: 'WAITING', current: 0, total: 20, sha256: '', error: '' })
  api.downloadBackendResource.mockResolvedValue({ status: 'cancelled' })
})
afterEach(() => { vi.useRealTimers() })

describe('service-root file panel', () => {
  it('opens the active directory through an opaque desktop action after a click', async () => {
    const executeFileDesktopAction = vi.fn(async () => ({ success: true }))
    vi.stubGlobal('netconsoleDesktop', { executeFileDesktopAction })
    api.prepareFileDesktopAction.mockResolvedValue({ action_ref: 'opaque-action' })
    const wrapper = render()
    try {
      await flushPromises()
      expect(api.prepareFileDesktopAction).not.toHaveBeenCalled()
      await button(wrapper, 1, 'Open in Explorer').trigger('click')
      await flushPromises()
      expect(api.prepareFileDesktopAction).toHaveBeenCalledWith('open_workspace_dir', { local_entry_id: 'http-root' })
      expect(executeFileDesktopAction).toHaveBeenCalledWith('opaque-action')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })
  it('copies opaque references, saves only after click, switches root and stops polling on unmount', async () => {
    const wrapper = render()
    await flushPromises()
    expect(api.downloadBackendResource).not.toHaveBeenCalled()
    await wrapper.findAll('.select-entry')[0]!.trigger('click')
    await button(wrapper, 0, 'Copy to other pane').trigger('click')
    await flushPromises()
    expect(api.operateFileWorkspace).toHaveBeenCalledWith(expect.objectContaining({ action: 'copy', source: 'opaque-file', destination: 'http-root', name: 'startup.cfg' }))
    await button(wrapper, 0, 'Save as').trigger('click')
    await flushPromises()
    expect(api.downloadBackendResource).toHaveBeenCalledWith({ apiPath: '/api/file-management/workspace/files/opaque-file', suggestedName: 'startup.cfg' })
    await wrapper.findAll('.change-root')[1]!.trigger('click')
    await flushPromises()
    expect(api.browseFileWorkspace).toHaveBeenCalledWith('ftp', '')
    wrapper.unmount()
    const polls = api.listFileWorkspaceTasks.mock.calls.length
    await vi.advanceTimersByTimeAsync(3000)
    expect(api.listFileWorkspaceTasks).toHaveBeenCalledTimes(polls)
  })

  it('blocks running-root writes and does not upload after empty file selection', async () => {
    api.browseFileWorkspace.mockImplementation(async kind => ({ kind, directory_id: `${kind}-root`, parent_id: '', label: '.', writable: kind === 'downloads', items: [entry] }))
    const wrapper = render()
    try {
      await flushPromises()
      await wrapper.findAll('.select-entry')[0]!.trigger('click')
      await wrapper.findAll('.select-entry')[1]!.trigger('click')
      expect(button(wrapper, 0, 'Copy to other pane').attributes()).toHaveProperty('disabled')
      expect(button(wrapper, 1, 'Rename').attributes()).toHaveProperty('disabled')
      expect(wrapper.findAll('.workspace-file-pane')[1]!.find('input[type=file]').exists()).toBe(false)
      await wrapper.get('input[type=file]').trigger('change')
      expect(api.uploadFileWorkspace).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
})
