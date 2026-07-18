import { describe, expect, it } from 'vitest'

import type { NcTableColumn } from './NcTableColumn'
import {
  calculateHeaderRequiredWidth,
  calculateTableColumnWidths,
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
})
