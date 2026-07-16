import { describe, expect, it } from 'vitest'

import source from './OnlineMrRealtimeView.vue?raw'

describe('Online MR realtime collection view', () => {
  it('provides independent formal MR collection controls and realtime delivery', () => {
    expect(source).toContain('车载 MR 实时收集')
    expect(source).toContain('listTrainCommunications')
    expect(source).toContain('<OnlineMrLocalControl')
    expect(source).toContain('<OnlineMrAgentControlPanel')
    expect(source).toContain('fping/iPerf')
    expect(source).toContain('强停')
    expect(source).toContain('原始日志动态查看')
    expect(source).toContain('会话交付')
    expect(source).not.toMatch(/READ ONLY|只读|仍由 Qt|迁移/)
  })
})
