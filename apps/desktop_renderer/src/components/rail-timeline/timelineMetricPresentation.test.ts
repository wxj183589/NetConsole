import { describe, expect, it } from 'vitest'

import { formatTimelineMetricValue, timelineMetricDefinition } from './timelineMetricPresentation'

describe('timeline metric presentation', () => {
  it('keeps Ping RTT and loss units distinct by metricId', () => {
    expect(formatTimelineMetricValue('ping_rtt', 44.7)).toBe('44.7 ms')
    expect(formatTimelineMetricValue('ping_rtt', 44.7)).not.toContain('%')
    expect(formatTimelineMetricValue('ping_loss', 0)).toBe('0%')
    expect(formatTimelineMetricValue('ping_loss', 0)).not.toContain('ms')
  })

  it('leaves RTT axis unbounded above while loss stays within 0~100%', () => {
    expect(formatTimelineMetricValue('ping_rtt', 280)).toBe('280 ms')
    expect(timelineMetricDefinition('ping_rtt')).toMatchObject({ axisUnit: 'ms', axisMin: 0 })
    expect(timelineMetricDefinition('ping_rtt')?.axisMax).toBeUndefined()
    expect(timelineMetricDefinition('ping_loss')).toMatchObject({ axisUnit: '%', axisMin: 0, axisMax: 100 })
  })
})
