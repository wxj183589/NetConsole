// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

import { resetWebFeaturesForTest, setWebFeaturesForTest } from '../../features'
import { resetUserSelectedExportForTests } from '../../composables/useUserSelectedExport'
import type {
  TracksideApBusinessPage,
  TracksideApBusinessRow,
  TracksideApTask,
} from '../../types/tracksideApBusiness'

const api = vi.hoisted(() => ({
  getTracksideApTask: vi.fn(),
  listTracksideApBusiness: vi.fn(),
  recoverTracksideApTasks: vi.fn(),
  startTracksideApBusinessExport: vi.fn(),
  startTracksideApUpdate: vi.fn(),
  tracksideApBusinessDownloadRequest: vi.fn(),
}))
const platformMocks = vi.hoisted(() => ({
  downloadBackendResource: vi.fn(),
}))

vi.mock('../../api/tracksideApBusiness', () => api)
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: platformMocks.downloadBackendResource,
  getPlatformAdapter: () => ({ hostType: 'browser' }),
}))

import TracksideApBusinessView from './TracksideApBusinessView.vue'

const storageKey = 'netconsole.trackside-ap.last-task'

const extendedRowDefaults = {
  switch_vendor: 'H3C',
  switch_tx_power: '',
  switch_rx_low_alarm: '',
  switch_rx_high_alarm: '',
  switch_tx_low_alarm: '',
  switch_tx_high_alarm: '',
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
    ap_optical_status: 'normal',
    updated_at: '2026-07-21T10:00:00+08:00',
    optical_severity: 'normal',
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
    ap_optical_status: 'not_collected',
    updated_at: '',
    optical_severity: 'warning',
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

const NcDataTableStub = defineComponent({
  name: 'NcDataTable',
  props: {
    data: { type: Array, default: () => [] },
    columns: { type: Array, default: () => [] },
    emptyText: String,
    height: String,
    tableId: String,
  },
  template: `
    <div class="nc-data-table" :data-table-id="tableId" :data-height="height">
      <div v-for="(row, index) in data" :key="index" class="table-row">
        <slot name="cell-switch_rx_power" :row="row" />
        <slot name="cell-switch_optical_status" :row="row" />
        <slot name="cell-ap_rx_power" :row="row" />
        <slot name="cell-ap_optical_status" :row="row" />
        <slot name="cell-optical_severity" :row="row" />
        <slot name="cell-actions" :row="row" />
      </div>
    </div>
  `,
})

const ElementStubs = {
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
    props: { currentPage: Number },
    emits: ['current-change'],
    template: '<button class="pagination-next" @click="$emit(\'current-change\', Number(currentPage || 1) + 1)">下一页</button>',
  }),
  ElTag: defineComponent({ template: '<span class="el-tag"><slot /></span>' }),
}

