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
const confirmDialog = vi.hoisted(() => vi.fn())
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
vi.mock('../../feedback/useConfirm', () => ({
  useConfirm: () => ({ confirm: confirmDialog }),
}))
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
  const InputNumber = defineComponent({
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    template: `
      <input
        type="number"
        :value="modelValue"
        @input="$emit('update:modelValue', Number($event.target.value))"
        @change="$emit('change', Number($event.target.value))"
      >
    `,
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
    ElInputNumber: InputNumber,
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
  action = 'trackside_ap_plan_export',
) => ({
  task_id: taskId,
  status,
  action,
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
        <slot name="cell-planned_ap_count" :row="row" />
        <slot name="cell-management_vlan" :row="row" />
        <slot name="cell-remark" :row="row" />
        <slot name="cell-preview_status" :row="row" />
        <slot name="cell-preview_message" :row="row" />
        <slot name="cell-actual_online_count" :row="row" />
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
  actual_online_count: 0,
  offline_count: 0,
  online_rate: null,
  unassigned_count: 0,
  unassigned_items: [],
  updated_at: '',
  warning: '',
})

function planRow(overrides: Partial<TracksideApPlanRow> = {}): TracksideApPlanRow {
  return {
    station_id: 'station:1',
    sequence_no: 1,
    station_name: '小洋江站',
    planned_ap_count: 30,
    management_vlan: 921,
    remark: '',
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

function stationOptions(count: number): Array<{ id: string; name: string; sort_order: number }> {
  return Array.from({ length: count }, (_, index) => ({
    id: `station:${index + 1}`,
    name: `站点${index + 1}`,
    sort_order: index + 1,
  }))
}

describe('TracksideApPlanningTab behavior', () => {
  beforeEach(() => {
    resetUserSelectedExportForTests()
    vi.useFakeTimers()
    localStorage.clear()
    sessionStorage.clear()
    routerPush.mockReset()
    routerReplace.mockReset()
    confirmDialog.mockReset().mockResolvedValue(true)
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
      props: {
        locked: false,
        saving: false,
        stations: [
          { id: 'station:1', name: '小洋江站', sort_order: 1 },
          { id: 'station:2', name: '云龙火车站站', sort_order: 2 },
        ],
      },
      global: { stubs },
    })
    await flushPromises()

    await wrapper.find('[data-plan-cell="0-sequence_no"] input').trigger(
      'paste',
      clipboard([
        '1\t小洋江站\t30\t921\t规划一',
        '2\t云龙火车站站\t0\t921\t规划二',
      ].join('\n')),
    )
    await flushPromises()

    const changes = wrapper.emitted('change') || []
    const latest = changes.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(2)
    expect(latest.map((row) => row.management_vlan)).toEqual([921, 921])
    expect(latest[1].planned_ap_count).toBe(0)
    expect(wrapper.text()).not.toContain('项需要修正')
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('creates a clean planning skeleton for all current stations', async () => {
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: stationOptions(15),
      },
      global: { stubs },
    })
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    const dirty = wrapper.emitted('change')?.at(-1)?.[1]
    expect(latest).toHaveLength(15)
    expect(latest.map((row) => row.station_id)).toEqual(
      stationOptions(15).map((station) => station.id),
    )
    expect(latest.every((row) => row.planned_ap_count === 0 && row.management_vlan === null)).toBe(true)
    expect(dirty).toBe(false)
    expect(wrapper.text()).not.toContain('有未保存修改')
    expect(wrapper.text()).not.toContain('项需要修正')

    await wrapper.find('[data-plan-cell="0-remark"] input').setValue('待后续规划')
    await flushPromises()
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('requires VLAN only for positive AP counts and rejects invalid values', async () => {
    const values: Array<Partial<TracksideApPlanRow>> = [
      { planned_ap_count: 0, management_vlan: null },
      { planned_ap_count: 0, management_vlan: 71 },
      { planned_ap_count: 1, management_vlan: null },
      { planned_ap_count: -1, management_vlan: null },
      { planned_ap_count: 0, management_vlan: 0 },
      { planned_ap_count: 0, management_vlan: 4095 },
      { planned_ap_count: 0, management_vlan: 71.5 },
    ]
    const stations = stationOptions(values.length)
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: values.map((value, index) => planRow({
        station_id: stations[index].id,
        station_name: stations[index].name,
        sequence_no: index + 1,
        ...value,
      })),
      total: values.length,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false, stations },
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('有 5 项需要修正')
    expect(wrapper.find('[data-plan-cell="2-management_vlan"]').attributes('title'))
      .toBe('AP数量大于 0 时必须填写 VLAN')
    expect(wrapper.find('[data-plan-cell="3-planned_ap_count"]').attributes('title'))
      .toBe('AP数量必须是非负整数')
    expect(wrapper.find('[data-plan-cell="4-management_vlan"]').attributes('title'))
      .toBe('VLAN 必须在 1～4094 范围内')
    wrapper.unmount()
  })

  it('fills the planning skeleton when stations arrive asynchronously', async () => {
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false, stations: [] },
      global: { stubs },
    })
    await flushPromises()
    await wrapper.setProps({ stations: stationOptions(15) })
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(15)
    expect(wrapper.text()).toContain('已加载 15 行')
    wrapper.unmount()
  })

  it('preserves saved fields while filling missing stations', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow({ planned_ap_count: 28, management_vlan: 922, remark: '保留值' })],
      total: 1,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: stationOptions(2),
      },
      global: { stubs },
    })
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(2)
    expect(latest[0]).toMatchObject({
      station_id: 'station:1',
      planned_ap_count: 28,
      management_vlan: 922,
      remark: '保留值',
    })
    expect(latest[1]).toMatchObject({
      station_id: 'station:2',
      planned_ap_count: 0,
      management_vlan: null,
    })
    expect(wrapper.emitted('change')?.at(-1)?.[1]).toBe(false)
    wrapper.unmount()
  })

  it('keeps dirty edits and appends only newly arrived stations', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow({ planned_ap_count: 28, management_vlan: 922 })],
      total: 1,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: [{ id: 'station:1', name: '小洋江站', sort_order: 1 }],
      },
      global: { stubs },
    })
    await flushPromises()

    await wrapper.find('[data-plan-cell="0-planned_ap_count"] input').setValue('99')
    await flushPromises()
    await wrapper.setProps({
      stations: [
        { id: 'station:1', name: '小洋江站（更新名）', sort_order: 1 },
        { id: 'station:2', name: '新增站点', sort_order: 2 },
      ],
    })
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    const edited = latest.find((row) => row.station_id === 'station:1')
    const appended = latest.find((row) => row.station_id === 'station:2')
    expect(edited?.planned_ap_count).toBe(99)
    expect(edited?.station_name).toBe('小洋江站（更新名）')
    expect(appended).toMatchObject({ planned_ap_count: 0, management_vlan: null })
    expect(wrapper.emitted('change')?.at(-1)?.[1]).toBe(true)
    wrapper.unmount()
  })

  it('does not duplicate a dirty row when its station id arrives later', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow({ planned_ap_count: 28, management_vlan: 922 })],
      total: 1,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false, stations: [] },
      global: { stubs },
    })
    await flushPromises()

    await wrapper.find('[data-plan-cell="0-planned_ap_count"] input').setValue('77')
    await flushPromises()
    await wrapper.setProps({
      stations: [{ id: 'station:1', name: '小洋江站（新名称）', sort_order: 1 }],
    })
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(1)
    expect(latest[0]).toMatchObject({
      station_id: 'station:1',
      station_name: '小洋江站（新名称）',
      planned_ap_count: 77,
    })
    expect(wrapper.emitted('change')?.at(-1)?.[1]).toBe(true)
    wrapper.unmount()
  })

  it('retains unmatched history rows and blocks saving until repaired', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow({
        station_id: 'station:legacy',
        station_name: '已删除站点',
        planned_ap_count: 12,
        management_vlan: 921,
      })],
      total: 1,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: [{ id: 'station:1', name: '当前站点', sort_order: 1 }],
      },
      global: { stubs },
    })
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(2)
    expect(latest.find((row) => row.station_id === 'station:legacy')?.station_match_status).toBe('unmatched')
    expect(wrapper.text()).toContain('未匹配当前站点')
    expect(button(wrapper, '保存').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('shows a cell-level summary for an invalid AP count', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow()],
      total: 1,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: [{ id: 'station:1', name: '小洋江站', sort_order: 1 }],
      },
      global: { stubs },
    })
    await flushPromises()

    await wrapper.find('[data-plan-cell="0-planned_ap_count"] input').trigger(
      'paste',
      clipboard('-1'),
    )
    await flushPromises()

    expect(wrapper.text()).toContain('有 1 项需要修正')
    expect(
      wrapper.find('[data-plan-cell="0-planned_ap_count"]').attributes('title'),
    ).toBe('AP数量必须是非负整数')
    wrapper.unmount()
  })

  it('keeps invalid import rows visible and applies valid rows only', async () => {
    api.previewTracksideApPlan.mockResolvedValue({
      file_name: 'partial.xlsx',
      file_sha256: 'sha256',
      duplicate_strategy: 'replace',
      can_apply: true,
      total_count: 2,
      valid_count: 1,
      duplicate_count: 0,
      error_count: 1,
      rows: [
        {
          row_number: 3,
          status: 'valid',
          key: '小洋江站',
          message: '',
          row: planRow({ planned_ap_count: 28 }),
        },
        {
          row_number: 4,
          status: 'error',
          key: '',
          message: '第4行 AP数量：必须是整数',
          row: {
            station_id: '',
            sequence_no: 2,
            station_name: '不存在站',
            planned_ap_count: 'invalid',
            management_vlan: 922,
            remark: '错误行',
          },
        },
      ],
      result_rows: [planRow({ planned_ap_count: 28 })],
      result_plan: null,
      legacy_schema: false,
      message: '',
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: [
          { id: 'station:1', name: '小洋江站', sort_order: 1 },
        ],
      },
      global: { stubs },
    })
    await flushPromises()

    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['xlsx'], 'partial.xlsx')],
    })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('不存在站')
    expect(wrapper.text()).toContain('请选择当前基础资料中的站点')
    await button(wrapper, '应用有效行').trigger('click')
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest).toHaveLength(1)
    expect(latest[0].station_name).toBe('小洋江站')
    expect(latest[0].planned_ap_count).toBe(28)
    wrapper.unmount()
  })

  it('keeps multi-row count and VLAN edits local until one explicit save', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [
        planRow({ planned_ap_count: 0 }),
        planRow({
          station_id: 'station:2',
          sequence_no: 2,
          station_name: '云龙火车站站',
          management_vlan: 922,
        }),
      ],
      total: 2,
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: [
          { id: 'station:1', name: '小洋江站', sort_order: 1 },
          { id: 'station:2', name: '云龙火车站站', sort_order: 2 },
        ],
      },
      global: { stubs },
    })
    await flushPromises()

    const firstCount = wrapper.find('[data-plan-cell="0-planned_ap_count"] input')
    expect(firstCount.attributes('readonly')).toBeUndefined()
    expect(firstCount.attributes('disabled')).toBeUndefined()
    await firstCount.setValue('30')
    await wrapper.find('[data-plan-cell="1-planned_ap_count"] input').setValue('56')
    await wrapper.find('[data-plan-cell="1-management_vlan"] input').setValue('923')
    await flushPromises()

    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest.map((row) => row.planned_ap_count)).toEqual([30, 56])
    expect(latest[1].management_vlan).toBe(923)
    expect(api.previewTracksideApPlan).not.toHaveBeenCalled()
    expect(api.startTracksideApUpdate).not.toHaveBeenCalled()
    expect(wrapper.emitted('save')).toBeUndefined()

    await button(wrapper, '保存').trigger('click')
    expect(wrapper.emitted('save')).toHaveLength(1)
    wrapper.unmount()
  })

  it('refreshes actual online status without replacing the planned-count draft', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow({ planned_ap_count: 28 })],
      total: 1,
    })
    api.getTracksideApOnlineStatus
      .mockResolvedValueOnce(emptyStatus())
      .mockResolvedValueOnce({
        ...emptyStatus(),
        items: [{
          station_id: 'station:1',
          station_name: '小洋江站',
          planned_ap_count: 28,
          actual_online_count: 28,
          offline_count: 0,
          online_rate: 100,
          remark: '',
          count_anomaly: false,
          warning: '',
        }],
        planned_ap_count: 28,
        actual_online_count: 28,
        online_rate: 100,
        updated_at: '2026-07-30 12:00:00',
      })
    api.startTracksideApUpdate.mockResolvedValue(
      task(
        'refresh-status',
        'COMPLETED',
        false,
        '',
        '',
        'trackside_ap_optical_update',
      ),
    )
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    const countInput = wrapper.find('[data-plan-cell="0-planned_ap_count"] input')
    await countInput.setValue('29')
    await button(wrapper, '刷新上线状态').trigger('click')
    await flushPromises()

    expect(api.getTracksideApPlan).toHaveBeenCalledTimes(1)
    expect(api.getTracksideApOnlineStatus).toHaveBeenCalledTimes(2)
    expect((countInput.element as HTMLInputElement).value).toBe('29')
    const latest = wrapper.emitted('change')?.at(-1)?.[0] as TracksideApPlanRow[]
    expect(latest[0].planned_ap_count).toBe(29)
    wrapper.unmount()
  })

  it('keeps the editable plan when online status loading fails and clears only that error after recovery', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow({ planned_ap_count: 28 })],
      total: 1,
    })
    api.getTracksideApOnlineStatus
      .mockRejectedValueOnce(new Error('connection reset'))
      .mockResolvedValueOnce(emptyStatus())
    api.startTracksideApUpdate.mockResolvedValue(
      task(
        'refresh-status',
        'COMPLETED',
        false,
        '',
        '',
        'trackside_ap_optical_update',
      ),
    )
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        stations: [{ id: 'station:1', name: '小洋江站', sort_order: 1 }],
      },
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('AP 上线状态刷新失败，已保留最后成功数据。')
    expect(wrapper.text()).not.toContain('轨旁 AP 规划刷新失败')
    expect(wrapper.text()).not.toContain('项需要修正')
    const countInput = wrapper.find('[data-plan-cell="0-planned_ap_count"] input')
    expect((countInput.element as HTMLInputElement).value).toBe('28')
    await countInput.setValue('29')
    expect((countInput.element as HTMLInputElement).value).toBe('29')

    await button(wrapper, '刷新上线状态').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('AP 上线状态刷新失败')
    expect((countInput.element as HTMLInputElement).value).toBe('29')
    expect(api.getTracksideApPlan).toHaveBeenCalledTimes(1)
    expect(api.getTracksideApOnlineStatus).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('renders weighted totals and a normal unassigned AP warning', async () => {
    api.getTracksideApOnlineStatus.mockResolvedValue({
      items: [{
        station_id: 'station:1',
        station_name: '01小洋江站',
        planned_ap_count: 28,
        actual_online_count: 28,
        offline_count: 0,
        online_rate: 100,
        remark: '核减2个AP',
        count_anomaly: false,
        warning: '',
      }],
      planned_ap_count: 945,
      actual_online_count: 719,
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
    expect(wrapper.text()).toContain('规划总数 945')
    expect(wrapper.text()).toContain('实际上线 719')
    expect(wrapper.text()).toContain('未上线 226')
    expect(wrapper.text()).toContain('总上线率 76.1%')
    wrapper.unmount()
  })

  it('shows over-planned and zero-plan rates as a dash', async () => {
    api.getTracksideApOnlineStatus.mockResolvedValue({
      items: [
        {
          station_id: 'station:1',
          station_name: '站点A',
          planned_ap_count: 1,
          actual_online_count: 2,
          offline_count: 0,
          online_rate: null,
          remark: '',
          count_anomaly: true,
          status: 'over_planned',
          warning: '实际上线 AP 数量超过当前规划数量，请检查规划资料或 AP 归属关系。',
        },
        {
          station_id: 'station:2',
          station_name: '站点B',
          planned_ap_count: 0,
          actual_online_count: 0,
          offline_count: 0,
          online_rate: null,
          remark: '',
          count_anomaly: false,
          warning: '',
        },
      ],
      planned_ap_count: 1,
      actual_online_count: 2,
      offline_count: 0,
      online_rate: null,
      unassigned_count: 0,
      unassigned_items: [],
      updated_at: '',
      warning: '',
      count_anomaly: true,
      status: 'anomaly',
    })
    const wrapper = mount(TracksideApPlanningTab, {
      props: { locked: false, saving: false },
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('200.0%')
    expect(wrapper.text()).toContain('超规划')
    expect(wrapper.text()).toContain('存在未纳入规划或超规划的在线 AP')
    expect(wrapper.text()).toContain('—')
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

  it('exports the saved plan with a line-specific overview filename', async () => {
    api.getTracksideApPlan.mockResolvedValue({
      ...emptyPlan(),
      items: [planRow()],
      total: 1,
    })
    api.exportTracksideApPlan.mockResolvedValue(
      task('current-plan', 'COMPLETED', true, 'artifact-current'),
    )
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        locked: false,
        saving: false,
        lineName: '宁波地铁12号线',
      },
      global: { stubs },
    })
    await flushPromises()
    await wrapper.find('[data-plan-cell="0-remark"] input').setValue('未保存备注')

    await button(wrapper, '导出当前').trigger('click')
    await flushPromises()

    expect(api.exportTracksideApPlan).toHaveBeenCalledWith(false)
    expect(sessionStorage.getItem('netconsole.user-selected-exports.v1')).toContain(
      '宁波地铁12号线_轨旁AP规划及上线概览_',
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
