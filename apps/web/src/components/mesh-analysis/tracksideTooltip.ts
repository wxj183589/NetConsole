import { escapeMeshTooltipHtml } from './meshRssiTooltip'

const TRACKSIDE_TOOLTIP_STYLE = [
  'min-width:260px',
  'width:340px',
  'max-width:360px',
  'max-height:min(420px,60vh)',
  'overflow-y:auto',
  'overscroll-behavior:contain',
  'white-space:normal',
  'overflow-wrap:anywhere',
  'line-height:1.5',
].join(';')
const DIVIDER_STYLE = 'margin:7px 0;border:0;border-top:1px solid currentColor;opacity:.28'

export interface TracksideTooltipEntry {
  apName: string | null
  radio: number | null
  role: 'ACTIVE' | 'STANDBY'
  tracksideRssi: number | null
  mrRssi: number | null
  station: string | null
  section: string | null
  activeDurationSeconds: number | null
}

function metric(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : escapeMeshTooltipHtml(value)
}

function entryLabel(entry: TracksideTooltipEntry): string {
  return entry.apName || '轨旁 AP 未知'
}

export function sortTracksideTooltipEntries(
  entries: readonly TracksideTooltipEntry[],
): TracksideTooltipEntry[] {
  return [...entries].sort((left, right) => (
    (left.role === 'ACTIVE' ? 0 : 1) - (right.role === 'ACTIVE' ? 0 : 1)
    || entryLabel(left).localeCompare(entryLabel(right), 'zh-CN')
    || (left.radio ?? Number.MAX_SAFE_INTEGER) - (right.radio ?? Number.MAX_SAFE_INTEGER)
  ))
}

export function buildTracksideTooltip(
  timestamp: string | null | undefined,
  entries: readonly TracksideTooltipEntry[],
): string {
  const rows = sortTracksideTooltipEntries(entries).map((entry, index) => {
    const location = `${entry.station || '—'} / ${entry.section || '—'}`
    const symbol = entry.role === 'ACTIVE' ? '●' : '○'
    const duration = entry.role === 'ACTIVE'
      && entry.activeDurationSeconds != null
      && Number.isFinite(entry.activeDurationSeconds)
      && entry.activeDurationSeconds >= 0
      ? `<br>主链持续：${metric(entry.activeDurationSeconds)} s`
      : ''
    return [
      index === 0 ? '' : `<hr style="${DIVIDER_STYLE}">`,
      `<strong>${symbol} ${escapeMeshTooltipHtml(entry.role)}　${escapeMeshTooltipHtml(entryLabel(entry))} · Radio ${metric(entry.radio)}</strong>`,
      `<br>轨旁 / MR RSSI：${metric(entry.tracksideRssi)} / ${metric(entry.mrRssi)}`,
      `<br>站点 / 区间：${escapeMeshTooltipHtml(location)}`,
      duration,
    ].join('')
  })
  const content = rows.length ? rows.join('') : '<br>当前时刻无有效采样'
  return `<div class="mesh-trackside-signal-tooltip" style="${TRACKSIDE_TOOLTIP_STYLE}">采样时间：${escapeMeshTooltipHtml(timestamp)}${content}</div>`
}

export function resolveTracksideTooltipPosition(
  pointerX: number,
  viewWidth: number,
  contentWidth: number,
  gap = 12,
  top = 12,
): [number, number] {
  const boundedView = Math.max(0, viewWidth)
  const boundedContent = Math.max(0, Math.min(contentWidth, boundedView - gap * 2))
  const left = pointerX < boundedView / 2
    ? Math.max(gap, boundedView - boundedContent - gap)
    : gap
  return [left, top]
}
