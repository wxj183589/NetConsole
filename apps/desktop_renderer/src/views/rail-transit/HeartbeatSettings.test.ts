// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import HeartbeatSettings from './HeartbeatSettings.vue'

const api = vi.hoisted(() => ({ config: vi.fn(), runtime: vi.fn(), save: vi.fn() }))
const context = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock('../../api/groundUnattended', () => ({ getHeartbeatConfig: api.config, getHeartbeatRuntime: api.runtime, updateHeartbeatConfig: api.save }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => context.current }))
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
const config = { enabled: true, interval_ms: 1000, timeout_ms: 4000, packet_size: 64, shard_size: 12, warmup_seconds: 10, backup_policy: 'MONITOR' }
const runtime = { state: 'RUNNING', enabled: true, target_count: 400, process_count: 34, last_sample_at: 'probe-time', last_success_at: 'success-time', last_error: '' }
const global = {
  renderStubDefaultSlot: true,
  stubs: {
    ElButton: { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
    ElDescriptionsItem: { template: '<div><slot /></div>' },
    ElAlert: { props: ['title'], template: '<div>{{ title }}</div>' },
  },
}
beforeEach(() => {
  vi.useFakeTimers()
  context.current = { t: (_key: string, fallback: string) => fallback, activeTab: ref('settings'), pageVisible: ref(true), pageActivated: ref(true) }
  api.config.mockResolvedValue({ ...config })
  api.runtime.mockResolvedValue({ ...runtime })
  api.save.mockResolvedValue({ ...config, enabled: false })
})
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })

it('loads independent configuration, shows runtime and saves without a Ground Run', async () => {
  const wrapper = shallowMount(HeartbeatSettings, { global })
  await flushPromises()
  expect(api.config).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('400 / 34')
  expect(wrapper.text()).toContain('success-time')
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(api.save).toHaveBeenCalledWith(config, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(wrapper.findComponent({ name: 'ElSwitch' }).attributes('modelvalue')).toBe('false')
  wrapper.unmount()
})

it('does not overlap runtime queries and cancels them when hidden or unmounted', async () => {
  let resolve!: (value: typeof runtime) => void
  api.runtime.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
  const wrapper = shallowMount(HeartbeatSettings, { global })
  await flushPromises()
  await vi.advanceTimersByTimeAsync(15000)
  expect(api.runtime).toHaveBeenCalledTimes(1)
  const firstSignal = api.runtime.mock.calls[0][0].signal as AbortSignal
  ;(context.current.pageVisible as { value: boolean }).value = false
  await flushPromises()
  expect(firstSignal.aborted).toBe(true)
  resolve({ ...runtime, target_count: 999 })
  await flushPromises()
  expect(wrapper.text()).not.toContain('999')
  ;(context.current.pageVisible as { value: boolean }).value = true
  await flushPromises()
  expect(api.runtime).toHaveBeenCalledTimes(2)
  const lastSignal = api.runtime.mock.calls[1][0].signal as AbortSignal
  wrapper.unmount()
  expect(lastSignal.aborted).toBe(true)
  await vi.advanceTimersByTimeAsync(15000)
  expect(api.runtime).toHaveBeenCalledTimes(2)
})

it('retries failed runtime reads without any monitoring control request', async () => {
  api.runtime.mockRejectedValueOnce(new Error('query failed'))
  const wrapper = shallowMount(HeartbeatSettings, { global })
  await flushPromises()
  expect(wrapper.text()).toContain('query failed')
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  expect(api.runtime).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain('400 / 34')
  expect(api.save).not.toHaveBeenCalled()
  wrapper.unmount()
})
