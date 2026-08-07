// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'

import { ApiRequestError } from '../../api/client'
import { resetWebFeaturesForTest, setWebFeaturesForTest } from '../../features'
import { resetUserSelectedExportForTests } from '../../composables/useUserSelectedExport'
import { useTaskStore } from '../../stores/tasks'
import type {
  TracksideApBusinessPage,
  TracksideApBusinessRow,
  TracksideApTask,
  WpsTracksideTarget,
} from '../../types/tracksideApBusiness'
import type { TaskItem } from '../../types/task'

const api = vi.hoisted(() => ({
  listTracksideApBusiness: vi.fn(),
  listTracksideWpsTargets: vi.fn(),
  getTracksideApBusinessExportProposal: vi.fn(),
  startTracksideApBusinessExport: vi.fn(),
  startTracksideApUpdate: vi.fn(),
  syncTracksideWpsTargets: vi.fn(),
  testTracksideWpsTarget: vi.fn(),
  updateTracksideWpsTarget: vi.fn(),
  tracksideApBusinessDownloadRequest: vi.fn(),
}))
const taskApi = vi.hoisted(() => ({
  acknowledgeAllTaskAlerts: vi.fn(),
  acknowledgeTask: vi.fn(),
  cancelTask: vi.fn(),
  cleanupTasks: vi.fn(),
  dismissTask: vi.fn(),
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
  listTasks: vi.fn(),
}))
const platformMocks = vi.hoisted(() => ({
  downloadBackendResource: vi.fn(),
  openExternalUrl: vi.fn(),
  writeClipboardText: vi.fn(),
  hostType: 'browser' as 'browser' | 'electron',
}))
const terminalMocks = vi.hoisted(() => ({
  busy: { __v_isRef: true, value: false },
  fitApTerminalVisible: { __v_isRef: true, value: false },
  fitApTerminalType: { __v_isRef: true, value: 'securecrt' },
  fitApTerminalOptions: { __v_isRef: true, value: [] },
  preflightDeviceTerminalTargets: vi.fn(),
  launchDeviceTerminalTargets: vi.fn(),
  requestFitApTerminal: vi.fn(),
  launchSelectedFitApTerminal: vi.fn(),
  showPreflightSkipped: vi.fn(),
  showLaunchResult: vi.fn(),
}))

vi.mock('../../api/tracksideApBusiness', () => api)
vi.mock('../../api/tasks', () => taskApi)
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: platformMocks.downloadBackendResource,
  getPlatformAdapter: () => ({
    hostType: platformMocks.hostType,
    openExternalUrl: platformMocks.openExternalUrl,
    writeClipboardText: platformMocks.writeClipboardText,
  }),
}))
vi.mock('../../composables/useExternalTerminalLauncher', () => ({
  useExternalTerminalLauncher: () => terminalMocks,
}))

import TracksideApBusinessView from './TracksideApBusinessView.vue'
import TracksideApWpsConfigDialog from './TracksideApWpsConfigDialog.vue'

const extendedRowDefaults = {
  switch_vendor: 'H3C',
  switch_tx_power: '',
  switch_rx_low_alarm: '',
  switch_rx_high_alarm: '',
  switch_tx_low_alarm: '',
  switch_tx_high_alarm: '',
  switch_interface_updated_at: '',
  switch_optical_updated_at: '',
  switch_interface_data_status: 'current' as const,
  switch_optical_data_status: 'current' as const,
  ap_tx_power: '',
  ap_match_source: '',
  ap_match_confidence: 0,
  lldp_match_status: '',
  local_rx_power_dbm: null,
  local_tx_power_dbm: null,
  remote_rx_power_dbm: null,
  remote_tx_power_dbm: null,
  forward_loss_db: null,
  reverse_loss_db: null,
  calculation_status: '',
  calculation_reason: '',
  planned_management_vlan: null,
  vlan_group_id: '',
  vlan_group_code: '',
  vlan_group_name: '',
  pvid_plan_status: 'unresolved' as const,
  local_sample_time: '',
  remote_sample_time: '',
  sample_time_delta_seconds: null,
}

const rows: TracksideApBusinessRow[] = [
  {
    ...extendedRowDefaults,
    site: '站点A',
    device_name: 'SW-A',
    interface_name: 'XGE1/0/1',
    link_status: 'UP',
    port_type: 'access',
    description: '',
    pvid: 921,
    vlan: '921',
    switch_rx_power: '-10.1',
    switch_optical_status: 'normal',
    ap_uuid: 'ap-1',
    ap_mac: 'bc5a-3457-8cc0',
    ap_name: 'AP-A',
    ap_rx_power: '-11.2',
    ap_device_optical_status: 'normal',
    ap_business_optical_status: 'normal',
    ap_business_threshold_dbm: -13.90,
    ap_business_reason: 'AP接收光功率 -11.20 dBm 达到业务门限 -13.90 dBm',
    ap_optical_status: 'normal',
    updated_at: '2026-07-21T10:00:00+08:00',
    optical_severity: 'normal',
    switch_device_uuid: 'switch-device-1',
    switch_terminal_available: true,
    switch_terminal_unavailable_reason: '',
    ap_terminal_ac_id: 'ac-1',
    ap_terminal_ap_id: 'ap-1',
    ap_terminal_available: true,
    ap_terminal_unavailable_reason: '',
  },
  {
    ...extendedRowDefaults,
    site: '站点B',
    device_name: 'SW-B',
    interface_name: 'XGE1/0/2',
    link_status: 'UP',
    port_type: 'access',
    description: '',
    pvid: 922,
    vlan: '922',
    switch_rx_power: '-12.1',
    switch_optical_status: 'warning',
    ap_uuid: '',
    ap_mac: '305f-277a-1880',
    ap_name: '',
    ap_rx_power: '',
    ap_device_optical_status: 'not_collected',
    ap_business_optical_status: 'unknown',
    ap_business_threshold_dbm: -13.90,
    ap_business_reason: 'AP接收光功率无有效值，业务状态未知',
    ap_optical_status: 'unknown',
    updated_at: '',
    optical_severity: 'warning',
    switch_device_uuid: 'switch-device-2',
    switch_terminal_available: false,
    switch_terminal_unavailable_reason: '缺少管理地址',
    ap_terminal_ac_id: '',
    ap_terminal_ap_id: '',
    ap_terminal_available: false,
    ap_terminal_unavailable_reason: '未关联到 FIT-AP 资源',
  },
]

function stationOptionsFor(items: TracksideApBusinessRow[]): string[] {
  return [...new Set(items.map((item) => item.site.trim()).filter(Boolean))]
}

function page(items = rows, pageNo = 1, stationOptions = stationOptionsFor(items)): TracksideApBusinessPage {
  return {
    items,
    total: items.length,
    page: pageNo,
    page_size: 50,
    site_id: 'demo',
    station_options: stationOptions,
    device_count: 2,
    candidate_interface_count: 2,
    optical_abnormal_count: 1,
    fit_ap_resource_count: 2,
    query_ms: 1,
    build_ms: 1,
    empty_reason: '',
    identity_shadow: {},
  }
}

