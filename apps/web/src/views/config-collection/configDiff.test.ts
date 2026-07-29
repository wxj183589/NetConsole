import { describe, expect, it } from 'vitest'

import {
  buildConfigDiffDocuments,
  parseConfigDiffRows,
  parseConfigDiffSummary,
} from './configDiff'
import type { ConfigDiffRow } from '../../types/configCollection'

describe('configuration side-by-side diff contract', () => {
  it('parses only valid server rows and summaries', () => {
    expect(parseConfigDiffRows([
      { left_line: 2, left_text: 'vlan 10', status: '~', right_line: 2, right_text: 'vlan 20' },
      { status: 'invalid' },
    ])).toEqual([
      { left_line: 2, left_text: 'vlan 10', status: '~', right_line: 2, right_text: 'vlan 20' },
    ])
    expect(parseConfigDiffSummary({ added: 1, removed: 2, modified: 3 })).toEqual({ added: 1, removed: 2, modified: 3 })
  })

  it('rebuilds complete left and right documents without changing the input', () => {
    const rows: ConfigDiffRow[] = [
      row(1, '#', '=', 1, '#'),
      row(2, 'sysname OLD', '~', 2, 'sysname NEW'),
      row(null, '', '+', 3, 'vlan 20'),
      row(3, 'return', '-', null, ''),
    ]
    const before = structuredClone(rows)

    expect(buildConfigDiffDocuments(rows)).toEqual({
      originalText: '#\nsysname OLD\nreturn',
      modifiedText: '#\nsysname NEW\nvlan 20',
      originalLineCount: 3,
      modifiedLineCount: 3,
    })
    expect(rows).toEqual(before)
  })

  it('preserves blank first lines, blank body lines and non-contiguous line numbers', () => {
    const documents = buildConfigDiffDocuments([
      row(1, '', '=', 1, ''),
      row(3, 'left-three', '~', 4, 'right-four'),
    ])

    expect(documents.originalText).toBe('\n\nleft-three')
    expect(documents.modifiedText).toBe('\n\n\nright-four')
    expect(documents.originalLineCount).toBe(3)
    expect(documents.modifiedLineCount).toBe(4)
  })

  it('handles empty and identical documents without trimming or deduplicating lines', () => {
    expect(buildConfigDiffDocuments([])).toEqual({
      originalText: '',
      modifiedText: '',
      originalLineCount: 0,
      modifiedLineCount: 0,
    })
    expect(buildConfigDiffDocuments([
      row(1, 'same', '=', 1, 'same'),
      row(2, 'same', '=', 2, 'same'),
    ])).toEqual({
      originalText: 'same\nsame',
      modifiedText: 'same\nsame',
      originalLineCount: 2,
      modifiedLineCount: 2,
    })
  })

  it('keeps one-sided additions and removals on their own document', () => {
    expect(buildConfigDiffDocuments([
      row(1, 'removed', '-', null, ''),
      row(null, '', '+', 1, 'added'),
    ])).toEqual({
      originalText: 'removed',
      modifiedText: 'added',
      originalLineCount: 1,
      modifiedLineCount: 1,
    })
  })

})

function row(
  leftLine: number | null,
  leftText: string,
  status: ConfigDiffRow['status'],
  rightLine: number | null,
  rightText: string,
): ConfigDiffRow {
  return {
    left_line: leftLine,
    left_text: leftText,
    status,
    right_line: rightLine,
    right_text: rightText,
  }
}
