// @vitest-environment happy-dom

import { computed, defineComponent, h, inject, provide, reactive, useAttrs, type Component, type ComputedRef, type PropType } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getDeviceOverview: vi.fn(),
  getDeviceDetailSection: vi.fn(),
  getDeviceInterfaceDetail: vi.fn(),
  refreshDeviceDetails: vi.fn(),
  taskStore: null as null | {
    tasks: Array<Record<string, unknown>>
    refresh: ReturnType<typeof vi.fn>
    acquirePolling: ReturnType<typeof vi.fn>
    releasePolling: ReturnType<typeof vi.fn>
  },
  routerPush: vi.fn(),
  messages: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('../../api/deviceManagement', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../api/deviceManagement')>(),
  getDeviceOverview: mocks.getDeviceOverview,
  getDeviceDetailSection: mocks.getDeviceDetailSection,
  getDeviceInterfaceDetail: mocks.getDeviceInterfaceDetail,
  refreshDeviceDetails: mocks.refreshDeviceDetails,
}))
vi.mock('../../stores/tasks', () => ({ useTaskStore: () => mocks.taskStore }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.routerPush }) }))
vi.mock('../../platform/runtime', () => ({
  getRuntimeConfig: () => ({ hostType: 'browser', apiBaseUrl: '', apiToken: '' }),
  getPlatformAdapter: () => ({ openExternalUrl: vi.fn() }),
}))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: mocks.messages,
}))

import DeviceDetailPanel from './DeviceDetailPanel.vue'
import type { DeviceOverviewResponse } from '../../types/deviceManagement'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, slots.default?.())
  },
})

const buttonStub = defineComponent({
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', { ...attrs, disabled: props.disabled || props.loading, onClick: () => emit('click') }, slots.default?.())
  },
})

const inputStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { attrs, emit }) {
    return () => h('input', { ...attrs, value: props.modelValue, onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value) })
  },
})

const tabsStub = defineComponent({
  props: { modelValue: { type: String, default: 'overview' } },
  emits: ['update:modelValue', 'tab-change'],
  setup(_props, { emit, slots }) {
    return () => h('div', [
      h('button', { 'data-testid': 'tab-overview', onClick: () => { emit('update:modelValue', 'overview'); emit('tab-change', 'overview') } }, '概览'),
      h('button', { 'data-testid': 'tab-interfaces', onClick: () => { emit('update:modelValue', 'interfaces'); emit('tab-change', 'interfaces') } }, '接口'),
      h('button', { 'data-testid': 'tab-optical', onClick: () => { emit('update:modelValue', 'optical'); emit('tab-change', 'optical') } }, '光模块'),
      h('button', { 'data-testid': 'tab-lldp', onClick: () => { emit('update:modelValue', 'lldp'); emit('tab-change', 'lldp') } }, 'LLDP'),
      h('button', { 'data-testid': 'tab-business', onClick: () => { emit('update:modelValue', 'business'); emit('tab-change', 'business') } }, '关联业务'),
      slots.default?.(),
    ])
  },
})

const paginationStub = defineComponent({
  props: { total: { type: Number, default: 0 } },
  emits: ['current-change', 'size-change'],
  setup(_props, { emit }) {
    return () => h('button', { 'data-testid': 'next-page', onClick: () => emit('current-change', 2) }, '下一页')
  },
})

const dialogStub = defineComponent({
  props: { modelValue: Boolean },
  setup(props, { slots }) {
    return () => props.modelValue ? h('section', [slots.default?.(), slots.footer?.()]) : null
  },
})

const tableRowsKey = Symbol('device-detail-table-rows')
const tableStub = defineComponent({
  props: { data: { type: Array as PropType<Array<Record<string, unknown>>>, default: () => [] } },
  setup(props, { slots }) {
    provide(tableRowsKey, computed(() => props.data))
    return () => h('div', { class: 'el-table-stub' }, slots.default?.())
  },
})
const tableColumnStub = defineComponent({
  setup(_props, { slots }) {
    const rows = inject<ComputedRef<Array<Record<string, unknown>>>>(tableRowsKey, computed(() => []))
    return () => h('div', { class: 'el-table-column-stub' }, slots.default
      ? rows.value.map((row, index) => h('div', { class: 'el-table-cell-stub', key: index }, slots.default?.({ row })))
      : [])
  },
})

