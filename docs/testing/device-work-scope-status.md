# 设备建设阶段与当前工作状态测试说明

## 自动化验证

在仓库工作树中使用项目虚拟环境执行：

```powershell
& 'D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe' -m pytest `
  tests/test_device_work_scope_status.py `
  tests/test_device_management_web_api.py `
  tests/test_device_import_export.py `
  tests/test_device_repository.py `
  tests/test_database.py `
  tests/test_config_collection_web_api.py `
  tests/test_ground_unattended_foundation.py `
  tests/test_ground_unattended_eligibility.py -q

Set-Location apps/desktop_renderer
pnpm exec vitest run `
  src/views/devices/DeviceManagementView.mount.test.ts `
  src/views/devices/DeviceManagementView.test.ts `
  src/components/device-detail/DeviceDetailPanel.mount.test.ts `
  src/views/config-collection/ConfigCollectionView.test.ts
pnpm build
```

测试使用 `RuntimeMode.TEST` 和隔离临时数据库，不得连接真实局点或真实设备。

## 人工验收

1. 启动 Electron，打开设备管理，确认默认当前工作状态为“参与当前调试”，迁移前设备仍显示。
2. 新建测试设备，确认默认建设阶段“未指定”、当前工作状态“参与当前调试”。
3. 手工选择测试用一期设备，批量设置“一期 + 暂不参与”并填写原因。不要按名称编号或 IP 范围自动选择。
4. 返回默认列表，确认该设备不显示；切换“全部”及“一期 + 暂不参与”，确认设备、原因和更新时间仍可见。
5. 对暂不参与设备执行连接测试、详情刷新、配置采集和外部终端，确认明确的手动任务可提交。
6. 检查无人值守、AC 与轨旁 AP 自动候选，确认暂不参与设备不会自动入选。
7. 检查设备详情和报告，确认暂不参与设备不会被描述为停运、退役或未并网，实际连接与采集状态仍独立显示。
8. 将测试设备改回“参与当前调试”，确认无需重启即可恢复默认显示和自动候选。
9. 导出 CSV，确认包含“建设阶段”“当前工作状态”“当前工作状态说明”；用上一版“投运状态”模板导入时按兼容映射处理，新模板空状态单元格更新时保留原值。
10. 重启 Electron，复核状态持久化，并确认设备 ID、UUID、地址、凭据、配置快照和任务历史未变化。

真实验收仅操作明确指定的测试设备。本功能交付和自动化测试不得替用户设置真实一期或二期设备状态。
