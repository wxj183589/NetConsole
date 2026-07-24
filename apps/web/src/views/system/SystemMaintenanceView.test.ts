// @vitest-environment happy-dom

import { computed, defineComponent, h, inject, provide, type ComputedRef, type PropType } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CleanupItem, MaintenanceTask } from '../../api/systemMaintenance'

const api = vi.hoisted(() => ({
  cancelMaintenanceTask: vi.fn(),
  clearLogs: vi.fn(),
  getAbout: vi.fn(),
  getChangelog: vi.fn(),
  getLogs: vi.fn(),
  getMaintenanceTask: vi.fn(),
  maintenanceArtifactDownloadRequest: vi.fn(),
  openMaintenanceDirectory: vi.fn(),
  recoverMaintenanceTasks: vi.fn(),
  requestAboutLink: vi.fn(),
  requestOpenSourceLink: vi.fn(),
  startCleanup: vi.fn(),
  startLogExport: vi.fn(),
  startOpenSourceExport: vi.fn(),
  startOpenSourceScan: vi.fn(),
}))
const confirmDialog = vi.hoisted(() => vi.fn())
const downloadBackendResource = vi.hoisted(() => vi.fn())
const openTaskWindow = vi.hoisted(() => vi.fn())
const messages = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('../../api/systemMaintenance', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../api/systemMaintenance')>(),
  ...api,
}))
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource,
  getPlatformAdapter: () => ({ openExternalUrl: vi.fn(), openTaskWindow }),
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: confirmDialog }) }))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: messages,
}))

import SystemMaintenanceView from './SystemMaintenanceView.vue'
import source from './SystemMaintenanceView.vue?raw'

const cleanupItems: CleanupItem[] = [
  {
    item_id: 'runtime_logs',
    title: '软件运行日志',
    description: '运行日志',
    retention_policy: '保留最近 3 天',
    status: '可清理',
    file_count: 2,
    total_bytes: 512,
  },
  {
    item_id: 'runtime_cache',
    title: '页面/图表缓存',
    description: '运行缓存',
    retention_policy: '保留最近 3 天',
    status: '无需清理',
    file_count: 0,
    total_bytes: 0,
  },
]

const tableRowsKey = Symbol('maintenance-table-rows')
const TableStub = defineComponent({
  name: 'ElTable',
  props: { data: { type: Array as PropType<unknown[]>, default: () => [] } },
  setup(props, { slots }) {
    provide(tableRowsKey, computed(() => props.data))
    return () => h('div', { class: 'el-table-stub' }, slots.default?.())
  },
})
const TableColumnStub = defineComponent({
  name: 'ElTableColumn',
  setup(_props, { slots }) {
    const rows = inject<ComputedRef<unknown[]>>(tableRowsKey, computed(() => []))
    return () => h(
      'div',
      { class: 'el-table-column-stub' },
      slots.default
        ? rows.value.map((row, index) => h('div', { class: 'el-table-cell-stub', key: index }, slots.default?.({ row, $index: index })))
        : [],
    )
  },
})
const ButtonStub = defineComponent({
  name: 'ElButton',
  inheritAttrs: false,
  props: { disabled: Boolean },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', {
      ...attrs,
      disabled: props.disabled,
      onClick: (event: MouseEvent) => emit('click', event),
    }, slots.default?.())
  },
})
const CheckboxStub = defineComponent({
  name: 'ElCheckbox',
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['change'],
  setup(props, { emit }) {
    return () => h('input', {
      type: 'checkbox',
      checked: props.modelValue,
      disabled: props.disabled,
      onChange: () => emit('change', !props.modelValue),
    })
  },
})
const PaginationStub = defineComponent({
  name: 'ElPagination',
  props: { currentPage: Number, pageSize: Number, total: Number },
  emits: ['update:current-page', 'update:page-size', 'change'],
  setup(props) {
    return () => h('div', {
      class: 'el-pagination-stub',
      'data-current-page': props.currentPage,
      'data-page-size': props.pageSize,
      'data-total': props.total,
    })
  },
})
const SlotStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h('div', attrs, [slots.header?.(), slots.default?.()])
  },
})