function snapshotPage(revision = 'a'.repeat(64), pageNo = 1): TracksideApBusinessPage {
  return {
    ...page(rows.map((row, index) => ({ ...row, row_id: `row-${index + 1}` })), pageNo),
    snapshot_id: `snapshot-${revision[0]}`,
    business_revision: revision,
    source_revisions: { base_data_revision: revision[0] },
    identity_revision: 7,
    created_at: '2026-08-06T01:02:03+08:00',
    content_sha256: 'c'.repeat(64),
    row_count: rows.length,
    abnormal_count: 1,
    unresolved_count: 0,
    ambiguous_count: 0,
    snapshot_retry_count: 0,
    identity_distinct_count: rows.length,
  }
}

function wpsTargets(configured = false): WpsTracksideTarget[] {
  return [
    {
      target_id: 'target-standard',
      site_id: 'demo',
      business_key: 'rail_transit.trackside_ap_business',
      target_code: 'wps_standard_spreadsheet',
      target_type: 'WPS_STANDARD_SPREADSHEET',
      target_name: '普通在线表格',
      document_open_url: 'https://www.kdocs.cn/l/standard',
      webhook_url: 'https://www.kdocs.cn/api/v3/ide/file/standard/script/test/sync_task',
      expected_document_id: 'standard',
      enabled: true,
      protocol_version: 2,
      timeout_seconds: 30,
      token_configured: configured,
      token_suffix: configured ? '1111' : '',
      last_test_at: '',
      last_test_status: '',
      last_test_message: '',
      last_sync_at: '',
      last_sync_status: '',
      last_sync_revision: '',
    },
    {
      target_id: 'target-smart',
      site_id: 'demo',
      business_key: 'rail_transit.trackside_ap_business',
      target_code: 'wps_smart_sheet',
      target_type: 'WPS_SMART_SHEET',
      target_name: '智能表格',
      document_open_url: 'https://www.kdocs.cn/l/smart',
      webhook_url: 'https://www.kdocs.cn/api/v3/ide/file/smart/script/test/sync_task',
      expected_document_id: 'smart',
      enabled: true,
      protocol_version: 2,
      timeout_seconds: 45,
      token_configured: configured,
      token_suffix: configured ? '2222' : '',
      last_test_at: '',
      last_test_status: '',
      last_test_message: '',
      last_sync_at: '',
      last_sync_status: '',
      last_sync_revision: '',
    },
  ]
}

function task(
  taskId: string,
  status = 'RUNNING',
  action = 'trackside_ap_optical_update',
  resultSummary: Record<string, unknown> = {},
): TracksideApTask {
  return {
    task_id: taskId,
    status,
    action,
    artifact_id: '',
    artifact_name: '',
    available: false,
    sha256: '',
    size_bytes: 0,
    message: '',
    error_message: '',
    result_summary: resultSummary,
  }
}

function globalTask(
  id: string,
  status: TaskItem['status'],
  type = 'trackside_ap_optical_update',
): TaskItem {
  return {
    id,
    type,
    name: type,
    status,
    progress: status === 'COMPLETED' ? 100 : 50,
    phase: '',
    stage: '',
    message: '',
    site_name: 'demo',
    owner: 'web_rail_transit',
    executor: 'LOCAL',
    source: 'local',
    device_id: '',
    device_name: '',
    agent: '',
    mr_name: '',
    session_id: '',
    mapping_state: '',
    created_time: '',
    started_time: '',
    finished_time: '',
    updated_time: '',
    duration_seconds: 0,
    error_code: '',
    error_summary: '',
    has_warning: false,
    snapshot_id: null,
    records_count: null,
    parser_version: '',
  }
}

const NcDataTableStub = defineComponent({
  name: 'NcDataTable',
  props: {
    data: { type: Array, default: () => [] },
    columns: { type: Array, default: () => [] },
    emptyText: String,
    height: String,
    tableId: String,
    rowKey: [String, Function],
    contextMenuItems: { type: Array, default: () => [] },
  },
  emits: ['selection-change'],
  template: `
    <div class="nc-data-table nc-data-table__scroll" :data-table-id="tableId" :data-height="height">
      <div v-for="(row, index) in data" :key="index" class="table-row">
        <slot name="cell-switch_rx_power" :row="row" />
        <slot name="cell-switch_tx_power" :row="row" />
        <slot name="cell-switch_optical_status" :row="row" />
        <slot name="cell-ap_rx_power" :row="row" />
        <slot name="cell-ap_tx_power" :row="row" />
        <slot name="cell-ap_device_optical_status" :row="row" />
        <slot name="cell-ap_optical_status" :row="row" />
        <slot name="cell-optical_severity" :row="row" />
        <slot name="cell-actions" :row="row" />
      </div>
    </div>
  `,
})

