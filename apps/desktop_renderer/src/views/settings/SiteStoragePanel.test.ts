// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/siteStorage'
import * as tasks from '../../api/tasks'
import { ApiRequestError } from '../../api/client'
import type { SiteRecord, SiteRetentionReport } from '../../api/siteStorage'
import SiteStoragePanel from './SiteStoragePanel.vue'

vi.mock('../../api/siteStorage')
vi.mock('../../api/tasks')

const workspace = vi.hoisted(() => ({
  checkpoint: {
    schemaVersion: 1 as const,
    windowId: 'main',
    activeTabId: 'mesh-tab',
    tabs: [],
  },
  createSnapshot: vi.fn(),
  prepareForSiteSwitch: vi.fn(),
  restoreAfterFailedSiteSwitch: vi.fn(),
}))
vi.mock('../../stores/workspace', () => ({ useWorkspaceStore: () => workspace }))

const adapter = {
  hostType: 'electron' as const,
  selectDataRootDirectory: vi.fn(async () => ({ cancelled: true })),
  selectSitePackage: vi.fn(async () => ({ cancelled: true })),
  selectSiteExportDestination: vi.fn(async () => ({ cancelled: true })),
  restartBackend: vi.fn(async (): Promise<{ success: boolean; error?: string }> => ({ success: true })),
  openTaskWindow: vi.fn(async () => ({ success: true })),
  executeSettingsAction: vi.fn(async () => ({ success: true })),
  refreshSiteContext: vi.fn(async () => undefined),
  onTraySiteSwitchRequested: vi.fn(() => () => undefined),
  reportSiteSwitchState: vi.fn(),
}
vi.mock('../../platform/runtime', () => ({ getPlatformAdapter: () => adapter }))

function site(overrides: Partial<SiteRecord> = {}): SiteRecord {
  return {
    site_id: 'demo',
    display_name: '演示局点',
    line_name: null,
    project_type: null,
    created_at: '',
    updated_at: '',
    remark: '',
    active: true,
    size_bytes: 1024,
    site_kind: 'demo',
    classification: 'managed_demo',
    managed_demo: true,
    demo_seed_version: '2026.07.21.1',
    migration_status: 'current',
    data_integrity: 'ok',
    recommended_action: 'keep_and_review',
    audited_at: '2026-07-21T08:00:00+08:00',
    ...overrides,
  }
}

function retentionReport(overrides: Partial<SiteRetentionReport> = {}): SiteRetentionReport {
  return {
    scan_token: 'a'.repeat(64),
    site_id: 'demo',
    display_name: '演示局点',
    generated_at: '2026-08-13T12:00:00+00:00',
    policy: {
      backup_archive_days: 30,
      backup_delete_days: 90,
      online_mr_raw_archive_days: 30,
      task_retention_status: 'KEEP_LAST_10_EFFECTIVE',
      typed_task_retention_apply_enabled: false,
      typed_task_retention_owner: 'TaskRepository.retain_recent_terminal_tasks',
      typed_task_retention_keep_per_scope: 10,
      rollback_keep_count: 2,
    },
    summary: {
      total_bytes: 8 * 1024 ** 3,
      current_database_bytes: 1024 ** 3,
      raw_bytes: 2 * 1024 ** 3,
      parsed_bytes: 1024 ** 3,
      backup_bytes: 4 * 1024 ** 3,
      other_bytes: 0,
      safe_cleanup_bytes: 700 * 1024 ** 2,
      compressible_bytes: 200 * 1024 ** 2,
      actionable_count: 2,
    },
    candidates: [
      {
        candidate_id: 'safe-delete',
        category: 'outdated_database',
        relative_path: 'files/backups/database-migrations/devices-before-old.sqlite',
        display_name: 'devices-before-old.sqlite',
        size_bytes: 700 * 1024 ** 2,
        estimated_release_bytes: 700 * 1024 ** 2,
        age_days: 100,
        status: 'historical_migration_version',
        recommended_action: 'delete',
        safe: true,
        reason: '当前 schema 更高且存在更新回滚副本',
        details: { schema_version: '2026.07.01.old' },
      },
      {
        candidate_id: 'safe-archive',
        category: 'expired_raw',
        relative_path: 'files/rail_transit/online_mr/MR-01/sessions/session-1/raw',
        display_name: 'Online MR session-1 原始数据',
        size_bytes: 300 * 1024 ** 2,
        estimated_release_bytes: 200 * 1024 ** 2,
        age_days: 45,
        status: 'archived_raw_copy',
        recommended_action: 'archive',
        safe: true,
        reason: '完整会话包已校验',
        details: { session_id: 'session-1' },
      },
      {
        candidate_id: 'unknown',
        category: 'outdated_database',
        relative_path: 'files/backups/unknown.sqlite',
        display_name: 'unknown.sqlite',
        size_bytes: 64 * 1024 ** 2,
        estimated_release_bytes: 0,
        age_days: 200,
        status: 'unknown_database',
        recommended_action: 'keep',
        safe: false,
        reason: '数据库类型或 schema 无法确认，只能人工复核',
        details: {},
      },
    ],
    ...overrides,
  }
}

