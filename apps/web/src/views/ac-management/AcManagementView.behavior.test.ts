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
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: mocks.routerPush }),
}))
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))
vi.mock('../../platform/runtime', () => ({
  getRuntimeConfig: () => ({ hostType: 'electron' }),
  getPlatformAdapter: () => ({ openExternalUrl: mocks.openExternalUrl }),
}))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: mocks.confirm }) }))
vi.mock('../../stores/acManagement', () => ({ useAcManagementStore: () => mocks.store }))
vi.mock('../../stores/tasks', () => ({ useTaskStore: () => mocks.taskStore }))

import AcManagementView from './AcManagementView.vue'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, slots.default?.())
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
  props: { tableId: { type: String, default: '' } },
  setup(props) {
    return () => h('div', { class: 'nc-data-table', 'data-table-id': props.tableId })
  },
})

const stubs: Record<string, Component> = {
  ElAlert: alertStub,
  ElButton: buttonStub,
  ElCheckbox: passthrough,
  ElDescriptions: passthrough,
  ElDescriptionsItem: descriptionsItemStub,
  ElDrawer: passthrough,
  ElEmpty: passthrough,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: passthrough,
  ElOption: optionStub,
  ElPagination: passthrough,
  ElSelect: passthrough,
  ElTabPane: passthrough,
  ElTabs: passthrough,
  ElTag: tagStub,
  ElTooltip: passthrough,
  NcDataTable: dataTableStub,
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
    startFitApDelete: vi.fn(),
    startFitApMetadataImport: vi.fn(),
    startFitApMetadataSave: vi.fn(),
  })
}

function mountView(selectedOptical = optical()): VueWrapper {
  mocks.store = makeStore(selectedOptical)
  mocks.taskStore = reactive({ tasks: [], acquirePolling: vi.fn(), releasePolling: vi.fn() })
  return mount(AcManagementView, {
    global: {
      stubs,
      directives: { loading: () => undefined },
    },
  })
}

describe('AC Management optical detail behavior', () => {
  beforeEach(() => {
    mocks.routerPush.mockReset()
    mocks.confirm.mockReset()
    mocks.openExternalUrl.mockReset()
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
    expect(threshold.text()).toContain('一般告警')
    expect(threshold.classes()).toContain('optical-value-danger')
    expect(wrapper.find('[data-testid="optical-judgement"]').text()).toBe('异常')
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
})
