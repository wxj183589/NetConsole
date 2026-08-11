import { t } from '../../i18n/runtime'

export type NcColumnWidthMode = 'auto' | 'fixed' | 'content' | 'header'
export type NcColumnStretchMode = 'none' | 'normal' | 'priority' | 'fill'
export type NcTableEmptySpaceStrategy = 'stretch' | 'center' | 'fill-last'

export type NcColumnValueType =
  | 'selection'
  | 'index'
  | 'text'
  | 'name'
  | 'status'
  | 'ip'
  | 'mac'
  | 'port'
  | 'number'
  | 'rate'
  | 'percentage'
  | 'datetime'
  | 'duration'
  | 'mileage'
  | 'description'
  | 'error'
  | 'actions'

export type NcTableAlignment = 'left' | 'center' | 'right'
export type NcElementColumnType = 'selection' | 'index' | 'expand'

export interface NcTableColumn<Row extends object = Record<string, unknown>> {
  key: string
  label: string
  prop?: keyof Row & string | string
  type?: NcElementColumnType
  valueType?: NcColumnValueType
  align?: NcTableAlignment
  headerAlign?: NcTableAlignment
  alignmentReason?: 'long-text' | 'code' | 'path' | 'description' | string
  widthMode?: NcColumnWidthMode
  width?: number
  minWidth?: number
  maxWidth?: number
  stretch?: NcColumnStretchMode
  stretchWeight?: number
  sortable?: boolean | 'custom'
  filterable?: boolean
  fixed?: 'left' | 'right' | boolean
  visible?: boolean
  hideable?: boolean
  showOverflowTooltip?: boolean
  headerIconCount?: number
  cellIconCount?: number
  cellKind?: 'plain' | 'tag' | 'actions'
  actionLabels?: readonly string[]
  displayValue?: (row: Row, index: number) => unknown
  measureValue?: (row: Row, index: number) => unknown
  columnAttrs?: Record<string, unknown>
}

export interface ResolvedNcTableColumn<Row extends object = Record<string, unknown>>
  extends NcTableColumn<Row> {
  prop: string
  valueType: NcColumnValueType
  align: NcTableAlignment
  headerAlign: NcTableAlignment
  widthMode: NcColumnWidthMode
  stretch: NcColumnStretchMode
  stretchWeight: number
  visible: boolean
  hideable: boolean
  showOverflowTooltip: boolean
}

export function normalizeNcTableColumn<Row extends object>(
  column: NcTableColumn<Row>,
): ResolvedNcTableColumn<Row> {
  const valueType = column.valueType
    ?? (column.type === 'selection' ? 'selection' : column.type === 'index' ? 'index' : 'text')
  const align = column.align ?? (['description', 'error'].includes(valueType) ? 'left' : 'center')
  if (align === 'left' && !column.alignmentReason && !['description', 'error'].includes(valueType)) {
    throw new Error(`表格列 ${column.key} 左对齐时必须声明 alignmentReason`)
  }
  const stretch = column.stretch ?? defaultStretchMode(valueType)
  const defaultWeight = stretch === 'priority' ? 3 : stretch === 'none' ? 0 : 1
  return {
    ...column,
    prop: column.prop ?? column.key,
    valueType,
    align,
    headerAlign: column.headerAlign ?? 'center',
    widthMode: column.widthMode ?? (column.width == null ? 'auto' : 'fixed'),
    stretch,
    stretchWeight: stretch === 'none' ? 0 : Math.max(0.1, column.stretchWeight ?? defaultWeight),
    visible: column.visible ?? true,
    fixed: column.fixed === true ? 'left' : column.fixed ?? (valueType === 'actions' ? 'right' : undefined),
    hideable: column.hideable ?? (!column.type && valueType !== 'actions'),
    showOverflowTooltip: column.showOverflowTooltip ?? !column.type,
  }
}

function defaultStretchMode(valueType: NcColumnValueType): NcColumnStretchMode {
  if (['name', 'description', 'error'].includes(valueType)) return 'priority'
  if (['text', 'ip'].includes(valueType)) return 'normal'
  return 'none'
}

export function displayTableValue(value: unknown): string {
  if (value == null || value === '' || (typeof value === 'number' && Number.isNaN(value))) return '—'
  if (typeof value === 'boolean') return value ? t('common.yes', '是') : t('common.no', '否')
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  return String(value)
}

export function readTableCellValue<Row extends object>(
  row: Row,
  column: ResolvedNcTableColumn<Row>,
  index: number,
): unknown {
  if (column.displayValue) return column.displayValue(row, index)
  const path = column.prop.split('.')
  let value: unknown = row
  for (const segment of path) {
    if (value == null || typeof value !== 'object') return undefined
    value = (value as Record<string, unknown>)[segment]
  }
  return value
}

const CONTROLLED_COLUMN_ATTRIBUTES = new Set([
  'align',
  'columnKey',
  'fixed',
  'headerAlign',
  'label',
  'minWidth',
  'prop',
  'showOverflowTooltip',
  'sortable',
  'type',
  'width',
])

export function safeNcTableColumnAttrs(attrs: Record<string, unknown> | undefined): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(attrs ?? {}).filter(([key]) => !CONTROLLED_COLUMN_ATTRIBUTES.has(key)),
  )
}
