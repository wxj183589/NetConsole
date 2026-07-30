import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab', () => {
  it('uses a station-row editor and delegates persistence to the parent transaction', () => {
    for (const contract of [
      'getTracksideApPlan',
      'getTracksideApOnlineStatus',
      'previewTracksideApPlan',
      'exportTracksideApPlan',
      'useTaskStore',
      'taskStore.refresh()',
      'AP 规划维护',
      'AP 上线情况概览',
      '新增站点',
      '删除所选',
      '保存',
      '撤销修改',
      '导入并预览',
      '导出当前',
      '下载模板',
      '刷新上线状态',
      '查看异常 AP 资料',
      "label: '序号'",
      "label: '车站名称'",
      "label: 'AP数量'",
      "label: '规划AP总数量'",
      "label: 'AP管理VLAN'",
      "label: '备注'",
      "label: 'Excel行'",
      "label: '问题'",
      "label: '实际上线'",
      "label: '未上线'",
      "label: '上线率'",
      '规划 AP 总数量由用户维护；实际上线数量来自最新 AC/FIT-AP 状态。',
      '超规划',
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
      "key: 'actual_ap_count'",
      "key: 'online_count'",
      "label: 'AP总数量'",
      "label: 'AP起始地址'",
      "label: '掩码'",
      "label: 'AP网关'",
      '规划影响预览',
      '修改管理 VLAN 影响预览',
      '应用预览结果',
      'allow-create',
    ]) expect(source).not.toContain(removed)

    expect(source).toContain("emit('change'")
    expect(source).toContain("emit('save')")
    expect(source).toContain('if (!file || props.saving) return')
    expect(source).toContain("input.value = ''")
    expect(source).toContain(':disabled="!canApplyImport || !canWrite"')
    expect(source).toContain('轨旁AP逐站规划模板.xlsx')
    expect(source).toContain('_轨旁AP规划及上线概览_')
    expect(source).toContain('deepCopy(rows.value)')
    expect(source).toContain('pasteGrid($event')
    expect(source).toContain('错误行会保留在预览中')
    expect(source).toContain('displayRate(onlineStatus.online_rate)')
    expect(source).toContain('overflow-x: auto')
    expect(source).not.toContain('min-width: 1120px')
    expect(source).toContain('width: 100%')
    expect(source).toContain('route-key="/rail-transit/base-data"')
    expect(source).not.toContain('saveTracksideApPlan')
    expect(source).not.toContain('getTracksideApTask')
    expect(source).not.toContain('recoverTracksideApTasks')
    expect(source).not.toContain('netconsole.trackside-ap-plan.last-task')
    expect(source).not.toContain('打开任务中心')
    expect(source).not.toContain('tracksideApPlanDownloadRequest')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
  })
})
