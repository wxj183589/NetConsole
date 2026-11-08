// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GroundHeartbeatMr, GroundMrMonitoring } from '../../types/groundUnattended'
import MrMonitoringDrawer from './MrMonitoringDrawer.vue'
const api = vi.hoisted(() => ({ monitor: vi.fn(), raw: vi.fn() }))
vi.mock('../../api/groundUnattended', () => ({ getGroundMrMonitoring: api.monitor, listGroundSyslogRecords: api.raw }))
const mr = { mr_uuid: 'mr-1', train_id: 't1', train_no: '001', role: 'CT', ip_states: [], status: 'ONLINE' } as unknown as GroundHeartbeatMr
const fixture = { mr, series: { points: [], diagnostics: { truncated: false }, window_statistics: { '1': { sent_count: 0, lost_count: 0, loss_rate_percent: null } } }, mesh_events: [], peer_intervals: [], run_sent_count: 0, run_lost_count: 0 } as unknown as GroundMrMonitoring
const global = { renderStubDefaultSlot: true, stubs: { ElDrawer: { template: '<section><slot name="header"/><slot/></section>' }, ElButton: { template: '<button @click="$emit(\'click\')"><slot/></button>' } } }
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })
describe('single MR monitoring lifecycle', () => {
  it('defaults to 60 minutes and five-second polling, and cancels hidden work', async () => {
    vi.useFakeTimers(); api.monitor.mockResolvedValue(fixture)
    const wrapper = shallowMount(MrMonitoringDrawer, { props: { mr, runId: 'run-1', active: true, section: 'all', terminalEnabled: false, quickEnabled: false }, global })
    await flushPromises()
    const request = api.monitor.mock.calls[0]!
    expect(Date.parse(request[1].end_time) - Date.parse(request[1].start_time)).toBe(3600000)
    expect(wrapper.text()).toContain('UNKNOWN')
    await vi.advanceTimersByTimeAsync(5000); await flushPromises()
    expect(api.monitor).toHaveBeenCalledTimes(2)
    await wrapper.setProps({ active: false })
    await vi.advanceTimersByTimeAsync(10000)
    expect(api.monitor).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('aborts a departed run and rejects its late response', async () => {
    let finish!: (data: GroundMrMonitoring) => void
    api.monitor.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })).mockResolvedValue(fixture)
    const wrapper = shallowMount(MrMonitoringDrawer, { props: { mr, runId: 'old', active: true, section: 'all', terminalEnabled: false, quickEnabled: false }, global })
    await flushPromises(); const signal = api.monitor.mock.calls[0]![2].signal as AbortSignal
    await wrapper.setProps({ runId: 'new' }); await flushPromises()
    finish({ ...fixture, mr: { ...mr, resolved_ap_name: 'STALE RESPONSE' } }); await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.text()).not.toContain('STALE RESPONSE')
    wrapper.unmount()
  })
})
