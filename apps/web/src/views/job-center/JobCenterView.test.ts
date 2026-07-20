import { createRenderer, defineComponent, h, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import JobCenterView from './JobCenterView.vue'
import source from './JobCenterView.vue?raw'

const platformMocks = vi.hoisted(() => ({
  download: vi.fn(),
  open: vi.fn(),
  reveal: vi.fn(),
  reportReady: vi.fn(),
}))
const routeState = vi.hoisted(() => ({ query: {} as Record<string, string>, path: '', name: undefined as string | undefined }))
const messageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: platformMocks.download,
  getPlatformAdapter: () => ({
    openPath: platformMocks.open,
    showItemInFolder: platformMocks.reveal,
    reportRendererReady: platformMocks.reportReady,
  }),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('element-plus', async () => {
  const { defineComponent, h } = await import('vue')
  const passthrough = (tag: string) => defineComponent({
    inheritAttrs: false,
    setup(_props, { attrs, slots }) {
      return () => h(tag, attrs, slots.default?.())
    },
  })
  const empty = defineComponent(() => () => h('empty-component'))
  return {
    ElAlert: passthrough('alert'),
    ElButton: passthrough('button'),
    ElDescriptions: passthrough('descriptions'),
    ElDescriptionsItem: passthrough('descriptions-item'),
    ElDrawer: passthrough('drawer'),
    ElEmpty: empty,
    ElInput: empty,
    ElLoadingDirective: {},
    ElMessage: messageMocks,
    ElOption: empty,
    ElProgress: empty,
    ElSelect: passthrough('select'),
    ElTable: empty,
    ElTableColumn: empty,
    ElTooltip: passthrough('tooltip'),
  }
})

vi.mock('@element-plus/icons-vue', () => ({
  CopyDocument: {},
  Refresh: {},
  View: {},
}))

vi.mock('../../components/NcStatusTag.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent(() => () => h('status-tag')) }
})

vi.mock('../../components/table/NcDataTable.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent((_props, { slots }) => () => h('data-table', slots.default?.())) }
})

vi.mock('element-plus/es', async () => {
  const { defineComponent, h } = await import('vue')
  const passthrough = (tag: string) => defineComponent({
    inheritAttrs: false,
    setup(_props, { attrs, slots }) {
      return () => h(tag, attrs, slots.default?.())
    },
  })
  const empty = defineComponent(() => () => h('empty-component'))
  return {
    ElAlert: passthrough('alert'),
    ElButton: passthrough('button'),
    ElMessage: messageMocks,
    ElDescriptions: passthrough('descriptions'),
    ElDescriptionsItem: passthrough('descriptions-item'),
    ElDrawer: passthrough('drawer'),
    ElEmpty: empty,
    ElInput: empty,
    ElLoadingDirective: {},
    ElOption: empty,
    ElProgress: empty,
    ElSelect: passthrough('select'),
    ElTable: empty,
    ElTableColumn: empty,
    ElTooltip: passthrough('tooltip'),
  }
})

interface HostNode {
  type: string
  text: string
  parent: HostNode | null
  children: HostNode[]
  props: Record<string, unknown>
}

function node(type: string, text = ''): HostNode {
  return { type, text, parent: null, children: [], props: {} }
}

