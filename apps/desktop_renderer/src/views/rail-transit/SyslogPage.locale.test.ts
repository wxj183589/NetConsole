// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAppLocale } from '../../i18n/runtime'
import SyslogPage from './SyslogPage.vue'

const state = vi.hoisted(() => ({ context: {} as Record<string, unknown> }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => state.context }))

const workspace = { template: '<div><slot name="header" /><slot name="summary" /><slot name="actions" /><slot /><slot name="pagination" /></div>' }
const filter = { props: ['labels', 'placeholder'], template: '<div>{{ placeholder }} {{ labels ? Object.values(labels).join(" / ") : "" }}</div>' }
const slot = { template: '<div><slot /></div>' }

afterEach(() => { setAppLocale('zh_CN') })

describe('Syslog page language switching', () => {
  it('updates filter labels, date placeholders and selection guidance without changing codes', async () => {
    setAppLocale('zh_CN')
    state.context = {
      NcLogWorkspace: workspace, NcMultiValueFilter: filter,
      NcDataTable: { template: '<div />' },
      syslogFilter: ref({ identityStatus: ['VERIFIED'], page: 1, pageSize: 50 }),
      syslogAdvancedFiltersOpen: ref(true), syslogAdvancedFilterCount: ref(2),
      selectedSyslogRecords: ref([{ id: 1 }]), syslogDiagnostics: ref({ source_kind: 'ACTIVE' }),
      health: ref({ udp_running: true }), groundEventLabel: String,
      groundSourceLabel: String, groundStatusLabel: String,
    }
    const wrapper = mount(SyslogPage, { global: { stubs: {
      ElInput: true, ElButton: slot, ElCheckbox: slot, ElCollapseTransition: slot,
      ElPagination: true,
      ElDatePicker: { props: ['startPlaceholder', 'endPlaceholder'], template: '<div>{{ startPlaceholder }} / {{ endPlaceholder }}</div>' },
    } } })
    expect(wrapper.text()).toContain('高级筛选（2 个条件）')
    expect(wrapper.text()).toContain('开始时间 / 结束时间')
    expect(wrapper.text()).toContain('身份已确认')
    setAppLocale('en_US')
    await nextTick()
    expect(wrapper.text()).toContain('Advanced filters (2)')
    expect(wrapper.text()).toContain('Start time / End time')
    expect(wrapper.text()).toContain('Verified identity')
    expect(wrapper.text()).toContain('High confidence / Medium confidence')
    expect(wrapper.text()).toContain('1 selected (use the header checkbox to select this page)')
    expect(wrapper.text()).toContain('Listening')
    expect((state.context.syslogFilter as { value: { identityStatus: string[] } }).value.identityStatus).toEqual(['VERIFIED'])
    setAppLocale('zh_CN')
    await nextTick()
    expect(wrapper.text()).toContain('高级筛选（2 个条件）')
    wrapper.unmount()
  })
})
