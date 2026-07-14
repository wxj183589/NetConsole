import { describe, expect, it } from 'vitest'

import source from './JobCenterView.vue?raw'

describe('Job Center read-only view', () => {
  it('exposes read-only detail, Online MR association and lazy logs', () => {
    expect(source).toContain('只读任务监控')
    expect(source).toContain('查看 Online MR 实时展示')
    expect(source).toContain('显示日志')
    expect(source).not.toContain('停止任务')
    expect(source).not.toContain('删除任务')
    expect(source).not.toContain('重试任务')
  })
})
