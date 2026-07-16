import { describe, expect, it } from 'vitest'

import source from './CarNetworkDiagnosticView.vue?raw'

describe('car network diagnostic view', () => {
  it('owns only the real diagnostic task lifecycle', () => {
    for (const contract of [
      'startCarNetworkDiagnostic',
      'getCarNetworkDiagnosticTask',
      'cancelCarNetworkDiagnostic',
      'recoverCarNetworkDiagnostics',
      'web.rail_car_network_diagnostic_execute',
      'web.rail_task_control',
      '开始检测',
      '取消检测',
      '跨 TC 丢包',
      'CarNetworkPointTableDialog',
      '点表管理',
    ]) expect(source).toContain(contract)
    for (const unrelated of [
      'importMeshAnalysis',
      'exportMeshAnalysisReport',
      'exportOnlineMrReport',
      'queryOnlineMrMetrics',
    ]) expect(source).not.toContain(unrelated)
  })
})
