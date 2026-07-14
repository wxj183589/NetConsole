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
    expect(source).toContain('保留上次数据')
    expect(source).not.toContain('setInterval')
  })
})
