// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AcMeshLinkPage from './AcMeshLinkPage.vue'

const api = vi.hoisted(() => ({ detail: vi.fn(), aps: vi.fn(), snapshot: vi.fn(), raw: vi.fn() }))
const injected = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock('../../api/acMeshLink', () => ({ getAcMeshMrDetail: api.detail, listAcMeshPeerAps: api.aps,
  getAcMeshSnapshot: api.snapshot, getAcMeshRawTail: api.raw }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => injected.current }))
vi.mock('../../components/ground-unattended/AcMeshRssiChart.vue', () => ({ default: { template: '<div />' } }))

const peers = Array.from({ length: 3 }, (_, index) => ({ id: index + 1, mr_id: 'mr-ct', peer_ap_name: `AP-${index + 1}`,
  bssid: `00:00:00:00:00:0${index + 1}`, rssi: -50 - index, relation_status: 'current', device_time: '2026-01-01 00:00:00' }))
const mr = { mr_id: 'mr-ct', train_no: '25', car_end: 'CT', mr_name: '列车25-MR-CT', management_ip: '192.0.2.1',
  management_ips: ['192.0.2.1'], data_status: 'fresh', peer_aps: peers }
const props = { summary: null, links: [], mrs: [mr], snapshots: [], rawTail: null, controllers: [],
  selectedControllerId: '', controllersLoading: false, controllersError: false, loading: false }
const global = { renderStubDefaultSlot: true, stubs: { ElDrawer: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /></div>' },
  NcDataTable: { props: ['data'], template: '<div class="rows">{{ data.length }}</div>' } } }

beforeEach(() => {
  injected.current = { acMeshQuery: reactive({ query: '', station: '', section: '', carEnd: '', dataStatus: '',
    matchStatus: '', multiplePeers: false, abnormalOnly: false, page: 1, mrPage: 1, snapshotPage: 1, pageSize: 50 }),
  acMeshTotals: reactive({ mrs: 1, snapshots: 0 }), loadAcMesh: vi.fn() }
  api.aps.mockResolvedValue({ items: [], total: 0 })
})
afterEach(() => vi.clearAllMocks())

describe('AC Mesh-Link MR page', () => {
  it('shows MR groups with all peer count and opens the full peer detail', async () => {
    api.detail.mockResolvedValue({ mr, current_links: peers, history_links: [], history_total: 0,
      history_note: 'observations only', recent_events: [] })
    const wrapper = shallowMount(AcMeshLinkPage, { props: props as never, global })
    expect((wrapper.vm as unknown as { view: string }).view).toBe('mr')
    expect(wrapper.find('.train-heading').text()).toContain('25')
    expect(wrapper.find('.peer-count').text()).toContain('3')
    expect(wrapper.findAll('.mr-row .peer-list el-tag-stub')).toHaveLength(2)
    await wrapper.find('.mr-row').trigger('click')
    await flushPromises()
    expect(api.detail).toHaveBeenCalledWith('mr-ct', expect.objectContaining({ page: 1, page_size: 100 }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.find('.drawer-content .rows').text()).toBe('3')
    wrapper.unmount()
  })

  it('discards an old MR detail after opening a reverse AP', async () => {
    let resolveOld!: (value: unknown) => void
    api.detail.mockImplementation(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = shallowMount(AcMeshLinkPage, { props: props as never, global })
    const vm = wrapper.vm as unknown as { openMr: (value: typeof mr) => Promise<void>; openAp: (value: unknown) => void;
      selectedAp: unknown; detail: unknown }
    const pending = vm.openMr(mr)
    const signal = api.detail.mock.calls[0]![2].signal as AbortSignal
    const ap = { ap_key: 'ap-1', ap_name: 'AP-1', mac: '00:00:00:00:00:01', relations: peers }
    vm.openAp(ap)
    resolveOld({ mr, current_links: peers, history_links: [], history_total: 0, recent_events: [] })
    await pending
    expect(signal.aborted).toBe(true)
    expect(vm.selectedAp).toEqual(ap)
    expect(vm.detail).toBeNull()
    wrapper.unmount()
  })

  it('zooms continuously around the pointer and pans without changing node layout', async () => {
    const wrapper = shallowMount(AcMeshLinkPage, { props: props as never, global })
    const vm = wrapper.vm as unknown as { view: string; fitGraph: () => void; graphViewport: { x: number; y: number; width: number; height: number } }
    vm.view = 'graph'
    await nextTick()
    const svg = wrapper.find('.relation-graph')
    vi.spyOn(svg.element, 'getBoundingClientRect').mockReturnValue({ left: 100, top: 50, width: 1000, height: 500 } as DOMRect)
    vm.fitGraph()
    const before = { ...vm.graphViewport }
    await svg.trigger('wheel', { deltaY: -100, deltaMode: 0, clientX: 350, clientY: 175 })
    const zoomed = { ...vm.graphViewport }
    expect(zoomed.width).toBeLessThan(before.width)
    expect(zoomed.x + zoomed.width * 0.25).toBeCloseTo(before.x + before.width * 0.25)
    expect(zoomed.y + zoomed.height * 0.25).toBeCloseTo(before.y + before.height * 0.25)
    await svg.trigger('pointerdown', { button: 0, pointerId: 1, clientX: 350, clientY: 175 })
    await svg.trigger('pointermove', { pointerId: 1, clientX: 450, clientY: 225 })
    await svg.trigger('pointerup', { pointerId: 1, clientX: 450, clientY: 225 })
    expect(vm.graphViewport.x).toBeCloseTo(zoomed.x - zoomed.width * 0.1)
    expect(vm.graphViewport.y).toBeCloseTo(zoomed.y - zoomed.height * 0.1)
    wrapper.unmount()
  })

  it('keeps the graph view after data refresh and opens the clicked AP relation', async () => {
    const wrapper = shallowMount(AcMeshLinkPage, { props: props as never, global })
    const vm = wrapper.vm as unknown as { view: string; fitGraph: () => void; graphViewport: { x: number; y: number; width: number; height: number }; selectedAp: { ap_name: string; relations: unknown[] } | null }
    vm.view = 'graph'
    await nextTick()
    const svg = wrapper.find('.relation-graph')
    vi.spyOn(svg.element, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 1000, height: 500 } as DOMRect)
    vm.fitGraph()
    await svg.trigger('wheel', { deltaY: -100, clientX: 500, clientY: 250 })
    const viewport = { ...vm.graphViewport }
    await wrapper.setProps({ mrs: [{ ...mr, peer_aps: [...peers] }] } as never)
    expect(vm.graphViewport).toEqual(viewport)
    await wrapper.find('.graph-ap-node').trigger('click')
    expect(wrapper.find('.graph-ap-node').classes()).toContain('graph-selected')
    expect(vm.selectedAp?.ap_name).toBe('AP-1')
    expect(vm.selectedAp?.relations).toHaveLength(1)
    expect(wrapper.find('.drawer-content').text()).toContain('AP-1')
    wrapper.unmount()
  })
})
