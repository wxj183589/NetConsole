import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab', () => {
  it('reuses plan import/export and delegates persistence to the parent transaction', () => {
    for (const contract of [
      'getTracksideApPlan', 'previewTracksideApPlan', 'exportTracksideApPlan',
      'recoverTracksideApTasks', 'previewTracksideApVlanAutoGroup', 'previewTracksideApVlanChange',
      "openTaskWindow({ module: 'rail'",
      '拆分 VLAN 组', '合并相邻组', '新增空组', '调整成员/边界', '删除空组', '查看站点', '查看地址分配',
      '地址容量', '已用地址', '导入并预览', '导出当前', '下载模板', '下载文件',
      '全线统一 VLAN', '每站独立 VLAN', '按站点分组 VLAN', 'VLAN 组视图', '按站点查看（继承值）',
      '区间默认组', '按区间起点继承（默认）', 'AP 级覆盖', '有效组来源',
      '修改 VLAN 组网络参数影响预览',
      '仅未锁定地址（默认）', '全部重新生成',
      '重复时覆盖', '重复时跳过', '重复时报错', '未保存修改',
      'web.rail_trackside_ap_plan_export',
    ]) expect(source).toContain(contract)
    expect(source).toContain("emit('change'")
    expect(source).toContain('const canPreviewImport = computed(() => !props.saving)')
    expect(source).toContain('const canApplyImport = computed(() => !props.locked && !props.saving)')
    expect(source).toContain('if (!file || !canPreviewImport.value) return')
    expect(source).toContain(':disabled="!importPreview?.can_apply || !canApplyImport"')
    expect(source).toContain('tracksideApPlanDownloadRequest')
    expect(source).toContain('downloadBackendResource')
    expect(source).toContain('v-if="canWrite"')
    expect(source).not.toContain("isFeatureEnabled('web.rail_trackside_ap_plan_write')")
    expect(source).toContain('deepCopy(draft.value)')
    expect(source).toContain('v-for="count in 4"')
    expect(source).toContain('overflow-x:auto')
    expect(source).toContain('min-width:1680px')
    expect(source).toContain("'section_default'")
    expect(source).toContain("'ap_override'")
    expect(source).toContain('beginGroupNetworkEdit')
    expect(source).toContain('commitGroupNetworkEdit')
    expect(source).not.toContain('structuredClone')
    expect(source).toContain("route-key=\"/rail-transit/base-data\"")
    expect(source).not.toContain('saveTracksideApPlan')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
