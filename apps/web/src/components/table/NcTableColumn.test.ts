import { describe, expect, it } from 'vitest'

import { setAppLocale } from '../../i18n/runtime'
import { displayTableValue, normalizeNcTableColumn, safeNcTableColumnAttrs } from './NcTableColumn'

describe('NcTableColumn', () => {
  it('uses centered headers and cells by default', () => {
    const column = normalizeNcTableColumn({ key: 'name', label: '设备名称', valueType: 'name' })
    expect(column.align).toBe('center')
    expect(column.headerAlign).toBe('center')
    expect(column.showOverflowTooltip).toBe(true)
  })

  it('keeps action columns visible and fixed on the right by default', () => {
    const column = normalizeNcTableColumn({ key: 'actions', label: '操作', valueType: 'actions' })
    expect(column.fixed).toBe('right')
    expect(column.hideable).toBe(false)
  })

  it('requires a reason for non-standard left alignment', () => {
    expect(() => normalizeNcTableColumn({ key: 'name', label: '名称', align: 'left' })).toThrow('alignmentReason')
    expect(normalizeNcTableColumn({
      key: 'path',
      label: '路径',
      align: 'left',
      alignmentReason: 'path',
    }).align).toBe('left')
  })

  it('renders missing values as an em dash without hiding factual zero', () => {
    expect(displayTableValue(undefined)).toBe('—')
    expect(displayTableValue(Number.NaN)).toBe('—')
    expect(displayTableValue([])).toBe('—')
    expect(displayTableValue(0)).toBe('0')
    expect(displayTableValue(false)).toBe('否')
    setAppLocale('en_US')
    expect(displayTableValue(false)).toBe('No')
    setAppLocale('zh_CN')
  })

  it('does not let generic Element Plus attrs bypass the shared width contract', () => {
    expect(safeNcTableColumnAttrs({ width: 20, minWidth: 10, filters: [{ text: '正常', value: 'ok' }] }))
      .toEqual({ filters: [{ text: '正常', value: 'ok' }] })
  })
})
