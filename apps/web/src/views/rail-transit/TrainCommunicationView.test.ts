import { describe, expect, it } from 'vitest'

import source from './TrainCommunicationView.vue?raw'

describe('train communication Online MR control integration', () => {
  it('keeps control in selected formal MR and separates LOCAL from AGENT', () => {
    expect(source).toContain("import OnlineMrLocalControl")
    expect(source).toContain("import OnlineMrAgentControlPanel")
    expect(source).toContain('<OnlineMrLocalControl')
    expect(source).toContain('<OnlineMrAgentControlPanel')
    expect(source).toContain('LOCAL 本地执行')
    expect(source).toContain('AGENT 远程执行')
    expect(source).toContain('store.selectedMr')
    expect(source).toContain(':site-id="store.summary?.site_id')
    expect(source).toContain(':mr="store.selectedMr.mr"')
  })

  it('describes controlled execution without destructive actions', () => {
    expect(source).toContain('本地主程序 WebHost')
    expect(source).toContain('LOCAL 与 AGENT Online MR')
    expect(source).not.toMatch(/强制停止|删除会话|任意命令/)
  })
})
