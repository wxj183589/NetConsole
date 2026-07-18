import { describe, expect, it } from 'vitest'

import source from './VehicleMrOnlineView.vue?raw'

describe('vehicle MR online view', () => {
  it('exposes persisted CT/TC state and real refresh and mapping actions', () => {
    expect(source).toContain('MR-CT 当前 AP')
    expect(source).toContain('MR-TC 当前 AP')
    expect(source).toContain('refreshVehicleMrOnline')
    expect(source).toContain('refreshVehicleMrApMapping')
    expect(source).toContain('saveVehicleMrMappings')
    expect(source).toContain('startVehicleMrCollection')
    expect(source).toContain('stopVehicleMrCollection')
    expect(source).toContain('previewVehicleMrMappings')
    expect(source).toContain('exportVehicleMrHistory')
    expect(source).toContain('exportVehicleMrMappingTemplate')
    expect(source).toContain('重复时覆盖')
    expect(source).toContain('重复时跳过')
    expect(source).toContain('重复时报错')
    expect(source).toContain('开始')
    expect(source).toContain('停止')
    expect(source).toContain('导出模板')
    expect(source).toContain("openTaskWindow({ module: 'rail'")
    expect(source).not.toContain('取消任务')
    expect(source).toContain('恢复任务')
    expect(source).not.toMatch(/READ ONLY|只读|迁移/)
  })

  it('uses typed data tables without changing editable mapping slots', () => {
    expect(source).toContain("import NcDataTable")
    expect(source).toContain('NcTableColumn<VehicleMrTrainState>')
    expect(source.match(/<NcDataTable\b/g)).toHaveLength(5)
    expect(source).toContain('table-id="rail-vehicle-mr-online-trains"')
    expect(source).toContain('table-id="rail-vehicle-mr-online-task-results"')
    expect(source).toContain(':preference-scope="task.action"')
    expect(source).toContain('table-id="rail-vehicle-mr-online-history"')
    expect(source).toContain('table-id="rail-vehicle-mr-online-mappings"')
    expect(source).toContain('table-id="rail-vehicle-mr-online-mapping-preview"')
    expect(source).toContain('v-model="row.tc1_peer_name"')
    expect(source).toContain("alignmentReason: 'long-text'")
    expect(source).not.toContain('<el-table')
  })
})
