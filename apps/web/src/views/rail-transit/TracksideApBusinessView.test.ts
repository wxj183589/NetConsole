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

vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('../../api/tracksideApBusiness', () => api)
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: vi.fn() }))

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
    ap_mac: '00:11:22:33:44:55',
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
    ap_mac: '00:11:22:33:44:66',
    ap_name: '',
    ap_rx_power: '',
    ap_optical_status: 'not_collected',
    updated_at: '',
    optical_severity: 'warning',
  },
]

function page(items = rows, pageNo = 1): TracksideApBusinessPage {
  return {
    items,
    total: items.length,
    page: pageNo,
    page_size: 50,
    site_id: 'demo',
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
  props: { data: { type: Array, default: () => [] } },
  template: `
    <div class="nc-data-table">
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
  ElCheckbox: defineComponent({
    props: { modelValue: Boolean },
    emits: ['update:modelValue'],
    template: '<label><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" /><slot /></label>',
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
    localStorage.clear()
    routerPush.mockReset()
    delete (window as Window & { netconsoleDesktop?: unknown }).netconsoleDesktop
  })

  afterEach(() => {
    resetWebFeaturesForTest()
    vi.useRealTimers()
  })

  it('submits all, station and AP update requests with the real scope payloads', async () => {
    const wrapper = await mountView()

    expect(button(wrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({})
    expect(wrapper.text()).toContain('任务已提交：范围 全部；目标 当前局点')

    await buttons(wrapper, '更新站点')[0].trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({ station: '站点A' })

    await buttons(wrapper, '更新 AP')[0].trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({
      ap_uuid: 'ap-1',
      ap_mac: '00:11:22:33:44:55',
      ap_name: 'AP-A',
    })

    expect(buttons(wrapper, '更新 AP')[1].attributes('disabled')).toBeUndefined()
    await buttons(wrapper, '更新 AP')[1].trigger('click')
    await flushPromises()
    expect(api.startTracksideApUpdate).toHaveBeenLastCalledWith({
      ap_uuid: '',
      ap_mac: '00:11:22:33:44:66',
      ap_name: '',
    })
    wrapper.unmount()
  })

  it('shows backend failures on the current page', async () => {
    api.startTracksideApUpdate.mockRejectedValueOnce(new Error('后端拒绝：功能未启用'))
    const wrapper = await mountView()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('后端拒绝：功能未启用')
    wrapper.unmount()
  })

  it('does not let an export task lock update buttons and clears stale recovered tasks', async () => {
    api.recoverTracksideApTasks.mockResolvedValueOnce([task('export-running', 'RUNNING', 'trackside_ap_business_export')])
    localStorage.setItem(storageKey, 'export-running')
    const exportWrapper = await mountView()

    expect(button(exportWrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    exportWrapper.unmount()

    api.recoverTracksideApTasks.mockResolvedValueOnce([])
    localStorage.setItem(storageKey, 'stale-task')
    const staleWrapper = await mountView()

    expect(localStorage.getItem(storageKey)).toBeNull()
    expect(button(staleWrapper, '更新全部光衰').attributes('disabled')).toBeUndefined()
    staleWrapper.unmount()
  })

  it('refreshes completed update tasks without resetting filters or page', async () => {
    vi.useFakeTimers()
    api.startTracksideApUpdate.mockResolvedValueOnce(task('update-running', 'RUNNING', 'trackside_ap_optical_update'))
    api.getTracksideApTask.mockResolvedValueOnce(task('update-running', 'COMPLETED', 'trackside_ap_optical_update', {
      status: 'DONE',
      target_count: 1,
      success_count: 1,
      failed_count: 0,
    }))
    const wrapper = await mountView()
    ;(wrapper.vm as unknown as { filters: { station: string; query: string; page: number } }).filters.station = '站点A'
    ;(wrapper.vm as unknown as { filters: { station: string; query: string; page: number } }).filters.query = 'AP-A'
    ;(wrapper.vm as unknown as { filters: { station: string; query: string; page: number } }).filters.page = 2
    api.listTracksideApBusiness.mockClear()

    await button(wrapper, '更新全部光衰').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(api.getTracksideApTask).toHaveBeenCalledWith('update-running')
    expect(api.listTracksideApBusiness).toHaveBeenLastCalledWith({
      station: '站点A',
      query: 'AP-A',
      optical_anomaly_only: false,
      page: 2,
      page_size: 50,
    })
    expect(wrapper.text()).toContain('更新成功')
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
