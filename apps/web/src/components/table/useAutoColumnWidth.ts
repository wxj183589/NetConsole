import { isRef, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

import { getColumnWidthPreset } from './columnPresets'
import {
  displayTableValue,
  normalizeNcTableColumn,
  readTableCellValue,
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
    const effectiveMin = Math.max(headerRequired, preset.minWidth, configuredMin)
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

export interface UseAutoColumnWidthOptions<Row extends object> {
  columns: Ref<readonly NcTableColumn<Row>[]>
  rows: Ref<readonly Row[]>
  manualWidths: Ref<Record<string, number>>
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
  const widths = ref<Record<string, number>>({})
  let timer: ReturnType<typeof setTimeout> | undefined

  const recalculate = (resetHistory = false): void => {
    if (timer) clearTimeout(timer)
    if (resetHistory) widths.value = {}
    widths.value = calculateTableColumnWidths({
      columns: options.columns.value,
      rows: options.rows.value,
      manualWidths: options.manualWidths.value,
      previousWidths: resetHistory ? {} : widths.value,
      bodyFont: isRef(options.bodyFont) ? options.bodyFont.value : options.bodyFont,
      headerFont: isRef(options.headerFont) ? options.headerFont.value : options.headerFont,
      measure: options.measure,
      sampleLimit: options.sampleLimit,
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
    ...(options.revision ? [options.revision] : []),
    ...(isRef(options.bodyFont) ? [options.bodyFont] : []),
    ...(isRef(options.headerFont) ? [options.headerFont] : []),
  ]
  watch(sources, schedule, {
    deep: true,
  })
  onMounted(() => recalculate())
  onBeforeUnmount(() => { if (timer) clearTimeout(timer) })

  return { widths, recalculate, schedule }
}
