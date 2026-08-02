import { describe, expect, it } from 'vitest'

import source from './RailTransitBaseDataView.vue?raw'

describe('Rail Transit base data maintenance view', () => {
  it('fills the available route width and height while keeping tab content scrollable', () => {
    expect(source).toContain('.rail-base-data { display: flex; width: 100%; height: 100%; max-width: none;')
    expect(source).toContain('.content-card { display: flex; min-width: 0; min-height: 0; flex: 1;')
    expect(source).toContain('.content-card > :deep(.el-tabs) { display: flex; min-width: 0; min-height: 0; flex: 1;')
    expect(source).toContain('.content-card > :deep(.el-tabs > .el-tabs__content) { min-width: 0; min-height: 0; flex: 1; overflow: hidden; }')
    expect(source).toContain('.content-card > :deep(.el-tabs > .el-tabs__content > .el-tab-pane) { width: 100%; height: 100%; overflow: auto; }')
    expect(source).not.toContain('max-width: 1760px')
  })

  it('lazy-mounts tab content and pages scoped AP and MR drafts', () => {
    expect(source).not.toMatch(/<el-tab-pane(?![^>]*\slazy)[^>]*>/)
    expect(source).toContain('pageRows(currentPageDraft.value.aps, editApPage.value, editApPageSize.value)')
    expect(source).toContain('pageRows(currentPageDraft.value.mrs, editMrPage.value, editMrPageSize.value)')
    expect(source).toContain(':total="apPageTotal"')
    expect(source).toContain(':total="mrPageTotal"')
    expect(source).toContain('cloneDto(editingDraft.value?.aps ?? [])')
  })

  it('owns independent subpage drafts, save scopes and switch guards', () => {
    expect(source).toContain("type EditableSubPage = Exclude<BaseDataEditScope, 'all'>")
    expect(source).toContain('const subPageEditContexts = reactive')
    expect(source).toContain("overview: createSubPageContext()")
    expect(source).toContain("trackside_ap_planning: createSubPageContext()")
    expect(source).toContain('store.refreshEditSnapshot(scope)')
    expect(source).toContain('store.validateChanges(scope, context.baseRevision, changes)')
    expect(source).toContain('store.saveChanges(scope, context.baseRevision, changes)')
    expect(source).toContain("confirmText: '保存并切换'")
    expect(source).toContain("secondaryText: '放弃并切换'")
    expect(source).toContain("cancelText: '取消切换'")
    expect(source).toContain("@unlock=\"startEditing('overview')\"")
    expect(source).toContain("@unlock=\"startEditing('stations')\"")
    expect(source).toContain("@unlock=\"startEditing('trackside_ap')\"")
    expect(source).toContain("@unlock=\"startEditing('trackside_ap_planning')\"")
    expect(source).toContain("@unlock=\"startEditing('vehicles')\"")
    expect(source).not.toContain('@click="startEditing">编辑</el-button>')
    expect(source).not.toContain('@click="saveAllChanges()">保存</el-button>')
    expect(source).toContain('一个或多个子页存在未保存修改')
    expect(source).toContain('anyDirty')
  })

  it('preserves the guarded base-data maintenance, import and navigation contracts', () => {
    for (const contract of [
      '基础资料总览',
      '站点与区间',
      '轨旁 AP',
      '轨旁 AP 导入预览',
      'exportTracksideApBase',
      'useTaskStore',
      'taskStore.refresh()',
      'handleTracksideApFile',
      '导入 {{ previewImportableCount }} 条有效数据到草稿',
      '未匹配 FIT-AP',
      'TracksideApPlanningTab',
      '列车与车载 MR',
      '数据质量问题',
      '关联运行状态',
      '线路与方向参数',
      '站序递增时的行驶头端',
      '物理安装位置',
      'MR 端位代码',
      '设备管理 · 站点字段',
      '从设备管理生成',
      '下载模板',
      '导入模板',
      '导出当前',
      '导出重命名命令',
      "row.runtime.fit_ap_name || row.name || row.point_code || '--'",
      'ap.runtime.fit_ap_ac_id || undefined',
      'ap.runtime.fit_ap_id',
      '递增方向线路侧',
      '递减方向线路侧',
      'handleApSectionChange(row, String($event))',
      "key: 'lldp_suggested_station_id', label: 'LLDP 建议站点'",
      'applyLldpStationSuggestion(row)',
      '应用到草稿',
      '保存后才会写入数据库',
      '新增节点',
      '终点属性',
      '线路端点：轨道线路实际到这里结束',
      '运营终到/折返',
      '运营终到/折返：正常运营列车会在这里作为终到、始发或折返站',
      '轨道设施',
      'v-model="row.track_facilities" multiple clearable',
      '中心里程',
      '根据站点生成区间',
      '恢复自动值',
      "markSectionField(row, 'name')",
      ':label="option.display_label" :value="option.uid"',
      "row.start_station = selected?.persisted_name || value",
      "row.result === 'CONFLICT'",
      'selected_by_default',
      '设备管理站点来源预览',
      '基础资料模板导入预览',
      '应用到当前草稿',
      '设备名称、系统名和地址不参与站点识别',
      '逐行校验并导入有效数据',
      'serverSnapshot',
      'editingDraft',
      ':data="stationRows"',
      ':data="sectionRows"',
      ':data="apRows"',
      ':data="mrRows"',
      'planningDirty',
      'currentPageDraft.value?.tracksideApPlans',
      ':model-value="planningRows"',
      ':editing="editing"',
      '@update:model-value="handlePlanningChange"',
      'store.refreshStationSourcePreview()',
      'store.previewStationTemplateFile(file)',
      'setFieldErrors(changes, validation.issues)',
      '待删除',
      "undoDelete('station', row)",
      '只看阻断问题',
      '待人工确认',
      'CREATE',
      'CONFLICT',
      '字段差异',
      'previewImportableCount <= 0',
      '仅显示冲突',
      '仅显示无效',
      '导出问题明细',
      '不影响基础资料导入及 MR 日志识别',
      '导入审计',
      '回滚',
      '<el-pagination',
      'handleVisibility',
      'store.stopPolling()',
      'onBeforeRouteLeave',
      "window.addEventListener('beforeunload'",
      'route.query.tab',
      'name="trackside-ap-planning"',
      "path: '/rail-transit/train-online'",
    ]) expect(source).toContain(contract)

    for (const forbidden of [
      'openApMesh',
      "key: 'line_side', label: '线路方向'",
      "key: 'mesh_related_name', label: '关联 MR'",
      "canEditRow('section', row.id) && !row.auto_generated",
      '>线路</el-checkbox>',
      '>运营</el-checkbox>',
      '我已核对差异、冲突和目标局点',
      "path: '/ac-management/mesh-links'",
      'getTracksideApTask',
      'recoverTracksideApTasks',
      'netconsole.trackside-ap-base.last-task',
      '打开任务中心',
      'reloadPlan',
      'watch(activeTab',
    ]) expect(source).not.toContain(forbidden)
  })

  it('does not expose credentials, lock mode or unguarded persistence', () => {
    expect(source).toContain("deleteEntity('trackside_ap', row)")
    expect(source).not.toContain('v-if="!locked"')
    expect(source).not.toContain('locked.value')
    expect(source).toMatch(/store\.importPolicies\?\.rollback_enabled/)
    expect(source).not.toContain('密码')
    expect(source).not.toContain('username')
    expect(source).not.toContain('client_count')
  })

  it('uses formal station IDs when generating planning rows and never creates stations there', () => {
    expect(source).toContain("if (stationSourcePlanningMode.value)")
    expect(source).toContain('candidate.matched_station_id')
    expect(source).toContain('未匹配项未创建站点')
    expect(source).toContain('缺少正式 station_id')
    expect(source).toContain('前往站点与区间维护')
    expect(source).toContain('当前环境只读：${writeDeniedReason')
  })

  it('uses the shared typed data table contract for every base-data table', () => {
    expect(source).toContain("import NcDataTable from '../../components/table/NcDataTable.vue'")
    expect(source).toContain('NcTableColumn<Station>[]')
    expect(source).toContain('NcTableColumn<DataQualityIssue>[]')
    expect(source).toContain('NcTableColumn<MergeFieldDiff>[]')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
    expect(source).toContain('#cell-expand')
    expect(source).toContain(':preference-scope="row.entity_id"')
    expect(source).toContain(':preference-scope="String(row.row_number)"')
    expect(source).toContain("alignmentReason: 'long-text'")
    expect(source).toContain("alignmentReason: 'path'")

    const tableIds = [...source.matchAll(/table-id="([^"]+)"/g)].map((match) => match[1])
    expect(tableIds.length).toBeGreaterThanOrEqual(10)
    expect(new Set(tableIds).size).toBe(tableIds.length)
  })
})
