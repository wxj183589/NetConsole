// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ConsoleCommandBar from './ConsoleCommandBar.vue'
import type { TerminalSession } from '../../api/terminal'

const mocks = vi.hoisted(() => ({ api: vi.fn(), save: vi.fn(), clone: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() }))
vi.mock('../../api/client', () => ({ apiRequest: mocks.api }))
vi.mock('../../api/terminal', async original => ({ ...await original<object>(), cloneTerminalSession: mocks.clone }))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: mocks.save }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessage: { error: mocks.error, success: mocks.success, info: mocks.info, warning: mocks.warning } }))
const sessions = [{ session_id: 'one', state: 'RUNNING', device_name: 'AC1' }, { session_id: 'two', state: 'RUNNING', device_name: 'AC2' }] as TerminalSession[]
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.clearAllMocks()
  mocks.api.mockImplementation(async (url: string) => url === '/api/terminal/quick-buttons' ? { version: 1, groups: [{ id: 'group-0', name: 'H3C', buttons: [{ id: 'version', name: '版本', action: 'SEND_STRING', text: 'display version\\r', color: '#409eff', order: 0, enabled: true }] }] } : { id: 'job-one', rows: [] })
})
afterEach(() => { wrappers.splice(0).forEach(item => item.unmount()); vi.useRealTimers() })
async function bar() { const wrapper = mount(ConsoleCommandBar, { props: { sessions, active: sessions[0]!, selected: ['two'], selectedDevices: [] }, global: { stubs: { ElDialog: true, ElTable: true, ElTableColumn: true } } }); wrappers.push(wrapper); await flushPromises(); return wrapper }
describe('console commands keep explicit target semantics', () => {
  it('defaults to current session and sends a saved quick button only there', async () => {
    const wrapper = await bar()
    expect(wrapper.get('select[aria-label="发送目标"]').element).toHaveProperty('value', 'current')
    await wrapper.findAll('.quick-buttons button').find(button => button.text() === '版本')!.trigger('click')
    await flushPromises()
    const call = mocks.api.mock.calls.find(call => call[0] === '/api/terminal/batch-sends')!
    expect(JSON.parse(call[1].body)).toMatchObject({ session_ids: ['one'], scope: 'current', group_id: 'group-0', button_id: 'version' })
  })
  it('preserves multiline content and sends only selected Session IDs', async () => {
    const wrapper = await bar()
    await wrapper.get('select[aria-label="发送目标"]').setValue('selected')
    await wrapper.get('textarea[aria-label="批量命令"]').setValue('display a\n\n display b ')
    await (wrapper.vm as unknown as { send(): Promise<void> }).send()
    const call = mocks.api.mock.calls.find(call => call[0] === '/api/terminal/batch-sends')!
    expect(JSON.parse(call[1].body)).toMatchObject({ session_ids: ['two'], text: 'display a\n\n display b ', mode: 'lines', interval_ms: 200, scope: 'selected' })
    expect(mocks.clone).not.toHaveBeenCalled()
  })
})

describe('release command sending without a details interface', () => {
  it('never renders a details entry or dialog before or after sending', async () => {
    const wrapper = await bar()
    await (wrapper.vm as unknown as { send(): Promise<void> }).send()
    await flushPromises()
    expect(wrapper.text()).not.toContain('发送详情')
    expect(wrapper.findAllComponents({ name: 'ElDialog' }).map(item => item.attributes('title'))).not.toContain('命令发送详情')
    expect(wrapper.find('el-table-stub').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Session ID')
    expect(wrapper.findAll('button').some(item => item.text().includes('重试失败目标'))).toBe(false)
  })
  it('reports partial writes without resending or changing the target list', async () => {
    vi.useFakeTimers()
    const wrapper = await bar()
    const original = mocks.api.getMockImplementation()!
    mocks.api.mockImplementation(async (url: string, options: unknown) => {
      if (url === '/api/terminal/batch-sends') return { id: 'partial', rows: [{ state: 'RUNNING' }, { state: 'WAITING' }] }
      if (url === '/api/terminal/batch-sends/partial') return { id: 'partial', rows: [{ state: 'SENT' }, { state: 'FAILED' }] }
      return original(url, options)
    })
    await wrapper.get('select[aria-label="发送目标"]').setValue('all')
    await wrapper.get('textarea[aria-label="批量命令"]').setValue('display a\r\n\n display b ')
    await (wrapper.vm as unknown as { send(): Promise<void> }).send()
    expect(mocks.info).toHaveBeenCalledWith('命令发送中')
    await vi.advanceTimersByTimeAsync(300)
    expect(mocks.warning).toHaveBeenCalledWith('命令已写入 1 个终端，1 个目标未确认发送')
    const sends = mocks.api.mock.calls.filter(call => call[0] === '/api/terminal/batch-sends')
    expect(sends).toHaveLength(1)
    expect(JSON.parse(sends[0]![1].body)).toMatchObject({ session_ids: ['one', 'two'], text: 'display a\r\n\n display b ', scope: 'all' })
    await vi.advanceTimersByTimeAsync(900)
    expect(mocks.api.mock.calls.filter(call => call[0] === '/api/terminal/batch-sends/partial')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('发送详情')
  })
  it('tracks overlapping sends independently and never reports device execution success', async () => {
    vi.useFakeTimers()
    const wrapper = await bar()
    let index = 0
    const original = mocks.api.getMockImplementation()!
    mocks.api.mockImplementation(async (url: string, options: unknown) => {
      if (url === '/api/terminal/batch-sends') return { id: `job-${++index}`, rows: [{ state: 'WAITING' }] }
      if (url.startsWith('/api/terminal/batch-sends/job-')) return { id: url.split('/').at(-1), rows: [{ state: 'SENT' }] }
      return original(url, options)
    })
    const vm = wrapper.vm as unknown as { send(): Promise<void> }
    await vm.send()
    await wrapper.setProps({ active: sessions[1] })
    await vm.send()
    await vi.advanceTimersByTimeAsync(300)
    const sends = mocks.api.mock.calls.filter(call => call[0] === '/api/terminal/batch-sends')
    expect(sends.map(call => JSON.parse(call[1].body).session_ids)).toEqual([['one'], ['two']])
    expect(mocks.success).toHaveBeenCalledTimes(2)
    expect(mocks.success).toHaveBeenCalledWith('命令已写入 1 个终端')
    expect(mocks.error).not.toHaveBeenCalled()
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(1200)
    expect(mocks.api.mock.calls.filter(call => String(call[0]).startsWith('/api/terminal/batch-sends/job-'))).toHaveLength(2)
  })
})

it('keeps explicit Session IDs authoritative when the same device is also selected', async () => {
  const wrapper = await bar()
  await wrapper.setProps({ sessions: sessions.map(item => ({ ...item, device_uuid: 'same-device' })), selected: ['two'], selectedDevices: [{ device_uuid: 'same-device', name: 'AC' }] })
  await wrapper.get('select[aria-label="发送目标"]').setValue('selected')
  await (wrapper.vm as unknown as { send(): Promise<void> }).send()
  const call = mocks.api.mock.calls.find(item => item[0] === '/api/terminal/batch-sends')!
  expect(JSON.parse(call[1].body).session_ids).toEqual(['two'])
})
