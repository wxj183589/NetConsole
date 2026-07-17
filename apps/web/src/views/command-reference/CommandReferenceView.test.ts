// @vitest-environment happy-dom

import { defineComponent, h, useAttrs, type Component } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from '../../api/client'
import { setAppLocale } from '../../i18n/runtime'
import type { CommandReferencePage } from '../../types/commandReference'

const taskId = 'command-reference-export-0123456789abcdef0123456789abcdef'
const taskStorageKey = 'netconsole.command-reference.current-export-task-id.v1'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  start: vi.fn(),
  get: vi.fn(),
  cancel: vi.fn(),
  download: vi.fn(),
  openTaskWindow: vi.fn(),
  routerPush: vi.fn(),
  hostType: 'electron' as 'browser' | 'electron',
  routeQuery: {} as Record<string, string>,
  messages: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('../../api/commandReference', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../api/commandReference')>(),
  listCommandReferences: mocks.list,
  startCommandReferenceExport: mocks.start,
  getCommandReferenceExport: mocks.get,
  cancelCommandReferenceExport: mocks.cancel,
}))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: mocks.download,
  getPlatformAdapter: () => ({ openTaskWindow: mocks.openTaskWindow }),
  getRuntimeConfig: () => ({ hostType: mocks.hostType }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: mocks.routeQuery }),
  useRouter: () => ({ push: mocks.routerPush }),
}))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: mocks.messages,
}))

import CommandReferenceView from './CommandReferenceView.vue'

const page: CommandReferencePage = {
  items: [{
    id: 'switch_display_version', module: '交换机巡检', device_scope: '交换机', vendor: 'H3C', protocol: 'SSH', category: '设备信息',
    command_template: 'display version', parameters: [], pre_commands: ['screen-length disable'], purpose: '查看设备版本', output_log: 'version.log',
    parser: 'VersionParser', consumer: '交换机巡检', risk_level: 'read_only', interactive_input: false, is_cli: true,
    read_only: true, modifies_device_config: false, requires_interactive_confirmation: false,
    source_locations: ['src/netconsole/example.py'], zte_adaptation_status: 'not_applicable', comware_command: 'display version', zte_command: '',
    parser_status: '已适配', notes: '只读命令',
  }],
  filters: { modules: ['交换机巡检'], device_scopes: ['交换机'], vendors: ['H3C'], protocols: ['SSH'], categories: ['设备信息'], risk_levels: ['read_only'] },
  summary: { total: 79, shown: 1, switch_count: 31, non_cli_count: 23 },
}

function exportTask(overrides: Record<string, unknown> = {}) {
  return {
    id: taskId, type: 'web_export_command_reference_markdown', name: '命令说明 Markdown 导出', status: 'RUNNING',
    progress: 10, stage: 'write', current: 1, total: 2, message: '正在导出', error_message: '', cancellable: true, result: {},
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, [slots.header?.(), slots.default?.()])
  },
})

const buttonStub = defineComponent({
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', { ...attrs, disabled: props.disabled || props.loading, onClick: () => emit('click') }, slots.default?.())
  },
})

const inputStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue', 'keyup'],
  setup(props, { attrs, emit }) {
    return () => h('input', {
      ...attrs,
      value: props.modelValue,
      onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
      onKeyup: (event: KeyboardEvent) => emit('keyup', event),
    })
  },
})

const descriptionStub = defineComponent({
  props: { label: String },
  setup(props, { slots }) { return () => h('div', [h('strong', props.label), slots.default?.()]) },
})

const tableColumnStub = defineComponent({
  props: { label: String },
  setup(props) { return () => h('span', props.label) },
})

const emptyStub = defineComponent({ props: { description: String }, setup: (props) => () => h('div', props.description) })
const alertStub = defineComponent({
  props: { title: String },
  setup(props, { slots }) { return () => h('div', [h('strong', props.title), slots.default?.()]) },
})

const elementStubs: Record<string, Component> = {
  ElAlert: alertStub, ElButton: buttonStub, ElCard: passthrough, ElDescriptions: passthrough,
  ElDescriptionsItem: descriptionStub, ElEmpty: emptyStub, ElInput: inputStub, ElOption: passthrough,
  ElSelect: passthrough, ElTable: passthrough, ElTableColumn: tableColumnStub,
}

async function renderView(): Promise<VueWrapper> {
  const wrapper = mount(CommandReferenceView, {
    attachTo: document.body,
    global: { directives: { loading: () => undefined }, stubs: elementStubs },
  })
  await flushPromises()
  return wrapper
}

function button(wrapper: VueWrapper, text: string) {
  const result = wrapper.findAll('button').find((item) => item.text() === text)
  if (!result) throw new Error(`找不到按钮：${text}`)
  return result
}

