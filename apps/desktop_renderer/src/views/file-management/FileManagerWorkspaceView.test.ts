// @vitest-environment happy-dom
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'

import { activeSiteContext } from '../../stores/siteContext'
import TerminalSftpPanel from '../console/TerminalSftpPanel.vue'
import FileManagerWorkspaceView from './FileManagerWorkspaceView.vue'

const api = vi.hoisted(() => ({
  listLocalFiles: vi.fn(),
  listRemoteDevices: vi.fn(),
  createLocalDirectory: vi.fn(),
  startManagedSftpDownload: vi.fn(),
  uploadManagedSftpFile: vi.fn(),
}))
vi.mock('../../api/fileManagement', () => api)
vi.mock('../../api/terminal', () => api)
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { device_uuid: 'dev-1' } }) }))

const refreshTransfers = vi.fn(async () => undefined)
const RemoteStub = defineComponent({
  props: ['deviceUuid', 'workspaceId'],
  setup(_props, { slots }) {
    return () => h('div', slots['managed-actions']?.({
      sessionId: 'session-1',
      directory: '/files',
      selectedRemote: ['/files/startup.cfg'],
      refreshTransfers,
    }))
  },
})

const ButtonStub = defineComponent({
  props: ['disabled'],
  emits: ['click'],
  setup(props, { emit, slots }) {
    return () => h('button', { disabled: props.disabled, onClick: () => emit('click') }, slots.default?.())
  },
})

const selectedEntry = { entry_id: 'entry-1', name: 'local.cfg', is_dir: false }
const TableStub = defineComponent({
  emits: ['selection-change'],
  setup(_props, { emit }) {
    return () => h('button', { 'data-test': 'select-local', onClick: () => emit('selection-change', [selectedEntry]) })
  },
})

it('uses the active Site and attaches both panel directions to opaque local references', async () => {
  activeSiteContext.value = { siteId: 'registry-site-id-a', displayName: 'A', revision: '' }
  api.listRemoteDevices.mockResolvedValue([{ device_id: 'dev-1', name: 'Switch', address: '192.0.2.1' }])
  api.listLocalFiles.mockResolvedValue({
    site_id: 'site-a', root_entry_id: 'root-1', current_entry_id: 'root-1',
    current_label: 'downloads', items: [selectedEntry], total: 1, page: 1, limit: 200,
  })
  api.uploadManagedSftpFile.mockResolvedValue({})
  api.startManagedSftpDownload.mockResolvedValue({})
  const wrapper = mount(FileManagerWorkspaceView, {
    global: {
      directives: { loading: () => undefined },
      stubs: {
        ElButton: ButtonStub,
        ElSelect: true,
        ElOption: true,
        ElInput: true,
        ElTabs: true,
        ElTabPane: true,
        ElTable: TableStub,
        ElTableColumn: true,
        RouterLink: true,
        TerminalSftpPanel: RemoteStub,
      },
    },
  })
  try {
    await flushPromises()
    expect(api.listRemoteDevices).toHaveBeenCalledWith()
    expect(api.listLocalFiles).toHaveBeenCalledWith({ directory_id: '', page: 1, limit: 200 })
    expect(wrapper.getComponent(TerminalSftpPanel).props()).toMatchObject({ deviceUuid: 'dev-1', workspaceId: 'file-manager' })
    const transferButton = (text: string) => wrapper.findAll('button').find(button => button.text() === text)!
    expect(transferButton('Upload selected files').attributes()).toHaveProperty('disabled')
    await wrapper.get('[data-test="select-local"]').trigger('click')
    await transferButton('Upload selected files').trigger('click')
    await transferButton('Download to left folder').trigger('click')
    await flushPromises()
    expect(api.uploadManagedSftpFile).toHaveBeenCalledWith('session-1', '/files', 'entry-1', 'error')
    expect(api.startManagedSftpDownload).toHaveBeenCalledWith('session-1', '/files/startup.cfg', 'root-1')
    expect(refreshTransfers).toHaveBeenCalledTimes(2)
  } finally {
    wrapper.unmount()
    activeSiteContext.value = null
  }
})
