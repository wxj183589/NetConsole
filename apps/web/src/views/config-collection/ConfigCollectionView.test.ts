// @vitest-environment happy-dom

import { computed, defineComponent, h, inject, provide, type ComputedRef, type PropType } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ConfigConfirmation,
  ConfigDevice,
  ConfigSnapshot,
  ConfigTaskReference,
  ConfigTaskStatus,
} from '../../types/configCollection'

const api = vi.hoisted(() => ({
  configArtifactDownloadRequest: vi.fn(),
  confirmSaveForce: vi.fn(),
  confirmSnapshotDelete: vi.fn(),
  getConfigDirectory: vi.fn(),
  issueSnapshotDelete: vi.fn(),
  listConfigDevices: vi.fn(),
  listConfigSnapshots: vi.fn(),
  listConfigTasks: vi.fn(),
  previewSaveForce: vi.fn(),
  submitConfigDiffExport: vi.fn(),
  submitConfigCollection: vi.fn(),
  submitConfigSnapshotsExport: vi.fn(),
  submitDeviceConfigDiff: vi.fn(),
  submitLatestConfigDiff: vi.fn(),
  submitSnapshotConfigDiff: vi.fn(),
  submitSnapshotContent: vi.fn(),
}))
const confirmDialog = vi.hoisted(() => vi.fn())
const routerPush = vi.hoisted(() => vi.fn())
const downloadBackendResource = vi.hoisted(() => vi.fn())
const message = vi.hoisted(() => ({
  error: vi.fn(),
  info: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('../../api/configCollection', () => api)
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource,
  getPlatformAdapter: () => ({ hostType: 'browser' }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: confirmDialog }) }))
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessage: message,
  }
})

import ConfigCollectionView from './ConfigCollectionView.vue'
import source from './ConfigCollectionView.vue?raw'

describe('Config collection responsive layout', () => {
  it('fills the route and gives both tables their card remaining height', () => {
    expect(source).toContain('.config-collection { display: flex; width: 100%; height: 100%; max-width: none;')
    expect(source).toContain('.main-grid { display: grid; min-width: 0; min-height: 0; flex: 1;')
    expect(source).toContain('.device-card, .snapshot-card { display: flex; min-width: 0; min-height: 0;')
    expect(source).toContain('height="100%"')
    expect(source).not.toContain('max-width: 1780px')
    expect(source).not.toContain('height="calc(100vh - 430px)"')
  })
})

const deviceA: ConfigDevice = {
  id: 1,
  device_uuid: 'device-a',
  name: 'SW-A',
  system_name: 'SW-A',
  device_type: 'SW',
  station: 'A站',
  group_id: null,
}
const deviceB: ConfigDevice = {
  id: 2,
  device_uuid: 'device-b',
  name: 'SW-B',
  system_name: 'SW-B',
  device_type: 'SW',
  station: 'B站',
  group_id: null,
}
const snapshotA: ConfigSnapshot = snapshot(101, deviceA, 'running', '20260715_101500')
const snapshotASaved: ConfigSnapshot = snapshot(102, deviceA, 'saved', '20260715_101500')
const snapshotB: ConfigSnapshot = snapshot(201, deviceB, 'running', '20260716_121500')

const tableRowsKey = Symbol('config-table-rows')
const TableStub = defineComponent({
  name: 'ElTable',
  props: { data: { type: Array as PropType<unknown[]>, default: () => [] } },
  emits: ['row-click', 'selection-change'],
  setup(props, { slots }) {
    provide(tableRowsKey, computed(() => props.data))
    return () => h('div', { class: 'el-table-stub' }, slots.default?.())
  },
})
const TableColumnStub = defineComponent({
  name: 'ElTableColumn',
  setup(_props, { slots }) {
    const rows = inject<ComputedRef<unknown[]>>(tableRowsKey, computed(() => []))
    return () => h(
      'div',
      { class: 'el-table-column-stub' },
      slots.default
        ? rows.value.map((row, index) => h('div', { class: 'el-table-cell-stub', key: index }, slots.default?.({ row })))
        : [],
    )
  },
})
const ButtonStub = defineComponent({
  name: 'ElButton',
  inheritAttrs: false,
  props: { disabled: Boolean },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', {
      ...attrs,
      disabled: props.disabled,
      onClick: (event: MouseEvent) => emit('click', event),
    }, slots.default?.())
  },
})
const SlotStub = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h('div', attrs, slots.default?.())
  },
})
const OptionStub = defineComponent({
  name: 'ElOption',
  props: { label: String },
  setup(props) {
    return () => h('span', props.label)
  },
})

