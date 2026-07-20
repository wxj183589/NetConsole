// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/siteStorage'
import SiteStoragePanel from './SiteStoragePanel.vue'

vi.mock('../../api/siteStorage')

const adapter = {
  hostType: 'electron' as const,
  selectDataRootDirectory: vi.fn(async () => ({ cancelled: true })),
  selectSitePackage: vi.fn(async () => ({ cancelled: true })),
  selectSiteExportDestination: vi.fn(async () => ({ cancelled: true })),
  restartBackend: vi.fn(async () => ({ success: true })),
  openTaskWindow: vi.fn(async () => ({ success: true })),
  executeSettingsAction: vi.fn(async () => ({ success: true })),
}
vi.mock('../../platform/runtime', () => ({ getPlatformAdapter: () => adapter }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listSites).mockResolvedValue([{ site_id: 'demo', display_name: '演示局点', path: 'C:\\data\\sites\\demo', created_at: '', updated_at: '', remark: '', active: true, size_bytes: 1024 }])
  vi.mocked(api.getDataRoot).mockResolvedValue({ data_root: 'C:\\data', default_data_root: 'C:\\default', site_count: 1, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })
})

describe('SiteStoragePanel', () => {
  it('shows the active site and controlled storage actions', async () => {
    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('演示局点')
    expect(wrapper.text()).toContain('全局数据根')
    expect(wrapper.find('[data-testid="create-site"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="migrate-data-root"]').exists()).toBe(true)
  })

  it('renders every legacy site returned by the registry API', async () => {
    vi.mocked(api.listSites).mockResolvedValue([
      { site_id: 'demo', display_name: '演示局点', path: 'C:\\data\\sites\\demo', created_at: '', updated_at: '', remark: '', active: true, size_bytes: 1024 },
      { site_id: 'legacy-dfd356e96ea0', display_name: '宁波地铁12号线', path: 'C:\\data\\sites\\宁波地铁12号线', created_at: '', updated_at: '', remark: '', active: false, size_bytes: 2048 },
    ])
    vi.mocked(api.getDataRoot).mockResolvedValue({ data_root: 'C:\\data', default_data_root: 'C:\\default', site_count: 2, active_site_id: 'demo', storage_mode: 'persistent', data_root_kind: 'persistent', persistent: true })

    const wrapper = mount(SiteStoragePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('宁波地铁12号线')
    expect(wrapper.text()).toContain('legacy-dfd356e96ea0')
    expect(wrapper.text()).toContain('2 个局点')
  })

  it('creates a site only after collecting display name and stable id', async () => {
    vi.spyOn(ElMessageBox, 'prompt')
      .mockResolvedValueOnce({ value: '宁波地铁12号线' } as never)
      .mockResolvedValueOnce({ value: 'ningbo-line-12' } as never)
    vi.mocked(api.createSite).mockResolvedValue({ site_id: 'ningbo-line-12', display_name: '宁波地铁12号线', path: 'C:\\data\\sites\\ningbo-line-12', created_at: '', updated_at: '', remark: '', active: false, size_bytes: 0 })
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
})
