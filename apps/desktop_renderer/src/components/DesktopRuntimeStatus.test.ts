import { describe, expect, it } from 'vitest'

import source from './DesktopRuntimeStatus.vue?raw'

describe('DesktopRuntimeStatus runtime binding state', () => {
  it('uses the renderer-bound runtime status instead of raw supervisor ready events', () => {
    expect(source).toContain('getPlatformRuntimeStatus()')
    expect(source).toContain('onPlatformRuntimeStatusChanged')
    expect(source).toContain('Backend 重新连接中')
    expect(source).not.toContain('runtime.onBackendStatusChanged')
  })
})