describe('ConfigCollectionView mounted workflow', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    Element.prototype.scrollIntoView = vi.fn()
    confirmDialog.mockResolvedValue(true)
    downloadBackendResource.mockResolvedValue({ status: 'saved' })
    api.configArtifactDownloadRequest.mockImplementation((artifactId, suggestedName) => ({ artifactId, suggestedName }))
    api.listConfigDevices.mockResolvedValue({
      items: [deviceA, deviceB],
      total: 2,
      page: 1,
      page_size: 50,
      total_pages: 1,
      groups: [],
    })
    api.listConfigSnapshots.mockImplementation((deviceId: number) => Promise.resolve(
      deviceId === deviceA.id ? [snapshotA, snapshotASaved] : [snapshotB],
    ))
    api.listConfigTasks.mockResolvedValue([])
    api.submitConfigCollection.mockResolvedValue([taskReference('collect-task', 'config_web_snapshot_fetch')])
    api.previewSaveForce.mockResolvedValue(confirmation('save_force'))
    api.confirmSaveForce.mockResolvedValue(taskReference('save-task', 'config_web_save_force'))
    api.issueSnapshotDelete.mockResolvedValue(confirmation('delete_snapshots'))
    api.confirmSnapshotDelete.mockResolvedValue(taskReference('delete-task', 'config_snapshot_delete_many'))
    api.submitSnapshotConfigDiff.mockResolvedValue(taskReference('diff-task', 'config_compare_snapshot_pair'))
    api.submitConfigDiffExport.mockResolvedValue(taskReference('export-task', 'config_web_export_diff'))
    api.submitConfigSnapshotsExport.mockResolvedValue(taskReference('zip-task', 'config_web_export_snapshots'))
  })

  afterEach(() => {
    vi.useRealTimers()
    Reflect.deleteProperty(window, 'netconsoleDesktop')
  })

  it('将未知快照大小显示为缺失值', async () => {
    api.listConfigSnapshots.mockImplementation((deviceId: number) => Promise.resolve(
      deviceId === deviceA.id ? [{ ...snapshotA, size_bytes: null }] : [snapshotB],
    ))

    const wrapper = await mountView()
    const snapshotTable = wrapper.findAllComponents(TableStub)[1]

    expect(snapshotTable.text()).toContain('—')
    expect(snapshotTable.text()).not.toContain('null B')
    wrapper.unmount()
  })

  it('drives collection, save force confirmation and deletion confirmation through mocked APIs', async () => {
    const wrapper = await mountView()
    const tables = wrapper.findAllComponents(TableStub)
    tables[0].vm.$emit('selection-change', [deviceA])
    await wrapper.vm.$nextTick()

    await button(wrapper, '采集 running / saved').trigger('click')
    await flushPromises()
    expect(api.submitConfigCollection).toHaveBeenCalledWith([deviceA.id])

    api.listConfigTasks.mockResolvedValue([
      terminalTask('collect-task', 'config_web_snapshot_fetch', {}),
    ])
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    await button(wrapper, '保存配置').trigger('click')
    await flushPromises()
    expect(api.previewSaveForce).toHaveBeenCalledWith([deviceA.id])
    expect(confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
      type: 'DANGER',
      title: '确认保存配置',
      confirmText: '确认保存配置',
      message: expect.stringContaining('固定执行 save force'),
    }))
    expect(api.confirmSaveForce).toHaveBeenCalledTimes(1)

    api.listConfigTasks.mockResolvedValue([
      terminalTask('collect-task', 'config_web_snapshot_fetch', {}),
      terminalTask('save-task', 'config_web_save_force', { saved: 1, total: 1, failed: 0 }),
    ])
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    wrapper.findAllComponents(TableStub)[1].vm.$emit('selection-change', [snapshotA])
    await wrapper.vm.$nextTick()
    await button(wrapper, '删除历史').trigger('click')
    await flushPromises()

    expect(api.issueSnapshotDelete).toHaveBeenCalledWith([snapshotA.id])
    expect(confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
      type: 'DESTRUCTIVE',
      title: '删除快照',
      confirmText: '确认删除快照',
      message: expect.stringContaining('确认'),
    }))
    expect(api.confirmSnapshotDelete).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('keeps independent cross-device choices, navigates diff, exports Artifact and opens the shared task window', async () => {
    const openTaskWindow = vi.fn().mockResolvedValue({ success: true })
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openTaskWindow },
    })
    const wrapper = await mountView()

    await buttons(wrapper, '设为左侧')[0].trigger('click')
    wrapper.findAllComponents(TableStub)[0].vm.$emit('row-click', deviceB)
    await flushPromises()
    await buttons(wrapper, '设为右侧')[0].trigger('click')

    expect(wrapper.get('[data-testid="left-snapshot-choice"]').text()).toContain(
      'SW-A · 运行配置 · 20260715_101500',
    )
    expect(wrapper.get('[data-testid="right-snapshot-choice"]').text()).toContain(
      'SW-B · 运行配置 · 20260716_121500',
    )

    await button(wrapper, '比较左右快照').trigger('click')
    await flushPromises()
    expect(api.submitSnapshotConfigDiff).toHaveBeenCalledWith(snapshotA.id, snapshotB.id)

    api.listConfigTasks.mockResolvedValue([
      terminalTask('diff-task', 'config_compare_snapshot_pair', {
        raw_diff: '--- SW-A\n+++ SW-B',
        left_label: 'SW-A · 运行配置 · 20260715_101500',
        right_label: 'SW-B · 运行配置 · 20260716_121500',
        diff_rows: [
          { left_line: 1, left_text: '#', status: '=', right_line: 1, right_text: '#' },
          { left_line: 2, left_text: 'sysname SW-A', status: '~', right_line: 2, right_text: 'sysname SW-B' },
          { left_line: null, left_text: '', status: '+', right_line: 3, right_text: 'vlan 20' },
        ],
        diff_summary: { added: 1, removed: 0, modified: 1 },
      }),
    ])
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(wrapper.text()).toContain('配置差异 · SW-A · 运行配置 · 20260715_101500 → SW-B · 运行配置 · 20260716_121500')
    expect(wrapper.text()).toContain('1 / 2')
    await button(wrapper, '下一处差异').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('2 / 2')

    await button(wrapper, '导出左右差异').trigger('click')
    await flushPromises()
    expect(api.submitConfigDiffExport).toHaveBeenCalledWith(snapshotA.id, snapshotB.id)

    api.listConfigTasks.mockResolvedValue([
      terminalTask('diff-task', 'config_compare_snapshot_pair', {}),
      terminalTask('export-task', 'config_web_export_diff', {
        artifact_id: 'export-artifact',
        display_name: 'SW-A_to_SW-B.diff',
      }),
    ])
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    await button(wrapper, '下载 Artifact').trigger('click')
    await flushPromises()
    expect(api.configArtifactDownloadRequest).toHaveBeenCalledWith('export-artifact', 'SW-A_to_SW-B.diff')
    expect(downloadBackendResource).toHaveBeenCalledTimes(1)

    await buttonContaining(wrapper, '任务中心').trigger('click')
    await flushPromises()
    expect(openTaskWindow).toHaveBeenCalledWith({ module: 'config' })
    expect(routerPush).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('uses two checked snapshots as the visible comparison pair', async () => {
    const wrapper = await mountView()
    const snapshotTable = wrapper.findAllComponents(TableStub)[1]

    snapshotTable.vm.$emit('selection-change', [snapshotA, snapshotASaved])
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="left-snapshot-choice"]').text()).toContain(
      'SW-A · 运行配置 · 20260715_101500',
    )
    expect(wrapper.get('[data-testid="right-snapshot-choice"]').text()).toContain(
      'SW-A · 保存配置 · 20260715_101500',
    )
    expect(wrapper.get('[data-testid="left-snapshot-choice"]').text()).toContain('来自当前勾选')
    expect((button(wrapper, '比较左右快照').element as HTMLButtonElement).disabled).toBe(false)

    await button(wrapper, '比较左右快照').trigger('click')
    await flushPromises()

    expect(api.submitSnapshotConfigDiff).toHaveBeenCalledWith(snapshotA.id, snapshotASaved.id)
    wrapper.unmount()
  })

  it('exports the same pair selected by the snapshot checkboxes', async () => {
    const wrapper = await mountView()
    wrapper.findAllComponents(TableStub)[1].vm.$emit('selection-change', [snapshotA, snapshotASaved])
    await wrapper.vm.$nextTick()

    await button(wrapper, '导出左右差异').trigger('click')
    await flushPromises()

    expect(api.submitConfigDiffExport).toHaveBeenCalledWith(snapshotA.id, snapshotASaved.id)
    wrapper.unmount()
  })

  it('keeps comparison disabled when only one snapshot is checked without a manual pair', async () => {
    const wrapper = await mountView()
    wrapper.findAllComponents(TableStub)[1].vm.$emit('selection-change', [snapshotA])
    await wrapper.vm.$nextTick()

    expect((button(wrapper, '比较左右快照').element as HTMLButtonElement).disabled).toBe(true)
    expect((button(wrapper, '导出左右差异').element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })

  it('blocks comparison for more than two checked snapshots without disabling batch actions', async () => {
    const snapshotAOlder = snapshot(103, deviceA, 'running', '20260714_091500')
    const wrapper = await mountView()
    wrapper.findAllComponents(TableStub)[1].vm.$emit(
      'selection-change',
      [snapshotA, snapshotASaved, snapshotAOlder],
    )
    await wrapper.vm.$nextTick()

    expect(message.warning).toHaveBeenCalledWith(
      '快照对比只能选择两条记录；批量勾选仍可用于导出 ZIP 或删除。',
    )
    expect((button(wrapper, '比较左右快照').element as HTMLButtonElement).disabled).toBe(true)
    expect((button(wrapper, '导出左右差异').element as HTMLButtonElement).disabled).toBe(true)
    expect((button(wrapper, '导出 ZIP').element as HTMLButtonElement).disabled).toBe(false)
    expect((button(wrapper, '删除历史').element as HTMLButtonElement).disabled).toBe(false)

    await button(wrapper, '导出 ZIP').trigger('click')
    await flushPromises()
    expect(api.submitConfigSnapshotsExport).toHaveBeenCalledWith([
      snapshotA.id,
      snapshotASaved.id,
      snapshotAOlder.id,
    ])
    await button(wrapper, '删除历史').trigger('click')
    await flushPromises()
    expect(api.issueSnapshotDelete).toHaveBeenCalledWith([
      snapshotA.id,
      snapshotASaved.id,
      snapshotAOlder.id,
    ])
    expect(api.submitSnapshotConfigDiff).not.toHaveBeenCalled()
    expect(api.submitConfigDiffExport).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not reuse checked snapshots after switching device or snapshot type', async () => {
    const wrapper = await mountView()
    wrapper.findAllComponents(TableStub)[1].vm.$emit('selection-change', [snapshotA, snapshotASaved])
    await wrapper.vm.$nextTick()

    wrapper.findAllComponents(TableStub)[0].vm.$emit('row-click', deviceB)
    await flushPromises()
    expect((button(wrapper, '比较左右快照').element as HTMLButtonElement).disabled).toBe(true)

    wrapper.findAllComponents(TableStub)[0].vm.$emit('row-click', deviceA)
    await flushPromises()
    wrapper.findAllComponents(TableStub)[1].vm.$emit('selection-change', [snapshotA, snapshotASaved])
    await wrapper.vm.$nextTick()
    await wrapper.get('[placeholder="配置类型"]').trigger('change')
    await flushPromises()

    expect((button(wrapper, '比较左右快照').element as HTMLButtonElement).disabled).toBe(true)
    expect(api.submitSnapshotConfigDiff).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('clears stale checked state on refresh and falls back to preserved manual choices', async () => {
    const wrapper = await mountView()
    await buttons(wrapper, '设为左侧')[0].trigger('click')
    wrapper.findAllComponents(TableStub)[0].vm.$emit('row-click', deviceB)
    await flushPromises()
    await buttons(wrapper, '设为右侧')[0].trigger('click')
    wrapper.findAllComponents(TableStub)[0].vm.$emit('row-click', deviceA)
    await flushPromises()

    const snapshotTable = wrapper.findAllComponents(TableStub)[1]
    snapshotTable.vm.$emit('selection-change', [snapshotA, snapshotASaved])
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="right-snapshot-choice"]').text()).toContain('保存配置')
    expect(wrapper.get('[data-testid="right-snapshot-choice"]').text()).toContain('来自当前勾选')

    await button(wrapper, '刷新').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="left-snapshot-choice"]').text()).toContain('SW-A · 运行配置')
    expect(wrapper.get('[data-testid="right-snapshot-choice"]').text()).toContain('SW-B · 运行配置')
    expect(wrapper.get('[data-testid="right-snapshot-choice"]').text()).toContain('手动指定')
    expect((button(wrapper, '比较左右快照').element as HTMLButtonElement).disabled).toBe(false)

    await button(wrapper, '比较左右快照').trigger('click')
    await flushPromises()
    expect(api.submitSnapshotConfigDiff).toHaveBeenCalledWith(snapshotA.id, snapshotB.id)
    wrapper.unmount()
  })
})

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(ConfigCollectionView, {
    global: {
      directives: { loading: () => undefined },
      stubs: {
        ElAlert: SlotStub,
        ElButton: ButtonStub,
        ElInput: SlotStub,
        ElOption: OptionStub,
        ElPagination: SlotStub,
        ElSelect: SlotStub,
        ElTable: TableStub,
        ElTableColumn: TableColumnStub,
        ElTag: SlotStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

function snapshot(id: number, device: ConfigDevice, type: string, timestamp: string): ConfigSnapshot {
  return {
    id,
    device_id: device.id,
    device_uuid: device.device_uuid,
    timestamp,
    type,
    size_bytes: 128,
    artifact_id: `snapshot-${id}`,
    filename: `${id}.txt`,
    hash: `hash-${id}`,
    created_at: timestamp,
    error_message: '',
  }
}

function taskReference(id: string, type: string): ConfigTaskReference {
  return {
    id,
    type,
    status: 'RUNNING',
    progress: 0,
    device_id: '',
    device_name: '',
    message: '',
  }
}

function terminalTask(id: string, type: string, result: Record<string, unknown>): ConfigTaskStatus {
  return {
    ...taskReference(id, type),
    status: 'COMPLETED',
    progress: 100,
    stage: '',
    created_time: '2026-07-15T10:15:00',
    started_time: '2026-07-15T10:15:01',
    finished_time: '2026-07-15T10:15:02',
    error_message: '',
    result,
  }
}

function confirmation(action: ConfigConfirmation['action']): ConfigConfirmation {
  return {
    action,
    confirmation_token: `${action}-token`,
    digest: `${action}-digest`,
    summary: action === 'save_force' ? '确认保存配置' : '确认删除 1 个快照',
    expires_at: '2026-07-15T10:20:00',
    snapshot_ids: action === 'delete_snapshots' ? [snapshotA.id] : [],
    device_ids: action === 'save_force' ? [deviceA.id] : [],
    action_plan: action === 'save_force' ? ['固定执行 save force'] : [],
  }
}

function buttons(wrapper: VueWrapper, text: string) {
  return wrapper.findAll('button').filter((candidate) => candidate.text().trim() === text)
}

function button(wrapper: VueWrapper, text: string) {
  const candidate = buttons(wrapper, text)[0]
  if (!candidate) throw new Error(`button not found: ${text}`)
  return candidate
}

function buttonContaining(wrapper: VueWrapper, text: string) {
  const candidate = wrapper.findAll('button').find((item) => item.text().includes(text))
  if (!candidate) throw new Error(`button not found: ${text}`)
  return candidate
}