describe('SystemMaintenanceView mounted workflow', () => {
  it('uses the route remainder for tab documents and tables without fixed workspace heights', () => {
    expect(source).toContain('.maintenance-page { display: flex; width: 100%; height: 100%;')
    expect(source).toContain('.maintenance-tabs :deep(.el-tab-pane) { position: absolute; inset: 0; display: flex; min-height: 0;')
    expect(source).toContain('.log-table-host, .maintenance-table-host { flex: 1; min-height: 0; overflow: hidden; }')
    expect(source).toContain('.document { flex: 1; min-height: 0; overflow: auto;')
    expect(source).not.toContain('height="520"')
    expect(source).not.toContain('min-height: 520px')
    expect(source).not.toContain('max-height: 620px')
    expect(source).not.toContain('height: calc(100dvh')
  })

  beforeEach(() => {
    vi.clearAllMocks()
    api.getLogs.mockResolvedValue({ items: [], page: 1, page_size: 200, total: 0, total_pages: 0 })
    api.getChangelog.mockResolvedValue({ title: '更新日志', version: '1.0', content: '' })
    api.getAbout.mockResolvedValue({ title: 'NetConsole', version: '1.0', author: '', external_tool_notice: '', repositories: [] })
    api.recoverMaintenanceTasks.mockResolvedValue([])
    api.startCleanup.mockResolvedValue(task({ action: 'cleanup_scan', cleanup_items: cleanupItems }))
    api.cancelMaintenanceTask.mockResolvedValue(task({ status: 'CANCELLED', action: 'cleanup_clean' }))
    api.startOpenSourceExport.mockResolvedValue(task({
      action: 'open_source_txt',
      available: true,
      artifact_id: 'artifact-1',
      artifact_kind: 'open_source_txt',
      artifact_name: 'open_source_notices.txt',
    }))
    api.maintenanceArtifactDownloadRequest.mockReturnValue({
      apiPath: '/api/system-maintenance/artifacts/open_source_txt/artifact-1',
      suggestedName: 'open_source_notices.txt',
    })
    confirmDialog.mockResolvedValue(true)
    downloadBackendResource.mockResolvedValue({ status: 'saved' })
    openTaskWindow.mockResolvedValue({ success: true })
  })

  it('scans with retention only and submits selected cleanup after confirmation', async () => {
    const wrapper = await mountView()

    await button(wrapper, '扫描白名单').trigger('click')
    await flushPromises()
    expect(api.startCleanup).toHaveBeenNthCalledWith(1, { mode: 'scan', retention_days: 3 })

    api.startCleanup.mockResolvedValueOnce(task({ action: 'cleanup_clean' }))
    await button(wrapper, '清理所选项目').trigger('click')
    await flushPromises()

    expect(confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
      type: 'DESTRUCTIVE',
      title: '确认安全清理',
      message: expect.stringContaining('超过 3 天'),
      confirmText: '确认清理',
    }))
    expect(api.startCleanup).toHaveBeenNthCalledWith(2, {
      mode: 'clean',
      retention_days: 3,
      selected_item_ids: ['runtime_logs'],
      confirmed: true,
    })
    wrapper.unmount()
  })

  it.each(['cancel', 'close'])('does not submit cleanup when confirmation returns %s', async (reason) => {
    api.recoverMaintenanceTasks.mockResolvedValue([task({ action: 'cleanup_scan', cleanup_items: cleanupItems })])
    confirmDialog.mockResolvedValue(false)
    const wrapper = await mountView()

    await button(wrapper, '清理所选项目').trigger('click')
    await flushPromises()

    expect(api.startCleanup).not.toHaveBeenCalled()
    expect(messages.error).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('blocks an empty selection and reports scan API failures', async () => {
    const wrapper = await mountView()
    expect(button(wrapper, '清理所选项目').attributes('disabled')).toBeDefined()
    expect(api.startCleanup).not.toHaveBeenCalled()

    api.startCleanup.mockRejectedValueOnce(new Error('扫描服务不可用'))
    await button(wrapper, '扫描白名单').trigger('click')
    await flushPromises()

    expect(messages.error).toHaveBeenCalledWith('扫描服务不可用')
    wrapper.unmount()
  })

  it('recovers an active task and delegates cancellation to the real API client', async () => {
    const active = task({ status: 'RUNNING', action: 'cleanup_clean' })
    api.recoverMaintenanceTasks.mockResolvedValue([active])
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('后台任务 · cleanup_clean')
    expect(wrapper.find('.task-status--active').exists()).toBe(true)
    expect(wrapper.find('.task-status--terminal').exists()).toBe(false)
    await button(wrapper, '取消').trigger('click')
    await flushPromises()

    expect(api.cancelMaintenanceTask).toHaveBeenCalledWith(active.task_id)
    wrapper.unmount()
  })

  it('downloads a completed TXT artifact through the desktop/browser adapter', async () => {
    const wrapper = await mountView()

    await button(wrapper, '导出 TXT').trigger('click')
    await flushPromises()
    expect(wrapper.find('.task-status--terminal').exists()).toBe(true)
    expect(wrapper.find('.task-status--active').exists()).toBe(false)
    expect(wrapper.text()).toContain('最近任务 · open_source_txt')
    expect(wrapper.findAll('button').some((item) => item.text().trim() === '取消')).toBe(false)
    await button(wrapper, '下载 Artifact').trigger('click')
    await flushPromises()

    expect(api.maintenanceArtifactDownloadRequest).toHaveBeenCalledWith(expect.objectContaining({
      artifact_id: 'artifact-1',
      artifact_name: 'open_source_notices.txt',
    }))
    expect(downloadBackendResource).toHaveBeenCalledWith({
      apiPath: '/api/system-maintenance/artifacts/open_source_txt/artifact-1',
      suggestedName: 'open_source_notices.txt',
    })
    wrapper.unmount()
  })

  it('uses the backend-provided Chinese event text and a flexible log table host', async () => {
    api.getLogs.mockResolvedValueOnce({
      items: [{
        time: '2026-07-21T10:00:00+08:00',
        level: 'INFO',
        display_level: '信息',
        display_event: '后端提供的中文事件',
        display_detail: '界面已启动',
        raw_event: 'UNMAPPED_EVENT_CODE',
        raw_detail: 'raw detail',
      }],
      page: 1,
      page_size: 200,
      total: 1,
      total_pages: 1,
    })

    const wrapper = await mountView()
    const logTable = wrapper.find('.log-table-host .nc-data-table')

    expect(wrapper.text()).toContain('后端提供的中文事件')
    expect(wrapper.text()).not.toContain('未知事件：UNMAPPED_EVENT_CODE')
    expect(wrapper.find('.log-table-host').exists()).toBe(true)
    expect(logTable.exists()).toBe(true)
    wrapper.unmount()
  })

  it('refreshes logs and corrects an invalid page after cleanup completes', async () => {
    api.recoverMaintenanceTasks.mockResolvedValue([task({ action: 'cleanup_scan', cleanup_items: cleanupItems })])
    api.getLogs
      .mockResolvedValueOnce({ items: [], page: 9, page_size: 200, total: 1800, total_pages: 9 })
      .mockResolvedValueOnce({ items: [], page: 9, page_size: 200, total: 60, total_pages: 1 })
      .mockResolvedValueOnce({ items: [], page: 1, page_size: 200, total: 60, total_pages: 1 })
    api.startCleanup.mockResolvedValueOnce(task({ action: 'cleanup_clean', status: 'COMPLETED' }))
    const wrapper = await mountView()

    await button(wrapper, '清理所选项目').trigger('click')
    await flushPromises()

    expect(api.getLogs).toHaveBeenNthCalledWith(2, expect.objectContaining({ page: 9 }))
    expect(api.getLogs).toHaveBeenNthCalledWith(3, expect.objectContaining({ page: 1 }))
    expect(wrapper.find('.el-pagination-stub').attributes('data-current-page')).toBe('1')
    expect(wrapper.find('.el-pagination-stub').attributes('data-total')).toBe('60')
    wrapper.unmount()
  })
})

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(SystemMaintenanceView, {
    global: {
      directives: { loading: () => undefined },
      stubs: {
        ElAlert: SlotStub,
        ElButton: ButtonStub,
        ElCard: SlotStub,
        ElCheckbox: CheckboxStub,
        ElDescriptions: SlotStub,
        ElDescriptionsItem: SlotStub,
        ElInput: SlotStub,
        ElInputNumber: SlotStub,
        ElOption: SlotStub,
        ElPagination: PaginationStub,
        ElProgress: SlotStub,
        ElSelect: SlotStub,
        ElTabPane: SlotStub,
        ElTable: TableStub,
        ElTableColumn: TableColumnStub,
        ElTabs: SlotStub,
        ElTag: SlotStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

function task(overrides: Partial<MaintenanceTask> = {}): MaintenanceTask {
  return {
    task_id: 'maintenance-task-1',
    status: 'COMPLETED',
    action: 'cleanup_scan',
    progress: 100,
    stage: '',
    message: '完成',
    error_message: '',
    artifact_id: '',
    artifact_kind: '',
    artifact_name: '',
    available: false,
    sha256: '',
    size_bytes: 0,
    cleanup_items: [],
    processed_files: 0,
    deleted_files: 0,
    failed_count: 0,
    freed_bytes: 0,
    deleted_log_records: 0,
    scanned_log_records: 0,
    malformed_log_records: 0,
    rewritten_log_files: 0,
    cutoff: '',
    components: [],
    ...overrides,
  }
}

function button(wrapper: VueWrapper, text: string) {
  const candidate = wrapper.findAll('button').find((item) => item.text().trim() === text)
  if (!candidate) throw new Error(`button not found: ${text}`)
  return candidate
}
