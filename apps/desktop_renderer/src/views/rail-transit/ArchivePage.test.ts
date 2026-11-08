// @vitest-environment happy-dom
import { ref } from 'vue'
import { shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ArchivePage from './ArchivePage.vue'

const mocks = vi.hoisted(() => ({ remove: vi.fn(), context: {} as Record<string, any> }))
vi.mock('../../api/groundUnattended', () => ({}))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => mocks.context }))

const archive = (archive_id: string, run_date: string) => ({
  archive_id, site_id: 'demo', run_id: `run-${archive_id}`, run_date,
  actual_started_at: `${run_date}T08:00:00+08:00`, actual_ended_at: `${run_date}T18:00:00+08:00`,
  mainline_train_count: 1, ping_target_count: 2, ping_sample_count: 20, covered_train_count: 1,
  session_count: 2, complete_session_count: 1, partial_session_count: 0, syslog_record_count: 3,
  archive_size_bytes: 100, sha256: '', manifest_sha256: '', archive_status: 'READY', file_count: 1,
  integrity_status: 'READY', retention_until: '', summary: {}, message: '', created_at: '', updated_at: '',
})

beforeEach(() => {
  mocks.remove.mockResolvedValue(undefined)
  mocks.context = {
    Delete: {}, Download: {}, FolderOpened: {}, NcDataTable: { template: '<div><slot /></div>' },
    t: (_key: string, fallback: string) => fallback,
    groundStatusLabel: (value: string) => value, statusType: () => 'success',
    archives: ref([archive('a-1', '2026-11-08'), archive('a-2', '2026-11-07')]),
    selectedArchives: ref([]), archiveTableHost: ref(null), archiveTableMaxHeight: ref(420), archiveColumns: [],
    showArchive: vi.fn(), removeArchive: vi.fn(), removeSelectedArchives: mocks.remove,
    downloadArchiveSummary: vi.fn(), downloadArchiveZip: vi.fn(), openArchiveDirectory: vi.fn(),
    activeTab: ref('archives'), pageVisible: ref(true), pageActivated: ref(true), quickContextRevision: ref(0),
  }
})
afterEach(() => vi.clearAllMocks())

describe('ArchivePage daily archive list', () => {
  it('does not query or render the timeline history workbench', () => {
    const wrapper = shallowMount(ArchivePage)
    expect(wrapper.text()).toContain('历史归档')
    expect(wrapper.text()).not.toContain('历史查询工作台')
    expect(wrapper.text()).toContain('已选择 0 个归档包')
  })

  it('deduplicates stable archive IDs and delegates batch deletion', async () => {
    const wrapper = shallowMount(ArchivePage)
    const vm = wrapper.vm as unknown as { onArchiveSelection: (rows: any[]) => void; removeSelectedArchiveRows: () => void }
    vm.onArchiveSelection([archive('a-1', '2026-11-08'), archive('a-1', '2026-11-08'), archive('a-2', '2026-11-07')])
    expect(mocks.context.selectedArchives.value.map((row: any) => row.archive_id)).toEqual(['a-1', 'a-2'])
    vm.removeSelectedArchiveRows()
    expect(mocks.remove).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('clears selection when the archive tab is hidden or the site context changes', async () => {
    const wrapper = shallowMount(ArchivePage)
    mocks.context.selectedArchives.value = [archive('a-1', '2026-11-08')]
    mocks.context.activeTab.value = 'timeline'
    await wrapper.vm.$nextTick()
    expect(mocks.context.selectedArchives.value).toEqual([])
    wrapper.unmount()
  })
})
