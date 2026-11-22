// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { classifyPingStatus, heartbeatPointValues, heartbeatStatusStatistics, pingPointValues, pingStatusColor, pingTooltipFormatter } from './pingChartStatus'

describe('Ping chart state mapping', () => {
  it.each([
    ['SUCCESS', { ok: true, rtt_ms: 2 }, '#22C55E'],
    ['TIMEOUT', { ok: false, error: 'timeout' }, '#EF4444'],
    ['PACKET_LOSS', { status: 'PACKET_LOSS', ok: false }, '#EF4444'],
    ['UNKNOWN', { ok: undefined, rtt_ms: null }, '#909399'],
  ] as const)('%s keeps its semantic color', (status, sample, color) => {
    expect(classifyPingStatus(sample)).toBe(status)
    expect(pingStatusColor(status)).toBe(color)
  })

  it('does not turn successful zero loss into 100 percent or invent RTT for timeout', () => {
    expect(pingPointValues({ ok: true, rtt_ms: 2 })).toMatchObject({ status: 'SUCCESS', rtt: 2, loss: 0 })
    expect(pingPointValues({ ok: false, error: 'timeout', rtt_ms: null })).toMatchObject({ status: 'TIMEOUT', rtt: null, loss: 100 })
    expect(pingPointValues({ ok: true, rtt_ms: 3, loss_percent: 25 })).toMatchObject({ status: 'PACKET_LOSS', rtt: 3, loss: 25 })
    expect(pingPointValues({ ok: undefined, rtt_ms: null })).toMatchObject({ status: 'UNKNOWN', rtt: null, loss: null })
  })

  it('keeps tooltip status, RTT and loss values consistent', () => {
    const points = [
      { target: '10.0.0.1', time: Date.parse('2026-11-07T00:00:00Z'), ...pingPointValues({ ok: true, rtt_ms: 2 }) },
      { target: '10.0.0.1', time: Date.parse('2026-11-07T00:00:01Z'), ...pingPointValues({ ok: false, error: 'timeout' }) },
    ]
    expect(pingTooltipFormatter(points, [{ axisValue: Date.parse('2026-11-07T00:00:00Z'), seriesName: 'RTT（ms）' }])).toContain('状态：正常连通')
    expect(pingTooltipFormatter(points, [{ axisValue: Date.parse('2026-11-07T00:00:01Z'), seriesName: '丢包/超时' }])).toContain('丢包：100%')
  })

  it('uses the persisted Heartbeat result independently of RTT', () => {
    expect(heartbeatPointValues({ ok: true, rtt_ms: null })).toMatchObject({ status: 'SUCCESS', loss: 0 })
    expect(heartbeatPointValues({ ok: false, rtt_ms: 0 })).toMatchObject({ status: 'PACKET_LOSS', loss: 100 })
    expect(heartbeatPointValues({ status: 'TIMEOUT', ok: true, rtt_ms: 3 }).status).toBe('TIMEOUT')
    expect(heartbeatStatusStatistics([
      { ok: true, rtt_ms: null }, { ok: false, rtt_ms: null }, { status: 'UNKNOWN' },
    ])).toEqual({ success: 1, failure: 1, unknown: 1, valid: 2, connectivityRate: 50 })
  })
})
