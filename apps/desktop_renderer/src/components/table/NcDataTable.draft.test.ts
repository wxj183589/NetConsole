// @vitest-environment happy-dom

import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import NcDataTable from './NcDataTable.vue'
import NcColumnSettings from './NcColumnSettings.vue'
import * as preferences from './tablePreferences'

const doLayout = vi.fn()
const ElTable = defineComponent({
  name: 'ElTable', props: ['data'], emits: ['header-dragend'],
  setup(_props, { slots, expose }) {
    expose({ doLayout })
    return () => h('div', slots.default?.())
  },
})
const ElTableColumn = defineComponent({
  name: 'ElTableColumn', props: ['columnKey', 'width', 'fixed'],
  setup(props) { return () => h('div', { class: 'column', 'data-key': props.columnKey, 'data-fixed': props.fixed || 'none', 'data-width': props.width }) },
})
const ElPopover = defineComponent({
  name: 'ElPopover', props: ['visible'], emits: ['show', 'update:visible'],
  setup(_props, { slots }) { return () => h('div', [slots.reference?.(), slots.default?.()]) },
})
const ElButton = defineComponent({
  name: 'ElButton', props: ['icon', 'circle', 'link', 'type', 'disabled'],
  setup(props, { slots }) { return () => h('button', { disabled: props.disabled }, slots.default?.()) },
})
const ElCheckbox = defineComponent({
  name: 'ElCheckbox', props: ['modelValue', 'disabled'], emits: ['change'],
  setup(props, { slots, emit }) { return () => h('label', [h('input', { type: 'checkbox', checked: props.modelValue, disabled: props.disabled, onChange: (event: Event) => emit('change', (event.target as HTMLInputElement).checked) }), slots.default?.()]) },
})
const global = { stubs: { ElTable, ElTableColumn, ElPopover, ElButton, ElCheckbox, ElTooltip: { template: '<span><slot /></span>' } } }
const columns = Array.from({ length: 15 }, (_, index) => ({ key: `field${index}`, label: `业务字段${index}`, hideable: index > 0 }))
const settle = async () => { await flushPromises(); await new Promise(resolve => setTimeout(resolve, 130)); await flushPromises() }
type TableWrapper = Pick<ReturnType<typeof mount>, 'getComponent' | 'findAll'>
function open(wrapper: TableWrapper) { wrapper.getComponent(ElPopover).vm.$emit('show') }
function button(wrapper: TableWrapper, label: string) {
  const found = wrapper.findAll('button').find(item => item.text() === label || item.attributes('aria-label') === label)
  if (!found) throw new Error(`Button missing: ${label}`)
  return found
}
const tableProps = { tableId: 'draft-layout', routeKey: '/draft', language: 'zh-CN', columns }

afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); doLayout.mockClear() })

