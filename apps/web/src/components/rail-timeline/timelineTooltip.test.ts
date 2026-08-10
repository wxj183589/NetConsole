import { describe, expect, it } from 'vitest'

import {
  buildTimelineTooltip,
  formatTimelineTime,
  type TimelineTooltipRow,
} from './timelineTooltip'
import { formatTimelineMetricValue } from './timelineMetricPresentation'

describe('timeline tooltip', () => {
  it('uses a compact tooltip by default and keeps detailed formatting available', () => {
    const rows: TimelineTooltipRow[] = [{
      seriesName: '上行',
      value: ['2026-07-21 15:00:00.123', 3] as [string, number],
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
    }]

    const quick = buildTimelineTooltip('traffic', rows)
    expect(quick).toContain('timeline-tooltip--quick')
    expect(quick).toContain('15:00:00.123')
    expect(quick).toContain('上行')
    expect(quick).toContain('3 Mbps')
    expect(quick).not.toContain('测试方向')

    const html = buildTimelineTooltip('traffic', rows, true)

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

  it('does not attach dBm to raw RSSI tooltip values', () => {
    const html = buildTimelineTooltip('generic', [{
      seriesName: '当前 ACTIVE MR 侧 RSSI',
      value: ['2026-07-21 15:00:00.123', 49],
      data: { metricType: 'rssi' },
    }])
    expect(html).toContain('49')
    expect(html).not.toContain('49 dBm')
  })

  it('renders Ping RTT as structured milliseconds rather than joining it to the target or a percent unit', () => {
    const html = buildTimelineTooltip('ping-rtt', [{
      seriesName: '10.122.2.249',
      value: ['2026-08-10 02:56:12.660', 34.2],
      data: {
        metricType: 'ping_rtt',
        point: {
          timestamp: '2026-08-10 02:56:12.660',
          value: 34.2,
          text_value: null,
          dimensions: { target_ip: '10.122.2.249', loss_percent: 0 },
        },
      },
    }], true)

    expect(html).toContain('时间：2026-08-10 02:56:12.660')
    expect(html).toContain('目标')
    expect(html).toContain('10.122.2.249')
    expect(html).toContain('RTT')
    expect(html).toContain('34.2 ms')
    expect(html).toContain('丢包')
    expect(html).toContain('0%')
    expect(html).not.toContain('10.122.2.24934.2%')
  })

  it('keeps the Ping loss tooltip as a percent', () => {
    const html = buildTimelineTooltip('ping-loss', [{
      seriesName: '10.122.2.249',
      value: ['2026-08-10 02:56:12.660', 50],
      data: { metricType: 'ping_loss', point: { timestamp: '2026-08-10 02:56:12.660', value: 50, text_value: null, dimensions: { target_ip: '10.122.2.249' } } },
    }], true)
    expect(html).toContain('丢包率')
    expect(html).toContain('50%')
    expect(html).not.toContain('50 ms')
  })

  it('uses the same RTT display value as the fixed analysis information', () => {
    const fixedInfoValue = formatTimelineMetricValue('ping_rtt', 34.2)
    const tooltip = buildTimelineTooltip('ping-rtt', [{
      value: ['2026-08-10 02:56:12.660', 34.2],
      data: { metricType: 'ping_rtt', point: { timestamp: '2026-08-10 02:56:12.660', value: 34.2, text_value: null, dimensions: { target_ip: '10.122.2.249', loss_percent: 0 } } },
    }], true)
    expect(fixedInfoValue).toBe('34.2 ms')
    expect(tooltip).toContain(`RTT</span><strong>${fixedInfoValue}</strong>`)
  })
})
