import { describe, expect, it } from 'vitest'

import source from './RailTransitWebParityView.vue?raw'

describe('rail transit Web parity controlled view', () => {
  it('calls the Online MR diagnostic, streaming import, report and task APIs', () => {
    expect(source).toContain('startCarNetworkDiagnostic')
    expect(source).toContain('importMeshAnalysis')
    expect(source).toContain('exportOnlineMrReport')
    expect(source).toContain('exportMeshAnalysisReport')
    expect(source).toContain('cancelRailTransitTask')
    expect(source).toContain('accept=".log,.txt"')
    expect(source).not.toContain('.csv')
    expect(source).not.toContain('site_id')
    expect(source).not.toContain('artifact_path')
  })
})
