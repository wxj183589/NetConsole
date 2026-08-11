# Electron Desktop Only 收敛记录

本文记录 `codex/electron-desktop-only` 对 `github/main@61851f7c` 的架构收敛基线、阶段回归和最终证据。事实优先级为生产代码、测试、构建输出和 smoke；未执行真实设备或安装器人工验收的项目不得标记为完成。

## 固定决策

- 唯一正式 GUI 产品为 Electron Desktop；Vue/Vite 只承担 Desktop Renderer 开发和构建。
- Renderer 继续通过 REST/WebSocket 使用 Python Backend；Agent、Syslog、无人值守、Remote MR、SSH/SNMP 等远程业务不是 Web 产品。
- 本次按 Clean Install 验收，不兼容旧安装状态、旧 `web.*` Feature 配置或旧 Renderer 本地状态，不建立 Legacy Feature Alias。
- 业务 Data Root、业务数据库 schema、设备/轨交/MESH/MR/Agent/任务数据契约均不因本次迁移改变。
- 每个高风险阶段设置 Regression Gate；本次引入的回归修复前不得进入下一阶段。

## Worktree 基线

| 项目 | 值 |
| --- | --- |
| Worktree | `D:/study/NetConsole-worktrees/electron-desktop-only` |
| Branch | `codex/electron-desktop-only` |
| Remote | `github` |
| Base | `github/main@61851f7c7ae2784ee54ff47f1c554d37d02c447d` |
| 初始 HEAD | `61851f7c7ae2784ee54ff47f1c554d37d02c447d` |

## BEFORE Function Matrix

| 功能 | 入口/调用链 | Feature Gate 基线 | Native 依赖 | 自动证据 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| Dashboard/工作区 | Vue 根路由、标签、附加工作区窗口 | 无独立业务 Gate | Electron 窗口/托盘 | Renderer/Electron 测试、源码 smoke | AVAILABLE |
| 设备管理与详情 | `/network/devices`、设备 REST API | `module.devices` + 旧设备 `web.*` 子项 | 文件选择、外部终端 | Renderer、Python API 测试 | AVAILABLE |
| 设备连接测试 | 设备列表及未保存表单 | V1 `web.*` 子项 | 无 | Renderer、Python API 测试 | AVAILABLE |
| 设备导入导出/采集 | 设备页、Task/Artifact API | 旧设备 import/export/collect Gate | 文件选择、Save As | Renderer、Python API/导出测试 | AVAILABLE |
| AC/FIT-AP | `/ac-management/*`、AC REST/Task API | `module.ac` + 旧 AC `web.*` 子项 | 外部终端、打开外部管理页 | Renderer、Python AC 测试 | AVAILABLE; REAL_DEVICE_PENDING |
| 配置采集与 Monaco Diff | `/config-center`、配置快照/导出 API | `module.config_collection` + 旧 `web.*` 子项 | Save As、打开目录 | Renderer、Python 配置测试 | AVAILABLE |
| 设备文件管理 | `/device-files`、SFTP/下载 API | `module.file_management` + 旧 `web.*` 子项 | 目录选择、受管下载 | Renderer、Python 文件测试 | AVAILABLE |
| 轨交基础资料 | `/rail-transit/base-data`、基础资料 API | `module.rail_transit` + 旧基础资料 Gate | 导入、模板导出 | Renderer、Python 基础资料测试 | AVAILABLE |
| 列车在线 | `/rail-transit/train-online`、列车状态/Task API | 旧列车在线 Gate + 隐藏依赖 | 导入导出 | Renderer、Python 轨交测试 | AVAILABLE |
| 地面无人值守 | `/rail-transit/ground-unattended`、调度/归档 API | 旧无人值守 Gate + 隐藏依赖 | 会话/归档文件 | Renderer、Python 无人值守测试 | AVAILABLE; REAL_DEVICE_PENDING |
| 车内通信检测 | `/rail-transit/train-communication`、Task API | 旧通信检测及动作 Gate | 点表导入导出 | Renderer、Python 通信测试 | AVAILABLE |
| 轨旁 AP 业务 | `/rail-transit/trackside-ap-business`、业务/导出 API | 旧轨旁 AP Gate | 外部终端、导出 | Renderer、Python 轨旁 AP 测试 | AVAILABLE |
| MESH 日志分析 | `/rail-transit/mesh-analysis`、MESH API | 旧 MESH 页面/动作 Gate | 原始日志导入、报告保存 | Renderer、Python MESH 测试 | AVAILABLE |
| Online MR 收集/分析 | `/rail-transit/online-mr*`、REST/WebSocket/Task | 旧 Online MR 页面/动作 Gate + 隐藏依赖 | 会话目录、报告保存 | Renderer、Python Online MR 测试 | AVAILABLE; REAL_DEVICE_PENDING |
| Agent 管理 | `/agents`、Agent Controller API | 旧 Agent 页面 Gate + Task 依赖 | 无 | Renderer、Python Agent 测试 | AVAILABLE |
| 任务中心 | `/tasks`、Task REST/WebSocket | 旧任务中心 Gate + Task 依赖 | Electron 任务通知 | Renderer、Python/Electron 测试 | AVAILABLE |
| 工具集/流量测试 | `/tools/*`、Traffic/Network API | `module.tools`、`module.network_tools` 与旧页面 Gate | 外部工具 Native Bridge | Renderer、Python/Agent 测试 | AVAILABLE |
| 日志与系统维护 | `/logs`、维护/Artifact API | `module.logs`、`module.system_settings` 与旧 Gate | 打开目录、Artifact 保存 | Renderer、Python 测试 | AVAILABLE |
| Customer/Full | Profile、Shift 解锁、构建准备 | V1 Registry/Profile | Electron 打包链 | Feature/Profile/Electron 测试 | AVAILABLE |
| Python Backend | 受管 Electron Backend | FeatureGate + Application Services | Electron lifecycle | Python/Electron 测试、源码 smoke | AVAILABLE |
| REST/WebSocket | Renderer -> Backend、Task/Traffic 等 WS | Backend Gate | 回环 Session Token | Python/Renderer/Electron smoke | AVAILABLE |
| Agent/Syslog/Remote MR | 独立远程业务监听与采集 | 对应业务 Gate | 无 GUI 依赖 | Python/Go 既有测试 | PRESERVED; NOT CHANGED |
| 业务 Data Root | `PathResolver` -> 独立业务根 | 不属于 Renderer Feature | HKLM 指针/显式覆盖 | 数据路径既有测试 | PRESERVED; NOT CHANGED |

