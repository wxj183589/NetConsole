import { describe, expect, it } from 'vitest'

import {
  nextConfigDiffChangeIndex,
  parseConfigDiffRows,
  parseConfigDiffSummary,
  statusForConfigDiffFilter,
} from './configDiff'

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

  it('maps all filters and wraps previous/next navigation', () => {
    expect(statusForConfigDiffFilter('all')).toBeNull()
    expect(statusForConfigDiffFilter('added')).toBe('+')
    expect(statusForConfigDiffFilter('removed')).toBe('-')
    expect(statusForConfigDiffFilter('modified')).toBe('~')
    expect(nextConfigDiffChangeIndex(0, 3, -1)).toBe(2)
    expect(nextConfigDiffChangeIndex(2, 3, 1)).toBe(0)
    expect(nextConfigDiffChangeIndex(0, 0, 1)).toBe(0)
  })
})