const renderer = createRenderer<HostNode, HostNode>({
  patchProp(element, key, _previous, next) {
    if (next == null) delete element.props[key]
    else element.props[key] = next
  },
  insert(child, parent, anchor) {
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove(child) {
    if (!child.parent) return
    const index = child.parent.children.indexOf(child)
    if (index >= 0) child.parent.children.splice(index, 1)
    child.parent = null
  },
  createElement(type) {
    return node(type)
  },
  createText(text) {
    return node('#text', text)
  },
  createComment(text) {
    return node('#comment', text)
  },
  setText(target, text) {
    target.text = text
  },
  setElementText(target, text) {
    target.text = text
    target.children = []
  },
  parentNode(target) {
    return target.parent
  },
  nextSibling(target) {
    if (!target.parent) return null
    const index = target.parent.children.indexOf(target)
    return target.parent.children[index + 1] ?? null
  },
  querySelector() {
    return null
  },
  setScopeId() {},
  cloneNode(target) {
    return { ...target, parent: null, children: [...target.children], props: { ...target.props } }
  },
  insertStaticContent(content, parent, anchor) {
    const target = node('#static', content)
    target.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(target)
    else parent.children.splice(index, 0, target)
    return [target, target]
  },
})

function task(id: string): TaskItem {
  return {
    id,
    type: 'device_export',
    name: `任务 ${id}`,
    status: 'COMPLETED',
    progress: 100,
    phase: '',
    stage: '',
    message: '',
    site_name: '',
    owner: 'device_export_process',
    executor: 'local-process',
    source: 'local',
    device_id: '',
    device_name: '',
    agent: '',
    mr_name: '',
    session_id: '',
    mapping_state: 'MAPPED',
    created_time: '',
    started_time: '',
    finished_time: '',
    updated_time: '',
    duration_seconds: 0,
    error_code: '',
    error_summary: '',
    has_warning: false,
    snapshot_id: null,
    records_count: null,
    parser_version: '',
    cancellable: true,
    artifact_download: {
      artifact_id: `artifact-${id}`,
      display_name: `设备-${id}.xlsx`,
      size_bytes: 42,
      media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      api_path: `/api/device-management/exports/${id}/download`,
      query: {},
    },
  }
}

function descendants(root: HostNode): HostNode[] {
  return root.children.flatMap((child) => [child, ...descendants(child)])
}

function textContent(target: HostNode): string {
  return target.text + target.children.map(textContent).join('')
}

function findButton(root: HostNode, label: string): HostNode | undefined {
  return descendants(root).find((target) => target.type === 'button' && textContent(target).includes(label))
}

function alertTitles(root: HostNode): string[] {
  return descendants(root)
    .filter((target) => target.type === 'alert')
    .map((target) => String(target.props.title || ''))
}

async function click(target: HostNode): Promise<void> {
  const handler = target.props.onClick as (() => unknown) | undefined
  expect(handler).toBeTypeOf('function')
  await handler?.()
  await nextTick()
}

describe('Job Center saved artifact capability lifecycle', () => {
  it('uses the unified data table contract', () => {
    expect(source).toContain('table-id="job-center-tasks"')
    expect(source).toContain(':columns="columns"')
    expect(source).not.toContain('<el-table')
  })

  beforeEach(() => {
    vi.clearAllMocks()
    routeState.query = {}
    routeState.path = ''
    routeState.name = undefined
    platformMocks.open.mockResolvedValue({ success: true })
    platformMocks.reveal.mockResolvedValue({ success: true })
    vi.stubGlobal('document', {
      hidden: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('only renders authorized actions and clears stale capabilities on every lifecycle boundary', async () => {
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'requestCancel').mockResolvedValue(undefined)
    store.selected = task('A')

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()

    const drawer = descendants(root).find((target) => target.type === 'drawer')
    const showDrawer = drawer?.props['onUpdate:modelValue'] as ((value: boolean) => void) | undefined
    expect(showDrawer).toBeTypeOf('function')
    showDrawer?.(true)
    await nextTick()

    expect(findButton(root, '打开文件')).toBeUndefined()
    expect(findButton(root, '打开所在目录')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-A' })
    await click(findButton(root, 'Artifact 下载')!)
    await click(findButton(root, '打开文件')!)
    await click(findButton(root, '打开所在目录')!)
    expect(platformMocks.open).toHaveBeenCalledWith('cap-A')
    expect(platformMocks.reveal).toHaveBeenCalledWith('cap-A')
    expect(messageMocks.success).toHaveBeenCalledWith('已请求系统打开文件')
    expect(messageMocks.success).toHaveBeenCalledWith('已在文件夹中定位')

    platformMocks.open.mockResolvedValueOnce({ success: false, error: '文件授权已过期' })
    await click(findButton(root, '打开文件')!)
    expect(alertTitles(root)).toContain('文件授权已过期，请重新下载后再试')
    expect(messageMocks.error).toHaveBeenCalledWith('文件授权已过期，请重新下载后再试')
    store.selected = task('A-switched')
    await nextTick()
    expect(alertTitles(root)).not.toContain('文件授权已过期，请重新下载后再试')
    store.selected = task('A')
    await nextTick()

    let finishDownload: (result: { status: 'failed'; error: string }) => void = () => undefined
    platformMocks.download.mockReturnValueOnce(new Promise((resolve) => { finishDownload = resolve }))
    const failedDownload = (findButton(root, 'Artifact 下载')!.props.onClick as () => Promise<void>)()
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()
    finishDownload({ status: 'failed', error: '取消保存' })
    await failedDownload
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'cancelled' })
    await click(findButton(root, 'Artifact 下载')!)
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'saved' })
    await click(findButton(root, 'Artifact 下载')!)
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-A2' })
    await click(findButton(root, 'Artifact 下载')!)
    store.selected = task('B')
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()

    let finishStaleDownload: (result: { status: 'saved'; capabilityId: string }) => void = () => undefined
    store.selected = task('A')
    await nextTick()
    platformMocks.download.mockReturnValueOnce(new Promise((resolve) => { finishStaleDownload = resolve }))
    const staleDownload = (findButton(root, 'Artifact 下载')!.props.onClick as () => Promise<void>)()
    store.selected = task('B')
    await nextTick()
    finishStaleDownload({ status: 'saved', capabilityId: 'stale-cap-A' })
    await staleDownload
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-B' })
    await click(findButton(root, 'Artifact 下载')!)
    platformMocks.open.mockResolvedValueOnce({ success: false, error: '系统未能打开所选路径 C:\\private\\secret.xlsx' })
    await click(findButton(root, '打开文件')!)
    expect(alertTitles(root)).toContain('系统未能打开文件，请检查文件关联后重试')
    expect(textContent(root)).not.toContain('C:\\private\\secret.xlsx')
    showDrawer?.(false)
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()
    expect(alertTitles(root)).not.toContain('系统未能打开文件，请检查文件关联后重试')

    showDrawer?.(true)
    await nextTick()
    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-B2' })
    await click(findButton(root, 'Artifact 下载')!)
    await click(findButton(root, '停止 / 取消')!)
    expect(findButton(root, '打开文件')).toBeUndefined()

    app.unmount()
  })

  it('reports the independent task window as interactive and keeps the list when a task id is missing', async () => {
    routeState.query = { module: 'rail', task_id: 'missing-task', task_window: '1' }
    routeState.path = '/desktop/tasks'
    routeState.name = 'desktop-tasks'
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'selectTask').mockRejectedValue(new Error('not found'))

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)

    await vi.waitFor(() => expect(platformMocks.reportReady).toHaveBeenCalledWith(true, 'interactive', 'task-window'))
    expect(store.selectTask).toHaveBeenCalledWith('missing-task')
    await vi.waitFor(() => expect(messageMocks.warning).toHaveBeenCalledWith('未找到任务 missing-task，已保留当前任务列表。'))
    await nextTick()
    expect(alertTitles(root)).toContain('未找到任务 missing-task，已保留当前任务列表。')
    app.unmount()
  })

  it('reports the task window as interactive even when polling cannot start', async () => {
    routeState.query = { module: 'rail', task_window: '1' }
    routeState.path = '/desktop/tasks'
    routeState.name = 'desktop-tasks'
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => { throw new Error('polling unavailable') })
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()

    expect(platformMocks.reportReady).toHaveBeenCalledWith(true, 'interactive', 'task-window')
    expect(messageMocks.error).toHaveBeenCalledWith('任务列表自动刷新启动失败，可手动刷新后重试。')
    expect(alertTitles(root)).toContain('任务列表自动刷新启动失败，可手动刷新后重试。')
    app.unmount()
    expect(store.releasePolling).toHaveBeenCalledWith('job-center-view')
  })
})
