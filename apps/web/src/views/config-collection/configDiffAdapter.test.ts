import { describe, expect, it } from 'vitest'

import { configCollectionDiffModel } from './configDiffAdapter'

describe('configuration collection diff adapter', () => {
  it('maps backend rows into the shared model', () => {
    const model = configCollectionDiffModel({
      comparisonId: 'task-1',
      originalLabel: 'running',
      modifiedLabel: 'saved',
      originalText: 'old',
      modifiedText: 'new',
      summary: { added: 0, removed: 0, modified: 1 },
      rows: [{ left_line: 1, left_text: 'old', status: '~', right_line: 1, right_text: 'new' }],
      rawDiff: 'raw',
    })

    expect(model.rows).toEqual([{
      originalLine: 1,
      originalText: 'old',
      modifiedLine: 1,
      modifiedText: 'new',
      status: 'modified',
    }])
  })
})
