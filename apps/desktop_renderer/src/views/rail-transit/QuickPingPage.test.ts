// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRendererFeaturesForTest, resetRendererFeaturesForTest } from '../../features'
import { setAppLocale } from '../../i18n/runtime'
import QuickPingPage from './QuickPingPage.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), start: vi.fn(), stop: vi.fn(), stopTarget: vi.fn(), samples: vi.fn() }))
vi.mock('../../api/groundUnattended', () => ({
  listGroundQuickPing: api.list, getGroundQuickPing: api.get,
  startGroundQuickPing: api.start, stopGroundQuickPing: api.stop, stopGroundQuickPingTarget: api.stopTarget,
  getGroundQuickPingSamples: api.samples,
}))

const stats = { sent: 2, received: 1, lost: 1, loss_rate_percent: 50, min_rtt_ms: 4, avg_rtt_ms: 4, max_rtt_ms: 4, jitter_ms: 0, current_consecutive_loss: 1, max_consecutive_loss: 1 }
const run = { run_id: 'run-1', state: 'RUNNING', targets: [], stats, target_stats: {}, recent_samples: [], started_at: '2026-01-01', ended_at: '', error: '' }
const trains = [{ train_id: 't1', train_no: '001', endpoints: [{ endpoint: 'CT', mr_id: 'm1', mr_name: 'MR1', management_ip: '192.0.2.1', backup_management_ip: '192.0.2.2' }] }]

beforeEach(() => setRendererFeaturesForTest({ 'capability.ground_unattended.quick_ping': { visible: true, enabled: true } }))
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers(); resetRendererFeaturesForTest(); setAppLocale('zh_CN') })

