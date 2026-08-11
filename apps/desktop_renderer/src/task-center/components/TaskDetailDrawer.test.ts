// @vitest-environment happy-dom

import { createPinia } from 'pinia'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
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
  downloadBackendResource: vi.fn(),
  openPath: vi.fn(),
  showItemInFolder: vi.fn(),
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
  downloadBackendResource: mocks.downloadBackendResource,
  resolveWebSocketUrl: (path: string) => `ws://127.0.0.1${path}`,
  getPlatformAdapter: () => ({
    openPath: mocks.openPath,
    showItemInFolder: mocks.showItemInFolder,
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

  it('renders UTC task details and log times in the business timezone', async () => {
    mocks.getTask.mockResolvedValue(task('task-time'))
    mocks.getTaskLogs.mockResolvedValue({
      task_id: 'task-time',
      lines: [{
        sequence: 1,
        time: '2026-08-06T15:31:15.538Z',
        level: 'ERROR',
        type: 'error',
        source: 'worker',
        message: '任务失败',
      }],
      message: '',
    })
    const wrapper = mount(TaskDetailDrawer, {
      props: { modelValue: true, taskId: 'task-time' },
      global: { plugins: [createPinia()] },
    })

    await flushPromises()
    const rendered = document.body.textContent || ''
    expect(rendered).toContain('2026-07-29 16:01:00')
    expect(rendered).not.toContain('2026-07-29T08:01:00Z')
    expect(source).toContain('formatTaskDateTime(line.time)')
    wrapper.unmount()
  })

  it('renders WPS format warnings without changing the completed task lifecycle', async () => {
    mocks.getTask.mockResolvedValue({
      ...task('wps-format-warning'),
      type: 'trackside_ap_wps_sync',
      status: 'COMPLETED',
      business_status: 'SUCCESS_WITH_WARNINGS',
      warning_count: 1,
      error_code: '',
      error_summary: '',
      details: {
        status: 'SUCCESS_WITH_WARNINGS',
        targets: [{
          target_code: 'wps_standard_spreadsheet',
          target_name: '杭州地铁10号线轨旁AP业务-WPS云文档',
          target_batch_id: 'target-1',
          status: 'SUCCESS_WITH_WARNINGS',
          remote_task_id_masked: 'GN/KU3B3...sk==',
          remote_task_type: 'open_air_script',
          remote_task_status: 'finished',
          remote_task_submitted_at: '2026-08-09T10:00:00+08:00',
          remote_task_last_polled_at: '2026-08-09T10:01:00+08:00',
          format_warning_count: 1,
          format_warnings: [{
            sheet_name: '轨旁AP业务',
            feature: 'freeze_panes',
            range: 'A1:P1',
            reason: 'runtime unsupported',
          }],
          source_workbook_format_manifest: {
            totals: {
              sheet_count: 9,
              column_count: 143,
              explicit_width_count: 143,
              auto_fit_column_count: 0,
              explicit_row_height_count: 21,
              format_run_count: 393,
            },
          },
          column_width_verification_report: {
            status: 'FAILED',
            total_columns: 16,
            explicit_applied_count: 15,
            auto_fit_applied_count: 1,
            clamped_count: 0,
            attempted_count: 16,
            read_back_count: 16,
            verified_count: 15,
            warning_count: 0,
            failed_count: 1,
            stage_counts: {
              WPS_COLUMN_WIDTH_VALUE_VERIFIED: 15,
              WPS_COLUMN_WIDTH_APPLY_MISMATCH: 1,
            },
            largest_differences: [{
              sheet_name: '轨旁AP业务',
              range: 'P:P',
              local_workbook_width: 38,
              remote_column_width: 8.43,
              remote_width_points: 59.01,
              difference: 29.57,
            }],
          },
          format_results: {
            column_width: {
              status: 'SUCCESS_WITH_WARNINGS',
              attempted_count: 16,
              verified_count: 15,
              failed_count: 1,
              applied_count: 15,
              expected_count: 16,
              warning_count: 1,
              examples: [{
                sheet_name: '轨旁AP业务',
                range: 'P:P',
                expected: 38,
                actual: 8.43,
                verified: false,
              }],
            },
            row_height: {
              status: 'SUCCESS',
              attempted_count: 9,
              read_back_count: 9,
              verified_count: 9,
              failed_count: 0,
            },
            font: {
              status: 'SUCCESS',
              attempted_count: 17,
              read_back_count: 17,
              verified_count: 17,
              failed_count: 0,
              format_run_count: 17,
            },
            border: {
              status: 'SUCCESS',
              attempted_count: 5,
              read_back_count: 5,
              verified_count: 5,
              failed_count: 0,
              items: [{ all_borders: true, verified: true }],
            },
            freeze_panes: {
              status: 'SUCCESS_WITH_WARNINGS',
              attempted_count: 9,
              read_back_count: 9,
              verified_count: 8,
              failed_count: 1,
              warning_count: 1,
              items: [{
                freeze_summary: true,
                sheet_name: '轨旁AP业务',
                expected_frozen_rows: 1,
                expected_frozen_columns: 0,
                actual_frozen_rows: 1,
                actual_frozen_columns: 0,
                verified: true,
              }, {
                freeze_summary: true,
                sheet_name: '当前异常光衰',
                expected_frozen_rows: 1,
                expected_frozen_columns: 0,
                actual_frozen_rows: 11,
                actual_frozen_columns: 0,
                verified: false,
              }],
            },
          },
        }],
      },
    })
    const wrapper = mount(TaskDetailDrawer, {
      props: { modelValue: true, taskId: 'wps-format-warning' },
      global: { plugins: [createPinia()] },
    })

    await flushPromises()
    const rendered = document.body.textContent || ''
    expect(rendered).toContain('WPS 子目标结果')
    expect(rendered).toContain('SUCCESS_WITH_WARNINGS')
    expect(rendered).toContain('格式告警1')
    expect(rendered).toContain('远端任务GN/KU3B3...sk==')
    expect(rendered).toContain('远端状态finished')
    expect(rendered).not.toContain('GN/KU3B3+remote-task==')
    expect(rendered).toContain('轨旁AP业务 / A1:P1 / freeze_panes / runtime unsupported')
    expect(rendered).toContain('源 Workbook 格式Sheet 9；列 143，显式宽度 143，AutoFit fallback 0，显式行高 21，FormatRun 393')
    expect(rendered).toContain('列宽自动验收FAILED；显式 15，AutoFit 1，Clamp 0，远端读回 16，验证通过 15/16，告警 0，失败 1')
    expect(rendered).toContain('故障层级：WPS_COLUMN_WIDTH_VALUE_VERIFIED 15，WPS_COLUMN_WIDTH_APPLY_MISMATCH 1')
    expect(rendered).toContain('最大差异 轨旁AP业务 / P:P：29.57（本地 38，WPS 8.43，物理宽度 59.01 pt）')
    expect(rendered).toContain('行高SUCCESS；设置 9，读回 9，验证通过 9，差异 0')
    expect(rendered).toContain('字体SUCCESS；设置 17，读回 17，验证通过 17，差异 0，FormatRun 17')
    expect(rendered).toContain('BorderSUCCESS；设置 5，读回 5，验证通过 5，差异 0；All Borders 1/1')
    expect(rendered).toContain('冻结窗格SUCCESS_WITH_WARNINGS；设置 9，读回 9，验证通过 8，差异 1；读回 1/2，1 row / 0 column x1；11 row / 0 column x1，告警 1')
    expect(rendered).toContain('轨旁AP业务：期望 1 row / 0 column，实际 1 row / 0 column，PASS')
    expect(rendered).toContain('当前异常光衰：期望 1 row / 0 column，实际 11 row / 0 column，FAIL')
    wrapper.unmount()
  })

  it('renders a masked WPS remote task while the local worker is polling', async () => {
    mocks.getTask.mockResolvedValue({
      ...task('wps-remote-running'),
      type: 'trackside_ap_wps_sync',
      status: 'RUNNING',
      error_code: '',
      error_summary: '',
      details: {
        remote_task_id_masked: 'GN/KU3B3...sk==',
        remote_task_type: 'open_air_script',
        remote_task_status: 'running',
        remote_task_submitted_at: '2026-08-09T10:00:00+08:00',
        remote_task_last_polled_at: '2026-08-09T10:00:08+08:00',
      },
    })
    const wrapper = mount(TaskDetailDrawer, {
      props: { modelValue: true, taskId: 'wps-remote-running' },
      global: { plugins: [createPinia()] },
    })

    await flushPromises()
    const rendered = document.body.textContent || ''
    expect(rendered).toContain('WPS 远端任务')
    expect(rendered).toContain('GN/KU3B3...sk==')
    expect(rendered).toContain('open_air_script')
    expect(rendered).toContain('running')
    expect(rendered).toContain('2026-08-09 10:00:08')
    wrapper.unmount()
  })

  it('keeps COMPLETED visible while hiding Artifact actions for a missing output', async () => {
    mocks.getTask.mockResolvedValue({
      ...task('task-missing'),
      status: 'COMPLETED',
      error_code: '',
      error_summary: '',
      message: '导出完成',
      artifact_available: false,
      artifact_availability: 'MISSING',
      missing_reason: '输出文件已不存在，可能已在资源管理器中删除。',
      downloadable: false,
      artifact_download: null,
    })
    const pinia = createPinia()
    const wrapper = mount(TaskDetailDrawer, {
      props: { modelValue: true, taskId: 'task-missing' },
      global: { plugins: [pinia] },
    })

    await flushPromises()
    expect(useTaskStore(pinia).selected?.status).toBe('COMPLETED')
    expect(document.querySelector('[data-testid="artifact-unavailable-alert"]')).not.toBeNull()
    expect(document.querySelector('[data-testid="artifact-download-button"]')).toBeNull()
    wrapper.unmount()
  })

  it('refreshes Artifact availability when a download races with external deletion', async () => {
    const available = {
      ...task('task-race'),
      status: 'COMPLETED' as const,
      error_code: '',
      error_summary: '',
      artifact_available: true,
      artifact_availability: 'AVAILABLE' as const,
      downloadable: true,
      artifact_download: {
        artifact_id: 'artifact-1',
        display_name: '链路明细.xlsx',
        size_bytes: 10,
        media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        api_path: '/api/job-center/artifacts/artifact-1',
        query: {},
      },
    }
    mocks.getTask
      .mockResolvedValueOnce(available)
      .mockResolvedValueOnce({
        ...available,
        artifact_available: false,
        artifact_availability: 'MISSING',
        missing_reason: '输出文件已不存在，可能已在资源管理器中删除。',
        downloadable: false,
        artifact_download: null,
      })
    mocks.downloadBackendResource.mockResolvedValue({
      status: 'failed',
      errorCode: 'ARTIFACT_NOT_FOUND',
      error: '导出文件已失效，请重新导出。',
    })
    const wrapper = mount(TaskDetailDrawer, {
      props: { modelValue: true, taskId: 'task-race' },
      global: { plugins: [createPinia()] },
    })

    await flushPromises()
    const downloadButton = document.querySelector<HTMLElement>('[data-testid="artifact-download-button"]')
    expect(downloadButton).not.toBeNull()
    downloadButton?.click()
    await flushPromises()

    expect(mocks.downloadBackendResource).toHaveBeenCalledOnce()
    expect(mocks.getTask).toHaveBeenCalledTimes(2)
    expect(document.querySelector('[data-testid="artifact-unavailable-alert"]')).not.toBeNull()
    wrapper.unmount()
  })
})
