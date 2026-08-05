// @vitest-environment happy-dom

import { defineComponent, h, reactive, useAttrs, type Component } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  store: null as null | Record<string, unknown>,
  taskStore: null as null | Record<string, unknown>,
  confirm: vi.fn(),
  openExternalUrl: vi.fn(),
  hostType: 'electron',
  createActionPlan: vi.fn(),
  confirmActionPlan: vi.fn(),
  executeActionPlan: vi.fn(),
  getActionPlan: vi.fn(),
  getActionAudit: vi.fn(),
  getExternalTerminalOptions: vi.fn(),
  openExternalTerminal: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: mocks.routerPush }),
}))
vi.mock('../../platform/runtime', () => ({
  getRuntimeConfig: () => ({ hostType: mocks.hostType }),
  getPlatformAdapter: () => ({ openExternalUrl: mocks.openExternalUrl }),
}))
vi.mock('../../api/acWebParity', () => ({
  createAcActionPlan: mocks.createActionPlan,
  confirmAcActionPlan: mocks.confirmActionPlan,
  executeAcActionPlan: mocks.executeActionPlan,
  getAcActionPlan: mocks.getActionPlan,
  getAcActionAudit: mocks.getActionAudit,
  startAcOmniPeekPreview: vi.fn(),
  getAcOmniPeekPreview: vi.fn(),
  startAcOmniPeekExport: vi.fn(),
  getAcExternalTerminalOptions: mocks.getExternalTerminalOptions,
  openAcFitApExternalTerminal: mocks.openExternalTerminal,
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: mocks.confirm }) }))
vi.mock('../../stores/acManagement', () => ({ useAcManagementStore: () => mocks.store }))
vi.mock('../../stores/tasks', () => ({ useTaskStore: () => mocks.taskStore }))

import AcManagementView from './AcManagementView.vue'
import { resetWebFeaturesForTest, setWebFeaturesForTest } from '../../features'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, slots.default?.())
  },
})

const dialogStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, [slots.default?.(), slots.footer?.()])
  },
})

const buttonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  setup(_props, { slots, emit }) {
    const attrs = useAttrs()
    return () => h('button', { ...attrs, onClick: () => emit('click') }, slots.default?.())
  },
})

const descriptionsItemStub = defineComponent({
  props: { label: { type: String, default: '' } },
  setup(props, { slots }) {
    return () => h('div', { class: 'description-item', 'data-label': props.label }, [
      h('span', { class: 'description-label' }, props.label),
      slots.default?.(),
    ])
  },
})

const tagStub = defineComponent({
  inheritAttrs: false,
  props: { type: { type: String, default: 'info' } },
  setup(props, { slots }) {
    const attrs = useAttrs()
    return () => h('span', { ...attrs, class: ['el-tag', attrs.class], 'data-type': props.type }, slots.default?.())
  },
})

const alertStub = defineComponent({
  props: { title: { type: String, default: '' }, type: { type: String, default: 'info' } },
  setup(props, { slots }) {
    return () => h('div', { class: 'el-alert', 'data-type': props.type }, [props.title, slots.default?.()])
  },
})

const optionStub = defineComponent({
  props: { label: { type: String, default: '' } },
  setup(props) {
    return () => h('option', props.label)
  },
})

const dataTableStub = defineComponent({
  name: 'NcDataTable',
  props: { tableId: { type: String, default: '' }, contextMenuItems: { type: Array, default: () => [] } },
  setup(props) {
    return () => h('div', { class: 'nc-data-table', 'data-table-id': props.tableId, 'data-menu-count': props.contextMenuItems.length })
  },
})

const stubs: Record<string, Component> = {
  ElAlert: alertStub,
  ElButton: buttonStub,
  ElCheckbox: passthrough,
  ElDescriptions: passthrough,
  ElDescriptionsItem: descriptionsItemStub,
  ElDrawer: passthrough,
  ElDropdown: passthrough,
  ElDropdownItem: passthrough,
  ElDropdownMenu: passthrough,
  ElDialog: dialogStub,
  ElEmpty: passthrough,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: passthrough,
  ElInputNumber: passthrough,
  ElOption: optionStub,
  ElPagination: passthrough,
  ElSelect: passthrough,
  ElRadio: passthrough,
  ElRadioGroup: passthrough,
  ElTabPane: passthrough,
  ElTabs: passthrough,
  ElTag: tagStub,
  ElTooltip: passthrough,
  NcDataTable: dataTableStub,
  AcOmniPeekExportDialog: passthrough,
}

