import { describe, expect, it } from 'vitest'

import source from './MeshAnalysisView.vue?raw'

describe('Mesh analysis read-only view', () => {
  it('shows persisted results without exposing parser or write actions', () => {
    expect(source).toContain('Mesh 原始日志分析')
    expect(source).toContain('主 / 备链路')
    expect(source).toContain('主链路时间线')
    expect(source).toContain('切换事件')
    expect(source).toContain('RSSI')
    expect(source).toContain('空口繁忙度')
    expect(source).toContain('fping / iPerf 对齐')
    expect(source).toContain('报告与来源')
    expect(source).toContain('<el-pagination')
    expect(source).not.toContain('peer_radio_mac')
    expect(source).not.toContain('归属来源')
    expect(source).not.toMatch(/>s*(重新分析|删除|生成报告|导出)s*</)
  })

  it('keeps raw tail collapsed behind an explicit action and stops polling on unmount', () => {
    expect(source).toContain('tail_available')
    expect(source).toContain('loadRawTail')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('clearTimeout')
    expect(source).toContain("document.visibilityState === 'visible'")
    expect(source).toContain('failureCount >= 3 ? 90_000 : 30_000')
    expect(source).not.toContain('setInterval')
    expect(source).not.toContain('absolute_path')
  })
})