## Gate 0：修改前实际验证

| 命令 | 结果 | 计数/说明 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/test_feature_flags.py tests/test_feature_registry_groups.py tests/test_edition_access.py tests/test_ac_formal_feature_profile.py tests/test_prepare_electron_edition.py tests/test_backend_release_script.py -q` | PASS | `67 passed` |
| `pnpm test -- --maxWorkers=2`（迁移前 `apps/web`） | PASS | `168 files / 1157 tests`；退出后打印本机 `3000` 端口 `ECONNREFUSED` 基线警告 |
| `pnpm build`（迁移前 `apps/web`） | PASS | Vue TypeScript 与 Vite production build 完成；仅有既有大 chunk 警告 |
| `pnpm test`（`apps/desktop_electron`） | PASS | `32 files / 255 tests` |
| `pnpm run build:main`（`apps/desktop_electron`） | PASS | typecheck、Main/Preload build 完成 |
| `pnpm smoke:dev`（`apps/desktop_electron`） | PASS | Backend ready、Renderer 加载、`SHUTDOWN_STARTED -> DOWNLOADS_STOPPED -> BACKEND_STOPPED -> EXIT_REQUESTED -> EXIT_RETURNED`；存在既有 Element Plus `role` 警告 |

Gate 0 Registry 事实：旧配置含 `89` 个 `web.*` ID。V2 允许合并重复/实现细节 Feature 和移除已证明无业务消费者的独立 Browser Production Feature；除此以外不得扩大 Customer 或缩减 Full 业务能力。

## 阶段状态

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| Gate 0 Baseline | PASS | 上述测试、构建、源码 Electron smoke |
| Gate 1 Feature Registry V2 | PASS | `79 passed, 1 warning`；Registry 与两个 Profile 均为 schema 2，键集严格覆盖 `140` 个 V2 ID |
| Gate 2 Desktop Renderer 路径迁移 | PASS | Renderer `168 files / 1157 tests`、production build；Electron typecheck、`32 files / 255 tests`、源码 smoke；Python `68 passed, 1 warning` |
| Gate 3 Browser Production 清理 | PASS | 后端 `67 passed, 1 warning`、Renderer 开发适配 `19 passed`、Electron `32 files / 255 tests`、源码 smoke |
| 最终 Customer/Full/Package/Installer | PENDING | 待补 |

## V2 Feature Registry

V2 是唯一正式 Feature Registry。它有 `140` 个 ID：`22` 个 `module.*`、`76` 个 `capability.*`、`7` 个 `internal.*`，以及既有领域内部 ID。`web.*` 为零；不存在 `LEGACY_FEATURE_ALIASES`、旧 Profile 迁移或旧 `customer.json` 兼容入口。Customer 与 Full 都以 schema 2 显式覆盖同一 `140` 个键；Customer 的表单连接测试保持关闭，Full 开启，已由 API 与 Renderer Gate 覆盖。

下表记录全部 V1 `web.*` 的业务去向。这里的“收敛到已有 module”表示旧页面 Gate 被其正式模块 Gate 取代，不保留别名。

| V1 `web.*` | V2 正式 ID | 处理 |
| --- | --- | --- |
| `web.agent_management` | `module.agent` | 收敛模块 |
| `web.job_center` | `module.task_center` | 收敛模块 |
| `web.device_management` | `module.devices` | 收敛模块 |
| `web.device_connection_test` | `capability.devices.connection_test` | 已保存设备测试 |
| `web.device_form_connection_test` | `capability.devices.form_connection_test` | 未保存表单测试，独立于已保存测试 |
| `web.device_management_write`、`web.device_management_collect`、`web.device_management_import`、`web.device_management_export`、`web.device_management_desktop` | `capability.devices.write`、`capability.devices.collect`、`capability.devices.import`、`capability.devices.export`、`capability.devices.desktop_actions` | 动作 Capability |
| `web.config_collection` | `module.config_collection` | 收敛模块 |
| `web.config_collection_fetch`、`web.config_collection_diff`、`web.config_collection_download`、`web.config_collection_delete`、`web.config_collection_save_force`、`web.config_collection_export`、`web.config_collection_open_directory` | `capability.config_collection.fetch`、`capability.config_collection.diff`、`capability.config_collection.download`、`capability.config_collection.delete`、`capability.config_collection.save_force`、`capability.config_collection.export`、`capability.config_collection.open_directory` | 动作 Capability |
| `web.file_management` | `module.file_management` | 收敛模块 |
| `web.file_management_download`、`web.file_management_local_write`、`web.file_management_remote`、`web.file_management_desktop_actions` | `capability.file_management.download`、`capability.file_management.local_write`、`capability.file_management.remote`、`capability.file_management.desktop_actions` | 动作 Capability |
| `web.network_tools` | `module.network_tools` | 收敛模块 |
| `web.network_tools_toolbox`、`web.network_tools_wireless_scan`、`web.network_test_components`、`web.network_tools_tcp_port_test` | `capability.network_tools.toolbox`、`capability.network_tools.wireless_scan`、`capability.network_tools.components`、`capability.network_tools.tcp_port_test` | 工具 Capability |
| `web.tool_collection` | `module.tools` | 收敛模块 |
| `web.ac_management`、`web.ac_fit_ap_resources` | `module.ac`、`module.fit_ap` | 收敛模块 |
| `web.ac_online_overview`、`web.ac_optical`、`web.ac_extensions`、`web.ac_extensions_preview`、`web.ac_extensions_apply`、`web.ac_extensions_rollback`、`web.ac_extensions_export`、`web.ac_refresh` | `capability.ac.online_overview`、`capability.ac.optical`、`capability.ac.extensions`、`capability.ac.extensions.preview`、`capability.ac.extensions.apply`、`capability.ac.extensions.rollback`、`capability.ac.extensions.export`、`capability.ac.refresh` | AC Capability |
| `web.ac_fit_ap_delete`、`web.ac_fit_ap_metadata_import`、`web.ac_fit_ap_metadata_write`、`web.ac_fit_ap_history`、`web.ac_fit_ap_resource_export`、`web.ac_fit_ap_external_terminal` | `capability.ac.fit_ap.delete`、`capability.ac.fit_ap.metadata_import`、`capability.ac.fit_ap.metadata_write`、`capability.ac.fit_ap.history`、`capability.ac.fit_ap.resource_export`、`capability.ac.external_terminal` | FIT-AP Capability |
| `web.ac_open_web`、`web.ac_dangerous_actions`、`web.ac_config_snapshots` | `capability.ac.open_management`、`capability.ac.dangerous_actions`、`capability.ac.config_snapshots` | AC Capability；名称不代表 Browser 产品 |
| `web.online_mr_realtime`、`web.online_mr_analysis` | `module.online_mr`、`module.online_mr_analysis` | 收敛模块 |
| `web.online_mr_report_export`、`web.online_mr_parse`、`web.online_mr_session_open_location`、`web.online_mr_session_delete`、`web.online_mr_local_control`、`web.online_mr_agent_control` | `capability.online_mr.report_export`、`capability.online_mr.parse`、`capability.online_mr.open_location`、`capability.online_mr.session_delete`、`capability.online_mr.local_control`、`capability.online_mr.agent_control` | Online MR Capability |
| `web.rail_transit_base_data`、`web.train_communication_monitoring`、`web.rail_train_online`、`web.ground_unattended`、`web.mesh_analysis`、`web.rail_trackside_ap_business` | `module.rail_base_data`、`module.train_communication`、`module.train_online`、`module.ground_unattended`、`module.mesh_analysis`、`module.trackside_ap` | 收敛业务模块 |
| `web.rail_transit_base_data_write`、`web.rail_task_control`、`web.rail_transit_wireless_dashboard` | `capability.rail_base_data.write`、`capability.rail_transit.task_control`、`capability.rail_transit.wireless_dashboard` | 轨交 Capability |
| `web.rail_train_online_refresh`、`web.rail_train_online_collect`、`web.rail_train_online_history_export`、`web.rail_train_online_mapping_write`、`web.rail_train_online_mapping_import`、`web.rail_train_online_mapping_export` | `capability.train_online.refresh`、`capability.train_online.collect`、`capability.train_online.history_export`、`capability.train_online.mapping_write`、`capability.train_online.mapping_import`、`capability.train_online.mapping_export` | 列车在线 Capability |
| `web.rail_car_network_diagnostic`、`web.rail_car_network_diagnostic_execute`、`web.rail_car_network_point_table_write`、`web.rail_car_network_point_table_export` | `module.train_communication`、`capability.train_communication.diagnostic_execute`、`capability.train_communication.point_table_write`、`capability.train_communication.point_table_export` | 车内通信 Capability |
| `web.mesh_analysis_import`、`web.mesh_analysis_report_export` | `capability.mesh.import`、`capability.mesh.report_export` | MESH Capability |
| `web.rail_trackside_ap_business_update`、`web.rail_trackside_ap_business_export`、`web.rail_trackside_ap_business_wps_sync`、`web.rail_trackside_ap_plan`、`web.rail_trackside_ap_plan_write`、`web.rail_trackside_ap_plan_export`、`web.rail_trackside_ap_base_io` | `capability.trackside_ap.update`、`capability.trackside_ap.export`、`capability.trackside_ap.wps_sync`、`capability.trackside_ap.plan`、`capability.trackside_ap.plan_write`、`capability.trackside_ap.plan_export`、`capability.trackside_ap.base_io` | 轨旁 AP Capability |
| `web.command_reference`、`web.logs`、`web.system_settings`、`web.feature_switch` | `module.command_reference`、`module.logs`、`module.system_settings`、`internal.feature_switch` | 收敛模块/内部开关 |
| `web.logs_export` | `capability.logs.export` | 日志导出 Capability |

## AFTER Function Matrix

| 功能域 | Before | After | 验证 |
| --- | --- | --- | --- |
| 设备管理、连接测试、导入导出、外部终端 | AVAILABLE | AVAILABLE | Feature Gate #1、API/Renderer Gate |
| AC/FIT-AP、配置采集、文件管理 | AVAILABLE | AVAILABLE | Feature/Profile、Renderer/Electron Gate |
| 轨交基础资料、列车在线、无人值守、车内通信、轨旁 AP、MESH、Online MR | AVAILABLE | AVAILABLE | Feature Gate #1、Renderer/Electron Gate |
| Agent、任务中心、日志、工具集、Traffic、REST/WebSocket | AVAILABLE | AVAILABLE | Feature Gate #1、Electron smoke |
| Python Backend、业务 Data Root | AVAILABLE | AVAILABLE；未改 schema/路径契约 | 代码审计、Python/Electron Gate |

## Browser Production 与 Listener 审计

| 项目 | 处理 | 证据 |
| --- | --- | --- |
| 独立 Browser Production launcher | 删除 | `launcher.py` 不再接受 `--mode web`，无 `webbrowser`、bootstrap HTML 或 `RuntimeMode.DESKTOP` 分支 |
| FastAPI Renderer 静态资源、REST/WebSocket | 保留 | Electron 受管 Backend 通过 loopback URL 装载打包 Renderer |
| Vite、`browser-adapter.ts`、浏览器下载 fallback | 保留为开发/测试能力 | 不是正式 GUI Runtime |
| Electron Backend | `127.0.0.1:0`，未改 | Electron 本机受管服务，需要临时 session token |
| Agent HTTP、Syslog、Remote MR、无人值守、iPerf | bind 未改 | 有远程采集/接入职责，无法证明仅服务本机 UI |

## Removed Components

| 组件 | 删除理由 | Electron 替代 | 证据 |
| --- | --- | --- | --- |
| `launcher.py --mode web` | 唯一独立 Browser Production 入口 | Electron Main -> 受管 Python Backend -> Desktop Renderer | 无 Electron/业务消费者；Gate #3 通过 |
| `_open_browser_shell()` 与 `web-console-*.html` | 只为浏览器打开临时 bootstrap | Electron `loadURL()` 到受管 Renderer | 仅由已删除的 `--mode web` 调用 |

最终 Customer/Full package、installer、package smoke 与 Clean Install 证据将在对应构建 Gate 完成后补充；本次不进行旧安装、旧 Feature Profile、旧 UI 本地状态或业务数据迁移。