async function emitSiteCommand(wrapper: VueWrapper, siteId: string, command: string): Promise<void> {
  const dropdown = wrapper.findAllComponents({ name: 'ElDropdown' })
    .find((item) => item.find(`[data-testid="more-site-${siteId}"]`).exists())
  expect(dropdown).toBeDefined()
  dropdown!.vm.$emit('command', command)
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  workspace.createSnapshot.mockReturnValue(workspace.checkpoint)
  workspace.prepareForSiteSwitch.mockResolvedValue(workspace.checkpoint)
  workspace.restoreAfterFailedSiteSwitch.mockResolvedValue(undefined)
  vi.mocked(api.listSites).mockResolvedValue([site()])
  vi.mocked(api.getDataRoot).mockResolvedValue({ data_root: 'C:\\data', default_data_root: 'C:\\default', site_count: 1, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })
  vi.mocked(api.preflightSiteActivation).mockResolvedValue({ ready: true, target_site_id: 'line-12', previous_site_id: 'demo' })
})

afterEach(() => { vi.restoreAllMocks() })

describe('SiteStoragePanel', () => {
  it('shows the active site and controlled storage actions', async () => {
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('演示局点')
    expect(wrapper.text()).toContain('全局数据根')
    expect(wrapper.find('[data-testid="create-site"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="import-site"]').text()).toBe('导入数据包')
    expect(wrapper.find('[data-testid="export-site"]').text()).toContain('导出当前局点')
    expect(wrapper.find('[data-testid="migrate-data-root"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('线路未填写')
    expect(wrapper.text()).toContain('项目类型未填写')
  })

  it('shows real site information and treats blank legacy fields as missing', async () => {
    vi.mocked(api.listSites).mockResolvedValue([
      site({ site_id: 'line-filled', display_name: '已填写局点', active: false, site_kind: 'formal', line_name: '杭州地铁10号线', project_type: 'PIS车地无线系统' }),
      site({ site_id: 'line-blank', display_name: '空字段局点', active: false, site_kind: 'legacy', line_name: '   ', project_type: '' }),
      site({ site_id: 'line-old', display_name: '旧版局点', active: false, site_kind: 'legacy', line_name: undefined, project_type: undefined }),
    ])

    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('线路：杭州地铁10号线')
    expect(wrapper.text()).toContain('项目类型：PIS车地无线系统')
    expect(wrapper.text()).toContain('空字段局点')
    expect(wrapper.text()).toContain('旧版局点')
    expect(wrapper.text().match(/线路未填写/g)?.length).toBe(2)
    expect(wrapper.text().match(/项目类型未填写/g)?.length).toBe(2)
  })

  it('edits site information, reloads the list and refreshes current site surfaces', async () => {
    const initial = site({ line_name: null, project_type: 'PIS车地无线系统' })
    const updated = site({ display_name: '新演示局点', line_name: '演示线路', project_type: 'PIS车地无线系统' })
    vi.mocked(api.listSites).mockResolvedValueOnce([initial]).mockResolvedValueOnce([updated])
    vi.mocked(api.updateSite).mockResolvedValue(updated)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'demo', 'edit')
    const dialog = wrapper.findComponent({ name: 'ElDialog' })
    await dialog.get('[data-testid="site-display-name-input"]').setValue(' 新演示局点 ')
    await dialog.get('[data-testid="site-line-name-input"]').setValue(' 演示线路 ')
    await dialog.get('[data-testid="save-site-info"]').trigger('click')
    await flushPromises()

    expect(api.updateSite).toHaveBeenCalledWith('demo', {
      display_name: '新演示局点',
      line_name: '演示线路',
      project_type: 'PIS车地无线系统',
    })
    expect(wrapper.text()).toContain('线路：演示线路')
    expect(adapter.refreshSiteContext).toHaveBeenCalledOnce()
  })

  it('keeps the editor open and shows a duplicate-name backend error', async () => {
    vi.mocked(api.updateSite).mockRejectedValue(new ApiRequestError('局点名称已存在', 409, 'SITE_NAME_CONFLICT'))
    const message = vi.spyOn(ElMessage, 'error')
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'demo', 'rename')
    const dialog = wrapper.findComponent({ name: 'ElDialog' })
    await dialog.get('[data-testid="site-display-name-input"]').setValue('重复局点')
    await dialog.get('[data-testid="save-site-info"]').trigger('click')
    await flushPromises()

    expect(message).toHaveBeenCalledWith('局点名称已存在')
    expect(api.listSites).toHaveBeenCalledOnce()
    expect(dialog.props('modelValue')).toBe(true)
  })

  it('applies a successful data-root refresh when the site list request fails', async () => {
    vi.mocked(api.listSites).mockRejectedValueOnce(new Error('site list unavailable'))
    vi.mocked(api.getDataRoot).mockResolvedValueOnce({ data_root: 'D:\\partial-data', default_data_root: 'C:\\default', site_count: 1, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })

    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('D:\\partial-data')
    expect(wrapper.text()).toContain('部分数据刷新失败，已保留最后成功数据')
    expect(wrapper.text()).toContain('局点列表（site list unavailable）')
  })

  it('inspects a selected data package before opening the merge dialog', async () => {
    adapter.selectSitePackage.mockResolvedValueOnce({ cancelled: false, path: 'C:\\packages\\line.ncresult' } as never)
    vi.mocked(api.inspectSitePackage).mockResolvedValue({
      site_id: 'demo',
      target_site_id: 'demo',
      site_uuid: 'site-1',
      site_name: '演示局点',
      package_type: 'collection_return',
      package_id: 'package-1',
      base_revision: 35,
      local_revision: 42,
      file_count: 3,
      site_identity_match: true,
      new_files: 2,
      duplicate_files: 1,
      new_tasks: 1,
      updated_tasks: 0,
      new_records: 0,
      updated_records: 1,
      duplicate_records: 0,
      unsupported_records: 0,
      deletion_requests: 0,
      conflict_count: 0,
      conflicts: [],
      invalid_count: 0,
      estimated_additional_bytes: 1024,
      create_snapshot: true,
      can_import: true,
      contains_credentials: false,
      encrypted: false,
      credential_reentry_count: 0,
    })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="import-site"]').trigger('click')
    await flushPromises()

    expect(api.inspectSitePackage).toHaveBeenCalledWith('C:\\packages\\line.ncresult')
    expect(api.importSite).not.toHaveBeenCalled()
  })

  it('inspects a plain full package without requesting a migration password', async () => {
    const passwordPrompt = vi.spyOn(ElMessageBox, 'prompt')
    adapter.selectSitePackage.mockResolvedValueOnce({ cancelled: false, path: 'C:\\packages\\full.ncsite' } as never)
    vi.mocked(api.inspectSitePackage).mockResolvedValue({
      site_id: 'demo',
      site_uuid: 'site-1',
      site_name: '演示局点',
      package_type: 'full_migration',
      package_id: 'package-1',
      base_revision: 1,
      file_count: 4,
      conflict_count: 0,
      conflicts: [],
      invalid_count: 0,
      estimated_additional_bytes: 4096,
      can_import: true,
      contains_credentials: true,
      encrypted: false,
      credential_reentry_count: 0,
    })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="import-site"]').trigger('click')
    await flushPromises()

    expect(passwordPrompt).not.toHaveBeenCalled()
    expect(api.inspectSitePackage).toHaveBeenCalledOnce()
    expect(api.inspectSitePackage).toHaveBeenCalledWith('C:\\packages\\full.ncsite')
    expect(wrapper.text()).toContain('完整迁移包包含设备用户名和密码，请妥善保管')
  })

  it('exposes one stable focus target and applies only a visual focus state', async () => {
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => undefined)
    const focus = vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(() => undefined)
    const wrapper = mount(SiteStoragePanel, { props: { focused: true } })
    await flushPromises()

    expect(wrapper.get('#site-storage-management').classes()).toContain('storage-panel--focused')
    await (wrapper.vm as unknown as { focus(): Promise<void> }).focus()
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    expect(api.activateSite).not.toHaveBeenCalled()
    expect(adapter.restartBackend).not.toHaveBeenCalled()
  })

  it('renders every legacy site returned by the registry API', async () => {
    vi.mocked(api.listSites).mockResolvedValue([
      site(),
      site({ site_id: 'legacy-dfd356e96ea0', display_name: '宁波地铁12号线', active: false, size_bytes: 2048, site_kind: 'legacy', classification: 'legacy_valid', managed_demo: false, demo_seed_version: '', migration_status: 'pending', data_integrity: 'unknown', recommended_action: 'audit_required' }),
    ])
    vi.mocked(api.getDataRoot).mockResolvedValue({ data_root: 'C:\\data', default_data_root: 'C:\\default', site_count: 2, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })

    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('宁波地铁12号线')
    expect(wrapper.text()).toContain('legacy-dfd356e96ea0')
    expect(wrapper.text()).toContain('2 个局点')
  })

  it('shows concrete blocking tasks and opens the selected task in Task Center', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as never)
    vi.mocked(api.listSites).mockResolvedValue([
      site(),
      site({ site_id: 'line-12', display_name: '十二号线', active: false, site_kind: 'formal', classification: 'normal_site', managed_demo: false }),
    ])
    vi.mocked(api.activateSite).mockRejectedValueOnce(new ApiRequestError(
      '存在仍在运行的任务，无法切换局点',
      409,
      'SITE_HAS_ACTIVE_TASKS',
      { blocking_tasks: [{ task_id: 'task-1', task_type: 'device_collect', task_name: '设备采集', status: 'RUNNING', blocking_reason: '任务宿主仍在运行' }] },
    ))
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="switch-site-line-12"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="site-blocking-tasks"]').text()).toContain('设备采集')
    expect(wrapper.get('[data-testid="site-blocking-tasks"]').text()).toContain('RUNNING')
    expect(wrapper.get('[data-testid="site-blocking-tasks"]').text()).toContain('task-1')
    await wrapper.get('[data-testid="site-blocking-tasks"] button').trigger('click')
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'task-1', module: 'logs' })
  })

  it('releases the switch button after Backend restart failure', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as never)
    vi.mocked(api.listSites).mockResolvedValue([
      site(),
      site({ site_id: 'line-12', display_name: '十二号线', active: false, site_kind: 'formal', classification: 'normal_site', managed_demo: false }),
    ])
    vi.mocked(api.activateSite).mockResolvedValueOnce(site({ site_id: 'line-12', active: true }) as never)
    adapter.restartBackend.mockResolvedValueOnce({ success: false, error: 'Backend 重启失败，已恢复原局点。' })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="switch-site-line-12"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Backend 重启失败，已恢复原局点。')
    expect(wrapper.get('[data-testid="switch-site-line-12"]').attributes('disabled')).toBeUndefined()
    expect(workspace.restoreAfterFailedSiteSwitch).toHaveBeenCalledWith(workspace.checkpoint)
  })

  it('prepares the workspace before activation and reports success only after Backend ready', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as never)
    vi.mocked(api.listSites).mockResolvedValue([
      site(),
      site({ site_id: 'line-12', display_name: '十二号线', active: false, site_kind: 'formal', classification: 'normal_site', managed_demo: false }),
    ])
    vi.mocked(api.activateSite).mockResolvedValueOnce({ restart_required: true })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="switch-site-line-12"]').trigger('click')
    await flushPromises()

    expect(workspace.prepareForSiteSwitch).toHaveBeenCalledWith(
      'line-12',
      expect.stringMatching(/^\/settings\?section=site-storage&site_focus=site-switch-/),
    )
    expect(api.preflightSiteActivation).toHaveBeenCalledWith('line-12')
    expect(api.activateSite).toHaveBeenCalledWith('line-12')
    expect(adapter.restartBackend).toHaveBeenCalledWith({ activeSiteId: 'line-12' })
    expect(vi.mocked(api.preflightSiteActivation).mock.invocationCallOrder[0])
      .toBeLessThan(workspace.prepareForSiteSwitch.mock.invocationCallOrder[0])
    expect(workspace.prepareForSiteSwitch.mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(api.activateSite).mock.invocationCallOrder[0])
    expect(vi.mocked(api.activateSite).mock.invocationCallOrder[0])
      .toBeLessThan(adapter.restartBackend.mock.invocationCallOrder[0])
    expect(workspace.restoreAfterFailedSiteSwitch).not.toHaveBeenCalled()
  })

  it('blocks a site switch while system settings have unsaved changes', async () => {
    vi.mocked(api.listSites).mockResolvedValue([
      site(),
      site({ site_id: 'line-12', display_name: '十二号线', active: false, site_kind: 'formal', classification: 'normal_site', managed_demo: false }),
    ])
    const wrapper = mount(SiteStoragePanel, { props: { switchBlocked: true } })
    await flushPromises()

    await wrapper.get('[data-testid="switch-site-line-12"]').trigger('click')
    await flushPromises()

    expect(api.activateSite).not.toHaveBeenCalled()
    expect(workspace.prepareForSiteSwitch).not.toHaveBeenCalled()
  })

  it('creates a site only after collecting display name and stable id', async () => {
    vi.spyOn(ElMessageBox, 'prompt')
      .mockResolvedValueOnce({ value: '宁波地铁12号线' } as never)
      .mockResolvedValueOnce({ value: 'ningbo-line-12' } as never)
    vi.mocked(api.createSite).mockResolvedValue(site({ site_id: 'ningbo-line-12', display_name: '宁波地铁12号线', active: false, size_bytes: 0, site_kind: 'formal', classification: 'normal_site', managed_demo: false, demo_seed_version: '' }))
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="create-site"]').trigger('click')
    await flushPromises()

    expect(api.createSite).toHaveBeenCalledWith({ site_id: 'ningbo-line-12', display_name: '宁波地铁12号线' })
  })

  it('makes isolated test storage visibly read-only', async () => {
    vi.mocked(api.getDataRoot).mockResolvedValue({
      data_root: '<temporary>',
      default_data_root: '<unavailable>',
      site_count: 1,
      active_site_id: 'demo',
      storage_mode: 'isolated_test',
      data_root_kind: 'temporary',
      persistent: false,
    })

    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.find('[data-testid="isolated-storage-alert"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('临时测试数据根')
    expect(wrapper.find('[data-testid="create-site"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="migrate-data-root"]').exists()).toBe(false)
  })

  it('runs the site audit as a task and refreshes the lifecycle summary', async () => {
    vi.mocked(api.auditSite).mockResolvedValue({ task_id: 'audit-1', task_type: 'site_audit' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'COMPLETED' } as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="audit-site-demo"]').trigger('click')
    await flushPromises()

    expect(api.auditSite).toHaveBeenCalledWith('demo')
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'audit-1', module: 'logs' })
    expect(api.listSites).toHaveBeenCalledTimes(2)
  })

  it('submits the first retention scan and renders all cleanup sections', async () => {
    vi.mocked(api.getLatestSiteRetention)
      .mockRejectedValueOnce(new ApiRequestError('尚未生成数据清理扫描', 404, 'SITE_RETENTION_SCAN_NOT_FOUND'))
      .mockResolvedValueOnce(retentionReport())
    vi.mocked(api.scanSiteRetention).mockResolvedValue({ task_id: 'scan-1', task_type: 'site_retention_scan' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'COMPLETED' } as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="retention-site-demo"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('尚未生成数据清理扫描')

    await wrapper.get('[data-testid="retention-scan"]').trigger('click')
    await flushPromises()

    expect(api.scanSiteRetention).toHaveBeenCalledWith('demo')
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'scan-1', module: 'logs' })
    expect(wrapper.get('[data-testid="retention-summary"]').text()).toContain('8.0 GB')
    expect(wrapper.text()).toContain('过期原始包/日志')
    expect(wrapper.text()).toContain('历史数据库备份')
    expect(wrapper.text()).toContain('过时数据库版本')
    expect(wrapper.text()).toContain('数据库历史记录/空间压缩')
  })

  it('keeps unknown databases disabled and executes only explicitly selected safe items', async () => {
    vi.mocked(api.getLatestSiteRetention)
      .mockResolvedValueOnce(retentionReport())
      .mockResolvedValueOnce(retentionReport({ candidates: [], summary: { ...retentionReport().summary, safe_cleanup_bytes: 0, compressible_bytes: 0, actionable_count: 0 } }))
    vi.mocked(api.applySiteRetention).mockResolvedValue({ task_id: 'apply-1', task_type: 'site_retention_apply' })
    vi.mocked(api.scanSiteRetention).mockResolvedValue({ task_id: 'scan-2', task_type: 'site_retention_scan' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'COMPLETED' } as never)
    const prompt = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '演示局点', action: 'confirm' } as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="retention-site-demo"]').trigger('click')
    await flushPromises()
    const unknown = wrapper.getComponent(
      '[data-testid="retention-candidate-unknown"]',
    ) as VueWrapper
    expect((unknown.props() as Record<string, unknown>).disabled).toBe(true)
    unknown.vm.$emit('change', true)
    const safeDelete = wrapper.getComponent(
      '[data-testid="retention-candidate-safe-delete"]',
    ) as VueWrapper
    safeDelete.vm.$emit('change', true)
    await flushPromises()

    expect(wrapper.text()).toContain('已选 1 项')
    await wrapper.get('[data-testid="retention-execute"]').trigger('click')
    await flushPromises()

    expect(prompt).toHaveBeenCalledWith(
      expect.stringContaining('预计释放 700.0 MB'),
      '确认执行数据清理',
      expect.objectContaining({ inputPlaceholder: '演示局点' }),
    )
    expect(api.applySiteRetention).toHaveBeenCalledWith('demo', 'a'.repeat(64), ['safe-delete'])
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'apply-1', module: 'logs' })
    expect(api.scanSiteRetention).toHaveBeenCalledWith('demo')
    expect(wrapper.text()).toContain('可处理 0 项')
  })

  it('shows only safe audit facts and does not render server paths', async () => {
    const alert = vi.spyOn(ElMessageBox, 'alert').mockResolvedValue(undefined as never)
    vi.mocked(api.getLatestSiteAudit).mockResolvedValue({
      display_name: '演示局点', site_id: 'demo', total_size: 1024, file_count: 8, directory_count: 4,
      is_current: false, is_registered: true, is_referenced_by_bootstrap: false, is_demo: true,
      managed_demo: true, demo_seed_version: '2026.07.21.1', migration_status: 'current',
      raw_log_count: 1, parsed_database_count: 2, report_count: 0, artifact_count: 0, task_count: 0,
      online_mr_session_count: 0, mesh_source_count: 1, unique_business_data: false,
      duplicate_candidates: [], referenced_records: [], classification: 'managed_demo',
      recommended_action: 'keep_and_review', can_delete: false, safe_to_replace: true,
      physical_path: 'C:\\private\\sites\\demo', manifest_path: 'C:\\private\\audit.json',
    } as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="show-audit-demo"]').trigger('click')
    await flushPromises()

    const content = String(alert.mock.calls[0]?.[0])
    expect(content).toContain('文件：8 个')
    expect(content).toContain('唯一业务数据：无')
    expect(content).not.toMatch(/[A-Z]:\\/i)
    expect(content).not.toContain('manifest')
  })

  it('applies cleanup only after prepare and explicit confirmation', async () => {
    const emptyShell = site({ site_id: 'legacy-empty', display_name: 'Legacy 空壳', active: false, site_kind: 'legacy', classification: 'empty_shell', managed_demo: false, demo_seed_version: '', data_integrity: 'ok', recommended_action: 'safe_delete_to_recycle' })
    vi.mocked(api.listSites).mockResolvedValue([emptyShell])
    vi.mocked(api.prepareSiteCleanup).mockResolvedValue({ cleanup_token: '1234567890abcdef', site_id: 'legacy-empty', classification: 'empty_shell', blocking_reasons: [], recoverable: true, can_delete: true })
    vi.mocked(api.applySiteCleanup).mockResolvedValue({ task_id: 'cleanup-1', task_type: 'site_cleanup_apply' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'COMPLETED' } as never)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'legacy-empty', 'cleanup')

    expect(api.prepareSiteCleanup).toHaveBeenCalledWith('legacy-empty')
    expect(api.applySiteCleanup).toHaveBeenCalledWith('legacy-empty', '1234567890abcdef')
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'cleanup-1', module: 'logs' })
  })

  it('does not apply a cleanup plan blocked by the backend', async () => {
    vi.mocked(api.listSites).mockResolvedValue([site({ site_id: 'legacy-current', active: false, site_kind: 'legacy', classification: 'empty_shell', managed_demo: false })])
    vi.mocked(api.prepareSiteCleanup).mockResolvedValue({ cleanup_token: '1234567890abcdef', site_id: 'legacy-current', classification: 'empty_shell', blocking_reasons: ['当前局点不能清理'], recoverable: true, can_delete: false })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'legacy-current', 'cleanup')

    expect(api.applySiteCleanup).not.toHaveBeenCalled()
  })

  it('rebuilds a non-active Demo only after confirmation', async () => {
    vi.mocked(api.listSites).mockResolvedValue([site({ active: false })])
    vi.mocked(api.rebuildDemoSite).mockResolvedValue({ task_id: 'demo-1', task_type: 'site_demo_rebuild' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'COMPLETED' } as never)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'demo', 'rebuild-demo')

    expect(api.rebuildDemoSite).toHaveBeenCalledWith(false)
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'demo-1', module: 'logs' })
  })

  it('keeps current and Demo sites out of the ordinary delete flow', async () => {
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'demo', 'delete')

    expect(api.trashSite).not.toHaveBeenCalled()
    expect(warning).toHaveBeenCalledWith('当前局点不可删除，请先切换到其他局点。')
  })

  it('requires the full display name before moving a normal site to trash', async () => {
    const normal = site({ site_id: 'line-1', display_name: '一号线', active: false, site_kind: 'formal', classification: 'normal_site', managed_demo: false })
    vi.mocked(api.listSites).mockResolvedValueOnce([normal]).mockResolvedValueOnce([])
    vi.mocked(api.trashSite).mockResolvedValue({ site_id: 'line-1', display_name: '一号线', trash_path: '.trash/line-1-20260806', recoverable: true })
    const prompt = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValueOnce({ value: '一号线', action: 'confirm' } as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await emitSiteCommand(wrapper, 'line-1', 'delete')

    expect(prompt).toHaveBeenCalledWith(
      expect.stringContaining('一号线'),
      '删除局点',
      expect.objectContaining({ inputPlaceholder: '一号线' }),
    )
    expect(api.trashSite).toHaveBeenCalledWith('line-1', '一号线')
    expect(wrapper.text()).not.toContain('一号线')
    expect(adapter.refreshSiteContext).toHaveBeenCalledOnce()
  })

  it('refreshes the list and tray context only after a submitted import completes', async () => {
    adapter.selectSitePackage.mockResolvedValueOnce({ cancelled: false, path: 'C:\\packages\\line.ncsite' } as never)
    vi.mocked(api.inspectSitePackage).mockResolvedValue({
      site_id: 'line-6', site_uuid: 'site-6', site_name: '宁波地铁6号线',
      package_type: 'full_migration', package_id: 'package-6', base_revision: 1,
      file_count: 1, conflict_count: 0, conflicts: [], invalid_count: 0,
      estimated_additional_bytes: 0, can_import: true, contains_credentials: true,
      encrypted: false, credential_reentry_count: 0,
    })
    vi.mocked(api.importSite).mockResolvedValue({ task_id: 'import-6', task_type: 'site_import' })
    vi.mocked(tasks.getTask).mockResolvedValueOnce({ status: 'RUNNING' } as never)
      .mockResolvedValueOnce({ status: 'COMPLETED' } as never)
    vi.mocked(api.listSites)
      .mockResolvedValueOnce([site()])
      .mockResolvedValueOnce([site(), site({ site_id: 'line-6', display_name: '宁波地铁6号线', active: false, site_kind: 'formal', classification: 'normal_site', managed_demo: false })])
    vi.mocked(api.getDataRoot)
      .mockResolvedValueOnce({ data_root: 'C:\\data', default_data_root: 'C:\\default', site_count: 1, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })
      .mockResolvedValueOnce({ data_root: 'C:\\data', default_data_root: 'C:\\default', site_count: 2, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })
    const success = vi.spyOn(ElMessage, 'success')
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="import-site"]').trigger('click')
    await flushPromises()
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入并合并'))
    expect(importButton).toBeDefined()
    await importButton!.trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 800))
    await flushPromises()

    expect(api.listSites).toHaveBeenCalledTimes(2)
    expect(api.getDataRoot).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('宁波地铁6号线')
    expect(wrapper.text()).toContain('2 个局点')
    expect(adapter.refreshSiteContext).toHaveBeenCalledOnce()
    expect(success).toHaveBeenCalledWith('数据包导入任务已提交')
    expect(success).toHaveBeenCalledWith('局点数据包导入完成')
  })

  it('does not report import completion or refresh sites when the import task fails', async () => {
    adapter.selectSitePackage.mockResolvedValueOnce({ cancelled: false, path: 'C:\\packages\\broken.ncsite' } as never)
    vi.mocked(api.inspectSitePackage).mockResolvedValue({
      site_id: 'line-6', site_uuid: 'site-6', site_name: '宁波地铁6号线',
      package_type: 'full_migration', package_id: 'package-6', base_revision: 1,
      file_count: 1, conflict_count: 0, conflicts: [], invalid_count: 0,
      estimated_additional_bytes: 0, can_import: true, contains_credentials: true,
      encrypted: false, credential_reentry_count: 0,
    })
    vi.mocked(api.importSite).mockResolvedValue({ task_id: 'import-6', task_type: 'site_import' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'FAILED' } as never)
    const success = vi.spyOn(ElMessage, 'success')
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.get('[data-testid="import-site"]').trigger('click')
    await flushPromises()
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入并合并'))
    await importButton!.trigger('click')
    await flushPromises()

    expect(api.listSites).toHaveBeenCalledOnce()
    expect(adapter.refreshSiteContext).not.toHaveBeenCalled()
    expect(success).not.toHaveBeenCalledWith('局点数据包导入完成')
    expect(wrapper.text()).toContain('局点导入任务状态：FAILED')
  })
})
