// @vitest-environment happy-dom

import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useTaskStore } from '../../stores/tasks'
import { useWorkspaceStore } from '../../stores/workspace'
import type { TaskItem } from '../../types/task'
import { requestTaskCenterOpen } from '../events'
import GlobalTaskCenter from './GlobalTaskCenter.vue'
import TaskDetailDrawer from './TaskDetailDrawer.vue'

const mocks = vi.hoisted(() => ({
  listTasks: vi.fn(),
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
  notification: vi.fn(),
  notificationClose: vi.fn(),
  setTray: vi.fn(),
  nativeOpenListener: undefined as ((context: { taskId?: string }) => void) | undefined,
}))

vi.mock('../../api/tasks', () => ({
  listTasks: mocks.listTasks,
  getTask: mocks.getTask,
  getTaskLogs: mocks.getTaskLogs,
  cancelTask: vi.fn(),
  cleanupTasks: vi.fn(),
  dismissTask: vi.fn(),
  acknowledgeTask: vi.fn(),
  acknowledgeAllTaskAlerts: vi.fn(),
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

function mountGlobal(pinia: ReturnType<typeof createPinia>) {
  return mount(GlobalTaskCenter, {
    global: {
      plugins: [pinia],
      stubs: {
        ElAlert: passthrough,
        ElBadge: passthrough,
        ElButton: passthrough,
        ElDrawer: passthrough,
        ElDropdown: passthrough,
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
    mocks.getTask.mockImplementation(async (id: string) => ({ ...runningTask, id }))
    mocks.getTaskLogs.mockResolvedValue({ task_id: runningTask.id, lines: [], message: '' })
    mocks.notification.mockImplementation(() => ({ close: mocks.notificationClose }))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    Object.defineProperty(document, 'hasFocus', { configurable: true, value: () => true })
    vi.stubGlobal('WebSocket', undefined)
  })

  it('emits one styled failure notification whose detail button opens the global drawer in place', async () => {
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
