import { describe, expect, it, vi } from 'vitest'

import { StartupTimeline } from '../src/main/startup-timeline'

describe('StartupTimeline', () => {
  it('records each monotonic milestone once without wall-clock or secret data', () => {
    const logger = vi.fn()
    const ticks = [1_050_000_000n, 1_200_000_000n]
    const timeline = new StartupTimeline(logger, 1_000_000_000n, () => ticks.shift()!)

    timeline.mark('electron.app_ready')
    timeline.mark('electron.app_ready')
    timeline.mark('backend.spawn_started')

    expect(timeline.snapshot()).toEqual([
      { event: 'electron.app_ready', elapsedMs: 50 },
      { event: 'backend.spawn_started', elapsedMs: 200 },
    ])
    expect(logger).toHaveBeenCalledTimes(2)
    expect(logger).toHaveBeenLastCalledWith(
      'ELECTRON_STARTUP_TIMELINE',
      'event=backend.spawn_started elapsed_ms=200.0',
    )
  })

  it('summarizes production timing without a synthetic benchmark', () => {
    const logger = vi.fn()
    const ticks = [1_000_000_000n, 1_800_000_000n, 2_400_000_000n]
    const timeline = new StartupTimeline(logger, 0n, () => ticks.shift()!)
    timeline.mark('backend.handshake_received')
    timeline.mark('backend.health_ready')
    timeline.mark('desktop.interactive')

    expect(timeline.performanceSummary()).toMatchObject({
      spawn_first_stdout_ms: 1000,
      backend_health_ms: 1800,
      renderer_ready_ms: 2400,
      total_ms: 2400,
    })
  })
})
