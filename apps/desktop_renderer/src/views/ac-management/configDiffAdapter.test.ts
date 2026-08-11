import { describe, expect, it } from 'vitest'

import { acConfigDiffModel } from './configDiffAdapter'

describe('AC configuration diff adapter', () => {
  it('maps the AC contract without parsing unified diff text', () => {
    const model = acConfigDiffModel({
      from_snapshot_id: 79,
      to_snapshot_id: 80,
      left_label: 'saved · batch',
      right_label: 'running · batch',
      left_content: 'old',
      right_content: 'new',
      diff_rows: [{ left_line: 1, left_text: 'old', status: '~', right_line: 1, right_text: 'new' }],
      diff_summary: { added: 0, removed: 0, modified: 1 },
      added: [],
      removed: [],
      modified: [{ from: 'old', to: 'new' }],
      raw_diff: 'not parsed',
      truncated: false,
    })

    expect(model.original.content).toBe('old')
    expect(model.modified.content).toBe('new')
    expect(model.rows?.[0].status).toBe('modified')
    expect(model.rawDiff).toBe('not parsed')
  })
})
