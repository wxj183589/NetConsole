import { describe, expect, it } from 'vitest'

import source from './JobCenterView.vue?raw'

describe('Job Center unified task view', () => {
  it('exposes filters, capabilities and lazy logs', () => {
    expect(source).toContain('统一任务中心')
    expect(source).toContain('查看 Online MR 实时展示')
    expect(source).toContain('显示日志')
    expect(source).toContain('停止 / 取消')
    expect(source).toContain('Artifact 下载')
    expect(source).toContain('moduleFilter')
  })
})
