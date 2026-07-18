import { describe, expect, it } from 'vitest'

import source from './DeviceDetailView.vue?raw'

describe('DeviceDetailView layout', () => {
  it('让完整详情页按可用视口高度伸展', () => {
    expect(source).toContain('display: flex')
    expect(source).toContain('flex-direction: column')
    expect(source).toContain('min-height: calc(100dvh - var(--nc-shell-header-height)')
    expect(source).toContain('.device-detail-page :deep(.device-detail-panel) { flex: 1; min-height: 0; }')
    expect(source).not.toContain('max-width: 1720px')
  })
})
