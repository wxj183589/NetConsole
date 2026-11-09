import type { MeshBusinessMetricLine } from './meshBusinessMetrics'

const escape = (value: unknown): string => String(value ?? '暂无数据').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!))
export const counterStatus: Record<string, string> = { valid: '有效增量', first: '首个采样，无上次数据', missing: '采样缺失', reset: '计数器重置或回绕', invalid_interval: '采样时间重复或倒序', gap: '采样间隔过长', link_changed: '链路已切换' }
export function meshMonitorTooltip(lines: MeshBusinessMetricLine[], params: any, unit = '', selectedSample?: Record<string, unknown> | null): string {
  const input = Array.isArray(params) ? params : [params]
  const original = selectedSample || input.find(item => item?.data?.sample)?.data.sample
  const values = original ? lines.map(line => {
    const field = line.sampleField || ''
    const value = original[field === 'local_rssi' ? 'local_rssi_db' : field === 'peer_rssi' ? 'peer_rssi_db' : field] ?? original[field]
    return { seriesId: line.key, data: { sample: original, value: [original.timestamp, value] } }
  }) : input
  const sample = values.find(item => item?.data?.sample)?.data.sample
  if (!sample) return '暂无有效采样'
  const header = `<strong>${escape(sample.timestamp)}</strong><div>${escape(sample.peer_ap_name || '未匹配 AP')} · ${escape(sample.peer_ap_mac || sample.peer_mac || '暂无 AP 地址')}</div>`
  const groups = new Map<string, { label: string; local?: any; peer?: any; counter: boolean }>()
  for (const item of values) {
    const line = lines.find(line => line.key === item.seriesId) || lines.find(line => line.label === item.seriesName)
    if (!line) continue
    const key = line.key.replace(/_(local|peer)$/, '')
    const group = groups.get(key) || { label: line.label.replace(/^(本端|对端)\s*/, ''), counter: Boolean(line.counterField) }
    group[line.side] = line.counterField ? item.data?.sample?.counter_samples?.[line.counterField] : item.data?.value?.[1]
    groups.set(key, group)
  }
  const blocks = [...groups.values()].map(group => {
    const cell = (value: unknown) => `<td style="text-align:right;white-space:normal;max-width:140px">${escape(value)}</td>`
    const row = (label: string, local: unknown, peer: unknown) => `<tr><td>${label}</td>${cell(local)}${cell(peer)}</tr>`
    const rows = group.counter ? [
      row('当前累计值', group.local?.current, group.peer?.current),
      row('上次累计值', group.local?.previous, group.peer?.previous),
      row('区间增量', group.local?.delta, group.peer?.delta),
      row('实际间隔（秒）', group.local?.interval_seconds, group.peer?.interval_seconds),
      row('每秒速率（次/s）', group.local?.per_second, group.peer?.per_second),
      row('状态', counterStatus[group.local?.status || 'missing'], counterStatus[group.peer?.status || 'missing']),
    ].join('') : row('当前值', group.local == null ? null : `${group.local}${unit}`, group.peer == null ? null : `${group.peer}${unit}`)
    return `<div><strong>${escape(group.label)}</strong><table style="width:100%;border-spacing:7px 2px;text-align:left;line-height:19px"><thead><tr><th>项目</th><th>本端</th><th>对端</th></tr></thead><tbody>${rows}</tbody></table></div>`
  })
  return `${header}<div style="display:flex;gap:14px;margin-top:5px">${blocks.join('')}</div>`
}
