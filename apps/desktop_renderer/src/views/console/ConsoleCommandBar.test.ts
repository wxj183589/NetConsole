// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ConsoleCommandBar from './ConsoleCommandBar.vue'
import type { TerminalSession } from '../../api/terminal'

const mocks = vi.hoisted(() => ({ api: vi.fn(), save: vi.fn(), clone: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn(), confirm: vi.fn(async () => undefined) }))
vi.mock('../../api/client', () => ({ apiRequest: mocks.api }))
vi.mock('../../api/terminal', async original => ({ ...await original<object>(), cloneTerminalSession: mocks.clone }))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: mocks.save }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessage: { error: mocks.error, success: mocks.success, info: mocks.info, warning: mocks.warning }, ElMessageBox: { confirm: mocks.confirm } }))
const sessions = [{ session_id: 'one', state: 'RUNNING', device_name: 'AC1' }, { session_id: 'two', state: 'RUNNING', device_name: 'AC2' }] as TerminalSession[]
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.clearAllMocks()
  mocks.api.mockImplementation(async (url: string) => url === '/api/terminal/quick-buttons' ? { version: 1, groups: [{ id: 'group-0', name: 'H3C', buttons: [{ id: 'version', name: '版本', action: 'SEND_STRING', text: 'display version\\r', color: '#409eff', tooltip: '', disable_tooltip: false, order: 0, enabled: true }] }] } : { id: 'job-one', rows: [] })
})

it('runs a bounded script through the Session batch API and displays output', async () => {
  const script = JSON.stringify({ version: 1, steps: [{ type: 'SEND_STRING', text: String.raw`display version\r` }] })
  mocks.api.mockImplementation(async (url: string) => {
    if (url === '/api/terminal/quick-buttons') return { version: 1, groups: [{ id: 'group-0', name: 'H3C', buttons: [{ id: 'script', name: '只读采集', action: 'RUN_SCRIPT', text: script, color: '#409eff', tooltip: '', disable_tooltip: false, order: 0, enabled: true }] }] }
    if (url === '/api/terminal/batch-sends') return { id: 'script-job', rows: [{ state: 'SENT', output: 'Comware 7.1' }] }
    return { id: 'script-job', rows: [{ state: 'SENT', output: 'Comware 7.1' }] }
  })
  const wrapper = await bar()
  await wrapper.findAll('.command-bar > .quick-buttons button').find(button => button.text() === '显示按钮栏')!.trigger('click')
  await wrapper.get('.mapped-button-bar button').trigger('click')
  await flushPromises()
  expect(JSON.parse(mocks.api.mock.calls.find(call => call[0] === '/api/terminal/batch-sends')![1].body)).toMatchObject({ session_ids: ['one'], text: String.raw`display version\r`, mode: 'escaped' })
  expect(wrapper.get('.script-output').text()).toContain('Comware 7.1')
  expect(wrapper.text()).toContain('完成')
})

