// @vitest-environment happy-dom

import { defineComponent, h, useAttrs, type Component } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  deleteGroundArchive: vi.fn(),
  getGroundArchive: vi.fn(),
  getGroundProfile: vi.fn(),
  getGroundStatus: vi.fn(),
  getGroundTrain: vi.fn(),
  groundArchiveSummaryDownloadRequest: vi.fn(),
  listGroundArchives: vi.fn(),
  getGroundHealth: vi.fn(),
  listGroundDeepCollections: vi.fn(),
  listGroundPingTargets: vi.fn(),
  listGroundTimeline: vi.fn(),
  listGroundTrains: vi.fn(),
  requestGroundConfigCheck: vi.fn(),
  openGroundArchiveDirectory: vi.fn(),
  pauseGroundRun: vi.fn(),
  resumeGroundRun: vi.fn(),
  saveGroundProfile: vi.fn(),
  setGroundTrainPriority: vi.fn(),
  startGroundRun: vi.fn(),
  stopAndArchiveGroundRun: vi.fn(),
  stopGroundRun: vi.fn(),
  saveGroundTrainPolicy: vi.fn(),
  syncGroundInventory: vi.fn(),
  checkGroundUdpPort: vi.fn(),
  listLocalIpv4Addresses: vi.fn(),
  recommendLocalSourceIp: vi.fn(),
  getGroundPingSeries: vi.fn(),
  getLatestGroundOperation: vi.fn(),
  listGroundSyslogRecords: vi.fn(),
}))

vi.mock('../../api/groundUnattended', () => api)
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: vi.fn() }))
vi.mock('../../components/ground-unattended/GroundPingChart.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent(() => () => h('div', { class: 'ground-ping-chart' })) }
})
vi.mock('../../components/table', async () => {
  const { defineComponent, h } = await import('vue')
  return { NcDataTable: defineComponent(() => () => h('div', { class: 'nc-data-table' })) }
})

import GroundUnattendedView from './GroundUnattendedView.vue'

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, slots.default?.())
  },
})

const alertStub = defineComponent({
  props: { title: { type: String, default: '' }, description: { type: String, default: '' } },
  setup(props) {
    return () => h('div', { class: 'el-alert' }, `${props.title} ${props.description}`)
  },
})

const emptyStub = defineComponent({
  props: { description: { type: String, default: '' } },
  setup(props, { slots }) {
    return () => h('div', { class: 'el-empty' }, [props.description, slots.default?.()])
  },
})

const stubs: Record<string, Component> = {
  ElAlert: alertStub,
  ElButton: passthrough,
  ElCheckbox: passthrough,
  ElDatePicker: passthrough,
  ElDescriptions: passthrough,
  ElDescriptionsItem: passthrough,
  ElDialog: passthrough,
  ElEmpty: emptyStub,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: passthrough,
  ElInputNumber: passthrough,
  ElOption: passthrough,
  ElPagination: passthrough,
  ElProgress: passthrough,
  ElSelect: passthrough,
  ElSwitch: passthrough,
  ElTabPane: passthrough,
  ElTable: passthrough,
  ElTableColumn: passthrough,
  ElTabs: passthrough,
  ElTag: passthrough,
}

