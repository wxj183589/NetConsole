// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/siteStorage'
import * as tasks from '../../api/tasks'
import { ApiRequestError } from '../../api/client'
import type { SiteRecord } from '../../api/siteStorage'
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
}
vi.mock('../../platform/runtime', () => ({ getPlatformAdapter: () => adapter }))

function site(overrides: Partial<SiteRecord> = {}): SiteRecord {
  return {
    site_id: 'demo',
    display_name: '演示局点',
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
    })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="import-site"]').trigger('click')
    await flushPromises()

    expect(api.inspectSitePackage).toHaveBeenCalledWith('C:\\packages\\line.ncresult')
    expect(api.importSite).not.toHaveBeenCalled()
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

    await wrapper.find('[data-testid="cleanup-site-legacy-empty"]').trigger('click')
    await flushPromises()

    expect(api.prepareSiteCleanup).toHaveBeenCalledWith('legacy-empty')
    expect(api.applySiteCleanup).toHaveBeenCalledWith('legacy-empty', '1234567890abcdef')
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'cleanup-1', module: 'logs' })
  })

  it('does not apply a cleanup plan blocked by the backend', async () => {
    vi.mocked(api.listSites).mockResolvedValue([site({ site_id: 'legacy-current', active: false, site_kind: 'legacy', classification: 'empty_shell', managed_demo: false })])
    vi.mocked(api.prepareSiteCleanup).mockResolvedValue({ cleanup_token: '1234567890abcdef', site_id: 'legacy-current', classification: 'empty_shell', blocking_reasons: ['当前局点不能清理'], recoverable: true, can_delete: false })
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="cleanup-site-legacy-current"]').trigger('click')
    await flushPromises()

    expect(api.applySiteCleanup).not.toHaveBeenCalled()
  })

  it('rebuilds a non-active Demo only after confirmation', async () => {
    vi.mocked(api.listSites).mockResolvedValue([site({ active: false })])
    vi.mocked(api.rebuildDemoSite).mockResolvedValue({ task_id: 'demo-1', task_type: 'site_demo_rebuild' })
    vi.mocked(tasks.getTask).mockResolvedValue({ status: 'COMPLETED' } as never)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    await wrapper.find('[data-testid="rebuild-demo-demo"]').trigger('click')
    await flushPromises()

    expect(api.rebuildDemoSite).toHaveBeenCalledWith(false)
    expect(adapter.openTaskWindow).toHaveBeenCalledWith({ taskId: 'demo-1', module: 'logs' })
  })
})
