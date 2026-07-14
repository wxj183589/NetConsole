import { describe, expect, it } from 'vitest'

import source from './AcMeshLinkView.vue?raw'

describe('AC Mesh-Link read-only view', () => {
  it('shows MR to trackside AP links without enterprise WLAN semantics', () => {
    expect(source).toContain('Mesh-Link 在线监控')
    expect(source).toContain('车载 MR 与轨旁 FIT-AP')
    expect(source).toContain('Mesh Radio')
    expect(source).toContain('RSSI')
    expect(source).toContain('数据过期')
    expect(source).toContain('无数据')
    expect(source).not.toContain('客户端数')
    expect(source).not.toContain('终端数')
  })

  it('polls stored snapshots only and stops when hidden or unmounted', () => {
    expect(source).toContain('刷新已落盘快照')
    expect(source).toContain('document.hidden')
    expect(source).toContain('store.stopPolling()')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('最新 Mesh-Link 原始输出')
    expect(source).not.toContain('display wlan mesh-link')
    expect(source).not.toContain('开始采集')
    expect(source).not.toContain('停止采集')
  })
})