const elementStubs: Record<string, Component | boolean> = {
  ElAlert: passthrough,
  ElButton: buttonStub,
  ElDescriptions: passthrough,
  ElDescriptionsItem: passthrough,
  ElDialog: dialogStub,
  ElEmpty: passthrough,
  ElInput: inputStub,
  ElOption: passthrough,
  ElPagination: paginationStub,
  ElSelect: passthrough,
  ElTable: tableStub,
  ElTableColumn: tableColumnStub,
  ElTabPane: passthrough,
  ElTabs: tabsStub,
}

const overview: DeviceOverviewResponse = {
  device_uuid: 'device-1', name: 'SW-1', system_name: 'sw-1', device_type: 'SW', station: null, location: null,
  primary_address: '192.0.2.1', backup_address: null, model: null, serial_number: null, mac_address: null,
  bootrom_version: null, uptime: null, connection_status: 'UNKNOWN',
  platform_facts: { vendor: 'H3C', role: 'switch', platform: 'comware', software_version: null, software_major: null, source: 'test', confidence: 'high', collected_at: null },
  capabilities: [{ capability_id: 'device.interfaces.read', available: true, executable: false, source: 'test', reason: null, profile_id: null, profile_version: null }],
  command_profile: { capability_id: 'device.inventory.collect', available: true, executable: true, source: 'test', reason: null, profile_id: 'profile-1', profile_version: 1, compatibility: 'verified', risk: null, real_device_status: 'reachable' },
  visible_sections: ['overview', 'interfaces', 'optical', 'lldp', 'configuration', 'tasks', 'business'],
  task_facts: { recent_task_count: 0, active_task_count: 0, latest_running_task: null, latest_successful_task: null, latest_failed_task: null, latest_error: null, truncated: false },
  counts: { interfaces: 0, transceivers: 0, lldp_neighbors: 0, recent_tasks: 0, config_snapshots: 0 },
  snapshot: { available: true, source: 'snapshot', collected_at: null, reason: null },
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.taskStore = reactive({ tasks: [], refresh: vi.fn(async () => undefined), acquirePolling: vi.fn(), releasePolling: vi.fn() })
  mocks.getDeviceOverview.mockResolvedValue(overview)
  mocks.getDeviceDetailSection.mockResolvedValue({ items: [{ name: 'GigabitEthernet1/0/1', status: null }], total: 1, page: 1, page_size: 50, total_pages: 1, source: { available: true, source: 'snapshot', collected_at: '', reason: null } })
  mocks.refreshDeviceDetails.mockResolvedValue({ task_id: 'refresh-1', operation_id: 'device.inventory.collect', status: 'PENDING', reused: false, message: '等待执行' })
})

async function renderPanel(withOverview = true) {
  const wrapper = mount(DeviceDetailPanel, {
    props: { deviceUuid: 'device-1', mode: 'page', ...(withOverview ? { overview } : {}) },
    global: { directives: { loading: () => undefined }, stubs: elementStubs },
  })
  await flushPromises()
  return wrapper
}

