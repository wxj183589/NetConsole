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
    private readonly stageTracingEnabled = false,
  ) {}

  beginStage(stage: string, request?: string): () => void {
    if (!this.stageTracingEnabled) return () => undefined
    const startedAt = this.now()
    const elapsedMs = Number(startedAt - this.startedAt) / 1_000_000
    this.logger('ELECTRON_STARTUP_STAGE', JSON.stringify({
      stage,
      phase: 'start',
      elapsed_ms: Number(elapsedMs.toFixed(1)),
      ...(request ? { request } : {}),
    }))
    return () => {
      const endedAt = this.now()
      const endedElapsedMs = Number(endedAt - this.startedAt) / 1_000_000
      const durationMs = Number(endedAt - startedAt) / 1_000_000
      this.logger('ELECTRON_STARTUP_STAGE', JSON.stringify({
        stage,
        phase: 'end',
        elapsed_ms: Number(endedElapsedMs.toFixed(1)),
        duration_ms: Number(durationMs.toFixed(1)),
        ...(request ? { request } : {}),
      }))
    }
  }

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

  performanceSummary(): Record<string, number | undefined> {
    const elapsed = (event: StartupMilestone): number | undefined => this.entries.get(event)?.elapsedMs
    return {
      spawn_first_stdout_ms: elapsed('backend.handshake_received'),
      backend_health_ms: elapsed('backend.health_ready'),
      renderer_ready_ms: elapsed('desktop.interactive'),
      total_ms: elapsed('desktop.interactive'),
    }
  }
}
