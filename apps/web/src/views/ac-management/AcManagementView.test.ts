import { describe, expect, it } from 'vitest'

import source from './AcManagementView.vue?raw'
import omniPeekSource from './AcOmniPeekExportDialog.vue?raw'

describe('AC Management resource view', () => {
  it('uses the full routed workspace width instead of centering a fixed-width shell', () => {
    expect(source).toContain('.ac-management { width: 100%; max-width: none; margin: 0; }')
    expect(source).not.toContain('max-width: 1780px')
  })

  it('shows real refresh, connection record, radio fields, optical relation and config diff', () => {
    expect(source).toContain('更新 FIT-AP 资源')
    expect(source).toContain('更新 AC 信息')
    expect(source).toContain('打开 AC Web')
    expect(source).toContain('getPlatformAdapter().openExternalUrl')
    expect(source).toContain("getRuntimeConfig().hostType === 'electron'")
    expect(source).toContain('更新当前 AP 详细信息')
    expect(source).toContain('更新光衰')
    expect(source).toContain('批量删除')
    expect(source).not.toContain('导入 AP 元数据')
    expect(source).toContain('保存手工覆盖')
    expect(source).toContain("openHistory('radio')")
    expect(source).toContain("openHistory('lldp')")
    expect(source).toContain("openHistory('optical')")
    expect(source).toContain('getAcApHistory')
    expect(source).not.toContain('accept=".csv,.xlsx"')
    expect(source).toContain('选择本页')
    expect(source).toContain('反选本页')
    expect(source).toContain('useConfirm')
    expect(source).toContain('confirm({')
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

  it('removes the page-level AC task banner without leaving its legacy task-window entry', () => {
    expect(source).not.toContain('AC 任务 · 运行中')
    expect(source).not.toContain('打开任务中心')
    expect(source).not.toContain('task-summary')
    expect(source).not.toContain('function openTaskWindow')
    expect(source).not.toContain("openTaskWindow({ module: 'ac'")
    expect(source).toContain('class="ac-info-strip"')
    expect(source).toContain('class="content-card"')
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
    expect(source).toContain('<AcOmniPeekExportDialog')
    expect(source).toContain(':ap-ids="omniPeekScopeIds"')
    expect(omniPeekSource).toContain('startAcOmniPeekPreview(props.acId, props.apIds')
    expect(omniPeekSource).toContain('startAcOmniPeekExport(props.acId, props.apIds')
    expect(omniPeekSource).toContain('selected_item_keys')
    expect(omniPeekSource).toContain('force_export_keys')
    expect(omniPeekSource).toContain('downloadBackendResource')
  })

  it('offers three FIT-AP export scopes and preserves Artifact retry', () => {
    expect(source).toContain("isFeatureEnabled('web.ac_fit_ap_resource_export')")
    expect(source).toContain('导出当前筛选结果')
    expect(source).toContain('导出已选择 AP')
    expect(source).toContain('导出当前 AC 全部 AP')
    expect(source).toContain(":disabled=\"!selectedApIds.size\"")
    expect(source).toContain('scope === \'filtered\'')
    expect(source).toContain('scope === \'selected\'')
    expect(source).toContain('submitExportAfterDestinationSelected')
    expect(source).toContain("'ac.fit_ap_resources'")
    expect(source).not.toContain('waitForResourceExport')
    expect(source).toContain('saveResourceExportArtifact')
    expect(source).toContain('导出文件仍保留在任务中心')
  })

  it('uses generated selectable options for FIT-AP resource metadata filters', () => {
    expect(source).toContain('store.filterOptions.stations')
    expect(source).toContain('store.filterOptions.sections')
    expect(source).toContain('store.filterOptions.models')
    expect(source).toContain('store.filterOptions.switches')
    expect(source).toContain('allow-create default-first-option placeholder="归属站点"')
    expect(source).not.toContain('<el-input v-model="store.filters.station"')
    expect(source).not.toContain('<el-input v-model="store.filters.section"')
    expect(source).not.toContain('<el-input v-model="store.filters.model"')
    expect(source).not.toContain('<el-input v-model="store.filters.switch"')
  })

  it('adds a bounded row context menu while retaining detail and copy actions', () => {
    expect(source).toContain(':context-menu-items="fitApContextMenuItems"')
    expect(source).toContain('NcDataTableContextMenuItem')
    expect(source).toContain('查看详情')
    expect(source).toContain('打开外部终端')
    expect(source).toContain('更新该 AP 光衰')
    expect(source).toContain('复制单元格')
    expect(source).toContain('复制整行')
    expect(source).toContain("getRuntimeConfig().hostType === 'electron'")
    expect(source).toContain("isFeatureEnabled('web.ac_fit_ap_external_terminal')")
    expect(source).toContain('useExternalTerminalLauncher')
    expect(source).toContain('requestFitApTerminal({ apId: row.id, acId: store.filters.ac_id })')
    expect(source).not.toContain('document.addEventListener(\'click\'')
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
    expect(source).toContain('自动关联信息（只读）')
    expect(source).toContain('保存时只提交正式 station_id；自动关联、LLDP 建议和 AC 原始站点不会自动写入。')
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