describe('QuickPingPage', () => {
  it('updates the live task statistics when the application language changes', async () => {
    setAppLocale('zh_CN')
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: false } })
    ;(wrapper.vm as unknown as { selected: typeof run }).selected = run
    await flushPromises()
    expect(wrapper.find('.metrics').text()).toContain('发送 / 接收 / 丢包')
    expect(wrapper.find('.metrics').text()).toContain('连续丢包 当前 / 最大')
    setAppLocale('en_US')
    await flushPromises()
    const metrics = wrapper.find('.metrics').text()
    expect(metrics).toContain('Sent / Received / Lost 2 / 1 / 1')
    expect(metrics).toContain('Packet loss 50.00%')
    expect(metrics).toContain('Min / Average / Max RTT')
    expect(metrics).toContain('Jitter')
    expect(metrics).toContain('Consecutive loss Current / Maximum')
    expect(metrics).not.toMatch(/[\p{Script=Han}]/u)
    wrapper.unmount()
  })

  it('does not start a task without the Quick Ping capability', async () => {
    resetRendererFeaturesForTest()
    const wrapper = shallowMount(QuickPingPage, { props: { trains: trains as never, active: false } })
    const vm = wrapper.vm as unknown as { selectedKeys: string[]; start: () => Promise<void> }
    vm.selectedKeys = ['m1:PRIMARY:192.0.2.1']
    await vm.start()
    expect(api.start).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('preselects the exact requested MR after inventory arrives', async () => {
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: false, mrId: 'm1' } })
    await wrapper.setProps({ trains: trains as never })
    expect((wrapper.vm as unknown as { selectedKeys: string[] }).selectedKeys).toEqual(['m1:PRIMARY:192.0.2.1', 'm1:BACKUP:192.0.2.2'])
    wrapper.unmount()
  })

  it('sends history pagination and full date filters to the server', async () => {
    api.list.mockResolvedValue({ items: [], total: 701 })
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: false } })
    const vm = wrapper.vm as unknown as { historyPage: number; historyQuery: string; historyState: string; historyRange: Date[]; refresh: () => Promise<void>; historyTotal: number }
    vm.historyPage = 12; vm.historyQuery = '001'; vm.historyState = 'COMPLETED'
    vm.historyRange = [new Date('2026-01-01T00:00:00+08:00'), new Date('2026-01-31T23:59:59+08:00')]
    await vm.refresh()
    expect(api.list).toHaveBeenCalledWith(50, expect.any(Object), expect.objectContaining({ offset: 550, query: '001', state: 'COMPLETED', start_time: '2025-12-31T16:00:00.000Z', end_time: '2026-01-31T15:59:59.000Z' }))
    expect(vm.historyTotal).toBe(701)
    wrapper.unmount()
  })

  it('keeps cursor pages bounded and discards samples from the previous range', async () => {
    let resolveOld!: (value: unknown) => void
    api.samples.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
      .mockResolvedValue({ items: [{ received_at: 'new' }], next_cursor: 'cursor-2', scan_budget_exhausted: false })
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: false } })
    const vm = wrapper.vm as unknown as { selected: unknown; sampleTarget: string; sampleRange: string; loadSamples: (next?: boolean) => Promise<void>; sampleRows: unknown[] }
    vm.selected = { ...run, targets: [{ target_ip: '192.0.2.1' }] }; vm.sampleTarget = '192.0.2.1'
    await flushPromises()
    const old = vm.loadSamples()
    vm.sampleRange = 'all'
    await vm.loadSamples()
    resolveOld({ items: [{ received_at: 'old' }], next_cursor: '' })
    await old
    expect(vm.sampleRows).toEqual([{ received_at: 'new' }])
    await vm.loadSamples(true)
    expect(api.samples).toHaveBeenLastCalledWith('run-1', expect.objectContaining({ target_ip: '192.0.2.1', cursor: 'cursor-2', limit: 1000 }), expect.any(Object))
    expect(vm.sampleRows).toHaveLength(1)
    wrapper.unmount()
  })
  it('uses unlimited duration by default and sends the API null contract', async () => {
    api.list.mockResolvedValue({ items: [run], total: 1 })
    api.get.mockResolvedValue(run)
    api.start.mockResolvedValue(run)
    const wrapper = shallowMount(QuickPingPage, { props: { trains: trains as never, active: false } })
    const vm = wrapper.vm as unknown as { selectedKeys: string[]; durationMode: string; start: () => Promise<void> }
    expect(vm.durationMode).toBe('unlimited')
    vm.selectedKeys = ['m1:PRIMARY:192.0.2.1']
    await vm.start()
    expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ interval_ms: 200, timeout_ms: 1000, packet_size: 64, duration_seconds: null }))
    wrapper.unmount()
  })

  it('starts with the selected backup address and custom duration', async () => {
    api.list.mockResolvedValue({ items: [run], total: 1 })
    api.get.mockResolvedValue(run)
    api.start.mockResolvedValue(run)
    const wrapper = shallowMount(QuickPingPage, { props: { trains: trains as never, active: false } })
    const vm = wrapper.vm as unknown as { selectedKeys: string[]; durationMode: string; customDuration: number; start: () => Promise<void> }
    vm.selectedKeys = ['m1:BACKUP:192.0.2.2']
    vm.durationMode = 'custom'
    vm.customDuration = 75
    await vm.start()
    expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ interval_ms: 200, timeout_ms: 1000, packet_size: 64, duration_seconds: 75, targets: [expect.objectContaining({ target_ip: '192.0.2.2', address_role: 'BACKUP' })] }))
    wrapper.unmount()
  })

  it('loads selected history details and stops polling after deactivation', async () => {
    vi.useFakeTimers()
    api.list.mockResolvedValue({ items: [run], total: 1 })
    api.get.mockResolvedValue({ ...run, state: 'COMPLETED' })
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: true } })
    await flushPromises()
    const vm = wrapper.vm as unknown as { selectRun: (value: typeof run) => Promise<void>; selected: typeof run }
    await vm.selectRun(run)
    expect(api.get).toHaveBeenCalledWith('run-1', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(vm.selected.state).toBe('COMPLETED')
    await wrapper.setProps({ active: false })
    const count = api.list.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(api.list).toHaveBeenCalledTimes(count)
    wrapper.unmount()
  })

  it('ignores an older history request when another run is selected', async () => {
    let resolveOld!: (value: typeof run) => void
    api.list.mockResolvedValue({ items: [run], total: 1 })
    api.get.mockImplementation((id: string) => id === 'run-1' ? new Promise((resolve) => { resolveOld = resolve }) : Promise.resolve({ ...run, run_id: 'run-2' }))
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: false } })
    const vm = wrapper.vm as unknown as { selectRun: (value: typeof run) => Promise<void>; selected: typeof run }
    const older = vm.selectRun(run)
    await vm.selectRun({ ...run, run_id: 'run-2' })
    resolveOld(run)
    await older
    expect(vm.selected.run_id).toBe('run-2')
    wrapper.unmount()
  })
})


