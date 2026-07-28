import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab', () => {
  it('reuses plan import/export and delegates persistence to the parent transaction', () => {
    for (const contract of [
      'getTracksideApPlan', 'previewTracksideApPlan', 'exportTracksideApPlan',
      'recoverTracksideApTasks', 'previewTracksideApVlanAutoGroup', 'previewTracksideApVlanChange',
      "openTaskWindow({ module: 'rail'",
      '拆分 VLAN 组', '合并相邻组', '新增空组', '调整成员/边界', '删除空组', '查看站点', '查看 AP/参考信息',
      '导入并预览', '导出当前', '下载模板', '下载文件',
      '全线统一 VLAN', '每站独立 VLAN', '按站点分组 VLAN', 'VLAN 组视图', '按站点查看（继承值）',
      '区间默认组', '按区间起点继承（默认）', 'AP 级覆盖', '有效组来源', '既有 AP IP（参考）',
      '修改管理 VLAN 影响预览', 'AP 与 IP 参考信息',
      '网络地址（参考）', '掩码/前缀（参考）', '网关（参考）', 'AP 起始地址（参考）', 'AP 结束地址（参考）',
      'VLAN 组继承', 'AP 单独指定', '站点历史配置', '未配置',
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
    expect(source).toContain('min-width:1120px')
    expect(source).toContain("'section_default'")
    expect(source).toContain("'ap_override'")
    expect(source).toContain('beginGroupVlanEdit')
    expect(source).toContain('commitGroupVlanEdit')
    expect(source).not.toContain("label: '网络地址'")
    expect(source).not.toContain("label: 'AP 网关'")
    expect(source).not.toContain("label: 'AP 起始地址'")
    expect(source).not.toContain("label: '地址容量'")
    expect(source).not.toContain("label: '已用地址'")
    expect(source).not.toContain('地址重算')
    expect(source).not.toContain('全部重新生成')
    expect(source).not.toContain('reallocationPolicy')
    expect(source).not.toContain('structuredClone')
    expect(source).toContain("route-key=\"/rail-transit/base-data\"")
    expect(source).not.toContain('saveTracksideApPlan')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
