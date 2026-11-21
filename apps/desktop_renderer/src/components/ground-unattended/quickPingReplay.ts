export interface SimulatedQuickPingRow {
  [key: string]: unknown
  received_at: string
  target_ip: string
  sample: { ok: boolean; rtt_ms: number | null; source: 'SIMULATED_QUICK_PING' }
}

function seedFor(value: string): number {
  let hash = 2166136261
  for (const char of value) hash = Math.imul(hash ^ char.codePointAt(0)!, 16777619)
  return hash >>> 0
}

function nextRandom(state: { value: number }): number {
  let x = state.value || 1
  x ^= x << 13; x ^= x >>> 17; x ^= x << 5
  state.value = x >>> 0
  return state.value / 0x100000000
}

/** Deterministic renderer-only playback; it never calls the network or API. */
export function generateSimulatedQuickPing(
  siteId: string, trainId: string, mrId: string, runId: string, targetIp: string,
  start: string, end: string, intervalMs = 1000,
): SimulatedQuickPingRow[] {
  const begin = Date.parse(start), finish = Date.parse(end)
  if (!Number.isFinite(begin) || !Number.isFinite(finish) || finish <= begin) return []
  const step = Math.max(250, intervalMs)
  const maxSamples = 10_000
  const count = Math.min(maxSamples, Math.floor((finish - begin) / step) + 1)
  const state = { value: seedFor([siteId, trainId, mrId, runId, targetIp, start, end].join('|')) }
  const baseline = 8 + Math.floor(nextRandom(state) * 18)
  const rows: SimulatedQuickPingRow[] = []
  for (let index = 0; index < count; index++) {
    const time = begin + index * step
    if (time > finish) break
    const roll = nextRandom(state)
    const timeout = index > 2 && (index % 47 === 0 || roll < 0.018)
    const highLatency = !timeout && (index % 31 === 0 || roll > 0.94)
    const jitter = Math.round((nextRandom(state) - 0.5) * 8)
    const rtt = timeout ? null : Math.max(1, baseline + jitter + (highLatency ? 90 + Math.round(nextRandom(state) * 80) : 0))
    rows.push({
      received_at: new Date(time).toISOString(), target_ip: targetIp,
      sample: { ok: !timeout, rtt_ms: rtt, source: 'SIMULATED_QUICK_PING' },
    })
  }
  return rows
}

export function simulatedQuickPingStats(rows: SimulatedQuickPingRow[]) {
  const successful = rows.map((row) => row.sample.rtt_ms).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const lost = rows.length - successful.length
  return {
    sent: rows.length, received: successful.length, lost,
    lossRate: rows.length ? lost / rows.length * 100 : 0,
    min: successful.length ? Math.min(...successful) : null,
    max: successful.length ? Math.max(...successful) : null,
    average: successful.length ? successful.reduce((sum, value) => sum + value, 0) / successful.length : null,
    lostSeconds: lost,
  }
}
