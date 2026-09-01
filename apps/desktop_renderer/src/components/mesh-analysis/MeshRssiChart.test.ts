import { describe, expect, it } from 'vitest'

import source from './MeshRssiChart.vue?raw'
import contextSource from './meshRssiContext.ts?raw'
import tracksideSource from './MeshTracksideSignalChart.vue?raw'

describe('MeshRssiChart', () => {
  it('resizes hidden tabs and releases chart resources', () => {
    expect(source).toContain('new ResizeObserver')
    expect(source).toContain('resizeObserver?.disconnect()')
    expect(source).toContain("window.removeEventListener('resize', handleWindowResize)")
    expect(source).toContain('cancelAnimationFrame(resizeFrame)')
    expect(source).toContain('clientHeight > 0')
    expect(source).toContain('chart?.dispose()')
    expect(source).toContain('function resize(): void')
    expect(source).toContain('if (!props.active || !chart) return')
    expect(source).toContain('.chart { height: 100%; min-height: 0;')
    expect(tracksideSource).toContain('.chart { height: 100%; min-height: 0;')
    expect(source).not.toContain('min-height: 240px')
    expect(tracksideSource).not.toContain('min-height: 240px')
  })

  it('renders one ACTIVE path series with zoom and preloaded standby context', () => {
    expect(source).toContain('components.LegendComponent')
    expect(source).toContain('createMultiSeriesTimeChartBaseOption')
    expect(source).toContain('buildMeshRssiSeries(props.points, props.showPeer, props.scope)')
    expect(source).toContain('buildMeshFullRssiSeries(props.rssiLine)')
    expect(source).toContain("richSeries.filter((item) => item.metric === 'peer_rssi')")
    expect(source).toContain('buildMeshRssiTooltip')
    expect(source).toContain('findRenderedSwitchPoint')
    expect(source).toContain('value: [point.timestamp, point.local_rssi]')
    expect(contextSource).toContain('point.local_rssi !== 0')
    expect(contextSource).toContain('!point.is_anomaly')
    expect(source).not.toContain('value: [event.point_timestamp, event.point_rssi]')
    expect(source).toContain('buildMeshLocationBands')
    expect(source).toContain('connectNulls: false')
    expect(source).not.toContain('sampling:')
    expect(source).not.toContain('new Map<string, MeshRssiPoint[]>')
  })
})
