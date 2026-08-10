import type { MeshChartBackupLink, MeshChartEvent, MeshChartPoint, MeshRssiZeroRun, MeshSwitchEvent } from '../../types/meshAnalysis'
import { t } from '../../i18n/runtime'

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

function linkCount(value: number | null | undefined): string {
  if (value == null) return 'LinkCnt：—'
  return value === 2 ? 'LinkCnt：2（△ 三角链路）' : `LinkCnt：${escapeMeshTooltipHtml(value)}`
}

export function buildBackupSection(backups: readonly MeshChartBackupLink[]): string {
  if (!backups.length) return `${divider()}<strong>备份链路：无</strong>`
  const rows = backups.map((item, index) => [
    `${index + 1}. ${escapeMeshTooltipHtml(item.peer_ap_name || item.peer_mac)}`,
    `AP MAC：${escapeMeshTooltipHtml(item.peer_ap_mac)}`,
    `MR / 轨旁 AP 接收信号：${metric(item.local_rssi)} / ${metric(item.peer_rssi)}`,
    linkCount(item.link_count),
    `Radio：${item.local_radio == null ? '—' : `radio${escapeMeshTooltipHtml(item.local_radio)}`}`,
    `归属站点 / 区间：${escapeMeshTooltipHtml(item.station)} / ${escapeMeshTooltipHtml(item.section)}`,
  ].join('<br>'))
  return `${divider()}<strong>备份链路</strong><br>${rows.join('<br>')}`
}

export function buildSwitchSection(event?: MeshChartEvent): string {
  if (!event) return ''
  const rows = [
    divider(),
    '<strong>切换事件</strong>',
    `切换事件时间：${escapeMeshTooltipHtml(event.timestamp)}`,
    `切出：${escapeMeshTooltipHtml(event.from_ap_name)} / ${escapeMeshTooltipHtml(event.from_peer_mac)}`,
    `切入：${escapeMeshTooltipHtml(event.to_ap_name)} / ${escapeMeshTooltipHtml(event.to_peer_mac)}`,
  ]
  if (event.before_rssi != null || event.after_rssi != null) {
    rows.push(`切出 / 切入 RSSI：${metric(event.before_rssi)} / ${metric(event.after_rssi)}`)
  }
  if (event.from_station || event.from_section || event.to_station || event.to_section) {
    rows.push(`切出归属：${escapeMeshTooltipHtml(event.from_station)} / ${escapeMeshTooltipHtml(event.from_section)}`)
    rows.push(`切入归属：${escapeMeshTooltipHtml(event.to_station)} / ${escapeMeshTooltipHtml(event.to_section)}`)
  }
  if (event.reason) rows.push(`切换原因：${escapeMeshTooltipHtml(event.reason)}`)
  if (event.render_aligned && event.render_point_timestamp) {
    rows.push(`对齐采样时间：${escapeMeshTooltipHtml(event.render_point_timestamp)}`)
  } else {
    rows.push('该切换事件无有效 RSSI 点，未作为折线节点显示。')
  }
  return rows.join('<br>')
}

export function buildMeshRssiTooltip(point?: MeshChartPoint, event?: MeshChartEvent, pointerTime?: string): string {
  if (!point) {
    return `<div class="mesh-rssi-tooltip" style="${TOOLTIP_STYLE}">采样时间：${escapeMeshTooltipHtml(pointerTime || event?.render_point_timestamp || event?.point_timestamp || event?.timestamp)}${pointerTime ? '<br>当前时刻无有效采样' : ''}${buildSwitchSection(event)}</div>`
  }
  return [
    `<div class="mesh-rssi-tooltip" style="${TOOLTIP_STYLE}">`,
    `采样时间：${escapeMeshTooltipHtml(point.timestamp)}`,
    divider(),
    '<strong>主链路</strong>',
    `当前轨旁 AP：${escapeMeshTooltipHtml(point.peer_ap_name)}`,
    `当前轨旁 AP MAC：${escapeMeshTooltipHtml(point.peer_ap_mac)}`,
    `MR / 轨旁 AP 接收信号：${metric(point.local_rssi)} / ${metric(point.peer_rssi)}`,
    linkCount(point.link_count),
    ...(point.local_rssi_zero_run
      ? [
          '<strong>状态：持续无有效 RSSI</strong>',
          `开始时间：${escapeMeshTooltipHtml(point.local_rssi_zero_run.start_time)}`,
          `结束时间：${escapeMeshTooltipHtml(point.local_rssi_zero_run.end_time)}`,
          `持续时间：${(point.local_rssi_zero_run.duration_ms / 1_000).toFixed(3)} s`,
        ]
      : []),
    `归属站点 / 区间：${escapeMeshTooltipHtml(point.station)} / ${escapeMeshTooltipHtml(point.section)}`,
    `建链持续时间：${metric(point.segment_duration_seconds, ' s')}`,
    buildBackupSection(point.backups || []),
    buildSwitchSection(event),
    '</div>',
  ].join('<br>')
}

