import type {
  ConfigDiffFilter,
  SharedConfigDiffModel,
  SharedConfigDiffRow,
} from './configDiffTypes'

export interface ConfigDiffNavigationTarget {
  originalLine: number | null
  modifiedLine: number | null
}

export const MONACO_DIFF_MAX_TOTAL_CHARACTERS = 4_000_000
export const MONACO_DIFF_MAX_TOTAL_LINES = 100_000

export function filteredConfigDiffRows(
  rows: readonly SharedConfigDiffRow[],
  filter: ConfigDiffFilter,
): SharedConfigDiffRow[] {
  return filter === 'all' ? [...rows] : rows.filter((row) => row.status === filter)
}

export function configDiffNavigationTargets(
  rows: readonly SharedConfigDiffRow[],
  filter: ConfigDiffFilter = 'all',
): ConfigDiffNavigationTarget[] {
  return rows
    .filter((row) => row.status !== 'equal' && (filter === 'all' || row.status === filter))
    .map((row) => ({
      originalLine: row.originalLine,
      modifiedLine: row.modifiedLine,
    }))
}

export function nextConfigDiffChangeIndex(current: number, count: number, step: -1 | 1): number {
  return count > 0 ? (current + step + count) % count : 0
}

export function correctConfigDiffChangeIndex(current: number, count: number): number {
  if (count <= 0) return 0
  return Math.min(Math.max(current, 0), count - 1)
}

export function exceedsMonacoDiffLimit(model: SharedConfigDiffModel): boolean {
  const original = model.original.content
  const modified = model.modified.content
  if (original.length + modified.length > MONACO_DIFF_MAX_TOTAL_CHARACTERS) return true
  return countDocumentLines(original) + countDocumentLines(modified) > MONACO_DIFF_MAX_TOTAL_LINES
}

function countDocumentLines(text: string): number {
  if (!text) return 0
  let count = 1
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) === 10) count += 1
  }
  return count
}
