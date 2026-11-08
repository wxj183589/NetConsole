// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MeshBusinessSummary from './MeshBusinessSummary.vue'

const api = vi.hoisted(() => ({ summary: vi.fn(), aps: vi.fn(), risks: vi.fn() }))
vi.mock('../../api/meshAnalysis', () => ({
  getMeshBusinessSummary: api.summary, listMeshApSignalStatistics: api.aps, listMeshSingleLinks: api.risks,
}))
vi.mock('../../i18n/meshBusiness', () => ({ meshBusinessText: (key: string) => key }))
const summary = { ap_total: 2, grades: { GOOD: 1 }, single_link_count: 3, single_link_seconds: 6, single_link_ap_count: 1, single_link_radios: [1] }
const table = defineComponent({ props: ['data'], setup: props => () => h('div', { class: 'rows' }, JSON.stringify(props.data)) })
const stubs = {
  NcDataTable: table,
  ElDialog: defineComponent({ props: ['modelValue'], setup: (props, { slots }) => () => props.modelValue ? h('aside', slots.default?.()) : null }),
  ElPagination: defineComponent({ emits: ['current-change', 'update:currentPage'], setup: (_, { emit }) => () => h('button', { class: 'next-page', onClick() { emit('update:currentPage', 2); emit('current-change', 2) } }, 'next') }),
  ElButton: defineComponent({ setup: (_, { slots }) => () => h('button', slots.default?.()) }),
  ElAlert: defineComponent({ props: ['title'], setup: (props, { slots }) => () => h('div', [props.title, slots.default?.()]) }),
  ElInput: true, ElSelect: true, ElOption: true, ElCheckbox: true,
}

beforeEach(() => {
  vi.resetAllMocks()
  api.summary.mockResolvedValue(summary)
  api.aps.mockResolvedValue({ items: [{ peer_ap_name: 'first' }], total: 100 })
  api.risks.mockResolvedValue({ items: [{ risk_type: 'NO_STANDBY' }], total: 3 })
})

describe('Mesh business summary', () => {
  it('loads details only after a click and pages on the server', async () => {
    const wrapper = mount(MeshBusinessSummary, { props: { sessionId: 'one' }, global: { stubs } })
    await flushPromises()
    expect(api.summary).toHaveBeenCalledOnce()
    expect(api.aps).not.toHaveBeenCalled()
    await wrapper.findAll('.business-card')[1]!.trigger('click')
    await flushPromises()
    expect(api.aps).toHaveBeenLastCalledWith('one', expect.objectContaining({ signal_grade: 'GOOD', page: 1, page_size: 50 }), expect.any(AbortSignal))
    await wrapper.find('.next-page').trigger('click')
    await flushPromises()
    expect(api.aps).toHaveBeenLastCalledWith('one', expect.objectContaining({ page: 2 }), expect.any(AbortSignal))
    wrapper.unmount()
  })

  it('retains valid detail rows when a subsequent request fails', async () => {
    const wrapper = mount(MeshBusinessSummary, { props: { sessionId: 'one' }, global: { stubs } })
    await flushPromises()
    await wrapper.find('.business-card').trigger('click')
    await flushPromises()
    expect(api.aps).toHaveBeenLastCalledWith('one', expect.objectContaining({ signal_grade: 'RECOGNIZED' }), expect.any(AbortSignal))
    api.aps.mockRejectedValueOnce(new Error('network failure'))
    await wrapper.find('.next-page').trigger('click')
    await flushPromises()
    expect(wrapper.find('.rows').text()).toContain('first')
    expect(wrapper.text()).toContain('network failure')
    wrapper.unmount()
  })

  it('aborts old details and rejects late responses after changing sessions', async () => {
    let resolveOld!: (value: unknown) => void
    api.aps.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = mount(MeshBusinessSummary, { props: { sessionId: 'one' }, global: { stubs } })
    await flushPromises()
    await wrapper.find('.business-card').trigger('click')
    const signal = api.aps.mock.calls[0]![2] as AbortSignal
    await wrapper.setProps({ sessionId: 'two' })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    resolveOld({ items: [{ peer_ap_name: 'stale' }], total: 1 })
    await flushPromises()
    await wrapper.find('.risk-card').trigger('click')
    await flushPromises()
    expect(api.risks).toHaveBeenCalledWith('two', { page: 1, page_size: 50 }, expect.any(AbortSignal))
    expect(wrapper.text()).not.toContain('stale')
    wrapper.unmount()
  })
})
