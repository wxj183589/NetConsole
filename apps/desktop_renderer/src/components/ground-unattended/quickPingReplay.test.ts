import { describe, expect, it } from 'vitest'
import { generateSimulatedQuickPing, simulatedQuickPingStats } from './quickPingReplay'

describe('simulated Quick Ping replay', () => {
  const args = ['hzdt-09', 'train-1', 'mr-ct', 'run-1', '192.0.2.1', '2026-11-07T00:00:00Z', '2026-11-07T00:02:00Z'] as const
  it('is deterministic and contains non-flat timeout/latency samples', () => {
    const first = generateSimulatedQuickPing(...args)
    expect(first).toEqual(generateSimulatedQuickPing(...args))
    expect(first.length).toBeGreaterThan(10)
    expect(first.some((row) => !row.sample.ok)).toBe(true)
    expect(new Set(first.filter((row) => row.sample.ok).map((row) => row.sample.rtt_ms)).size).toBeGreaterThan(1)
    expect(simulatedQuickPingStats(first).sent).toBe(first.length)
  })
  it('changes with identity and target address', () => {
    expect(generateSimulatedQuickPing(...args)).not.toEqual(generateSimulatedQuickPing('hzdt-09', 'train-2', args[2], args[3], args[4], args[5], args[6]))
    expect(generateSimulatedQuickPing(...args)).not.toEqual(generateSimulatedQuickPing(args[0], args[1], args[2], args[3], '192.0.2.2', args[5], args[6]))
  })
})
