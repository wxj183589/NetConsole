// @vitest-environment happy-dom

import { createPinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import TaskDetailDrawer from './TaskDetailDrawer.vue'
import source from './TaskDetailDrawer.vue?raw'
import globalSource from './GlobalTaskCenter.vue?raw'
import jobCenterSource from '../../views/job-center/JobCenterView.vue?raw'

const mocks = vi.hoisted(() => ({
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
}))

vi.mock('../../api/tasks', () => ({
  listTasks: vi.fn(async () => []),
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
    openPath: vi.fn(),
    showItemInFolder: vi.fn(),
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const task = (id: string): TaskItem => ({
  id,
  type: 'mesh_log_import',
  name: `任务 ${id}`,
  status: 'FAILED',
  progress: 100,
  phase: 'parse',
  stage: 'parse',
  message: '失败',
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
  finished_time: '2026-07-29T08:01:00Z',
  updated_time: '2026-07-29T08:01:00Z',
  duration_seconds: 59,
  error_code: 'FAILED',
  error_summary: '任务失败',
  has_warning: false,
  snapshot_id: null,
  records_count: null,
  parser_version: '',
  cancellable: false,
})

describe('TaskDetailDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getTaskLogs.mockResolvedValue({ task_id: '', lines: [], message: '' })
    vi.stubGlobal('WebSocket', undefined)
  })

  it('is the single full-detail implementation shared by both task-center surfaces', () => {
    expect(globalSource).toContain("import TaskDetailDrawer from './TaskDetailDrawer.vue'")
    expect(jobCenterSource).toContain("import TaskDetailDrawer from '../../task-center/components/TaskDetailDrawer.vue'")
    expect(source).toContain('任务日志 tail')
    expect(source).toContain('保存导出表格')
    expect(globalSource).not.toContain('任务日志 tail')
    expect(jobCenterSource).not.toContain('任务日志 tail')
  })

  it('switches to the newest task and clears detail state when closed', async () => {
    let resolveA: ((value: TaskItem) => void) | undefined
    let resolveB: ((value: TaskItem) => void) | undefined
    mocks.getTask.mockImplementation((id: string) => new Promise((resolve) => {
      if (id === 'task-A') resolveA = resolve
      else resolveB = resolve
    }))
    const pinia = createPinia()
    const wrapper = shallowMount(TaskDetailDrawer, {
      props: {
        modelValue: true,
        taskId: 'task-A',
        source: 'notification',
      },
      global: { plugins: [pinia] },
    })
    const store = useTaskStore(pinia)

    await wrapper.setProps({ taskId: 'task-B' })
    resolveB?.(task('task-B'))
    await flushPromises()
    expect(store.selected?.id).toBe('task-B')

    resolveA?.(task('task-A'))
    await flushPromises()
    expect(store.selected?.id).toBe('task-B')

    store.logs = [{
      sequence: 1,
      time: '2026-07-29T08:01:00Z',
      level: 'ERROR',
      type: 'error',
      source: 'worker',
      message: '旧日志',
    }]
    await wrapper.setProps({ modelValue: false })
    await flushPromises()
    expect(store.selected).toBeNull()
    expect(store.logs).toEqual([])
    expect(store.logsExpanded).toBe(false)
    wrapper.unmount()
  })
})
