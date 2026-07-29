import type {
  ConfigDiffRow,
  ConfigDiffStatus,
  ConfigDiffSummary,
} from '../../types/configCollection'

export interface ConfigDiffDocuments {
  originalText: string
  modifiedText: string
  originalLineCount: number
  modifiedLineCount: number
}

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

function materializeDocument(lines: string[], lineCount: number): string {
  if (!lineCount) return ''
  const result = Array.from({ length: lineCount }, (_, index) => lines[index] ?? '')
  return result.join('\n')
}
