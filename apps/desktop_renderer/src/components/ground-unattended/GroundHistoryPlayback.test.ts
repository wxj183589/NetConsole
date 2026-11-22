// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GroundMrMonitoring, GroundRun, GroundTrain } from '../../types/groundUnattended'
import GroundHistoryPlayback from './GroundHistoryPlayback.vue'

const api = vi.hoisted(() => ({ heartbeat: vi.fn(), monitor: vi.fn(), quickRuns: vi.fn(), quickSamples: vi.fn() }))
vi.mock('../../api/groundUnattended', () => ({ getGroundHeartbeat: api.heartbeat, getGroundMrMonitoring: api.monitor, listGroundQuickPing: api.quickRuns, getGroundQuickPingSamples: api.quickSamples }))
afterEach(() => vi.resetAllMocks())

describe('Ground history playback isolation', () => {
  it('does not start or query anything merely by entering playback', async () => {
    const wrapper = shallowMount(GroundHistoryPlayback, {
      props: { siteId: 'hzdt-09', runs: [], trains: [], active: true },
      global: { stubs: { ElSelect: true, ElOption: true, ElDatePicker: true, ElButton: true, ElAlert: true, ElPagination: true, MrMonitoringChart: true } },
    })
    await wrapper.vm.$nextTick()
    expect(api.monitor).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('不启动采集')
    wrapper.unmount()
  })

  it('loads MR choices from the selected historical run instead of live trains', async () => {
    const run = { run_id: 'run-archive', actual_started_at: '2026-11-07T00:00:00Z', actual_ended_at: '2026-11-07T01:00:00Z' } as unknown as GroundRun
    api.heartbeat.mockResolvedValue({ mrs: [{ mr_uuid: 'mr-archive', train_id: 'train-archive', train_no: '009', role: 'CT', mr_name: 'MR archive' }] })
    const wrapper = shallowMount(GroundHistoryPlayback, {
      props: { siteId: 'hzdt-09', runs: [run], trains: [], active: true },
      global: { stubs: { ElSelect: true, ElOption: true, ElDatePicker: true, ElButton: true, ElAlert: true, ElPagination: true, MrMonitoringChart: true } },
    })
    await flushPromises()
    expect(api.heartbeat).toHaveBeenCalledWith('', expect.objectContaining({ signal: expect.any(AbortSignal) }), expect.objectContaining({ run_id: 'run-archive', data_mode: 'HISTORICAL_PLAYBACK' }))
    expect((wrapper.vm as unknown as { mrOptions: Array<{ id: string }> }).mrOptions).toEqual([{ id: 'mr-archive', role: 'CT', name: 'MR archive', trainId: 'train-archive', trainNo: '009' }])
    wrapper.unmount()
  })

  it('puts one navigator before five independently collapsible chart regions', async () => {
    const run = { run_id: 'run-1', actual_started_at: '2026-11-07T00:00:00Z', actual_ended_at: '2026-11-07T01:00:00Z' } as unknown as GroundRun
    const train = { train_id: 'train-1', train_no: '001', endpoints: [{ mr_id: 'mr-1', endpoint: 'CT', mr_name: 'MR-1' }] } as unknown as GroundTrain
    const mr = { mr_uuid: 'mr-1', train_id: 'train-1', train_no: '001', role: 'CT', management_ip: '192.0.2.1', backup_management_ip: '192.0.2.2' }
    api.heartbeat.mockResolvedValue({ mrs: [] })
    api.quickRuns.mockResolvedValue({ items: [] })
    api.monitor.mockResolvedValue({
      mr, queried_start: run.actual_started_at, queried_end: run.actual_ended_at,
      series: { points: [
        { ts: run.actual_started_at, target_ip: '192.0.2.1', ok: true, rtt_ms: 3 },
        { ts: run.actual_started_at, target_ip: '192.0.2.2', ok: true, rtt_ms: 4 },
      ], diagnostics: { truncated: false } }, mesh_events: [], peer_intervals: [], loss_events: [], loss_event_total: 0,
      loss_event_limit: 3, loss_event_offset: 0, events_truncated: false, run_sent_count: 2, run_lost_count: 0,
    } as unknown as GroundMrMonitoring)
    const wrapper = shallowMount(GroundHistoryPlayback, {
      props: { siteId: 'hzdt-09', runs: [run], trains: [train], active: true },
      global: { stubs: {
        ElSelect: true, ElOption: true, ElDatePicker: true, ElButton: true, ElAlert: true, ElPagination: true,
        ElTag: true, ElTooltip: true,
        MrMonitoringChart: {
          props: ['visibleStart', 'visibleEnd', 'selectedTime'],
          emits: ['viewport-change', 'cursor-change'],
          template: '<div class="chart-stub">{{ visibleStart }}|{{ visibleEnd }}|{{ selectedTime }}<button class="viewport-emitter" @click="$emit(\'viewport-change\', { start: \'2026-11-07T00:10:00.000Z\', end: \'2026-11-07T00:20:00.000Z\' })" /><button class="cursor-emitter" @click="$emit(\'cursor-change\', \'2026-11-07T00:15:00.000Z\')" /></div>',
        },
        QuickPingChart: {
          props: ['visibleStart', 'visibleEnd', 'selectedTime'],
          emits: ['viewport-change', 'cursor-change'],
          template: '<div class="chart-stub">{{ visibleStart }}|{{ visibleEnd }}|{{ selectedTime }}<button class="viewport-emitter" @click="$emit(\'viewport-change\', { start: \'2026-11-07T00:10:00.000Z\', end: \'2026-11-07T00:20:00.000Z\' })" /><button class="cursor-emitter" @click="$emit(\'cursor-change\', \'2026-11-07T00:15:00.000Z\')" /></div>',
        },
      } },
    })
    await (wrapper.vm as unknown as { query: () => Promise<void> }).query()
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.navigator')).toHaveLength(1)
    expect(wrapper.findAll('.track')).toHaveLength(3)
    expect(wrapper.find('.navigator').element.compareDocumentPosition(wrapper.find('.track').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(wrapper.findAll('.chart-stub')).toHaveLength(4)

    const toggle = (label: string) => wrapper.findAll('button.track-toggle').find((button) => button.text().includes(label))!
    await toggle('主用管理 IP').trigger('click')
    expect(wrapper.findAll('.chart-stub')).toHaveLength(3)
    await toggle('备用管理 IP').trigger('click')
    expect(wrapper.findAll('.chart-stub')).toHaveLength(2)
    await toggle('Peer AP').trigger('click')
    expect(wrapper.findAll('.chart-stub')).toHaveLength(1)

    const nextStart = '2026-11-07T00:10:00.000Z', nextEnd = '2026-11-07T00:20:00.000Z'
    ;(wrapper.vm as unknown as { changeViewport: (value: { start: string; end: string }) => void }).changeViewport({ start: nextStart, end: nextEnd })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.navigator-range').text()).toContain('2026')
    await wrapper.find('.viewport-emitter').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.chart-stub').every((chart) => chart.text().includes(`${nextStart}|${nextEnd}`))).toBe(true)
    await wrapper.find('.cursor-emitter').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.chart-stub').every((chart) => chart.text().includes('|2026-11-07T00:15:00.000Z'))).toBe(true)
    wrapper.unmount()
  })
})
