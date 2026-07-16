import type {
  ConfigDiffRow,
  ConfigDiffStatus,
  ConfigDiffSummary,
} from '../../types/configCollection'

export type ConfigDiffFilter = 'all' | 'added' | 'removed' | 'modified'

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
