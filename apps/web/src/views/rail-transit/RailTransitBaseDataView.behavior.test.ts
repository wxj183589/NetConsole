// @vitest-environment happy-dom

import { defineComponent, nextTick } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RailTransitBaseDataView from './RailTransitBaseDataView.vue'

const mocks = vi.hoisted(() => ({
  summary: vi.fn(),
  editSession: vi.fn(),
  validate: vi.fn(),
  save: vi.fn(),
  emptyPage: vi.fn(),
  issuePage: vi.fn(),
  importPolicies: vi.fn(),
  importOperations: vi.fn(),
  stationSourcePreview: vi.fn(),
  stationTemplatePreview: vi.fn(),
  download: vi.fn(),
}))

vi.mock('../../api/railTransitBaseData', () => ({
  applyRailTransitImport: vi.fn(),
  getRailTransitBaseDataEditSession: mocks.editSession,
  getRailTransitImportPolicies: mocks.importPolicies,
  getRailTransitSummary: mocks.summary,
  listRailTransitImportChanges: vi.fn(async () => []),
  listRailTransitImportOperations: mocks.importOperations,
  listDataQualityIssueGroups: mocks.issuePage,
  listRelations: mocks.emptyPage,
  listSections: mocks.emptyPage,
  listStations: mocks.emptyPage,
  listTracksideAps: mocks.emptyPage,
  listTrains: mocks.emptyPage,
  listVehicleMrs: mocks.emptyPage,
  previewRailTransitImport: vi.fn(),
  getStationSourcePreview: mocks.stationSourcePreview,
  previewStationTemplate: mocks.stationTemplatePreview,
  rollbackRailTransitImport: vi.fn(),
  saveRailTransitBaseDataChanges: mocks.save,
  stationTemplateDownloadRequest: vi.fn(() => ({ apiPath: '/api/rail-transit/base-data/station-template', suggestedName: '线路与站点基础资料模板.xlsx' })),
  stationTemplateExportDownloadRequest: vi.fn(() => ({ apiPath: '/api/rail-transit/base-data/station-template-export', suggestedName: '线路与站点基础资料.xlsx' })),
  validateRailTransitBaseDataChanges: mocks.validate,
}))

vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: mocks.download,
}))

vi.mock('../../components/feedback/useConfirm', () => ({
  useConfirm: () => ({
    confirm: vi.fn(async () => true),
    confirmChoice: vi.fn(async () => 'secondary'),
  }),
}))

