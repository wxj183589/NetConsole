import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanView.vue?raw'

describe('trackside AP plan view', () => {
  it('keeps the complete Qt plan operations on the rail application service boundary', () => {
    for (const contract of [
      'getTracksideApPlan', 'previewTracksideApPlan', 'saveTracksideApPlan',
      'exportTracksideApPlan', 'recoverTracksideApTasks', "openTaskWindow({ module: 'rail'",
      '新增', '删除', '保存', '导入并预览', '导出规划', '导出模板',
      '重复时覆盖', '重复时跳过', '重复时报错', '未保存修改',
      'web.rail_trackside_ap_plan_write', 'web.rail_trackside_ap_plan_export',
    ]) expect(source).toContain(contract)
    expect(source).not.toContain('cancelTracksideApTask')
    expect(source).toContain('const planColumns: NcTableColumn<TracksideApPlanRow>[]')
    expect(source).toContain('table-id="trackside-ap-plan"')
    expect(source).toContain('table-id="trackside-ap-plan-import-preview"')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
