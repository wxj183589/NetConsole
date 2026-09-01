// @vitest-environment happy-dom

import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from '../../api/client'
import { useTaskStore } from '../../stores/tasks'
import { useWorkspaceStore } from '../../stores/workspace'
import type { TaskItem } from '../../types/task'
import { requestTaskCenterOpen } from '../events'
import GlobalTaskCenter from './GlobalTaskCenter.vue'
import TaskDetailDrawer from './TaskDetailDrawer.vue'

const mocks = vi.hoisted(() => ({
  listTasks: vi.fn(),
  cleanupTasks: vi.fn(),
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
  notification: vi.fn(),
  notificationClose: vi.fn(),
  setTray: vi.fn(),
  confirm: vi.fn(),
  messages: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  nativeOpenListener: undefined as ((context: { taskId?: string }) => void) | undefined,
}))

vi.mock('../../api/tasks', () => ({
  listTasks: mocks.listTasks,
  cleanupTasks: mocks.cleanupTasks,
  getTask: mocks.getTask,
  getTaskLogs: mocks.getTaskLogs,
  cancelTask: vi.fn(),
  dismissTask: vi.fn(),
  acknowledgeTask: vi.fn(),
  acknowledgeAllTaskAlerts: vi.fn(),
}))

vi.mock('../../components/feedback/useConfirm', () => ({
  useConfirm: () => ({ confirm: mocks.confirm }),
}))

vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: vi.fn(),
  resolveWebSocketUrl: (path: string) => `ws://127.0.0.1${path}`,
  getPlatformAdapter: () => ({
    hostType: 'browser',
    setTaskTrayStatus: mocks.setTray,
    onTaskCenterOpenRequested: (listener: (context: { taskId?: string }) => void) => {
      mocks.nativeOpenListener = listener
      return () => { mocks.nativeOpenListener = undefined }
    },
    showTaskNotification: vi.fn(),
    openPath: vi.fn(),
    showItemInFolder: vi.fn(),
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessage: mocks.messages,
    ElNotification: mocks.notification,
  }
})

const runningTask: TaskItem = {
  id: 'task-1',
  type: 'mesh_log_import',
  name: 'MESH ZIP 批量导入分析',
  status: 'RUNNING',
  progress: 60,
  phase: '解析中',
  stage: 'parse',
  message: '正在解析',
  site_name: '测试局点',
  owner: 'web_rail_transit',
  executor: 'LOCAL',
  source: 'local',
  device_id: '',
  device_name: '',
  agent: '',
  mr_name: '',
  session_id: '',
  mapping_state: 'LINKED',
  created_time: '2026-07-29T08:00:00Z',
  started_time: '2026-07-29T08:00:01Z',
  finished_time: '',
  updated_time: '2026-07-29T08:01:00Z',
  duration_seconds: 59,
  error_code: '',
  error_summary: '',
  has_warning: false,
  snapshot_id: null,
  records_count: null,
  parser_version: '',
  cancellable: true,
  module: 'rail',
}
const workspaceTab = {
  id: 'tasks',
  instanceId: 'tasks',
  routeName: 'tasks',
  routeFullPath: '/tasks',
  title: '任务中心',
  identityKey: 'tasks',
  cacheKey: 'tasks',
  pinned: false,
  openedAt: 1,
  lastActivatedAt: 1,
}

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h(
      'div',
      attrs,
      Object.values(slots).flatMap((slot) => slot?.() || []),
    )
  },
})

const dropdownStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h(
      'div',
      {
        class: 'dropdown-stub',
        onClick: () => (attrs.onCommand as ((command: string) => void) | undefined)?.('completed'),
      },
      slots.default?.(),
    )
  },
})

