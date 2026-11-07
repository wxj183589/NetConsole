// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRendererFeaturesForTest } from '../../features'
import HeartbeatPage from './HeartbeatPage.vue'
import OverviewPage from './OverviewPage.vue'

const api = vi.hoisted(() => ({ heartbeat: vi.fn(), timeline: vi.fn() }))
const injected = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock('../../api/groundUnattended', () => ({ getGroundHeartbeat: api.heartbeat, listGroundTimeline: api.timeline }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => injected.current }))
vi.mock('../../composables/useExternalTerminalLauncher', () => ({ useExternalTerminalLauncher: () => ({}) }))

const snapshot = {
  run_id: 'run-1', run_state: 'RUNNING', mr_counts: { ONLINE: 1, OFFLINE: 0 },
  train_counts: { BOTH_ONLINE: 1, CT_ONLY: 1, TRAIN_OFFLINE: 1 }, trains: [{ train_id: 't1', train_no: '001', status: 'CT_ONLY' }],
  mrs: [{ mr_uuid: 'mr-1', train_id: 't1', train_no: '001', mr_name: 'Mock CT', role: 'CT', status: 'ONLINE', engine_state: 'RUNNING', unreachable_since: '', last_success_at: '2026-01-01', last_recovery_at: '', consecutive_recovery_successes: 0, updated_at: '2026-01-01', ip_states: [
    { ip: '192.0.2.1', sent_count: 10, received_count: 8, lost_count: 2, avg_rtt_ms: 2 },
    { ip: '192.0.2.2', sent_count: 10, received_count: 10, lost_count: 0, avg_rtt_ms: 1 },
  ] }],
}
const pingTargets = [{ mr_id: 'mr-1', target_ip: '192.0.2.1' }, { mr_id: 'mr-1', target_ip: '192.0.2.2' }]
const props = { trains: [], pingTargets, trainColumns: [], pingColumns: [], trainFilter: '', pingFilter: { query: '', endpoint: '', station: '', section: '', minLoss: 0 }, locationStats: { ap: 0, station: 0, unmatched: 0, excluded: 0 }, statusLabel: String, statusType: () => 'info', endpoint: () => undefined, endpointRadioTooltip: () => '', controlSourceLabel: String }
const global = {
  renderStubDefaultSlot: true,
  stubs: {
    NcDataTable: { props: ['data'], template: '<div><slot v-if="data.length" name="cell-actions" :row="data[0]" /></div>' },
    ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
    ElDrawer: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /></div>' },
    ElDescriptionsItem: { template: '<div><slot /></div>' },
    ElTableColumn: { template: '<div />' },
  },
}

beforeEach(() => {
  setRendererFeaturesForTest({ 'ground_unattended.quick_ping': { visible: true, enabled: true }, 'capability.ground_unattended.quick_ping': { visible: true, enabled: true } })
  injected.current = {
    activeTab: ref('heartbeat'), pageVisible: ref(true), pageActivated: ref(true), selectedRunId: ref('run-1'), quickContextRevision: ref(0),
    status: ref(null), profile: ref(null), health: ref(null), syslogTransport: ref(null), syslogTransportLoading: ref(false),
    t: (_key: string, fallback: string) => fallback, statusType: () => 'info', bytes: String,
    groundStatusLabel: String, groundRunModeLabel: String,
  }
  api.heartbeat.mockResolvedValue(snapshot)
  api.timeline.mockResolvedValue({ items: [{ event_id: 1, severity: 'error', event_type: 'deep_scheduler_failed', title: '深采失败', message: 'mock', ts: '2026-01-01' }], total: 1 })
})
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })

