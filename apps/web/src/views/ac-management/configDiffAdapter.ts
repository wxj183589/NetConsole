import type { SharedConfigDiffModel, SharedConfigDiffStatus } from '../../components/config-diff/configDiffTypes'
import type { AcConfigDiff } from '../../types/acManagement'

const statusMap: Record<AcConfigDiff['diff_rows'][number]['status'], SharedConfigDiffStatus> = {
  '=': 'equal',
  '+': 'added',
  '-': 'removed',
  '~': 'modified',
}

export function acConfigDiffModel(diff: AcConfigDiff): SharedConfigDiffModel {
  return {
    comparisonId: `ac-${diff.from_snapshot_id}-${diff.to_snapshot_id}`,
    original: { id: diff.from_snapshot_id, label: diff.left_label, content: diff.left_content },
    modified: { id: diff.to_snapshot_id, label: diff.right_label, content: diff.right_content },
    summary: { ...diff.diff_summary },
    rows: diff.diff_rows.map((row) => ({
      originalLine: row.left_line,
      originalText: row.left_text,
      modifiedLine: row.right_line,
      modifiedText: row.right_text,
      status: statusMap[row.status],
    })),
    rawDiff: diff.raw_diff,
    truncated: diff.truncated,
  }
}
