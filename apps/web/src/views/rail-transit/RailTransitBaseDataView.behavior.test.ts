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
  rollbackRailTransitImport: vi.fn(),
  saveRailTransitBaseDataChanges: mocks.save,
  validateRailTransitBaseDataChanges: mocks.validate,
}))

vi.mock('../../components/feedback/useConfirm', () => ({
  useConfirm: () => ({
    confirm: vi.fn(async () => true),
    confirmChoice: vi.fn(async () => 'secondary'),
  }),
}))

const Passthrough = defineComponent({ template: '<div><slot /></div>' })
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
  ElDescriptions: Passthrough,
  ElDescriptionsItem: Passthrough,
  ElDialog: Passthrough,
  ElDivider: Passthrough,
  ElInput: InputStub,
  ElInputNumber: InputNumberStub,
  ElOption: OptionStub,
  ElPagination: Passthrough,
  ElSelect: SelectStub,
  ElTabPane: Passthrough,
  ElTabs: Passthrough,
  ElTag: Passthrough,
  NcDataTable: Passthrough,
  TracksideApPlanningTab: PlanningStub,
}

const baseSummary = {
  site_id: 'demo', site_name: '宁波地铁12号线', line_name: '', project_type: '', network_type: 'default',
  remark: '', created_at: '', updated_at: '', station_count: 0, section_count: 0, ap_count: 0,
  train_count: 0, mr_count: 0, missing_location_ap_count: 0, invalid_mileage_count: 0,
  duplicate_ap_mac_count: 0, duplicate_static_ip_count: 0, unbound_mr_count: 0, issue_count: 0, message: '',
}
const writableSession = {
  site_id: 'demo', base_revision: 'a'.repeat(64), loaded_at: '', can_write: true, write_scope: 'real' as const,
  storage_mode: 'persistent' as const, write_denial_code: '', write_denial_reason: '',
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
