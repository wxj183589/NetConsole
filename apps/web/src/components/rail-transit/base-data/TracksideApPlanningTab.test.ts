import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab', () => {
  it('reuses plan import/export and delegates persistence to the parent transaction', () => {
    for (const contract of [
      'getTracksideApPlan', 'previewTracksideApPlan', 'exportTracksideApPlan',
      'recoverTracksideApTasks', "openTaskWindow({ module: 'rail'",
      '新增', '删除', '导入并预览', '导出当前', '下载模板', '下载文件',
      '重复时覆盖', '重复时跳过', '重复时报错', '未保存修改',
      'web.rail_trackside_ap_plan_export',
    ]) expect(source).toContain(contract)
    expect(source).toContain("emit('change'")
    expect(source).toContain('const canPreviewImport = computed(() => !props.saving)')
    expect(source).toContain('const canApplyImport = computed(() => !props.locked && !props.saving)')
    expect(source).toContain('if (!file || !canPreviewImport.value) return')
    expect(source).toContain(':disabled="!preview?.can_apply || !canApplyImport"')
    expect(source).toContain('tracksideApPlanDownloadRequest')
    expect(source).toContain('downloadBackendResource')
    expect(source).toContain('v-if="canWrite"')
    expect(source).not.toContain("isFeatureEnabled('web.rail_trackside_ap_plan_write')")
    expect(source).toContain('rows.value.map((row) => ({ ...row }))')
    expect(source).not.toContain('structuredClone(rows.value)')
    expect(source).toContain("route-key=\"/rail-transit/base-data\"")
    expect(source).not.toContain('saveTracksideApPlan')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
