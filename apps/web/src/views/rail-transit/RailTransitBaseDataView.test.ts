import { describe, expect, it } from 'vitest'

import source from './RailTransitBaseDataView.vue?raw'

describe('Rail Transit base data read-only view', () => {
  it('shows all read-only domains, server pagination and preview safety notice', () => {
    expect(source).toContain('基础资料总览')
    expect(source).toContain('站点与区间')
    expect(source).toContain('轨旁 AP')
    expect(source).toContain('列车与车载 MR')
    expect(source).toContain('数据质量问题')
    expect(source).toContain('关联运行状态')
    expect(source).toContain('当前仅支持校验和合并预览。正式写入功能默认关闭。')
    expect(source).toContain('只看阻断问题')
    expect(source).toContain('待人工确认')
    expect(source).toContain('CREATE')
    expect(source).toContain('CONFLICT')
    expect(source).toContain('字段差异')
    expect(source).toContain('正式写入未启用')
    expect(source).toMatch(/<el-button type="primary" disabled>正式写入未启用/)
    expect(source).toContain('<el-pagination')
    expect(source).toContain('handleVisibility')
    expect(source).toContain('store.stopPolling()')
  })

  it('does not expose persistence, deletion or credential UI', () => {
    expect(source).not.toMatch(/>\s*(确认导入|应用|覆盖数据库|删除)\s*<\/el-button>/)
    expect(source).not.toContain('密码')
    expect(source).not.toContain('username')
    expect(source).not.toContain('client_count')
  })
})
