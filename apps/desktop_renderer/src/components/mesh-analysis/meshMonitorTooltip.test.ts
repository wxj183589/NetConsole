// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { buildMeshBusinessMetricGroups, type MeshBusinessMetricSample } from './meshBusinessMetrics'
import { meshMonitorTooltip } from './meshMonitorTooltip'

const sample: MeshBusinessMetricSample = {
  timestamp: '2026-11-09 10:00:00.034', peer_ap_name: '轨旁 AP 01', peer_ap_mac: 'bc:5a:34:57:62:c0', local_rssi: -42, peer_rssi: -48, local_cpu_percent: 12, peer_cpu_percent: 22,
  counter_samples: Object.fromEntries(['local_tx', 'peer_tx', 'local_rx', 'peer_rx', 'local_retry', 'peer_retry', 'local_err', 'peer_err', 'local_tx_garp', 'peer_rx_garp', 'local_tx_mul_join', 'peer_rx_mul_join'].map((key, index) => [key, { current: 100 + index * 2, previous: 100, delta: index * 2, interval_seconds: 0.5, per_second: index * 4, status: 'valid' }])),
}
function tooltip(key: Parameters<typeof buildMeshBusinessMetricGroups>[1], input = sample, unit = '') {
  const lines = buildMeshBusinessMetricGroups([input], key)[0]!.lines
  const params = lines.map(line => ({ seriesId: line.key, seriesName: line.label, data: line.data[0] }))
  const element = document.createElement('div')
  element.innerHTML = meshMonitorTooltip(lines, params, unit)
  return { element, lines, params }
}