const Passthrough = defineComponent({ template: '<div><slot /></div>' })
const DialogStub = defineComponent({
  props: { modelValue: Boolean, title: String },
  template: '<div v-if="modelValue" class="dialog-stub"><h3>{{ title }}</h3><slot /><slot name="footer" /></div>',
})
const AlertStub = defineComponent({
  props: { title: String, description: String },
  template: '<div class="alert-stub">{{ title }} {{ description }}<slot /></div>',
})
const ButtonStub = defineComponent({
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  template: '<button v-bind="$attrs" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
})
const InputStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: [String, Number], default: '' } },
  emits: ['update:modelValue', 'input'],
  methods: {
    update(event: Event) {
      const value = (event.target as HTMLInputElement).value
      this.$emit('update:modelValue', value)
      this.$emit('input', value)
    },
  },
  template: '<input v-bind="$attrs" :value="modelValue" @input="update">',
})
const SelectStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: [String, Boolean], default: '' }, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  methods: {
    update(event: Event) {
      const value = (event.target as HTMLSelectElement).value
      this.$emit('update:modelValue', value)
      this.$emit('change', value)
    },
  },
  template: '<select v-bind="$attrs" :value="String(modelValue)" :disabled="disabled" @change="update"><slot /></select>',
})
const OptionStub = defineComponent({
  props: { label: String, value: { type: [String, Number, Boolean], default: '' } },
  template: '<option :value="String(value)">{{ label }}</option>',
})
const InputNumberStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: Number, default: 0 } },
  emits: ['update:modelValue', 'change'],
  template: '<input v-bind="$attrs" type="number" :value="modelValue">',
})
const CheckboxStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: Boolean, default: false }, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  methods: {
    update(event: Event) {
      const checked = (event.target as HTMLInputElement).checked
      this.$emit('update:modelValue', checked)
      this.$emit('change', checked)
    },
  },
  template: '<label><input v-bind="$attrs" type="checkbox" :checked="modelValue" :disabled="disabled" @change="update"><slot /></label>',
})
const DataTableStub = defineComponent({
  props: { data: { type: Array, default: () => [] }, columns: { type: Array, default: () => [] }, tableId: String },
  methods: {
    cell(row: Record<string, unknown>, column: Record<string, unknown>) {
      const displayValue = column.displayValue
      if (typeof displayValue === 'function') return displayValue(row)
      const value = row[String(column.key)]
      if (Array.isArray(value)) return value.map((item) => item?.message || String(item)).join('；')
      return value ?? ''
    },
  },
  template: `
    <div class="table-stub" :data-table-id="tableId">
      <div v-for="(row, rowIndex) in data" :key="row.id || row.candidate_id || row.row_number || rowIndex" class="table-row">
        <span v-for="column in columns" :key="column.key">{{ cell(row, column) }} </span>
        <slot name="cell-selected" :row="row" />
        <slot name="cell-issues" :row="row" />
        <slot name="cell-node_type" :row="row" />
        <slot name="cell-match_status" :row="row" />
        <slot name="cell-action" :row="row" />
      </div>
      <slot />
    </div>
  `,
})
const PlanningStub = defineComponent({
  props: { locked: Boolean, saving: Boolean },
  emits: ['change'],
  setup(_props, { expose }) {
    expose({ reload: vi.fn(async () => true) })
    return {}
  },
  template: '<div data-test="planning-stub">规划</div>',
})

const elementStubs = {
  ElAlert: AlertStub,
  ElButton: ButtonStub,
  ElCheckbox: CheckboxStub,
  ElDescriptions: Passthrough,
  ElDescriptionsItem: Passthrough,
  ElDialog: DialogStub,
  ElDivider: Passthrough,
  ElInput: InputStub,
  ElInputNumber: InputNumberStub,
  ElOption: OptionStub,
  ElPagination: Passthrough,
  ElSelect: SelectStub,
  ElTabPane: Passthrough,
  ElTabs: Passthrough,
  ElTag: Passthrough,
  NcDataTable: DataTableStub,
  TracksideApPlanningTab: PlanningStub,
}

