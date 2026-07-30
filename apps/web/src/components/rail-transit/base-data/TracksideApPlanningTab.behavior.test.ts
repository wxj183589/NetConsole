// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

import { resetUserSelectedExportForTests } from '../../../composables/useUserSelectedExport'
import type {
  TracksideApOnlineStatus,
  TracksideApPlan,
  TracksideApPlanRow,
} from '../../../types/tracksideApBusiness'

const api = vi.hoisted(() => ({
  exportTracksideApPlan: vi.fn(),
  getTracksideApOnlineStatus: vi.fn(),
  getTracksideApPlan: vi.fn(),
  getTracksideApTask: vi.fn(),
  previewTracksideApPlan: vi.fn(),
  recoverTracksideApTasks: vi.fn(),
  startTracksideApUpdate: vi.fn(),
  tracksideApPlanDownloadRequest: vi.fn(),
}))
const downloadBackendResource = vi.hoisted(() => vi.fn())
const routerPush = vi.hoisted(() => vi.fn())
const routerReplace = vi.hoisted(() => vi.fn())
const messages = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
}))

vi.mock('../../../api/tracksideApBusiness', () => api)
vi.mock('../../../platform/runtime', () => ({
  downloadBackendResource,
  getPlatformAdapter: () => ({ hostType: 'browser' }),
}))
vi.mock('../../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('vue-router', () => ({
  useRouter: () => ({
    currentRoute: { value: { query: {} } },
    push: routerPush,
    replace: routerReplace,
  }),
}))
vi.mock('element-plus', async () => {
  const { defineComponent } = await import('vue')
  const Button = defineComponent({
    emits: ['click'],
    template: '<button @click="$emit(\'click\')"><slot /></button>',
  })
  const Container = defineComponent({
    template: '<div><slot /><slot name="footer" /></div>',
  })
  const Input = defineComponent({
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">',
  })
  return {
    ElMessage: messages,
    ElAlert: defineComponent({
      props: { title: String },
      template: '<div>{{ title }}<slot /></div>',
    }),
    ElButton: Button,
    ElDialog: Container,
    ElDescriptions: Container,
    ElDescriptionsItem: Container,
    ElInput: Input,
    ElInputNumber: Input,
    ElLoadingDirective: {},
    ElOption: defineComponent({ template: '<option><slot /></option>' }),
    ElSelect: Input,
    ElTabPane: Container,
    ElTabs: Container,
    ElTag: Container,
  }
})
vi.mock('@element-plus/icons-vue', () => ({
  Check: {},
  Delete: {},
  Download: {},
  Plus: {},
  Refresh: {},
  RefreshLeft: {},
  UploadFilled: {},
  View: {},
}))

import TracksideApPlanningTab from './TracksideApPlanningTab.vue'

