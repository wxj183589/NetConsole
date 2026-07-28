import { createRenderer, defineComponent, h, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import JobCenterView from './JobCenterView.vue'
import source from './JobCenterView.vue?raw'

it('uses Backend text integrity instead of guessing from replacement characters', () => {
  expect(source).toContain('historicalTextDamaged')
  expect(source).toContain("store.selected?.text_integrity === 'historical_corrupted'")
  expect(source).toContain("store.selected?.text_integrity === 'current_corrupted'")
  expect(source).toContain("store.selected?.text_integrity === 'unknown_corrupted'")
  expect(source).toContain('该历史日志由旧版本生成，文字已经发生编码损坏；没有原始字节时无法恢复。')
  expect(source).toContain('当前任务发生文本编码异常，请停止任务并查看应用日志。')
  expect(source).toContain('该任务包含已损坏文字，但无法确认产生版本。')
  expect(source).not.toContain("value.includes('\\uFFFD')")
})

it('describes task logs as expanded by default and keeps the manual toggle', () => {
  expect(source).toContain('默认展开；每秒读取最后 300 条结构化事件。')
  expect(source).toContain("store.logsExpanded ? '隐藏日志' : '显示日志'")
})

it('renders the controlled point-table preview summary instead of a generic empty record count', () => {
  expect(source).toContain('showPointTablePreviewResult')
  expect(source).toContain('生成节点数')
  expect(source).toContain('等待用户保存')
  expect(source).toContain("stringDetail('target_train_display', stringDetail('target_train'))")
})

const platformMocks = vi.hoisted(() => ({
  download: vi.fn(),
  open: vi.fn(),
  reveal: vi.fn(),
  reportReady: vi.fn(),
}))
const routeState = vi.hoisted(() => ({ query: {} as Record<string, string>, path: '', name: undefined as string | undefined }))
const messageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  info: vi.fn(),
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
    ElSwitch: passthrough('switch'),
    ElTable: empty,
    ElTableColumn: empty,
    ElTooltip: passthrough('tooltip'),
  }
})

