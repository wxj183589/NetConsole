import type { MeshChartBackupLink, MeshChartEvent, MeshChartPoint, MeshSwitchEvent } from '../../types/meshAnalysis'

const TOOLTIP_STYLE = 'min-width:280px;max-width:420px;white-space:normal;overflow-wrap:anywhere;line-height:1.6'
const DIVIDER_STYLE = 'margin:8px 0;border:0;border-top:1px solid currentColor;opacity:.35'

export function escapeMeshTooltipHtml(value: unknown): string {
  const text = value == null || value === '' ? '—' : String(value)
  return text.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)
}

function metric(value: number | null | undefined, unit = ''): string {
  return value == null ? '—' : escapeMeshTooltipHtml(`${value}${unit}`)
}

function divider(): string {
  return `<hr class="mesh-rssi-tooltip__divider" style="${DIVIDER_STYLE}">`
}

export function buildBackupSection(backups: readonly MeshChartBackupLink[]): string {
  if (!backups.length) return `${divider()}<strong>备份链路：无</strong>`
  const rows = backups.map((item, index) => [
    `${index + 1}. ${escapeMeshTooltipHtml(item.peer_ap_name || item.peer_mac)}`,
    `AP MAC：${escapeMeshTooltipHtml(item.peer_ap_mac)}`,
    `MR / 轨旁 AP 接收信号：${metric(item.local_rssi)} / ${metric(item.peer_rssi)}`,
    `Radio：${item.local_radio == null ? '—' : `radio${escapeMeshTooltipHtml(item.local_radio)}`}`,
    `归属站点 / 区间：${escapeMeshTooltipHtml(item.station)} / ${escapeMeshTooltipHtml(item.section)}`,
  ].join('<br>'))
  return `${divider()}<strong>备份链路</strong><br>${rows.join('<br>')}`
}

export function buildSwitchSection(event?: MeshChartEvent): string {
  if (!event) return ''
  return [
    divider(),
    '<strong>切换事件</strong>',
    `切出：${escapeMeshTooltipHtml(event.from_ap_name)} / ${escapeMeshTooltipHtml(event.from_peer_mac)}`,
    `切入：${escapeMeshTooltipHtml(event.to_ap_name)} / ${escapeMeshTooltipHtml(event.to_peer_mac)}`,
  ].join('<br>')
}

export function buildMeshRssiTooltip(point?: MeshChartPoint, event?: MeshChartEvent): string {
  if (!point) {
    return `<div class="mesh-rssi-tooltip" style="${TOOLTIP_STYLE}">采样时间：${escapeMeshTooltipHtml(event?.point_timestamp || event?.timestamp)}${buildSwitchSection(event)}</div>`
  }
  return [
    `<div class="mesh-rssi-tooltip" style="${TOOLTIP_STYLE}">`,
    `采样时间：${escapeMeshTooltipHtml(point.timestamp)}`,
    divider(),
    '<strong>主链路</strong>',
    `当前轨旁 AP：${escapeMeshTooltipHtml(point.peer_ap_name)}`,
    `当前轨旁 AP MAC：${escapeMeshTooltipHtml(point.peer_ap_mac)}`,
    `MR / 轨旁 AP 接收信号：${metric(point.local_rssi)} / ${metric(point.peer_rssi)}`,
    `归属站点 / 区间：${escapeMeshTooltipHtml(point.station)} / ${escapeMeshTooltipHtml(point.section)}`,
    `建链持续时间：${metric(point.segment_duration_seconds, ' s')}`,
    buildBackupSection(point.backups || []),
    buildSwitchSection(event),
    '</div>',
  ].join('<br>')
}

export function buildMeshSwitchPointTooltip(
  event: MeshSwitchEvent | undefined,
  seriesName: string,
  value: number | null | undefined,
): string {
  return [
    `<div class="mesh-switch-tooltip" style="${TOOLTIP_STYLE}">`,
    `时间：${escapeMeshTooltipHtml(event?.timestamp)}`,
    `${escapeMeshTooltipHtml(seriesName || '切换 RSSI')}：${metric(value)}`,
    `原 AP → 目标 AP：${escapeMeshTooltipHtml(event?.from_ap_name || event?.from_peer_mac)} → ${escapeMeshTooltipHtml(event?.to_ap_name || event?.to_peer_mac)}`,
    `Radio：${event?.local_radio == null ? '—' : escapeMeshTooltipHtml(event.local_radio)}`,
    '</div>',
  ].join('<br>')
}
