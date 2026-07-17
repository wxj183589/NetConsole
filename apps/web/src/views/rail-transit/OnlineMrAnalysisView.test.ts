import { describe, expect, it } from 'vitest'

import source from './OnlineMrAnalysisView.vue?raw'

describe('Online MR analysis view', () => {
  it('queries real metrics and timeline and delivers a recoverable report artifact', () => {
    expect(source).toContain('queryOnlineMrMetrics')
    expect(source).toContain('queryOnlineMrTimeline')
    expect(source).toContain('RSSI')
    expect(source).toContain('Channel Busy')
    expect(source).toContain('fping RTT')
    expect(source).toContain('丢包')
    expect(source).toContain('iPerf')
    expect(source).toContain('exportOnlineMrReport')
    expect(source).toContain('recoverRailTransitTasks')
    expect(source).toContain("openTaskWindow({ module: 'rail'")
    expect(source).not.toContain('cancelRailTransitTask')
    expect(source).not.toContain('downloadBackendResource')
    expect(source).not.toMatch(/READ ONLY|只读|迁移/)
  })
})
