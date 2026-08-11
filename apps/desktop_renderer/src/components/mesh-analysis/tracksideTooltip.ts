import type { MeshRssiZeroRun } from '../../types/meshAnalysis'

export interface TracksideTooltipEntry {
  seriesId: string
  metaId: number
  apName: string | null
  radio: number | null
  role: 'ACTIVE' | 'STANDBY'
  linkCount?: number | null
  tracksideRssi: number | null
  mrRssi: number | null
  station: string | null
  section: string | null
  activeDurationSeconds: number | null
  color: string
  rssiZeroRun?: MeshRssiZeroRun | null
}

export interface PinnedTracksideFrame {
  timestamp: string
  timestampMillis: number
  entries: TracksideTooltipEntry[]
}

export function displayTracksideTooltipMetric(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : String(value)
}

export function displayTracksideZeroDuration(durationMs: number): string {
  return `${(Math.max(durationMs, 0) / 1_000).toFixed(3)} s`
}

export function tracksideTooltipApLabel(entry: TracksideTooltipEntry): string {
  return entry.apName || '轨旁 AP 未知'
}

export function sortTracksideTooltipEntries(
  entries: readonly TracksideTooltipEntry[],
): TracksideTooltipEntry[] {
  return [...entries].sort((left, right) => (
    (left.role === 'ACTIVE' ? 0 : 1) - (right.role === 'ACTIVE' ? 0 : 1)
    || tracksideTooltipApLabel(left).localeCompare(tracksideTooltipApLabel(right), 'zh-CN')
    || (left.radio ?? Number.MAX_SAFE_INTEGER) - (right.radio ?? Number.MAX_SAFE_INTEGER)
  ))
}
