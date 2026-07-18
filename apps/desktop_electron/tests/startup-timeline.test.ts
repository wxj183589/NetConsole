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
})
