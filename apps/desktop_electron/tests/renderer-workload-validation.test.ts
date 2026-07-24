import { describe, expect, it } from 'vitest'

import { validateRendererWorkloadReport } from '../src/shared/validation'

describe('renderer workload validation', () => {
  it('preserves bounded MESH memory profile counters', () => {
    const report = validateRendererWorkloadReport({
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'trackside-cache-ready',
      sessionId: 'session-1',
      pointCount: 44_251,
      metadataCount: 44_251,
      conflictEdgeCount: 1_024,
      echartsInstanceCount: 2,
      canvasCount: 2,
      meshInstanceCount: 2,
      tracksideCacheCount: 1,
      tracksideChartCount: 1,
      activeDetailRequests: 0,
      tracksideCacheBuildCount: 20,
      tracksideCacheDisposeCount: 19,
      chartInitCount: 20,
      chartDisposeCount: 19,
      reportRevision: 3,
    })

    expect(report).toMatchObject({
      pointCount: 44_251,
      metadataCount: 44_251,
      conflictEdgeCount: 1_024,
      meshInstanceCount: 2,
      tracksideCacheCount: 1,
      tracksideChartCount: 1,
    })
  })

  it('rejects unbounded or unrecognized memory fields', () => {
    expect(() => validateRendererWorkloadReport({
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'session-selected',
      pointCount: -1,
      reportRevision: 1,
    })).toThrow()
    expect(() => validateRendererWorkloadReport({
      module: 'mesh-analysis',
      route: '/rail-transit/mesh-analysis',
      phase: 'session-selected',
      externalMemoryBytes: 1,
      reportRevision: 1,
    })).toThrow()
  })
})
