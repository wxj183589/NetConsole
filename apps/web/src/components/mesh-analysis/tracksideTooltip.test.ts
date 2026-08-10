import { describe, expect, it } from 'vitest'

import {
  displayTracksideTooltipMetric,
  sortTracksideTooltipEntries,
  tracksideTooltipApLabel,
  type TracksideTooltipEntry,
} from './tracksideTooltip'

const entries: TracksideTooltipEntry[] = [
  {
    seriesId: 'series-b',
    metaId: 2,
    apName: 'AP-B',
    radio: 2,
    role: 'STANDBY',
    tracksideRssi: 0,
    mrRssi: 0,
    station: '站点乙',
    section: null,
    activeDurationSeconds: 12.5,
    color: '#27ae60',
  },
  {
    seriesId: 'series-a',
    metaId: 1,
    apName: 'AP-A',
    radio: 1,
    role: 'ACTIVE',
    tracksideRssi: 29,
    mrRssi: 21,
    station: '站点甲',
    section: '区间甲',
    activeDurationSeconds: 7.574,
    color: '#2f80ed',
  },
]

describe('trackside tooltip view-model helpers', () => {
  it('sorts by role, AP label, and Radio without changing entries', () => {
    const sorted = sortTracksideTooltipEntries([
      { ...entries[1], radio: 2 },
      entries[0],
      { ...entries[1], radio: 1 },
    ])

    expect(sorted.map((entry) => `${entry.role}:${entry.apName}:${entry.radio}`)).toEqual([
      'ACTIVE:AP-A:1',
      'ACTIVE:AP-A:2',
      'STANDBY:AP-B:2',
    ])
    expect(entries[0].role).toBe('STANDBY')
  })

  it('keeps raw RSSI values and renders missing values as an em dash', () => {
    expect(displayTracksideTooltipMetric(29)).toBe('29')
    expect(displayTracksideTooltipMetric(0)).toBe('0')
    expect(displayTracksideTooltipMetric(null)).toBe('—')
    expect(displayTracksideTooltipMetric(Number.NaN)).toBe('—')
  })

  it('uses a stable user-facing fallback for a missing AP name', () => {
    expect(tracksideTooltipApLabel(entries[1])).toBe('AP-A')
    expect(tracksideTooltipApLabel({ ...entries[1], apName: null })).toBe('轨旁 AP 未知')
  })

})