const task = (
  taskId: string,
  status: string,
  available = false,
  artifactId = '',
  artifactName = '',
) => ({
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

const NcDataTableStub = defineComponent({
  props: { data: { type: Array, default: () => [] } },
  template: `
    <div class="nc-data-table">
      <div v-for="row in data" :key="row.sequence_no || row.ap_id || row.station_name">
        <span class="row-station">{{ row.station_name }}</span>
        <slot name="cell-sequence_no" :row="row" />
        <slot name="cell-station_name" :row="row" />
        <slot name="cell-ap_count" :row="row" />
        <slot name="cell-ap_start_address" :row="row" />
        <slot name="cell-subnet_mask" :row="row" />
        <slot name="cell-ap_gateway" :row="row" />
        <slot name="cell-management_vlan" :row="row" />
        <slot name="cell-remark" :row="row" />
        <slot name="cell-online_rate" :row="row" />
        <slot name="cell-actions" :row="row" />
      </div>
    </div>
  `,
})

const stubs = {
  NcDataTable: NcDataTableStub,
}

const emptyPlan = (): TracksideApPlan => ({
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

const emptyStatus = (): TracksideApOnlineStatus => ({
  items: [],
  planned_ap_count: 0,
  actual_ap_count: 0,
  online_count: 0,
  offline_count: 0,
  online_rate: null,
  unassigned_count: 0,
  unassigned_items: [],
  updated_at: '',
  warning: '',
})

function planRow(overrides: Partial<TracksideApPlanRow> = {}): TracksideApPlanRow {
  return {
    station_id: '',
    sequence_no: 1,
    station_name: '小洋江站',
    ap_count: 30,
    ap_start_address: '10.122.221.X',
    subnet_mask: '24',
    mask_length: 24,
    ap_gateway: '10.122.221.254',
    management_vlan: 921,
    ap_management_vlans: '921',
    remark: '',
    sort_order: 0,
    ...overrides,
  }
}

function button(wrapper: VueWrapper, label: string) {
  const match = wrapper.findAll('button').find((item) => item.text().includes(label))
  if (!match) throw new Error(`button not found: ${label}`)
  return match
}

function clipboard(text: string): Record<string, unknown> {
  return { clipboardData: { getData: () => text } }
}

describe('TracksideApPlanningTab behavior', () => {
  beforeEach(() => {
    resetUserSelectedExportForTests()
    vi.useFakeTimers()
    localStorage.clear()
    sessionStorage.clear()
    routerPush.mockReset()
    routerReplace.mockReset()
    for (const message of Object.values(messages)) message.mockReset()
    for (const method of Object.values(api)) method.mockReset()
    api.getTracksideApPlan.mockResolvedValue(emptyPlan())
    api.getTracksideApOnlineStatus.mockResolvedValue(emptyStatus())
    api.recoverTracksideApTasks.mockResolvedValue([])
    api.tracksideApPlanDownloadRequest.mockImplementation(
      (artifactId: string, suggestedName: string) => ({
        apiPath: `/api/artifacts/${artifactId}`,
        suggestedName,
      }),
    )
    downloadBackendResource.mockReset().mockResolvedValue({ status: 'saved' })
  })

  it('adds a row and pastes an Excel grid with repeated VLAN values', async () => {
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    await button(wrapper, '新增站点').trigger('click')
    await wrapper.find('[data-plan-cell="0-sequence_no"] input').trigger(
      'paste',
      clipboard([
        '1\t小洋江站\t30\t10.122.221.X\t24\t10.122.221.254\t921\t规划一',
        '2\t云龙火车站站\t0\t10.122.222.x\t/24\t10.122.222.254\t921\t规划二',
      ].join('\n')),
    )
    await flushPromises()

    const changes = wrapper.emitted('change') || []
    const latest = changes.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(2)
    expect(latest.map((row) => row.management_vlan)).toEqual([921, 921])
    expect(latest[0].ap_start_address).toBe('10.122.221.X')
    expect(latest[1].ap_count).toBe(0)
    expect(wrapper.text()).not.toContain('项需要修正')
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('shows a cell-level summary for invalid pasted values', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow()],
      total: 1,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    await wrapper.find('[data-plan-cell="0-ap_start_address"] input').trigger(
      'paste',
      clipboard('not-an-address'),
    )
    await flushPromises()

    expect(wrapper.text()).toContain('有 1 项需要修正')
    expect(
      wrapper.find('[data-plan-cell="0-ap_start_address"]').attributes('title'),
    ).toBe('应为 IPv4 或末段 X 占位符')
    wrapper.unmount()
  })

  it('renders weighted totals and a normal unassigned AP warning', async () => {
    api.getTracksideApOnlineStatus.mockResolvedValue({
      items: [{
        station_id: 'station:1',
        station_name: '01小洋江站',
        planned_ap_count: 30,
        actual_ap_count: 28,
        online_count: 28,
        offline_count: 0,
        online_rate: 100,
        remark: '核减2个AP',
      }],
      planned_ap_count: 955,
      actual_ap_count: 945,
      online_count: 719,
      offline_count: 226,
      online_rate: 76.1,
      unassigned_count: 11,
      unassigned_items: [{
        ap_id: 'ap:1',
        ap_name: 'AP-未分配',
        point_code: 'P001',
        mac: '',
        station_name: '',
      }],
      updated_at: '2026-07-30 11:30:25',
      warning: '当前有 11 个轨旁 AP 尚未分配归属站点。',
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('状态更新时间：2026-07-30 11:30:25')
    expect(wrapper.text()).toContain('当前有 11 个轨旁 AP 尚未分配归属站点。')
    expect(wrapper.text()).toContain('查看未分配 AP')
    expect(wrapper.text()).toContain('AP 945')
    expect(wrapper.text()).toContain('上线 719')
    expect(wrapper.text()).toContain('未上线 226')
    expect(wrapper.text()).toContain('总上线率 76.1%')
    wrapper.unmount()
  })

  it('does not page-download a newly created template or recovered task', async () => {
    api.exportTracksideApPlan.mockResolvedValue(task('new-template', 'RUNNING'))
    api.getTracksideApTask.mockResolvedValue(
      task('new-template', 'COMPLETED', true, 'artifact-1'),
    )
    api.recoverTracksideApTasks.mockResolvedValue([
      task('history', 'COMPLETED', true, 'history-artifact'),
    ])
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    await button(wrapper, '下载模板').trigger('click')
    await flushPromises()
    expect(downloadBackendResource).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(downloadBackendResource).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('netconsole.user-selected-exports.v1')).toContain(
      'new-template',
    )
    wrapper.unmount()
  })

  it('exports the current draft without a delayed page download', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow()],
      total: 1,
    })
    api.exportTracksideApPlan.mockResolvedValue(
      task('current-plan', 'COMPLETED', true, 'artifact-current'),
    )
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()
    await wrapper.find('[data-plan-cell="0-remark"] input').setValue('未保存备注')

    await button(wrapper, '导出当前').trigger('click')
    await flushPromises()

    expect(api.exportTracksideApPlan).toHaveBeenCalledWith(
      false,
      expect.arrayContaining([expect.objectContaining({ remark: '未保存备注' })]),
    )
    expect(downloadBackendResource).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps manual Artifact download after a save failure', async () => {
    localStorage.setItem('netconsole.trackside-ap-plan.last-task', 'retry-task')
    api.recoverTracksideApTasks.mockResolvedValue([
      task('retry-task', 'COMPLETED', true, 'retry-artifact', '后端模板.xlsx'),
    ])
    downloadBackendResource.mockResolvedValueOnce({
      status: 'failed',
      error: '保存失败',
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    await button(wrapper, '下载文件').trigger('click')
    await flushPromises()
    expect(downloadBackendResource).toHaveBeenCalledTimes(1)
    expect(messages.error).toHaveBeenCalledWith('保存失败')

    downloadBackendResource.mockResolvedValueOnce({ status: 'saved' })
    await button(wrapper, '下载文件').trigger('click')
    await flushPromises()
    expect(downloadBackendResource).toHaveBeenCalledTimes(2)

    await button(wrapper, '打开任务中心').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tasks',
      query: { module: 'rail', task_id: 'retry-task' },
    })
    wrapper.unmount()
  })
})
