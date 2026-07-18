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

  it('shows both trackside AP receive-power facts without redundant status columns', () => {
    expect(source.match(/meshColumn\('ap_rx_power', '轨旁 AP 室外侧收光'/g)).toHaveLength(2)
    expect(source.match(/meshColumn\('switch_rx_power', '轨旁 AP 室内侧收光'/g)).toHaveLength(2)
    expect(source).not.toContain('label="链路状态"')
    expect(source).not.toContain('label="轨旁 AP 状态"')
    expect(source).not.toContain('label="光衰状态"')
    expect(source).not.toContain('label="信道"')
    expect(source).not.toContain('label="带宽"')
    expect(source).not.toContain('row.link_status')
    expect(source).not.toContain('row.ap_online_status')
    expect(source).not.toContain('row.optical_status')
  })

  it('uses one shared table contract for monitoring, snapshots and detail history', () => {
    for (const tableId of ['ac-mesh-mrs', 'ac-mesh-current-links', 'ac-mesh-snapshots', 'ac-mesh-detail-links', 'ac-mesh-detail-events']) {
      expect(source).toContain(`table-id="${tableId}"`)
    }
    expect(source).not.toContain('<el-table')
  })
})
