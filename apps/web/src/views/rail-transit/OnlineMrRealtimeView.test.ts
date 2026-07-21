// @vitest-environment happy-dom

import { createPinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const trainApi = vi.hoisted(() => ({
  getTrainCommunicationSummary: vi.fn(),
  listTrainCommunications: vi.fn(),
}))
const onlineMrApi = vi.hoisted(() => ({
  getCurrentOnlineMrSession: vi.fn(),
  getOnlineMrPreview: vi.fn(),
  getOnlineMrRawTail: vi.fn(),
  listOnlineMrCollectors: vi.fn(),
  listOnlineMrRawFiles: vi.fn(),
  listRecentOnlineMrSessions: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('../../api/trainCommunication', () => trainApi)
vi.mock('../../api/onlineMr', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../api/onlineMr')>(),
  ...onlineMrApi,
}))

import source from './OnlineMrRealtimeView.vue?raw'
import OnlineMrRealtimeView from './OnlineMrRealtimeView.vue'

describe('Online MR realtime collection view', () => {
  it('shows only the current collection session and moves history to analysis', () => {
    expect(source).toContain('车载 MR 实时收集')
    expect(source).toContain('listTrainCommunications')
    expect(source).toContain('<OnlineMrLocalControl')
    expect(source).toContain('<OnlineMrAgentControlPanel')
    expect(source).toContain('轻量实时预览')
    expect(source).toContain('当前采集状态')
    expect(source).toContain('原始日志动态查看')
    expect(source).toContain("rawSource = ref('terminal_monitor')")
    expect(source).toContain('data-testid="raw-source"')
    expect(source).not.toContain('table-id="online-mr-raw-growth"')
    expect(source).toContain('当前无实时采集任务，请选择列车启动采集')
    expect(source).not.toContain('listRecentOnlineMrSessions')
    expect(source).not.toContain('route.query.session_id')
    expect(source).not.toContain('addOnlineMrNote')
    expect(source).not.toContain('parseOnlineMrSession')
    expect(source).not.toContain('最近会话')
    expect(source).not.toMatch(/READ ONLY|只读|仍由 Qt|迁移/)
    expect(source).toContain('const collectorColumns: NcTableColumn<OnlineMrRuntimeStatusRow>[]')
    expect(source).toContain('table-id="online-mr-collectors"')
    expect(source).toContain(':preference-scope="store.current.session_id"')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})

const CollapseStub = defineComponent({
  name: 'ElCollapse',
  props: { modelValue: { type: Array, default: () => [] } },
  emits: ['update:modelValue'],
  setup(props, { slots }) {
    return () => h('div', { class: 'collapse-stub', 'data-expanded': JSON.stringify(props.modelValue) }, slots.default?.())
  },
})
const CollapseItemStub = defineComponent({
  name: 'ElCollapseItem',
  props: { title: String, name: String },
  setup(props, { slots }) {
    return () => h('section', { class: 'collapse-item-stub', 'data-name': props.name }, [h('span', props.title), slots.default?.()])
  },
})
const OptionStub = defineComponent({
  name: 'ElOption',
  props: { label: String, value: [String, Number] },
  setup(props) {
    return () => h('span', { class: 'option-stub', 'data-value': props.value }, props.label)
  },
})
const SlotStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h('div', attrs, slots.default?.())
  },
})
const DataTableStub = defineComponent({
  name: 'NcDataTable',
  inheritAttrs: false,
  props: { tableId: String },
  setup(props) {
    return () => h('div', { class: 'data-table-stub', 'data-table-id': props.tableId })
  },
})

describe('Online MR realtime mounted behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    trainApi.getTrainCommunicationSummary.mockResolvedValue({ site_id: 'site-a' })
    trainApi.listTrainCommunications.mockResolvedValue({ items: [] })
    onlineMrApi.getCurrentOnlineMrSession.mockResolvedValue({
      session_id: 'session-1', site_id: 'site-a', mr_name: 'MR-01', device_id: 1, device_name: '列车01',
      status: 'COLLECTING', phase: 'COLLECTING', created_at: null, started_at: '2026-07-21 10:00:00', stopped_at: null,
      duration_seconds: 30, duration_minutes: 0.5, controller_task_id: 'task-1', executor_kind: 'LOCAL', agent_id: null,
      has_raw_data: true, has_parsed_data: false, has_package: false, package_name: null, package_reference: null,
      force_stopped: false, finalization_complete: false, stop_reason: null, task_status: 'RUNNING', mapping_state: 'LINKED',
      error_code: null, error_message: null, session_path_reference: 'MR-01/sessions/session-1', connection_summary: {},
      collection_config: {}, enabled_collectors: ['terminal_monitor'], traffic_summary: {}, file_summary: {},
      database_summary: { status: 'missing', available: false, compatible: false, size_bytes: 0, modified_at: null, schema_version: null, parser_version: null, tables: [], row_counts: {}, available_capabilities: [], missing_capabilities: [], missing_tables: [], error_code: null, message: '尚未解析', recoverable: true, action: 'parse_session' },
      notes_count: 0, latest_metric_time: null, data_integrity: 'unknown',
    })
    onlineMrApi.listOnlineMrCollectors.mockResolvedValue([])
    onlineMrApi.getOnlineMrPreview.mockResolvedValue({ session_id: 'session-1', available: false, updated_at: null, message: '', display_context: {}, link: {}, fping: {}, iperf: {} })
    onlineMrApi.listOnlineMrRawFiles.mockResolvedValue([])
    onlineMrApi.getOnlineMrRawTail.mockResolvedValue({ success: true, name: 'mesh_link', exists: true, lines: ['tail'], message: '', size_bytes: 4, modified_at: null, summary: {} })
  })

  it('lays out status and collapsed log growth side by side, then enables raw polling from an array collapse model', async () => {
    const wrapper = mount(OnlineMrRealtimeView, {
      global: {
        plugins: [createPinia()],
        directives: { loading: () => undefined },
        stubs: {
          NcDataTable: DataTableStub,
          NcStatusTag: SlotStub,
          OnlineMrLocalControl: SlotStub,
          OnlineMrAgentControlPanel: SlotStub,
          ElAlert: SlotStub,
          ElButton: SlotStub,
          ElCollapse: CollapseStub,
          ElCollapseItem: CollapseItemStub,
          ElDescriptions: SlotStub,
          ElDescriptionsItem: SlotStub,
          ElEmpty: SlotStub,
          ElOption: OptionStub,
          ElSelect: SlotStub,
          ElTabPane: SlotStub,
          ElTabs: SlotStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('.current-session').exists()).toBe(true)
    expect(wrapper.find('.runtime-status').exists()).toBe(true)
    expect(wrapper.find('.runtime-log-viewer').exists()).toBe(true)
    const collapse = wrapper.findComponent(CollapseStub)
    expect(collapse.props('modelValue')).toEqual([])

    collapse.vm.$emit('update:modelValue', ['logs'])
    await nextTick()
    await flushPromises()

    expect(collapse.props('modelValue')).toEqual(['logs'])
    expect(onlineMrApi.getOnlineMrRawTail).toHaveBeenCalledWith('session-1', 'mesh_link')
    expect(onlineMrApi.getOnlineMrRawTail).toHaveBeenCalledWith('session-1', 'fping_raw')
    expect(onlineMrApi.getOnlineMrRawTail).toHaveBeenCalledWith('session-1', 'terminal_monitor')
    expect(onlineMrApi.listRecentOnlineMrSessions).not.toHaveBeenCalled()
    const rawValues = wrapper.findAll('.option-stub').map((item) => item.attributes('data-value'))
    expect(rawValues).toEqual(expect.arrayContaining(['terminal_monitor', 'wireless_status', 'channel_busy', 'switch_history', 'iperf_client', 'fping_samples', 'fping_summary', 'collector_output']))
    wrapper.unmount()
  })
})
