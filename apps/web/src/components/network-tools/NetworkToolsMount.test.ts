// @vitest-environment happy-dom

import { createPinia, setActivePinia } from 'pinia'
import { config, flushPromises, shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useTaskStore } from '../../stores/tasks'
import type { NetworkToolTask, WirelessScanRun } from '../../types/networkTools'
import type { TaskItem } from '../../types/task'
import NetworkToolboxPanel from './NetworkToolboxPanel.vue'
import WirelessScanPanel from './WirelessScanPanel.vue'
import {
  cancelNetworkTask,
  exportNetworkTask,
  getNetworkProbeEnvironment,
  getNetworkTask,
  getWirelessRunDetail,
  listNetworkTaskResults,
  listWirelessAdapters,
  listWirelessProjects,
  listWirelessResults,
  listWirelessRuns,
  startNetworkTask,
} from '../../api/networkTools'

vi.mock('../../api/networkTools', () => ({
  calculateIpv4: vi.fn(), calculateIpv6: vi.fn(), calculateSubnets: vi.fn(), calculateVlsm: vi.fn(), calculateWildcard: vi.fn(), summarizeRoutes: vi.fn(),
  cancelNetworkTask: vi.fn(), exportNetworkTask: vi.fn(), getNetworkExportArtifact: vi.fn(), getNetworkTask: vi.fn(), listNetworkTaskResults: vi.fn(), startNetworkTask: vi.fn(), getNetworkProbeEnvironment: vi.fn(),
  cancelWirelessTask: vi.fn(), createWirelessProject: vi.fn(), deleteWirelessProject: vi.fn(), exportWirelessScan: vi.fn(), getWirelessExportArtifact: vi.fn(), getWirelessTask: vi.fn(), getWirelessRunDetail: vi.fn(), listWirelessAdapters: vi.fn(), listWirelessProjects: vi.fn(), listWirelessResults: vi.fn(), listWirelessRuns: vi.fn(), startWirelessScan: vi.fn(),
}))

config.global.renderStubDefaultSlot = true

const task = (status: NetworkToolTask['status'], type = 'network_tools.subnet_ping'): NetworkToolTask => ({
  id: 'probe-1', type, name: '网段 Ping', status, progress: 50, current: 1, total: 0, message: '',
  created_time: '', updated_time: '', finished_time: '', result_path: '', error_message: '', result: {}, source: 'local', cancellable: status === 'RUNNING',
})
const mountGlobal = (pinia: ReturnType<typeof createPinia>) => ({
  plugins: [pinia],
  stubs: { ElTableColumn: { template: '<div />' } },
})

