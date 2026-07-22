import { describe, expect, it } from 'vitest'

import source from './AcManagementView.vue?raw'

describe('AC Management resource view', () => {
  it('shows real refresh, connection record, radio fields, optical relation and config diff', () => {
    expect(source).toContain('更新 FIT-AP 资源')
    expect(source).toContain('更新 AC 信息')
    expect(source).toContain('打开 AC Web')
    expect(source).toContain('getPlatformAdapter().openExternalUrl')
    expect(source).toContain("getRuntimeConfig().hostType === 'electron'")
    expect(source).toContain('深度更新')
    expect(source).toContain('更新光衰')
    expect(source).toContain('批量删除')
    expect(source).toContain('导入 AP 元数据')
    expect(source).toContain('保存元数据')
    expect(source).toContain("openHistory('radio')")
    expect(source).toContain("openHistory('lldp')")
    expect(source).toContain("openHistory('optical')")
    expect(source).toContain('getAcApHistory')
    expect(source).toContain('.csv,.xlsx')
    expect(source).toContain('选择本页')
    expect(source).toContain('反选本页')
    expect(source).toContain('useConfirm')
    expect(source).toContain('confirm({')
    expect(source).toContain('打开任务窗口')
    expect(source).toContain("openTaskWindow({ module: 'ac'")
    expect(source).toContain('FIT-AP 资源')
    expect(source).toContain('AC 连接记录')
    expect(source).toContain('Mesh Radio 1 / 2')
    expect(source).toContain('利用率 (%)')
    expect(source).toContain('客户端')
    expect(source).toContain('AP 在线状态')
    expect(source).toContain('光衰判定')
    expect(source).toContain('数据已过期')
    expect(source).not.toContain('未关联 AP 离线')
    expect(source).toContain('配置采集与对比')
    expect(source).not.toContain('label="FIT-AP 光衰"')
    expect(source).not.toContain('Radio 3')
    expect(source).not.toContain('client_count')
    expect(source).not.toContain('序列号')
    expect(source).toContain('一键固化新上线 AP')
    expect(source).toContain('一键开启 AP 远程登入')
    expect(source).toContain("prepareAcAction('persist_auto_ap')")
    expect(source).toContain("prepareAcAction('enable_ap_remote_login')")
    expect(source).toContain('createAcActionPlan')
    expect(source).toContain('confirmAcActionPlan')
    expect(source).toContain('executeAcActionPlan')
    expect(source).toContain('getAcActionPlan')
    expect(source).toContain('getAcActionAudit')
    expect(source).not.toContain('save force')
  })

  it('removes the obsolete page alert and wires bounded AC additions', () => {
    expect(source).not.toContain('title="AC / FIT-AP 资源"')
    expect(source).not.toContain('“更新 FIT-AP 资源”通过后台任务连接所选 H3C AC')
    expect(source).not.toContain('readonly-alert')
    expect(source).toContain("isFeatureEnabled('web.ac_dangerous_actions')")
    expect(source).toContain(':disabled="!store.filters.ac_id || acActionConflict"')
    expect(source).toContain('actionPlan.command_summary.join')
    expect(source).toContain('store.trackActionTask')
    expect(source).not.toContain('actionPlan.confirm_token')
  })

  it('uses current-AC OmniPeek scope and the shared task/artifact flow', () => {
    expect(source).toContain('导出 OmniPeek 名称表')
    expect(source).toContain("isFeatureEnabled('ac.omnipeek_name_table_export')")
    expect(source).toContain('startAcOmniPeekPreview(store.filters.ac_id, omniPeekScopeIds.value)')
    expect(source).toContain('startAcOmniPeekExport(store.filters.ac_id, omniPeekScopeIds.value)')
    expect(source).toContain('input_ap_count')
    expect(source).toContain('exportable_entry_count')
    expect(source).toContain('skipped_count')
    expect(source).toContain('error_count')
    expect(source).toContain('openTaskWindow(task.task_id)')
  })

  it('adds a bounded row context menu while retaining detail and copy actions', () => {
    expect(source).toContain('@row-contextmenu="showContextMenu"')
    expect(source).toContain('查看详情')
    expect(source).toContain('打开外部终端')
    expect(source).toContain('更新该 AP 光衰')
    expect(source).toContain('复制单元格')
    expect(source).toContain('复制整行')
    expect(source).toContain("getRuntimeConfig().hostType === 'electron'")
    expect(source).toContain("isFeatureEnabled('web.ac_fit_ap_external_terminal')")
    expect(source).toContain('openAcFitApExternalTerminal(row.id, store.filters.ac_id, terminalType.value)')
    expect(source).not.toContain('subprocess')
    expect(source).not.toContain('confirm_token')
  })

  it('places rail metadata after AP-side receive optical attenuation', () => {
    const orderedColumns = [
      "acColumn('optical_rx_power', 'AP侧收光光衰'",
      "acColumn('station', '归属站点'",
      "acColumn('section', '归属区间'",
      "acColumn('mileage', '里程'",
      "acColumn('direction', '线路方向'",
    ]

    const positions = orderedColumns.map((column) => source.indexOf(column))
    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((left, right) => left - right))
  })

  it('uses the shared table component instead of private column sizing and visibility state', () => {
    expect(source).toContain('table-id="ac-fit-ap-resources"')
    expect(source).toContain('table-id="ac-config-snapshots"')
    expect(source).toContain('table-id="ac-fit-ap-radios"')
    expect(source).toContain('table-id="ac-fit-ap-history"')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('columnVisibility')
  })

  it('uses topology ordering, short interface display, and keeps LLDP station inference advisory', () => {
    expect(source).toContain("sort_by: 'topology'")
    expect(source).toContain('displayInterfaceName')
    expect(source).toContain("station_source === 'lldp_switch_suggestion'")
    expect(source).toContain('根据 LLDP 邻居交换机站点建议，保存后才写入')
  })

  it('stops polling when hidden and exposes no unapproved device write action', () => {
    expect(source).toContain('document.hidden')
    expect(source).toContain('store.stopPolling()')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('taskStore.releasePolling(pollingConsumer)')
    expect(source).not.toContain('停止任务')
    expect(source).not.toContain('cancelRefreshTask')
    expect(source).not.toContain('下发')
  })
})