const baseSummary = {
  site_id: 'demo', site_name: '宁波地铁12号线', line_name: '', project_type: '', network_type: 'default',
  main_path_code: 'MAIN', increasing_direction_name: '上行', decreasing_direction_name: '下行',
  station_source_group_name: '车站', station_source_field: 'station',
  remark: '', created_at: '', updated_at: '', station_count: 0,
  normal_station_count: 0, special_node_count: 0, source_pending_count: 0, source_conflict_count: 0,
  source_stale_count: 0, section_count: 0, ap_count: 0,
  train_count: 0, mr_count: 0, missing_location_ap_count: 0, invalid_mileage_count: 0,
  duplicate_ap_mac_count: 0, duplicate_static_ip_count: 0, unbound_mr_count: 0, issue_count: 0, message: '',
}
const writableSession = {
  site_id: 'demo', base_revision: 'a'.repeat(64), loaded_at: '', can_write: true, write_scope: 'real' as const,
  storage_mode: 'persistent' as const, write_denial_code: '', write_denial_reason: '',
}
const sourceStationWuxiang = {
  id: 'new:source:wuxiang',
  name: '五乡',
  code: '32',
  line_name: '',
  sort_order: 32,
  ap_count: 0,
  section_count: 0,
  mileage_min: null,
  mileage_max: null,
  remark: '',
  source_station_value: '32-五乡',
  source_station_key: '32-五乡',
  node_type: 'station',
  path_code: 'MAIN',
  participates_in_direction: true,
  structure_type: 'unknown',
  platform_layout: 'unknown',
  is_line_terminal: false,
  is_service_terminal: false,
  turnback_capable: false,
  turnback_type: 'none',
  turnback_direction: 'none',
  enabled: true,
  source_kind: 'device_station_field',
  source_device_count: 2,
  source_sync_status: 'matched',
  source_last_seen_at: '',
}
const sourceParkingLot = {
  ...sourceStationWuxiang,
  id: 'new:source:parking',
  name: '高桥西停车场',
  code: '50',
  sort_order: null,
  source_station_value: '50-高桥西停车场',
  source_station_key: '50-高桥西停车场',
  node_type: 'parking_lot',
  path_code: 'UNASSIGNED',
  participates_in_direction: false,
  source_device_count: 1,
}
const sourceConflict = {
  ...sourceStationWuxiang,
  id: 'new:source:conflict',
  name: '冲突站',
  code: '32',
  source_station_value: '32-冲突站',
  source_station_key: '32-冲突站',
  source_device_count: 1,
  source_sync_status: 'conflict',
}
const stationSourcePreviewPayload = {
  site_id: 'demo',
  source_group_name: '车站',
  source_field: 'station',
  group_found: true,
  scanned_device_count: 4,
  empty_station_device_count: 1,
  unique_station_value_count: 3,
  normal_station_count: 2,
  special_node_count: 1,
  create_count: 2,
  match_count: 0,
  conflict_count: 1,
  warning_count: 1,
  issues: [{
    severity: 'warning',
    code: 'station_source_value_empty',
    message: '1 台分组为“车站”的设备 station 字段为空，已跳过',
    field_name: 'station',
    blocking: false,
    entity_id: 'device-empty',
  }],
  candidates: [
    {
      candidate_id: 'station-source:wuxiang',
      source_station_value: '32-五乡',
      source_station_key: '32-五乡',
      code: '32',
      name: '五乡',
      node_type: 'station',
      path_code: 'MAIN',
      sort_order: 32,
      participates_in_direction: true,
      source_device_count: 2,
      match_status: 'create',
      matched_station_id: '',
      proposed_station: sourceStationWuxiang,
      issues: [],
    },
    {
      candidate_id: 'station-source:parking',
      source_station_value: '50-高桥西停车场',
      source_station_key: '50-高桥西停车场',
      code: '50',
      name: '高桥西停车场',
      node_type: 'parking_lot',
      path_code: 'UNASSIGNED',
      sort_order: null,
      participates_in_direction: false,
      source_device_count: 1,
      match_status: 'create',
      matched_station_id: '',
      proposed_station: sourceParkingLot,
      issues: [],
    },
    {
      candidate_id: 'station-source:conflict',
      source_station_value: '32-冲突站',
      source_station_key: '32-冲突站',
      code: '32',
      name: '冲突站',
      node_type: 'station',
      path_code: 'MAIN',
      sort_order: 32,
      participates_in_direction: true,
      source_device_count: 1,
      match_status: 'conflict',
      matched_station_id: '',
      proposed_station: sourceConflict,
      issues: [{
        severity: 'error',
        code: 'station_source_code_conflict',
        message: '相同节点编码对应不同站名',
        field_name: 'code',
        blocking: true,
        entity_id: '',
      }],
    },
  ],
}
const templateStation = {
  ...sourceStationWuxiang,
  id: 'new:template:baozhuang',
  name: '宝幢',
  code: '33',
  sort_order: 33,
  source_station_value: '33-宝幢',
  source_station_key: '33-宝幢',
  structure_type: 'underground',
  platform_layout: 'island',
  source_kind: 'template',
  source_device_count: 0,
  source_sync_status: 'manual',
}
const stationTemplatePreviewPayload = {
  valid: true,
  line_metadata: {
    line_name: '模板线',
    system_type: 'PIS',
    network_domain: 'default',
    main_path_code: 'MAIN',
    increasing_direction_name: '上行',
    decreasing_direction_name: '下行',
    station_source_group_name: '车站',
    station_source_field: 'station',
    remark: '模板备注',
  },
  rows: [{
    row_number: 2,
    source_station_value: '33-宝幢',
    source_station_key: '33-宝幢',
    code: '33',
    name: '宝幢',
    node_type: 'station',
    path_code: 'MAIN',
    sort_order: 33,
    participates_in_direction: true,
    proposed_station: templateStation,
    action: 'create',
    valid: true,
    issues: [],
  }],
  create_count: 1,
  update_count: 0,
  unchanged_count: 0,
  conflict_count: 0,
  blocking_count: 0,
  issues: [],
}

