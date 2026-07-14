import { describe, expect, it } from 'vitest'

import source from './TrainCommunicationView.vue?raw'

describe('train communication Online MR control integration', () => {
  it('keeps the dashboard out of control and mounts control only for selected formal MR', () => {
    expect(source).toContain("import OnlineMrLocalControl")
    expect(source).toContain('<OnlineMrLocalControl')
    expect(source).toContain('store.selectedMr')
    expect(source).toContain(':site-id="store.summary?.site_id')
    expect(source).toContain(':mr="store.selectedMr.mr"')
  })

  it('describes a local controlled entry instead of remote execution', () => {
    expect(source).toContain('本地主程序 WebHost')
    expect(source).toContain('LOCAL Online MR')
    expect(source).not.toMatch(/Agent 启动|Agent 停止|强制停止|删除会话|任意命令/)
  })
})