describe('TracksideApBusinessView mounted behavior', () => {
  beforeEach(() => {
    resetUserSelectedExportForTests()
    resetWebFeaturesForTest()
    setWebFeaturesForTest({
      'web.rail_trackside_ap_business_update': { visible: true, enabled: true },
      'web.rail_trackside_ap_business_export': { visible: true, enabled: true },
      'web.rail_task_control': { visible: true, enabled: true },
      'rail.zte_trackside_switch_adapter': { visible: true, enabled: true },
    })
    api.listTracksideApBusiness.mockResolvedValue(page())
    api.recoverTracksideApTasks.mockResolvedValue([])
    api.getTracksideApTask.mockResolvedValue(task('task-complete', 'COMPLETED', 'trackside_ap_optical_update', { status: 'DONE', target_count: 1, success_count: 1 }))
    api.startTracksideApBusinessExport.mockResolvedValue(task('export-task', 'RUNNING', 'trackside_ap_business_export'))
    api.startTracksideApUpdate.mockResolvedValue(task('update-task', 'COMPLETED', 'trackside_ap_optical_update', { status: 'DONE', target_count: 1, success_count: 1 }))
    api.tracksideApBusinessDownloadRequest.mockImplementation((artifactId: string, artifactName: string) => ({
      apiPath: `/api/rail-transit/trackside-ap-business/artifacts/${encodeURIComponent(artifactId)}/download`,
      suggestedName: artifactName,
    }))
    platformMocks.downloadBackendResource.mockResolvedValue({ status: 'saved', capabilityId: 'cap-1' })
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

  it('localizes empty reasons and exposes unmatched online counts', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce({
      ...page([], 1, []),
      device_count: 15,
      candidate_interface_count: 756,
      fit_ap_resource_count: 0,
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
        reason: '在线 AP 未匹配到当前有效轨旁 AP 资料。',
        suggested_action: '补充基础资料',
      }],
    })
    const wrapper = await mountView()

    expect(wrapper.getComponent(NcDataTableStub).props('emptyText')).toBe(
      '已发现候选 AP 端口，部分端口尚未关联 AP 运行态资料。',
    )
    expect(wrapper.text()).not.toContain('trackside.empty.no_fit_ap_resource')
    expect(wrapper.text()).toContain('待关联在线 AP 188')
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
    expect(columns.map((column) => column.label)).toContain('模块状态')
    expect(columns.map((column) => column.label)).not.toContain('双向光衰')
    expect(columns.map((column) => column.key)).not.toContain('calculation_status')
    expect(columns.map((column) => column.key).slice(
      columns.findIndex((column) => column.key === 'ap_optical_status'),
      columns.findIndex((column) => column.key === 'updated_at') + 1,
    )).toEqual(['ap_optical_status', 'optical_severity', 'updated_at'])
    expect(columns.map((column) => column.label)).not.toContain('交换机光衰')
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
    expect(wrapper.text()).toContain('已按当前项目、建设阶段、当前工作状态和站点交换机工作范围过滤；AP 身份仅用于关联')
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
    expect(wrapper.text()).toContain('任务已提交，可通过顶部任务入口查看进度')
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
    api.recoverTracksideApTasks.mockResolvedValueOnce([task('update-running', 'RUNNING', 'trackside_ap_optical_update')])
    localStorage.setItem(storageKey, 'update-running')
    const activeWrapper = await mountView()

    expect(button(activeWrapper, '更新全部光衰').attributes('disabled')).toBeDefined()
    expect(activeWrapper.text()).toContain('检测到正在运行的轨旁 AP 任务，可通过顶部任务入口查看进度')
    expect(activeWrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    expect(buttons(activeWrapper, '打开任务中心')).toHaveLength(0)
    activeWrapper.unmount()
  })

  it('does not let an export task lock update buttons and clears stale recovered tasks', async () => {
    api.recoverTracksideApTasks.mockResolvedValueOnce([task('export-running', 'RUNNING', 'trackside_ap_business_export')])
    localStorage.setItem(storageKey, 'export-running')
    const exportWrapper = await mountView()

    expect(button(exportWrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    expect(buttons(exportWrapper, '打开任务中心')).toHaveLength(0)
    expect(exportWrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    exportWrapper.unmount()

    api.recoverTracksideApTasks.mockResolvedValueOnce([])
    localStorage.setItem(storageKey, 'stale-task')
    const staleWrapper = await mountView()

    expect(localStorage.getItem(storageKey)).toBeNull()
    expect(button(staleWrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    expect(staleWrapper.text()).not.toContain('检测到正在运行的轨旁 AP 任务')
    expect(staleWrapper.text()).not.toContain('轨旁 AP 任务')
    staleWrapper.unmount()
  })

  it('refreshes completed update tasks without resetting filters or page', async () => {
    vi.useFakeTimers()
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    api.startTracksideApUpdate.mockResolvedValueOnce(task('update-running', 'RUNNING', 'trackside_ap_optical_update'))
    api.getTracksideApTask.mockResolvedValueOnce(task('update-running', 'COMPLETED', 'trackside_ap_optical_update', {
      status: 'DONE',
      target_count: 1,
      success_count: 1,
      failed_count: 0,
    }))
    const wrapper = await mountView()
    api.listTracksideApBusiness.mockResolvedValue(page(rows, 1, ['01-小洋江站', '02-云龙火车站']))
    await wrapper.find('.station-select').setValue('02-云龙火车站')
    await flushPromises()
    ;(wrapper.vm as unknown as { filters: { query: string; page: number } }).filters.query = 'AP-A'
    ;(wrapper.vm as unknown as { filters: { page: number } }).filters.page = 2
    api.listTracksideApBusiness.mockClear()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(api.getTracksideApTask).toHaveBeenCalledWith('update-running')
    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '02-云龙火车站',
      query: 'AP-A',
      optical_anomaly_only: false,
      page: 2,
      page_size: 50,
    })
    expect(wrapper.text()).toContain('轨旁 AP 光衰数据已刷新')
    expect(wrapper.text()).not.toContain('结果项')
    expect(wrapper.text()).not.toContain('target_count')
    expect((wrapper.find('.station-select').element as HTMLSelectElement).value).toBe('02-云龙火车站')
    wrapper.unmount()
  })

  it.each([
    {
      name: '仅忽略可选交换机分支时显示绿色成功',
      taskStatus: 'COMPLETED',
      summary: {
        status: 'SUCCESS', success_count: 746, failed_count: 0, skipped_count: 1,
        actionable_skipped_count: 0, ignored_skipped_count: 1,
        skipped_reason_counts: { no_station_switches: 1 },
      },
      expected: '轨旁 AP 光衰数据已刷新：成功 746，失败 0；另有 1 项不适用或已忽略',
      type: 'success',
    },
    {
      name: '存在真实失败时显示明确成功和失败数量',
      taskStatus: 'COMPLETED',
      summary: {
        status: 'PARTIAL_SUCCESS', success_count: 745, failed_count: 1,
        actionable_skipped_count: 0, ignored_skipped_count: 0,
      },
      expected: '轨旁 AP 光衰数据已刷新：成功 745，失败 1，请在任务中心查看详情',
      type: 'warning',
    },
    {
      name: '存在可处理跳过时明确显示未执行数量',
      taskStatus: 'COMPLETED',
      summary: {
        status: 'PARTIAL_SUCCESS', success_count: 745, failed_count: 0,
        actionable_skipped_count: 1, ignored_skipped_count: 0,
        skipped_reason_counts: { connection_incomplete: 1 },
      },
      expected: '轨旁 AP 光衰数据已刷新：成功 745，1 个目标未执行，请在任务中心查看详情',
      type: 'warning',
    },
    {
      name: '所有目标失败时显示失败数量和主要原因',
      taskStatus: 'FAILED',
      summary: {
        status: 'FAILED', success_count: 0, failed_count: 746,
        actionable_skipped_count: 0, ignored_skipped_count: 0,
        failure_reason_counts: { fit_ap_collection_failed: 746 },
      },
      expected: '轨旁 AP 光衰更新失败：成功 0，失败 746；主要原因：AP 光衰采集失败，请在任务中心查看详情',
      type: 'error',
    },
  ])('$name', async ({ taskStatus, summary, expected, type }) => {
    vi.useFakeTimers()
    api.startTracksideApUpdate.mockResolvedValueOnce(task('update-running', 'RUNNING', 'trackside_ap_optical_update'))
    api.getTracksideApTask.mockResolvedValueOnce(task('update-running', taskStatus, 'trackside_ap_optical_update', summary))
    const wrapper = await mountView()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    const notice = wrapper.findAll('.el-alert').find((item) => item.text().includes(expected))
    expect(notice?.attributes('data-type')).toBe(type)
    expect(wrapper.text()).not.toContain('部分目标未成功')
    wrapper.unmount()
  })

  it('does not open a delayed Save As when a business export completes', async () => {
    vi.useFakeTimers()
    const expectedName = '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx'
    api.startTracksideApBusinessExport.mockResolvedValueOnce(task('export-running', 'RUNNING', 'trackside_ap_business_export'))
    api.getTracksideApTask.mockResolvedValueOnce({
      ...task('export-running', 'COMPLETED', 'trackside_ap_business_export'),
      artifact_id: 'artifact-1',
      artifact_name: expectedName,
      available: true,
    })
    const wrapper = await mountView()

    await button(wrapper, '导出表格').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(platformMocks.downloadBackendResource).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('轨旁 AP 业务表格已生成')
    expect(sessionStorage.getItem('netconsole.user-selected-exports.v1')).toContain('export-running')
    expect(wrapper.text()).not.toContain('保存导出表格')
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    expect(buttons(wrapper, '打开任务中心')).toHaveLength(0)
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

function button(wrapper: VueWrapper, label: string) {
  const match = buttons(wrapper, label)[0]
  if (!match) throw new Error(`按钮不存在：${label}`)
  return match
}

function buttons(wrapper: VueWrapper, label: string) {
  return wrapper.findAll('button').filter((item) => item.text().includes(label))
}
