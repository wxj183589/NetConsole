// @vitest-environment happy-dom

import { defineComponent, h, useAttrs, type Component } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  deleteGroundArchive: vi.fn(),
  getGroundArchive: vi.fn(),
  getGroundProfile: vi.fn(),
  getGroundStatus: vi.fn(),
  getGroundTrain: vi.fn(),
  groundArchiveSummaryDownloadRequest: vi.fn(),
  groundArchiveZipDownloadRequest: vi.fn(),
  listGroundArchives: vi.fn(),
  getGroundHealth: vi.fn(),
  getActiveGroundOperation: vi.fn(),
  getGroundOperation: vi.fn(),
  getGroundPingSeries: vi.fn(),
  getGroundPingSeriesIncremental: vi.fn(),
  getGroundSyslogTransportStatus: vi.fn(),
  listGroundDeepCollections: vi.fn(),
  listGroundPingTargets: vi.fn(),
  listGroundRuns: vi.fn(),
  listGroundSyslogRecords: vi.fn(),
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
  probeGroundSyslogTransportState: vi.fn(),
  getLatestGroundOperation: vi.fn(),
  verifyGroundArchive: vi.fn(),
  downloadBackendResource: vi.fn(),
}))

vi.mock('../../api/groundUnattended', () => api)
vi.mock('../../api/client', () => ({
  ApiRequestError: class ApiRequestError extends Error {
    constructor(
      message: string,
      readonly status: number,
      readonly code = '',
      readonly details: Record<string, unknown> = {},
    ) {
      super(message)
      this.name = 'ApiRequestError'
    }
  },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: api.downloadBackendResource }))
vi.mock('../../components/ground-unattended/GroundPingChart.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent(() => () => h('div', { class: 'ground-ping-chart' })) }
})
vi.mock('../../components/table', async () => {
  const { defineComponent, h } = await import('vue')
  return { NcDataTable: defineComponent(() => () => h('div', { class: 'nc-data-table' })) }
})
vi.mock('../../components/workspace/NcFloatingWindow.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      props: { modelValue: Boolean },
      emits: ['update:modelValue', 'close'],
      setup(props, { slots }) {
        return () => props.modelValue ? h('section', { class: 'nc-floating-window' }, slots.default?.()) : null
      },
    }),
  }
})

import GroundUnattendedView from './GroundUnattendedView.vue'
import { ApiRequestError } from '../../api/client'

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