describe('DeviceDetailPanel mounted interactions', () => {
  it('renders backend-visible tabs, loads a section lazily once, and paginates', async () => {
    const wrapper = await renderPanel()
    expect(wrapper.find('[data-testid="tab-interfaces"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).toContain('switch')
    expect(wrapper.text()).toContain('profile-1')
    expect(mocks.getDeviceDetailSection).not.toHaveBeenCalled()

    mocks.getDeviceDetailSection.mockResolvedValueOnce({ items: [{ name: 'GigabitEthernet1/0/1', status: null }], total: 1, page: 1, page_size: 50, total_pages: 1, truncated: true, source: { available: true, source: 'snapshot', collected_at: '', task_id: 'section-task-1', reason: '扫描上限 1000 条' } })
    await wrapper.get('[data-testid="tab-interfaces"]').trigger('click')
    await flushPromises()
    expect(mocks.getDeviceDetailSection).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('section-task-1')
    expect(wrapper.text()).toContain('结果已截断：扫描上限 1000 条')
    expect(mocks.getDeviceDetailSection).toHaveBeenCalledWith('device-1', 'interfaces', expect.objectContaining({ page: 1, page_size: 50 }))
    await wrapper.get('[data-testid="tab-interfaces"]').trigger('click')
    await flushPromises()
    expect(mocks.getDeviceDetailSection).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-testid="next-page"]').trigger('click')
    await flushPromises()
    expect(mocks.getDeviceDetailSection).toHaveBeenCalledTimes(2)
  })

  it('中文显示设备枚举并只按后端严重性标记接收功率', async () => {
    mocks.getDeviceDetailSection.mockImplementation((_deviceUuid: string, section: string) => {
      if (section === 'optical') {
        return Promise.resolve({
          items: [
            { interface_name: 'GE1/0/1', severity: 'normal', severity_reason: 'RX power is above maintenance normal line', rx_power: -8 },
            { interface_name: 'GE1/0/2', severity: 'notice', severity_reason: 'RX power is below maintenance normal line', rx_power: -18 },
            { interface_name: 'GE1/0/3', severity: 'alarm', severity_reason: 'RX power below alarm low threshold', rx_power: -28 },
            { interface_name: 'GE1/0/4', severity: 'critical', severity_reason: 'Vendor raw reason', rx_power: -30 },
            { interface_name: 'GE1/0/5', severity: '正常', severity_reason: 'Port is DOWN', rx_power: -7 },
            { interface_name: 'GE1/0/6', severity: 'no_module', severity_reason: 'Optical module is not present', rx_power: null },
            {
              interface_name: 'gei-0/3/0/1',
              device_vendor: 'ZTE',
              severity: 'no_light',
              severity_reason: '设备未返回接收光功率',
              rx_power: null,
              rx_low_alarm: -28.2,
              rx_high_alarm: 0,
            },
          ],
          total: 7, page: 1, page_size: 50, total_pages: 1,
          source: { available: true, source: 'snapshot', collected_at: '', reason: null },
        })
      }
      if (section === 'lldp') {
        return Promise.resolve({
          items: [
            {
              local_interface: 'gei-0/3/0/2',
              neighbor_system_name: 'HZDT-TEST-AP',
              neighbor_interface: 'Ten-GigabitEthernet1/0/1',
              neighbor_ip: '192.0.2.26',
              pvid: 71,
              ttl: 228,
              port_description: 'Test AP uplink',
              association_status: 'matched',
            },
            { local_interface: 'GE1/0/2', association_status: 'unresolved' },
          ],
          total: 2, page: 1, page_size: 50, total_pages: 1,
          source: { available: true, source: 'snapshot', collected_at: '', reason: null },
        })
      }
      return Promise.resolve({
        items: [{
          name: 'gei-0/3/0/41',
          link_status: 'PHYSICAL_DOWN',
          admin_status: 'up',
          physical_status: 'down',
          protocol_status: 'down',
          media_type: 'optical',
          category: 'physical',
          port_status: 'hybrid',
          port_mode: 'hybrid',
          pvid: '71',
          native_vlan: '71',
          tagged_vlans: ['201'],
          untagged_vlans: [],
          vlan: 'Native/PVID 71；Tagged 201',
          pvid_source: 'show_running_config_switchvlan',
          pvid_verified: true,
          vlan_config_status: 'current',
        }],
        total: 1, page: 1, page_size: 50, total_pages: 1,
        source: { available: true, source: 'snapshot', collected_at: '', reason: null },
      })
    })
    const wrapper = await renderPanel()

    await wrapper.get('[data-testid="tab-interfaces"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('gei-0/3/0/41')
    expect(wrapper.text()).toContain('物理 Down')
    expect(wrapper.text()).toContain('Up')
    expect(wrapper.text()).toContain('Down')
    expect(wrapper.text()).toContain('光口')
    expect(wrapper.text()).toContain('物理接口')
    expect(wrapper.text()).toContain('Hybrid')
    expect(wrapper.text()).toContain('71')
    expect(wrapper.text()).toContain('Native/PVID 71；Tagged 201')
    expect(wrapper.text()).not.toContain('未启用')

    await wrapper.get('[data-testid="tab-optical"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('正常')
    expect(wrapper.text()).toContain('注意')
    expect(wrapper.text()).toContain('告警')
    expect(wrapper.text()).toContain('严重告警')
    expect(wrapper.text()).toContain('未检测到光模块')
    expect(wrapper.text()).toContain('接收功率低于告警低阈值')
    expect(wrapper.text()).toContain('设备未返回接收光功率')
    expect(wrapper.text()).not.toContain('接收功率缺失或不高于 -35 dBm')
    expect(wrapper.text()).toContain('Vendor raw reason')
    expect(wrapper.text()).not.toContain('接收功率高于维护正常线')
    expect(wrapper.text()).not.toContain('RX power is above maintenance normal line')
    expect(wrapper.text()).not.toContain('端口已断开')
    expect(wrapper.text()).not.toContain('Port is DOWN')
    const rxPowerCells = wrapper.findAll('.optical-rx-power')
    expect(rxPowerCells).toHaveLength(7)
    expect(rxPowerCells[0].classes()).toContain('optical-tone-normal')
    expect(rxPowerCells[1].classes()).toContain('optical-tone-warning')
    expect(rxPowerCells[2].classes()).toContain('optical-tone-danger')
    expect(rxPowerCells[3].classes()).toContain('optical-tone-danger')
    expect(rxPowerCells[4].classes()).toContain('optical-tone-normal')
    expect(rxPowerCells[5].classes()).toContain('optical-tone-neutral')
    expect(rxPowerCells[6].classes()).toContain('optical-tone-danger')

    await wrapper.get('[data-testid="tab-lldp"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('HZDT-TEST-AP')
    expect(wrapper.text()).toContain('Ten-GigabitEthernet1/0/1')
    expect(wrapper.text()).toContain('192.0.2.26')
    expect(wrapper.text()).toContain('Test AP uplink')
    expect(rxPowerCells[5].classes()).not.toContain('optical-tone-danger')

    wrapper.unmount()
  })

  it('colors trackside optical anomalies in business relations and keeps no-module neutral', async () => {
    mocks.getDeviceDetailSection.mockImplementation((_deviceUuid, section) => Promise.resolve(section === 'business'
      ? {
          items: [
            { association_type: 'trackside_ap', association_id: 'alarm', status: 'alarm', name: 'AP-01', trackside_ap: {} },
            { association_type: 'trackside_ap', association_id: 'warning', status: 'warning', name: 'AP-02', trackside_ap: {} },
            { association_type: 'trackside_ap', association_id: 'normal', status: 'normal', name: 'AP-03', trackside_ap: {} },
            { association_type: 'trackside_ap', association_id: 'no-module', status: 'no_module', name: null, trackside_ap: {} },
          ],
          total: 4, page: 1, page_size: 50, total_pages: 1,
          source: { available: true, source: 'snapshot', collected_at: '', reason: null },
        }
      : {
          items: [], total: 0, page: 1, page_size: 50, total_pages: 1,
          source: { available: true, source: 'snapshot', collected_at: '', reason: null },
        }))
    const wrapper = await renderPanel()

    await wrapper.get('[data-testid="tab-business"]').trigger('click')
    await flushPromises()

    const statusCells = wrapper.findAll('.business-optical-status')
    expect(statusCells).toHaveLength(4)
    expect(statusCells[0].text()).toBe('告警')
    expect(statusCells[0].classes()).toContain('optical-tone-danger')
    expect(statusCells[1].classes()).toContain('optical-tone-warning')
    expect(statusCells[2].classes()).toContain('optical-tone-normal')
    expect(statusCells[3].text()).toBe('无光模块')
    expect(statusCells[3].classes()).toContain('optical-tone-neutral')
    expect(statusCells[3].classes()).not.toContain('optical-tone-danger')
    wrapper.unmount()
  })

  it('submits a refresh task through the shared task window and cleans polling on unmount', async () => {
    const wrapper = await renderPanel()
    const refresh = wrapper.findAll('button').find((button) => button.text() === '刷新全部')
    expect(refresh).toBeTruthy()
    await refresh!.trigger('click')
    await flushPromises()
    expect(mocks.refreshDeviceDetails).toHaveBeenCalledWith('device-1')
    expect(mocks.routerPush).toHaveBeenCalledWith(expect.objectContaining({ name: 'tasks' }))
    wrapper.unmount()
    expect(mocks.taskStore?.releasePolling).toHaveBeenCalledWith('device-detail-panel')
  })

  it('enables overview and full refresh for a wireless controller with an executable profile', async () => {
    const wirelessControllerOverview = {
      ...overview,
      name: '251-无线控制器-主',
      device_type: 'AC',
      platform_facts: { ...overview.platform_facts, role: 'wireless_controller' },
      command_profile: {
        ...overview.command_profile,
        profile_id: 'h3c.comware.wireless_controller.generic.device-inventory.v1',
      },
    }
    const wrapper = mount(DeviceDetailPanel, {
      props: { deviceUuid: 'wireless-controller-1', mode: 'page', overview: wirelessControllerOverview },
      global: { directives: { loading: () => undefined }, stubs: elementStubs },
    })
    await flushPromises()

    const refreshAll = wrapper.findAll('button').find((button) => button.text() === '刷新全部')
    const refreshOverview = wrapper.findAll('button').find((button) => button.text() === '刷新概览')
    expect(refreshAll?.attributes('disabled')).toBeUndefined()
    expect(refreshOverview?.attributes('disabled')).toBeUndefined()
    await refreshAll!.trigger('click')
    await flushPromises()
    expect(mocks.refreshDeviceDetails).toHaveBeenCalledWith('wireless-controller-1')
    wrapper.unmount()
  })

  it('fails closed when the backend command profile is not executable', async () => {
    const unsupportedOverview = {
      ...overview,
      command_profile: { ...overview.command_profile, executable: false, reason: '缺少可执行命令画像' },
    }
    const wrapper = mount(DeviceDetailPanel, {
      props: { deviceUuid: 'device-1', mode: 'page', overview: unsupportedOverview },
      global: { directives: { loading: () => undefined }, stubs: elementStubs },
    })
    await flushPromises()
    const refresh = wrapper.findAll('button').find((button) => button.text() === '刷新全部')
    expect(refresh).toBeTruthy()
    expect(refresh!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('缺少可执行命令画像')
    await refresh!.trigger('click')
    expect(mocks.refreshDeviceDetails).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps task submission success separate from task refresh and window failures', async () => {
    mocks.taskStore!.refresh.mockRejectedValueOnce(new Error('task store unavailable'))
    mocks.routerPush.mockRejectedValueOnce(new Error('task window unavailable'))
    const wrapper = await renderPanel()
    const refresh = wrapper.findAll('button').find((button) => button.text() === '刷新全部')
    await refresh!.trigger('click')
    await flushPromises()
    expect(mocks.refreshDeviceDetails).toHaveBeenCalledWith('device-1')
    expect(mocks.messages.warning).toHaveBeenCalledWith('任务已提交，但任务状态刷新失败；任务中心打开失败')
    expect(mocks.messages.success).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('reloads overview and loaded sections after a refresh task reaches a terminal status', async () => {
    const wrapper = await renderPanel(false)
    await wrapper.get('[data-testid="tab-interfaces"]').trigger('click')
    await flushPromises()
    mocks.taskStore!.tasks = [{ id: 'refresh-1', type: 'device.inventory.collect', module: 'devices', status: 'PENDING' }]
    const refresh = wrapper.findAll('button').find((button) => button.text() === '刷新全部')
    await refresh!.trigger('click')
    await flushPromises()
    const overviewCallsBeforeTerminal = mocks.getDeviceOverview.mock.calls.length
    mocks.taskStore!.tasks = [{ id: 'refresh-1', type: 'device.inventory.collect', module: 'devices', status: 'COMPLETED' }]
    await flushPromises()
    expect(mocks.getDeviceOverview.mock.calls.length).toBeGreaterThan(overviewCallsBeforeTerminal)
    expect(mocks.getDeviceDetailSection.mock.calls.length).toBeGreaterThan(1)
    wrapper.unmount()
  })

  it('ignores a stale section response after the device UUID changes', async () => {
    let resolveStale!: (value: unknown) => void
    mocks.getDeviceDetailSection.mockImplementationOnce(() => new Promise((resolve) => { resolveStale = resolve }))
    const wrapper = await renderPanel(false)
    await wrapper.get('[data-testid="tab-interfaces"]').trigger('click')
    await wrapper.setProps({ deviceUuid: 'device-2' })
    await flushPromises()
    resolveStale({ items: [{ name: 'stale-interface' }], total: 1, page: 1, page_size: 50, total_pages: 1, source: { available: true, source: 'snapshot', collected_at: null, reason: null } })
    await flushPromises()
    expect(mocks.getDeviceOverview).toHaveBeenLastCalledWith('device-2')
    wrapper.unmount()
  })

})