it('keeps every script step on its initially confirmed terminal', async () => {
  const script = JSON.stringify({ version: 1, steps: [
    { type: 'SEND_STRING', text: String.raw`display version\r` },
    { type: 'WAIT', milliseconds: 60 },
    { type: 'SEND_STRING', text: String.raw`display clock\r` },
  ] })
  mocks.api.mockImplementation(async (url: string) => url === '/api/terminal/quick-buttons'
    ? { version: 1, groups: [{ id: 'group-0', name: 'H3C', buttons: [{ id: 'script', name: '采集', action: 'RUN_SCRIPT', text: script, color: '#409eff', tooltip: '', disable_tooltip: false, order: 0, enabled: true }] }] }
    : { id: 'script-job', rows: [{ state: 'SENT', output: '' }] })
  const wrapper = await bar()
  await wrapper.findAll('.command-bar > .quick-buttons button').find(button => button.text() === '显示按钮栏')!.trigger('click')
  await wrapper.get('.mapped-button-bar button').trigger('click')
  await flushPromises()
  await wrapper.setProps({ active: sessions[1] })
  await new Promise(resolve => setTimeout(resolve, 100))
  await flushPromises()
  const sends = mocks.api.mock.calls.filter(call => call[0] === '/api/terminal/batch-sends')
  expect(sends).toHaveLength(2)
  expect(sends.map(call => JSON.parse(call[1].body).session_ids)).toEqual([['one'], ['one']])
})
afterEach(() => { wrappers.splice(0).forEach(item => item.unmount()); vi.useRealTimers() })
async function bar() { const wrapper = mount(ConsoleCommandBar, { props: { sessions, active: sessions[0]!, selected: ['two'], selectedDevices: [] }, global: { stubs: { ElDialog: { template: '<div><slot /><slot name="footer" /></div>' }, ElTable: true, ElTableColumn: true } } }); wrappers.push(wrapper); await flushPromises(); return wrapper }
describe('console commands keep explicit target semantics', () => {
  it('defaults to current session and sends a saved quick button only there', async () => {
    const wrapper = await bar()
    expect(wrapper.get('select[aria-label="发送目标"]').element).toHaveProperty('value', 'current')
    expect(wrapper.get('.command-bar > .quick-buttons').text()).toContain('管理按钮')
    expect(wrapper.find('.mapped-button-bar').exists()).toBe(false)
    expect((wrapper.get('.command-input').element as HTMLElement).style.display).toBe('none')
    await wrapper.get('.command-bar > .quick-buttons button').trigger('click')
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

it('shows the selected button group in the collapsible bar and sends from it', async () => {
  const wrapper = await bar()
  await wrapper.findAll('.command-bar > .quick-buttons button').find(button => button.text() === '显示按钮栏')!.trigger('click')
  expect(wrapper.get('.mapped-button-bar').text()).toContain('版本')
  await wrapper.get('.mapped-button-bar button').trigger('click')
  await flushPromises()
  const call = mocks.api.mock.calls.find(call => call[0] === '/api/terminal/batch-sends')!
  expect(JSON.parse(call[1].body)).toMatchObject({ session_ids: ['one'], scope: 'current', button_id: 'version' })
})

it('routes Menu Function buttons through the active terminal action event', async () => {
  mocks.api.mockImplementation(async (url: string) => url === '/api/terminal/quick-buttons' ? {
    version: 1,
    groups: [{ id: 'group-0', name: 'H3C', buttons: [{ id: 'clear', name: '清屏', action: 'MENU_FUNCTION', text: 'clear-screen', color: '#409eff', tooltip: '', disable_tooltip: false, order: 0, enabled: true }] }],
  } : { id: 'job-one', rows: [] })
  const wrapper = await bar()
  await wrapper.findAll('.command-bar > .quick-buttons button').find(button => button.text() === '显示按钮栏')!.trigger('click')
  await wrapper.get('.mapped-button-bar button').trigger('click')
  expect(wrapper.emitted('menuAction')).toEqual([['clear-screen']])
  expect(mocks.api.mock.calls.some(call => call[0] === '/api/terminal/batch-sends')).toBe(false)
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

it('sends batch scheduling settings and exposes pause, cancel and export controls', async () => {
  const wrapper = await bar()
  await wrapper.get('.command-bar > .quick-buttons button').trigger('click')
  const batchButton = wrapper.findAll('button').find(button => button.text() === '批量命令')!
  await batchButton.trigger('click')
  await wrapper.get('select[aria-label="批量执行方式"]').setValue('sequential')
  await wrapper.get('input[aria-label="单设备超时"]').setValue('30')
  await wrapper.get('input[aria-label="批量总超时"]').setValue('180')
  await wrapper.get('input[aria-label="失败重试次数"]').setValue('1')
  await (wrapper.vm as unknown as { send(): Promise<void> }).send()
  const request = mocks.api.mock.calls.find(call => call[0] === '/api/terminal/batch-sends')!
  expect(JSON.parse(request[1].body)).toMatchObject({ execution_mode: 'sequential', device_timeout: 30, total_timeout: 180, max_retries: 1 })
  expect(wrapper.find('[aria-label="批量写入状态"]').exists()).toBe(true)
})

it('validates Send String before saving or sending a configured button', async () => {
  const wrapper = await bar()
  await wrapper.get('.command-bar > .quick-buttons button').trigger('click')
  await wrapper.get('textarea[aria-label="发送字符串"]').setValue(String.raw`display version\q`)
  await wrapper.findAll('button').find(button => button.text() === '保存配置')!.trigger('click')
  await flushPromises()
  expect(mocks.api.mock.calls.some(call => call[0] === '/api/terminal/quick-buttons' && call[1]?.method === 'PUT')).toBe(false)
  expect(mocks.error).toHaveBeenCalledWith(expect.stringContaining('unsupported escape'))

  const invalidImport = {
    version: 1,
    groups: [{
      id: 'imported',
      name: 'Imported',
      buttons: [{ id: 'bad', name: 'Bad', action: 'RUN_SCRIPT', text: 'echo', color: '#409eff', tooltip: '', disable_tooltip: false, order: 0, enabled: true }],
    }],
  }
  const fileInput = wrapper.get('input[type="file"]')
  Object.defineProperty(fileInput.element, 'files', {
    configurable: true,
    value: [new File([JSON.stringify(invalidImport)], 'buttons.json', { type: 'application/json' })],
  })
  await fileInput.trigger('change')
  await flushPromises()
  expect(mocks.api.mock.calls.some(call => call[0] === '/api/terminal/quick-buttons' && call[1]?.method === 'PUT')).toBe(false)

  await wrapper.findAll('.quick-buttons button').find(button => button.text() === '版本')!.trigger('click')
  await flushPromises()
  expect(mocks.api.mock.calls.some(call => call[0] === '/api/terminal/batch-sends')).toBe(false)
})

it('offers retry only for a failed row and follows the new retry job', async () => {
  const wrapper = await bar()
  const original = mocks.api.getMockImplementation()!
  mocks.api.mockImplementation(async (url: string, options: unknown) => {
    if (url === '/api/terminal/batch-sends') return { id: 'first-job', rows: [{ session_id: 'one', state: 'FAILED', error: 'offline' }] }
    if (url === '/api/terminal/batch-sends/first-job/retry/one') return { id: 'retry-job', rows: [{ session_id: 'one', state: 'SENT' }] }
    return original(url, options)
  })
  await wrapper.get('.command-bar > .quick-buttons button').trigger('click')
  await wrapper.findAll('button').find(button => button.text() === '批量命令')!.trigger('click')
  await (wrapper.vm as unknown as { send(): Promise<void> }).send()
  await flushPromises()
  const retryButton = wrapper.findAll('button').find(button => button.text() === '重试该设备')
  expect(retryButton).toBeDefined()
  await retryButton!.trigger('click')
  await flushPromises()
  expect(mocks.api.mock.calls.some(call => call[0] === '/api/terminal/batch-sends/first-job/retry/one' && call[1]?.method === 'POST')).toBe(true)
  expect(wrapper.text()).toContain('SENT')
})
