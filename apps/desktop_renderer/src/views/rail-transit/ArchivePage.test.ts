// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetRendererFeaturesForTest, setRendererFeaturesForTest } from '../../features'
import ArchivePage from './ArchivePage.vue'

const mocks = vi.hoisted(() => ({ list: vi.fn(), start: vi.fn(), submit: vi.fn(), context: {} as Record<string, any> }))
vi.mock('../../api/groundUnattended', () => ({ listGroundHistory: mocks.list, startGroundHistoryExport: mocks.start }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => mocks.context }))
vi.mock('../../composables/useUserSelectedExport', () => ({ useUserSelectedExport: () => ({ submitExportAfterDestinationSelected: mocks.submit, hasActiveExportAction: () => false }) }))

const result = { items: [], total: 621, sources: { timeline: 'AVAILABLE' }, page: 1, page_size: 100 }
beforeEach(() => {
  setRendererFeaturesForTest({ 'capability.ground_unattended.history_export': { visible: true, enabled: true } })
  mocks.list.mockResolvedValue(result)
  mocks.submit.mockResolvedValue({ status: 'cancelled' })
  mocks.context = {
    t: (_key: string, fallback: string) => fallback, NcDataTable: { template: '<div />' },
    archives: [], archiveColumns: [], trains: ref([]), activeTab: ref('overview'),
    pageVisible: ref(true), pageActivated: ref(true), quickContextRevision: ref(0),
    selectedRunId: ref(''), syslogFilter: {}, syslogTimeRange: ref(null),
  }
})
afterEach(() => { vi.clearAllMocks(); resetRendererFeaturesForTest() })

describe('ArchivePage history workbench', () => {
  it('queries all filters and a server page beyond the initial hundred rows', async () => {
    const wrapper = shallowMount(ArchivePage)
    const vm = wrapper.vm as unknown as { filters: Record<string, string>; timeRange: Date[]; page: number; total: number; loadHistory: () => Promise<void> }
    Object.assign(vm.filters, { sort_order: 'asc', data_type: 'heartbeat', run_id: 'run-1', train_id: 'train-1', mr_id: 'mr-1', mr_role: 'CT', event_type: 'AP_OFFLINE' })
    vm.timeRange = [new Date('2026-11-01T00:00:00+08:00'), new Date('2026-11-07T00:00:00+08:00')]
    vm.page = 6
    await vm.loadHistory()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ sort_order: 'asc', page: 6, page_size: 100, mr_id: 'mr-1', event_type: 'AP_OFFLINE', start_at: '2026-10-31T16:00:00.000Z', end_at: '2026-11-06T16:00:00.000Z' }), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(vm.total).toBe(621)
    wrapper.unmount()
  })

  it('clears old site selection and discards its late response', async () => {
    let resolveOld!: (value: unknown) => void
    mocks.list.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve })).mockResolvedValue({ ...result, total: 2 })
    mocks.context.activeTab.value = 'archives'
    const wrapper = shallowMount(ArchivePage)
    const vm = wrapper.vm as unknown as { filters: Record<string, string>; rows: unknown[]; total: number; selected: unknown; detailOpen: boolean }
    vm.filters.mr_id = 'old-mr'; vm.selected = { record_id: 'old' }; vm.detailOpen = true
    mocks.context.quickContextRevision.value += 1
    await flushPromises()
    resolveOld({ ...result, items: [{ record_id: 'old' }], total: 999 })
    await flushPromises()
    expect(vm.total).toBe(2); expect(vm.rows).toEqual([])
    expect(vm.filters.mr_id).toBe(''); expect(vm.selected).toBeNull(); expect(vm.detailOpen).toBe(false)
    wrapper.unmount()
  })

  it('uses the shared destination coordinator and exports the full filter without a page cap', async () => {
    const wrapper = shallowMount(ArchivePage)
    const vm = wrapper.vm as unknown as { filters: Record<string, string>; exportHistory: () => Promise<void> }
    vm.filters.train_id = 'train-1'; vm.filters.sort_order = 'asc'
    await vm.exportHistory()
    expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'rail.ground_history', suggestedName: expect.stringMatching(/\.csv$/) }))
    expect(mocks.start).not.toHaveBeenCalled()
    const options = mocks.submit.mock.calls[0][0]
    vm.filters.train_id = 'later-edit'
    await options.submit()
    expect(mocks.start).toHaveBeenCalledWith(expect.objectContaining({ train_id: 'train-1', sort_order: 'asc' }))
    expect(mocks.start.mock.calls[0][0]).not.toHaveProperty('page')
    expect(mocks.start.mock.calls[0][0]).not.toHaveProperty('page_size')
    wrapper.unmount()
  })

  it('blocks history export when the capability is disabled', async () => {
    resetRendererFeaturesForTest()
    const wrapper = shallowMount(ArchivePage)
    await (wrapper.vm as unknown as { exportHistory: () => Promise<void> }).exportHistory()
    expect(mocks.submit).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
