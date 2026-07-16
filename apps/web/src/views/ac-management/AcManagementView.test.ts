import { describe, expect, it } from 'vitest'

import source from './AcManagementView.vue?raw'

describe('AC Management resource view', () => {
  it('shows real refresh, connection record, radio fields, optical relation and config diff', () => {
    expect(source).toContain('更新 FIT-AP 资源')
    expect(source).toContain('更新 AC 信息')
    expect(source).toContain('深度更新')
    expect(source).toContain('更新光衰')
    expect(source).toContain('批量删除')
    expect(source).toContain('选择本页')
    expect(source).toContain('反选本页')
    expect(source).toContain('ElMessageBox.confirm')
    expect(source).toContain('取消任务')
    expect(source).toContain('FIT-AP 资源')
    expect(source).toContain('AC 连接记录')
    expect(source).toContain('Mesh Radio 1 / 2')
    expect(source).toContain('利用率 (%)')
    expect(source).toContain('客户端')
    expect(source).toContain('未关联 AP 离线')
    expect(source).toContain('配置采集与对比')
    expect(source).not.toContain('Radio 3')
    expect(source).not.toContain('client_count')
    expect(source).not.toContain('序列号')
    expect(source).not.toContain('固化')
    expect(source).not.toContain('save force')
  })

  it('stops polling when hidden and exposes no unapproved device write action', () => {
    expect(source).toContain('document.hidden')
    expect(source).toContain('store.stopPolling()')
    expect(source).toContain('onBeforeUnmount')
    expect(source).not.toContain('停止任务')
    expect(source).not.toContain('下发')
  })
})
