export interface TracksideTooltipEntry {
  apName: string | null
  radio: number | null
  role: 'ACTIVE' | 'STANDBY'
  tracksideRssi: number | null
  mrRssi: number | null
  station: string | null
  section: string | null
  activeDurationSeconds: number | null
  color: string
}

export function displayTracksideTooltipMetric(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : String(value)
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
