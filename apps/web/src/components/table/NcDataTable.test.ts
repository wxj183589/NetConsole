// @vitest-environment happy-dom

import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import NcDataTable from './NcDataTable.vue'
import { tablePreferenceKey } from './tablePreferences'

const tableDoLayout = vi.fn()

const ElTable = defineComponent({
  name: 'ElTable',
  props: {
    data: { type: Array, default: () => [] },
    stripe: Boolean,
    fit: Boolean,
    flexible: Boolean,
    scrollbarAlwaysOn: Boolean,
  },
  emits: ['header-dragend', 'row-contextmenu'],
  setup(_props, { slots, expose }) {
    expose({ doLayout: tableDoLayout })
    return () => h('div', { class: 'el-table-stub' }, slots.default?.())
  },
})

const ElTableColumn = defineComponent({
  name: 'ElTableColumn',
  props: ['columnKey', 'label', 'width', 'align', 'headerAlign', 'type', 'fixed', 'className', 'labelClassName'],
  setup(props, { slots }) {
    return () => h('div', {
      class: ['el-table-column-stub', props.className],
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

afterEach(() => { localStorage.clear(); tableDoLayout.mockClear(); Reflect.deleteProperty(window, 'netconsoleDesktop') })

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

  it('distributes business columns to the measured scroll viewport', async () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get() { return this.classList.contains('nc-data-table__scroll') ? 600 : 0 },
    })
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'device-list-fill',
        routeKey: '/devices',
        showColumnSettings: false,
        data: [{ name: 'AP01', group: '默认', status: '在线' }],
        columns: [
          { key: 'name', label: '设备名称', valueType: 'name' },
          { key: 'group', label: '分组', valueType: 'text' },
          { key: 'status', label: '状态', valueType: 'status' },
        ],
      },
      global,
    })
    try {
      await wrapper.vm.$nextTick()
      const totalWidth = wrapper.findAll('.el-table-column-stub')
        .reduce((total, column) => total + Number(column.attributes('data-width')), 0)
      expect(totalWidth).toBe(600)
      expect(wrapper.get('.el-table-stub').attributes('style')).toContain('width: 100%')
      expect(wrapper.getComponent(ElTable).props('flexible')).toBe(true)
      expect(wrapper.getComponent(ElTable).props('scrollbarAlwaysOn')).toBe(true)
    } finally {
      wrapper.unmount()
      if (original) Object.defineProperty(HTMLElement.prototype, 'clientWidth', original)
      else delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth
    }
  })

  it('clamps manual drag width and safely updates reactive layout preferences', async () => {
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'device-list',
        routeKey: '/devices',
        language: 'zh-CN',
        userKey: 'operator',
        showColumnSettings: true,
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
    const settings = wrapper.findComponent({ name: 'NcColumnSettings' })
    expect(() => settings.vm.$emit('toggle', 'name', true)).not.toThrow()
    await wrapper.vm.$nextTick()
    wrapper.unmount()
  })

  it('normalizes partial preferences so newly added columns remain operable', async () => {
    localStorage.setItem(tablePreferenceKey({ userKey: 'local-user', routeKey: '/devices', tableId: 'device-list', language: 'zh-CN' }), JSON.stringify({
      version: 1,
      order: ['name'],
      columns: [{ key: 'name', visible: true }],
    }))
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'device-list',
        routeKey: '/devices',
        language: 'zh-CN',
        showColumnSettings: true,
        data: [{ name: 'AP01', status: '在线', group: '默认' }],
        columns: [
          { key: 'name', label: '名称', valueType: 'name' },
          { key: 'status', label: '状态', valueType: 'status' },
          { key: 'group', label: '分组', valueType: 'text' },
        ],
      },
      global,
    })
    const settings = wrapper.findComponent({ name: 'NcColumnSettings' })
    settings.vm.$emit('toggle', 'group', false)
    await flushPromises()
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 120))
    await flushPromises()
    expect(wrapper.findAll('.el-table-column-stub:not(.nc-data-table__column--hidden)').map((item) => item.attributes('data-key'))).toEqual(['name', 'status'])
    expect(tableDoLayout).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not let an asynchronous Electron preference overwrite a user mutation', async () => {
    let resolvePreference: (value: unknown) => void = () => undefined
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { getUiPreference: vi.fn(() => new Promise((resolve) => { resolvePreference = resolve })) },
    })
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'mesh-analysis-link-details:v2',
        routeKey: '/rail-transit/mesh-analysis',
        language: 'zh-CN',
        showColumnSettings: true,
        data: [{ name: 'AP01', status: '在线' }],
        columns: [
          { key: 'name', label: '名称', valueType: 'name' },
          { key: 'status', label: '状态', valueType: 'status' },
        ],
      },
      global,
    })
    const settings = wrapper.findComponent({ name: 'NcColumnSettings' })
    settings.vm.$emit('toggle', 'status', false)
    await wrapper.vm.$nextTick()
    resolvePreference({ version: 1, order: ['name', 'status'], columns: [{ key: 'name', visible: true }, { key: 'status', visible: true }] })
    await flushPromises()
    expect(wrapper.findAll('.el-table-column-stub:not(.nc-data-table__column--hidden)').map((item) => item.attributes('data-key'))).toEqual(['name'])
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

  it('owns the typed context menu, explains disabled actions, clamps it and closes on Escape', async () => {
    const action = vi.fn()
    const row = { name: 'AP01' }
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'context-menu',
        routeKey: '/ac-management',
        showColumnSettings: false,
        data: [row],
        columns: [{ key: 'name', label: '名称', valueType: 'name' }],
        contextMenuItems: [
          { key: 'open', label: '打开', action },
          { key: 'disabled', label: '不可用动作', action, disabled: true, disabledReason: '当前 AP 离线' },
        ],
      },
      global,
    })
    wrapper.getComponent(ElTable).vm.$emit(
      'row-contextmenu',
      row,
      { property: 'name' },
      new MouseEvent('contextmenu', { clientX: window.innerWidth - 1, clientY: window.innerHeight - 1 }),
    )
    await wrapper.vm.$nextTick()

    const menu = wrapper.get('[role="menu"]')
    expect(Number.parseInt(menu.attributes('style')?.match(/left: (\d+)px/)?.[1] || '0', 10)).toBeLessThan(window.innerWidth)
    expect(menu.text()).toContain('当前 AP 离线')
    const disabled = menu.findAll('button').find((button) => button.text().includes('不可用动作'))!
    expect(disabled.attributes()).toHaveProperty('disabled')
    await menu.findAll('button').find((button) => button.text().includes('打开'))!.trigger('click')
    expect(action).toHaveBeenCalledWith(expect.objectContaining({ row, columnKey: 'name', cellValue: 'AP01' }))
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)

    wrapper.getComponent(ElTable).vm.$emit('row-contextmenu', row, { property: 'name' }, new MouseEvent('contextmenu'))
    await wrapper.vm.$nextTick()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