function mountGlobal(pinia: ReturnType<typeof createPinia>) {
  return mount(GlobalTaskCenter, {
    global: {
      plugins: [pinia],
      stubs: {
        ElAlert: passthrough,
        ElBadge: passthrough,
        ElButton: passthrough,
        ElDrawer: passthrough,
        ElDropdown: dropdownStub,
        'el-dropdown': dropdownStub,
        ElDropdownItem: passthrough,
        ElDropdownMenu: passthrough,
        ElEmpty: passthrough,
        ElIcon: passthrough,
        ElProgress: passthrough,
        ElSegmented: passthrough,
        ElTag: passthrough,
        ElTooltip: passthrough,
        TaskDetailDrawer: true,
        teleport: true,
      },
    },
  })
}

describe('GlobalTaskCenter behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.nativeOpenListener = undefined
    mocks.listTasks.mockResolvedValue([runningTask])
    mocks.cleanupTasks.mockImplementation((_type: string, options?: { dryRun?: boolean }) => Promise.resolve({
      matched: 1,
      dismissed: options?.dryRun ? 0 : 1,
      skipped_active: 0,
      skipped_unacknowledged: 0,
      artifacts_deleted: 0,
      task_ids: options?.dryRun ? [] : ['task-1'],
      counts: { completed: 1, cancelled: 0, expired: 0, alerts: 0 },
    }))
    mocks.confirm.mockImplementation(async (options: { onConfirm?: () => Promise<void> }) => {
      await options.onConfirm?.()
      return true
    })
    mocks.getTask.mockImplementation(async (id: string) => ({ ...runningTask, id }))
    mocks.getTaskLogs.mockResolvedValue({ task_id: runningTask.id, lines: [], message: '' })
    mocks.notification.mockImplementation(() => ({ close: mocks.notificationClose }))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    Object.defineProperty(document, 'hasFocus', { configurable: true, value: () => true })
    vi.stubGlobal('WebSocket', undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('emits one styled failure notification whose detail button opens the global drawer in place', async () => {
    vi.useFakeTimers()
    const pinia = createPinia()
    const workspace = useWorkspaceStore(pinia)
    const navigate = vi.spyOn(workspace, 'openOrActivateRoute').mockResolvedValue(workspaceTab)
    const wrapper = mountGlobal(pinia)
    await flushPromises()
    const store = useTaskStore(pinia)

    store.tasks = [{
      ...runningTask,
      status: 'FAILED',
      progress: 100,
      error_summary: '没有可用于重建的原始 MESH 日志',
      updated_time: '2026-07-29T08:02:00Z',
      cancellable: false,
    }]
    await nextTick()
    await vi.advanceTimersByTimeAsync(800)

    expect(mocks.notification).toHaveBeenCalledOnce()
    const options = mocks.notification.mock.calls[0][0]
    expect(options).toMatchObject({
      title: 'MESH ZIP 批量导入分析失败',
      type: 'error',
      duration: 0,
      customClass: 'nc-task-notification',
      appendTo: document.body,
    })
    expect(options.message.children[0].children).toBe('没有可用于重建的原始 MESH 日志')
    expect(options.message.children[1].children).toBe('查看详情')
    expect(options.onClick).toBeUndefined()

    store.tasks = [{ ...store.tasks[0] }]
    await nextTick()
    expect(mocks.notification).toHaveBeenCalledOnce()

    options.message.children[1].props.onClick(new MouseEvent('click'))
    await nextTick()
    const detail = wrapper.findComponent(TaskDetailDrawer)
    expect(detail.props('modelValue')).toBe(true)
    expect(detail.props('taskId')).toBe('task-1')
    expect(detail.props('source')).toBe('notification')
    expect(mocks.notificationClose).toHaveBeenCalledOnce()
    expect(navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('collapses terminal device connection subtasks into one summary notification', async () => {
    vi.useFakeTimers()
    const pinia = createPinia()
    const wrapper = mountGlobal(pinia)
    await flushPromises()
    const store = useTaskStore(pinia)

    store.tasks = Array.from({ length: 50 }, (_, offset) => offset + 1).map((index) => ({
      ...runningTask,
      id: `device-test-${index}`,
      type: 'device_connection_test',
      name: `设备连接测试 · 设备-${index} · SSH`,
      status: index > 48 ? 'FAILED' : 'COMPLETED',
      has_warning: false,
      error_summary: index > 48 ? '连接超时' : '',
      updated_time: '2026-07-29T08:02:00Z',
      cancellable: false,
    }))
    await nextTick()
    await vi.advanceTimersByTimeAsync(800)

    expect(mocks.notification).toHaveBeenCalledOnce()
    const options = mocks.notification.mock.calls[0][0]
    expect(options.title).toBe('设备连接测试 · 批量完成')
    expect(options.type).toBe('error')
    expect(options.message.children[0].children).toBe('共 50 个子任务：成功 48，失败 2')
    options.message.children[1].props.onClick(new MouseEvent('click'))
    await nextTick()
    expect(wrapper.find('[data-testid="task-center-drawer"]').exists()).toBe(true)
    expect(wrapper.findComponent(TaskDetailDrawer).props('modelValue')).toBe(false)

    store.tasks = store.tasks.map((task) => ({ ...task }))
    await nextTick()
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.notification).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('keeps a single device terminal task as one notification', async () => {
    vi.useFakeTimers()
    const pinia = createPinia()
    const wrapper = mountGlobal(pinia)
    await flushPromises()
    const store = useTaskStore(pinia)

    store.tasks = [{
      ...runningTask,
      id: 'device-test-single',
      type: 'device_connection_test',
      name: '设备连接测试 · 设备-1 · SSH',
      status: 'COMPLETED',
      progress: 100,
      updated_time: '2026-07-29T08:02:00Z',
      cancellable: false,
    }]
    await nextTick()
    await vi.advanceTimersByTimeAsync(800)

    expect(mocks.notification).toHaveBeenCalledOnce()
    expect(mocks.notification.mock.calls[0][0].title).toBe('设备连接测试 · 设备-1 · SSH已完成')
    wrapper.unmount()
  })

  it('gives cleanup one outcome message and refreshes once after success', async () => {
    const pinia = createPinia()
    const wrapper = mountGlobal(pinia)
    await flushPromises()
    const initialListCalls = mocks.listTasks.mock.calls.length

    await (wrapper.vm as unknown as { cleanupHistory: (type: 'completed') => Promise<void> }).cleanupHistory('completed')
    await flushPromises()

    expect(mocks.cleanupTasks).toHaveBeenCalledTimes(2)
    expect(mocks.messages.success).toHaveBeenCalledOnce()
    expect(mocks.messages.success).toHaveBeenCalledWith('已清理 1 条已结束任务')
    expect(mocks.messages.error).not.toHaveBeenCalled()
    expect(mocks.listTasks).toHaveBeenCalledTimes(initialListCalls + 1)
    wrapper.unmount()
  })

  it('reports an empty cleanup and the production guard without generic duplicate errors', async () => {
    const pinia = createPinia()
    const wrapper = mountGlobal(pinia)
    await flushPromises()

    mocks.cleanupTasks.mockResolvedValueOnce({
      matched: 0,
      dismissed: 0,
      skipped_active: 0,
      skipped_unacknowledged: 0,
      artifacts_deleted: 0,
      task_ids: [],
      counts: { completed: 0, cancelled: 0, expired: 0, alerts: 0 },
    })
    await (wrapper.vm as unknown as { cleanupHistory: (type: 'completed') => Promise<void> }).cleanupHistory('completed')
    await flushPromises()
    expect(mocks.messages.info).toHaveBeenCalledWith('当前没有可清理的已结束任务')
    expect(mocks.messages.error).not.toHaveBeenCalled()

    mocks.cleanupTasks.mockRejectedValueOnce(new ApiRequestError(
      '当前连接真实生产数据；该维护/删除操作已阻止。',
      409,
      'PRODUCTION_WRITE_CONFIRMATION_REQUIRED',
    ))
    await (wrapper.vm as unknown as { cleanupHistory: (type: 'completed') => Promise<void> }).cleanupHistory('completed')
    await flushPromises()
    expect(mocks.messages.error).toHaveBeenCalledOnce()
    expect(mocks.messages.error).toHaveBeenCalledWith('生产模式已阻止任务清理：当前操作需要授权维护模式。')
    wrapper.unmount()
  })

  it('allows at most one cleanup request while the preview is in flight', async () => {
    let resolvePreview!: (value: unknown) => void
    mocks.cleanupTasks.mockImplementationOnce(() => new Promise((resolve) => {
      resolvePreview = resolve
    }))
    const pinia = createPinia()
    const wrapper = mountGlobal(pinia)
    await flushPromises()
    const cleanup = (wrapper.vm as unknown as { cleanupHistory: (type: 'completed') => Promise<void> }).cleanupHistory

    const first = cleanup('completed')
    await Promise.resolve()
    await cleanup('completed')
    expect(mocks.cleanupTasks).toHaveBeenCalledOnce()

    resolvePreview({
      matched: 0,
      dismissed: 0,
      skipped_active: 0,
      skipped_unacknowledged: 0,
      artifacts_deleted: 0,
      task_ids: [],
      counts: { completed: 0, cancelled: 0, expired: 0, alerts: 0 },
    })
    await first
    wrapper.unmount()
  })

  it('keeps REST and live task updates on the same business-time display path', async () => {
    const pinia = createPinia()
    const wrapper = mountGlobal(pinia)
    await flushPromises()
    const listCallsBeforeOpen = mocks.listTasks.mock.calls.length
    await wrapper.find('[data-testid="global-task-indicator"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(mocks.listTasks).toHaveBeenCalledTimes(listCallsBeforeOpen + 1)
    expect(wrapper.text()).toContain('2026-07-29 16:01:00')
    expect(wrapper.text()).not.toContain('2026-07-29T08:01:00Z')

    const store = useTaskStore(pinia)
    store.tasks = [{ ...runningTask, updated_time: '2026-07-29T08:02:00Z' }]
    await nextTick()
    expect(wrapper.text()).toContain('2026-07-29 16:02:00')
    expect(wrapper.text()).not.toContain('2026-07-29T08:02:00Z')
    wrapper.unmount()
  })

  it('routes task-center open events by task id without changing the current route', async () => {
    const pinia = createPinia()
    const workspace = useWorkspaceStore(pinia)
    const navigate = vi.spyOn(workspace, 'openOrActivateRoute').mockResolvedValue(workspaceTab)
    const wrapper = mountGlobal(pinia)
    await flushPromises()

    requestTaskCenterOpen()
    await nextTick()
    expect(wrapper.find('[data-testid="task-center-drawer"]').exists()).toBe(true)

    requestTaskCenterOpen({ taskId: 'task-local' })
    await nextTick()
    expect(wrapper.findComponent(TaskDetailDrawer).props('taskId')).toBe('task-local')
    expect(navigate).not.toHaveBeenCalled()

    mocks.nativeOpenListener?.({ taskId: 'task-native' })
    await nextTick()
    expect(wrapper.findComponent(TaskDetailDrawer).props('taskId')).toBe('task-native')
    expect(wrapper.findComponent(TaskDetailDrawer).props('source')).toBe('native')
    expect(navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens list details in place and only navigates from the full task-center button', async () => {
    const pinia = createPinia()
    const workspace = useWorkspaceStore(pinia)
    const navigate = vi.spyOn(workspace, 'openOrActivateRoute').mockResolvedValue(workspaceTab)
    const wrapper = mountGlobal(pinia)
    await flushPromises()

    requestTaskCenterOpen()
    await nextTick()
    await wrapper.get('[data-testid="task-summary-detail-task-1"]').trigger('click')
    expect(wrapper.findComponent(TaskDetailDrawer).props('taskId')).toBe('task-1')
    expect(wrapper.findComponent(TaskDetailDrawer).props('source')).toBe('global-list')
    expect(navigate).not.toHaveBeenCalled()

    requestTaskCenterOpen()
    await nextTick()
    await wrapper.get('[data-testid="navigate-full-task-center"]').trigger('click')
    expect(navigate).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledWith('/tasks')
    wrapper.unmount()
  })
})
