import { describe, expect, it } from 'vitest'

import source from './RailTransitWebParityView.vue?raw'

describe('rail transit Web parity controlled view', () => {
  it('calls the Online MR diagnostic, streaming import, report and task APIs', () => {
    expect(source).toContain('startCarNetworkDiagnostic')
    expect(source).toContain('importMeshAnalysis')
    expect(source).toContain('exportOnlineMrReport')
    expect(source).toContain('exportMeshAnalysisReport')
    expect(source).toContain('cancelRailTransitTask')
    expect(source).toContain('recoverRailTransitTasks')
    expect(source).toContain('getRailTransitTask')
    expect(source).toContain('downloadOnlineMrReport')
    expect(source).toContain('downloadMeshAnalysisReport')
    expect(source).toContain('localStorage')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('onlineTrains')
    expect(source).toContain('accept=".log,.txt"')
    expect(source).not.toContain('.csv')
    expect(source).not.toContain('site_id')
    expect(source).not.toContain('artifact_path')
    expect(source).not.toContain('JSON.stringify')
  })
})
