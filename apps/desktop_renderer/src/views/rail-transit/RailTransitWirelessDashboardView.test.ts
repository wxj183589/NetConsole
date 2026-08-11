import { describe, expect, it } from 'vitest'

import source from './RailTransitWirelessDashboardView.vue?raw'

describe('rail transit wireless dashboard', () => {
  it('is a read-only aggregation view with domain-specific sections', () => {
    expect(source).toContain('轨道交通无线综合看板')
    expect(source).toContain('基础设施状态')
    expect(source).toContain('在线列车通信')
    expect(source).toContain('CT / TC 独立展示')
    expect(source).toContain('告警与异常')
    expect(source).toContain('数据时效')
    expect(source).toContain('最近任务')
    expect(source).toContain('Mesh 离线分析')
    expect(source).toContain('Agent 状态')
    expect(source).not.toContain('客户端数')
    expect(source).not.toMatch(/>\s*(启动采集|停止采集|刷新 AC|删除|导入|生成报告)\s*</)
  })

  it('uses layered timeout polling and keeps previous data after failures', () => {
    expect(source).toContain('active.value ? 2_000 : 10_000')
    expect(source).toContain('failureCount.value >= 3 ? 30_000')
    expect(source).toContain('due.infrastructure = now + 30_000')
    expect(source).toContain('due.mesh = now + 5_000')
    expect(source).toContain('due.alerts = now + 5_000')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain("document.visibilityState !== 'visible'")
    expect(source).toContain('已保留最后成功数据')
    expect(source).toContain('Promise.allSettled')
    expect(source).toContain("label: '汇总指标'")
    expect(source).toContain("label: '列车通信'")
    expect(source).toContain("label: '最近任务与会话'")
    expect(source).toContain('部分看板数据刷新失败')
    expect(source).not.toContain('const core = await Promise.all')
    expect(source).not.toContain('setInterval')
  })

  it('does not render unloaded metrics as real zero values', () => {
    expect(source).toContain("return data.value ? (value ?? 0) : '—'")
    expect(source).toContain("s ? `${s.registered_trains} / ${s.registered_mrs}` : '—'")
    expect(source).toContain("data ? `${data.alerts.total} 条` : '—'")
  })

  it('uses typed compact data tables with stable dashboard identities', () => {
    expect(source).toContain("import NcDataTable")
    expect(source).toContain('NcTableColumn<WirelessDashboardAlert>')
    expect(source.match(/<NcDataTable\b/g)).toHaveLength(5)
    expect(source).toContain('table-id="rail-wireless-dashboard-mesh-links"')
    expect(source).toContain('table-id="rail-wireless-dashboard-trains"')
    expect(source).toContain('table-id="rail-wireless-dashboard-alerts"')
    expect(source).toContain('table-id="rail-wireless-dashboard-freshness"')
    expect(source).toContain('table-id="rail-wireless-dashboard-agents"')
    expect(source).toContain("alignmentReason: 'long-text'")
    expect(source).not.toContain('<el-table')
  })
})
