import { describe, expect, it } from 'vitest'

import source from './AcManagementView.vue?raw'

describe('AC Management resource view', () => {
  it('shows real refresh, connection record, radio fields, optical relation and config diff', () => {
    expect(source).toContain('更新 FIT-AP 资源')
    expect(source).toContain('更新 AC 信息')
    expect(source).toContain('打开 AC Web')
    expect(source).toContain('getPlatformAdapter().openExternalUrl')
    expect(source).toContain("getRuntimeConfig().hostType === 'electron'")
    expect(source).toContain('深度更新')
    expect(source).toContain('更新光衰')
    expect(source).toContain('批量删除')
    expect(source).toContain('导入 AP 元数据')
    expect(source).toContain('保存元数据')
    expect(source).toContain("openHistory('radio')")
    expect(source).toContain("openHistory('lldp')")
    expect(source).toContain("openHistory('optical')")
    expect(source).toContain('getAcApHistory')
    expect(source).toContain('.csv,.xlsx')
    expect(source).toContain('选择本页')
    expect(source).toContain('反选本页')
    expect(source).toContain('ElMessageBox.confirm')
    expect(source).toContain('打开任务窗口')
    expect(source).toContain("openTaskWindow({ module: 'ac'")
    expect(source).toContain('FIT-AP 资源')
    expect(source).toContain('AC 连接记录')
    expect(source).toContain('Mesh Radio 1 / 2')
    expect(source).toContain('利用率 (%)')
    expect(source).toContain('客户端')
    expect(source).toContain('未关联 AP 离线')
    expect(source).toContain('配置采集与对比')
    expect(source).not.toContain('label="FIT-AP 光衰"')
    expect(source).not.toContain('Radio 3')
    expect(source).not.toContain('client_count')
    expect(source).not.toContain('序列号')
    expect(source).not.toContain('固化')
    expect(source).not.toContain('save force')
  })

  it('places rail metadata after AP-side receive optical attenuation', () => {
    const orderedColumns = [
      "key: 'optical_rx_power', label: 'AP侧收光光衰'",
      "key: 'station', label: '归属站点'",
      "key: 'section', label: '归属区间'",
      "key: 'mileage', label: '里程'",
      "key: 'direction', label: '线路方向'",
    ]

    const positions = orderedColumns.map((column) => source.indexOf(column))
    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((left, right) => left - right))
  })

  it('uses topology ordering, short interface display, and keeps LLDP station inference advisory', () => {
    expect(source).toContain("sort_by: 'topology'")
    expect(source).toContain('displayInterfaceName')
    expect(source).toContain("station_source === 'lldp_switch_suggestion'")
    expect(source).toContain('根据 LLDP 邻居交换机站点建议，保存后才写入')
  })

  it('stops polling when hidden and exposes no unapproved device write action', () => {
    expect(source).toContain('document.hidden')
    expect(source).toContain('store.stopPolling()')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('taskStore.releasePolling(pollingConsumer)')
    expect(source).not.toContain('停止任务')
    expect(source).not.toContain('cancelRefreshTask')
    expect(source).not.toContain('下发')
  })
})