describe('persisted heartbeat UI', () => {
  it('loads the initial snapshot once but does not poll while monitoring is stopped', async () => {
    vi.useFakeTimers()
    ;(injected.current.status as { value: unknown }).value = { state: 'STOPPED' }
    const wrapper = shallowMount(HeartbeatPage, { props: props as never, global })
    await flushPromises()

    expect(api.heartbeat).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(api.heartbeat).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('uses one completion chained timer while running and clears it on pause', async () => {
    vi.useFakeTimers()
    ;(injected.current.status as { value: unknown }).value = { state: 'RUNNING' }
    const wrapper = shallowMount(HeartbeatPage, { props: props as never, global })
    await flushPromises()

    expect(api.heartbeat).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2_999)
    expect(api.heartbeat).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(api.heartbeat).toHaveBeenCalledTimes(2)

    ;(injected.current.status as { value: unknown }).value = { state: 'PAUSED' }
    await flushPromises()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(api.heartbeat).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('backs off failed polls and keeps the last successful snapshot', async () => {
    vi.useFakeTimers()
    ;(injected.current.status as { value: unknown }).value = { state: 'RUNNING' }
    api.heartbeat.mockResolvedValueOnce(snapshot).mockRejectedValueOnce(new Error('temporary failure')).mockResolvedValue({ ...snapshot, run_id: 'run-after-retry' })
    const wrapper = shallowMount(HeartbeatPage, { props: props as never, global })
    await flushPromises()

    await vi.advanceTimersByTimeAsync(3_000)
    await flushPromises()
    expect(api.heartbeat).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('001')

    await vi.advanceTimersByTimeAsync(5_999)
    expect(api.heartbeat).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(api.heartbeat).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('run-after-retry')
    wrapper.unmount()
  })

  it('renders one train with independent CT/CW cards and opens the unified monitor', async () => {
    const wrapper = shallowMount(HeartbeatPage, { props: props as never, global })
    await flushPromises()
    expect(wrapper.findAll('.train-row')).toHaveLength(1)
    expect(wrapper.findAll('.mr-card')).toHaveLength(2)
    expect(wrapper.text()).toContain('192.0.2.1')
    expect(wrapper.text()).toContain('192.0.2.2')
    expect(wrapper.text()).toContain('仅 CT 可达')
    expect(wrapper.text()).not.toContain('RTT 2 ms')
    expect(wrapper.find('[table-id="ground-heartbeat-mrs"]').exists()).toBe(false)
    await wrapper.find('.mr-card[role="button"]').trigger('click')
    const vm = wrapper.vm as unknown as { selectedMr: typeof snapshot.mrs[0] }
    expect(vm.selectedMr.ip_states).toHaveLength(2)
    const drawer = wrapper.findComponent({ name: 'MrMonitoringDrawer' })
    expect(drawer.exists()).toBe(true)
    drawer.vm.$emit('quick-ping')
    expect(wrapper.emitted('quick-ping')?.[0]).toEqual(['mr-1'])
    wrapper.unmount()
  })

  it('sends IP and AP search to the backend before pagination', async () => {
    vi.useFakeTimers()
    const wrapper = shallowMount(HeartbeatPage, { props: props as never, global })
    await flushPromises()
    ;(wrapper.vm as unknown as { search: string }).search = '192.0.2.2'
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(api.heartbeat.mock.calls.at(-1)?.[2]).toMatchObject({ query: '192.0.2.2', page: 1, page_size: 50 })
    wrapper.unmount()
  })

  it('aborts old run requests and ignores a late response', async () => {
    let resolveOld!: (value: typeof snapshot) => void
    api.heartbeat.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    const wrapper = shallowMount(HeartbeatPage, { props: props as never, global })
    await flushPromises()
    const oldSignal = api.heartbeat.mock.calls[0]![1].signal as AbortSignal
    api.heartbeat.mockResolvedValue({ ...snapshot, run_id: 'run-2', mrs: [] })
    ;(injected.current.selectedRunId as { value: string }).value = 'run-2'
    await flushPromises()
    resolveOld(snapshot)
    await flushPromises()
    expect(oldSignal.aborted).toBe(true)
    expect(wrapper.text()).toContain('run-2')
    expect((wrapper.vm as unknown as { heartbeatMrs: unknown[] }).heartbeatMrs).toEqual([])
    wrapper.unmount()
  })

  it('polls only the active page and stops both page requests after deactivation', async () => {
    vi.useFakeTimers()
    const heartbeat = shallowMount(HeartbeatPage, { props: props as never, global })
    const overview = shallowMount(OverviewPage, { global })
    await flushPromises()
    expect(api.heartbeat).toHaveBeenCalledTimes(1)
    expect(api.timeline).not.toHaveBeenCalled()
    ;(injected.current.activeTab as { value: string }).value = 'overview'
    await flushPromises()
    expect(api.heartbeat).toHaveBeenCalledTimes(2)
    expect(api.timeline).toHaveBeenCalledTimes(1)
    expect(overview.find('[data-testid="v2-heartbeat-metrics"]').text()).toContain('1 / 1 / 1')
    expect(overview.text()).toContain('深采失败')
    ;(injected.current.pageActivated as { value: boolean }).value = false
    await flushPromises()
    await vi.advanceTimersByTimeAsync(15000)
    expect(api.heartbeat).toHaveBeenCalledTimes(2)
    expect(api.timeline).toHaveBeenCalledTimes(1)
    heartbeat.unmount(); overview.unmount()
  })
})