describe('轨道交通基础资料编辑闭环', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.summary.mockResolvedValue({ ...baseSummary })
    mocks.editSession.mockResolvedValue({ ...writableSession })
    mocks.validate.mockResolvedValue({ valid: true, issues: [] })
    mocks.save.mockResolvedValue({
      revision: 'b'.repeat(64), created_count: 0, updated_count: 1, deleted_count: 0,
      warnings: [], validation_issues: [],
    })
    mocks.emptyPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    mocks.issuePage.mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 50, issue_total: 0,
      blocking_total: 0, warning_total: 0, info_total: 0, code_counts: {},
    })
    mocks.importPolicies.mockResolvedValue({
      feature_enabled: true, write_enabled: true, copy_write_authorized: false,
      real_write_authorized: true, rollback_enabled: false, write_scope: 'real',
      identity_boundaries: {}, items: [],
    })
    mocks.importOperations.mockResolvedValue([])
    mocks.stationSourcePreview.mockResolvedValue(stationSourcePreviewPayload)
    mocks.stationTemplatePreview.mockResolvedValue(stationTemplatePreviewPayload)
    mocks.download.mockResolvedValue({ status: 'saved' })
  })

  it('真实点击解锁后建立草稿，并保存线路和项目类型', async () => {
    let saved = false
    mocks.summary.mockImplementation(async () => ({
      ...baseSummary,
      line_name: saved ? '宁波地铁12号线' : '',
      project_type: saved ? 'PIS' : '',
    }))
    mocks.save.mockImplementation(async () => {
      saved = true
      return {
        revision: 'b'.repeat(64), created_count: 0, updated_count: 1, deleted_count: 0,
        warnings: [], validation_issues: [],
      }
    })
    const wrapper = await mountView()

    const unlock = button(wrapper, '解锁')
    expect(unlock.attributes('disabled')).toBeUndefined()
    await unlock.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前处于编辑状态')
    const lineInput = wrapper.find('input[placeholder="请输入线路名称"]')
    expect(lineInput.exists()).toBe(true)
    await lineInput.setValue('宁波地铁12号线')
    await wrapper.find('select[placeholder="请选择或输入项目类型"]').setValue('PIS')
    await nextTick()

    const save = button(wrapper, '保存')
    expect(save.attributes('disabled')).toBeUndefined()
    await save.trigger('click')
    await flushPromises()

    expect(mocks.validate).toHaveBeenCalledWith(expect.objectContaining({
      site_id: 'demo',
      changes: [expect.objectContaining({
        entity_type: 'site_metadata',
        values: expect.objectContaining({ line_name: '宁波地铁12号线', system_type: 'PIS' }),
      })],
    }))
    expect(mocks.save).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('当前处于锁定状态')
    expect(wrapper.text()).toContain('宁波地铁12号线 · 宁波地铁12号线 · PIS')
    wrapper.unmount()
  })

  it('保存失败时保留编辑草稿和可重试状态', async () => {
    mocks.save.mockRejectedValueOnce(new Error('SAVE_FAILED'))
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    const lineInput = wrapper.find('input[placeholder="请输入线路名称"]')
    await lineInput.setValue('待重试线路')
    await wrapper.find('select[placeholder="请选择或输入项目类型"]').setValue('信号')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前处于编辑状态')
    expect(wrapper.find('input[placeholder="请输入线路名称"]').element).toHaveProperty('value', '待重试线路')
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('隔离测试模式禁用解锁并显示明确原因', async () => {
    mocks.editSession.mockResolvedValue({
      ...writableSession,
      can_write: false,
      storage_mode: 'isolated_test',
      write_denial_code: 'ISOLATED_TEST_READONLY',
      write_denial_reason: '隔离测试模式下禁止修改正式局点数据。',
    })
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('隔离测试模式下禁止修改正式局点数据。')
    expect(button(wrapper, '解锁').attributes('disabled')).toBeDefined()
    expect(mocks.save).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('锁定状态可以预览设备站点来源但不能应用草稿', async () => {
    const wrapper = await mountView()

    await button(wrapper, '从设备管理生成').trigger('click')
    await flushPromises()

    expect(mocks.stationSourcePreview).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('设备管理站点来源预览')
    expect(wrapper.text()).toContain('设备管理 · 站点字段')
    expect(wrapper.text()).toContain('五乡')
    expect(wrapper.text()).toContain('高桥西停车场')
    expect(wrapper.text()).toContain('站点字段为空')
    expect(button(wrapper, '应用到当前草稿').attributes('disabled')).toBeDefined()
    expect(mocks.save).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('解锁后将设备来源应用到草稿，点击保存后才提交 validate 和 changes', async () => {
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    await button(wrapper, '从设备管理生成').trigger('click')
    await flushPromises()
    await button(wrapper, '应用到当前草稿').trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('未保存修改')
    expect(wrapper.text()).toContain('五乡')
    expect(wrapper.text()).toContain('高桥西停车场')
    expect(wrapper.text()).not.toContain('五乡1')
    expect(mocks.save).not.toHaveBeenCalled()

    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const payload = mocks.validate.mock.calls.at(-1)?.[0]
    const stationChanges = payload.changes.filter((change: { entity_type: string }) => change.entity_type === 'station')
    const names = stationChanges.map((change: { values: { name: string } }) => change.values.name)
    expect(names).toEqual(expect.arrayContaining(['五乡', '高桥西停车场']))
    expect(names).not.toContain('冲突站')
    expect(names).not.toContain('五乡1')
    expect(stationChanges).toEqual(expect.arrayContaining([
      expect.objectContaining({
        values: expect.objectContaining({
          name: '高桥西停车场',
          node_type: 'parking_lot',
          path_code: 'UNASSIGNED',
          sort_order: null,
          participates_in_direction: false,
          source_kind: 'device_station_field',
        }),
      }),
    ]))
    const parking = stationChanges.find((change: { values: { name: string } }) => change.values.name === '高桥西停车场')
    expect(parking.values).not.toHaveProperty('source_device_count')
    expect(mocks.save).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('模板导入先预览再应用到草稿，保存时统一走基础资料闭环', async () => {
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    const input = wrapper.get('input[accept=".xlsx"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['xlsx'], '线路与站点基础资料.xlsx')],
      configurable: true,
    })
    await input.trigger('change')
    await flushPromises()

    expect(mocks.stationTemplatePreview).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('站点模板导入预览')
    expect(wrapper.text()).toContain('宝幢')
    await button(wrapper, '应用到当前草稿').trigger('click')
    await nextTick()
    expect(mocks.save).not.toHaveBeenCalled()

    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const payload = mocks.validate.mock.calls.at(-1)?.[0]
    expect(payload.changes).toEqual(expect.arrayContaining([
      expect.objectContaining({
        entity_type: 'site_metadata',
        values: expect.objectContaining({ line_name: '模板线', system_type: 'PIS', station_source_field: 'station' }),
      }),
      expect.objectContaining({
        entity_type: 'station',
        values: expect.objectContaining({
          name: '宝幢',
          source_station_value: '33-宝幢',
          structure_type: 'underground',
          platform_layout: 'island',
          source_kind: 'template',
        }),
      }),
    ]))
    expect(mocks.save).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})

async function mountView(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{
      path: '/rail-transit/base-data',
      name: 'rail-transit-base-data',
      component: RailTransitBaseDataView,
      meta: { title: '轨道交通 / 基础资料' },
    }],
  })
  await router.push('/rail-transit/base-data')
  await router.isReady()
  const wrapper = mount(RailTransitBaseDataView, {
    global: {
      plugins: [createPinia(), router],
      directives: { loading: () => undefined },
      stubs: elementStubs,
    },
  })
  await flushPromises()
  return wrapper
}

function button(wrapper: VueWrapper, label: string) {
  const candidate = wrapper.findAll('button').find((item) => item.text().trim() === label)
  if (!candidate) throw new Error(`未找到按钮：${label}`)
  return candidate
}
