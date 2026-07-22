import { isRef, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

import { getColumnWidthPreset } from './columnPresets'
import {
  displayTableValue,
  normalizeNcTableColumn,
  readTableCellValue,
  type NcTableEmptySpaceStrategy,
  type NcTableColumn,
  type ResolvedNcTableColumn,
} from './NcTableColumn'
import { measureTextWidth } from './textMeasurement'

export interface ColumnWidthContext {
  bodyFont?: string
  headerFont?: string
  measure?: (text: unknown, font: string) => number
}

export interface CalculateColumnWidthsOptions<Row extends object> extends ColumnWidthContext {
  columns: readonly NcTableColumn<Row>[]
  rows: readonly Row[]
  manualWidths?: Readonly<Record<string, number>>
  previousWidths?: Readonly<Record<string, number>>
  sampleLimit?: number
}

export interface DistributeColumnWidthsOptions<Row extends object> {
  columns: readonly NcTableColumn<Row>[]
  baseWidths: Readonly<Record<string, number>>
  availableWidth: number
  manualWidths?: Readonly<Record<string, number>>
  emptySpaceStrategy?: NcTableEmptySpaceStrategy
}

const HEADER_HORIZONTAL_PADDING = 32
const CELL_HORIZONTAL_PADDING = 28
const HEADER_ICON_WIDTH = 20
const CELL_ICON_WIDTH = 18
const TAG_CHROME_WIDTH = 26
const ACTION_BUTTON_CHROME_WIDTH = 32
const SAFETY_MARGIN = 6

export function stableTableSample<Row>(rows: readonly Row[], limit = 200): readonly Row[] {
  if (rows.length <= limit) return rows
  const headCount = Math.ceil(limit / 2)
  return [...rows.slice(0, headCount), ...rows.slice(rows.length - (limit - headCount))]
}

export function calculateHeaderRequiredWidth<Row extends object>(
  rawColumn: NcTableColumn<Row>,
  context: ColumnWidthContext = {},
): number {
  const column = normalizeNcTableColumn(rawColumn)
  const measure = context.measure ?? measureTextWidth
  const font = context.headerFont ?? '600 14px "Microsoft YaHei UI", sans-serif'
  const hasFilter = column.filterable || Array.isArray(column.columnAttrs?.filters)
  const iconCount = (column.sortable ? 1 : 0) + (hasFilter ? 1 : 0) + (column.headerIconCount ?? 0)
  return Math.ceil(measure(column.label, font) + HEADER_HORIZONTAL_PADDING + iconCount * HEADER_ICON_WIDTH + SAFETY_MARGIN)
}

function calculateContentRequiredWidth<Row extends object>(
  column: ResolvedNcTableColumn<Row>,
  rows: readonly Row[],
  context: ColumnWidthContext,
): number {
  if (column.type === 'selection') return getColumnWidthPreset('selection').minWidth
  const measure = context.measure ?? measureTextWidth
  const font = context.bodyFont ?? '400 14px "Microsoft YaHei UI", sans-serif'
  let contentWidth = 0
  rows.forEach((row, index) => {
    const raw = column.measureValue ? column.measureValue(row, index) : readTableCellValue(row, column, index)
    contentWidth = Math.max(contentWidth, measure(displayTableValue(raw), font))
  })
  if (column.cellKind === 'actions' && column.actionLabels?.length) {
    contentWidth = column.actionLabels.reduce(
      (total, label) => total + measure(label, font) + ACTION_BUTTON_CHROME_WIDTH,
      0,
    )
  }
  const chrome = column.cellKind === 'tag' ? TAG_CHROME_WIDTH : 0
  return Math.ceil(contentWidth + CELL_HORIZONTAL_PADDING + chrome + (column.cellIconCount ?? 0) * CELL_ICON_WIDTH + SAFETY_MARGIN)
}

export function calculateTableColumnWidths<Row extends object>(
  options: CalculateColumnWidthsOptions<Row>,
): Record<string, number> {
  const rows = stableTableSample(options.rows, options.sampleLimit)
  const widths: Record<string, number> = {}
  for (const rawColumn of options.columns) {
    const column = normalizeNcTableColumn(rawColumn)
    const preset = getColumnWidthPreset(column.valueType)
    const headerRequired = calculateHeaderRequiredWidth(column, options)
    const contentRequired = calculateContentRequiredWidth(column, rows, options)
    const configuredMin = column.minWidth ?? 0
    const presetMin = column.widthMode === 'fixed' ? 0 : preset.minWidth
    const effectiveMin = Math.max(headerRequired, presetMin, configuredMin)
    const effectiveMax = Math.max(effectiveMin, column.maxWidth ?? preset.maxWidth)
    const automatic = column.widthMode === 'header'
      ? headerRequired
      : column.widthMode === 'content'
        ? contentRequired
        : Math.max(headerRequired, contentRequired)
    const requested = options.manualWidths?.[column.key]
      ?? (column.widthMode === 'fixed' ? column.width : undefined)
      ?? automatic
    const historical = options.previousWidths?.[column.key] ?? 0
    const shouldKeepHistorical = options.manualWidths?.[column.key] == null && column.widthMode !== 'fixed'
    widths[column.key] = Math.min(
      effectiveMax,
      Math.max(effectiveMin, requested ?? effectiveMin, shouldKeepHistorical ? historical : 0),
    )
  }
  return widths
}

function effectiveMaximum<Row extends object>(column: ResolvedNcTableColumn<Row>, width: number): number {
  const preset = getColumnWidthPreset(column.valueType)
  return Math.max(width, column.maxWidth ?? preset.maxWidth)
}

function distributeWeighted<Row extends object>(
  columns: readonly ResolvedNcTableColumn<Row>[],
  widths: Record<string, number>,
  maximums: Readonly<Record<string, number>>,
  remainingWidth: number,
): number {
  let remaining = remainingWidth
  while (remaining > 0) {
    const active = columns.filter((column) => widths[column.key] < maximums[column.key])
    if (!active.length) break
    const totalWeight = active.reduce((total, column) => total + column.stretchWeight, 0)
    let distributed = 0
    for (const column of active) {
      const room = maximums[column.key] - widths[column.key]
      const share = Math.max(1, Math.floor(remaining * column.stretchWeight / totalWeight))
      const amount = Math.min(room, share, remaining - distributed)
      widths[column.key] += amount
      distributed += amount
      if (distributed >= remaining) break
    }
    if (distributed <= 0) break
    remaining -= distributed
  }
  return remaining
}

export function distributeColumnWidths<Row extends object>(
  options: DistributeColumnWidthsOptions<Row>,
): Record<string, number> {
  const columns = options.columns.map(normalizeNcTableColumn).filter((column) => column.visible)
  const widths = Object.fromEntries(columns.map((column) => [column.key, options.baseWidths[column.key] ?? 0]))
  const availableWidth = Math.max(0, Math.floor(options.availableWidth))
  const total = Object.values(widths).reduce((sum, width) => sum + width, 0)
  if (!availableWidth || total >= availableWidth || options.emptySpaceStrategy === 'center') return widths

  const maximums = Object.fromEntries(columns.map((column) => [
    column.key,
    effectiveMaximum(column, widths[column.key]),
  ]))
  const canStretch = (column: ResolvedNcTableColumn<Row>): boolean => (
    column.stretch !== 'none'
    && column.widthMode !== 'fixed'
    && column.fixed !== 'left'
    && column.fixed !== 'right'
    && options.manualWidths?.[column.key] == null
  )
  const weighted = columns.filter((column) => canStretch(column) && column.stretch !== 'fill')
  const fill = columns.filter((column) => canStretch(column) && column.stretch === 'fill')
  let remaining = availableWidth - total
  if (options.emptySpaceStrategy === 'fill-last') {
    const fallback = [...columns].reverse().find(canStretch)
    if (fallback) distributeWeighted([fallback], widths, maximums, remaining)
    return widths
  }
  remaining = distributeWeighted(weighted, widths, maximums, remaining)
  distributeWeighted(fill, widths, maximums, remaining)
  return widths
}

export interface UseAutoColumnWidthOptions<Row extends object> {
  columns: Ref<readonly NcTableColumn<Row>[]>
  rows: Ref<readonly Row[]>
  manualWidths: Ref<Record<string, number>>
  availableWidth?: Ref<number>
  emptySpaceStrategy?: NcTableEmptySpaceStrategy
  revision?: Ref<number>
  debounceMs?: number
  sampleLimit?: number
  bodyFont?: string | Ref<string>
  headerFont?: string | Ref<string>
  measure?: (text: unknown, font: string) => number
}

export function useAutoColumnWidth<Row extends object>(
  options: UseAutoColumnWidthOptions<Row>,
) {
  const baseWidths = ref<Record<string, number>>({})
  const widths = ref<Record<string, number>>({})
  let timer: ReturnType<typeof setTimeout> | undefined

  const recalculate = (resetHistory = false): void => {
    if (timer) clearTimeout(timer)
    if (resetHistory) baseWidths.value = {}
    baseWidths.value = calculateTableColumnWidths({
      columns: options.columns.value,
      rows: options.rows.value,
      manualWidths: options.manualWidths.value,
      previousWidths: resetHistory ? {} : baseWidths.value,
      bodyFont: isRef(options.bodyFont) ? options.bodyFont.value : options.bodyFont,
      headerFont: isRef(options.headerFont) ? options.headerFont.value : options.headerFont,
      measure: options.measure,
      sampleLimit: options.sampleLimit,
    })
    widths.value = distributeColumnWidths({
      columns: options.columns.value,
      baseWidths: baseWidths.value,
      availableWidth: options.availableWidth?.value ?? 0,
      manualWidths: options.manualWidths.value,
      emptySpaceStrategy: options.emptySpaceStrategy,
    })
  }

  const schedule = (): void => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => recalculate(), options.debounceMs ?? 350)
  }

  const sources = [
    options.columns,
    options.rows,
    options.manualWidths,
    ...(options.availableWidth ? [options.availableWidth] : []),
    ...(options.revision ? [options.revision] : []),
    ...(isRef(options.bodyFont) ? [options.bodyFont] : []),
    ...(isRef(options.headerFont) ? [options.headerFont] : []),
  ]
  watch(sources, schedule, {
    deep: true,
  })
  onMounted(() => recalculate())
  onBeforeUnmount(() => { if (timer) clearTimeout(timer) })

  return { widths, baseWidths, recalculate, schedule }
}