function optical(overrides: Record<string, unknown> = {}) {
  return {
    optical_status: 'warning',
    optical_severity: 'warning',
    raw_status: 'alarm',
    ap_rx_status: 'normal',
    switch_rx_status: 'alarm',
    tx_power_status: 'unknown',
    ap_offline_related: false,
    ap_online_status: 'online',
    data_freshness: 'fresh',
    is_current_anomaly: true,
    anomaly_reason: '检测到交换机侧收光一般告警：-19.75 dBm；AP 侧收光正常：-8.63 dBm。当前 AP 在线。',
    source_switch: '01-小洋江站1',
    source_interface: 'GE2/0/18',
    tx_power: '-6.13',
    rx_power: '-8.63',
    switch_rx_power: '-19.75',
    temperature: '',
    voltage: '',
    bias_current: '',
    threshold_status: '一般告警',
    error_summary: '',
    updated_at: '2026-07-22T08:21:44+08:00',
    ...overrides,
  }
}

function makeStore(selectedOptical = optical()) {
  return reactive({
    summary: {
      site_id: 'demo',
      acs: [{
        id: 'ac-1',
        name: '测试 AC',
        management_ip: '10.0.0.1',
        model: '',
        software_version: '',
        ap_total: 1,
        online_aps: 1,
        offline_aps: 0,
        unauthenticated_aps: 0,
        radio_total: 2,
        optical_anomalies: 1,
        updated_at: '',
        data_source: 'SQLite 已采集数据',
      }],
      ap_total: 1,
      online_aps: 1,
      offline_aps: 0,
      unauthenticated_aps: 0,
      radio_total: 2,
      optical_anomalies: 1,
      updated_at: '',
      message: '',
    },
    activeAc: {
      id: 'ac-1',
      name: '测试 AC',
      management_ip: '10.0.0.1',
      model: '',
      software_version: '',
      ap_total: 1,
      online_aps: 1,
      offline_aps: 0,
      unauthenticated_aps: 0,
      radio_total: 2,
      optical_anomalies: 1,
      updated_at: '',
      data_source: 'SQLite 已采集数据',
    },
    filters: {
      ac_id: 'ac-1',
      page: 1,
      page_size: 50,
      query: '',
      status: '',
      station: '',
      section: '',
      model: '',
      switch: '',
      optical_status: '',
      sort_by: 'topology',
      sort_order: 'asc',
    },
    filterOptions: {
      stations: ['小洋江站'],
      sections: ['小洋江-鄞州大道'],
      models: ['WA6522'],
      switches: ['01-小洋江站1'],
    },
    aps: [],
    total: 0,
    selected: {
      ap: {
        id: 'ap-1',
        ac_id: 'ac-1',
        ac_name: '测试 AC',
        name: 'bc5a-3457-7100',
        ip: '10.0.1.10',
        mac: 'bc5a-3457-7100',
        status: 'online',
        state_display: '运行',
        model: '',
        online_time: '',
        is_unauthenticated: false,
        radio1_status: '',
        radio2_status: '',
        radio1_channel: '',
        radio2_channel: '',
        radio1_power: '',
        radio2_power: '',
        station: '',
        station_source: 'empty',
        section: '',
        mileage: '',
        direction: '',
        location_note: '',
        switch_name: '01-小洋江站1',
        switch_interface: 'GE2/0/18',
        lldp_status: '',
        optical_status: 'warning',
        optical_severity: 'warning',
        optical_data_freshness: 'fresh',
        optical_is_current_anomaly: true,
        optical_rx_power: '-8.63',
        updated_at: '',
      },
      radios: [],
      lldp: {
        switch_name: '01-小洋江站1',
        switch_ip: '',
        interface_name: 'GE2/0/18',
        lldp_neighbor: '',
        port_status: 'UP',
        vlan: '',
        optical_module_status: '',
        match_status: '',
        source: '',
        updated_at: '',
      },
      optical: selectedOptical,
      connection: { ip_address: '', state: '', connected_at: '', updated_at: '' },
    },
    snapshots: [],
    snapshotTotal: 0,
    snapshotPage: 1,
    snapshotPageSize: 30,
    snapshotType: '',
    configContent: null,
    configDiff: null,
    loading: false,
    detailLoading: false,
    configLoading: false,
    error: '',
    refreshTask: null,
    actionTask: null,
    refreshStarting: false,
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    manualRefresh: vi.fn(),
    setAcId: vi.fn(),
    applyFilters: vi.fn(),
    setPage: vi.fn(),
    setPageSize: vi.fn(),
    refreshSnapshots: vi.fn(),
    setSnapshotPage: vi.fn(),
    setSnapshotType: vi.fn(),
    selectAp: vi.fn(),
    loadConfig: vi.fn(),
    loadDiff: vi.fn(),
    loadMoreConfig: vi.fn(),
    startAcInfoRefresh: vi.fn(),
    startFitApRefresh: vi.fn(),
    startFitApDetailRefresh: vi.fn(),
    startOpticalRefresh: vi.fn(),
    startApOpticalRefresh: vi.fn(),
    startFitApDelete: vi.fn(),
    startFitApMetadataImport: vi.fn(),
    startFitApMetadataSave: vi.fn(),
    trackActionTask: vi.fn(),
  })
}

