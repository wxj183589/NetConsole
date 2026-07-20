import { describe, expect, it } from 'vitest'

import source from './MeshRssiChart.vue?raw'

describe('MeshRssiChart', () => {
  it('resizes hidden tabs and releases chart resources', () => {
    expect(source).toContain('new ResizeObserver')
    expect(source).toContain('resizeObserver?.disconnect()')
    expect(source).toContain("window.removeEventListener('resize', resize)")
    expect(source).toContain('chart?.dispose()')
  })

  it('renders stable AP/Radio series with zoom, legend and complete tooltip context', () => {
    expect(source).toContain('components.LegendComponent')
    expect(source).toContain("type: 'slider'")
    expect(source).toContain("filterMode: 'none'")
    expect(source).toContain('peer_ap_name || point.peer_ap_mac')
    expect(source).toContain('Peer MAC：')
    expect(source).toContain('connectNulls: false')
    expect(source).not.toMatch(/point\.value\s*\?\?\s*0/)
  })
})
