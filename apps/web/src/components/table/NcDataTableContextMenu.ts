export interface NcDataTableContext<Row extends object> {
  row: Row
  rowIndex: number
  columnKey: string
  cellValue: unknown
}

export interface NcDataTableContextMenuItem<Row extends object> {
  key: string
  label: string
  action: (context: NcDataTableContext<Row>) => void | Promise<void>
  disabled?: boolean | ((context: NcDataTableContext<Row>) => boolean)
  disabledReason?: string | ((context: NcDataTableContext<Row>) => string)
  danger?: boolean
  separatorBefore?: boolean
}

export const NC_DATA_TABLE_CONTEXT_MENU_MARGIN = 8

export interface NcDataTableContextMenuPositionInput {
  anchorX: number
  anchorY: number
  menuWidth: number
  menuHeight: number
  viewportWidth: number
  viewportHeight: number
  margin?: number
}

export interface NcDataTableContextMenuPosition {
  left: number
  top: number
}

function positionAxis(anchor: number, menuSize: number, viewportSize: number, margin: number): number {
  const safeViewportSize = Math.max(0, viewportSize)
  const safeMargin = Math.max(0, Math.min(margin, safeViewportSize / 2))
  const availableSize = Math.max(0, safeViewportSize - safeMargin * 2)
  const effectiveMenuSize = Math.min(Math.max(0, menuSize), availableSize)
  const maximum = Math.max(safeMargin, safeViewportSize - effectiveMenuSize - safeMargin)
  const preferred = anchor + effectiveMenuSize + safeMargin > safeViewportSize
    ? anchor - effectiveMenuSize
    : anchor
  return Math.max(safeMargin, Math.min(preferred, maximum))
}

export function calculateNcDataTableContextMenuPosition({
  anchorX,
  anchorY,
  menuWidth,
  menuHeight,
  viewportWidth,
  viewportHeight,
  margin = NC_DATA_TABLE_CONTEXT_MENU_MARGIN,
}: NcDataTableContextMenuPositionInput): NcDataTableContextMenuPosition {
  return {
    left: positionAxis(anchorX, menuWidth, viewportWidth, margin),
    top: positionAxis(anchorY, menuHeight, viewportHeight, margin),
  }
}
