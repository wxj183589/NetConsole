import { describe, expect, it } from 'vitest'

import source from './CarNetworkDiagnosticView.vue?raw'

describe('car network diagnostic view', () => {
  it('owns only the real diagnostic task lifecycle', () => {
    for (const contract of [
      'startCarNetworkDiagnostic',
      'getCarNetworkDiagnosticTask',
      'recoverCarNetworkDiagnostics',
      "openTaskWindow({ module: 'rail'",
      'web.rail_car_network_diagnostic_execute',
      'web.rail_task_control',
      '开始检测',
      '打开任务窗口',
      '跨 TC 丢包',
      'CarNetworkPointTableDialog',
      '点表管理',
    ]) expect(source).toContain(contract)
    expect(source).not.toContain('cancelCarNetworkDiagnostic')
    for (const unrelated of [
      'importMeshAnalysis',
      'exportMeshAnalysisReport',
      'exportOnlineMrReport',
      'queryOnlineMrMetrics',
    ]) expect(source).not.toContain(unrelated)
    expect(source).toContain('const trainColumns: NcTableColumn<OnlineTrainRow>[]')
    expect(source).toContain('table-id="car-network-diagnostic-trains"')
    expect(source).toContain('table-id="car-network-diagnostic-result"')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
