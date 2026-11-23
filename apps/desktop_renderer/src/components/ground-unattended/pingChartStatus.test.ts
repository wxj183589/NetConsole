// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { heartbeatPointValues, heartbeatStatusStatistics, pingPointValues, pingStatusColor, pingTooltipFormatter } from './pingChartStatus'

describe('Ping chart state mapping', () => {
  it.each([
    ['SUCCESS', { status: 'SUCCESS', rtt_display_ms: 2, loss_percent: 0 }, '#22C55E'],
    ['TIMEOUT', { status: 'TIMEOUT', rtt_display_ms: null, loss_percent: 100 }, '#EF4444'],
    ['PACKET_LOSS', { status: 'PACKET_LOSS', rtt_display_ms: 2, loss_percent: 25 }, '#EF4444'],
    ['UNKNOWN', { status: 'UNKNOWN', rtt_display_ms: null, loss_percent: null }, '#909399'],
  ] as const)('%s keeps its semantic color', (status, sample, color) => {
    expect(pingPointValues(sample)).toMatchObject({ status })
    expect(pingStatusColor(status)).toBe(color)
  })

  it('does not turn successful zero loss into 100 percent or invent RTT for timeout', () => {
    expect(pingPointValues({ status: 'SUCCESS', rtt_display_ms: 2, loss_percent: 0 })).toMatchObject({ status: 'SUCCESS', rtt: 2, loss: 0 })
    expect(pingPointValues({ status: 'TIMEOUT', rtt_display_ms: null, loss_percent: 100 })).toMatchObject({ status: 'TIMEOUT', rtt: null, loss: 100 })
    expect(pingPointValues({ status: 'PACKET_LOSS', rtt_display_ms: 3, loss_percent: 25 })).toMatchObject({ status: 'PACKET_LOSS', rtt: 3, loss: 25 })
    expect(pingPointValues({ status: 'UNKNOWN', rtt_display_ms: null, loss_percent: null })).toMatchObject({ status: 'UNKNOWN', rtt: null, loss: null })
  })

  it('keeps tooltip status, RTT and loss values consistent', () => {
    const points = [
      { target: '10.0.0.1', time: Date.parse('2026-11-07T00:00:00Z'), ...pingPointValues({ status: 'SUCCESS', rtt_display_ms: 2, loss_percent: 0 }) },
      { target: '10.0.0.1', time: Date.parse('2026-11-07T00:00:01Z'), ...pingPointValues({ status: 'TIMEOUT', rtt_display_ms: null, loss_percent: 100 }) },
    ]
    expect(pingTooltipFormatter(points, [{ axisValue: Date.parse('2026-11-07T00:00:00Z'), seriesName: 'RTT（ms）' }])).toContain('状态：正常连通')
    expect(pingTooltipFormatter(points, [{ axisValue: Date.parse('2026-11-07T00:00:01Z'), seriesName: '丢包/超时' }])).toContain('丢包：100%')
  })

  it('uses the persisted Heartbeat result independently of RTT', () => {
    expect(heartbeatPointValues({ heartbeat_status: 'SUCCESS', rtt_ms: null })).toMatchObject({ status: 'SUCCESS', loss: 0 })
    expect(heartbeatPointValues({ heartbeat_status: 'PACKET_LOSS', rtt_ms: 0 })).toMatchObject({ status: 'PACKET_LOSS', loss: 100 })
    expect(heartbeatPointValues({ heartbeat_status: 'TIMEOUT', status: 'SUCCESS', rtt_ms: 3 }).status).toBe('TIMEOUT')
    expect(heartbeatStatusStatistics([
      { heartbeat_status: 'SUCCESS', rtt_ms: null }, { heartbeat_status: 'PACKET_LOSS', rtt_ms: null }, { heartbeat_status: 'UNKNOWN' },
    ])).toEqual({ success: 1, failure: 1, unknown: 1, valid: 2, connectivityRate: 50 })
  })
})
