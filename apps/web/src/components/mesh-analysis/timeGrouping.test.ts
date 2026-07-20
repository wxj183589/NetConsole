import { describe, expect, it } from 'vitest'

import { buildMeshTimeGroupClasses } from './timeGrouping'

describe('meshTimeGroupClass', () => {
  it('keeps equal timestamps in one group and alternates only on change', () => {
    const rows = [{ timestamp: 't1' }, { timestamp: 't1' }, { timestamp: 't2' }, { timestamp: 't2' }, { timestamp: 't3' }]
    const groups = buildMeshTimeGroupClasses(rows, (item) => item.timestamp)
    expect(rows.map((row) => groups.get(row))).toEqual([
      'mesh-time-group-0', 'mesh-time-group-0', 'mesh-time-group-1', 'mesh-time-group-1', 'mesh-time-group-0',
    ])
  })

  it('keeps missing timestamps visible without inventing a time', () => {
    const rows = [{ timestamp: null }, { timestamp: null }, { timestamp: 't1' }]
    const groups = buildMeshTimeGroupClasses(rows, (item) => item.timestamp)
    expect(groups.get(rows[0])).toBe('mesh-time-group-0')
    expect(groups.get(rows[2])).toBe('mesh-time-group-1')
  })
})
