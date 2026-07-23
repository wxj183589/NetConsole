import { describe, expect, it } from 'vitest'

import source from './MeshRssiChart.vue?raw'

describe('MeshRssiChart', () => {
  it('resizes hidden tabs and releases chart resources', () => {
    expect(source).toContain('new ResizeObserver')
    expect(source).toContain('resizeObserver?.disconnect()')
    expect(source).toContain("window.removeEventListener('resize', handleWindowResize)")
    expect(source).toContain('cancelAnimationFrame(resizeFrame)')
    expect(source).toContain('clientHeight > 0')
    expect(source).toContain('chart?.dispose()')
  })

  it('renders one ACTIVE path series with zoom and preloaded standby context', () => {
    expect(source).toContain('components.LegendComponent')
    expect(source).toContain('createMultiSeriesTimeChartBaseOption')
    expect(source).toContain('buildMeshRssiSeries(props.points, props.showPeer, props.scope)')
    expect(source).toContain('buildMeshRssiTooltip')
    expect(source).toContain('findRenderedSwitchPoint')
    expect(source).toContain('point.local_rssi !== 0')
    expect(source).toContain('value: [point.timestamp, point.local_rssi]')
    expect(source).not.toContain('value: [event.point_timestamp, event.point_rssi]')
    expect(source).toContain('buildMeshLocationBands')
    expect(source).toContain('connectNulls: false')
    expect(source).not.toContain('new Map<string, MeshRssiPoint[]>')
  })
})