const tableColumnStub = defineComponent({
  setup() {
    return () => h('div')
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
  ElSkeleton: passthrough,
  ElSelect: passthrough,
  ElSwitch: passthrough,
  ElTabPane: passthrough,
  ElTable: passthrough,
  ElTableColumn: tableColumnStub,
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
    service_state: 'DISABLED', active_run_id: '', active_run_state: '', active_run_date: '', active_run_started_at: '',
    latest_run_id: '', latest_run_state: '', latest_run_date: '', latest_run_started_at: '', latest_run_ended_at: '',
    active_operation_id: '', active_operation_state: '', latest_operation_id: '', latest_operation_state: '',
  }
}

function pingTarget(overrides: Record<string, unknown> = {}) {
  return {
    run_id: 'run-active',
    run_date: '2026-07-30',
    target_ip: '192.0.2.10',
    train_id: 'train-1',
    train_no: '01',
    mr_id: 'mr-ct',
    mr_name: '01-MR-CT',
    mr_position_code: 'CT',
    started_at: '',
    updated_at: '',
    shard_id: 'shard-1',
    raw_sample_count: 1,
    effective_sample_count: 1,
    warmup_ignored_count: 0,
    sent_count: 1,
    success_count: 1,
    loss_count: 0,
    loss_rate_percent: 0,
    min_rtt_ms: 2,
    avg_rtt_ms: 2,
    max_rtt_ms: 2,
    continuous_loss_max_count: 0,
    continuous_loss_max_seconds: 0,
    current_ap_name: 'AP01',
    station: '站点A',
    section: '站点A-站点B',
    first_sample_at: '2026-07-30T08:00:00+08:00',
    last_sample_at: '2026-07-30T08:00:02+08:00',
    active_raw_file_count: 1,
    archived_raw_file_count: 0,
    raw_file_available: true,
    archive_available: false,
    data_source: 'ACTIVE',
    data_availability: 'ACTIVE_RAW',
    ...overrides,
  }
}

function pingSeries(points: Array<Record<string, unknown>>, overrides: Record<string, unknown> = {}) {
  const effective = points.filter((point) => !point.warmup_ignored)
  const successes = effective.filter((point) => point.ok)
  const rtts = successes.flatMap((point) => (
    typeof point.rtt_ms === 'number' ? [point.rtt_ms] : []
  ))
  return {
    raw_sample_count: points.length,
    effective_sample_count: effective.length,
    ignored_sample_count: points.length - effective.length,
    success_count: successes.length,
    loss_count: effective.length - successes.length,
    rtt_sample_count: rtts.length,
    rtt_sum_ms: rtts.reduce((total, rtt) => total + rtt, 0),
    current_rtt_ms: rtts.at(-1) ?? null,
    average_rtt_ms: rtts.length
      ? rtts.reduce((total, rtt) => total + rtt, 0) / rtts.length
      : null,
    max_rtt_ms: rtts.length ? Math.max(...rtts) : null,
    points,
    loss_windows: [],
    ap_transitions: [],
    position_segments: [],
    diagnostics: {
      requested_run_id: 'run-active',
      resolved_start_time: '',
      resolved_end_time: '',
      source_kind: 'ACTIVE',
      data_availability: 'ACTIVE_RAW',
      files_considered: 1,
      files_scanned: 1,
      records_scanned: points.length,
      bytes_scanned: 100,
      malformed_record_count: 0,
      duplicate_record_count: 0,
      truncated: false,
      legacy_archive: false,
      no_data_reason: '',
    },
    next_cursor: 'cursor-1',
    latest_sequence: Number(points.at(-1)?.seq ?? 0),
    latest_timestamp: String(points.at(-1)?.ts ?? ''),
    server_time: '2026-07-30T08:00:03+08:00',
    active: true,
    target_state: 'RUNNING',
    has_more: false,
    ...overrides,
  }
}

function pingPoint(sampleId: string, ts: string, seq: number) {
  return {
    sample_id: sampleId,
    ts,
    seq,
    target_ip: '192.0.2.10',
    train_id: 'train-1',
    train_no: '01',
    mr_id: 'mr-ct',
    mr_name: '01-MR-CT',
    mr_position_code: 'CT',
    ok: true,
    rtt_ms: 2,
    warmup_ignored: false,
    position_quality: 'MATCHED',
    current_ap_name: 'AP01',
    station: '站点A',
    section: '站点A-站点B',
    data_source: 'ACTIVE',
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
  api.getGroundSyslogTransportStatus.mockResolvedValue({
    configured_return_ip: '10.8.0.4',
    configured_return_port: 5514,
    return_address_status: 'LOCAL_ADDRESS',
    return_address_is_local: true,
    allow_external_address: false,
    listen_host: '0.0.0.0',
    listen_port: 5514,
    receiver_running: false,
    receiver_state: 'STOPPED',
    actual_listen_address: '',
    port_state: 'AVAILABLE',
    port_message: '端口空闲',
    ports_match: true,
    target_port_message: '目标端口与本地监听一致',
    last_received_at: '',
    received_count: 0,
    active_mr_count: 0,
    unidentified_count: 0,
    identity_conflict_count: 0,
    queue_length: 0,
    queue_capacity: 20_000,
    dropped_count: 0,
    recommended_local_ip: '10.8.0.4',
    recommended_adapter_name: '板载',
    checked_at: '',
  })
  api.getActiveGroundOperation.mockResolvedValue(null)
  api.getGroundOperation.mockResolvedValue(null)
  api.getLatestGroundOperation.mockResolvedValue(null)
  api.listGroundRuns.mockResolvedValue({ items: [], total: 0 })
  api.listGroundSyslogRecords.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  api.listLocalIpv4Addresses.mockResolvedValue({ items: [], total: 0, generated_at: '' })
  api.groundArchiveSummaryDownloadRequest.mockReturnValue({
    apiPath: '/api/rail-transit/ground-unattended/artifacts/archive-1/summary-download',
    suggestedName: '2026-07-30_ground_unattended_summary.json',
  })
  api.groundArchiveZipDownloadRequest.mockReturnValue({
    apiPath: '/api/rail-transit/ground-unattended/artifacts/archive-1/download',
    suggestedName: '2026-07-30_ground_unattended.zip',
    expectedSizeBytes: 1024,
    expectedSha256: 'a'.repeat(64),
  })
  api.downloadBackendResource.mockResolvedValue({ status: 'cancelled' })
  api.probeGroundSyslogTransportState.mockImplementation(async (reason: unknown) => ({
    code: reason instanceof ApiRequestError ? reason.code : 'UNKNOWN_ERROR',
    requestId: reason instanceof ApiRequestError ? String(reason.details.request_id || '') : '',
    backendState: reason instanceof ApiRequestError && reason.status > 0 ? 'ONLINE' : 'UNKNOWN',
  }))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Ground unattended page loading behavior', () => {
  it('shows NOT_LOCAL Transport status, blocks start, and does not overwrite the saved address', async () => {
    api.getGroundProfile.mockResolvedValue({ ...profile(), enabled: true, syslog_server_ip: '10.8.0.3' })
    api.getGroundSyslogTransportStatus.mockResolvedValue({
      ...(await api.getGroundSyslogTransportStatus()),
      configured_return_ip: '10.8.0.3',
      configured_return_port: 514,
      return_address_status: 'NOT_LOCAL',
      return_address_is_local: false,
      recommended_local_ip: '10.0.0.24',
      recommended_adapter_name: '板载',
      port_state: 'AVAILABLE',
      target_port_message: '目标为外部/NAT 地址，本机监听端口状态不适用',
    })

    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      profile: { syslog_server_ip: string }
      startBlockedReason: string
    }

    expect(wrapper.text()).toContain('10.8.0.3:514 当前不属于本机')
    expect(wrapper.text()).toContain('10.0.0.24')
    expect(wrapper.text()).toContain('仅展示，不自动覆盖')
    expect(view.profile.syslog_server_ip).toBe('10.8.0.3')
    expect(view.startBlockedReason).toContain('当前不属于本机')
    wrapper.unmount()
  })

  it('merges incremental Ping samples without duplicates and sorts late samples', async () => {
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
    })
    api.listGroundRuns.mockResolvedValue({
      items: [{ run_id: 'run-active', run_date: '2026-07-30', state: 'RUNNING' }],
      total: 1,
    })
    const second = pingPoint('sample-2', '2026-07-30T08:00:02+08:00', 2)
    api.getGroundPingSeries.mockResolvedValue(pingSeries([second], {
      position_segments: [{
        started_at: '2026-07-30T08:00:02+08:00',
        target_ip: '192.0.2.10',
        current_ap_identity: 'ap-a',
        current_ap_name: 'AP01',
        station: '站点A',
        section: '站点A-站点B',
        position_quality: 'MATCHED',
      }],
    }))
    api.getGroundPingSeriesIncremental.mockResolvedValue(pingSeries([
      second,
      pingPoint('sample-late', '2026-07-30T08:00:01.500+08:00', 3),
      pingPoint('sample-3', '2026-07-30T08:00:03+08:00', 4),
    ], {
      raw_sample_count: 3,
      effective_sample_count: 3,
      next_cursor: 'cursor-2',
      latest_sequence: 4,
      latest_timestamp: '2026-07-30T08:00:03+08:00',
      position_segments: [{
        started_at: '2026-07-30T08:00:01.500+08:00',
        target_ip: '192.0.2.10',
        current_ap_identity: 'ap-a',
        current_ap_name: 'AP01',
        station: '站点A',
        section: '站点A-站点B',
        position_quality: 'MATCHED',
      }, {
        started_at: '2026-07-30T08:00:03+08:00',
        target_ip: '192.0.2.10',
        current_ap_identity: 'ap-b',
        current_ap_name: 'AP02',
        station: '站点B',
        section: '站点A-站点B',
        position_quality: 'MATCHED',
      }],
    }))
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      pingSeries: {
        points: Array<{ sample_id: string }>
        raw_sample_count: number
        position_segments: Array<Record<string, unknown>>
      }
      showPingSeries: (row: ReturnType<typeof pingTarget>) => Promise<void>
      loadPingIncremental: () => Promise<void>
      pingPaused: boolean
    }

    await view.showPingSeries(pingTarget())
    await view.loadPingIncremental()
    expect(api.getGroundPingSeriesIncremental).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 'cursor-1', max_points: 200 }),
      expect.any(Object),
    )
    expect(view.pingSeries.points.map((point) => point.sample_id)).toEqual([
      'sample-late',
      'sample-2',
      'sample-3',
    ])
    expect(view.pingSeries.raw_sample_count).toBe(3)
    expect(view.pingSeries.position_segments.map((row) => row.current_ap_identity)).toEqual([
      'ap-a',
      'ap-b',
    ])

    view.pingPaused = true
    await view.loadPingIncremental()
    expect(api.getGroundPingSeriesIncremental).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('keeps one floating window while switching the selected Ping target', async () => {
    api.getGroundPingSeries.mockResolvedValue(pingSeries([
      pingPoint('sample-1', '2026-07-30T08:00:01+08:00', 1),
    ]))
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      activeTab: string
      pingWindowOpen: boolean
      selectedPingTarget: { target_ip: string }
      showPingSeries: (row: ReturnType<typeof pingTarget>) => Promise<void>
    }

    await view.showPingSeries(pingTarget({ target_ip: '192.0.2.10' }))
    await view.showPingSeries(pingTarget({
      target_ip: '192.0.2.11',
      mr_id: 'mr-cw',
      mr_name: '01-MR-CW',
      mr_position_code: 'CW',
    }))

    expect(view.pingWindowOpen).toBe(true)
    expect(view.selectedPingTarget.target_ip).toBe('192.0.2.11')
    expect(api.getGroundPingSeries).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('.nc-floating-window')).toHaveLength(1)

    view.activeTab = 'timeline'
    await flushPromises()
    expect(view.pingWindowOpen).toBe(true)
    expect(view.selectedPingTarget.target_ip).toBe('192.0.2.11')
    expect(wrapper.findAll('.nc-floating-window')).toHaveLength(1)
    wrapper.unmount()
  })

  it('caps the live Ping ring buffer and keeps duplicate statistics classified', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      mergePingSeries: (value: ReturnType<typeof pingSeries>, reset: boolean) => void
      pingSeries: {
        points: Array<{ sample_id: string }>
        raw_sample_count: number
        effective_sample_count: number
        ignored_sample_count: number
        success_count: number
        loss_count: number
        rtt_sample_count: number
        rtt_sum_ms: number
        average_rtt_ms: number | null
      }
      pingLiveStats: { success: number; loss: number; averageRtt: number | null }
    }
    const startedAt = Date.parse('2026-07-30T08:00:00+08:00')
    const initial = Array.from({ length: 3_000 }, (_, index) => (
      pingPoint(
        `sample-${index}`,
        new Date(startedAt + index * 1_000).toISOString(),
        index,
      )
    ))
    view.mergePingSeries(pingSeries(initial), true)
    const duplicateWarmup = {
      ...initial.at(-1)!,
      warmup_ignored: true,
    }
    const additions = [
      duplicateWarmup,
      pingPoint('sample-3000', new Date(startedAt + 3_000_000).toISOString(), 3_000),
      pingPoint('sample-3001', new Date(startedAt + 3_001_000).toISOString(), 3_001),
    ]
    view.mergePingSeries(pingSeries(additions, {
      raw_sample_count: 3,
      effective_sample_count: 2,
      ignored_sample_count: 1,
    }), false)

    expect(view.pingSeries.points).toHaveLength(3_000)
    expect(view.pingSeries.points[0]?.sample_id).toBe('sample-2')
    expect(view.pingSeries.points.at(-1)?.sample_id).toBe('sample-3001')
    expect(view.pingSeries.raw_sample_count).toBe(3_002)
    expect(view.pingSeries.effective_sample_count).toBe(3_002)
    expect(view.pingSeries.ignored_sample_count).toBe(0)
    expect(view.pingSeries.success_count).toBe(3_002)
    expect(view.pingSeries.loss_count).toBe(0)
    expect(view.pingSeries.rtt_sample_count).toBe(3_002)
    expect(view.pingSeries.rtt_sum_ms).toBe(6_004)
    expect(view.pingSeries.average_rtt_ms).toBe(2)
    expect(view.pingLiveStats).toMatchObject({
      success: 3_002,
      loss: 0,
      averageRtt: 2,
    })
    wrapper.unmount()
  })

  it('keeps initial Syslog failure local and confirms Backend remains online', async () => {
    const message = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    api.listGroundSyslogRecords.mockRejectedValue(
      new ApiRequestError(
        'Backend 连接中断，请重试。',
        0,
        'BACKEND_CONNECTION_INTERRUPTED',
      ),
    )
    api.probeGroundSyslogTransportState.mockResolvedValue({
      code: 'BACKEND_CONNECTION_INTERRUPTED',
      requestId: '',
      backendState: 'ONLINE',
    })
    const wrapper = mountPage()
    await flushPromises()

    ;(wrapper.vm as unknown as { activeTab: string }).activeTab = 'syslog'
    await flushPromises()

    expect(api.probeGroundSyslogTransportState).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('Syslog 日志暂时无法加载')
    expect(wrapper.text()).toContain('Syslog 查询连接中断，Backend 仍在线')
    expect(wrapper.text()).toContain('Backend 状态 在线')
    expect(message).not.toHaveBeenCalled()
    message.mockRestore()
    wrapper.unmount()
  })

  it('only reports Backend unreachable when the health recheck also fails', async () => {
    api.listGroundSyslogRecords.mockRejectedValue(
      new ApiRequestError(
        'Backend 连接中断，请重试。',
        0,
        'BACKEND_CONNECTION_INTERRUPTED',
      ),
    )
    api.probeGroundSyslogTransportState.mockResolvedValue({
      code: 'BACKEND_UNREACHABLE',
      requestId: '',
      backendState: 'OFFLINE',
    })
    const wrapper = mountPage()
    await flushPromises()

    ;(wrapper.vm as unknown as { activeTab: string }).activeTab = 'syslog'
    await flushPromises()

    expect(wrapper.text()).toContain('无法连接本机 Backend')
    expect(wrapper.text()).toContain('Backend 状态 离线')
    expect(wrapper.text()).toContain('BACKEND_UNREACHABLE')
    wrapper.unmount()
  })

  it('shows one Toast for a manual Syslog failure', async () => {
    const message = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    api.listGroundSyslogRecords.mockRejectedValue(
      new ApiRequestError('查询失败', 500, 'GROUND_SYSLOG_QUERY_FAILED'),
    )
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as { loadSyslog: (silent?: boolean) => Promise<void> }

    await view.loadSyslog(false)
    await flushPromises()

    expect(message).toHaveBeenCalledWith('Syslog 日志加载失败：查询失败')
    expect(message).toHaveBeenCalledTimes(1)
    message.mockRestore()
    wrapper.unmount()
  })

  it('reuses an in-flight Syslog request with the same fingerprint', async () => {
    let resolveRequest!: (value: { items: []; total: number; page: number; page_size: number }) => void
    api.listGroundSyslogRecords.mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as { loadSyslog: (silent?: boolean) => Promise<void> }

    const first = view.loadSyslog(true)
    const second = view.loadSyslog(true)
    await flushPromises()

    expect(api.listGroundSyslogRecords).toHaveBeenCalledOnce()
    resolveRequest({ items: [], total: 0, page: 1, page_size: 100 })
    await Promise.all([first, second])
    wrapper.unmount()
  })

  it('cancels changed Syslog parameters and ignores the old response', async () => {
    const requests: Array<{
      signal: AbortSignal
      resolve: (value: { items: Array<{ raw_text: string }>; total: number; page: number; page_size: number }) => void
    }> = []
    api.listGroundSyslogRecords.mockImplementation(
      (_params: unknown, options: { signal: AbortSignal }) => new Promise((resolve) => {
        requests.push({ signal: options.signal, resolve })
      }),
    )
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      loadSyslog: (silent?: boolean) => Promise<void>
      syslogFilter: { keyword: string }
      syslogRecords: Array<{ raw_text: string }>
    }

    void view.loadSyslog(true)
    await flushPromises()
    view.syslogFilter.keyword = 'new-filter'
    void view.loadSyslog(true)
    await flushPromises()

    expect(requests).toHaveLength(2)
    expect(requests[0].signal.aborted).toBe(true)
    requests[1].resolve({ items: [{ raw_text: 'new' }], total: 1, page: 1, page_size: 100 })
    await flushPromises()
    requests[0].resolve({ items: [{ raw_text: 'old' }], total: 1, page: 1, page_size: 100 })
    await flushPromises()
    expect(view.syslogRecords).toEqual([{ raw_text: 'new' }])
    wrapper.unmount()
  })

  it('clears the Syslog issue and reports recovery once', async () => {
    const success = vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    api.listGroundSyslogRecords
      .mockRejectedValueOnce(new ApiRequestError(
        'Backend 连接中断，请重试。',
        0,
        'BACKEND_CONNECTION_INTERRUPTED',
      ))
      .mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
    api.probeGroundSyslogTransportState.mockResolvedValue({
      code: 'BACKEND_CONNECTION_INTERRUPTED',
      requestId: '',
      backendState: 'ONLINE',
    })
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      activeTab: string
      loadSyslog: (silent?: boolean) => Promise<void>
    }
    view.activeTab = 'syslog'
    await flushPromises()
    expect(wrapper.text()).toContain('Syslog 日志暂时无法加载')

    await view.loadSyslog(true)
    await flushPromises()

    expect(wrapper.text()).not.toContain('Syslog 日志暂时无法加载')
    expect(success).toHaveBeenCalledWith('Syslog 日志已恢复')
    expect(success).toHaveBeenCalledTimes(1)
    success.mockRestore()
    wrapper.unmount()
  })

  it('turns historical Syslog auto-refresh off by default', async () => {
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
      latest_run_id: 'run-history',
      latest_run_state: 'COMPLETED',
    })
    api.listGroundRuns.mockResolvedValue({
      items: [
        { run_id: 'run-active', run_date: '2026-07-30', state: 'RUNNING' },
        { run_id: 'run-history', run_date: '2026-07-29', state: 'COMPLETED' },
      ],
      total: 2,
    })
    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      selectedRunId: string
      syslogAutoRefresh: boolean
    }

    view.selectedRunId = 'run-history'
    await flushPromises()

    expect(view.syslogAutoRefresh).toBe(false)
    wrapper.unmount()
  })

  it('saves existing archive artifacts only after an explicit user action', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.downloadBackendResource).not.toHaveBeenCalled()
    const view = wrapper.vm as unknown as {
      downloadArchiveSummary: (row: { archive_id: string; run_date: string }) => Promise<void>
      downloadArchiveZip: (row: { archive_id: string; run_date: string }) => Promise<void>
    }
    const archive = { archive_id: 'archive-1', run_date: '2026-07-30' }

    await view.downloadArchiveSummary(archive)
    await view.downloadArchiveZip(archive)

    expect(api.downloadBackendResource).toHaveBeenNthCalledWith(1, {
      apiPath: '/api/rail-transit/ground-unattended/artifacts/archive-1/summary-download',
      suggestedName: '2026-07-30_ground_unattended_summary.json',
    })
    expect(api.downloadBackendResource).toHaveBeenNthCalledWith(2, {
      apiPath: '/api/rail-transit/ground-unattended/artifacts/archive-1/download',
      suggestedName: '2026-07-30_ground_unattended.zip',
      expectedSizeBytes: 1024,
      expectedSha256: 'a'.repeat(64),
    })
    expect(api.downloadBackendResource.mock.calls.flat()).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ destinationPath: expect.anything() })]),
    )
    wrapper.unmount()
  })

  it('selects the active run even when the run list responds first', async () => {
    let resolveStatus!: (value: ReturnType<typeof status>) => void
    api.getGroundStatus.mockImplementation(() => new Promise((resolve) => {
      resolveStatus = resolve
    }))
    api.listGroundRuns.mockResolvedValue({
      items: [
        { run_id: 'run-recent', run_date: '2026-07-29', state: 'COMPLETED' },
        { run_id: 'run-active', run_date: '2026-07-30', state: 'RUNNING' },
      ],
      total: 2,
    })

    const wrapper = mountPage()
    await flushPromises()
    resolveStatus({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
      latest_run_id: 'run-recent',
      latest_run_state: 'COMPLETED',
    })
    await flushPromises()

    expect((wrapper.vm as unknown as { selectedRunId: string }).selectedRunId).toBe('run-active')
    wrapper.unmount()
  })

  it('cancels Ping detail loading and polling when the dialog closes', async () => {
    vi.useFakeTimers()
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
    })
    api.listGroundRuns.mockResolvedValue({
      items: [{ run_id: 'run-active', run_date: '2026-07-30', state: 'RUNNING' }],
      total: 1,
    })
    let requestSignal: AbortSignal | undefined
    api.getGroundPingSeries.mockImplementation(
      (_params: unknown, options: { signal: AbortSignal }) => new Promise((_resolve, reject) => {
        requestSignal = options.signal
        options.signal.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'))
        })
      }),
    )
    const target = {
      run_id: 'run-active',
      train_id: 'train-1',
      train_no: '01',
      mr_id: 'mr-ct',
      mr_name: '01-MR-CT',
      mr_position_code: 'CT',
      target_ip: '192.0.2.10',
    }

    const wrapper = mountPage()
    await flushPromises()
    const view = wrapper.vm as unknown as {
      activeTab: string
      handlePingDialogClosed: () => void
      pingWindowOpen: boolean
      selectedPingTarget: unknown
      showPingSeries: (row: typeof target) => Promise<void>
    }
    view.activeTab = 'ping'
    await flushPromises()
    void view.showPingSeries(target)
    await flushPromises()
    expect(api.getGroundPingSeries).toHaveBeenCalledOnce()
    expect(requestSignal?.aborted).toBe(false)

    view.pingWindowOpen = false
    view.handlePingDialogClosed()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(20_000)
    await flushPromises()

    expect(requestSignal?.aborted).toBe(true)
    expect(view.selectedPingTarget).toBeNull()
    expect(api.getGroundPingSeries).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

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

  it('shows a recent completed operation once and does not poll it back after auto-hide', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-30T08:00:00+08:00'))
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      latest_operation_id: 'groundop-completed',
      latest_operation_state: 'COMPLETED',
    })
    api.getGroundOperation.mockResolvedValue({
      operation_id: 'groundop-completed',
      site_id: 'line-12',
      run_id: 'run-1',
      operation_type: 'STOP',
      operation_state: 'COMPLETED',
      operation_stage: 'COMPLETED',
      progress_percent: 100,
      message: '正常停止完成',
      started_at: '2026-07-30T07:59:50+08:00',
      updated_at: '2026-07-30T07:59:59+08:00',
      completed_at: '2026-07-30T07:59:59+08:00',
      failure_code: '',
      failure_reason: '',
      result_summary: {},
    })

    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('groundop-completed')

    await vi.advanceTimersByTimeAsync(15_000)
    await flushPromises()

    expect(wrapper.text()).not.toContain('groundop-completed')
    expect(api.getGroundOperation).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('keeps a failed operation visible until the user closes it', async () => {
    vi.useFakeTimers()
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      latest_operation_id: 'groundop-failed',
      latest_operation_state: 'FAILED',
    })
    api.getGroundOperation.mockResolvedValue({
      operation_id: 'groundop-failed',
      site_id: 'line-12',
      run_id: 'run-1',
      operation_type: 'STOP_AND_ARCHIVE',
      operation_state: 'FAILED',
      operation_stage: 'ARCHIVE_VERIFYING',
      progress_percent: 90,
      message: '归档校验失败',
      started_at: '',
      updated_at: '2026-07-30T08:00:00+08:00',
      completed_at: '',
      failure_code: 'ARCHIVE_FAILED',
      failure_reason: 'SHA-256 不一致',
      result_summary: {},
    })

    const wrapper = mountPage()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()

    expect(wrapper.text()).toContain('groundop-failed')
    expect(wrapper.text()).toContain('SHA-256 不一致')
    wrapper.unmount()
  })

  it('does not poll inactive timeline, deep, syslog, ping or archive tabs', async () => {
    vi.useFakeTimers()
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
    })

    const wrapper = mountPage()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(30_000)
    await flushPromises()

    expect(api.listGroundPingTargets).not.toHaveBeenCalled()
    expect(api.listGroundDeepCollections).not.toHaveBeenCalled()
    expect(api.listGroundTimeline).not.toHaveBeenCalled()
    expect(api.listGroundSyslogRecords).not.toHaveBeenCalled()
    expect(api.listGroundArchives).not.toHaveBeenCalled()
    expect(api.getGroundHealth.mock.calls.length).toBeGreaterThan(1)
    wrapper.unmount()
  })

  it('does not overlap a pending request of the same polling class', async () => {
    vi.useFakeTimers()
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
    })
    api.getGroundHealth.mockImplementation(() => new Promise(() => undefined))

    const wrapper = mountPage()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(30_000)
    await flushPromises()

    expect(api.getGroundHealth).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('runs overview polling for 30 simulated minutes and stops after unmount', async () => {
    vi.useFakeTimers()
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
    })

    const wrapper = mountPage()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(30 * 60_000)
    await flushPromises()

    expect(api.getGroundStatus.mock.calls.length).toBeGreaterThanOrEqual(350)
    expect(api.getGroundStatus.mock.calls.length).toBeLessThanOrEqual(370)
    expect(api.getGroundHealth.mock.calls.length).toBeGreaterThanOrEqual(350)
    expect(api.getGroundHealth.mock.calls.length).toBeLessThanOrEqual(370)

    wrapper.unmount()
    const statusCalls = api.getGroundStatus.mock.calls.length
    const healthCalls = api.getGroundHealth.mock.calls.length
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(api.getGroundStatus).toHaveBeenCalledTimes(statusCalls)
    expect(api.getGroundHealth).toHaveBeenCalledTimes(healthCalls)
  })

  it('keeps Syslog auto-refresh bounded for 10 simulated minutes', async () => {
    vi.useFakeTimers()
    api.getGroundStatus.mockResolvedValue({
      ...status(),
      state: 'RUNNING',
      service_state: 'RUNNING',
      active_run_id: 'run-active',
      active_run_state: 'RUNNING',
    })
    api.listGroundRuns.mockResolvedValue({
      items: [{
        run_id: 'run-active',
        run_date: '2026-07-30',
        state: 'RUNNING',
        actual_started_at: '2026-07-30T07:00:00+08:00',
        actual_ended_at: '',
        archive_status: '',
        ping_sample_count: 0,
        syslog_record_count: 0,
        source_availability: 'ACTIVE_RAW',
      }],
      total: 1,
    })

    const wrapper = mountPage()
    await flushPromises()
    ;(wrapper.vm as unknown as { activeTab: string }).activeTab = 'syslog'
    await flushPromises()
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    await flushPromises()

    expect(api.listGroundSyslogRecords.mock.calls.length).toBeGreaterThanOrEqual(70)
    expect(api.listGroundSyslogRecords.mock.calls.length).toBeLessThanOrEqual(80)
    wrapper.unmount()
  })
})
