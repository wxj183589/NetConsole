export type SharedConfigDiffStatus = 'equal' | 'added' | 'removed' | 'modified'

export interface SharedConfigDiffRow {
  originalLine: number | null
  originalText: string
  modifiedLine: number | null
  modifiedText: string
  status: SharedConfigDiffStatus
}

export interface SharedConfigDiffModel {
  comparisonId: string
  original: {
    id?: string | number
    label: string
    content: string
  }
  modified: {
    id?: string | number
    label: string
    content: string
  }
  summary: {
    added: number
    removed: number
    modified: number
  }
  rows?: SharedConfigDiffRow[]
  rawDiff?: string
  truncated?: boolean
}

export type ConfigDiffFilter = 'all' | Exclude<SharedConfigDiffStatus, 'equal'>