describe('mesh monitor business tooltip', () => {
  it('uses the selected original record when downsampled series point is different', () => {
    const { lines, params } = tooltip('tx_rx')
    const selected = { ...sample, timestamp: '2026-11-09 10:00:00.068', peer_ap_name: '选中 AP', counter_samples: { local_tx: { current: 9988, previous: 9960, delta: 28, interval_seconds: 0.034, per_second: 823.529, status: 'valid' } } }
    const html = meshMonitorTooltip(lines, params, '次/s', selected)
    expect(html).toContain(selected.timestamp)
    expect(html).toContain('选中 AP')
    expect(html).toContain('9988')
    expect(html).toContain('823.529')
    expect(html).not.toContain(sample.timestamp)
    expect(html).not.toContain('轨旁 AP 01')
    expect(html).toContain('暂无数据')
  })

  it('uses raw RSSI fields and requested units for a selected original sample', () => {
    const { lines, params } = tooltip('rssi')
    const html = meshMonitorTooltip(lines, params, 'dBm', { timestamp: '2026-11-09 10:00:01.000', local_rssi_db: -88, peer_rssi_db: -90 })
    expect(html).toContain('-88dBm')
    expect(html).toContain('-90dBm')
    expect(html).not.toContain('-42')
  })
  it.each([['rssi', 'dB', '-42', '-48'], ['cpu', '%', '12', '22']] as const)('shows %s values for both ends with one AP identity', (key, unit, local, peer) => {
    const text = tooltip(key, sample, unit).element.textContent!
    expect(text).toContain(sample.timestamp)
    expect(text.split('轨旁 AP 01')).toHaveLength(2)
    expect(text.split('bc:5a:34:57:62:c0')).toHaveLength(2)
    for (const value of ['本端', '对端', local, peer, unit]) expect(text).toContain(value)
    expect(text).not.toMatch(/身份来源|解析规则|匹配规则|来源行号|record_id|source_file/)
  })

  it.each(['tx_rx', 'retry', 'error', 'control'] as const)('shows %s both-end counter values, deltas, actual intervals and rates', key => {
    const { element, lines } = tooltip(key)
    const text = element.textContent!
    for (const label of ['当前累计值', '上次累计值', '区间增量', '实际间隔', '每秒速率', '状态', '本端', '对端']) expect(text).toContain(label)
    for (const line of lines) {
      const metadata = sample.counter_samples![line.counterField!]!
      for (const field of ['current', 'previous', 'delta', 'interval_seconds', 'per_second'] as const) expect(text).toContain(String(metadata[field]))
    }
    expect(text).toContain('有效增量')
  })

  it.each(['tx_rx', 'retry', 'error', 'control'] as const)('lays out %s as six rows with parallel local and peer columns', key => {
    const { element, lines } = tooltip(key)
    const tables = [...element.querySelectorAll('table')]
    expect(tables).toHaveLength(lines.length / 2)
    for (const [index, table] of tables.entries()) {
      expect([...table.querySelectorAll('thead th')].map(cell => cell.textContent)).toEqual(['项目', '本端', '对端'])
      const local = sample.counter_samples![lines[index * 2]!.counterField!]!
      const peer = sample.counter_samples![lines[index * 2 + 1]!.counterField!]!
      const expected = [
        ['当前累计值', String(local.current), String(peer.current)],
        ['上次累计值', String(local.previous), String(peer.previous)],
        ['区间增量', String(local.delta), String(peer.delta)],
        ['实际间隔（秒）', String(local.interval_seconds), String(peer.interval_seconds)],
        ['每秒速率（次/s）', String(local.per_second), String(peer.per_second)],
        ['状态', '有效增量', '有效增量'],
      ]
      expect([...table.querySelectorAll('tbody tr')].map(row => [...row.querySelectorAll('td')].map(cell => cell.textContent))).toEqual(expected)
    }
  })

  it.each([['first', '首个采样'], ['reset', '计数器重置'], ['gap', '采样间隔过长'], ['link_changed', '链路已切换'], ['invalid_interval', '采样时间重复或倒序']] as const)('explains a %s counter without inventing values', (status, reason) => {
    const input = { ...sample, counter_samples: { local_retry: { current: 12, previous: null, delta: null, interval_seconds: null, per_second: null, status } } }
    const text = tooltip('retry', input).element.textContent!
    expect(text).toContain(reason)
    expect(text).toContain('暂无数据')
    expect(text).not.toMatch(/undefined|NaN/)
  })

  it('escapes AP names and addresses rather than injecting markup', () => {
    const { element } = tooltip('rssi', { ...sample, peer_ap_name: '<img src=x onerror=alert(1)>', peer_ap_mac: '<script>alert(1)</script>' })
    expect(element.querySelector('img,script')).toBeNull()
    expect(element.textContent).toContain('<img src=x onerror=alert(1)>')
    expect(element.textContent).toContain('<script>alert(1)</script>')
  })

  it('handles missing samples and unknown series without exposing internal identifiers', () => {
    expect(meshMonitorTooltip([], [])).toBe('暂无有效采样')
    const { lines } = tooltip('cpu')
    const html = meshMonitorTooltip(lines, { seriesId: 'internal_series', data: { sample, value: [sample.timestamp, 99] } })
    expect(html).toContain('轨旁 AP 01')
    expect(html).not.toContain('internal_series')
  })

  it.each([['rssi', -71, -79, 'dB'], ['cpu', 67, 83, '%']] as const)('uses the selected raw %s sample instead of a different downsampled AP and time', (key, local, peer, unit) => {
    const { lines, params } = tooltip(key)
    const selected = { timestamp: '2026-11-09 11:22:33.789', peer_ap_name: 'RAW SELECTED AP', peer_ap_mac: '11:22:33:44:55:66', local_rssi_db: local, peer_rssi_db: peer, local_cpu_percent: local, peer_cpu_percent: peer }
    const element = document.createElement('div')
    element.innerHTML = meshMonitorTooltip(lines, params, unit, selected)
    const text = element.textContent!
    expect(text).toContain(selected.timestamp)
    expect(text).toContain(selected.peer_ap_name)
    expect(text).toContain(selected.peer_ap_mac)
    expect([...element.querySelectorAll('tbody td')].map(cell => cell.textContent)).toEqual(['当前值', `${local}${unit}`, `${peer}${unit}`])
    for (const obsolete of [sample.timestamp, String(sample.peer_ap_name), String(sample.peer_ap_mac)]) expect(text).not.toContain(obsolete)
  })

  it('uses all twelve selected raw counter metadata entries without mixing downsampled samples', () => {
    const lines = buildMeshBusinessMetricGroups([sample], 'counters')[0]!.lines
    const params = lines.map((line, index) => ({ seriesId: line.key, data: { sample: { ...sample, timestamp: `OLD-${index}`, peer_ap_name: `OLD-AP-${index}` }, value: [sample.timestamp, 999999] } }))
    const counter_samples = Object.fromEntries(lines.map((line, index) => [line.counterField!, { current: 9000 + index, previous: 8000 + index, delta: 1000, interval_seconds: 0.037 + index / 1000, per_second: 1000 / (0.037 + index / 1000), status: 'valid' }]))
    const selected = { timestamp: '2026-11-09 12:34:56.987', peer_ap_name: 'RAW COUNTER AP', peer_ap_mac: 'aa:bb:cc:11:22:33', counter_samples }
    const element = document.createElement('div')
    element.innerHTML = meshMonitorTooltip(lines, params, '次/s', selected)
    const text = element.textContent!
    expect(text).toContain(selected.timestamp)
    expect(text).toContain(selected.peer_ap_name)
    expect(text).not.toMatch(/OLD-|轨旁 AP 01|2026-11-09 10:00/)
    expect([...element.querySelectorAll('td')].some(cell => cell.textContent === '999999')).toBe(false)
    const tables = [...element.querySelectorAll('table')]
    expect(tables).toHaveLength(6)
    for (const [index, table] of tables.entries()) {
      const local = counter_samples[lines[index * 2]!.counterField!]!
      const peer = counter_samples[lines[index * 2 + 1]!.counterField!]!
      expect([...table.querySelectorAll('tbody tr')].map(row => [...row.querySelectorAll('td')].slice(1).map(cell => cell.textContent))).toEqual([
        [String(local.current), String(peer.current)], [String(local.previous), String(peer.previous)],
        [String(local.delta), String(peer.delta)], [String(local.interval_seconds), String(peer.interval_seconds)],
        [String(local.per_second), String(peer.per_second)], ['有效增量', '有效增量'],
      ])
    }
  })

  it('does not fill missing selected raw fields from a downsampled sample', () => {
    const { lines, params } = tooltip('retry')
    const element = document.createElement('div')
    element.innerHTML = meshMonitorTooltip(lines, params, '次/s', { timestamp: 'RAW-MISSING', peer_ap_name: 'RAW-MISSING-AP' })
    expect([...element.querySelectorAll('tbody tr')].slice(0, 5).every(row => [...row.querySelectorAll('td')].slice(1).every(cell => cell.textContent === '暂无数据'))).toBe(true)
    expect(element.textContent).not.toContain('有效增量')
    expect(element.textContent).not.toContain('轨旁 AP 01')
  })
})
