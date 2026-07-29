// @vitest-environment happy-dom

import { defineComponent, h, useAttrs, type Component } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
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
  getLatestGroundOperation: vi.fn(),
  verifyGroundArchive: vi.fn(),
  downloadBackendResource: vi.fn(),
}))

vi.mock('../../api/groundUnattended', () => api)
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
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Ground unattended page loading behavior', () => {
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
      pingDialog: boolean
      selectedPingTarget: unknown
      showPingSeries: (row: typeof target) => Promise<void>
    }
    view.activeTab = 'ping'
    await flushPromises()
    void view.showPingSeries(target)
    await flushPromises()
    expect(api.getGroundPingSeries).toHaveBeenCalledOnce()
    expect(requestSignal?.aborted).toBe(false)

    view.pingDialog = false
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
