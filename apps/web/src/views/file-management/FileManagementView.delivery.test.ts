// @vitest-environment happy-dom

import { computed, defineComponent, h, inject, provide, type ComputedRef, type PropType } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { FileDownloadTask } from '../../types/fileManagement'

const api = vi.hoisted(() => ({
  cancelFileDownload: vi.fn(),
  clearFileDownloads: vi.fn(),
  connectDeviceFiles: vi.fn(),
  createLocalDirectory: vi.fn(),
  disconnectDeviceFiles: vi.fn(),
  fileDownloadRequest: vi.fn(() => ({ apiPath: '/api/file-management/downloads/task-1/file', suggestedName: 'startup.conf' })),
  getFileManagementStatus: vi.fn(),
  listFileDownloads: vi.fn(),
  listLocalFiles: vi.fn(),
  listRemoteDevices: vi.fn(),
  listRemoteFiles: vi.fn(),
  localFileDownloadRequest: vi.fn(),
  prepareFileDesktopAction: vi.fn(),
  retryFileDownload: vi.fn(),
  startRemoteFileDownloadBatch: vi.fn(),
}))
const downloadBackendResource = vi.hoisted(() => vi.fn())
const messages = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), warning: vi.fn() }))

vi.mock('../../api/fileManagement', () => api)
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource,
  getPlatformAdapter: () => ({ openPath: vi.fn(), showItemInFolder: vi.fn() }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: messages,
  ElMessageBox: { prompt: vi.fn() },
}))

import FileManagementView from './FileManagementView.vue'

const rowsKey = Symbol('rows')
const TableStub = defineComponent({
  props: { data: { type: Array as PropType<unknown[]>, default: () => [] } },
  setup(props, { slots }) {
    provide(rowsKey, computed(() => props.data))
    return () => h('div', slots.default?.())
  },
})
const TableColumnStub = defineComponent({
  setup(_props, { slots }) {
    const rows = inject<ComputedRef<unknown[]>>(rowsKey, computed(() => []))
    return () => h('div', slots.default ? rows.value.map((row) => slots.default?.({ row })) : [])
  },
})
const ButtonStub = defineComponent({
  props: { disabled: Boolean },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', { ...attrs, disabled: props.disabled, onClick: () => emit('click') }, slots.default?.())
  },
})
const SlotStub = defineComponent({ setup(_props, { slots }) { return () => h('div', slots.default?.()) } })

describe('FileManagementView download delivery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getFileManagementStatus.mockResolvedValue({
      site_id: 'demo',
      local_files: { available: true, message: '' },
      device_files: { available: true, message: '' },
      winscp: { available: false, message: '' },
    })
    api.listRemoteDevices.mockResolvedValue([])
    api.listLocalFiles.mockResolvedValue({
      site_id: 'demo', root_entry_id: 'root', current_entry_id: 'root', parent_entry_id: '',
      current_label: '下载目录', items: [], total: 0, page: 1, limit: 500, has_more: false,
    })
    api.listFileDownloads.mockResolvedValue([completedTask()])
  })

  it('confirms a saved non-openable file and keeps native actions disabled', async () => {
    downloadBackendResource.mockResolvedValue({ status: 'saved' })
    const wrapper = mount(FileManagementView, {
      global: {
        directives: { loading: () => undefined },
        stubs: {
          ElAlert: SlotStub, ElButton: ButtonStub, ElCheckbox: SlotStub, ElInput: SlotStub,
          ElOption: SlotStub, ElPagination: SlotStub, ElProgress: SlotStub, ElSelect: SlotStub,
          ElTable: TableStub, ElTableColumn: TableColumnStub, ElTag: SlotStub,
        },
      },
    })
    await flushPromises()

    await button(wrapper, 'Save').trigger('click')
    await flushPromises()

    expect(messages.success).toHaveBeenCalledWith('文件已保存；该文件类型不支持直接打开或定位')
    expect(button(wrapper, 'Open').attributes('disabled')).toBeDefined()
    expect(button(wrapper, 'Show in folder').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})

function completedTask(): FileDownloadTask {
  return {
    task_id: 'task-1', site_id: 'demo', status: 'COMPLETED', progress: 100, stage: '', message: '完成',
    batch_id: '', source_kind: 'remote', device_name: 'MR-1', remote_name: 'startup.conf',
    downloaded_bytes: 12, total_bytes: 12, speed_bytes_per_second: 0,
    created_at: '', updated_at: '', retryable: false, retry_reason: '',
    result: {
      result_kind: 'device_file', file_ref: '', device_file_ref: 'fd1_result', name: 'startup.conf',
      size_bytes: 12, artifact_id: '', relative_path: '', sha256: '', device_id: 'device-1',
      remote_entry_id: 'remote-1', target_kind: 'device_file', mesh_import_status: '',
      mesh_imported_count: 0, mesh_duplicate_count: 0, mesh_parsed_record_count: 0, mesh_import_error: '',
    },
  }
}

function button(wrapper: ReturnType<typeof mount>, label: string) {
  const target = wrapper.findAll('button').find((item) => item.text().trim() === label)
  if (!target) throw new Error(`button not found: ${label}`)
  return target
}
