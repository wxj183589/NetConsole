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
  stationDeletePreflight: vi.fn(),
  stationConflictPreview: vi.fn(),
  stationTemplatePreview: vi.fn(),
  importPreview: vi.fn(),
  sectionGenerationPreview: vi.fn(),
  stationsPage: vi.fn(),
  sectionsPage: vi.fn(),
  tracksideApsPage: vi.fn(),
  download: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
  messageError: vi.fn(),
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
  listSections: mocks.sectionsPage,
  listStations: mocks.stationsPage,
  listTracksideAps: mocks.tracksideApsPage,
  listTrains: mocks.emptyPage,
  listVehicleMrs: mocks.emptyPage,
  previewRailTransitImport: mocks.importPreview,
  previewSectionGeneration: mocks.sectionGenerationPreview,
  getStationSourcePreview: mocks.stationSourcePreview,
  preflightStationDeletion: mocks.stationDeletePreflight,
  getStationConflictPreview: mocks.stationConflictPreview,
  previewStationTemplate: mocks.stationTemplatePreview,
  rollbackRailTransitImport: vi.fn(),
  saveRailTransitBaseDataChanges: mocks.save,
  stationTemplateDownloadRequest: vi.fn(() => ({ apiPath: '/api/rail-transit/base-data/station-template', suggestedName: '线路站点与区间基础资料模板.xlsx' })),
  stationTemplateExportDownloadRequest: vi.fn(() => ({ apiPath: '/api/rail-transit/base-data/station-template-export', suggestedName: '线路站点与区间基础资料.xlsx' })),
  validateRailTransitBaseDataChanges: mocks.validate,
}))

vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: mocks.download,
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessage: {
      success: mocks.messageSuccess,
      warning: mocks.messageWarning,
      error: mocks.messageError,
    },
  }
})

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
  props: { title: String, description: String, type: String },
  template: '<div class="alert-stub" :data-type="type">{{ title }} {{ description }}<slot /></div>',
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
  props: { modelValue: { type: [String, Boolean, Array], default: '' }, disabled: Boolean },
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
  props: { modelValue: { type: Number, default: null } },
  emits: ['update:modelValue', 'change'],
  methods: {
    update(event: Event) {
      const value = (event.target as HTMLInputElement).value
      const numberValue = value === '' ? null : Number(value)
      this.$emit('update:modelValue', numberValue)
      this.$emit('change', numberValue)
    },
  },
  template: '<input v-bind="$attrs" type="number" :value="modelValue ?? \'\'" @input="update">',
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
  emits: ['selection-change'],
  data: () => ({ selectedRows: [] as Record<string, unknown>[] }),
  methods: {
    cell(row: Record<string, unknown>, column: Record<string, unknown>) {
      const displayValue = column.displayValue
      if (typeof displayValue === 'function') return displayValue(row)
      const value = row[String(column.key)]
      if (Array.isArray(value)) return value.map((item) => item?.message || String(item)).join('；')
      return value ?? ''
    },
    toggle(row: Record<string, unknown>, checked: boolean) {
      this.selectedRows = checked
        ? [...this.selectedRows.filter((item) => item !== row), row]
        : this.selectedRows.filter((item) => item !== row)
      this.$emit('selection-change', this.selectedRows)
    },
    clearSelection() {
      this.selectedRows = []
      this.$emit('selection-change', [])
    },
    toggleRowSelection(row: Record<string, unknown>, selected = true) {
      this.toggle(row, selected)
    },
  },
  template: `
    <div class="table-stub" :data-table-id="tableId">
      <div v-for="(row, rowIndex) in data" :key="row.id || row.candidate_id || row.row_number || rowIndex" class="table-row">
        <input
          v-if="columns.some((column) => column.type === 'selection')"
          class="row-selection"
          type="checkbox"
          :checked="selectedRows.includes(row)"
          @change="toggle(row, $event.target.checked)"
        >
        <span v-for="column in columns" :key="column.key">{{ cell(row, column) }} </span>
        <slot name="cell-selected" :row="row" />
        <slot name="cell-issues" :row="row" />
        <slot name="cell-node_type" :row="row" />
        <slot name="cell-name" :row="row" />
        <slot name="cell-section_kind" :row="row" />
        <slot name="cell-path_code" :row="row" />
        <slot name="cell-start_station" :row="row" />
        <slot name="cell-end_station" :row="row" />
        <slot name="cell-line_direction" :row="row" />
        <slot name="cell-section_mileage_range" :row="row" />
        <slot name="cell-source_kind" :row="row" />
        <slot name="cell-enabled" :row="row" />
        <slot name="cell-remark" :row="row" />
        <slot name="cell-edit_actions" :row="row" />
        <slot name="cell-match_status" :row="row" />
        <slot name="cell-action" :row="row" />
        <slot name="cell-center_mileage_text" :row="row" />
        <slot name="cell-track_facilities" :row="row" />
        <slot name="cell-structure_platform" :row="row" />
        <slot name="cell-result" :row="row" />
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
  ElDrawer: DialogStub,
  ElDivider: Passthrough,
  ElForm: Passthrough,
  ElFormItem: Passthrough,
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
  increasing_direction_leading_end: 'unknown' as const,
  station_source_group_name: '车站', station_source_field: 'station',
  remark: '', created_at: '', updated_at: '', station_count: 0,
  normal_station_count: 0, special_node_count: 0, source_pending_count: 0, source_conflict_count: 0,
  source_stale_count: 0, section_count: 0, ap_count: 0,
  train_count: 0, mr_count: 0, missing_location_ap_count: 0, invalid_mileage_count: 0,
  duplicate_ap_mac_count: 0, duplicate_static_ip_count: 0, unbound_mr_count: 0, issue_count: 0, message: '',
}
const tracksideApRow = (id: string, locationClass: 'MAINLINE' | 'DEPOT') => ({
  id,
  site_id: 'demo',
  line_name: '宁波地铁12号线',
  name: id,
  point_code: id,
  mac: id === 'ap-1' ? '00:11:22:33:44:51' : '00:11:22:33:44:52',
  management_ip: '',
  model: '',
  station: '正线站',
  section: '',
  section_start_station: '',
  section_end_station: '',
  mileage: { raw: '', normalized: '', meters: null, line_type: '', valid: true, error: '' },
  line_side: '',
  line_side_source: 'unavailable' as const,
  line_side_derivation_issue_code: '',
  line_side_derivation_issue_message: '',
  direction: '',
  location_class: locationClass,
  participates_in_mainline: locationClass === 'MAINLINE',
  location_class_source: 'MANUAL_EXPLICIT',
  location_class_conflict: false,
  radios: [],
  remark: '',
  source_file: '',
  source_sheet: '',
  source_row: null,
  updated_at: '',
  runtime: {
    fit_ap_id: '',
    fit_ap_ac_id: '',
    fit_ap_name: '',
    fit_ap_match_status: 'unmatched',
    fit_ap_status: 'unknown',
    optical_status: 'no_data',
    mesh_status: 'unknown',
    mesh_related_name: '',
    latest_session_id: '',
    latest_session_status: '',
    updated_at: '',
  },
  issue_count: 0,
  highest_issue_severity: '',
  record_kind: 'manual',
  base_metadata: {},
})
const writableSession = {
  site_id: 'demo', base_revision: 'a'.repeat(64), loaded_at: '', can_write: true, write_scope: 'real' as const,
  storage_mode: 'persistent' as const, write_denial_code: '', write_denial_reason: '',
}
const sourceStationWuxiang = {
  id: 'new:source:wuxiang',
  node_uid: 'node-wuxiang',
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
  source_station_key: '五乡',
  source_order_text: '32',
  source_order: 32,
  canonical_station_name: '五乡',
  node_type: 'station',
  path_code: 'MAIN',
  participates_in_direction: true,
  structure_type: 'underground',
  platform_layout: 'island',
  center_mileage_text: '',
  center_mileage_m: null,
  is_line_terminal: false,
  is_service_terminal: false,
  turnback_capable: false,
  turnback_type: 'none',
  track_facilities: [],
  turnback_direction: 'none',
  terminal_extension_enabled: false,
  terminal_endpoint_label: '端点',
  terminal_extension_distance_m: null,
  terminal_endpoint_mileage_text: '',
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
  source_station_key: '高桥西停车场',
  source_order_text: '50',
  source_order: 50,
  canonical_station_name: '高桥西停车场',
  node_type: 'parking_lot',
  path_code: 'UNASSIGNED',
  participates_in_direction: false,
  structure_type: 'unknown',
  platform_layout: 'unknown',
  source_device_count: 1,
}
const sourceConflict = {
  ...sourceStationWuxiang,
  id: 'new:source:conflict',
  name: '冲突站',
  code: '32',
  source_station_value: '32-冲突站',
  source_station_key: '冲突站',
  canonical_station_name: '冲突站',
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
      source_station_key: '五乡',
      source_order_text: '32',
      source_order: 32,
      code: '32',
      name: '五乡',
      canonical_station_name: '五乡',
      node_type: 'station',
      path_code: 'MAIN',
      sort_order: 32,
      participates_in_direction: true,
      source_device_count: 2,
      match_status: 'create',
      matched_station_id: '',
      matched_station_name: '',
      suggested_action: '新增',
      proposed_station: sourceStationWuxiang,
      issues: [],
    },
    {
      candidate_id: 'station-source:parking',
      source_station_value: '50-高桥西停车场',
      source_station_key: '高桥西停车场',
      source_order_text: '50',
      source_order: 50,
      code: '50',
      name: '高桥西停车场',
      canonical_station_name: '高桥西停车场',
      node_type: 'parking_lot',
      path_code: 'UNASSIGNED',
      sort_order: null,
      participates_in_direction: false,
      source_device_count: 1,
      match_status: 'create',
      matched_station_id: '',
      matched_station_name: '',
      suggested_action: '新增',
      proposed_station: sourceParkingLot,
      issues: [],
    },
    {
      candidate_id: 'station-source:conflict',
      source_station_value: '32-冲突站',
      source_station_key: '冲突站',
      source_order_text: '32',
      source_order: 32,
      code: '32',
      name: '冲突站',
      canonical_station_name: '冲突站',
      node_type: 'station',
      path_code: 'MAIN',
      sort_order: 32,
      participates_in_direction: true,
      source_device_count: 1,
      match_status: 'conflict',
      matched_station_id: '',
      matched_station_name: '',
      suggested_action: '人工确认',
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
  source_station_key: '宝幢',
  source_order_text: '33',
  source_order: 33,
  canonical_station_name: '宝幢',
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
  section_rows: [],
  section_sheet_present: true,
  create_count: 1,
  update_count: 0,
  unchanged_count: 0,
  conflict_count: 0,
  blocking_count: 0,
  issues: [],
}
const generatedIncreasingSection = {
  id: 'new:auto:increasing',
  name: '高桥西-高桥-上行',
  section_code: 'AUTO-INCREASING',
  section_kind: 'between_stations',
  path_code: 'MAIN',
  direction_role: 'increasing',
  line_direction: '上行',
  start_node_type: 'station',
  start_node_uid: 'node-low',
  start_station: '高桥西',
  end_node_type: 'station',
  end_node_uid: 'node-high',
  end_station: '高桥',
  line_side: '上行',
  auto_generated: true,
  generation_key: 'MAIN|between|node-low|node-high|increasing',
  manual_override_fields: [],
  section_mileage_start_m: 152,
  section_mileage_end_m: 1801,
  section_mileage_open_end: false,
  section_mileage_source: 'generated',
  enabled: true,
  source_kind: 'generated',
  ap_count: 0,
  mileage_min: null,
  mileage_max: null,
  remark: '',
}
const generatedDecreasingSection = {
  ...generatedIncreasingSection,
  id: 'new:auto:decreasing',
  name: '高桥西-高桥-下行',
  section_code: 'AUTO-DECREASING',
  direction_role: 'decreasing',
  line_direction: '下行',
  start_node_uid: 'node-high',
  start_station: '高桥',
  end_node_uid: 'node-low',
  end_station: '高桥西',
  line_side: '下行',
  generation_key: 'MAIN|between|node-low|node-high|decreasing',
}
const staleGeneratedSection = {
  ...generatedIncreasingSection,
  id: 'section:stale',
  name: '旧区间-上行',
  section_code: 'AUTO-STALE',
  start_node_uid: 'node-old-low',
  start_station: '旧站甲',
  end_node_uid: 'node-old-high',
  end_station: '旧站乙',
  generation_key: 'MAIN|between|node-old-low|node-old-high|increasing',
}
const sectionGenerationPreviewPayload = {
  site_id: 'demo',
  base_revision: 'a'.repeat(64),
  generated_sections: [
    {
      item_id: 'generation:create:increasing',
      result: 'CREATE',
      proposed_section: generatedIncreasingSection,
      current_section: null,
      selected_by_default: true,
      selectable: true,
      issues: [],
    },
    {
      item_id: 'generation:create:decreasing',
      result: 'CREATE',
      proposed_section: generatedDecreasingSection,
      current_section: null,
      selected_by_default: true,
      selectable: true,
      issues: [],
    },
    {
      item_id: 'generation:stale',
      result: 'STALE',
      proposed_section: null,
      current_section: staleGeneratedSection,
      selected_by_default: false,
      selectable: true,
      issues: [{
        severity: 'warning',
        code: 'section_generation_stale',
        message: '旧自动区间已过期，默认保留',
        field_name: 'generation_key',
        blocking: false,
        entity_id: 'section:stale',
      }],
    },
  ],
  create_count: 2,
  update_count: 0,
  unchanged_count: 0,
  conflict_count: 0,
  stale_count: 1,
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
    mocks.stationsPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    mocks.sectionsPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    mocks.tracksideApsPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
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
    mocks.stationDeletePreflight.mockResolvedValue({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      items: [],
      safe_delete_count: 0,
      requires_merge_count: 0,
      blocked_count: 0,
    })
    mocks.stationConflictPreview.mockResolvedValue({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      groups: [],
      conflict_group_count: 0,
      conflict_station_count: 0,
      recommended_overwrite_count: 0,
      recommended_merge_count: 0,
      remaining_manual_count: 0,
    })
    mocks.stationTemplatePreview.mockResolvedValue(stationTemplatePreviewPayload)
    mocks.sectionGenerationPreview.mockResolvedValue(sectionGenerationPreviewPayload)
    mocks.download.mockResolvedValue({ status: 'saved' })
  })

  it('单个业务接口失败时显示部分刷新失败并保留已加载站点', async () => {
    mocks.stationsPage.mockResolvedValue({
      items: [sourceStationWuxiang],
      total: 1,
      page: 1,
      page_size: 50,
    })
    mocks.issuePage.mockRejectedValue(new Error('connection reset'))

    const wrapper = await mountView()

    const warning = wrapper.findAll('.alert-stub').find(
      (item) => item.text().includes('部分基础资料刷新失败，已保留最后成功数据。'),
    )
    expect(warning?.attributes('data-type')).toBe('warning')
    expect(warning?.text()).toContain('数据质量问题')
    expect(warning?.text()).toContain('错误码：UNEXPECTED_ERROR')
    expect(warning?.text()).toContain('连续失败：1 次')
    expect(warning?.text()).toContain('最近成功：尚无成功记录')
    expect(warning?.text()).toContain('该项目暂无成功缓存')
    expect(wrapper.text()).not.toContain('Backend 连接中断，请重试。')
    expect(wrapper.get('[data-table-id="rail-base-stations"]').text()).toContain(
      sourceStationWuxiang.name,
    )
    wrapper.unmount()
  })

  it('总览尚无成功数据且加载失败时不把未知统计显示为零', async () => {
    mocks.summary.mockRejectedValue(new Error('summary unavailable'))

    const wrapper = await mountView()

    const stationCard = wrapper.findAll('.summary-grid article').find(
      (item) => item.text().includes('站点'),
    )
    expect(stationCard?.text()).toContain('加载失败')
    expect(stationCard?.text()).not.toMatch(/站点\s*0/)
    expect(wrapper.text()).toContain('部分基础资料刷新失败，已保留最后成功数据。')
    expect(wrapper.text()).not.toContain('Backend 连接中断，请重试。')
    wrapper.unmount()
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

  it('手工新增轨旁 AP 未选择位置类型时默认按正线保存', async () => {
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    await button(wrapper, '新增轨旁 AP').trigger('click')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const apChange = mocks.validate.mock.calls.at(-1)?.[0].changes.find(
      (change: { entity_type: string }) => change.entity_type === 'trackside_ap',
    )
    expect(apChange).toMatchObject({
      action: 'create',
      values: {
        location_class: 'MAINLINE',
        participates_in_mainline: true,
        location_class_source: 'DEFAULT_MAINLINE',
      },
    })
    wrapper.unmount()
  })

  it.each([
    {
      targetClass: 'MAINLINE',
      targetLabel: '正线',
      sourceClass: 'DEPOT',
      participates: true,
    },
    {
      targetClass: 'DEPOT',
      targetLabel: '车辆段',
      sourceClass: 'MAINLINE',
      participates: false,
    },
  ] as const)(
    '批量设置轨旁 AP 为$targetLabel时同步正线资格',
    async ({ targetClass, targetLabel, sourceClass, participates }) => {
      mocks.tracksideApsPage.mockResolvedValue({
        items: [
          tracksideApRow('ap-1', sourceClass),
          tracksideApRow('ap-2', sourceClass),
        ],
        total: 2,
        page: 1,
        page_size: 50,
      })
      const wrapper = await mountView()
      await button(wrapper, '解锁').trigger('click')
      await flushPromises()

      const table = wrapper.get('[data-table-id="rail-base-trackside-aps"]')
      for (const selection of table.findAll('input.row-selection')) {
        await selection.setValue(true)
      }
      await wrapper
        .get('select[placeholder="批量位置类型"]')
        .setValue(targetClass)
      await button(wrapper, '批量设置位置类型').trigger('click')
      await button(wrapper, '保存').trigger('click')
      await flushPromises()

      const apChanges = mocks.validate.mock.calls
        .at(-1)?.[0].changes.filter(
          (change: { entity_type: string }) =>
            change.entity_type === 'trackside_ap',
        )
      expect(apChanges).toHaveLength(2)
      expect(apChanges.map((change: { entity_id: string }) => change.entity_id)).toEqual([
        'ap-1',
        'ap-2',
      ])
      for (const change of apChanges) {
        expect(change.values).toMatchObject({
          location_class: targetClass,
          participates_in_mainline: participates,
          location_class_source: 'MANUAL_EXPLICIT',
        })
      }
      expect(mocks.messageSuccess).toHaveBeenCalledWith(
        `已将 2 条轨旁 AP 设为${targetLabel}`,
      )
      wrapper.unmount()
    },
  )

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

  it('规范站名覆盖既有编号名称并保留节点身份和人工字段', async () => {
    const existing = {
      ...sourceStationWuxiang,
      id: 'station:existing',
      node_uid: 'node-existing',
      name: '1.五乡',
      code: '1',
      sort_order: 1,
      source_station_value: '',
      source_station_key: '',
      source_order_text: '',
      source_order: null,
      canonical_station_name: '五乡',
      center_mileage_text: 'K12+345',
      center_mileage_m: 12345,
      platform_layout: 'side' as const,
      remark: '人工备注',
    }
    const proposed = {
      ...sourceStationWuxiang,
      id: existing.id,
      node_uid: existing.node_uid,
      name: '五乡',
      code: '01',
      sort_order: 1,
      source_station_value: '01五乡',
      source_station_key: '五乡',
      source_order_text: '01',
      source_order: 1,
      canonical_station_name: '五乡',
    }
    mocks.stationsPage.mockResolvedValue({ items: [existing], total: 1, page: 1, page_size: 50 })
    mocks.stationSourcePreview.mockResolvedValue({
      ...stationSourcePreviewPayload,
      scanned_device_count: 1,
      empty_station_device_count: 0,
      unique_station_value_count: 1,
      normal_station_count: 1,
      special_node_count: 0,
      create_count: 0,
      match_count: 1,
      conflict_count: 0,
      warning_count: 0,
      issues: [],
      candidates: [{
        candidate_id: 'station-source:wuxiang-matched',
        source_station_value: '01五乡',
        source_station_key: '五乡',
        source_order_text: '01',
        source_order: 1,
        code: '01',
        name: '五乡',
        canonical_station_name: '五乡',
        node_type: 'station',
        path_code: 'MAIN',
        sort_order: 1,
        participates_in_direction: true,
        source_device_count: 1,
        match_status: 'matched',
        matched_station_id: existing.id,
        matched_station_name: existing.name,
        suggested_action: '覆盖现有',
        proposed_station: proposed,
        issues: [],
      }],
    })

    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    await button(wrapper, '从设备管理生成').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('覆盖现有')
    expect(wrapper.text()).toContain('1.五乡')
    await button(wrapper, '应用到当前草稿').trigger('click')
    await nextTick()
    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const change = mocks.validate.mock.calls.at(-1)?.[0].changes.find(
      (item: { entity_type: string }) => item.entity_type === 'station',
    )
    expect(change).toMatchObject({
      action: 'update',
      entity_id: existing.id,
      values: {
        old_name: '1.五乡',
        node_uid: existing.node_uid,
        name: '五乡',
        code: '01',
        sort_order: 1,
        source_station_value: '01五乡',
        source_order_text: '01',
        source_order: 1,
        canonical_station_name: '五乡',
        center_mileage_text: 'K12+345',
        center_mileage_m: 12345,
        platform_layout: 'side',
        remark: '人工备注',
      },
    })
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
    expect(wrapper.text()).toContain('基础资料模板导入预览')
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

  it('轨旁 AP 预览存在冲突和无效行时仍允许导入有效数据', async () => {
    mocks.importPreview.mockResolvedValue({
      preview_id: 'preview-1',
      file_name: '轨旁AP.xlsx',
      file_size: 1024,
      template_type: 'ap_switch_port_point_table',
      confidence_score: 100,
      total_rows: 3,
      valid_rows: 1,
      error_count: 2,
      warning_count: 1,
      sheet_names: ['轨旁AP'],
      statistics: { unmatched_fit_ap_rows: 1 },
      rows: [],
      database_hash: 'a'.repeat(64),
      preview_expires_at: '2026-07-30T12:00:00+00:00',
      write_enabled: false,
      message: '',
      merge_plan: {
        plan_id: 'plan-1',
        site_id: 'demo',
        source_file_name: '轨旁AP.xlsx',
        source_file_sha256: 'b'.repeat(64),
        source_type: 'official_point_table',
        database_hash: 'a'.repeat(64),
        created_at: '2026-07-30T11:00:00+00:00',
        preview_expires_at: '2026-07-30T12:00:00+00:00',
        write_enabled: false,
        items: [
          {
            row_number: 1, entity_type: 'ap', source_identity: { ap_point_code: 'AP001', ap_mac: '0011-2233-4401' },
            matched_entity_id: '', matched_entity_name: '', match_method: 'no_exact_match',
            result: 'CREATE', conflict_summary: '', field_diffs: [], source_values: {
              ap_point_code: 'AP001', ap_mac_norm: '001122334401',
            }, blocking: false, issues: [{
              severity: 'warning', code: 'fit_ap_unmatched', entity_type: 'ap', entity_id: '',
              entity_name: '', row_number: 1, field_name: 'ap_mac_display', original_value: '',
              message: '当前局点暂无对应 FIT-AP 运行态资料', suggested_action: '', blocking: false,
            }],
          },
          {
            row_number: 2, entity_type: 'ap', source_identity: { ap_point_code: 'AP002', ap_mac: '0011-2233-4402' },
            matched_entity_id: '', matched_entity_name: '', match_method: 'cross_key',
            result: 'CONFLICT', conflict_summary: '身份冲突', field_diffs: [], source_values: {},
            blocking: true, issues: [],
          },
          {
            row_number: 3, entity_type: 'ap', source_identity: { ap_point_code: 'AP003', ap_mac: 'bad' },
            matched_entity_id: '', matched_entity_name: '', match_method: '',
            result: 'INVALID', conflict_summary: '', field_diffs: [], source_values: {},
            blocking: true, issues: [{
              severity: 'error', code: 'ap_mac_invalid', entity_type: 'ap', entity_id: '',
              entity_name: '', row_number: 3, field_name: 'ap_mac_display', original_value: 'bad',
              message: 'AP MAC 格式无效', suggested_action: '', blocking: true,
            }],
          },
        ],
        summary: {
          total_rows: 3, importable_count: 1, create_count: 1, update_count: 0,
          unchanged_count: 0, skip_count: 0, conflict_count: 1, invalid_count: 1,
          warning_count: 1, unmatched_fit_ap_count: 1, needs_confirmation_count: 0,
          blocking_count: 2,
        },
      },
    })
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    const input = wrapper.find('input[accept=".xlsx,.csv,.json"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['preview'], '轨旁AP.xlsx')],
    })
    await input.trigger('change')
    await flushPromises()

    const importButton = button(wrapper, '导入 1 条有效数据到草稿')
    expect(importButton.attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('仅显示冲突')
    expect(wrapper.text()).toContain('仅显示无效')
    expect(wrapper.text()).not.toContain('我已核对差异、冲突和目标局点')
    wrapper.unmount()
  })

  it('下载模板区分桌面保存、用户取消和真实失败', async () => {
    const wrapper = await mountView()

    await button(wrapper, '下载模板').trigger('click')
    await flushPromises()
    expect(mocks.download).toHaveBeenLastCalledWith({
      apiPath: '/api/rail-transit/base-data/station-template',
      suggestedName: '线路站点与区间基础资料模板.xlsx',
    })
    expect(mocks.messageSuccess).toHaveBeenLastCalledWith('线路站点与区间模板已保存')

    mocks.messageSuccess.mockClear()
    mocks.download.mockResolvedValueOnce({ status: 'cancelled' })
    await button(wrapper, '下载模板').trigger('click')
    await flushPromises()
    expect(mocks.messageSuccess).not.toHaveBeenCalled()
    expect(mocks.messageError).not.toHaveBeenCalled()

    mocks.download.mockResolvedValueOnce({ status: 'failed', error: '目标文件不可写' })
    await button(wrapper, '下载模板').trigger('click')
    await flushPromises()
    expect(mocks.messageError).toHaveBeenLastCalledWith('目标文件不可写')
    wrapper.unmount()
  })

  it('未保存草稿导出正式数据时给出提示并调用正确接口', async () => {
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    await button(wrapper, '新增节点').trigger('click')
    await nextTick()

    await button(wrapper, '导出当前').trigger('click')
    await flushPromises()

    expect(mocks.messageWarning).toHaveBeenCalledWith('未保存修改不包含在本次导出中')
    expect(mocks.download).toHaveBeenLastCalledWith({
      apiPath: '/api/rail-transit/base-data/station-template-export',
      suggestedName: '线路站点与区间基础资料.xlsx',
    })
    wrapper.unmount()
  })

  it('MAIN 手工新站默认地下岛式且中心里程进入待保存变更', async () => {
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    await button(wrapper, '新增节点').trigger('click')
    await nextTick()

    const stationTable = wrapper.get('[data-table-id="rail-base-stations"]')
    await stationTable.get('input:not([type])').setValue('高桥西')
    await stationTable.get('input[placeholder="如 K12+345"]').setValue('K12+345')
    await nextTick()
    expect(wrapper.text()).toContain('未保存修改')

    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const payload = mocks.validate.mock.calls.at(-1)?.[0]
    expect(payload.changes).toEqual(expect.arrayContaining([
      expect.objectContaining({
        entity_type: 'station',
        action: 'create',
        values: expect.objectContaining({
          name: '高桥西',
          path_code: 'MAIN',
          structure_type: 'underground',
          platform_layout: 'island',
          center_mileage_text: 'K12+345',
        }),
      }),
    ]))
    wrapper.unmount()
  })

  it('锁定状态以多个标签展示轨道设施并允许模板预览但禁止应用', async () => {
    mocks.stationsPage.mockResolvedValue({
      items: [{
        ...sourceStationWuxiang,
        id: 'station:wuxiang',
        track_facilities: ['turnback_track', 'storage_track', 'depot_connection'],
      }],
      total: 1,
      page: 1,
      page_size: 50,
    })
    const wrapper = await mountView()
    const stationTable = wrapper.get('[data-table-id="rail-base-stations"]')
    expect(stationTable.text()).toContain('折返线')
    expect(stationTable.text()).toContain('存车线')
    expect(stationTable.text()).toContain('出入段线')

    const input = wrapper.get('input[accept=".xlsx"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['xlsx'], '线路站点与区间基础资料.xlsx')],
      configurable: true,
    })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.text()).toContain('基础资料模板导入预览')
    expect(button(wrapper, '应用到当前草稿').attributes('disabled')).toBeDefined()
    expect(mocks.save).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('区间生成预览使用当前草稿，默认保留过期项并可取消单个方向', async () => {
    mocks.stationsPage.mockResolvedValue({
      items: [
        {
          ...sourceStationWuxiang,
          id: 'station:low',
          node_uid: 'node-low',
          name: '高桥西',
          code: '11',
          sort_order: 11,
        },
        {
          ...sourceStationWuxiang,
          id: 'station:high',
          node_uid: 'node-high',
          name: '高桥',
          code: '12',
          sort_order: 12,
        },
      ],
      total: 2,
      page: 1,
      page_size: 50,
    })
    mocks.sectionsPage.mockResolvedValue({
      items: [staleGeneratedSection],
      total: 1,
      page: 1,
      page_size: 50,
    })
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    await button(wrapper, '根据站点生成区间').trigger('click')
    await flushPromises()

    expect(mocks.sectionGenerationPreview).toHaveBeenCalledWith(expect.objectContaining({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      stations: expect.arrayContaining([
        expect.objectContaining({ name: '高桥西', node_uid: 'node-low' }),
        expect.objectContaining({ name: '高桥', node_uid: 'node-high' }),
      ]),
      current_sections: [expect.objectContaining({ id: 'section:stale' })],
    }))
    const previewTable = wrapper.get('[data-table-id="rail-base-section-generation-preview"]')
    expect(previewTable.text()).toContain('高桥西-高桥-上行')
    expect(previewTable.text()).toContain('高桥西-高桥-下行')
    const checkboxes = previewTable.findAll('input[type="checkbox"]')
    expect(checkboxes).toHaveLength(3)
    expect((checkboxes[0].element as HTMLInputElement).checked).toBe(true)
    expect((checkboxes[1].element as HTMLInputElement).checked).toBe(true)
    expect((checkboxes[2].element as HTMLInputElement).checked).toBe(false)

    await checkboxes[1].setValue(false)
    await button(wrapper, '应用到当前草稿').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('未保存修改')
    expect(mocks.save).not.toHaveBeenCalled()

    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    const payload = mocks.validate.mock.calls.at(-1)?.[0]
    const sectionChanges = payload.changes.filter((change: { entity_type: string }) => change.entity_type === 'section')
    expect(sectionChanges).toHaveLength(1)
    expect(sectionChanges[0]).toMatchObject({
      action: 'create',
      values: {
        name: '高桥西-高桥-上行',
        start_station: '高桥西',
        end_station: '高桥',
      },
    })
    wrapper.unmount()
  })

  it('解锁后可编辑自动区间并记录人工覆盖，端点展示名不会进入保存值', async () => {
    mocks.stationsPage.mockResolvedValue({
      items: [
        { ...sourceStationWuxiang, id: 'station:low', node_uid: 'node-low', name: '高桥西', sort_order: 11, is_line_terminal: true, terminal_extension_enabled: true },
        { ...sourceStationWuxiang, id: 'station:high', node_uid: 'node-high', name: '高桥', sort_order: 12 },
      ],
      total: 2,
      page: 1,
      page_size: 50,
    })
    mocks.sectionsPage.mockResolvedValue({ items: [generatedIncreasingSection], total: 1, page: 1, page_size: 50 })
    const wrapper = await mountView()
    const sectionTable = wrapper.get('[data-table-id="rail-base-sections"]')
    expect(sectionTable.find('input[data-field="section-name"]').exists()).toBe(false)

    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    const nameInput = sectionTable.get('input[data-field="section-name"]')
    await nameInput.setValue('现场专用区间')
    const startSelect = sectionTable.get('select[data-field="section-start-node"]')
    expect(startSelect.text()).toContain('端点（高桥西端）')
    await startSelect.setValue('endpoint:MAIN:low')
    await sectionTable.get('select[data-field="section-direction"]').setValue('下行')
    await nextTick()

    expect(sectionTable.text()).toContain('自动生成 · 已调整')
    expect(wrapper.text()).toContain('未保存修改')
    expect(mocks.save).not.toHaveBeenCalled()

    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    const sectionChange = mocks.validate.mock.calls.at(-1)?.[0].changes.find((change: { entity_type: string }) => change.entity_type === 'section')
    expect(sectionChange.values).toMatchObject({
      name: '现场专用区间',
      start_node_type: 'terminal_endpoint',
      start_node_uid: 'endpoint:MAIN:low',
      start_station: '端点',
      direction_role: 'decreasing',
      line_direction: '下行',
      line_side: '左线',
      auto_generated: true,
      source_kind: 'generated',
      generation_key: generatedIncreasingSection.generation_key,
    })
    expect(sectionChange.values.start_station).not.toContain('高桥西端')
    expect(sectionChange.values.manual_override_fields).toEqual(expect.arrayContaining([
      'name', 'start_node_type', 'start_node_uid', 'start_station', 'direction_role', 'line_direction', 'line_side',
    ]))
    wrapper.unmount()
  })

  it('显示并编辑独立的区间物理里程范围，不改写 AP 统计字段', async () => {
    mocks.sectionsPage.mockResolvedValue({ items: [generatedIncreasingSection], total: 1, page: 1, page_size: 50 })
    const wrapper = await mountView()
    const sectionTable = wrapper.get('[data-table-id="rail-base-sections"]')

    expect(sectionTable.text()).toContain('152–1801 m')
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    await sectionTable.get('input[data-field="section-mileage-start"]').setValue('160')
    await sectionTable.get('input[data-field="section-mileage-end"]').setValue('1800')

    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    const sectionChange = mocks.validate.mock.calls.at(-1)?.[0].changes.find((change: { entity_type: string }) => change.entity_type === 'section')
    expect(sectionChange.values).toMatchObject({
      section_mileage_start_m: 160,
      section_mileage_end_m: 1800,
      section_mileage_open_end: false,
      section_mileage_source: 'manual',
    })
    expect(sectionChange.values.manual_override_fields).toEqual(expect.arrayContaining([
      'section_mileage_start_m', 'section_mileage_end_m', 'section_mileage_source',
    ]))
    expect(sectionChange.values).not.toHaveProperty('mileage_min')
    expect(sectionChange.values).not.toHaveProperty('mileage_max')
    wrapper.unmount()
  })

  it('高里程端开放范围显示为加号格式', async () => {
    mocks.sectionsPage.mockResolvedValue({
      items: [{
        ...generatedIncreasingSection,
        id: 'section:terminal-high',
        name: '霞浦-端点-上行',
        section_kind: 'terminal_extension',
        section_mileage_start_m: 45574,
        section_mileage_end_m: null,
        section_mileage_open_end: true,
      }],
      total: 1,
      page: 1,
      page_size: 50,
    })
    const wrapper = await mountView()
    expect(wrapper.get('[data-table-id="rail-base-sections"]').text()).toContain('45574+ m')
    wrapper.unmount()
  })

  it('恢复自动值只修改草稿并清空人工覆盖字段', async () => {
    mocks.sectionsPage.mockResolvedValue({
      items: [{
        ...generatedIncreasingSection,
        name: '已保存人工名称',
        manual_override_fields: ['name', 'section_mileage_start_m', 'section_mileage_source'],
        section_mileage_start_m: 155,
        section_mileage_source: 'manual',
      }],
      total: 1,
      page: 1,
      page_size: 50,
    })
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    const sectionTable = wrapper.get('[data-table-id="rail-base-sections"]')
    await button(wrapper, '恢复自动值').trigger('click')
    await flushPromises()

    expect(mocks.sectionGenerationPreview).toHaveBeenCalledWith(expect.objectContaining({ current_sections: [] }))
    expect(mocks.save).not.toHaveBeenCalled()
    expect((sectionTable.get('input[data-field="section-name"]').element as HTMLInputElement).value).toBe('高桥西-高桥-上行')
    expect(sectionTable.text()).toContain('自动生成')
    expect(sectionTable.text()).not.toContain('自动生成 · 已调整')

    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    const sectionChange = mocks.validate.mock.calls.at(-1)?.[0].changes.find((change: { entity_type: string }) => change.entity_type === 'section')
    expect(sectionChange.values.manual_override_fields).toEqual([])
    expect(sectionChange.values.section_mileage_start_m).toBe(152)
    expect(sectionChange.values.section_mileage_end_m).toBe(1801)
    expect(sectionChange.values.section_mileage_source).toBe('generated')
    wrapper.unmount()
  })

  it('区间生成冲突项不可勾选', async () => {
    mocks.sectionGenerationPreview.mockResolvedValue({
      ...sectionGenerationPreviewPayload,
      generated_sections: [{
        item_id: 'generation:conflict',
        result: 'CONFLICT',
        proposed_section: generatedIncreasingSection,
        current_section: {
          ...generatedIncreasingSection,
          id: 'section:manual',
          auto_generated: false,
          generation_key: '',
          source_kind: 'manual',
        },
        selected_by_default: false,
        selectable: false,
        issues: [{
          severity: 'error',
          code: 'section_generation_conflict',
          message: '与人工区间同名',
          field_name: 'name',
          blocking: true,
          entity_id: 'section:manual',
        }],
      }],
      create_count: 0,
      conflict_count: 1,
      stale_count: 0,
      blocking_count: 1,
    })
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    await button(wrapper, '根据站点生成区间').trigger('click')
    await flushPromises()

    const checkbox = wrapper.get('[data-table-id="rail-base-section-generation-preview"] input[type="checkbox"]')
    expect(checkbox.attributes('disabled')).toBeDefined()
    expect(button(wrapper, '应用到当前草稿').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('站点选择仅在解锁后可用，批量删除预检不会静默跳过阻断项', async () => {
    const safeStation = { ...sourceStationWuxiang, id: 'station:safe', node_uid: 'node-safe', name: '安全站', code: '01', sort_order: 1, source_kind: 'manual' }
    const blockedStation = { ...sourceStationWuxiang, id: 'station:blocked', node_uid: 'node-blocked', name: '被引用站', code: '02', sort_order: 2, source_kind: 'manual' }
    mocks.stationsPage.mockResolvedValue({ items: [safeStation, blockedStation], total: 2, page: 1, page_size: 50 })
    mocks.stationDeletePreflight.mockResolvedValue({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      safe_delete_count: 1,
      requires_merge_count: 1,
      blocked_count: 0,
      items: [
        {
          station_id: safeStation.id, station_name: safeStation.name, code: safeStation.code, sort_order: 1,
          source_kind: 'manual', status: 'SAFE_DELETE', reason: '无正式引用', is_manual: true, is_line_terminal: false,
          references: { section_start_count: 0, section_end_count: 0, ap_count: 0, relation_count: 0, endpoint_extension_count: 0, plan_count: 0, total_count: 0 },
        },
        {
          station_id: blockedStation.id, station_name: blockedStation.name, code: blockedStation.code, sort_order: 2,
          source_kind: 'manual', status: 'REQUIRES_MERGE', reason: '存在区间引用', is_manual: true, is_line_terminal: false,
          references: { section_start_count: 1, section_end_count: 0, ap_count: 1, relation_count: 0, endpoint_extension_count: 0, plan_count: 0, total_count: 2 },
        },
      ],
    })
    const wrapper = await mountView()
    const stationTable = wrapper.get('[data-table-id="rail-base-stations"]')
    expect(stationTable.findAll('input.row-selection')).toHaveLength(0)

    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    const selections = stationTable.findAll('input.row-selection')
    expect(selections).toHaveLength(2)
    await selections[0].setValue(true)
    await selections[1].setValue(true)
    expect(wrapper.text()).toContain('已选择 2 项')

    await button(wrapper, '删除选中').trigger('click')
    await flushPromises()
    expect(mocks.stationDeletePreflight).toHaveBeenCalledWith({
      site_id: 'demo',
      base_revision: 'a'.repeat(64),
      station_ids: [safeStation.id, blockedStation.id],
    })
    expect(wrapper.text()).toContain('REQUIRES_MERGE')
    expect(wrapper.text()).toContain('不会被静默跳过')
    await button(wrapper, '仅标记安全项').trigger('click')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const changes = mocks.validate.mock.calls.at(-1)?.[0].changes
    expect(changes).toEqual([
      expect.objectContaining({ entity_type: 'station', action: 'delete', entity_id: safeStation.id }),
    ])
    expect(changes).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ entity_id: blockedStation.id }),
    ]))
    wrapper.unmount()
  })

  it('合并重复站点生成单个 replace 草稿并保留正式目标身份', async () => {
    const formal = {
      ...sourceStationWuxiang,
      id: 'station:formal',
      node_uid: 'node-formal',
      name: '小洋江站',
      code: '01',
      sort_order: 1,
      source_kind: 'manual',
      source_station_key: '',
      source_station_value: '',
      remark: '人工字段',
    }
    const duplicate = {
      ...sourceStationWuxiang,
      id: 'station:duplicate',
      node_uid: 'node-duplicate',
      name: '1.小洋江站',
      code: '01',
      sort_order: 1,
      source_kind: 'device_station_field',
      source_station_key: '01小洋江站',
      source_station_value: '01小洋江站',
    }
    mocks.stationsPage.mockResolvedValue({ items: [formal, duplicate], total: 2, page: 1, page_size: 50 })
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()
    const selections = wrapper.get('[data-table-id="rail-base-stations"]').findAll('input.row-selection')
    await selections[0].setValue(true)
    await selections[1].setValue(true)
    await button(wrapper, '合并重复项').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('将被合并删除')
    expect(wrapper.text()).toContain('保留身份')
    expect(wrapper.text()).toContain(formal.node_uid)
    await button(wrapper, '应用合并到草稿').trigger('click')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()

    const mergeChange = mocks.validate.mock.calls.at(-1)?.[0].changes.find((change: { action: string }) => change.action === 'replace')
    expect(mergeChange).toMatchObject({
      entity_type: 'station',
      entity_id: formal.id,
      values: {
        node_uid: formal.node_uid,
        old_name: formal.name,
        merge_source_names: [duplicate.name],
        merge_source_node_uids: [duplicate.node_uid],
      },
    })
    wrapper.unmount()
  })

  it('撤销站点合并只恢复相关引用，不覆盖其他区间草稿修改', async () => {
    const formal = {
      ...sourceStationWuxiang,
      id: 'station:formal',
      node_uid: 'node-formal',
      name: '小洋江站',
      code: '01',
      sort_order: 1,
      source_kind: 'manual',
      source_station_key: '',
      source_station_value: '',
    }
    const duplicate = {
      ...sourceStationWuxiang,
      id: 'station:duplicate',
      node_uid: 'node-duplicate',
      name: '1.小洋江站',
      code: '01',
      sort_order: 1,
      source_kind: 'device_station_field',
    }
    const referencedSection = {
      ...generatedIncreasingSection,
      id: 'section:referenced',
      name: '小洋江-下一站',
      start_node_uid: duplicate.node_uid,
      start_station: duplicate.name,
      end_node_uid: 'node-next',
      end_station: '下一站',
    }
    const unrelatedSection = {
      ...generatedIncreasingSection,
      id: 'section:unrelated',
      name: '其他区间',
      start_node_uid: 'node-other-a',
      start_station: '其他站A',
      end_node_uid: 'node-other-b',
      end_station: '其他站B',
    }
    mocks.stationsPage.mockResolvedValue({ items: [formal, duplicate], total: 2, page: 1, page_size: 50 })
    mocks.sectionsPage.mockResolvedValue({ items: [referencedSection, unrelatedSection], total: 2, page: 1, page_size: 50 })
    const wrapper = await mountView()
    await button(wrapper, '解锁').trigger('click')
    await flushPromises()

    const sectionNames = wrapper.get('[data-table-id="rail-base-sections"]').findAll('input[data-field="section-name"]')
    await sectionNames[1].setValue('其他区间-人工修改')
    const selections = wrapper.get('[data-table-id="rail-base-stations"]').findAll('input.row-selection')
    await selections[0].setValue(true)
    await selections[1].setValue(true)
    await button(wrapper, '合并重复项').trigger('click')
    await button(wrapper, '应用合并到草稿').trigger('click')
    await nextTick()

    expect(wrapper.get('[data-table-id="rail-base-sections"]').text()).toContain(formal.name)
    await button(wrapper, '撤销选中变更').trigger('click')
    await nextTick()
    const currentSectionNames = wrapper.get('[data-table-id="rail-base-sections"]').findAll('input[data-field="section-name"]')
    expect((currentSectionNames[1].element as HTMLInputElement).value).toBe('其他区间-人工修改')

    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    const changes = mocks.validate.mock.calls.at(-1)?.[0].changes
    expect(changes).toEqual([
      expect.objectContaining({
        entity_type: 'section',
        entity_id: unrelatedSection.id,
        values: expect.objectContaining({ name: '其他区间-人工修改' }),
      }),
    ])
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
