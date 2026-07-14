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

  it('creates a controlled refresh task and stops polling without cancelling it', () => {
    expect(source).toContain('刷新 Mesh-Link')
    expect(source).toContain('store.startRefresh')
    expect(source).toContain('正在刷新 Mesh-Link')
    expect(source).toContain('打开任务详情')
    expect(source).toContain('原始回显')
    expect(source).toContain('document.hidden')
    expect(source).toContain('store.stopPolling()')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('最新 Mesh-Link 原始输出')
    expect(source).not.toContain('display wlan mesh-link')
    expect(source).not.toContain('password')
    expect(source).not.toContain('任意命令')
    expect(source).not.toContain('cancel')
    expect(source).not.toContain('停止采集')
  })
})
