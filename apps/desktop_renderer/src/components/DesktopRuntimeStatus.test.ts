import { describe, expect, it } from 'vitest'

import source from './DesktopRuntimeStatus.vue?raw'

describe('DesktopRuntimeStatus runtime binding state', () => {
  it('uses the renderer-bound runtime status instead of raw supervisor ready events', () => {
    expect(source).toContain('getPlatformRuntimeStatus()')
    expect(source).toContain('onPlatformRuntimeStatusChanged')
    expect(source).toContain('正在连接服务')
    expect(source).not.toContain('runtime.onBackendStatusChanged')
  })
})
