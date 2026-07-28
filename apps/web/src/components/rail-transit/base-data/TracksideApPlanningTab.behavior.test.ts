// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

const api = vi.hoisted(() => ({
  exportTracksideApPlan: vi.fn(),
  getTracksideApPlan: vi.fn(),
  getTracksideApTask: vi.fn(),
  recoverTracksideApTasks: vi.fn(),
  previewTracksideApPlan: vi.fn(),
  previewTracksideApVlanAutoGroup: vi.fn(),
  previewTracksideApVlanChange: vi.fn(),
  tracksideApPlanDownloadRequest: vi.fn(),
}))
const downloadBackendResource = vi.hoisted(() => vi.fn())
const routerPush = vi.hoisted(() => vi.fn())
const messages = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))

vi.mock('../../../api/tracksideApBusiness', () => api)
vi.mock('../../../platform/runtime', () => ({ downloadBackendResource }))
vi.mock('../../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('../../feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: vi.fn(async () => true) }) }))
vi.mock('element-plus', async () => {
  const { defineComponent } = await import('vue')
  const Button = defineComponent({ emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' })
  const Container = defineComponent({ template: '<div><slot /><slot name="footer" /></div>' })
  const Alert = defineComponent({ props: { title: String }, template: '<div>{{ title }}<slot /></div>' })
  return {
    ElMessage: messages,
    ElAlert: Alert,
    ElButton: Button,
    ElDialog: Container,
    ElDescriptions: Container,
    ElDescriptionsItem: Container,
    ElInput: defineComponent({ template: '<input />' }),
    ElInputNumber: defineComponent({ template: '<input />' }),
    ElLoadingDirective: {},
    ElOption: defineComponent({ template: '<option><slot /></option>' }),
    ElSelect: defineComponent({ template: '<select><slot /></select>' }),
    ElTabPane: Container,
    ElTabs: Container,
    ElTag: Container,
  }
})
vi.mock('@element-plus/icons-vue', () => ({ Delete: {}, Download: {}, Plus: {}, UploadFilled: {} }))

import TracksideApPlanningTab from './TracksideApPlanningTab.vue'

const task = (taskId: string, status: string, available = false, artifactId = '', artifactName = '') => ({
  task_id: taskId,
  status,
  action: 'trackside_ap_plan_export',
  artifact_id: artifactId,
  artifact_name: artifactName,
  available,
  sha256: '',
  size_bytes: 0,
  message: '',
  error_message: '',
  result_summary: {},
})

const stubs = {
  NcDataTable: defineComponent({ template: '<div />' }),
  ElAlert: defineComponent({ template: '<div><slot /></div>' }),
  ElButton: defineComponent({ emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' }),
  ElSelect: defineComponent({ template: '<select><slot /></select>' }),
  ElOption: defineComponent({ template: '<option><slot /></option>' }),
  ElDialog: defineComponent({ template: '<div><slot /><slot name="footer" /></div>' }),
  ElInput: defineComponent({ template: '<input />' }),
  ElInputNumber: defineComponent({ template: '<input />' }),
  ElDescriptions: defineComponent({ template: '<div><slot /></div>' }),
  ElDescriptionsItem: defineComponent({ template: '<span><slot /></span>' }),
  ElTabPane: defineComponent({ template: '<div><slot /></div>' }),
  ElTabs: defineComponent({ template: '<div><slot /></div>' }),
  ElTag: defineComponent({ template: '<span><slot /></span>' }),
}

const emptyPlan = () => ({
  items: [],
  total: 0,
  planning: {
    line_id: 'current',
    planning_mode: 'station_independent',
    auto_group_station_count: 1,
    address_allocation_strategy: 'station_then_point',
    revision: 0,
    updated_at: '',
  },
  groups: [],
  assignments: [],
  allocations: [],
  station_details: [],
  issues: [],
  valid: true,
  unassigned_station_count: 0,
})

function button(wrapper: VueWrapper, label: string) {
  const match = wrapper.findAll('button').find((item) => item.text().includes(label))
  if (!match) throw new Error(`button not found: ${label}`)
  return match
}

describe('TracksideApPlanningTab download behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    routerPush.mockReset()
    messages.success.mockReset()
    messages.error.mockReset()
    messages.info.mockReset()
    api.exportTracksideApPlan.mockReset()
    api.getTracksideApTask.mockReset()
    api.recoverTracksideApTasks.mockReset()
    api.tracksideApPlanDownloadRequest.mockReset()
    api.getTracksideApPlan.mockResolvedValue(emptyPlan())
    api.recoverTracksideApTasks.mockResolvedValue([])
    api.tracksideApPlanDownloadRequest.mockImplementation((artifactId: string, suggestedName: string) => ({ apiPath: `/api/artifacts/${artifactId}`, suggestedName }))
    downloadBackendResource.mockReset().mockResolvedValue({ status: 'saved' })
  })

  it('automatically downloads a newly created template once without opening task center', async () => {
    api.exportTracksideApPlan.mockResolvedValue(task('new-template', 'RUNNING'))
    api.getTracksideApTask.mockResolvedValue(task('new-template', 'COMPLETED', true, 'artifact-1'))
    const wrapper = mount(TracksideApPlanningTab, { props: { locked: false, saving: false }, global: { stubs } })
    await flushPromises()

    await wrapper.find('.toolbar button').trigger('click')
    await flushPromises()
    expect(routerPush).not.toHaveBeenCalled()
    expect(downloadBackendResource).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(downloadBackendResource).toHaveBeenCalledTimes(1)
    expect(api.tracksideApPlanDownloadRequest).toHaveBeenCalledWith('artifact-1', '轨旁AP规划模板.xlsx')

    await vi.advanceTimersByTimeAsync(3000)
    expect(downloadBackendResource).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does not automatically download a recovered completed task', async () => {
    api.recoverTracksideApTasks.mockResolvedValue([task('history', 'COMPLETED', true, 'history-artifact')])
    const wrapper = mount(TracksideApPlanningTab, { props: { locked: false, saving: false }, global: { stubs } })
    await flushPromises()
    expect(downloadBackendResource).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('downloads the current plan with its own fallback name', async () => {
    api.exportTracksideApPlan.mockResolvedValue(task('current-plan', 'COMPLETED', true, 'artifact-current'))
    const wrapper = mount(TracksideApPlanningTab, { props: { locked: false, saving: false }, global: { stubs } })
    await flushPromises()

    await button(wrapper, '导出当前').trigger('click')
    await flushPromises()
    expect(api.exportTracksideApPlan).toHaveBeenCalledWith(false, undefined)
    expect(api.tracksideApPlanDownloadRequest).toHaveBeenCalledWith('artifact-current', '轨旁AP规划.xlsx')
    wrapper.unmount()
  })

  it.each([
    ['FAILED', false, '', '轨旁 AP 规划导出失败'],
    ['CANCELLED', false, '', '轨旁 AP 规划导出已取消'],
    ['COMPLETED', false, '', '没有可下载的 Artifact'],
  ])('does not download terminal task state %s without an artifact', async (status, available, artifactId, message) => {
    api.exportTracksideApPlan.mockResolvedValue(task(`terminal-${status}`, status, available, artifactId))
    const wrapper = mount(TracksideApPlanningTab, { props: { locked: false, saving: false }, global: { stubs } })
    await flushPromises()

    await button(wrapper, '下载模板').trigger('click')
    await flushPromises()
    expect(downloadBackendResource).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(message)
    wrapper.unmount()
  })

  it('keeps manual download and task window actions after an automatic download failure', async () => {
    api.exportTracksideApPlan.mockResolvedValue(task('retry-task', 'COMPLETED', true, 'retry-artifact', '后端模板.xlsx'))
    downloadBackendResource.mockResolvedValueOnce({ status: 'failed', error: '保存失败' })
    const wrapper = mount(TracksideApPlanningTab, { props: { locked: false, saving: false }, global: { stubs } })
    await flushPromises()

    await button(wrapper, '下载模板').trigger('click')
    await flushPromises()
    expect(downloadBackendResource).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('可使用“下载文件”重试')

    downloadBackendResource.mockResolvedValueOnce({ status: 'saved' })
    await button(wrapper, '下载文件').trigger('click')
    await flushPromises()
    expect(downloadBackendResource).toHaveBeenCalledTimes(2)

    await button(wrapper, '打开任务中心').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ name: 'tasks', query: { module: 'rail', task_id: 'retry-task' } })
    wrapper.unmount()
  })
})