function mountView(selectedOptical = optical()): VueWrapper {
  mocks.store = makeStore(selectedOptical)
  mocks.taskStore = reactive({ tasks: [], acquirePolling: vi.fn(), releasePolling: vi.fn(), refresh: vi.fn() })
  return mount(AcManagementView, {
    global: {
      stubs,
      directives: { loading: () => undefined },
    },
  })
}

describe('AC Management optical detail behavior', () => {
  beforeEach(() => {
    setWebFeaturesForTest({
      'web.ac_dangerous_actions': { visible: true, enabled: true },
      'web.ac_fit_ap_external_terminal': { visible: true, enabled: true },
      'ac.omnipeek_name_table_export': { visible: true, enabled: true },
      'desktop.native_bridge': { visible: true, enabled: true },
    })
    mocks.routerPush.mockReset()
    mocks.confirm.mockReset()
    mocks.openExternalUrl.mockReset()
    mocks.hostType = 'electron'
    mocks.createActionPlan.mockReset()
    mocks.confirmActionPlan.mockReset()
    mocks.executeActionPlan.mockReset()
    mocks.getActionPlan.mockReset()
    mocks.getActionAudit.mockReset().mockResolvedValue({})
    mocks.getExternalTerminalOptions.mockReset()
    mocks.openExternalTerminal.mockReset()
  })

  it('renders formal AC actions and OmniPeek with explicit production feature states', () => {
    const wrapper = mountView()

    expect(wrapper.text()).toContain('一键固化新上线 AP')
    expect(wrapper.text()).toContain('一键开启 AP 远程登入')
    expect(wrapper.text()).toContain('导出 OmniPeek 名称表')
    expect(wrapper.find('[data-table-id="ac-fit-ap-resources"]').attributes('data-menu-count')).toBe('5')
    wrapper.unmount()
  })

  it('renders AC content without the legacy task banner and keeps refresh submission actions', async () => {
    const wrapper = mountView()

    expect(wrapper.text()).not.toContain('AC 任务 · 运行中')
    expect(wrapper.text()).not.toContain('打开任务中心')
    expect(wrapper.find('.task-summary').exists()).toBe(false)
    expect(wrapper.find('[data-table-id="ac-fit-ap-resources"]').exists()).toBe(true)

    await wrapper.findAll('button').find((button) => button.text().includes('更新 AC 信息'))!.trigger('click')
    await wrapper.findAll('button').find((button) => button.text().includes('更新 FIT-AP 资源'))!.trigger('click')

    expect(mocks.store!.startAcInfoRefresh).toHaveBeenCalledOnce()
    expect(mocks.store!.startFitApRefresh).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('renders generated FIT-AP resource filter options', () => {
    const wrapper = mountView()

    expect(wrapper.text()).toContain('小洋江站')
    expect(wrapper.text()).toContain('小洋江-鄞州大道')
    expect(wrapper.text()).toContain('WA6522')
    expect(wrapper.text()).toContain('01-小洋江站1')
    wrapper.unmount()
  })

  it('shows a preserved AP MAC independently from an offline AP address', async () => {
    const wrapper = mountView()
    Object.assign((mocks.store!.selected as Record<string, Record<string, unknown>>).ap, {
      ip: '',
      mac: 'bc5a-3457-b5e0',
      status: 'offline',
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.detail-heading p').text()).toBe('-- · bc5a-3457-b5e0')
    expect(wrapper.find('.detail-heading .el-tag').text()).toBe('离线')
    wrapper.unmount()
  })

  it('keeps external terminal enabled in Electron and disabled with a reason in Browser mode', () => {
    const wrapper = mountView()
    const menu = wrapper.findComponent(dataTableStub).props('contextMenuItems') as Array<Record<string, unknown>>
    const external = menu.find((item) => item.key === 'external-terminal')!
    const row = { id: 'ap-1', name: 'AP-1', ip: '10.0.0.2', status: 'online' }

    expect((external.disabled as (context: unknown) => boolean)({ row })).toBe(false)
    mocks.hostType = 'browser'
    const browserWrapper = mountView()
    const browserMenu = browserWrapper.findComponent(dataTableStub).props('contextMenuItems') as Array<Record<string, unknown>>
    const browserExternal = browserMenu.find((item) => item.key === 'external-terminal')!
    expect((browserExternal.disabled as (context: unknown) => boolean)({ row })).toBe(true)
    expect((browserExternal.disabledReason as (context: unknown) => string)({ row })).toContain('仅桌面版')
    wrapper.unmount()
    browserWrapper.unmount()
    resetWebFeaturesForTest()
  })

  it('does not render or call the removed FIT-AP remote login profile flow', async () => {
    mocks.getExternalTerminalOptions.mockResolvedValue({
      default_terminal_type: 'securecrt',
      options: [{ terminal_type: 'securecrt', label: 'SecureCRT' }],
    })
    const legacyMissingCode = ['AP', 'CREDENTIALS', 'MISSING'].join('_')
    mocks.openExternalTerminal.mockRejectedValue(Object.assign(new Error('legacy missing credentials'), { code: legacyMissingCode }))
    const wrapper = mountView()
    const menu = wrapper.findComponent(dataTableStub).props('contextMenuItems') as Array<Record<string, unknown>>
    const external = menu.find((item) => item.key === 'external-terminal')!

    await (external.action as (context: unknown) => Promise<void>)({
      row: { id: 'ap-1', name: 'AP-1', ip: '10.0.0.2', status: 'online' },
    })
    await vi.waitFor(() => expect(mocks.openExternalTerminal).toHaveBeenCalledWith('ap-1', 'ac-1', 'securecrt'))

    expect(wrapper.text()).not.toContain(['配置 FIT-AP', '远程登录'].join(' '))
    expect(wrapper.text()).not.toContain(['保存并', '打开终端'].join(''))
    expect(wrapper.text()).not.toContain(['远程登录', '密码'].join(''))
    wrapper.unmount()
  })

  it('colors only the side that actually triggers the optical alarm', () => {
    const wrapper = mountView()

    const txPower = wrapper.find('[data-testid="optical-tx-power"]')
    const apRxPower = wrapper.find('[data-testid="optical-ap-rx-power"]')
    const switchRxPower = wrapper.find('[data-testid="optical-switch-rx-power"]')
    const threshold = wrapper.find('[data-testid="optical-threshold-status"]')

    expect(txPower.text()).toBe('-6.13 dBm')
    expect(txPower.classes()).toContain('optical-value-muted')
    expect(txPower.classes()).not.toContain('optical-value-danger')
    expect(apRxPower.text()).toBe('-8.63 dBm')
    expect(apRxPower.classes()).toContain('optical-value-normal')
    expect(apRxPower.classes()).not.toContain('optical-value-danger')
    expect(switchRxPower.text()).toBe('-19.75 dBm')
    expect(switchRxPower.classes()).toContain('optical-value-danger')
    expect(threshold.text()).toContain('光衰大')
    expect(threshold.classes()).toContain('optical-value-danger')
    expect(wrapper.find('[data-testid="optical-judgement"]').text()).toBe('异常')
    wrapper.unmount()
  })

  it('lets low switch Rx override a stale backend normal status in the detail view', () => {
    const wrapper = mountView(optical({
      optical_status: 'normal',
      optical_severity: 'normal',
      raw_status: 'normal',
      ap_rx_status: 'normal',
      switch_rx_status: 'normal',
      tx_power_status: 'unknown',
      is_current_anomaly: false,
      anomaly_reason: '光衰结果正常',
      rx_power: '-7.72',
      switch_rx_power: '-19.10',
      tx_power: '-19.10',
      threshold_status: '正常',
    }))

    expect(wrapper.get('[data-testid="optical-ap-rx-power"]').classes()).toContain('optical-value-normal')
    expect(wrapper.get('[data-testid="optical-switch-rx-power"]').classes()).toContain('optical-value-danger')
    expect(wrapper.get('[data-testid="optical-tx-power"]').classes()).toContain('optical-value-muted')
    expect(wrapper.get('[data-testid="optical-threshold-status"]').text()).toContain('光衰大')
    expect(wrapper.get('[data-testid="optical-judgement"]').text()).toBe('异常')
    expect(wrapper.text()).toContain('交换机侧收光异常：-19.10 dBm，低于 -13.90 dBm')
    expect(wrapper.text()).toContain('严重告警')
    wrapper.unmount()
  })

  it('uses stale tone instead of current danger when data is expired', () => {
    const wrapper = mountView(optical({ data_freshness: 'stale', is_current_anomaly: false }))
    const switchRxPower = wrapper.find('[data-testid="optical-switch-rx-power"]')

    expect(switchRxPower.classes()).toContain('optical-value-stale')
    expect(switchRxPower.classes()).not.toContain('optical-value-danger')
    expect(wrapper.find('[data-testid="optical-judgement"]').text()).toBe('数据已过期')
    wrapper.unmount()
  })

  it('does not append dBm to empty optical values', () => {
    const wrapper = mountView(optical({ rx_power: '', ap_rx_status: 'unknown' }))
    const apRxPower = wrapper.find('[data-testid="optical-ap-rx-power"]')

    expect(apRxPower.text()).toBe('--')
    expect(apRxPower.text()).not.toContain('dBm')
    expect(apRxPower.classes()).toContain('optical-value-muted')
    wrapper.unmount()
  })

  it('previews fixed commands and never executes before explicit confirmation', async () => {
    const plan = {
      plan_id: 'plan-1', target_id: 'ac-1', action_id: 'persist_auto_ap', action_label: '固化新 AP',
      plan_digest: 'digest', confirm_token: 'secret-token', expires_at: Date.now() + 60_000,
      status: 'PREVIEW', command_summary: ['system-view', 'wlan auto-ap persistent all', 'save force', 'return', 'quit'], task_id: '',
    }
    mocks.createActionPlan.mockResolvedValue(plan)
    mocks.confirmActionPlan.mockResolvedValue({ ...plan, status: 'CONFIRMED' })
    mocks.executeActionPlan.mockResolvedValue({ ...plan, status: 'EXECUTING', task_id: 'action-task-1' })
    const wrapper = mountView()

    await wrapper.findAll('button').find((button) => button.text().includes('一键固化新上线 AP'))!.trigger('click')
    await wrapper.vm.$nextTick()

    expect(mocks.createActionPlan).toHaveBeenCalledWith('ac-1', 'persist_auto_ap')
    expect(wrapper.text()).toContain('wlan auto-ap persistent all')
    expect(wrapper.text()).not.toContain('secret-token')
    expect(mocks.executeActionPlan).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text().includes('确认并执行真实配置'))!.trigger('click')
    await vi.waitFor(() => expect(mocks.executeActionPlan).toHaveBeenCalledWith('plan-1'))
    expect((mocks.store!.trackActionTask as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith('action-task-1')
    wrapper.unmount()
  })
})
