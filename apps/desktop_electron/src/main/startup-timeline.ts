import type { DesktopLogger } from './logger'

export type StartupMilestone =
  | 'electron.app_ready'
  | 'electron.window_created'
  | 'electron.loading_view_shown'
  | 'backend.spawn_started'
  | 'backend.handshake_received'
  | 'backend.health_ready'
  | 'renderer.navigation_started'
  | 'renderer.dom_ready'
  | 'renderer.mounted'
  | 'desktop.interactive'

export interface StartupTimelineEntry {
  event: StartupMilestone
  elapsedMs: number
}

export class StartupTimeline {
  private readonly entries = new Map<StartupMilestone, StartupTimelineEntry>()

  constructor(
    private readonly logger: DesktopLogger,
    private readonly startedAt = process.hrtime.bigint(),
    private readonly now = () => process.hrtime.bigint(),
  ) {}

  mark(event: StartupMilestone): StartupTimelineEntry {
    const existing = this.entries.get(event)
    if (existing) return existing
    const elapsedMs = Number(this.now() - this.startedAt) / 1_000_000
    const entry = { event, elapsedMs }
    this.entries.set(event, entry)
    this.logger('ELECTRON_STARTUP_TIMELINE', `event=${event} elapsed_ms=${elapsedMs.toFixed(1)}`)
    return entry
  }

  snapshot(): StartupTimelineEntry[] {
    return [...this.entries.values()].map((entry) => ({ ...entry }))
  }
}
