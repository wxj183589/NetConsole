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
    maxHeight: [Number, String],
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
      'data-fixed': props.fixed || 'none',
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

afterEach(() => {
  localStorage.clear()
  tableDoLayout.mockClear()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
  Reflect.deleteProperty(document.documentElement, 'clientWidth')
  Reflect.deleteProperty(document.documentElement, 'clientHeight')
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('NcDataTable', () => {
  it('uses content height when autoHeight is enabled', () => {
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'adaptive-table',
        routeKey: '/adaptive',
        showColumnSettings: false,
        autoHeight: true,
        maxHeight: 420,
        data: Array.from({ length: 5 }, (_, index) => ({ name: `AP${index}` })),
        columns: [{ key: 'name', label: '名称', valueType: 'name' }],
      },
      global,
    })

    expect(wrapper.classes()).toContain('nc-data-table--auto-height')
    expect(wrapper.getComponent(ElTable).props('maxHeight')).toBe(420)
    wrapper.unmount()
  })

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

  it('restores visibility, order, right pinning and manual width after remount', async () => {
    const props = {
      tableId: 'device-detail-sections',
      routeKey: '/devices/:deviceId',
      preferenceScope: 'interfaces',
      language: 'zh-CN',
      showColumnSettings: true,
      data: [{ name: 'GE1/0/1', status: 'UP', description: 'uplink' }],
      columns: [
        { key: 'name', label: '接口', valueType: 'port' as const, minWidth: 120 },
        { key: 'status', label: '状态', valueType: 'status' as const },
        { key: 'description', label: '描述', valueType: 'description' as const },
      ],
    }
    let wrapper = mount(NcDataTable, { props, global })
    const settings = wrapper.findComponent({ name: 'NcColumnSettings' })

    settings.vm.$emit('toggle', 'status', false)
    settings.vm.$emit('move', 'description', -1)
    settings.vm.$emit('pin', 'description')
    settings.vm.$emit('pin', 'description')
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 140))
    wrapper.getComponent(ElTable).vm.$emit(
      'header-dragend',
      260,
      180,
      { columnKey: 'name' },
      new MouseEvent('mouseup'),
    )
    await flushPromises()
    wrapper.unmount()

    wrapper = mount(NcDataTable, { props, global })
    await flushPromises()
    const columns = wrapper.findAll('.el-table-column-stub')
    expect(columns.map((column) => column.attributes('data-key'))).toEqual(['name', 'description'])
    expect(columns[0].attributes('data-width')).toBe('260')
    expect(columns[1].attributes('data-fixed')).toBe('right')

    wrapper.findComponent({ name: 'NcColumnSettings' }).vm.$emit('pin', 'description')
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 140))
    expect(JSON.parse(localStorage.getItem(tablePreferenceKey({
      userKey: 'local-user',
      routeKey: '/devices/:deviceId',
      tableId: 'device-detail-sections:interfaces',
      language: 'zh-CN',
    })) || '{}').columns.find((column: { key: string }) => column.key === 'description').fixed).toBe(false)
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

  it('teleports the typed context menu to body, measures it and flips inside the viewport', async () => {
    const action = vi.fn()
    const row = { name: 'AP01' }
    Object.defineProperty(document.documentElement, 'clientWidth', { configurable: true, value: 320 })
    Object.defineProperty(document.documentElement, 'clientHeight', { configurable: true, value: 240 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const width = this.classList.contains('nc-data-table__context-menu') ? 180 : 0
      const height = this.classList.contains('nc-data-table__context-menu') ? 160 : 0
      return {
        x: 0,
        y: 0,
        top: 0,
        right: width,
        bottom: height,
        left: 0,
        width,
        height,
        toJSON: () => undefined,
      }
    })
    const wrapper = mount(NcDataTable, {
      attachTo: document.body,
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
      { property: 'name', columnKey: 'name' },
      new MouseEvent('contextmenu', { clientX: 315, clientY: 235 }),
    )
    await flushPromises()

    const menu = document.body.querySelector<HTMLElement>('[role="menu"]')
    expect(menu).not.toBeNull()
    expect(menu!.parentElement).toBe(document.body)
    expect(menu!.style.left).toBe('132px')
    expect(menu!.style.top).toBe('72px')
    expect(menu!.style.visibility).toBe('visible')
    expect(Number.parseFloat(menu!.style.left) + 180).toBeLessThanOrEqual(320 - 8)
    expect(Number.parseFloat(menu!.style.top) + 160).toBeLessThanOrEqual(240 - 8)
    expect(menu!.textContent).toContain('当前 AP 离线')
    const buttons = [...menu!.querySelectorAll<HTMLButtonElement>('button')]
    const disabled = buttons.find((button) => button.textContent?.includes('不可用动作'))!
    expect(disabled.disabled).toBe(true)
    buttons.find((button) => button.textContent?.includes('打开'))!.click()
    await flushPromises()
    expect(action).toHaveBeenCalledWith(expect.objectContaining({ row, columnKey: 'name', cellValue: 'AP01' }))
    expect(document.body.querySelector('[role="menu"]')).toBeNull()
    expect(wrapper.emitted('selection-change')).toBeUndefined()
    wrapper.unmount()
  })

  it('retargets another row and closes on outside pointer, Escape, resize, table scroll and data refresh', async () => {
    const action = vi.fn()
    const first = { name: 'AP01' }
    const second = { name: 'AP02' }
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const width = this.classList.contains('nc-data-table__context-menu') ? 120 : 0
      const height = this.classList.contains('nc-data-table__context-menu') ? 80 : 0
      return {
        x: 0,
        y: 0,
        top: 0,
        right: width,
        bottom: height,
        left: 0,
        width,
        height,
        toJSON: () => undefined,
      }
    })
    const wrapper = mount(NcDataTable, {
      attachTo: document.body,
      props: {
        tableId: 'context-menu-lifecycle',
        routeKey: '/devices',
        showColumnSettings: false,
        data: [first, second],
        columns: [{ key: 'name', label: '名称', valueType: 'name' }],
        contextMenuItems: [{ key: 'open', label: '打开', action }],
      },
      global,
    })
    const table = wrapper.getComponent(ElTable)
    const open = async (row: typeof first, x = 100, y = 100) => {
      table.vm.$emit(
        'row-contextmenu',
        row,
        { property: 'name', columnKey: 'name' },
        new MouseEvent('contextmenu', { clientX: x, clientY: y }),
      )
      await flushPromises()
      return document.body.querySelector<HTMLElement>('[role="menu"]')!
    }

    await open(first)
    const retargeted = await open(second, 180, 140)
    expect(retargeted.style.left).toBe('180px')
    retargeted.querySelector<HTMLButtonElement>('button')!.click()
    await flushPromises()
    expect(action).toHaveBeenLastCalledWith(expect.objectContaining({ row: second, rowIndex: 1 }))

    await open(first)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()

    await open(first)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()

    await open(first)
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()

    const menu = await open(first)
    menu.dispatchEvent(new Event('scroll'))
    await flushPromises()
    expect(document.body.querySelector('[role="menu"]')).toBe(menu)
    wrapper.get('.nc-data-table__scroll').element.dispatchEvent(new Event('scroll'))
    await flushPromises()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()

    await open(first)
    await wrapper.setProps({ data: [{ name: 'AP03' }] })
    await flushPromises()
    expect(document.body.querySelector('[role="menu"]')).toBeNull()
    wrapper.unmount()
  })

  it('removes global context-menu listeners when unmounted', () => {
    const addWindow = vi.spyOn(window, 'addEventListener')
    const removeWindow = vi.spyOn(window, 'removeEventListener')
    const addDocument = vi.spyOn(document, 'addEventListener')
    const removeDocument = vi.spyOn(document, 'removeEventListener')
    const wrapper = mount(NcDataTable, {
      props: {
        tableId: 'context-menu-cleanup',
        routeKey: '/devices',
        showColumnSettings: false,
        data: [{ name: 'AP01' }],
        columns: [{ key: 'name', label: '名称', valueType: 'name' }],
        contextMenuItems: [{ key: 'open', label: '打开', action: vi.fn() }],
      },
      global,
    })
    const scrollRegistration = addWindow.mock.calls.find(([type]) => type === 'scroll')
    const resizeRegistration = addWindow.mock.calls.find(([type]) => type === 'resize')
    const pointerRegistration = addDocument.mock.calls.find(([type]) => type === 'pointerdown')
    const keyboardRegistration = addDocument.mock.calls.find(([type]) => type === 'keydown')
    expect(scrollRegistration).toBeTruthy()
    expect(resizeRegistration).toBeTruthy()
    expect(pointerRegistration).toBeTruthy()
    expect(keyboardRegistration).toBeTruthy()

    wrapper.unmount()

    expect(removeWindow).toHaveBeenCalledWith(...scrollRegistration!)
    expect(removeWindow).toHaveBeenCalledWith(...resizeRegistration!)
    expect(removeDocument).toHaveBeenCalledWith(...pointerRegistration!)
    expect(removeDocument).toHaveBeenCalledWith(...keyboardRegistration!)
  })
})
