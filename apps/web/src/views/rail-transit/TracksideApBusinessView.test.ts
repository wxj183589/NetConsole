// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

import { resetWebFeaturesForTest, setWebFeaturesForTest } from '../../features'
import type { TracksideApBusinessPage, TracksideApBusinessRow, TracksideApTask } from '../../types/tracksideApBusiness'

const routerPush = vi.fn()
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

vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('../../api/tracksideApBusiness', () => api)
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: platformMocks.downloadBackendResource }))

import TracksideApBusinessView from './TracksideApBusinessView.vue'

const storageKey = 'netconsole.trackside-ap.last-task'

const rows: TracksideApBusinessRow[] = [
  {
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
  props: { data: { type: Array, default: () => [] }, height: String, tableId: String },
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
    resetWebFeaturesForTest()
    setWebFeaturesForTest({
      'web.rail_trackside_ap_business_update': { visible: true, enabled: true },
      'web.rail_trackside_ap_business_export': { visible: true, enabled: true },
      'web.rail_task_control': { visible: true, enabled: true },
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
    routerPush.mockReset()
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
    expect(buttons(wrapper, '打开任务窗口')).toHaveLength(1)
    expect(wrapper.find('[data-table-id="trackside-ap-business"]').attributes('data-height')).toBe('calc(100vh - 330px)')
    expect(wrapper.find('[data-table-id="trackside-ap-business-task-result"]').exists()).toBe(false)
    expect(wrapper.find('input[placeholder="站点"]').exists()).toBe(false)
    expect(wrapper.find('select').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows station options from the backend page and queries immediately when changed', async () => {
    api.listTracksideApBusiness.mockResolvedValueOnce(page(rows.slice(0, 1), 1, ['01-小洋江站', '02-云龙火车站']))
    const wrapper = await mountView()
    const stationSelect = wrapper.find('select')
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
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('02-云龙火车站')

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
    const stationSelect = wrapper.find('select')

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
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('')
    wrapper.unmount()
  })

  it('submits an update task, opens the task window and keeps only a light notice', async () => {
    api.startTracksideApUpdate.mockResolvedValueOnce(task('update-running', 'RUNNING', 'trackside_ap_optical_update'))
    const wrapper = await mountView()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()

    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({})
    expect(routerPush).toHaveBeenLastCalledWith({ name: 'tasks', query: { module: 'rail', task_id: 'update-running' } })
    expect(wrapper.text()).toContain('任务已提交，详细进度请查看任务窗口')
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    expect(wrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    expect(buttons(wrapper, '打开任务窗口')).toHaveLength(1)
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
    api.startTracksideApUpdate.mockRejectedValueOnce(new Error('后端拒绝：功能未启用'))
    const wrapper = await mountView()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('后端拒绝：功能未启用')
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    wrapper.unmount()
  })

  it('recovers active tasks with the top task-window entry only', async () => {
    api.recoverTracksideApTasks.mockResolvedValueOnce([task('update-running', 'RUNNING', 'trackside_ap_optical_update')])
    localStorage.setItem(storageKey, 'update-running')
    const activeWrapper = await mountView()

    expect(button(activeWrapper, '更新全部光衰').attributes('disabled')).toBeDefined()
    expect(activeWrapper.text()).toContain('检测到正在运行的轨旁 AP 任务，详细进度请查看任务窗口')
    expect(activeWrapper.text()).not.toContain('停止、日志和恢复统一在任务窗口处理')
    expect(buttons(activeWrapper, '打开任务窗口')).toHaveLength(1)
    await button(activeWrapper, '打开任务窗口').trigger('click')
    expect(routerPush).toHaveBeenLastCalledWith({ name: 'tasks', query: { module: 'rail', task_id: 'update-running' } })
    activeWrapper.unmount()
  })

  it('does not let an export task lock update buttons and clears stale recovered tasks', async () => {
    api.recoverTracksideApTasks.mockResolvedValueOnce([task('export-running', 'RUNNING', 'trackside_ap_business_export')])
    localStorage.setItem(storageKey, 'export-running')
    const exportWrapper = await mountView()

    expect(button(exportWrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    expect(buttons(exportWrapper, '打开任务窗口')).toHaveLength(1)
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
    await wrapper.find('select').setValue('02-云龙火车站')
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
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('02-云龙火车站')
    wrapper.unmount()
  })

  it('auto-saves completed business exports with the backend artifact name without a page save button', async () => {
    vi.useFakeTimers()
    const expectedName = '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx'
    api.startTracksideApBusinessExport.mockResolvedValueOnce(task('export-running', 'RUNNING', 'trackside_ap_business_export'))
    api.getTracksideApTask.mockResolvedValueOnce({
      ...task('export-complete', 'COMPLETED', 'trackside_ap_business_export'),
      artifact_id: 'artifact-1',
      artifact_name: expectedName,
      available: true,
    })
    const wrapper = await mountView()

    await button(wrapper, '导出表格').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(platformMocks.downloadBackendResource).toHaveBeenCalledWith({
      apiPath: '/api/rail-transit/trackside-ap-business/artifacts/artifact-1/download',
      suggestedName: expectedName,
    })
    expect(wrapper.text()).toContain('轨旁 AP 业务表格已生成')
    expect(wrapper.text()).not.toContain('保存导出表格')
    expect(wrapper.text()).not.toContain('轨旁 AP 任务')
    expect(buttons(wrapper, '打开任务窗口')).toHaveLength(1)
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
