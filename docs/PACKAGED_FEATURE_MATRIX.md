# 正式 Electron 包功能矩阵

本矩阵用于 v1.4.4 跨电脑交付门禁。`release included=是` 表示功能代码、页面和 API 属于正式构建契约，不代表已经完成真实 Windows/真实设备人工验收。自动测试不能替代 NSIS 安装、跨电脑导入或现场 SSH。

## 功能基线解析契约

| 运行环境 | 功能基线来源 | 外部 runtime 配置 | 基线缺失或损坏 |
| --- | --- | --- | --- |
| 正式 Electron 包 | 包内只读 `customer/production` 基线 | 忽略外部 `build_info.json`、任意 schema 版本的 `feature_flags.json` 及 `feature_flags.local.json` | 回退 Feature Registry 的稳定生产默认，并记录 `PACKAGED_FEATURE_POLICY_FALLBACK` |
| 源码开发态 | 开发构建信息、外部 runtime 配置与 Registry | 按现有开发配置语义读取；支持本地可见性/启用状态覆盖 | 回退开发态 Registry 默认 |

因此，正式包不能通过外部 schema 禁用固定生产功能，也不能重新启用 `DEVELOPMENT`、`HIDDEN`、`DISABLED` 或 internal-only 能力。`client_package` 仍只表示构建/发布元数据，不是正式运行时的通用权限开关。

## 必要生产功能