const ElementStubs = {
  ElDialog: defineComponent({
    props: { modelValue: Boolean, title: String },
    emits: ['update:modelValue'],
    template: '<div v-if="modelValue" class="el-dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></div>',
  }),
  ElForm: defineComponent({ template: '<form><slot /></form>' }),
  ElFormItem: defineComponent({ props: { label: String }, template: '<label>{{ label }}<slot /></label>' }),
  ElAlert: defineComponent({
    props: { title: String, type: String },
    template: '<div class="el-alert" :data-type="type"><span>{{ title }}</span><slot /></div>',
  }),
  ElButton: defineComponent({
    props: { disabled: Boolean, loading: Boolean },
    emits: ['click'],
    template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
  }),
  ElSelect: defineComponent({
    props: { modelValue: String, placeholder: String, clearable: Boolean, filterable: Boolean },
    emits: ['update:modelValue', 'change'],
    template: `
      <select :value="modelValue || ''" @change="$emit('update:modelValue', $event.target.value); $emit('change', $event.target.value)">
        <option value="">{{ placeholder || '全部站点' }}</option>
        <slot />
      </select>
    `,
  }),
  ElCheckbox: defineComponent({
    props: { modelValue: Boolean },
    emits: ['update:modelValue'],
    template: '<label><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" /><slot /></label>',
  }),
  ElSwitch: defineComponent({
    props: { modelValue: Boolean },
    emits: ['update:modelValue'],
    template: '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
  }),
  ElInputNumber: defineComponent({
    props: { modelValue: Number },
    emits: ['update:modelValue'],
    template: '<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
  }),
  ElOption: defineComponent({
    props: { label: String, value: String, title: String },
    template: '<option :value="value" :title="title">{{ label }}</option>',
  }),
  ElInput: defineComponent({
    props: { modelValue: String, placeholder: String },
    emits: ['update:modelValue'],
    template: '<input :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  }),
  ElPagination: defineComponent({
    props: { currentPage: Number, pageSize: Number, pageSizes: { type: Array, default: () => [] } },
    emits: ['current-change', 'size-change'],
    template: `
      <div class="el-pagination-stub" :data-current-page="currentPage" :data-page-size="pageSize" :data-page-sizes="JSON.stringify(pageSizes)">
        <button class="pagination-next" @click="$emit('current-change', Number(currentPage || 1) + 1)">下一页</button>
        <select class="pagination-size" @change="$emit('size-change', Number($event.target.value))">
          <option v-for="size in pageSizes" :key="size" :value="size">{{ size }}</option>
        </select>
      </div>
    `,
  }),
  ElTag: defineComponent({ template: '<span class="el-tag"><slot /></span>' }),
  ElTooltip: defineComponent({ props: { content: String }, template: '<span class="el-tooltip" :data-content="content"><slot /></span>' }),
}

describe('TracksideApBusinessView mounted behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetUserSelectedExportForTests()
    resetWebFeaturesForTest()
    for (const method of Object.values(api)) method.mockReset()
    setWebFeaturesForTest({
      'web.rail_trackside_ap_business_update': { visible: true, enabled: true },
      'web.rail_trackside_ap_business_export': { visible: true, enabled: true },
      'web.rail_task_control': { visible: true, enabled: true },
      'web.device_management_desktop': { visible: true, enabled: true },
      'web.ac_fit_ap_external_terminal': { visible: true, enabled: true },
      'desktop.native_bridge': { visible: true, enabled: true },
      'rail.zte_trackside_switch_adapter': { visible: true, enabled: true },
      'web.rail_trackside_ap_business_wps_sync': { visible: true, enabled: true },
    })
    api.listTracksideApBusiness.mockResolvedValue(page())
    api.listTracksideWpsTargets.mockResolvedValue([])
    api.updateTracksideWpsTarget.mockResolvedValue({})
    api.testTracksideWpsTarget.mockResolvedValue({ target_code: 'wps_standard_spreadsheet', result: {} })
    api.syncTracksideWpsTargets.mockResolvedValue(task('wps-task', 'RUNNING', 'trackside_ap_wps_sync'))
    api.getTracksideApBusinessExportProposal.mockResolvedValue({
      site_id: 'demo',
      site_display_name: '宁波地铁12号线',
      generated_at: '2026-07-21T23:45:01+08:00',
      suggested_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    for (const method of Object.values(taskApi)) method.mockReset()
    taskApi.listTasks.mockResolvedValue([])
    api.startTracksideApBusinessExport.mockResolvedValue(task('export-task', 'RUNNING', 'trackside_ap_business_export'))
    api.startTracksideApUpdate.mockResolvedValue(task('update-task', 'COMPLETED', 'trackside_ap_optical_update', { status: 'DONE', target_count: 1, success_count: 1 }))
    api.tracksideApBusinessDownloadRequest.mockImplementation((artifactId: string, artifactName: string) => ({
      apiPath: `/api/rail-transit/trackside-ap-business/artifacts/${encodeURIComponent(artifactId)}/download`,
      suggestedName: artifactName,
    }))
    platformMocks.downloadBackendResource.mockResolvedValue({ status: 'saved', capabilityId: 'cap-1' })
    platformMocks.openExternalUrl.mockReset()
    platformMocks.openExternalUrl.mockResolvedValue({ success: true })
    platformMocks.writeClipboardText.mockReset()
    platformMocks.writeClipboardText.mockResolvedValue({ success: true })
    platformMocks.hostType = 'browser'
    terminalMocks.preflightDeviceTerminalTargets.mockReset()
    terminalMocks.launchDeviceTerminalTargets.mockReset()
    terminalMocks.requestFitApTerminal.mockReset()
    terminalMocks.launchSelectedFitApTerminal.mockReset()
    terminalMocks.showPreflightSkipped.mockReset()
    terminalMocks.showLaunchResult.mockReset()
    terminalMocks.preflightDeviceTerminalTargets.mockResolvedValue({
      terminalType: 'securecrt',
      launchableDevices: ['device-1'],
      skippedDevices: [],
    })
    terminalMocks.launchDeviceTerminalTargets.mockResolvedValue({ success: 1, failed: 0, failures: [] })
    terminalMocks.requestFitApTerminal.mockResolvedValue(null)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
    localStorage.clear()
    delete (window as Window & { netconsoleDesktop?: unknown }).netconsoleDesktop
  })

  afterEach(() => {
    resetWebFeaturesForTest()
    vi.useRealTimers()
  })

  it('renders the business table without the removed task card', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    expect(wrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    expect(wrapper.text()).not.toContain('保存导出表格')
    expect(wrapper.text()).not.toContain('结果项')
    expect(buttons(wrapper, '打开任务中心')).toHaveLength(0)
    expect(wrapper.find('.business-table-host').exists()).toBe(true)
    expect(wrapper.find('[data-table-id="trackside-ap-business"]').attributes('data-height')).toBe('100%')
    const mainTable = wrapper.getComponent(NcDataTableStub)
    const mainRowKey = mainTable.props('rowKey') as (row: TracksideApBusinessRow) => string
    expect(mainRowKey(rows[0])).toContain(`${rows[0].device_name}|${rows[0].interface_name}`)
    const tableColumns = wrapper.getComponent(NcDataTableStub).props('columns') as Array<Record<string, unknown>>
    expect(tableColumns.find((column) => column.key === 'description')).toMatchObject({
      width: 90,
      maxWidth: 120,
      align: 'center',
      headerAlign: 'center',
      stretch: 'none',
      showOverflowTooltip: true,
    })
    expect(tableColumns.find((column) => column.key === 'port_type')).toMatchObject({ width: 100 })
    expect(tableColumns.find((column) => column.key === 'ap_mac')).toMatchObject({ stretch: 'priority' })
    expect(wrapper.find('[data-table-id="trackside-ap-business-task-result"]').exists()).toBe(false)
    expect(wrapper.find('input[placeholder="站点"]').exists()).toBe(false)
    expect(wrapper.find('select').exists()).toBe(true)
    wrapper.unmount()
  })

  it('opens WPS configuration and saves independent URLs, webhooks and tokens', async () => {
    const initialTargets = wpsTargets(false)
    api.listTracksideWpsTargets.mockResolvedValue(initialTargets)
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('在线文档连接、webhook 或脚本令牌尚未完整配置')
    await button(wrapper, '配置云文档').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('令牌未配置')

    const dialog = wrapper.getComponent(TracksideApWpsConfigDialog)
    const vm = dialog.vm as unknown as {
      drafts: Array<{ target_code: string; token: string; document_open_url: string; webhook_url: string }>
      saveTargetConfiguration: (code: 'wps_standard_spreadsheet' | 'wps_smart_sheet') => Promise<boolean>
    }
    vm.drafts[0].token = 'standard-test-token'
    vm.drafts[0].document_open_url = 'https://www.kdocs.cn/l/standard-updated'
    vm.drafts[0].webhook_url = 'https://www.kdocs.cn/api/v3/ide/file/standard-updated/script/test/sync_task'
    vm.drafts[1].token = 'smart-test-token'
    vm.drafts[1].document_open_url = 'https://www.kdocs.cn/l/smart-updated'
    vm.drafts[1].webhook_url = 'https://www.kdocs.cn/api/v3/ide/file/smart-updated/script/test/sync_task'
    api.listTracksideWpsTargets.mockResolvedValue(wpsTargets(true))

    await vm.saveTargetConfiguration('wps_standard_spreadsheet')
    await vm.saveTargetConfiguration('wps_smart_sheet')
    expect(api.updateTracksideWpsTarget).toHaveBeenNthCalledWith(1, 'wps_standard_spreadsheet', expect.objectContaining({
      token: 'standard-test-token',
      document_open_url: 'https://www.kdocs.cn/l/standard-updated',
      webhook_url: 'https://www.kdocs.cn/api/v3/ide/file/standard-updated/script/test/sync_task',
    }))
    expect(api.updateTracksideWpsTarget).toHaveBeenNthCalledWith(2, 'wps_smart_sheet', expect.objectContaining({
      token: 'smart-test-token',
      document_open_url: 'https://www.kdocs.cn/l/smart-updated',
      webhook_url: 'https://www.kdocs.cn/api/v3/ide/file/smart-updated/script/test/sync_task',
    }))
    expect(vm.drafts[0].token).toBe('')
    expect(vm.drafts[1].token).toBe('')
    wrapper.unmount()
  })

  it('opens each WPS document through the platform adapter without window.open in Electron', async () => {
    platformMocks.hostType = 'electron'
    api.listTracksideWpsTargets.mockResolvedValue(wpsTargets(true))
    const nativeOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = await mountView()
    await button(wrapper, '配置云文档').trigger('click')
    await flushPromises()

    const dialog = wrapper.getComponent(TracksideApWpsConfigDialog)
    const vm = dialog.vm as unknown as {
      openDocument: (target: WpsTracksideTarget) => Promise<void>
    }
    const targets = wpsTargets(true)
    await vm.openDocument(targets[0])
    await vm.openDocument(targets[1])

    expect(platformMocks.openExternalUrl).toHaveBeenNthCalledWith(1, targets[0].document_open_url)
    expect(platformMocks.openExternalUrl).toHaveBeenNthCalledWith(2, targets[1].document_open_url)
    expect(nativeOpen).not.toHaveBeenCalled()
    nativeOpen.mockRestore()
    wrapper.unmount()
  })

  it('copies WPS deployment scripts through the controlled platform clipboard', async () => {
    platformMocks.hostType = 'electron'
    api.listTracksideWpsTargets.mockResolvedValue(wpsTargets(true))
    const wrapper = await mountView()
    await button(wrapper, '配置云文档').trigger('click')
    await flushPromises()

    const dialog = wrapper.getComponent(TracksideApWpsConfigDialog)
    const vm = dialog.vm as unknown as {
      copyAirScript: (
        code: 'wps_standard_spreadsheet' | 'wps_smart_sheet',
        kind: 'probe' | 'sync',
      ) => Promise<void>
    }
    await vm.copyAirScript('wps_standard_spreadsheet', 'probe')
    await vm.copyAirScript('wps_smart_sheet', 'sync')

    expect(platformMocks.writeClipboardText).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('trackside-ap-standard-2.3.0'),
    )
    expect(platformMocks.writeClipboardText).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('WPS_SMART_SHEET_RUNTIME_UNVERIFIED'),
    )
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens the page-level ordinary and smart WPS targets independently', async () => {
    platformMocks.hostType = 'electron'
    api.listTracksideWpsTargets.mockResolvedValue(wpsTargets(true))
    const wrapper = await mountView()

    await button(wrapper, '打开普通表格').trigger('click')
    await button(wrapper, '打开智能表格').trigger('click')
    await flushPromises()

    expect(platformMocks.openExternalUrl).toHaveBeenNthCalledWith(1, wpsTargets(true)[0].document_open_url)
    expect(platformMocks.openExternalUrl).toHaveBeenNthCalledWith(2, wpsTargets(true)[1].document_open_url)
    wrapper.unmount()
  })

  it('shows a failure when the desktop external link capability rejects the WPS document', async () => {
    platformMocks.hostType = 'electron'
    platformMocks.openExternalUrl.mockResolvedValue({ success: false, error: '系统浏览器不可用' })
    api.listTracksideWpsTargets.mockResolvedValue(wpsTargets(true))
    const wrapper = await mountView()
    await button(wrapper, '配置云文档').trigger('click')
    await flushPromises()

    const dialog = wrapper.getComponent(TracksideApWpsConfigDialog)
    const vm = dialog.vm as unknown as { openDocument: (target: WpsTracksideTarget) => Promise<void> }
    await vm.openDocument(wpsTargets(true)[0])

    expect(wrapper.text()).toContain('系统浏览器不可用')
    wrapper.unmount()
  })

  it('keeps filters, successful rows and scroll offsets across KeepAlive navigation', async () => {
    const host = await mountCachedView()
    expect(api.listTracksideApBusiness).toHaveBeenCalledTimes(1)
    let view = host.getComponent(TracksideApBusinessView)
    const vm = view.vm as unknown as {
      filters: { query: string; station: string; optical_anomaly_only: boolean; page: number; page_size: number }
      excludedVisible: boolean
      unmatchedVisible: boolean
      currentTaskId: string
    }
    vm.filters.query = '0011-2233-4455'
    vm.filters.station = '站点A'
    vm.filters.optical_anomaly_only = true
    vm.filters.page = 2
    vm.filters.page_size = 100
    vm.excludedVisible = true
    vm.unmatchedVisible = true
    vm.currentTaskId = 'task-observed'
    const scroll = view.get('.nc-data-table__scroll').element as HTMLElement
    scroll.scrollTop = 240
    scroll.scrollLeft = 360

    ;(host.vm as unknown as { active: boolean }).active = false
    await host.vm.$nextTick()
    scroll.scrollTop = 0
    scroll.scrollLeft = 0
    ;(host.vm as unknown as { active: boolean }).active = true
    await flushPromises()
    view = host.getComponent(TracksideApBusinessView)
    const restored = view.vm as unknown as typeof vm

    expect(restored.filters).toMatchObject({
      query: '0011-2233-4455',
      station: '站点A',
      optical_anomaly_only: true,
      page: 2,
      page_size: 100,
    })
    expect(restored.excludedVisible).toBe(true)
    expect(restored.unmatchedVisible).toBe(true)
    expect(restored.currentTaskId).toBe('task-observed')
    expect(view.getComponent(NcDataTableStub).props('data')).toEqual(rows)
    expect(scroll.scrollTop).toBe(240)
    expect(scroll.scrollLeft).toBe(360)
    expect(api.listTracksideApBusiness).toHaveBeenCalledTimes(1)
    host.unmount()
  })

  it('keeps old rows visible while a stale background refresh fails', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-05T10:00:00+08:00'))
    const host = await mountCachedView()
    const view = host.getComponent(TracksideApBusinessView)
    api.listTracksideApBusiness.mockClear()
    api.listTracksideApBusiness.mockRejectedValueOnce(new Error('刷新失败'))

    ;(host.vm as unknown as { active: boolean }).active = false
    await host.vm.$nextTick()
    vi.advanceTimersByTime(5 * 60 * 1000 + 1)
    ;(host.vm as unknown as { active: boolean }).active = true
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenCalledTimes(1)
    expect(view.getComponent(NcDataTableStub).props('data')).toEqual(rows)
    expect(view.text()).toContain('部分数据不可用，已保留最后成功数据。')
    host.unmount()
  })

  it('refreshes once after a related task completes while the page is inactive', async () => {
    const host = await mountCachedView()
    api.listTracksideApBusiness.mockClear()
    api.listTracksideApBusiness.mockResolvedValue(page(rows))

    ;(host.vm as unknown as { active: boolean }).active = false
    await host.vm.$nextTick()
    taskApi.listTasks.mockResolvedValueOnce([
      globalTask('lldp-refresh', 'COMPLETED', 'device_detail_collect'),
    ])
    await useTaskStore().refresh()
    await flushPromises()
    expect(api.listTracksideApBusiness).not.toHaveBeenCalled()

    ;(host.vm as unknown as { active: boolean }).active = true
    await flushPromises()
    expect(api.listTracksideApBusiness).toHaveBeenCalledTimes(1)

    ;(host.vm as unknown as { active: boolean }).active = false
    await host.vm.$nextTick()
    ;(host.vm as unknown as { active: boolean }).active = true
    await flushPromises()
    expect(api.listTracksideApBusiness).toHaveBeenCalledTimes(1)
    host.unmount()
  })

  it('discards the current site page and ignores a request that finishes after site switch', async () => {
    let resolveRows!: (value: TracksideApBusinessPage) => void
    api.listTracksideApBusiness.mockReset()
    api.listTracksideApBusiness.mockReturnValueOnce(new Promise((resolve) => { resolveRows = resolve }))
    const wrapper = mount(TracksideApBusinessView, {
      global: {
        directives: { loading: () => undefined },
        stubs: { ...ElementStubs, NcDataTable: NcDataTableStub },
      },
    })
    await wrapper.vm.$nextTick()
    const vm = wrapper.vm as unknown as { filters: { station: string; page: number } }
    vm.filters.station = '旧站点'
    vm.filters.page = 3

    window.dispatchEvent(new CustomEvent('netconsole:before-site-switch', { detail: { targetSiteId: 'new-site' } }))
    resolveRows(page())
    await flushPromises()

    expect(vm.filters.station).toBe('')
    expect(vm.filters.page).toBe(1)
    expect(wrapper.getComponent(NcDataTableStub).props('data')).toEqual([])
    wrapper.unmount()
  })

  it('shows the shared terminal label only on target columns and uses exact switch or FIT-AP targets', async () => {
    platformMocks.hostType = 'electron'
    terminalMocks.preflightDeviceTerminalTargets
      .mockResolvedValueOnce({ terminalType: 'securecrt', launchableDevices: ['switch-device-1'], skippedDevices: [] })
    const wrapper = await mountView()
    const items = wrapper.getComponent(NcDataTableStub).props('contextMenuItems') as Array<{
      key: string
      label: string
      visible: (context: { row: TracksideApBusinessRow; columnKey: string }) => boolean
      disabled: (context: { row: TracksideApBusinessRow; columnKey: string }) => boolean
      disabledReason: (context: { row: TracksideApBusinessRow; columnKey: string }) => string
      action: (context: { row: TracksideApBusinessRow; columnKey: string; cellValue?: unknown }) => Promise<void>
    }>
    const switchAction = items.find((item) => item.key === 'switch-external-terminal')!
    const apAction = items.find((item) => item.key === 'ap-external-terminal')!
    const copyCell = items.find((item) => item.key === 'copy-cell')!
    const copyRow = items.find((item) => item.key === 'copy-row')!
    const context = (row: TracksideApBusinessRow, columnKey: string) => ({ row, columnKey })

    expect(switchAction.visible(context(rows[0], 'device_name'))).toBe(true)
    expect(switchAction.visible(context(rows[0], 'ap_mac'))).toBe(false)
    expect(apAction.visible(context(rows[0], 'ap_mac'))).toBe(true)
    expect(apAction.visible(context(rows[0], 'ap_name'))).toBe(true)
    expect(apAction.visible(context(rows[0], 'interface_name'))).toBe(false)
    expect(switchAction.label).toBe('打开外部终端')
    expect(apAction.label).toBe('打开外部终端')
    expect(switchAction.disabled(context(rows[1], 'device_name'))).toBe(true)
    expect(switchAction.disabledReason(context(rows[1], 'device_name'))).toBe('缺少管理地址')
    expect(apAction.disabledReason(context(rows[1], 'ap_mac'))).toBe('未关联到 FIT-AP 资源')

    await switchAction.action(context(rows[0], 'device_name'))
    await apAction.action(context(rows[0], 'ap_mac'))
    await apAction.action(context(rows[0], 'ap_name'))
    await copyCell.action({ ...context(rows[0], 'ap_mac'), cellValue: rows[0].ap_mac })
    await copyRow.action(context(rows[0], 'ap_name'))

    expect(terminalMocks.preflightDeviceTerminalTargets).toHaveBeenCalledWith(['switch-device-1'])
    expect(terminalMocks.preflightDeviceTerminalTargets).not.toHaveBeenCalledWith(['ap-1'])
    expect(terminalMocks.preflightDeviceTerminalTargets).not.toHaveBeenCalledWith(['bc5a-3457-8cc0'])
    expect(terminalMocks.launchDeviceTerminalTargets).toHaveBeenCalledTimes(1)
    expect(terminalMocks.requestFitApTerminal).toHaveBeenNthCalledWith(1, { acId: 'ac-1', apId: 'ap-1' })
    expect(terminalMocks.requestFitApTerminal).toHaveBeenNthCalledWith(2, { acId: 'ac-1', apId: 'ap-1' })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('bc5a-3457-8cc0')
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('SW-A\tXGE1/0/1'))
    wrapper.unmount()
  })

  it('shows unavailable source status without hiding successful business rows', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce({
      ...page(),
      partial_data: true,
      source_statuses: {
        switch_devices: 'loaded',
        interfaces: 'loaded',
        switch_optical: 'loaded',
        lldp: 'loaded',
        fit_ap_resources: 'failed',
        fit_ap_optical: 'loaded',
      },
      unavailable_sources: [{
        source: 'fit_ap_resources',
        label: 'FIT-AP 资源',
        code: 'FIT_AP_RESOURCES_UNAVAILABLE',
        message: 'FIT-AP 资源暂时不可用。',
      }],
    })
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('部分数据不可用，已展示成功构建的交换机/AP 端口行。')
    expect(wrapper.text()).toContain('FIT-AP 资源：FIT_AP_RESOURCES_UNAVAILABLE')
    expect(wrapper.getComponent(NcDataTableStub).props('data')).toHaveLength(2)
    const cards = wrapper.findAll('.summary-grid article').map((item) => item.text())
    expect(cards).toContain('AC AP 资源加载失败')
    expect(cards).toContain('基础资料待补充加载失败')
    expect(cards).toContain('候选 AP 端口2')
    wrapper.unmount()
  })

  it('retains the last successful table when a refresh request fails', async () => {
    const wrapper = await mountView()
    api.listTracksideApBusiness.mockRejectedValueOnce(new Error('connection reset'))

    await button(wrapper, '刷新').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('部分数据不可用，已保留最后成功数据。')
    expect(wrapper.getComponent(NcDataTableStub).props('data')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('Backend 连接中断，请重试。')
    wrapper.unmount()
  })

  it('does not render unloaded statistics as zero', async () => {
    let resolvePage: ((value: TracksideApBusinessPage) => void) | undefined
    api.listTracksideApBusiness.mockImplementationOnce(() => new Promise((resolve) => {
      resolvePage = resolve
    }))
    const wrapper = mount(TracksideApBusinessView, {
      global: {
        directives: { loading: () => undefined },
        stubs: { ...ElementStubs, NcDataTable: NcDataTableStub },
      },
    })

    expect(wrapper.findAll('.summary-grid strong').map((item) => item.text())).toEqual([
      '—',
      '—',
      '—',
      '—',
      '—',
    ])
    resolvePage?.(page())
    await flushPromises()
    wrapper.unmount()
  })

  it('localizes empty reasons and exposes unmatched online counts', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce({
      ...page([], 1, []),
      device_count: 15,
      candidate_interface_count: 756,
      fit_ap_resource_count: 188,
      fit_ap_matched_count: 0,
      fit_ap_unmatched_online_count: 188,
      empty_reason: 'trackside.empty.no_fit_ap_resource',
      unmatched_online_items: [{
        source: 'fit_ap_online',
        item_id: 'ap-unmatched',
        ap_name: 'AP-UNMATCHED',
        mac: '0011-2233-4455',
        ac_status: 'R',
        runtime_station_text: '站点A',
        reason: '在线 AP 尚未匹配轨旁 AP 基础资料；基础资料仅作补充，不影响业务生成。',
        suggested_action: '补充基础资料',
      }],
    })
    const wrapper = await mountView()

    expect(wrapper.getComponent(NcDataTableStub).props('emptyText')).toBe(
      '已发现候选 AP 端口，部分端口尚未关联 AP 运行态资料。',
    )
    expect(wrapper.text()).not.toContain('trackside.empty.no_fit_ap_resource')
    expect(wrapper.text()).toContain('AC AP 资源188')
    expect(wrapper.text()).toContain('基础资料待补充 188')
    expect(wrapper.text()).toContain('设备管理与 AC 生成业务行；基础资料仅补充站点和工程属性')
    wrapper.unmount()
  })

  it('separates switch and planning failures and exposes structured diagnostics', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce({
      ...page(),
      fit_ap_unmatched_online_count: 5,
      fit_ap_switch_not_found_count: 2,
      fit_ap_switch_identity_ambiguous_count: 1,
      fit_ap_plan_not_found_count: 1,
      fit_ap_plan_station_invalid_count: 1,
      unmatched_online_items: [{
        source: 'fit_ap_online',
        item_id: 'ap-unmatched',
        ap_name: 'AP-UNMATCHED',
        mac: '0011-2233-4455',
        ac_status: 'R',
        runtime_station_text: '',
        association_status: 'switch_not_found',
        reason_code: 'SWITCH_NOT_FOUND',
        reason: '上联交换机未匹配设备管理记录',
        suggested_action: '核对交换机身份',
        lldp_exists: true,
        lldp_system_name: 'HZDT-SC',
        switch_candidate_count: 0,
        failure_stage: 'switch_identity',
      }],
    })
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('交换机未匹配 2')
    expect(wrapper.text()).toContain('交换机身份冲突 1')
    expect(wrapper.text()).toContain('AP 规划缺失 1')
    expect(wrapper.text()).toContain('规划站点无效 1')
    expect(wrapper.text()).toContain('状态：最新')
    await button(wrapper, '交换机未匹配').trigger('click')
    await flushPromises()
    const tables = wrapper.findAllComponents(NcDataTableStub)
    const diagnosticColumns = tables
      .flatMap((table) => table.props('columns') as Array<{ key: string }>)
      .map((column) => column.key)
    expect(diagnosticColumns).toContain('reason_code')
    expect(diagnosticColumns).toContain('lldp_system_name')
    expect(diagnosticColumns).toContain('matched_switch_device_id')
    wrapper.unmount()
  })

  it('keeps station update enabled while disabling AP update without identity', async () => {
    const candidate: TracksideApBusinessRow = {
      ...rows[1],
      site: '站点C',
      device_name: 'SW-C',
      interface_name: 'XGE1/0/3',
      ap_uuid: '',
      ap_mac: '',
      ap_name: '',
    }
    api.listTracksideApBusiness.mockResolvedValueOnce(page([candidate]))
    const wrapper = await mountView()

    expect(buttons(wrapper, '更新站点')[0].attributes('disabled')).toBeUndefined()
    expect(buttons(wrapper, '更新 AP')[0].attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('keeps vendor, LLDP and optical columns without bidirectional loss', async () => {
    const wrapper = await mountView()
    const columns = wrapper.getComponent(NcDataTableStub).props('columns') as Array<{
      key: string
      label: string
      displayValue?: (row: TracksideApBusinessRow) => unknown
    }>
    const byKey = new Map(columns.map((column) => [column.key, column]))
    const zteRow = {
      ...rows[0],
      switch_vendor: 'ZTE',
      lldp_match_status: 'SAMPLE_REQUIRED',
    }

    expect(byKey.get('switch_vendor')?.displayValue?.(zteRow)).toBe('中兴 ZTE')
    expect(byKey.get('lldp_match_status')?.displayValue?.(zteRow)).toBe(
      '待真实样本验证',
    )
    expect(byKey.get('ap_business_threshold_dbm')?.displayValue?.(zteRow)).toBe(
      'AP Rx ≥ -13.90 dBm 且交换机 Rx ≥ -13.90 dBm',
    )
    expect(columns.map((column) => column.label)).toContain('交换机侧业务光衰')
    expect(columns.map((column) => column.label)).not.toContain('双向光衰')
    expect(columns.map((column) => column.key)).not.toContain('calculation_status')
    expect(columns.map((column) => column.key).slice(
      columns.findIndex((column) => column.key === 'ap_device_optical_status'),
      columns.findIndex((column) => column.key === 'updated_at') + 1,
    )).toEqual([
      'ap_device_optical_status',
      'ap_optical_status',
      'ap_business_threshold_dbm',
      'ap_business_reason',
      'optical_severity',
      'updated_at',
    ])
    expect(columns.map((column) => column.label)).not.toContain('交换机光衰')
    wrapper.unmount()
  })

  it('renders device module and AP business optical states independently', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page([{
      ...rows[0],
      ap_rx_power: '-17.80',
      ap_device_optical_status: 'normal',
      ap_business_optical_status: 'abnormal',
      ap_optical_status: 'abnormal',
      ap_business_reason: 'AP接收光功率 -17.80 dBm 低于业务门限 -13.90 dBm',
      optical_severity: 'abnormal',
    }]))

    const wrapper = await mountView()
    const table = wrapper.get('[data-table-id="trackside-ap-business"]')

    expect(table.text()).toContain('正常')
    expect(table.text()).toContain('光衰大')
    expect(table.get('.el-tooltip').attributes('data-content')).toContain(
      '-17.80 dBm 低于业务门限 -13.90 dBm',
    )
    wrapper.unmount()
  })

  it('marks switch Rx and the combined status abnormal when backend normal is stale', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page([{
      ...rows[0],
      model: 'WA6528X-E',
      ap_rx_power: '-7.72',
      ap_tx_power: '-19.10',
      ap_device_optical_status: 'normal',
      ap_optical_status: 'normal',
      switch_rx_power: '-19.10',
      switch_tx_power: '-20.00',
      switch_device_optical_status: 'normal',
      switch_optical_status: 'normal',
      ap_business_optical_status: 'normal',
      optical_severity: 'normal',
    }]))

    const wrapper = await mountView()
    const table = wrapper.get('[data-table-id="trackside-ap-business"]')

    expect(table.get('[data-testid="trackside-ap-rx"]').classes()).toContain('optical-normal')
    expect(table.get('[data-testid="trackside-switch-rx"]').classes()).toContain('optical-alarm')
    expect(table.get('[data-testid="trackside-switch-tx"]').classes()).not.toContain('optical-alarm')
    expect(table.get('[data-testid="trackside-ap-tx"]').classes()).not.toContain('optical-alarm')
    expect(table.text()).toContain('光衰大')
    wrapper.unmount()
  })

  it('does not load or render the vendor adapter development area', async () => {
    const wrapper = await mountView()

    for (const removed of [
      '中兴 ZTE',
      'C89E-4 Release 已验证',
      'ZXR10 5960X-ES',
      '接口（可选）',
      '启动厂商采样',
      '查看 Profile',
      '下载原始输出 ZIP',
    ]) expect(wrapper.text()).not.toContain(removed)
    expect(wrapper.find('.adapter-section').exists()).toBe(false)
    expect(wrapper.text()).toContain('设备管理与 AC 生成业务行；基础资料仅补充站点和工程属性')
    wrapper.unmount()
  })

  it('renders ZTE unknown and unavailable DOM module states without calling them faults', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page([
      { ...rows[0], switch_optical_status: 'unverified' },
      { ...rows[1], switch_optical_status: 'dom_unavailable' },
    ]))

    const wrapper = await mountView()

    expect(wrapper.text()).toContain('状态未知/第三方模块')
    expect(wrapper.text()).toContain('不支持 DOM')
    expect(wrapper.text()).not.toContain('光模块故障')
    wrapper.unmount()
  })

  it('shows station options from the backend page and queries immediately when changed', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows.slice(0, 1), 1, ['01-小洋江站', '02-云龙火车站']))
    const wrapper = await mountView()
    const stationSelect = wrapper.find('.station-select')
    expect(stationSelect.attributes('allow-create')).toBeUndefined()

    expect(wrapper.findAll('option').map((item) => item.text())).toEqual(expect.arrayContaining([
      '全部站点',
      '01-小洋江站',
      '02-云龙火车站',
    ]))

    api.listTracksideApBusiness.mockResolvedValue(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    api.listTracksideApBusiness.mockClear()
    ;(wrapper.vm as unknown as { filters: { page: number } }).filters.page = 3
    await stationSelect.setValue('02-云龙火车站')
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '02-云龙火车站',
      query: '',
      optical_anomaly_only: false,
      page: 1,
      page_size: 50,
    })
    expect((wrapper.find('.station-select').element as HTMLSelectElement).value).toBe('02-云龙火车站')

    api.listTracksideApBusiness.mockClear()
    await stationSelect.setValue('')
    await flushPromises()
    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '',
      query: '',
      optical_anomaly_only: false,
      page: 1,
      page_size: 50,
    })
    wrapper.unmount()
  })

  it('renders page size options and reloads from the first page when changed', async () => {
    const wrapper = await mountView()
    const pagination = wrapper.get('.el-pagination-stub')

    expect(pagination.attributes('data-page-sizes')).toBe('[20,50,100,200]')
    api.listTracksideApBusiness.mockClear()
    ;(wrapper.vm as unknown as { filters: { page: number } }).filters.page = 4

    await wrapper.get('.pagination-size').setValue('100')
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '',
      query: '',
      optical_anomaly_only: false,
      page: 1,
      page_size: 100,
    })
    wrapper.unmount()
  })

  it('clears a station that disappears after reload and retries from the full dataset', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    const wrapper = await mountView()
    const stationSelect = wrapper.find('.station-select')

    api.listTracksideApBusiness.mockResolvedValue(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    await stationSelect.setValue('02-云龙火车站')
    await flushPromises()

    api.listTracksideApBusiness.mockClear()
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows.slice(0, 1), 1, ['01-小洋江站']))
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows, 1, ['01-小洋江站']))

    await button(wrapper, '刷新').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenNthCalledWith(1, {
      station: '02-云龙火车站',
      query: '',
      optical_anomaly_only: false,
      page: 1,
      page_size: 50,
    })
    expect(api.listTracksideApBusiness).toHaveBeenNthCalledWith(2, {
      station: '',
      query: '',
      optical_anomaly_only: false,
      page: 1,
      page_size: 50,
    })
    expect((wrapper.find('.station-select').element as HTMLSelectElement).value).toBe('')
    wrapper.unmount()
  })

  it('submits an update task without opening or routing to the task center', async () => {
    api.startTracksideApUpdate.mockResolvedValueOnce(task('update-running', 'RUNNING', 'trackside_ap_optical_update'))
    const openTaskWindow = vi.fn()
    ;(window as unknown as { netconsoleDesktop?: { openTaskWindow: typeof openTaskWindow } }).netconsoleDesktop = { openTaskWindow }
    const wrapper = await mountView()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()

    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({})
    expect(openTaskWindow).not.toHaveBeenCalled()
    expect(taskApi.listTasks).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    expect(wrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    expect(buttons(wrapper, '打开任务中心')).toHaveLength(0)
    wrapper.unmount()
  })

  it('submits station and AP update requests with stable scope payloads', async () => {
    const wrapper = await mountView()

    await buttons(wrapper, '更新站点')[0].trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({ station: '站点A' })

    await buttons(wrapper, '更新 AP')[0].trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({
      ap_uuid: 'ap-1',
    })

    expect(buttons(wrapper, '更新 AP')[1].attributes('disabled')).toBeUndefined()
    await buttons(wrapper, '更新 AP')[1].trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({
      ap_mac: '305f-277a-1880',
    })
    wrapper.unmount()
  })

  it('shows backend failures on the current page', async () => {
    api.startTracksideApUpdate.mockRejectedValueOnce(new Error('后端拒绝：任务资源繁忙'))
    const wrapper = await mountView()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('后端拒绝：任务资源繁忙')
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    wrapper.unmount()
  })

  it('recovers active tasks without adding a page-level task-center entry', async () => {
    taskApi.listTasks.mockResolvedValueOnce([
      globalTask('update-running', 'RUNNING'),
    ])
    const activeWrapper = await mountView()

    expect(button(activeWrapper, '更新全部光衰').attributes('disabled')).toBeDefined()
    expect(activeWrapper.text()).not.toContain('检测到正在运行的轨旁 AP 任务')
    expect(activeWrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    expect(buttons(activeWrapper, '打开任务中心')).toHaveLength(0)
    activeWrapper.unmount()
  })

  it('does not let a globally tracked export task lock update buttons', async () => {
    taskApi.listTasks.mockResolvedValueOnce([
      globalTask('export-running', 'RUNNING', 'web_export_trackside_ap_business'),
    ])
    const exportWrapper = await mountView()

    expect(button(exportWrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    expect(button(exportWrapper, '导出表格').attributes('disabled')).toBeDefined()
    expect(buttons(exportWrapper, '打开任务中心')).toHaveLength(0)
    expect(exportWrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    exportWrapper.unmount()
  })

  it('does not start an export while a trackside update is running', async () => {
    taskApi.listTasks.mockResolvedValueOnce([
      globalTask('update-running', 'RUNNING'),
    ])
    const wrapper = await mountView()

    expect(button(wrapper, '导出表格').attributes('disabled')).toBeDefined()
    expect(api.getTracksideApBusinessExportProposal).not.toHaveBeenCalled()
    expect(api.startTracksideApBusinessExport).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('refreshes completed update tasks without resetting filters or page', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    api.startTracksideApUpdate.mockResolvedValueOnce(task('update-running', 'RUNNING', 'trackside_ap_optical_update'))
    taskApi.listTasks
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([globalTask('update-running', 'RUNNING')])
    const wrapper = await mountView()
    api.listTracksideApBusiness.mockResolvedValue(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    await wrapper.find('.station-select').setValue('02-云龙火车站')
    await flushPromises()
    ;(wrapper.vm as unknown as { filters: { query: string; page: number } }).filters.query = 'AP-A'
    ;(wrapper.vm as unknown as { filters: { page: number } }).filters.page = 2
    api.listTracksideApBusiness.mockClear()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()
    taskApi.listTasks.mockResolvedValue([
      globalTask('update-running', 'COMPLETED'),
    ])
    await useTaskStore().refresh()
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '02-云龙火车站',
      query: 'AP-A',
      optical_anomaly_only: false,
      page: 2,
      page_size: 50,
    })
    expect(wrapper.text()).not.toContain('轨旁 AP 光衰数据已刷新')
    expect((wrapper.find('.station-select').element as HTMLSelectElement).value).toBe('02-云龙火车站')
    wrapper.unmount()
  })

  it('does not open a delayed Save As when a business export completes', async () => {
    api.startTracksideApBusinessExport.mockResolvedValueOnce(task('export-running', 'RUNNING', 'trackside_ap_business_export'))
    const wrapper = await mountView()

    await button(wrapper, '导出表格').trigger('click')
    await flushPromises()

    expect(platformMocks.downloadBackendResource).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('netconsole.user-selected-exports.v1')).toContain('export-running')
    expect(wrapper.text()).not.toContain('保存导出表格')
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    expect(buttons(wrapper, '打开任务中心')).toHaveLength(0)
    wrapper.unmount()
  })

  it('shows snapshot time and sends expected revision for pagination', async () => {
    const revision = 'a'.repeat(64)
    api.listTracksideApBusiness.mockResolvedValue(snapshotPage(revision))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain(`快照 ${revision.slice(0, 12)}`)
    api.listTracksideApBusiness.mockClear()

    await wrapper.get('.pagination-next').trigger('click')
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '',
      query: '',
      optical_anomaly_only: false,
      page: 2,
      page_size: 50,
      expected_revision: revision,
    })
    wrapper.unmount()
  })

  it('exports the current filter and stable selected row ids', async () => {
    const revision = 'a'.repeat(64)
    api.listTracksideApBusiness.mockResolvedValue(snapshotPage(revision))
    const wrapper = await mountView()
    const firstTable = wrapper.findAllComponents(NcDataTableStub)[0]
    firstTable.vm.$emit('selection-change', [snapshotPage(revision).items[0]])
    await flushPromises()

    await button(wrapper, '导出表格').trigger('click')
    await flushPromises()

    expect(api.startTracksideApBusinessExport).toHaveBeenCalledWith({
      generated_at: '2026-07-21T23:45:01+08:00',
      suggested_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
      expected_revision: revision,
      station: '',
      query: '',
      optical_anomaly_only: false,
      selected_row_ids: ['row-1'],
    })
    wrapper.unmount()
  })

  it('reloads the first page without an expected revision after stale conflict', async () => {
    const oldRevision = 'a'.repeat(64)
    const newRevision = 'b'.repeat(64)
    api.listTracksideApBusiness.mockResolvedValueOnce(snapshotPage(oldRevision))
    const wrapper = await mountView()
    api.listTracksideApBusiness.mockReset()
    api.listTracksideApBusiness
      .mockRejectedValueOnce(new ApiRequestError('数据已更新', 409, 'TRACKSIDE_AP_SNAPSHOT_STALE'))
      .mockResolvedValueOnce(snapshotPage(newRevision))

    await wrapper.get('.pagination-next').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(api.listTracksideApBusiness).toHaveBeenNthCalledWith(1, {
      station: '',
      query: '',
      optical_anomaly_only: false,
      page: 2,
      page_size: 50,
      expected_revision: oldRevision,
    })
    expect(api.listTracksideApBusiness).toHaveBeenNthCalledWith(2, {
      station: '',
      query: '',
      optical_anomaly_only: false,
      page: 1,
      page_size: 50,
    })
    expect(wrapper.text()).toContain(newRevision.slice(0, 12))
    wrapper.unmount()
  })

  it('keeps the current table when snapshot creation is temporarily unstable', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(snapshotPage())
    const wrapper = await mountView()
    api.listTracksideApBusiness.mockRejectedValueOnce(
      new ApiRequestError('数据刷新中', 503, 'TRACKSIDE_AP_SNAPSHOT_UNSTABLE'),
    )

    await button(wrapper, '查询').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已保留当前表格')
    expect(wrapper.findAll('.table-row')).toHaveLength(rows.length)
    wrapper.unmount()
  })
})

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(TracksideApBusinessView, {
    global: {
      directives: { loading: () => undefined },
      stubs: { ...ElementStubs, NcDataTable: NcDataTableStub },
    },
  })
  await flushPromises()
  return wrapper
}

async function mountCachedView(): Promise<VueWrapper> {
  const CachedHost = defineComponent({
    components: { TracksideApBusinessView },
    setup() {
      const active = ref(true)
      return { active }
    },
    template: '<KeepAlive><TracksideApBusinessView v-if="active" /></KeepAlive>',
  })
  const wrapper = mount(CachedHost, {
    attachTo: document.body,
    global: {
      directives: { loading: () => undefined },
      stubs: { ...ElementStubs, NcDataTable: NcDataTableStub },
    },
  })
  await flushPromises()
  return wrapper
}

function button(wrapper: VueWrapper, label: string) {
  const match = buttons(wrapper, label)[0]
  if (!match) throw new Error(`按钮不存在：${label}`)
  return match
}

function buttons(wrapper: VueWrapper, label: string) {
  return wrapper.findAll('button').filter((item) => item.text().includes(label))
}
