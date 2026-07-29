import { describe, expect, it } from 'vitest'

import {
  configDiffNavigationTargets,
  correctConfigDiffChangeIndex,
  exceedsMonacoDiffLimit,
  MONACO_DIFF_MAX_TOTAL_CHARACTERS,
  nextConfigDiffChangeIndex,
} from './configDiffNavigation'
import type { SharedConfigDiffModel, SharedConfigDiffRow } from './configDiffTypes'

describe('shared configuration diff navigation', () => {
  const rows: SharedConfigDiffRow[] = [
    row(1, 1, 'equal'),
    row(2, 2, 'modified'),
    row(null, 3, 'added'),
    row(3, null, 'removed'),
  ]

  it('filters targets and wraps navigation', () => {
    expect(configDiffNavigationTargets(rows)).toHaveLength(3)
    expect(configDiffNavigationTargets(rows, 'added')).toEqual([{
      originalLine: null,
      modifiedLine: 3,
    }])
    expect(nextConfigDiffChangeIndex(0, 3, -1)).toBe(2)
    expect(nextConfigDiffChangeIndex(2, 3, 1)).toBe(0)
    expect(correctConfigDiffChangeIndex(3, 1)).toBe(0)
  })

  it('guards Monaco without truncating either document', () => {
    expect(exceedsMonacoDiffLimit(model('x'.repeat(MONACO_DIFF_MAX_TOTAL_CHARACTERS + 1), ''))).toBe(true)
    expect(exceedsMonacoDiffLimit(model('line 1\nline 2', 'line 1\nline 3'))).toBe(false)
  })
})

function row(
  originalLine: number | null,
  modifiedLine: number | null,
  status: SharedConfigDiffRow['status'],
): SharedConfigDiffRow {
  return { originalLine, originalText: '', modifiedLine, modifiedText: '', status }
}

function model(original: string, modified: string): SharedConfigDiffModel {
  return {
    comparisonId: 'limit',
    original: { label: 'left', content: original },
    modified: { label: 'right', content: modified },
    summary: { added: 0, removed: 0, modified: 0 },
  }
}
