// @vitest-environment happy-dom

import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import NcDataTable from './NcDataTable.vue'
import { tablePreferenceKey } from './tablePreferences'

const ElTable = defineComponent({
  name: 'ElTable',
  props: ['data', 'stripe', 'fit'],
  emits: ['header-dragend'],
  setup(_props, { slots }) {
    return () => h('div', { class: 'el-table-stub' }, slots.default?.())
  },
})

const ElTableColumn = defineComponent({
  name: 'ElTableColumn',
  props: ['columnKey', 'label', 'width', 'align', 'headerAlign', 'type'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'el-table-column-stub',
      'data-key': props.columnKey,
      'data-label': props.label,
      'data-width': props.width,
      'data-align': props.align,
      'data-header-align': props.headerAlign,
    }, slots.default?.({ row: { name: 'AP01' }, $index: 0 }))
  },
})

const global = {
  stubs: {
    ElTable,
    ElTableColumn,
    NcColumnSettings: true,
  },
}

afterEach(() => localStorage.clear())

describe('NcDataTable', () => {
  it('renders columns centered with widths that include the full header', async () => {
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'device-list',
        routeKey: '/devices',
        showColumnSettings: false,
        data: [{ name: 'AP01' }],
        columns: [{ key: 'name', label: '完整设备名称', valueType: 'name' }],
      },
      global,
    })
    await wrapper.vm.$nextTick()
    const column = wrapper.get('.el-table-column-stub')
    expect(column.attributes('data-align')).toBe('center')
    expect(column.attributes('data-header-align')).toBe('center')
    expect(Number(column.attributes('data-width'))).toBeGreaterThanOrEqual(140)
    expect(wrapper.getComponent(ElTable).props('fit')).toBe(true)
    wrapper.unmount()
  })

  it('clamps manual drag width and persists it in the isolated layout key', async () => {
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'device-list',
        routeKey: '/devices',
        language: 'zh-CN',
        userKey: 'operator',
        showColumnSettings: false,
        data: [{ name: 'AP01' }],
        columns: [{ key: 'name', label: '完整设备名称', valueType: 'name' }],
      },
      global,
    })
    wrapper.getComponent(ElTable).vm.$emit(
      'header-dragend',
      20,
      180,
      { columnKey: 'name' },
      new MouseEvent('mouseup'),
    )
    await wrapper.vm.$nextTick()

    const raw = localStorage.getItem(tablePreferenceKey({
      userKey: 'operator',
      routeKey: '/devices',
      tableId: 'device-list',
      language: 'zh-CN',
    }))
    expect(raw).not.toBeNull()
    const saved = JSON.parse(raw ?? '{}')
    expect(saved.columns[0].width).toBeGreaterThan(20)
    wrapper.unmount()
  })

  it('forwards the controlled cell slot for expand columns', () => {
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'device-details',
        routeKey: '/devices',
        showColumnSettings: false,
        data: [{ name: 'AP01' }],
        columns: [{ key: 'details', label: '详情', type: 'expand', valueType: 'text' }],
      },
      slots: {
        'cell-details': ({ row }: { row: { name: string } }) => h('span', { class: 'expanded-row' }, row.name),
      },
      global,
    })

    expect(wrapper.get('.expanded-row').text()).toBe('AP01')
    wrapper.unmount()
  })
})
