import type {
  ConfigDiffRow,
  ConfigDiffStatus,
  ConfigDiffSummary,
} from '../../types/configCollection'

export type ConfigDiffFilter = 'all' | 'added' | 'removed' | 'modified'

export interface ConfigDiffDocuments {
  originalText: string
  modifiedText: string
  originalLineCount: number
  modifiedLineCount: number
}

export interface ConfigDiffNavigationTarget {
  leftLine: number | null
  rightLine: number | null
}

export const MONACO_DIFF_MAX_TOTAL_CHARACTERS = 4_000_000
export const MONACO_DIFF_MAX_TOTAL_LINES = 100_000

export function parseConfigDiffRows(value: unknown): ConfigDiffRow[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const row = item as Record<string, unknown>
    const status = String(row.status || '')
    if (!['=', '+', '-', '~'].includes(status)) return []
    return [{
      left_line: typeof row.left_line === 'number' ? row.left_line : null,
      left_text: String(row.left_text || ''),
      status: status as ConfigDiffStatus,
      right_line: typeof row.right_line === 'number' ? row.right_line : null,
      right_text: String(row.right_text || ''),
    }]
  })
}

export function parseConfigDiffSummary(value: unknown): ConfigDiffSummary {
  if (!value || typeof value !== 'object') return { added: 0, removed: 0, modified: 0 }
  const summary = value as Record<string, unknown>
  return {
    added: Number(summary.added || 0),
    removed: Number(summary.removed || 0),
    modified: Number(summary.modified || 0),
  }
}

export function statusForConfigDiffFilter(value: ConfigDiffFilter): ConfigDiffStatus | null {
  if (value === 'added') return '+'
  if (value === 'removed') return '-'
  if (value === 'modified') return '~'
  return null
}

export function nextConfigDiffChangeIndex(current: number, count: number, step: -1 | 1): number {
  return count > 0 ? (current + step + count) % count : 0
}

export function buildConfigDiffDocuments(diffRows: readonly ConfigDiffRow[]): ConfigDiffDocuments {
  const originalLines: string[] = []
  const modifiedLines: string[] = []
  let originalLineCount = 0
  let modifiedLineCount = 0

  for (const row of diffRows) {
    if (row.left_line !== null && row.left_line > 0) {
      originalLineCount = Math.max(originalLineCount, row.left_line)
      originalLines[row.left_line - 1] = row.left_text
    }
    if (row.right_line !== null && row.right_line > 0) {
      modifiedLineCount = Math.max(modifiedLineCount, row.right_line)
      modifiedLines[row.right_line - 1] = row.right_text
    }
  }

  return {
    originalText: materializeDocument(originalLines, originalLineCount),
    modifiedText: materializeDocument(modifiedLines, modifiedLineCount),
    originalLineCount,
    modifiedLineCount,
  }
}

export function configDiffNavigationTargets(
  diffRows: readonly ConfigDiffRow[],
  filter: ConfigDiffFilter = 'all',
): ConfigDiffNavigationTarget[] {
  const status = statusForConfigDiffFilter(filter)
  return diffRows
    .filter((row) => row.status !== '=' && (!status || row.status === status))
    .map((row) => ({ leftLine: row.left_line, rightLine: row.right_line }))
}

export function correctConfigDiffChangeIndex(current: number, count: number): number {
  if (count <= 0) return 0
  return Math.min(Math.max(current, 0), count - 1)
}

export function exceedsMonacoDiffLimit(originalText: string, modifiedText: string): boolean {
  if (originalText.length + modifiedText.length > MONACO_DIFF_MAX_TOTAL_CHARACTERS) return true
  return countDocumentLines(originalText) + countDocumentLines(modifiedText) > MONACO_DIFF_MAX_TOTAL_LINES
}

function materializeDocument(lines: string[], lineCount: number): string {
  if (!lineCount) return ''
  const result = Array.from({ length: lineCount }, (_, index) => lines[index] ?? '')
  return result.join('\n')
}

function countDocumentLines(text: string): number {
  if (!text) return 0
  let count = 1
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) === 10) count += 1
  }
  return count
}
