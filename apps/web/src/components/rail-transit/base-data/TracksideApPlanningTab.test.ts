import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab source contract', () => {
  it('is a controlled editor with stable-ID association and no persistence ownership', () => {
    for (const contract of [
      'modelValue: TracksideApPlanRow[]',
      'stations: PlanningStation[]',
      'editing: boolean',
      'readonly: boolean',
      'saving: boolean',
      "'update:modelValue'",
      "'validation-change'",
      "'request-generate-stations'",
      'station_id',
      '待关联历史规划',
      'overflow-x: auto',
      'const planColumns',
      ':controls="false"',
      'pasteGrid',
      'focusNextRow',
      'cancelCellEdit',
      '@wheel.prevent.stop',
      'route-key="/rail-transit/base-data"',
      'v-if="editing"',
      'v-else>{{ row.station_name || \'--\' }}</span>',
    ]) expect(source).toContain(contract)

    for (const forbidden of [
      'getTracksideApPlan',
      'saveTracksideApPlan',
      'previewTracksideApPlan',
      'useTaskStore',
      'locked',
      '解锁',
      'setTimeout',
      'allow-create',
      '<el-table',
    ]) expect(source).not.toContain(forbidden)
  })

  it('keeps all table sizing in planColumns and removes numeric step controls structurally', () => {
    for (const column of [
      "key: 'sequence_no', label: '序号', valueType: 'number', width: 72, align: 'center', hideable: false",
      "key: 'station_name', label: '车站名称', valueType: 'name', minWidth: 260, align: 'left', hideable: false",
      "key: 'planned_ap_count', label: 'AP数量', valueType: 'number', width: 110, align: 'center'",
      "key: 'management_vlan', label: 'AP管理VLAN', valueType: 'number', width: 130, align: 'center'",
      "key: 'remark', label: '备注', valueType: 'description', minWidth: 360, align: 'left'",
      "key: 'relation_status', label: '关联状态', valueType: 'status', width: 120, align: 'center'",
      "key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 48, align: 'center'",
      "key: 'actions', label: '操作', valueType: 'actions', width: 64, align: 'center', fixed: 'right'",
    ]) expect(source).toContain(column)

    expect(source.match(/<el-input-number/g)).toHaveLength(3)
    expect(source.match(/:controls="false"/g)).toHaveLength(3)
    expect(source).not.toContain('el-input-number__increase')
    expect(source).not.toContain('el-input-number__decrease')
    expect(source).toContain('.plan-cell :deep(.el-input-number),')
    expect(source).toContain('width: 100%; min-width: 0; box-sizing: border-box;')
  })
})
