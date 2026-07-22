import { describe, expect, it } from 'vitest'

import type { NcTableColumn } from './NcTableColumn'
import {
  calculateHeaderRequiredWidth,
  calculateTableColumnWidths,
  distributeColumnWidths,
  stableTableSample,
} from './useAutoColumnWidth'

interface Row extends Record<string, unknown> {
  name: string
  status?: string
}

const measure = (text: unknown): number => Array.from(String(text ?? '')).reduce(
  (width, char) => width + (/[^\x00-\xff]/.test(char) ? 14 : 8),
  0,
)

describe('automatic table column widths', () => {
  it('never makes a column narrower than its full header', () => {
    const column: NcTableColumn<Row> = {
      key: 'name',
      label: '完整中文设备名称',
      valueType: 'text',
      maxWidth: 80,
    }
    const header = calculateHeaderRequiredWidth(column, { measure })
    const widths = calculateTableColumnWidths({ columns: [column], rows: [{ name: 'A' }], measure })
    expect(widths.name).toBeGreaterThanOrEqual(header)
  })

  it('accounts for sort, filter and status tag chrome', () => {
    const plain: NcTableColumn<Row> = { key: 'status', label: '状态', valueType: 'status' }
    const decorated: NcTableColumn<Row> = {
      ...plain,
      sortable: true,
      filterable: true,
      cellKind: 'tag',
    }
    expect(calculateHeaderRequiredWidth(decorated, { measure }))
      .toBe(calculateHeaderRequiredWidth(plain, { measure }) + 40)
    expect(calculateTableColumnWidths({ columns: [decorated], rows: [{ name: '', status: '认证失败' }], measure }).status)
      .toBeGreaterThanOrEqual(96)
  })

  it('uses content, configured minimum and field presets for empty and populated data', () => {
    const column: NcTableColumn<Row> = { key: 'name', label: '名称', valueType: 'name', minWidth: 180 }
    const empty = calculateTableColumnWidths({ columns: [column], rows: [], measure })
    const populated = calculateTableColumnWidths({
      columns: [column],
      rows: [{ name: '一条明显更长的设备名称' }],
      measure,
    })
    expect(empty.name).toBe(180)
    expect(populated.name).toBeGreaterThan(empty.name)
  })

  it('honors an explicit fixed width below the field preset while preserving the full header', () => {
    const column: NcTableColumn<Row> = {
      key: 'description',
      label: '描述',
      valueType: 'description',
      width: 90,
      maxWidth: 120,
    }
    const widths = calculateTableColumnWidths({
      columns: [column],
      rows: [{ name: '', description: '一段明显超过固定列宽的描述内容' }],
      measure,
    })
    const manuallyExpanded = calculateTableColumnWidths({
      columns: [column],
      rows: [],
      manualWidths: { description: 300 },
      measure,
    })
    expect(widths.description).toBe(90)
    expect(manuallyExpanded.description).toBe(120)
  })

  it('clamps manual widths to the header and keeps historical maxima across pages', () => {
    const column: NcTableColumn<Row> = { key: 'name', label: '设备名称', valueType: 'text', maxWidth: 300 }
    const header = calculateHeaderRequiredWidth(column, { measure })
    const manual = calculateTableColumnWidths({
      columns: [column], rows: [{ name: '短' }], manualWidths: { name: 20 }, measure,
    })
    const historical = calculateTableColumnWidths({
      columns: [column], rows: [{ name: '短' }], previousWidths: { name: 260 }, measure,
    })
    expect(manual.name).toBeGreaterThanOrEqual(header)
    expect(historical.name).toBe(260)
  })

  it('uses stable head and tail samples for large tables', () => {
    const rows = Array.from({ length: 1000 }, (_, index) => ({ name: String(index) }))
    const sampled = stableTableSample(rows, 200)
    expect(sampled).toHaveLength(200)
    expect(sampled[0]?.name).toBe('0')
    expect(sampled.at(-1)?.name).toBe('999')
  })

  it('measures operation labels as complete buttons without unbounded growth', () => {
    const column: NcTableColumn<Row> = {
      key: 'actions',
      label: '操作',
      valueType: 'actions',
      cellKind: 'actions',
      actionLabels: ['详情', '编辑', '删除'],
    }
    const width = calculateTableColumnWidths({ columns: [column], rows: [], measure }).actions
    expect(width).toBeGreaterThan(180)
    expect(width).toBeLessThanOrEqual(320)
  })

  it('fills a wider viewport by weighted business columns', () => {
    const columns: NcTableColumn<Row>[] = [
      { key: 'name', label: '名称', valueType: 'name', maxWidth: 300 },
      { key: 'group', label: '分组', valueType: 'text', maxWidth: 200 },
      { key: 'status', label: '状态', valueType: 'status', maxWidth: 100 },
    ]
    const widths = distributeColumnWidths({
      columns,
      baseWidths: { name: 100, group: 100, status: 100 },
      availableWidth: 500,
    })
    expect(Object.values(widths).reduce((total, width) => total + width, 0)).toBe(500)
    expect(widths.name - 100).toBeGreaterThan(widths.group - 100)
    expect(widths.status).toBe(100)
  })

  it('keeps base widths for equal or narrower viewports to enable horizontal scrolling', () => {
    const columns: NcTableColumn<Row>[] = [
      { key: 'name', label: '名称', valueType: 'name' },
      { key: 'status', label: '状态', valueType: 'status' },
    ]
    const baseWidths = { name: 180, status: 120 }
    expect(distributeColumnWidths({ columns, baseWidths, availableWidth: 300 })).toEqual(baseWidths)
    expect(distributeColumnWidths({ columns, baseWidths, availableWidth: 240 })).toEqual(baseWidths)
  })

  it('redistributes space after a priority column reaches its maximum', () => {
    const columns: NcTableColumn<Row>[] = [
      { key: 'name', label: '名称', valueType: 'name', maxWidth: 120 },
      { key: 'group', label: '分组', valueType: 'text', maxWidth: 300 },
      { key: 'status', label: '状态', valueType: 'status' },
    ]
    const widths = distributeColumnWidths({
      columns,
      baseWidths: { name: 100, group: 100, status: 100 },
      availableWidth: 500,
    })
    expect(widths.name).toBe(120)
    expect(widths.group).toBe(280)
    expect(widths.status).toBe(100)
  })

  it('uses a fill column without stretching manual, hidden or fixed columns', () => {
    const columns: NcTableColumn<Row>[] = [
      { key: 'name', label: '名称', valueType: 'name', fixed: 'left' },
      { key: 'description', label: '说明', valueType: 'description', stretch: 'fill', maxWidth: 400 },
      { key: 'status', label: '状态', valueType: 'status', visible: false },
    ]
    const widths = distributeColumnWidths({
      columns,
      baseWidths: { name: 120, description: 100, status: 100 },
      availableWidth: 400,
      manualWidths: { name: 120 },
    })
    expect(widths).toEqual({ name: 120, description: 280 })
  })

  it('leaves bounded columns unchanged when no column may stretch', () => {
    const columns: NcTableColumn<Row>[] = [
      { key: 'status', label: '状态', valueType: 'status' },
      { key: 'time', label: '时间', valueType: 'datetime' },
    ]
    expect(distributeColumnWidths({
      columns,
      baseWidths: { status: 100, time: 180 },
      availableWidth: 800,
    })).toEqual({ status: 100, time: 180 })
  })

  it('supports bounded fill-last without widening every short column', () => {
    const columns: NcTableColumn<Row>[] = [
      { key: 'name', label: '名称', valueType: 'name', maxWidth: 300 },
      { key: 'group', label: '分组', valueType: 'text', maxWidth: 180 },
    ]
    expect(distributeColumnWidths({
      columns,
      baseWidths: { name: 100, group: 100 },
      availableWidth: 500,
      emptySpaceStrategy: 'fill-last',
    })).toEqual({ name: 100, group: 180 })
  })
})
