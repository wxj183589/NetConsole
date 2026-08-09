import { describe, expect, it } from 'vitest'

import {
  buildTimelineTooltip,
  formatTimelineTime,
} from './timelineTooltip'

describe('timeline tooltip', () => {
  it('shows business fields without leaking internal dimensions', () => {
    const html = buildTimelineTooltip('traffic', [{
      seriesName: '上行',
      value: ['2026-07-21 15:00:00.123', 3],
      data: {
        metricType: 'iperf_bitrate',
        point: {
          timestamp: '2026-07-21 15:00:00.123',
          raw_timestamp: '2026-07-21 15:00:00.123',
          normalized_timestamp: '2026-07-21 15:00:00.123',
          timestamp_source: 'device',
          correction_ms: null,
          correction_method: 'none',
          correction_confidence: 'high',
          value: 3,
          text_value: null,
          dimensions: {
            direction: 'upload',
            target_ip: '10.0.0.1',
            statistic: 'average',
            role: 'old',
            radio: null,
            transfer_bytes: 1024,
            loss_percent: null,
          },
        },
      },
    }])

    expect(html).toContain('时间：2026-07-21 15:00:00.123')
    expect(html).toContain('测试方向')
    expect(html).toContain('MR → Server')
    expect(html).toContain('发送数据')
    expect(html).not.toContain('target_ip=')
    expect(html).not.toContain('statistic=')
    expect(html).not.toContain('role=old')
    expect(html).not.toContain('radio=null')
    expect(html).not.toContain('176')
  })

  it('formats Unix milliseconds as a readable local timestamp', () => {
    const formatted = formatTimelineTime(new Date('2026-07-21T15:00:00.000').getTime())
    expect(formatted).toMatch(/^2026-07-21 15:00:00$/)
  })
})