describe('NcDataTable column draft', () => {
  it('applies ten field changes over 100000 records with one save, one layout and zero queries', async () => {
    const data = Array.from({ length: 100000 }, (_, index) => Object.fromEntries(columns.map(column => [column.key, `${column.label}-${index}`])))
    const query = vi.fn()
    vi.stubGlobal('fetch', query)
    const save = vi.spyOn(preferences, 'saveTablePreferencesAsync')
    const wrapper = mount(NcDataTable, { props: { ...tableProps, data }, global })
    await settle()
    save.mockClear(); doLayout.mockClear()
    open(wrapper)
    await flushPromises()
    const settings = wrapper.getComponent(NcColumnSettings)
    for (let index = 1; index <= 10; index += 1) {
      settings.findAllComponents(ElCheckbox)[index]!.vm.$emit('change', false)
      await flushPromises()
    }
    const last = settings.findAll('.nc-column-settings__item')[14]!
    await last.findAll('button')[0]!.trigger('click')
    await last.findAll('button')[1]!.trigger('click')
    expect(save).not.toHaveBeenCalled()
    expect(doLayout).not.toHaveBeenCalled()
    expect(wrapper.findAll('.column')).toHaveLength(15)
    expect(wrapper.getComponent(ElTable).props('data')).toHaveLength(100000)
    await button(settings, '应用并查询').trigger('click')
    await settle()
    expect(save).toHaveBeenCalledTimes(1)
    expect(doLayout).toHaveBeenCalledTimes(1)
    expect(query).not.toHaveBeenCalled()
    expect(wrapper.findAll('.column').map(item => item.attributes('data-key'))).toEqual(['field0', 'field11', 'field12', 'field14', 'field13'])
    expect(wrapper.find('[data-key=field14]').attributes('data-fixed')).toBe('left')
    expect(wrapper.getComponent(ElTable).props('data')).toHaveLength(100000)
    expect(wrapper.getComponent(ElTable).props('data')[99999]).toEqual(data[99999])
    wrapper.unmount()
    const restored = mount(NcDataTable, { props: { ...tableProps, data }, global })
    await settle()
    expect(restored.findAll('.column').map(item => item.attributes('data-key'))).toEqual(['field0', 'field11', 'field12', 'field14', 'field13'])
    expect(restored.find('[data-key=field14]').attributes('data-fixed')).toBe('left')
    restored.unmount()
  }, 20000)

  it('keeps reset and autofit in the draft until apply and discards cancelled changes', async () => {
    const save = vi.spyOn(preferences, 'saveTablePreferencesAsync')
    const wrapper = mount(NcDataTable, { props: { ...tableProps, data: [{ field0: 'AP01' }] }, global })
    await settle()
    wrapper.getComponent(ElTable).vm.$emit('header-dragend', 350, 180, { columnKey: 'field0' }, new MouseEvent('mouseup'))
    await new Promise(resolve => setTimeout(resolve, 400))
    await settle()
    const original = localStorage.getItem(preferences.tablePreferenceKey({ userKey: 'local-user', ...tableProps }))
    const manualWidth = wrapper.find('[data-key=field0]').attributes('data-width')
    expect(Number(manualWidth)).toBeGreaterThan(200)
    save.mockClear(); doLayout.mockClear()
    open(wrapper); await flushPromises()
    const settings = wrapper.getComponent(NcColumnSettings)
    settings.findAllComponents(ElCheckbox)[1]!.vm.$emit('change', false)
    await button(settings, '自动适应列宽').trigger('click')
    await button(settings, '恢复默认布局').trigger('click')
    await button(settings, '取消').trigger('click')
    expect(save).not.toHaveBeenCalled()
    expect(doLayout).not.toHaveBeenCalled()
    expect(localStorage.getItem(preferences.tablePreferenceKey({ userKey: 'local-user', ...tableProps }))).toBe(original)
    expect(wrapper.find('[data-key=field0]').attributes('data-width')).toBe(manualWidth)
    open(wrapper); await flushPromises()
    expect(settings.findAllComponents(ElCheckbox)[1]!.props('modelValue')).toBe(true)
    await button(settings, '恢复默认布局').trigger('click')
    settings.findAllComponents(ElCheckbox)[1]!.vm.$emit('change', false)
    await button(settings, '应用并查询').trigger('click')
    await settle()
    expect(save).toHaveBeenCalledTimes(1)
    expect(doLayout).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-key=field1]').exists()).toBe(false)
    const stored = JSON.parse(localStorage.getItem(preferences.tablePreferenceKey({ userKey: 'local-user', ...tableProps }))!)
    expect(stored.columns.every((column: { width?: number }) => column.width == null)).toBe(true)
    expect(wrapper.find('[data-key=field0]').attributes('data-width')).not.toBe(manualWidth)
    wrapper.unmount()
  })

  it('discards a closed draft on reopening and does not save unchanged apply', async () => {
    const save = vi.spyOn(preferences, 'saveTablePreferencesAsync')
    const wrapper = mount(NcDataTable, { props: tableProps, global })
    await settle(); save.mockClear(); doLayout.mockClear()
    open(wrapper); await flushPromises()
    const settings = wrapper.getComponent(NcColumnSettings)
    settings.findAllComponents(ElCheckbox)[1]!.vm.$emit('change', false)
    wrapper.getComponent(ElPopover).vm.$emit('update:visible', false)
    open(wrapper); await flushPromises()
    expect(settings.findAllComponents(ElCheckbox)[1]!.props('modelValue')).toBe(true)
    await button(settings, '应用并查询').trigger('click')
    await settle()
    expect(save).not.toHaveBeenCalled()
    expect(doLayout).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
