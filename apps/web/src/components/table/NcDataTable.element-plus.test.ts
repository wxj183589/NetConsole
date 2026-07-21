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
  return wrapper.findAll('.el-table__header-wrapper th:not(.nc-data-table__column--hidden) .cell').map((cell) => cell.text()).filter(Boolean)
}

function bodyValues(wrapper: VueWrapper): string[] {
  return wrapper.findAll('.el-table__body-wrapper tbody tr:first-child td:not(.nc-data-table__column--hidden) .cell').map((cell) => cell.text()).filter(Boolean)
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

async function settleColumnLayout(): Promise<void> {
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 240))
  await flushPromises()
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 20))
  await flushPromises()
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
    const tableElement = wrapper.get('.el-table').element

    expect(headerLabels(wrapper)).toEqual(['A列', 'B列', 'C列'])
    expect(bodyValues(wrapper)).toEqual(['A1', 'B1', 'C1'])

    settings.vm.$emit('toggle', 'b', false)
    await settleColumnLayout()
    expect(headerLabels(wrapper)).toEqual(['A列', 'C列'])
    expect(bodyValues(wrapper)).toEqual(['A1', 'C1'])
    expect(wrapper.get('.el-table').element).toBe(tableElement)
    expect(bodyValues(wrapper)).toEqual(['A1', 'C1'])

    settings.vm.$emit('toggle', 'b', true)
    await settleColumnLayout()
    expect(headerLabels(wrapper)).toEqual(['A列', 'B列', 'C列'])
    settings.vm.$emit('move', 'c', -1)
    await settleColumnLayout()
    expect(headerLabels(wrapper)).toEqual(['A列', 'C列', 'B列'])
    expect(bodyValues(wrapper)).toEqual(['A1', 'C1', 'B1'])

    settings.vm.$emit('pin', 'c')
    await settleColumnLayout()
    const pinnedHeader = wrapper.findAll('.el-table__header-wrapper th').find((cell) => cell.text().includes('C列'))
    expect(pinnedHeader?.classes()).toContain('el-table-fixed-column--left')

    wrapper.unmount()
    wrapper = await renderTable()
    expect(headerLabels(wrapper)).toEqual(['C列', 'A列', 'B列'])
    expect(wrapper.findAll('.el-table__header-wrapper th').find((cell) => cell.text().includes('C列'))?.classes())
      .toContain('el-table-fixed-column--left')

    wrapper.getComponent(NcColumnSettings).vm.$emit('reset')
    await settleColumnLayout()
    expect(headerLabels(wrapper)).toEqual(['A列', 'B列', 'C列'])
    wrapper.unmount()
  })

  it('keeps a wide 40-column table on the single Element Plus scroll plane', async () => {
    const columns = Array.from({ length: 40 }, (_, index) => ({
      key: `column_${index}`,
      label: `测试字段 ${index}`,
      prop: `column_${index}`,
      minWidth: 130,
    }))
    const data = Array.from({ length: 20 }, (_, rowIndex) => Object.fromEntries(
      columns.map((column, columnIndex) => [column.key, `R${rowIndex}C${columnIndex}`]),
    ))
    const wrapper = mount(NcDataTable, {
      attachTo: document.body,
      props: {
        tableId: 'element-plus-scroll-regression',
        routeKey: '/tests/table-scroll',
        language: 'zh-CN',
        data,
        columns,
        height: 420,
      },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const outer = wrapper.get('.nc-data-table__scroll').element as HTMLElement
    expect(outer.querySelectorAll(':scope > .el-table')).toHaveLength(1)
    expect(wrapper.findAll('.nc-data-table__scroll')).toHaveLength(1)
    expect(wrapper.get('.el-table').attributes('style')).toContain('width: 100%')
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(20)

    const bodyWrapper = wrapper.get('.el-table__body-wrapper').element as HTMLElement
    const internal = bodyWrapper.querySelector('.el-scrollbar__wrap') as HTMLElement | null
      || bodyWrapper
    Object.defineProperties(internal, {
      clientHeight: { configurable: true, value: 360 },
      scrollHeight: { configurable: true, value: 40_000 },
      clientWidth: { configurable: true, value: 900 },
      scrollWidth: { configurable: true, value: 5_200 },
    })
    internal.scrollTop = 20_000
    internal.scrollLeft = 2_400
    internal.dispatchEvent(new Event('scroll'))

    expect(internal.scrollTop).toBe(20_000)
    expect(internal.scrollLeft).toBe(2_400)
    expect(wrapper.get('.el-table__header-wrapper').element.closest('.el-table__body-wrapper')).toBeNull()
    expect(wrapper.get('.el-table__header-wrapper').isVisible()).toBe(true)
    wrapper.unmount()
  }, 15_000)
})