| 功能 ID | 中文名称 | Registry status | visible | enabled | internal_only | release included | 正式包预期 | API | 页面 | 定向自动证据 | 人工验收 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `web.device_management` | 设备管理 | `ENABLED` | 是 | 是 | 否 | 是 | 可见、可查询 | `/api/device-management/devices` | `/devices` | `test_device_management_web_api.py`、`DeviceManagementView*.test.ts` | `PENDING` |
| `web.device_connection_test` | 已保存设备连接测试 | `ENABLED` | 是 | 是 | 否 | 是 | 前置校验后可创建任务 | `/api/device-management/devices/{id}/connection-tests` | `/devices` | `test_device_management_web_api.py` | `PENDING` |
| `web.device_form_connection_test` | 未保存表单连接测试 | `ENABLED` | 是 | 是 | 否 | 是 | 一次性凭据、任务参数无秘密 | `/api/device-management/devices/test-connection` | `/devices` 编辑弹窗 | `test_device_management_web_api.py`、`DeviceManagementView.test.ts` | `PENDING` |
| `web.device_management_collect` | 设备采集与诊断 | `ENABLED` | 是 | 是 | 否 | 是 | 可提交采集/诊断 | `/api/device-management/devices/*/collect` | `/devices` | `test_device_management_web_api.py`、`test_device_detail_web_api.py` | `PENDING` |
| `web.device_management_import` | 设备导入 | `ENABLED` | 是 | 是 | 否 | 是 | 可预览并受控导入 | `/api/device-management/imports/*` | `/devices` | `test_device_management_web_api.py` | `PENDING` |
| `web.device_management_export` | 设备导出 | `ENABLED` | 是 | 是 | 否 | 是 | 进入 Export Process | `/api/device-management/exports/*` | `/devices` | `test_device_management_web_api.py` | `PENDING` |
| `web.config_collection` | 配置采集中心 | `ENABLED` | 是 | 是 | 否 | 是 | 采集、比较、下载可用 | `/api/config-collection/*` | `/config-collection` | 配置采集定向 pytest/Vitest | `PENDING` |
| `web.file_management` | 文件管理 | `ENABLED` | 是 | 是 | 否 | 是 | 本地与设备文件入口可用 | `/api/file-management/*` | `/file-management` | `test_file_management_service.py` | `PENDING` |
| `web.file_management_remote` | SFTP 浏览与下载 | `ENABLED` | 是 | 是 | 否 | 是 | 受控只读远端操作 | `/api/file-management/remote/*` | `/file-management` | `test_file_management_service.py` | `PENDING` |
| `web.network_tools` | 网络工具 | `ENABLED` | 是 | 是 | 否 | 是 | toolbox/Traffic 可用 | `/api/network-tools/*`、`/api/traffic/*` | `/network-tools` | `test_network_tools_api.py`、`test_network_tools_web_parity.py` | `PENDING` |
| `web.command_reference` | 命令说明 | `ENABLED` | 是 | 是 | 否 | 是 | 可查询与受控导出 | `/api/command-reference/*` | `/command-reference` | 命令说明 API/Vitest | `PENDING` |
| `web.logs` | 日志中心 | `ENABLED` | 是 | 是 | 否 | 是 | 可查询与受控导出 | `/api/logs/*` | `/logs` | 日志 API/Vitest | `PENDING` |
| `web.job_center` | 任务中心 | `ENABLED` | 是 | 是 | 否 | 是 | 全局入口、抽屉、浮层和完整页面可用 | `/api/job-center/*`、`/ws/tasks` | `/tasks` | `test_job_center.py`、`test_task_center.py`、`GlobalTaskCenter.test.ts`、`JobCenterView.test.ts` | `PENDING` |
| `web.ac_management` | AC 管理 | `ENABLED` | 是 | 是 | 否 | 是 | 正式 AC 页面可用 | `/api/ac-management/*` | `/ac-management` | `test_ac_management.py` | `PENDING` |
| `web.ac_fit_ap_resources` | FIT-AP 资源 | `ENABLED` | 是 | 是 | 否 | 是 | 资源查询与受控动作可用 | `/api/ac-management/*` | `/ac-management` | `test_ac_management.py`、AC 动作定向测试 | `PENDING` |
| `web.rail_transit_base_data` | 轨道交通基础资料 | `ENABLED` | 是 | 是 | 否 | 是 | 查询、受控编辑与导出可用 | `/api/rail-transit/base-data/*` | `/rail-transit/base-data` | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.train_communication_monitoring` | 车内通信检测 | `ENABLED` | 是 | 是 | 否 | 是 | 固定拓扑与检测任务可用 | `/api/rail-transit/train-communication/*` | `/rail-transit/train-communication` | `test_train_communication_web_api.py` | `PENDING` |
| `web.rail_train_online` | 列车在线 | `ENABLED` | 是 | 是 | 否 | 是 | 在线状态、刷新、映射和历史导出可用 | `/api/rail-transit/train-online/*` | `/rail-transit/train-online` | `test_web_parity_foundation.py`、轨交 parity 测试 | `PENDING` |
| `web.ground_unattended` | 地面无人值守 | `ENABLED` | 是 | 是 | 否 | 是 | 时间窗口、正线分类、全车长 Ping、深度覆盖与安全归档已接线 | `/api/rail-transit/ground-unattended/*` | `/rail-transit/ground-unattended` | `test_ground_unattended_*.py`、GroundUnattended Vitest | `REAL_DEVICE_PENDING` |
| `web.online_mr_realtime` | 车载 MR 实时收集 | `ENABLED` | 是 | 是 | 否 | 是 | 实时页面和受控收集入口可用 | `/api/online-mr/*` | `/rail-transit/online-mr` | Online MR 定向 pytest/Vitest | `PENDING` |
| `web.online_mr_analysis` | 车载 MR 收集分析 | `ENABLED` | 是 | 是 | 否 | 是 | 分析页面可见 | `/api/online-mr/sessions/*` | `/rail-transit/online-mr-analysis` | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.online_mr_parse` | Online MR 解析 | `ENABLED` | 是 | 是 | 否 | 是 | 进入统一任务控制 | `/api/online-mr/sessions/{id}/parse` | Online MR 分析页 | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.online_mr_report_export` | Online MR 报告 | `ENABLED` | 是 | 是 | 否 | 是 | 进入 Export/Job 闭环 | `/api/online-mr/sessions/{id}/report` | Online MR 分析页 | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.mesh_analysis` | MR 原始 MESH 日志分析 | `ENABLED` | 是 | 是 | 否 | 是 | 分析查询页可见 | `/api/rail-transit/mesh-analysis/*` | `/rail-transit/mesh-analysis` | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.mesh_analysis_import` | MESH 导入与重建 | `ENABLED` | 是 | 是 | 否 | 是 | 可预览、导入和重建 | `/api/rail-transit/mesh-analysis/import-*` | MESH 分析页 | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.mesh_analysis_report_export` | MESH 报告与导出 | `ENABLED` | 是 | 是 | 否 | 是 | 可生成/下载派生报告 | `/api/rail-transit/mesh-analysis/*/report` | MESH 分析页 | `test_rail_transit_web_parity.py` | `PENDING` |
| `web.rail_trackside_ap_business` | 轨旁 AP 业务 | `ENABLED` | 是 | 是 | 否 | 是 | 光衰更新与导出可用 | `/api/rail-transit/trackside-ap-business/*` | `/rail-transit/trackside-ap-business` | `test_trackside_ap_business_export_web.py` | `PENDING` |
| `web.system_settings` | 系统设置与环境自检 | `ENABLED` | 是 | 是 | 否 | 是 | 设置、局点管理和自检可用 | `/api/settings/*`、`/api/settings/self-check` | `/settings` | `test_system_settings_web_api.py`、`SystemSettingsView.test.ts` | `PENDING` |

局点管理当前是 `web.system_settings` 内的正式面板，不建立第二个 Feature ID。其 API 位于 `/api/sites` 与局点包相关路由；v4 未加密完整包凭据恢复、无迁移密码/无 `payload.enc`、脱敏包清洗、checksum 篡改零发布和 `needs_reentry` 闭环由 `test_site_storage.py / test_site_storage_api.py` 验证。设备凭据显式查看和旧字段保存兼容由 `test_device_management_web_api.py / DeviceManagementView*.test.ts` 验证。

## 必须保持关闭的能力

| 功能 ID | Registry / 属性 | 正式包预期 | 自动门禁 |
| --- | --- | --- | --- |
| `module.feature_switch`、`system.feature_flags`、`web.feature_switch` | `internal_only` | 不显示、不启用、配置 API 受控拒绝 | FeatureGate pytest、设置 API pytest |
| `web.ac_online_overview`、`web.ac_extensions*`、`web.ac_config_snapshots` | `DEVELOPMENT` | 不显示、不启用 | FeatureGate pytest、构建 Gate |
| `web.online_mr_local_control`、`web.online_mr_agent_control` | `DEVELOPMENT`，未接入生产调用 | 不显示、不启用 | FeatureGate pytest |
| `web.rail_car_network_diagnostic` | 隐藏兼容、`DEVELOPMENT` | 不注册正式入口 | FeatureGate/导航测试 |

## 干净安装与跨电脑验收

| 场景 | 自动证据 | Windows 图形/跨电脑结果 |
| --- | --- | --- |
| Web production build、vue-tsc | 本分支执行 | 不适用 |
| Electron tests、typecheck、build | 本分支执行 | 不适用 |
| Backend PyInstaller、Electron unpacked package smoke | 必须从最终 clean commit 重建；包内 Backend/Web/self-check commit、UTC 时间和 dirty 状态由 smoke 与实际 HEAD 比较，结果见当次交付记录 | 不适用 |
| NSIS 安装器构建 | 最终提交推送后生成带 Git short commit 的唯一文件名；直接从 setup.exe 复核 PE Installer 身份、内嵌数据根源码及新旧文案、Backend/Frontend commit、Unicode NSIS、双次 SHA-256，并输出 `.exe.release.json`；自动构建成功不等同安装验收 | 不适用 |
| NSIS 安装、启动、卸载 | 无法由单元测试或 installer build 替代 | `PENDING` |
| 数据根不存在、为空、含普通文件、合法旧根 | 自动 Gate 只能证明最终 EXE 与源码/提交一致，不能代替向导实际分支；需核对 `HKLM\Software\NetConsole\DataRoot` 和普通文件安装前后哈希 | `PENDING` |
| 全新普通 Windows 用户、空 AppData | 环境自检逻辑与临时数据根 smoke | `PENDING` |
| 无 Python/Node/pnpm/Git/源码 | PyInstaller/Electron 制品契约 | `PENDING` |
| 中文用户名、中文安装/数据路径 | UTF-8/SQLite/REST/WebSocket 自动探针 | `PENDING` |
| 跨电脑导入 v4 完整迁移包 | 无需密码、普通 ZIP、包内完整凭据、checksum/SQLite 校验、导入恢复与直接使用包内凭据 pytest | `PENDING` |
| 导入脱敏分享包并重新录入凭据 | 包清洗、显式密码保存/清除与 `needs_reentry` pytest | `PENDING` |
| 恢复或重录凭据后的真实/仿真 H3C SSH | Repository/连接任务自动闭环 | `PENDING` |
| 中文任务 title/message/progress/log/finished | JSONL 逐字节分块、SQLite/API/WebSocket 测试 | `PENDING` |

人工项只有在最终安装包和目标 Windows 环境实际执行后才可从 `PENDING` 改为 `PASS/FAIL`。
