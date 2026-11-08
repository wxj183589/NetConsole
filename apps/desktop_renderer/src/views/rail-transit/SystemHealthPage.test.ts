// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAppLocale } from '../../i18n/runtime'
import { groundStatusLabel } from './groundUnattendedLabels'
import SystemHealthPage from './SystemHealthPage.vue'

const state = vi.hoisted(() => ({ health: null as unknown }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => ({
  health: state.health, groundStatusLabel, bytes: (n: number) => `${n} B`,
}) }))

function render() {
  return mount(SystemHealthPage, { global: { stubs: {
    ElTag: { template: '<span><slot /></span>' },
    ElEmpty: { props: ['description'], template: '<span>{{ description }}</span>' },
  } } })
}

describe('system health page', () => {
  beforeEach(() => { setAppLocale('zh_CN'); state.health = ref(null) })
  afterEach(() => { setAppLocale('zh_CN') })
  it('shows unavailable measurements without inventing runtime data', () => {
    const wrapper = render()
    expect(wrapper.text()).toContain('未知')
    expect(wrapper.text()).toContain('本次运行时长—')
    expect(wrapper.text()).toContain('心跳采样写入延迟—')
    expect(wrapper.text()).toContain('Supervisor—')
  })
  it('shows backend health separately from AP state and exposes measured storage and AC metrics', () => {
    state.health = ref({
      status: 'DEGRADED', supervisor_running: true, run_state: 'RUNNING', run_elapsed_seconds: 120,
      ping_sample_rate_per_second: 12, ping_sample_write_duration_ms: 1.25,
      raw_write_failed_count: 3, raw_write_rate_bytes_per_second: 2048,
      disk_total_bytes: 10000, disk_free_bytes: 5000, raw_file_count: 7,
      archive_pending_count: 2, archive_failed_count: 1, ping_worker_warnings: ['采样延迟'],
      ac_pollers: [{ controller_id: 'ac1', controller_name: 'AC 1', status: 'CRITICAL', poll_count: 4,
        success_count: 3, failure_count: 1, last_success_age_seconds: 31, heartbeat_age_seconds: 1 }],
    })
    const wrapper = render()
    expect(wrapper.text()).toContain('降级')
    expect(wrapper.text()).toContain('120.0 秒')
    expect(wrapper.text()).toContain('12 /s')
    expect(wrapper.text()).toContain('1.3 ms')
    expect(wrapper.text()).toContain('采样延迟')
    expect(wrapper.text()).toContain('10000 B / 5000 B')
    expect(wrapper.text()).toContain('2048 B/s')
    expect(wrapper.text()).toContain('75.0%')
    expect(wrapper.text()).toContain('距最近成功 31.0 秒')
    expect(wrapper.text()).toContain('严重')
  })
  it('updates rendered metric units and poll statistics when the language changes', async () => {
    state.health = ref({
      status: 'HEALTHY', dropped: 4, disk_queue_count: 2, spool_files: 3,
      spool_guard_state: 'HEALTHY',
      ac_pollers: [{ controller_id: 'ac1', status: 'HEALTHY', connection_state: 'CONNECTED',
        poll_interval_seconds: 15, poll_count: 4, success_count: 3, failure_count: 1,
        reconnect_count: 2, next_poll_at: '2026-01-01T00:00:15Z' }],
    })
    const wrapper = render()
    expect(wrapper.text()).toContain('3 个文件 · 保护')
    expect(wrapper.text()).toContain('轮询 4 · 成功 3 · 失败 1 · 重连 2')
    setAppLocale('en_US')
    await nextTick()
    expect(wrapper.text()).toContain('3 files · Protection')
    expect(wrapper.text()).toContain('Polls 4 · Succeeded 3 · Failed 1 · Reconnects 2')
    expect(wrapper.text()).toContain('CONNECTED · 15 s')
    expect(wrapper.text()).toContain('Next poll 2026-01-01T00:00:15Z')
    expect(wrapper.text()).not.toContain('个文件')
    setAppLocale('zh_CN')
    await nextTick()
    expect(wrapper.text()).toContain('3 个文件 · 保护')
    wrapper.unmount()
  })

})
