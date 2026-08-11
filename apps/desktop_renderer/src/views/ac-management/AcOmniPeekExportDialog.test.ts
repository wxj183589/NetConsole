// @vitest-environment happy-dom

import { defineComponent, h, useAttrs } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  startPreview: vi.fn(),
  getPreview: vi.fn(),
  getPreferences: vi.fn(),
  cancelTask: vi.fn(),
}))

vi.mock('../../api/acWebParity', () => ({
  acOmniPeekArtifactDownloadRequest: vi.fn(),
  cancelAcWebTask: mocks.cancelTask,
  getAcOmniPeekPreferences: mocks.getPreferences,
  getAcOmniPeekPreview: mocks.getPreview,
  getAcWebTask: vi.fn(),
  saveAcOmniPeekPreferences: vi.fn(),
  startAcOmniPeekExport: vi.fn(),
  startAcOmniPeekPreview: mocks.startPreview,
}))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: vi.fn(),
  getRuntimeConfig: () => ({ hostType: 'browser' }),
  getPlatformAdapter: () => ({}),
}))

import AcOmniPeekExportDialog from './AcOmniPeekExportDialog.vue'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, [slots.header?.(), slots.default?.(), slots.footer?.()])
  },
})

const checkboxStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(props, { slots, emit }) {
    return () => h('label', [
      h('input', { type: 'checkbox', checked: props.modelValue, onChange: (event: Event) => {
        const value = (event.target as HTMLInputElement).checked
        emit('update:modelValue', value)
        emit('change', value)
      } }),
      slots.default?.(),
    ])
  },
})

const dataTableStub = defineComponent({
  name: 'NcDataTable',
  props: { data: { type: Array, default: () => [] }, columns: { type: Array, default: () => [] } },
  setup(props) {
    return () => h('div', { class: 'preview-table', 'data-rows': props.data.length, 'data-columns': props.columns.length })
  },
})
const inputStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: String, default: '' } },
  setup(props) { return () => h('span', { class: 'el-input-stub' }, props.modelValue) },
})

const stubs = {
  ElAlert: passthrough,
  ElButton: passthrough,
  ElCard: passthrough,
  ElCheckbox: checkboxStub,
  ElColorPicker: passthrough,
  ElDialog: passthrough,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: inputStub,
  ElOption: passthrough,
  ElPagination: passthrough,
  ElSelect: passthrough,
  ElTag: passthrough,
  NcDataTable: dataTableStub,
}

describe('AcOmniPeekExportDialog', () => {
  beforeEach(() => {
    mocks.startPreview.mockReset().mockResolvedValue({ task_id: 'preview-1' })
    mocks.cancelTask.mockReset().mockResolvedValue({})
    mocks.getPreferences.mockReset().mockResolvedValue({ line_name: '杭州地铁4号线-信号-A网', colors: {} })
    mocks.getPreview.mockReset().mockResolvedValue({
      task_id: 'preview-1', task_status: 'COMPLETED', ready: true,
      config: {},
      source_counts: { 'AC FIT-AP资源': 974, 'AP扩展信息': 559, '设备管理': 2 },
      statistics: { total: 561, selected: 558, abnormal: 3, mac_conflict: 0, r2_failed: 0, missing_mac: 3 },
      items: [{ item_key: 'ap-1', selected: true, force_export: false, force_export_allowed: false, role: 'trackside_ap', type_label: '轨旁AP', name: 'ap3301_a', location: '池华街-金家渡', physical_mac: '4C:E9:E4:EE:F2:20', r1_mac: '4C:E9:E4:EE:F2:2F', r2_mac: '4C:E9:E4:EE:F2:3F', r1_source: 'H3C规则推导', r2_source: 'H3C规则推导', export_content: '物理MAC / R1 / R2', group: '测试组', color: '#00FF00', status: '正常', abnormal_reason: '', data_source: 'AC FIT-AP资源' }],
      matching_item_keys: ['ap-1'], selected_item_keys: ['ap-1'], total: 1, page: 1, page_size: 100,
      input_ap_count: 974, exportable_entry_count: 3, skipped_count: 3, error_count: 3, message: '',
    })
  })

  it('renders the complete configuration and structured preview instead of a summary-only dialog', async () => {
    const wrapper = mount(AcOmniPeekExportDialog, {
      props: { modelValue: true, acId: 'ac-1', apIds: [] },
      global: { stubs, directives: { loading: () => undefined } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('杭州地铁4号线-信号-A网名称表.nam')
    expect(wrapper.text()).toContain('AC FIT-AP资源：974 条')
    expect(wrapper.text()).toContain('AP扩展信息：559 条')
    expect(wrapper.text()).toContain('设备管理车载MR：2 条')
    expect(wrapper.text()).toContain('Radio 模式')
    expect(wrapper.text()).toContain('MAC 冲突')
    expect(wrapper.text()).toContain('全选当前筛选')
    expect(wrapper.get('.preview-table').attributes('data-rows')).toBe('1')
    expect(wrapper.get('.preview-table').attributes('data-columns')).toBe('16')
    expect(mocks.startPreview).toHaveBeenCalledWith('ac-1', [], expect.objectContaining({ include_device_mr: false }))
    wrapper.unmount()
  })
})
