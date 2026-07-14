import { describe, expect, it } from 'vitest'

import source from './TrafficTestView.vue?raw'

describe('existing traffic test view', () => {
  it('keeps fping and iPerf controls while accepting TCP probe history', () => {
    expect(source).toContain('开始高频 Ping')
    expect(source).toContain('开始 iPerf Client')
    expect(source).toContain('启动 iPerf Server')
    expect(source).toContain("['HIGH_FREQUENCY_PING', 'TCP_PORT_TEST']")
  })
})