beforeEach(() => {
  vi.useFakeTimers()
  setAppLocale('zh_CN')
  mocks.routeQuery = {}
  mocks.list.mockReset().mockResolvedValue(structuredClone(page))
  mocks.start.mockReset().mockResolvedValue(exportTask())
  mocks.get.mockReset().mockResolvedValue(exportTask())
  mocks.cancel.mockReset().mockResolvedValue({ id: taskId, status: 'STOPPING', message: '已请求停止任务' })
  mocks.download.mockReset().mockResolvedValue({ status: 'saved' })
  mocks.openTaskWindow.mockReset().mockResolvedValue({ success: true })
  mocks.routerPush.mockReset().mockResolvedValue(undefined)
  mocks.hostType = 'electron'
  Object.values(mocks.messages).forEach((item) => item.mockReset())
  localStorage.clear()
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
  localStorage.clear()
})

describe('Command Reference mounted behavior', () => {
  it('debounces textChanged queries, sends empty queries, and ignores stale responses', async () => {
    const wrapper = await renderView()
    const input = wrapper.get('input[placeholder="搜索命令、用途、模块、源码位置"]')
    const first = deferred<CommandReferencePage>()
    const second = deferred<CommandReferencePage>()
    mocks.list.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise)

    await input.setValue('display')
    await vi.advanceTimersByTimeAsync(249)
    expect(mocks.list).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ query: 'display' }))

    await input.setValue('save')
    await vi.advanceTimersByTimeAsync(250)
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ query: 'save' }))
    second.resolve({ ...structuredClone(page), items: [{ ...page.items[0], command_template: 'save force' }] })
    await flushPromises()
    first.resolve({ ...structuredClone(page), items: [{ ...page.items[0], command_template: 'stale command' }] })
    await flushPromises()
    expect(wrapper.text()).toContain('save force')
    expect(wrapper.text()).not.toContain('stale command')

    mocks.list.mockResolvedValueOnce(structuredClone(page))
    await input.setValue('')
    await vi.advanceTimersByTimeAsync(250)
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ query: '' }))
  })

  it('renders Qt facts, copies commands, and opens the Electron task window', async () => {
    const wrapper = await renderView()
    expect(wrapper.text()).toContain('前置条件')
    expect(wrapper.text()).toContain('是否只读')
    expect(wrapper.text()).toContain('是否修改设备配置')
    expect(wrapper.text()).toContain('是否存在交互确认')

    await button(wrapper, '复制命令模板').trigger('click')
    await button(wrapper, '导出 Markdown').trigger('click')
    await flushPromises()
    await button(wrapper, '打开统一任务窗口').trigger('click')
    await flushPromises()

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('display version')
    expect(mocks.openTaskWindow).toHaveBeenCalledWith({ taskId, module: 'command-reference', status: 'RUNNING' })
    expect(mocks.routerPush).not.toHaveBeenCalled()

    mocks.hostType = 'browser'
    await button(wrapper, '打开统一任务窗口').trigger('click')
    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'tasks', query: { task_id: taskId, module: 'command-reference', status: 'RUNNING' },
    })
  })

  it('polls PENDING through COMPLETED and enables the artifact download', async () => {
    mocks.start.mockResolvedValueOnce(exportTask({ status: 'PENDING', progress: 0, cancellable: true }))
    mocks.get
      .mockResolvedValueOnce(exportTask({ status: 'RUNNING', progress: 60 }))
      .mockResolvedValueOnce(exportTask({
        status: 'COMPLETED', progress: 100, cancellable: false,
        result: { artifact_id: 'artifact-1', artifact_name: 'NetConsole_软件使用命令清单.md' },
      }))
    const wrapper = await renderView()

    await button(wrapper, '导出 Markdown').trigger('click')
    await flushPromises()
    expect(localStorage.getItem(taskStorageKey)).toBe(taskId)
    expect(button(wrapper, '下载 Artifact').attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(wrapper.text()).toContain('RUNNING')
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(wrapper.text()).toContain('COMPLETED')
    expect(button(wrapper, '下载 Artifact').attributes('disabled')).toBeUndefined()

    await button(wrapper, '下载 Artifact').trigger('click')
    await flushPromises()
    expect(mocks.download).toHaveBeenCalledWith({
      apiPath: '/api/command-reference/artifacts/artifact-1/download',
      suggestedName: 'NetConsole_软件使用命令清单.md',
    })
    await vi.advanceTimersByTimeAsync(5_000)
    expect(mocks.get).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('keeps polling STOPPING until the API reports a terminal cancellation', async () => {
    mocks.get
      .mockResolvedValueOnce(exportTask({ status: 'STOPPING', cancellable: false, message: '正在停止' }))
      .mockResolvedValueOnce(exportTask({ status: 'CANCELLED', cancellable: false, message: '已取消' }))
    const wrapper = await renderView()
    await button(wrapper, '导出 Markdown').trigger('click')
    await flushPromises()

    await button(wrapper, '取消').trigger('click')
    await flushPromises()
    expect(mocks.cancel).toHaveBeenCalledWith(taskId)
    expect(mocks.get).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('STOPPING')

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(mocks.get).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('CANCELLED')

    await vi.advanceTimersByTimeAsync(5_000)
    expect(mocks.get).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('recovers after a temporary refresh failure without clearing the task id', async () => {
    mocks.get
      .mockRejectedValueOnce(new ApiRequestError('后端暂时不可用', 503))
      .mockResolvedValueOnce(exportTask({
        status: 'COMPLETED', progress: 100, cancellable: false,
        result: { artifact_id: 'artifact-1', artifact_name: 'NetConsole_软件使用命令清单.md' },
      }))
    const wrapper = await renderView()
    await button(wrapper, '导出 Markdown').trigger('click')
    await flushPromises()

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(wrapper.text()).toContain('任务状态刷新暂时失败，正在重试')
    expect(localStorage.getItem(taskStorageKey)).toBe(taskId)

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(wrapper.text()).toContain('COMPLETED')
    expect(wrapper.text()).not.toContain('任务状态刷新暂时失败，正在重试')
    expect(button(wrapper, '下载 Artifact').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('does not request again after unmounting during STOPPING or an error retry delay', async () => {
    mocks.get.mockResolvedValueOnce(exportTask({ status: 'STOPPING', cancellable: false }))
    const stopping = await renderView()
    await button(stopping, '导出 Markdown').trigger('click')
    await flushPromises()
    await button(stopping, '取消').trigger('click')
    await flushPromises()
    expect(mocks.get).toHaveBeenCalledTimes(1)
    stopping.unmount()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(mocks.get).toHaveBeenCalledTimes(1)

    localStorage.clear()
    mocks.get.mockReset().mockRejectedValueOnce(new ApiRequestError('后端暂时不可用', 503))
    const retrying = await renderView()
    await button(retrying, '导出 Markdown').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(mocks.get).toHaveBeenCalledTimes(1)
    retrying.unmount()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(mocks.get).toHaveBeenCalledTimes(1)
  })

  it('stops polling when the export reaches FAILED', async () => {
    mocks.get.mockResolvedValueOnce(exportTask({ status: 'FAILED', cancellable: false, error_message: '导出失败' }))
    const wrapper = await renderView()
    await button(wrapper, '导出 Markdown').trigger('click')
    await flushPromises()

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()
    expect(wrapper.text()).toContain('FAILED')
    await vi.advanceTimersByTimeAsync(5_000)
    expect(mocks.get).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('clears damaged and missing persisted task ids', async () => {
    localStorage.setItem(taskStorageKey, 'damaged-task-id')
    const damaged = await renderView()
    expect(mocks.get).not.toHaveBeenCalled()
    expect(localStorage.getItem(taskStorageKey)).toBeNull()
    damaged.unmount()

    localStorage.setItem(taskStorageKey, taskId)
    mocks.get.mockRejectedValueOnce(new ApiRequestError('导出任务不存在', 404))
    const missing = await renderView()
    expect(mocks.get).toHaveBeenCalledWith(taskId)
    expect(localStorage.getItem(taskStorageKey)).toBeNull()
    expect(missing.text()).not.toContain(taskId)
    missing.unmount()
  })

  it('recovers a routed task and uses unified cancel and safe download contracts', async () => {
    mocks.routeQuery = { task_id: 'task-recovered' }
    mocks.get.mockResolvedValueOnce(exportTask({ id: 'task-recovered', status: 'RUNNING' }))
    const wrapper = await renderView()
    expect(mocks.get).toHaveBeenCalledWith('task-recovered')

    await button(wrapper, '取消').trigger('click')
    await flushPromises()
    expect(mocks.cancel).toHaveBeenCalledWith('task-recovered')
    expect(mocks.get).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    mocks.routeQuery = { task_id: 'task-completed' }
    mocks.get.mockReset().mockResolvedValue(exportTask({
      id: 'task-completed', status: 'COMPLETED', cancellable: false,
      result: { artifact_id: 'artifact-1', artifact_name: 'NetConsole_软件使用命令清单.md', sha256: 'abc' },
    }))
    const completed = await renderView()
    await button(completed, '下载 Artifact').trigger('click')
    await flushPromises()
    expect(mocks.download).toHaveBeenCalledWith({
      apiPath: '/api/command-reference/artifacts/artifact-1/download',
      suggestedName: 'NetConsole_软件使用命令清单.md',
    })
  })

  it('renders translated empty and error states from mounted behavior', async () => {
    mocks.list.mockResolvedValueOnce({ ...structuredClone(page), items: [], summary: { ...page.summary, shown: 0 } })
    const empty = await renderView()
    expect(empty.text()).toContain('当前筛选没有命令说明')
    empty.unmount()

    mocks.list.mockRejectedValueOnce(new Error('命令说明资源暂时不可用'))
    const failed = await renderView()
    expect(failed.text()).toContain('命令说明资源暂时不可用')
    expect(button(failed, '重试').exists()).toBe(true)
  })

  it('consumes the shared dynamic application locale', async () => {
    const wrapper = await renderView()
    setAppLocale('en_US')
    await flushPromises()

    expect(wrapper.text()).toContain('Command Reference')
    expect(wrapper.text()).toContain('Prerequisites')
    expect(wrapper.findAll('button').some((item) => item.text() === 'Open task window')).toBe(false)

    await button(wrapper, 'Export Markdown').trigger('click')
    await flushPromises()
    expect(button(wrapper, 'Open task window').exists()).toBe(true)
  })
})