describe('Quick Ping IP selection and individual control', () => {
  it('deduplicates MR aliases by IP while preserving primary and backup addresses', async () => {
    const inventory = [...trains, { train_id: 't2', endpoints: [{ endpoint: 'CW', mr_id: 'alias', mr_name: 'Alias', management_ip: '192.0.2.1' }] }]
    const wrapper = shallowMount(QuickPingPage, { props: { trains: inventory as never, active: false } })
    const vm = wrapper.vm as unknown as { selectedKeys: string[]; selectedTargets: Array<{ target_ip: string }>; targetDisabled: (target: unknown) => boolean; targets: unknown[] }
    vm.selectedKeys = ['m1:PRIMARY:192.0.2.1', 'm1:BACKUP:192.0.2.2', 'alias:PRIMARY:192.0.2.1']
    expect(vm.selectedTargets.map((target) => target.target_ip).sort()).toEqual(['192.0.2.1', '192.0.2.2'])
    await flushPromises()
    expect(wrapper.text()).toContain('2')
    wrapper.unmount()
  })

  it('retains occupied IPs from other history pages and rejects stale selections', async () => {
    api.list.mockResolvedValue({ items: [], total: 200, active_ips: { '192.0.2.1': 'owner-run' } })
    const wrapper = shallowMount(QuickPingPage, { props: { trains: trains as never, active: false } })
    const vm = wrapper.vm as unknown as { selectedKeys: string[]; targets: unknown[]; targetDisabled: (target: unknown) => boolean; historyPage: number; refresh: () => Promise<void>; start: () => Promise<void>; error: string }
    vm.historyPage = 4
    await vm.refresh()
    expect(vm.targetDisabled(vm.targets[0])).toBe(true)
    expect(vm.targetDisabled(vm.targets[1])).toBe(false)
    vm.selectedKeys = ['m1:PRIMARY:192.0.2.1']
    await vm.start()
    expect(api.start).not.toHaveBeenCalled()
    expect(vm.error).toBeTruthy()
    wrapper.unmount()
  })

  it('searches inventory by MR or IP and removes all aliases of a selected IP', async () => {
    const wrapper = shallowMount(QuickPingPage, { props: { trains: trains as never, active: false } })
    const vm = wrapper.vm as unknown as { targetQuery: string; filteredTargets: Array<{ target_ip: string }>; selectedKeys: string[]; selectedTargets: unknown[]; removeTarget: (target: unknown) => void }
    vm.targetQuery = '192.0.2.2'
    expect(vm.filteredTargets.map((target) => target.target_ip)).toEqual(['192.0.2.2'])
    vm.selectedKeys = ['m1:PRIMARY:192.0.2.1', 'm1:BACKUP:192.0.2.2']
    vm.removeTarget(vm.selectedTargets[0])
    expect(vm.selectedKeys).toEqual(['m1:BACKUP:192.0.2.2'])
    wrapper.unmount()
  })

  it('stops only the requested IP and leaves the batch running', async () => {
    const live = { ...run, targets: [{ target_ip: '192.0.2.1' }, { target_ip: '192.0.2.2' }], target_runtime: { '192.0.2.1': { state: 'RUNNING' }, '192.0.2.2': { state: 'RUNNING' } } }
    api.stopTarget.mockResolvedValue(live); api.get.mockResolvedValue(live); api.list.mockResolvedValue({ items: [live], total: 1 })
    const wrapper = shallowMount(QuickPingPage, { props: { trains: [], active: false } })
    const vm = wrapper.vm as unknown as { selected: unknown; stopTarget: (ip: string) => Promise<void> }
    vm.selected = live
    await vm.stopTarget('192.0.2.1')
    expect(api.stopTarget).toHaveBeenCalledWith('run-1', '192.0.2.1')
    expect(api.stop).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
