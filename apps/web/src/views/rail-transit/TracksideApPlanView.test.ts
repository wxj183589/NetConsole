import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanView.vue?raw'

describe('trackside AP plan view', () => {
  it('keeps the complete Qt plan operations on the rail application service boundary', () => {
    for (const contract of [
      'getTracksideApPlan', 'previewTracksideApPlan', 'saveTracksideApPlan',
      'exportTracksideApPlan', 'cancelTracksideApTask', 'recoverTracksideApTasks',
      '新增', '删除', '保存', '导入并预览', '导出规划', '导出模板',
      '重复时覆盖', '重复时跳过', '重复时报错', '未保存修改',
      'web.rail_trackside_ap_plan_write', 'web.rail_trackside_ap_plan_export',
    ]) expect(source).toContain(contract)
  })
})
