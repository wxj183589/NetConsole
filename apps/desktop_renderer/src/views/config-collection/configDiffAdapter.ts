import type { ConfigDiffRow, ConfigDiffSummary } from '../../types/configCollection'
import type {
  SharedConfigDiffModel,
  SharedConfigDiffRow,
  SharedConfigDiffStatus,
} from '../../components/config-diff/configDiffTypes'

const statusMap: Record<ConfigDiffRow['status'], SharedConfigDiffStatus> = {
  '=': 'equal',
  '+': 'added',
  '-': 'removed',
  '~': 'modified',
}

export function configCollectionDiffModel(input: {
  comparisonId: string
  originalLabel: string
  modifiedLabel: string
  originalText: string
  modifiedText: string
  summary: ConfigDiffSummary
  rows: readonly ConfigDiffRow[]
  rawDiff: string
}): SharedConfigDiffModel {
  return {
    comparisonId: input.comparisonId,
    original: { label: input.originalLabel, content: input.originalText },
    modified: { label: input.modifiedLabel, content: input.modifiedText },
    summary: { ...input.summary },
    rows: input.rows.map(mapRow),
    rawDiff: input.rawDiff,
  }
}

function mapRow(row: ConfigDiffRow): SharedConfigDiffRow {
  return {
    originalLine: row.left_line,
    originalText: row.left_text,
    modifiedLine: row.right_line,
    modifiedText: row.right_text,
    status: statusMap[row.status],
  }
}
