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
    expect(source).toContain('onlineMrReportDownloadRequest')
    expect(source).toContain('meshAnalysisReportDownloadRequest')
    expect(source).toContain('downloadBackendResource')
    expect(source).toContain('localStorage')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('onlineTrains')
    expect(source).toContain('accept=".log,.txt"')
    for (const featureId of [
      'web.rail_car_network_diagnostic_execute',
      'web.mesh_analysis_import',
      'web.online_mr_report_export',
      'web.mesh_analysis_report_export',
      'web.rail_task_control',
    ]) expect(source).toContain(`isFeatureEnabled('${featureId}')`)
    expect(source).not.toContain('.csv')
    expect(source).not.toContain('site_id')
    expect(source).not.toContain('artifact_path')
    expect(source).not.toContain('JSON.stringify')
  })
})
