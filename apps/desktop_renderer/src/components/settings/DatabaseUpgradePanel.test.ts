// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { h, defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/databaseUpgrades'
import * as tasks from '../../api/tasks'
import type { DatabaseBackup, DatabaseUpgradeSnapshot } from '../../api/databaseUpgrades'
import DatabaseUpgradePanel from './DatabaseUpgradePanel.vue'

vi.mock('../../api/databaseUpgrades')
vi.mock('../../api/tasks')
vi.mock('../../features', () => ({ isFeatureEnabled: () => true }))
vi.mock('../../i18n/runtime', () => ({ t: (_key: string, fallback: string) => fallback }))

const mocks = vi.hoisted(() => ({
  confirm: vi.fn(),
  openTaskWindow: vi.fn(),
}))
vi.mock('../feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: mocks.confirm }) }))
vi.mock('../../platform/runtime', () => ({ getPlatformAdapter: () => ({ openTaskWindow: mocks.openTaskWindow }) }))

const tableStub = defineComponent({
  name: 'ElTable',
  props: { data: { type: Array, default: () => [] }, rowKey: { type: String, default: '' } },
  emits: ['selection-change'],
  setup(props, { emit, expose, slots }) {
    let selected: unknown[] = []
    const emitSelection = () => emit('selection-change', selected)
    expose({
      setSelection: (rows: unknown[]) => { selected = [...rows]; emitSelection() },
      clearSelection: () => { selected = []; emitSelection() },
      toggleAllSelection: () => {
        selected = selected.length === props.data.length ? [] : [...props.data]
        emitSelection()
      },
      toggleRowSelection: (row: unknown, checked = true) => {
        selected = checked
          ? [...selected.filter((item) => item !== row), row]
          : selected.filter((item) => item !== row)
        emitSelection()
      },
    })
    return () => h('div', { 'data-testid': 'table-stub' }, slots.default?.())
  },
})

const tableColumnStub = defineComponent({ name: 'ElTableColumn', setup: () => () => null })
const passthroughStub = (name: string) => defineComponent({
  name,
  inheritAttrs: false,
  setup(_, { attrs, slots }) { return () => h('div', attrs, slots.default?.()) },
})
const buttonStub = defineComponent({
  name: 'ElButton',
  inheritAttrs: false,
  setup(_, { attrs, slots }) { return () => h('button', attrs, slots.default?.()) },
})
const checkboxStub = defineComponent({
  name: 'ElCheckbox',
  inheritAttrs: false,
  props: { modelValue: Boolean, indeterminate: Boolean, disabled: Boolean },
  emits: ['change'],
  setup(props, { attrs, emit, slots }) {
    return () => h('label', attrs, [
      h('input', {
        type: 'checkbox',
        checked: props.modelValue,
        disabled: props.disabled,
        indeterminate: props.indeterminate,
        'data-testid': attrs['data-testid'],
        onChange: (event: Event) => emit('change', (event.target as HTMLInputElement).checked),
      }),
      slots.default?.(),
    ])
  },
})

const stubs = {
  ElTable: tableStub,
  ElTableColumn: tableColumnStub,
  ElTabs: passthroughStub('ElTabs'),
  ElTabPane: passthroughStub('ElTabPane'),
  ElAlert: passthroughStub('ElAlert'),
  ElTag: passthroughStub('ElTag'),
  ElTooltip: passthroughStub('ElTooltip'),
  ElIcon: passthroughStub('ElIcon'),
  ElButton: buttonStub,
  ElCheckbox: checkboxStub,
}

const mounted: VueWrapper[] = []

function backup(id: string, index: number, size = 1024): DatabaseBackup {
  return {
    backup_id: id,
    task_id: `seed-${index}`,
    database_kind: 'mesh_derived',
    scope_type: 'site_profile',
    scope_id: 'demo:profile',
    profile_name: `Profile ${index}`,
    created_at: `2026-09-03T00:00:0${index}+00:00`,
    old_schema_version: 'old',
    target_schema_version: 'new',
    database_size: size,
    database_sha256: 'sha256',
    result_status: 'VALID_BACKUP',
    integrity_check_result: { restorable: true },
    path: `C:\\backups\\${id}`,
  }
}

function snapshot(backups: DatabaseBackup[]): DatabaseUpgradeSnapshot {
  return { site_id: 'demo', databases: [], backups, backup_count: backups.length, backup_size_bytes: backups.reduce((sum, item) => sum + item.database_size, 0) }
}

const defaultBackups = [backup('backup-1', 1, 1024), backup('backup-2', 2, 2048), backup('backup-3', 3, 4096)]

function terminalTask(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    type: 'database_backup_batch_delete',
    name: '批量删除数据库备份',
    status: 'COMPLETED',
    progress: 100,
    phase: '',
    stage: '',
    message: '',
    site_name: 'demo',
    owner: 'database-upgrade',
    executor: 'LOCAL',
    source: 'local',
    device_id: '',
    device_name: '',
    agent: '',
    mr_name: '',
    session_id: '',
    mapping_state: '',
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
    success_count: 0,
    failed_count: 0,
    skipped_count: 0,
    partial_success: false,
    details: {},
    ...overrides,
  }
}

function mountPanel(): VueWrapper {
  const wrapper = mount(DatabaseUpgradePanel, { global: { stubs, directives: { loading: () => undefined } } })
  mounted.push(wrapper)
  return wrapper
}

