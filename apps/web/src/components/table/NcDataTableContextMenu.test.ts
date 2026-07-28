import { describe, expect, it } from 'vitest'

import {
  calculateNcDataTableContextMenuPosition,
  NC_DATA_TABLE_CONTEXT_MENU_MARGIN,
} from './NcDataTableContextMenu'

describe('calculateNcDataTableContextMenuPosition', () => {
  it.each([
    {
      name: '视口中间优先向右下展开',
      input: { anchorX: 200, anchorY: 160, menuWidth: 180, menuHeight: 220, viewportWidth: 800, viewportHeight: 600 },
      expected: { left: 200, top: 160 },
    },
    {
      name: '靠近右侧时向左展开',
      input: { anchorX: 790, anchorY: 160, menuWidth: 180, menuHeight: 220, viewportWidth: 800, viewportHeight: 600 },
      expected: { left: 610, top: 160 },
    },
    {
      name: '靠近底部时向上展开',
      input: { anchorX: 200, anchorY: 590, menuWidth: 180, menuHeight: 220, viewportWidth: 800, viewportHeight: 600 },
      expected: { left: 200, top: 370 },
    },
    {
      name: '右下角同时向左和向上展开',
      input: { anchorX: 790, anchorY: 590, menuWidth: 180, menuHeight: 220, viewportWidth: 800, viewportHeight: 600 },
      expected: { left: 610, top: 370 },
    },
    {
      name: '左上角保留安全边距',
      input: { anchorX: 1, anchorY: 2, menuWidth: 180, menuHeight: 220, viewportWidth: 800, viewportHeight: 600 },
      expected: { left: 8, top: 8 },
    },
    {
      name: '超大菜单由安全边距起始',
      input: { anchorX: 400, anchorY: 300, menuWidth: 1200, menuHeight: 900, viewportWidth: 800, viewportHeight: 600 },
      expected: { left: 8, top: 8 },
    },
  ])('$name', ({ input, expected }) => {
    expect(calculateNcDataTableContextMenuPosition(input)).toEqual(expected)
  })

  it('对 CSS 像素中的小数坐标和缩放后尺寸保持边界约束', () => {
    const viewportWidth = 1024.5
    const viewportHeight = 768.25
    const menuWidth = 211.75
    const menuHeight = 355.5
    const position = calculateNcDataTableContextMenuPosition({
      anchorX: 1018.25,
      anchorY: 761.75,
      menuWidth,
      menuHeight,
      viewportWidth,
      viewportHeight,
    })

    expect(position.left).toBeCloseTo(804.75)
    expect(position.top).toBeCloseTo(404.75)
    expect(position.left).toBeGreaterThanOrEqual(NC_DATA_TABLE_CONTEXT_MENU_MARGIN)
    expect(position.top).toBeGreaterThanOrEqual(NC_DATA_TABLE_CONTEXT_MENU_MARGIN)
    expect(position.left + menuWidth).toBeLessThanOrEqual(viewportWidth - NC_DATA_TABLE_CONTEXT_MENU_MARGIN)
    expect(position.top + menuHeight).toBeLessThanOrEqual(viewportHeight - NC_DATA_TABLE_CONTEXT_MENU_MARGIN)
  })
})
