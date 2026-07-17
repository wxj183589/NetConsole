import { describe, expect, it } from 'vitest'

import source from './CarNetworkPointTableDialog.vue?raw'

describe('car network point table dialog', () => {
  it('covers the Qt editing, import, rule, task, recovery and export controls', () => {
    for (const contract of [
      'getCarNetworkPointTable', 'previewCarNetworkPointTable', 'transformCarNetworkPointTable',
      'saveCarNetworkPointTable', 'generateCarNetworkPointTable', 'exportCarNetworkPointTable',
      'recoverCarNetworkPointTableTasks', "openTaskWindow({ module: 'rail'",
      '新增行', '删除行', '地址映射并应用', '从设备管理生成', '保存全局规则',
      '应用全局规则', '应用并覆盖自定义行', '恢复默认映射', '导入并预览',
      '重复时覆盖', '重复时跳过', '重复时报错', '锁定并保存', '解锁并保存',
      'web.rail_car_network_point_table_write', 'web.rail_car_network_point_table_export',
    ]) expect(source).toContain(contract)
    expect(source).not.toContain('cancelCarNetworkPointTableTask')
  })
})