vi.mock('@element-plus/icons-vue', () => ({
  Check: {},
  CopyDocument: {},
  Delete: {},
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
    ElSwitch: passthrough('switch'),
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
    text_integrity: 'ok',
    text_integrity_reason: '',
    snapshot_id: null,
    records_count: null,
    parser_version: '',
    cancellable: true,
    artifact_download: {
      artifact_id: `artifact-${id}`,
      display_name: `设备-${id}.xlsx`,
      size_bytes: 42,
      sha256: 'a'.repeat(64),
      media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      api_path: `/api/device-management/exports/${id}/download`,
      query: {},
    },
  }
}

function tracksideExportTask(id: string): TaskItem {
  const base = task(id)
  return {
    ...base,
    type: 'web_export_trackside_ap_business',
    name: '轨旁 AP 业务导出',
    owner: 'web_rail_transit',
    module: 'rail',
    artifact_download: {
      artifact_id: `artifact-${id}`,
      display_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
      size_bytes: 128,
      media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      api_path: `/api/job-center/artifacts/artifact-${id}`,
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

  it('shows distinct current and historical encoding states from Backend metadata', async () => {
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    store.selected = {
      ...task('current-corrupted'),
      status: 'RUNNING',
      message: '当前�异常',
      text_integrity: 'current_corrupted',
      text_integrity_reason: 'replacement_character_detected_in_current_event',
    }

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()

    expect(alertTitles(root)).toContain('当前任务发生文本编码异常，请停止任务并查看应用日志。')
    expect(alertTitles(root)).not.toContain('该历史日志由旧版本生成，文字已经发生编码损坏；没有原始字节时无法恢复。')

    store.selected = {
      ...task('historical-corrupted'),
      message: '历史�异常',
      text_integrity: 'historical_corrupted',
      text_integrity_reason: 'legacy_task_before_encoding_fix',
    }
    await nextTick()
    expect(alertTitles(root)).toContain('该历史日志由旧版本生成，文字已经发生编码损坏；没有原始字节时无法恢复。')
    expect(alertTitles(root)).not.toContain('当前任务发生文本编码异常，请停止任务并查看应用日志。')

    store.selected = {
      ...task('unknown-corrupted'),
      text_integrity: 'unknown_corrupted',
      text_integrity_reason: 'corrupted_text_producer_version_unknown',
    }
    await nextTick()
    expect(alertTitles(root)).toContain('该任务包含已损坏文字，但无法确认产生版本。')

    store.selected = task('normal')
    await nextTick()
    expect(alertTitles(root)).not.toContain('该历史日志由旧版本生成，文字已经发生编码损坏；没有原始字节时无法恢复。')
    expect(alertTitles(root)).not.toContain('当前任务发生文本编码异常，请停止任务并查看应用日志。')
    expect(alertTitles(root)).not.toContain('该任务包含已损坏文字，但无法确认产生版本。')
    app.unmount()
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
    await click(findButton(root, '另存 Artifact')!)
    expect(platformMocks.download).toHaveBeenCalledWith(expect.objectContaining({
      expectedSizeBytes: 42,
      expectedSha256: 'a'.repeat(64),
    }))
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
    const failedDownload = (findButton(root, '另存 Artifact')!.props.onClick as () => Promise<void>)()
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()
    finishDownload({ status: 'failed', error: '取消保存' })
    await failedDownload
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'cancelled' })
    await click(findButton(root, '另存 Artifact')!)
    expect(findButton(root, '打开文件')).toBeUndefined()
    expect(messageMocks.warning).toHaveBeenCalledWith('Artifact 已生成，但尚未保存到本地。')

    platformMocks.download.mockResolvedValueOnce({ status: 'started' })
    await click(findButton(root, '另存 Artifact')!)
    expect(findButton(root, '打开文件')).toBeUndefined()
    expect(messageMocks.info).toHaveBeenCalledWith('文件已交由浏览器下载，请在浏览器下载记录中查看。')

    platformMocks.download.mockResolvedValueOnce({ status: 'saved' })
    await click(findButton(root, '另存 Artifact')!)
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-A2' })
    await click(findButton(root, '另存 Artifact')!)
    store.selected = task('B')
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()

    let finishStaleDownload: (result: { status: 'saved'; capabilityId: string }) => void = () => undefined
    store.selected = task('A')
    await nextTick()
    platformMocks.download.mockReturnValueOnce(new Promise((resolve) => { finishStaleDownload = resolve }))
    const staleDownload = (findButton(root, '另存 Artifact')!.props.onClick as () => Promise<void>)()
    store.selected = task('B')
    await nextTick()
    finishStaleDownload({ status: 'saved', capabilityId: 'stale-cap-A' })
    await staleDownload
    await nextTick()
    expect(findButton(root, '打开文件')).toBeUndefined()

    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-B' })
    await click(findButton(root, '另存 Artifact')!)
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
    await click(findButton(root, '另存 Artifact')!)
    await click(findButton(root, '停止 / 取消')!)
    expect(findButton(root, '打开文件')).toBeUndefined()

    app.unmount()
  })

  it('uses the trackside AP business save endpoint from the task window', async () => {
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    store.selected = tracksideExportTask('rail-1')

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()
    const drawer = descendants(root).find((target) => target.type === 'drawer')
    const showDrawer = drawer?.props['onUpdate:modelValue'] as ((value: boolean) => void) | undefined
    showDrawer?.(true)
    await nextTick()

    expect(findButton(root, '另存 Artifact')).toBeUndefined()
    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-trackside' })
    await click(findButton(root, '保存导出表格')!)

    expect(platformMocks.download).toHaveBeenCalledWith({
      apiPath: '/api/rail-transit/trackside-ap-business/artifacts/artifact-rail-1/download',
      suggestedName: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(messageMocks.success).toHaveBeenCalledWith('轨旁 AP 业务表格已保存')
    expect(findButton(root, '打开文件')).toBeDefined()
    app.unmount()
  })

  it('renders structured FIT-AP progress details without parsing log text', async () => {
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    store.selected = {
      ...task('fit-ap-progress'),
      type: 'trackside_ap_optical_update',
      name: '轨旁 AP 光衰更新',
      status: 'RUNNING',
      progress: 37,
      stage: 'trackside_ap.fit_ap.collect',
      module: 'rail',
      details: {
        phase: 'fit_ap_optical',
        event: 'ap_completed',
        ap_name: 'bc5a-3457-a920',
        ap_ip: '10.122.223.4',
        station: '01-小洋江站',
        round: 1,
        fit_ap_completed: 37,
        fit_ap_total: 974,
        success_count: 31,
        failed_count: 6,
        effective_concurrency: 64,
        status: 'failed',
        reason_code: 'connect_timeout',
      },
    }
    store.logs = [
      {
        sequence: 1,
        time: '2026-07-22T02:39:52Z',
        level: 'INFO',
        type: 'progress',
        source: 'worker',
        message: 'AP 37/974 失败：bc5a-3457-a920',
        details: { event: 'ap_completed', status: 'failed', reason_code: 'connect_timeout' },
      },
      {
        sequence: 2,
        time: '2026-07-22T02:39:53Z',
        level: 'INFO',
        type: 'progress',
        source: 'worker',
        message: '第 2 轮重试 3/27：bc5a-3457-a920',
        details: { event: 'ap_retry_started', status: 'retrying' },
      },
    ]
    store.setLogsExpanded(true)

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()
    const drawer = descendants(root).find((target) => target.type === 'drawer')
    const showDrawer = drawer?.props['onUpdate:modelValue'] as ((value: boolean) => void) | undefined
    showDrawer?.(true)
    await nextTick()

    const text = textContent(root)
    expect(text).toContain('当前处理')
    expect(text).toContain('bc5a-3457-a920')
    expect(text).toContain('10.122.223.4')
    expect(text).toContain('01-小洋江站')
    expect(text).toContain('37 / 974')
    expect(text).toContain('31 / 6')
    expect(text).toContain('连接超时')
    const logRows = descendants(root).filter((target) => target.props.class && String(target.props.class).includes('log-line'))
    expect(String(logRows[0].props.class)).toContain('error')
    expect(String(logRows[1].props.class)).toContain('warning')
    app.unmount()
  })

  it('renders resident AC polling as indeterminate lifecycle progress', async () => {
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    store.selected = {
      ...task('resident-ac'),
      type: 'ac_mesh_link_resident_poll',
      name: 'AC Mesh-Link 常驻轮询 · 无线控制器',
      status: 'RUNNING',
      progress: 29,
      current: 63,
      total: 0,
      task_mode: 'resident',
      progress_mode: 'indeterminate',
      owner: 'ground_unattended_ac_mesh_link',
      details: {
        connection_state: 'WAITING',
        poll_interval_seconds: 10,
        poll_count: 63,
        success_count: 62,
        failure_count: 1,
        reconnect_count: 1,
        consecutive_failures: 0,
        last_success_at: '2026-07-29T08:00:00+08:00',
        next_poll_at: '2026-07-29T08:00:10+08:00',
        latest_snapshot_id: 88,
        latest_snapshot_record_count: 24,
        heartbeat_at: '2026-07-29T08:00:02+08:00',
      },
    }

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()
    const drawer = descendants(root).find((target) => target.type === 'drawer')
    const showDrawer = drawer?.props['onUpdate:modelValue'] as ((value: boolean) => void) | undefined
    showDrawer?.(true)
    await nextTick()

    const text = textContent(root)
    expect(text).toContain('常驻运行 · 已完成 63 次轮询')
    expect(text).toContain('WAITING')
    expect(text).toContain('63 / 62 / 1')
    expect(text).not.toContain('29%')
    app.unmount()
  })

  it('shows completed task state and the independent partial business result with skip reasons', async () => {
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    store.selected = {
      ...task('trackside-partial'),
      type: 'trackside_ap_optical_update',
      name: '轨旁 AP 光衰更新',
      status: 'COMPLETED',
      module: 'rail',
      details: {
        status: 'PARTIAL_SUCCESS',
        success_count: 745,
        failed_count: 0,
        skipped_count: 1,
        actionable_skipped_count: 1,
        ignored_skipped_count: 0,
        skipped_reason_counts: { connection_incomplete: 1 },
        failure_reason_counts: {},
      },
    }

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()
    const drawer = descendants(root).find((target) => target.type === 'drawer')
    const showDrawer = drawer?.props['onUpdate:modelValue'] as ((value: boolean) => void) | undefined
    showDrawer?.(true)
    await nextTick()

    const text = textContent(root)
    expect(text).toContain('业务结果：部分成功')
    expect(text).toContain('任务状态：已完成 · 部分成功')
    expect(text).toContain('745')
    expect(text).toContain('未执行')
    expect(text).toContain('连接信息不完整')
    app.unmount()
  })

  it('keeps the task list when a requested task id is missing', async () => {
    routeState.query = { module: 'rail', task_id: 'missing-task' }
    routeState.path = '/tasks'
    routeState.name = 'tasks'
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)
    vi.spyOn(store, 'selectTask').mockRejectedValue(new Error('not found'))

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)

    expect(store.selectTask).toHaveBeenCalledWith('missing-task')
    await vi.waitFor(() => expect(messageMocks.warning).toHaveBeenCalledWith('未找到任务 missing-task，已保留当前任务列表。'))
    await nextTick()
    expect(alertTitles(root)).toContain('未找到任务 missing-task，已保留当前任务列表。')
    app.unmount()
  })

  it('keeps the task center usable when polling cannot start', async () => {
    routeState.query = { module: 'rail' }
    routeState.path = '/tasks'
    routeState.name = 'tasks'
    const root = node('root')
    const pinia = createPinia()
    const store = useTaskStore(pinia)
    vi.spyOn(store, 'acquirePolling').mockImplementation(() => { throw new Error('polling unavailable') })
    vi.spyOn(store, 'releasePolling').mockImplementation(() => undefined)

    const app = renderer.createApp(JobCenterView)
    app.use(pinia)
    app.mount(root)
    await nextTick()

    expect(messageMocks.error).toHaveBeenCalledWith('任务列表自动刷新启动失败，可手动刷新后重试。')
    expect(alertTitles(root)).toContain('任务列表自动刷新启动失败，可手动刷新后重试。')
    app.unmount()
    expect(store.releasePolling).toHaveBeenCalledWith('job-center-view')
  })
})