export function buildMeshRssiQuickTooltip(point?: MeshChartPoint, event?: MeshChartEvent, pointerTime?: string): string {
  const time = pointerTime || point?.timestamp || event?.render_point_timestamp || event?.timestamp
  const rows = [
    `<div class="mesh-rssi-tooltip mesh-rssi-tooltip--quick" style="max-width:220px;white-space:normal;line-height:1.45">`,
    escapeMeshTooltipHtml(time),
  ]
  if (point) {
    rows.push(`RSSI ${metric(point.local_rssi, ' dBm')}`)
    rows.push(`AP ${escapeMeshTooltipHtml(point.peer_ap_name || point.peer_mac)}`)
    rows.push(linkCount(point.link_count))
  } else if (event) {
    rows.push(escapeMeshTooltipHtml(event.to_ap_name || event.to_peer_mac || '切换事件'))
  } else {
    rows.push('当前时刻无有效采样')
  }
  rows.push('</div>')
  return rows.join('<br>')
}

export function buildMeshRssiZeroRunTooltip(
  point: MeshChartPoint,
  zeroRun: MeshRssiZeroRun,
  pointerTime?: string,
  seriesName?: string,
): string {
  return [
    `<div class="mesh-rssi-tooltip" style="${TOOLTIP_STYLE}">`,
    `采样时间：${escapeMeshTooltipHtml(pointerTime || point.timestamp)}`,
    divider(),
    `<strong>${t('mesh.rssi.zero.heading', 'RSSI 状态')}</strong>`,
    `${t('mesh.rssi.zero.status', '状态：持续无有效 RSSI')}`,
    `${t('mesh.rssi.zero.metric', '指标')}：${escapeMeshTooltipHtml(seriesName)}`,
    `${t('mesh.rssi.zero.start', '开始时间')}：${escapeMeshTooltipHtml(zeroRun.start_time)}`,
    `${t('mesh.rssi.zero.end', '结束时间')}：${escapeMeshTooltipHtml(zeroRun.end_time)}`,
    `${t('mesh.rssi.zero.duration', '持续时间')}：${(zeroRun.duration_ms / 1_000).toFixed(3)} s`,
    `链路角色：${escapeMeshTooltipHtml(point.link_state)}`,
    `当前轨旁 AP：${escapeMeshTooltipHtml(point.peer_ap_name)}`,
    `当前轨旁 AP MAC：${escapeMeshTooltipHtml(point.peer_ap_mac)}`,
    `Radio：${point.local_radio == null ? '—' : escapeMeshTooltipHtml(point.local_radio)}`,
    linkCount(point.link_count),
    `归属站点 / 区间：${escapeMeshTooltipHtml(point.station)} / ${escapeMeshTooltipHtml(point.section)}`,
    '</div>',
  ].join('<br>')
}

export function buildMeshSwitchPointTooltip(
  event: MeshSwitchEvent | undefined,
  seriesName: string,
  value: number | null | undefined,
  linkCountValue?: number | null,
): string {
  return [
    `<div class="mesh-switch-tooltip" style="${TOOLTIP_STYLE}">`,
    `时间：${escapeMeshTooltipHtml(event?.timestamp)}`,
    `${escapeMeshTooltipHtml(seriesName || '切换 RSSI')}：${metric(value)}`,
    `原 AP → 目标 AP：${escapeMeshTooltipHtml(event?.from_ap_name || event?.from_peer_mac)} → ${escapeMeshTooltipHtml(event?.to_ap_name || event?.to_peer_mac)}`,
    `Radio：${event?.local_radio == null ? '—' : escapeMeshTooltipHtml(event.local_radio)}`,
    linkCount(linkCountValue),
    '</div>',
  ].join('<br>')
}
