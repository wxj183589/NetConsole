// @vitest-environment happy-dom
import { defineComponent, h, KeepAlive } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ listLocalServices: vi.fn(), readLocalServiceLogs: vi.fn() }))
vi.mock('../../api/localNetworkServices', () => api)
import ServiceLogsPanel from './ServiceLogsPanel.vue'

const field = (name: string) => defineComponent({ name, props: ['modelValue'], emits: ['update:modelValue'], template: '<div><slot /></div>' })
const stubs = {
  ElSelect: field('ElSelect'), ElInput: field('ElInput'), ElDatePicker: field('ElDatePicker'),
  ElSwitch: field('ElSwitch'), ElCheckbox: field('ElCheckbox'), ElOption: true, ElButton: true,
  ElTooltip: { template: '<div><slot /></div>' }, ElAlert: true,
  NcDataTable: { props: ['data'], template: '<div>{{ JSON.stringify(data) }}</div>' },
}

describe('ServiceLogsPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    api.listLocalServices.mockResolvedValue({ services: [{ id: 'http', enabled: true }, { id: 'ftp', enabled: true }] })
    api.readLocalServiceLogs.mockResolvedValue({ entries: [{ index: 0, time: '', level: 'INFO', message: 'started', raw: 'started' }], lines: ['started'] })
  })
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

  it('loads existing services, polls without overlap, and stops on unmount', async () => {
    const wrapper = mount(ServiceLogsPanel, { global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('started')
    expect(api.readLocalServiceLogs).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(api.readLocalServiceLogs).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(4000)
    expect(api.readLocalServiceLogs).toHaveBeenCalledTimes(2)
  })

  it('queries filters and ignores a stale response after switching service', async () => {
    const wrapper = mount(ServiceLogsPanel, { global: { stubs } })
    await flushPromises()
    let resolveOld!: (value: unknown) => void
    api.readLocalServiceLogs.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    wrapper.findComponent({ name: 'ElInput' }).vm.$emit('update:modelValue', 'port')
    await flushPromises()
    wrapper.findAllComponents({ name: 'ElSelect' })[0]!.vm.$emit('update:modelValue', 'ftp')
    await flushPromises()
    expect(api.readLocalServiceLogs).toHaveBeenLastCalledWith('ftp', expect.objectContaining({ keyword: 'port' }))
    resolveOld({ entries: [{ message: 'obsolete HTTP' }], lines: [] })
    await flushPromises()
    expect(wrapper.text()).not.toContain('obsolete HTTP')
    wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(api.readLocalServiceLogs).toHaveBeenLastCalledWith('ftp', expect.objectContaining({ history: true }))
    wrapper.unmount()
  })

  it('pauses while kept alive and resumes when activated', async () => {
    const Host = defineComponent({
      props: { shown: Boolean },
      setup: (props) => () => h(KeepAlive, null, { default: () => props.shown ? h(ServiceLogsPanel) : null }),
    })
    const wrapper = mount(Host, { props: { shown: true }, global: { stubs } })
    await flushPromises()
    expect(api.readLocalServiceLogs).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ shown: false })
    await vi.advanceTimersByTimeAsync(4000)
    expect(api.readLocalServiceLogs).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ shown: true })
    await flushPromises()
    expect(api.readLocalServiceLogs).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