function profile() {
  return {
    site_id: 'line-12', enabled: false, schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: 'Asia/Shanghai',
    ac_poll_interval_seconds: 10, stationary_exclusion_minutes: 10, ac_stale_grace_seconds: 120,
    ac_ping_correlation_tolerance_seconds: 15, ap_switch_before_seconds: 5, ap_switch_after_seconds: 5,
    max_active_trains: 2, max_active_mrs: 4, max_starting_mrs: 2, max_finalizing_mrs: 2,
    deep_collection_master_enabled: true,
    fleet_ping_interval_ms: 1000, fleet_ping_timeout_ms: 4000, fleet_ping_packet_size: 64, fleet_ping_shard_size: 12, fleet_ping_warmup_seconds: 10,
    udp_listen_host: '0.0.0.0', udp_listen_port: 5514, udp_queue_capacity: 20000, raw_flush_interval_seconds: 1, raw_flush_record_count: 100,
    event_batch_size: 100, event_batch_interval_seconds: 1, boot_time_tolerance_seconds: 120, config_check_cooldown_seconds: 1800,
    syslog_server_ip: '10.8.0.4', syslog_server_port: 5514, ping_raw_retention_days: 30, syslog_raw_retention_days: 30,
    allow_external_syslog_address: false,
    minimum_valid_collection_minutes: 10, preferred_collection_minutes: 20, maximum_collection_minutes: 30,
    start_jitter_seconds: 3, start_batch_size: 1, detail_retention_days: 30, summary_retention_days: 180,
    storage_warning_free_gb: 5, storage_critical_free_gb: 1, created_at: '', updated_at: '',
  }
}

function status() {
  return {
    site_id: 'line-12', enabled: false, state: 'DISABLED', paused: false, run_id: '', run_date: '', actual_started_at: '', actual_ended_at: '',
    schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: 'Asia/Shanghai', running_mode: 'STANDARD',
    next_start_at: '', next_end_at: '', profile_effective_at: '', ac_last_updated_at: '', ac_freshness_status: 'NO_DATA',
    mainline_train_count: 0, ping_target_count: 0, active_deep_train_count: 0, covered_train_count: 0, incomplete_train_count: 0,
    disk_used_bytes: 0, disk_free_bytes: 0, disk_status: 'UNKNOWN', inventory_train_count: 0, syslog_active_mr_count: 0,
    config_abnormal_count: 0, data_quality_warning_count: 0, latest_archive_status: '', latest_archive_message: '', message: '', updated_at: '',
  }
}

function mountPage() {
  return mount(GroundUnattendedView, {
    global: { stubs, directives: { loading: {} } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getGroundStatus.mockResolvedValue(status())
  api.getGroundProfile.mockResolvedValue(profile())
  api.listGroundTrains.mockResolvedValue({ items: [], total: 0 })
  api.listGroundPingTargets.mockResolvedValue({ items: [], total: 0 })
  api.listGroundDeepCollections.mockResolvedValue({ items: [], total: 0 })
  api.listGroundTimeline.mockResolvedValue({ items: [], total: 0 })
  api.listGroundArchives.mockResolvedValue({ items: [], total: 0 })
  api.getGroundHealth.mockResolvedValue({ site_id: 'line-12', status: 'OK' })
  api.getLatestGroundOperation.mockResolvedValue(null)
  api.listLocalIpv4Addresses.mockResolvedValue({ items: [], total: 0, generated_at: '' })
})

describe('Ground unattended page loading behavior', () => {
  it('keeps the profile and settings visible when an optional request fails', async () => {
    api.getGroundHealth.mockRejectedValue(new Error('健康接口故障'))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('运行时间与 AC')
    expect(wrapper.text()).toContain('地面无人值守部分数据未加载')
    expect(wrapper.text()).toContain('系统健康：健康接口故障')
    expect(wrapper.text()).not.toContain('无人值守配置未加载')
    wrapper.unmount()
  })

  it('shows an actionable settings error instead of an empty pane when profile loading fails', async () => {
    api.getGroundProfile.mockRejectedValue(new Error('后台初始化失败'))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('无人值守配置未加载')
    expect(wrapper.text()).toContain('后台初始化失败')
    expect(wrapper.text()).toContain('重新加载配置')
    expect(wrapper.text()).not.toContain('运行时间与 AC')
    wrapper.unmount()
  })

  it('does not present a missing status response as disabled', async () => {
    api.getGroundStatus.mockRejectedValue(new Error('状态接口故障'))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('状态未加载')
    expect(wrapper.text()).toContain('运行时间与 AC')
    wrapper.unmount()
  })
})