function backupTable(wrapper: VueWrapper) {
  return wrapper.findAllComponents({ name: 'ElTable' })[1]
}

async function setBackupSelection(wrapper: VueWrapper, rows: DatabaseBackup[]): Promise<void> {
  const panel = wrapper.vm as unknown as { onBackupSelectionChange: (value: DatabaseBackup[]) => void }
  panel.onBackupSelectionChange(rows)
  await nextTick()
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getDatabaseUpgradeSnapshot).mockResolvedValue(snapshot(defaultBackups))
  vi.mocked(api.deleteDatabaseBackups).mockResolvedValue({ task_id: 'task-1', task_type: 'database_backup_batch_delete' })
  vi.mocked(tasks.getTask).mockResolvedValue(terminalTask() as never)
  mocks.confirm.mockResolvedValue(true)
  mocks.openTaskWindow.mockResolvedValue({ success: true })
})

afterEach(() => mounted.splice(0).forEach((wrapper) => wrapper.unmount()))

describe('DatabaseUpgradePanel historical backups', () => {
  it('selects all backups in the complete data model, including rows beyond the visible viewport', async () => {
    const rows = Array.from({ length: 40 }, (_, index) => backup(`backup-${index + 1}`, index + 1))
    vi.mocked(api.getDatabaseUpgradeSnapshot).mockResolvedValue(snapshot(rows))
    const wrapper = mountPanel()
    await flushPromises()

    const checkbox = wrapper.get('input[data-testid="history-backup-select-all"]')
    ;(checkbox.element as HTMLInputElement).checked = true
    await checkbox.trigger('change')

    expect(wrapper.get('[data-testid="history-backup-selection-summary"]').text()).toContain('已选 40 / 40 个备份')
    expect(backupTable(wrapper).props('rowKey')).toBe('backup_id')
  })

  it('shows an indeterminate state for a partial stable-id selection', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await setBackupSelection(wrapper, defaultBackups.slice(0, 2))
    await flushPromises()

    expect(wrapper.findComponent({ name: 'ElCheckbox' }).props('indeterminate')).toBe(true)
    expect(wrapper.get('[data-testid="history-backup-selection-summary"]').text()).toContain('已选 2 / 3 个备份')
  })

  it('confirms the estimate and submits exactly one batch request by backup id', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await setBackupSelection(wrapper, defaultBackups)
    await wrapper.get('[data-testid="history-backup-batch-delete"]').trigger('click')
    await flushPromises()

    expect(mocks.confirm).toHaveBeenCalledOnce()
    expect(mocks.confirm.mock.calls[0][0]).toMatchObject({
      message: expect.stringContaining('3 个数据库备份'),
      detail: expect.stringContaining('预计释放空间：7.0 KB'),
    })
    expect(api.deleteDatabaseBackups).toHaveBeenCalledOnce()
    expect(api.deleteDatabaseBackups).toHaveBeenCalledWith(['backup-1', 'backup-2', 'backup-3'])
    expect(api.deleteDatabaseBackup).not.toHaveBeenCalled()
    expect(api.getDatabaseUpgradeSnapshot).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="history-backup-selection-summary"]').text()).toContain('已选 0 / 3 个备份')
  })

  it('keeps failed rows selected after a partial task and prunes deleted rows on refresh', async () => {
    const rows = [backup('backup-1', 1), backup('backup-2', 2), backup('backup-3', 3)]
    vi.mocked(api.getDatabaseUpgradeSnapshot)
      .mockResolvedValueOnce(snapshot(rows))
      .mockResolvedValueOnce(snapshot([rows[2]]))
    vi.mocked(tasks.getTask).mockResolvedValue(terminalTask({ success_count: 2, failed_count: 1, partial_success: true, details: { released_bytes: 3072 } }) as never)
    const wrapper = mountPanel()
    await flushPromises()
    await setBackupSelection(wrapper, rows)
    await wrapper.get('[data-testid="history-backup-batch-delete"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="history-backup-selection-summary"]').text()).toContain('已选 1 / 1 个备份')
    expect(wrapper.get('[data-testid="history-backup-selection-bytes"]').text()).toContain('1.0 KB')
    expect(api.getDatabaseUpgradeSnapshot).toHaveBeenCalledTimes(2)
  })

  it('does not submit when confirmation is cancelled and prevents duplicate confirmation while pending', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await setBackupSelection(wrapper, [defaultBackups[0]])
    mocks.confirm.mockResolvedValueOnce(false)
    await wrapper.get('[data-testid="history-backup-batch-delete"]').trigger('click')
    await flushPromises()
    expect(api.deleteDatabaseBackups).not.toHaveBeenCalled()

    let resolveConfirmation: ((accepted: boolean) => void) | undefined
    mocks.confirm.mockReturnValueOnce(new Promise<boolean>((resolve) => { resolveConfirmation = resolve }))
    const first = wrapper.get('[data-testid="history-backup-batch-delete"]').trigger('click')
    await flushPromises()
    const second = wrapper.get('[data-testid="history-backup-batch-delete"]').trigger('click')
    await flushPromises()
    expect(mocks.confirm).toHaveBeenCalledTimes(2)
    resolveConfirmation?.(false)
    await Promise.all([first, second])
    expect(api.deleteDatabaseBackups).not.toHaveBeenCalled()
  })
})
