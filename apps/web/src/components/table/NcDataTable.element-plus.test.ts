// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import NcColumnSettings from './NcColumnSettings.vue'
import NcDataTable from './NcDataTable.vue'

class ResizeObserverStub {
  observe(): void {}
  disconnect(): void {}
}

function headerLabels(wrapper: VueWrapper): string[] {
  return wrapper.findAll('.el-table__header-wrapper th .cell').map((cell) => cell.text()).filter(Boolean)
}

function bodyValues(wrapper: VueWrapper): string[] {
  return wrapper.findAll('.el-table__body-wrapper tbody tr:first-child td .cell').map((cell) => cell.text()).filter(Boolean)
}

async function renderTable(): Promise<VueWrapper> {
  const wrapper = mount(NcDataTable, {
    attachTo: document.body,
    props: {
      tableId: 'element-plus-preference-regression',
      routeKey: '/tests/table-preferences',
      language: 'zh-CN',
      data: [{ a: 'A1', b: 'B1', c: 'C1' }],
      columns: [
        { key: 'a', label: 'A列', prop: 'a', valueType: 'text' },
        { key: 'b', label: 'B列', prop: 'b', valueType: 'text' },
        { key: 'c', label: 'C列', prop: 'c', valueType: 'text' },
      ],
    },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.lang = 'zh-CN'
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, value: ResizeObserverStub })
})

afterEach(() => {
  document.body.innerHTML = ''
  localStorage.clear()
})

describe('NcDataTable with Element Plus', () => {
  it('applies visibility, order and pinning to real headers and cells and restores them after remount', async () => {
    let wrapper = await renderTable()
    const settings = wrapper.getComponent(NcColumnSettings)

    expect(headerLabels(wrapper)).toEqual(['A列', 'B列', 'C列'])
    expect(bodyValues(wrapper)).toEqual(['A1', 'B1', 'C1'])

    settings.vm.$emit('toggle', 'b', false)
    await flushPromises()
    expect(headerLabels(wrapper)).toEqual(['A列', 'C列'])
    expect(bodyValues(wrapper)).toEqual(['A1', 'C1'])

    settings.vm.$emit('toggle', 'b', true)
    await flushPromises()
    settings.vm.$emit('move', 'c', -1)
    await flushPromises()
    expect(headerLabels(wrapper)).toEqual(['A列', 'C列', 'B列'])
    expect(bodyValues(wrapper)).toEqual(['A1', 'C1', 'B1'])

    settings.vm.$emit('pin', 'c')
    await flushPromises()
    const pinnedHeader = wrapper.findAll('.el-table__header-wrapper th').find((cell) => cell.text().includes('C列'))
    expect(pinnedHeader?.classes()).toContain('el-table-fixed-column--left')

    wrapper.unmount()
    wrapper = await renderTable()
    expect(headerLabels(wrapper)).toEqual(['C列', 'A列', 'B列'])
    expect(wrapper.findAll('.el-table__header-wrapper th').find((cell) => cell.text().includes('C列'))?.classes())
      .toContain('el-table-fixed-column--left')

    wrapper.getComponent(NcColumnSettings).vm.$emit('reset')
    await flushPromises()
    expect(headerLabels(wrapper)).toEqual(['A列', 'B列', 'C列'])
    wrapper.unmount()
  })
})
