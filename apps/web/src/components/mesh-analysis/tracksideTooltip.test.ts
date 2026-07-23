import { describe, expect, it } from 'vitest'

import {
  buildTracksideTooltip,
  resolveTracksideTooltipPosition,
  type TracksideTooltipEntry,
} from './tracksideTooltip'

const entries: TracksideTooltipEntry[] = [
  {
    apName: 'AP-B',
    radio: 2,
    role: 'STANDBY',
    tracksideRssi: -51,
    mrRssi: -48,
    station: '站点乙',
    section: null,
    activeDurationSeconds: 12.5,
  },
  {
    apName: 'AP-A',
    radio: 1,
    role: 'ACTIVE',
    tracksideRssi: -41,
    mrRssi: -38,
    station: '站点甲',
    section: '区间甲',
    activeDurationSeconds: 7.574,
  },
]

describe('trackside tooltip', () => {
  it('keeps only the compact business fields and one timestamp', () => {
    const html = buildTracksideTooltip('2026-07-20 13:53:19.181', entries)

    expect(html.match(/采样时间：/g)).toHaveLength(1)
    expect(html).toContain('● ACTIVE　AP-A · Radio 1')
    expect(html).toContain('○ STANDBY　AP-B · Radio 2')
    expect(html).toContain('轨旁 / MR RSSI：-41 / -38 dBm')
    expect(html).toContain('站点 / 区间：站点乙 / —')
    expect(html.match(/主链持续：/g)).toHaveLength(1)
    expect(html.indexOf('ACTIVE')).toBeLessThan(html.indexOf('STANDBY'))
    for (const removed of [
      '序列：',
      'AP MAC：',
      'Peer MAC：',
      'Peer Radio MAC：',
      'Peer Signal / MR Signal：',
      '数据来源：',
      'peer_rssi_db',
      'run_id',
      'link_id',
    ]) expect(html).not.toContain(removed)
  })

  it('sorts equal AP names by Radio after role', () => {
    const html = buildTracksideTooltip('2026-07-20 13:53:19.181', [
      { ...entries[1], radio: 2 },
      { ...entries[1], radio: 1 },
    ])
    expect(html.indexOf('Radio 1')).toBeLessThan(html.indexOf('Radio 2'))
  })

  it('stays fixed within each half and flips only across the center', () => {
    expect(resolveTracksideTooltipPosition(100, 1_000, 340)).toEqual([648, 12])
    expect(resolveTracksideTooltipPosition(400, 1_000, 340)).toEqual([648, 12])
    expect(resolveTracksideTooltipPosition(600, 1_000, 340)).toEqual([12, 12])
    expect(resolveTracksideTooltipPosition(900, 1_000, 340)).toEqual([12, 12])
    expect(resolveTracksideTooltipPosition(50, 300, 340)).toEqual([12, 12])
  })

  it('builds 100 current-frame tooltips below the 5ms target', () => {
    const frameEntries = Array.from({ length: 16 }, (_, index) => ({
      ...entries[index % entries.length],
      apName: `AP-${String(index).padStart(2, '0')}`,
      radio: index % 2 + 1,
    }))
    const durations: number[] = []
    for (let index = 0; index < 100; index += 1) {
      const started = performance.now()
      buildTracksideTooltip('2026-07-20 13:53:19.181', frameEntries)
      durations.push(performance.now() - started)
    }
    const average = durations.reduce((sum, item) => sum + item, 0) / durations.length
    const maximum = Math.max(...durations)
    console.info(`trackside tooltip profile: avg=${average.toFixed(3)}ms max=${maximum.toFixed(3)}ms`)
    expect(average).toBeLessThan(5)
    expect(maximum).toBeLessThan(5)
  })
})
