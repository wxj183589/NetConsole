import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab', () => {
  it('uses a station-row editor and delegates persistence to the parent transaction', () => {
    for (const contract of [
      'getTracksideApPlan',
      'getTracksideApOnlineStatus',
      'previewTracksideApPlan',
      'exportTracksideApPlan',
      'recoverTracksideApTasks',
      "openTaskWindow({ module: 'rail'",
      'AP 规划维护',
      'AP 上线统计',
      '新增站点',
      '删除所选',
      '保存',
      '撤销修改',
      '导入并预览',
      '导出当前',
      '下载模板',
      '刷新上线状态',
      '查看 AP 参考信息',
      "label: '序号'",
      "label: '车站名称'",
      "label: 'AP数量'",
      "label: 'AP起始地址'",
      "label: '掩码'",
      "label: 'AP网关'",
      "label: 'AP管理VLAN'",
      "label: '备注'",
      '重复时报错',
      '有未保存修改',
      'importPreview.legacy_schema',
      'importPreview.message',
      'web.rail_trackside_ap_plan_export',
    ]) expect(source).toContain(contract)

    for (const removed of [
      'previewTracksideApVlanAutoGroup',
      'previewTracksideApVlanChange',
      '拆分 VLAN 组',
      '合并相邻组',
      '新增空组',
      '调整成员/边界',
      '删除空组',
      '全线统一 VLAN',
      '每站独立 VLAN',
      '按站点分组 VLAN',
      'VLAN 组视图',
      '按站点查看（继承值）',
      '阻断问题',
      'revision',
    ]) expect(source).not.toContain(removed)

    expect(source).toContain("emit('change'")
    expect(source).toContain("emit('save')")
    expect(source).toContain('if (!file || props.saving) return')
    expect(source).toContain("input.value = ''")
    expect(source).toContain(':disabled="!importPreview?.can_apply || !canWrite"')
    expect(source).toContain('tracksideApPlanDownloadRequest')
    expect(source).toContain('downloadBackendResource')
    expect(source).toContain('deepCopy(rows.value)')
    expect(source).toContain('pasteGrid($event')
    expect(source).toContain('validStartAddress')
    expect(source).toContain('displayRate(onlineStatus.online_rate)')
    expect(source).toContain('overflow-x: auto')
    expect(source).toContain('min-width: 1120px')
    expect(source).toContain('width: 100%')
    expect(source).toContain('route-key="/rail-transit/base-data"')
    expect(source).not.toContain('saveTracksideApPlan')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