describe('mounted network tools lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getNetworkProbeEnvironment).mockResolvedValue({
      adapters: [{ name: 'Ethernet 2', interface_index: 12, status: 'Up', ipv4_addresses: ['192.168.50.10/24'], display_name: 'Ethernet 2 / 192.168.50.10/24 / Up' }],
      scan_engine: '系统 ping', scan_engine_available: false, supports_source_ip: true, message: 'fping 不可用',
    })
    vi.mocked(startNetworkTask).mockResolvedValue({ task: task('RUNNING') })
    vi.mocked(getNetworkTask).mockResolvedValue(task('RUNNING'))
    vi.mocked(cancelNetworkTask).mockResolvedValue(task('CANCELLED', 'network_tools.continuous_ping'))
    vi.mocked(listNetworkTaskResults).mockResolvedValue({ items: [{ target: '192.168.50.1', status: 'online' }], offset: 0, limit: 100, total: 1 })
    vi.mocked(exportNetworkTask).mockResolvedValue({ task: task('PENDING', 'network_tools.toolbox_export') })
    vi.mocked(listWirelessAdapters).mockResolvedValue([])
    vi.mocked(listWirelessProjects).mockResolvedValue([])
    vi.mocked(listWirelessRuns).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    vi.mocked(listWirelessResults).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
    vi.mocked(getWirelessRunDetail).mockResolvedValue({ scan_id: 'scan_20260715_120000_deadbeef', project_id: '', project_name: '', project_description: '', adapter_name: '', adapter_guid: '', started_at: '', ended_at: '', status: 'success', network_count: 0, raw_output: '' })
  })

  it('mounts source selection, continuous stop, paging, status grid and cancelled export without owning global polling', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useTaskStore()
    vi.spyOn(store, 'refresh').mockResolvedValue()
    const acquirePolling = vi.spyOn(store, 'acquirePolling')
    const releasePolling = vi.spyOn(store, 'releasePolling')
    const wrapper = shallowMount(NetworkToolboxPanel, { global: mountGlobal(pinia) })
    await flushPromises()
    const vm = wrapper.vm as any

    vm.taskKind = 'subnet_ping'
    vm.selectedAdapterIndex = 12
    vm.selectAdapter()
    await vm.startProbe()
    expect(startNetworkTask).toHaveBeenLastCalledWith(expect.objectContaining({ target: '192.168.50.10/24', source_ip: '192.168.50.10', usable_only: true, count: 1 }))

    store.tasks = [{ id: 'probe-1', type: 'network_tools.continuous_ping', name: '持续 Ping', status: 'RUNNING', owner: 'web_network_tools', progress: 50 } as TaskItem]
    vm.selectedTask = task('RUNNING', 'network_tools.continuous_ping')
    await nextTick()
    await wrapper.get('[data-testid="stop-task"]').trigger('click')
    expect(cancelNetworkTask).toHaveBeenCalledWith('probe-1')

    store.tasks = [{ id: 'probe-1', type: 'network_tools.subnet_ping', name: '网段 Ping', status: 'CANCELLED', owner: 'web_network_tools', progress: 50 } as TaskItem]
    vi.mocked(getNetworkTask).mockResolvedValue(task('CANCELLED'))
    vm.taskKind = 'subnet_ping'
    vm.probe.target = '192.168.50.0/24'
    vm.selectedTask = task('CANCELLED')
    vm.taskResults = [{ target: '192.168.50.1', status: 'online', latency_ms: 1.2 }]
    vm.resultTotal = 1
    await flushPromises()
    expect(wrapper.get('[data-testid="subnet-status-grid"]').find('.is-online').exists()).toBe(true)
    vm.selectSubnetResult({ target: '192.168.50.1', status: 'online' })
    await nextTick()
    expect(vm.selectedSubnetResult.target).toBe('192.168.50.1')
    await vm.changeResultPage(2)
    expect(listNetworkTaskResults).toHaveBeenLastCalledWith('probe-1', 500, 500)
    await wrapper.get('[data-testid="export-csv"]').trigger('click')
    expect(exportNetworkTask).toHaveBeenCalledWith('probe-1', 'csv')

    wrapper.unmount()
    expect(acquirePolling).not.toHaveBeenCalled()
    expect(releasePolling).not.toHaveBeenCalled()
  })

  it('mounts WLAN SQL paging with server-side filters and leaves shared polling alive', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useTaskStore()
    vi.spyOn(store, 'refresh').mockResolvedValue()
    const acquirePolling = vi.spyOn(store, 'acquirePolling')
    const releasePolling = vi.spyOn(store, 'releasePolling')
    const wrapper = shallowMount(WirelessScanPanel, { global: mountGlobal(pinia) })
    await flushPromises()
    const vm = wrapper.vm as any
    const run = { scan_id: 'scan_20260715_120000_deadbeef', started_at: '', ended_at: '', status: 'success', network_count: 1201 } as WirelessScanRun

    await vm.selectRun(run)
    vm.form.only_trackside = true
    vm.form.band = '5G'
    vm.form.radio = '2'
    vm.form.search = '测试站'
    vm.resultPageSize = 200
    await vm.changeResultPage(3)
    expect(listWirelessResults).toHaveBeenLastCalledWith(run.scan_id, 3, 200, { only_trackside: true, band: '5G', radio: '2', search: '测试站' })

    wrapper.unmount()
    expect(acquirePolling).not.toHaveBeenCalled()
    expect(releasePolling).not.toHaveBeenCalled()
  })
})
