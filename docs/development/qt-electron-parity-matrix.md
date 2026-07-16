# Qt → Electron 功能对等矩阵

## 目的与事实来源

本文按当前 Qt 源码、Vue 路由、FastAPI Router、Application Service 和测试记录判断迁移状态，不以“页面已经存在”作为完成依据。审计基线为 `main@901e2529`，设备管理第一批整改位于 `codex/electron-device-qt-parity-1to1`。

正式产品入口固定为：

```text
Electron Desktop → Vue → FastAPI → Application Service → Domain / Infrastructure
```

- Electron Desktop 是永久桌面产品和 Qt 业务迁移目标。
- Qt 是迁移期生产与回退入口；模块达到 `COMPLETE` 前不得隐藏或删除对应 Qt 页面。
- 普通浏览器只保留开发、诊断和 API 联调能力，不再作为独立产品形态，不要求单独的功能对等、发布打包或人工验收。
- Vue、FastAPI 和 Application Service 仍然只有一套；取消浏览器产品入口不等于复制一套 Electron 页面。
- Electron main/preload 只提供窗口、Python Core 生命周期和白名单本机能力，不实现业务规则。

核心证据入口：

- Qt 页面：`src/netconsole/ui/pages/`、`src/netconsole/ui/dialogs/`、`src/netconsole/ui/widgets/`
- Electron 页面：`apps/web/src/router/routes.ts`、`apps/web/src/views/`
- 导航状态：`apps/web/src/navigation/registry.ts`
- API：`src/netconsole/backend/api/`
- 永久业务层：`src/netconsole/services/`、`src/netconsole/application/`
- 功能开关：`src/netconsole/core/feature_registry.py`

## 唯一状态枚举

| 状态 | 判定 |
| --- | --- |
| `NOT_STARTED` | 没有对应 Electron 业务入口或闭环。 |
| `UI_ONLY` | 只有静态页面或前端临时状态。 |
| `READ_ONLY` | 读取真实数据，但 Qt 中的操作闭环未迁移。 |
| `FAKE` | 仍以 Fake 数据、Fake 执行或模拟成功作为主要证据。 |
| `PARTIAL` | 已有部分真实操作，但缺少 Qt 可见能力、状态恢复、导入导出或错误闭环。 |
| `IMPLEMENTED_UNVERIFIED` | Qt 可见能力已形成真实调用链并有自动化证据，尚未完成人工 Qt/Electron 对照。 |
| `REAL_DEVICE_PENDING` | 人工软件流程已通过，只剩真实设备、Agent 或现场环境验收。 |
| `COMPLETE` | Qt 操作、真实 Application Service、自动测试、人工对照及所需真实设备验收全部通过。 |
| `BLOCKED` | 由明确产品决策、缺失授权或不可用环境冻结。 |

`COMPLETE` 必须同时满足：Qt 已有操作全部存在；无 Fake；调用真实 Application Service；自动测试通过；人工业务流程通过；需要设备的功能已完成真实设备验收。任何一项缺失都不能使用 `COMPLETE`。

## 模块来源与能力矩阵

| 模块 | Qt 导航路径 | Qt 页面类/源码 | Electron 路由/组件 | Qt 可见操作与业务能力 | Application Service / FastAPI | Electron 当前状态 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dashboard | 首页 | 主窗口聚合入口 | `/` / `DashboardView.vue` | 全局状态入口 | 当前仅导航和状态壳 | 占位内容，未形成 Qt 对等首页 | `UI_ONLY` |
| 设备管理 | 设备管理 | `DeviceManagementPage`：`src/netconsole/ui/pages/device_management_page.py`；相关 Dialog/Widget 见专项文档 | `/network/devices` / `DeviceManagementView.vue` | 列表、筛选、分页、当前页选择、CRUD、分组、连接测试、采集、详情/历史、终端、CSV/SecureCRT/OmniPeek | `DeviceManagementWebService`；`device_management_router.py` | 真实数据库、Task、Export Process 和 Desktop Action 已接入；未保存表单通过不落盘的一次性回环秘密通道测试；诊断与全部导出产生受控 Artifact；页面任务私有持久化已删除，统一任务窗口依赖尚未合入 | `PARTIAL / BLOCKED_ON_TASK_WINDOW` |
| AC 管理 | AC 管理及其子页 | `AcManagementPage`、`TracksideApPlanPage`、`TracksideApServicePage` | `/ac-management/*` / `views/ac-management/` | FIT-AP、光衰、扩展、Mesh、规划和受控 AC 操作 | AC Query/Application Service；AC Router | 查询、部分受控动作和 Fake 能力并存，独立页面仍缺失 | `PARTIAL` |
| 轨道交通 | 轨道交通及其子页 | `RailTransitPage`、`CarNetworkDiagnosticPage`、`OnlineMrCollectionPage`、`MeshLogAnalysisPage` 等 | `/rail-transit/*` / `views/rail-transit/` | 基础资料、在线列车、车地通信、车内检测、Online MR、Mesh 分析和报告 | Rail/Online MR/Mesh Application Service；相关 Router | 只读、部分控制和 Fake 状态并存，尚未逐模块完成纵向闭环 | `PARTIAL` |
| 配置采集中心 | 配置采集中心 | `ConfigCollectionCenterPage`：`src/netconsole/ui/pages/config_collection_center_page.py` | `/config-center` / `ConfigCollectionView.vue` | 采集、保存、比较、历史、导出和目录动作 | `ConfigCollectionApplicationService`；Config Router | 多项真实操作已接入，尚未完成 Qt 全量人工对照 | `PARTIAL` |
| 文件管理 | 文件管理 | `FileManagementPage`：`src/netconsole/ui/pages/file_management_page.py` | `/file-manager` / `FileManagementView.vue` | 本地与设备文件、连接、导航、传输、进度和取消 | `FileManagementApplicationService`；File Router | 本地浏览和受控只读远程下载已有，未达到双窗格完整对等 | `PARTIAL` |
| 网络工具 | 网络工具 | `NetworkToolsPage`、`NetworkToolboxPage`、`IperfBandwidthPage`、`WirelessScanPage` | `/network-tools/*` / `views/network-tools/` | Ping/fping/TCP、iPerf、Traffic、小工具、无线扫描、任务停止和导出 | Network/Traffic Application Service；Network/Traffic Router | 多个真实闭环已有，真实 Agent/无线硬件和 Qt 全量对照未完成 | `PARTIAL` |
| 无线扫描 | 网络工具 → 无线扫描 | `WirelessScanPage` | 规划归属网络工具，当前无独立正式路由 | 扫描、项目、结果和导出 | Wireless Scan Job/Export | 自动化与 Fake 证据为主，真实无线硬件未验收 | `FAKE` |
| 任务中心 | Qt 中分散任务进度 | 多个进度 Dialog/Worker | `/tasks` / `JobCenterView.vue` | 列表、详情、日志、取消、恢复 | `TaskApplicationService`、`JobCenterQueryService`；Job Router | 通用任务中心真实可用，但需随业务模块逐项验收 | `PARTIAL` |
| Agent 管理 | 无完整 Qt 一级入口 | Online MR Agent 相关 Dialog | `/agents` / `AgentListView.vue` | Profile、健康、工具、任务、包和远程执行入口 | Agent Controller Service；Agent Router | 真实 Controller 路径与 Fake 验收并存，真实 Agent 环境未通过 | `PARTIAL` |
| 命令说明 | 命令说明 | `CommandReferencePage` | 规划 `/command-reference`，未注册正式组件 | 命令参考查询 | 未形成永久 API/页面闭环 | 未开始 | `NOT_STARTED` |
| 日志中心 | 日志 | `AppLogPage` | 规划 `/logs`，未注册正式组件 | 日志分页、筛选和查看 | 未形成永久 API/页面闭环 | 未开始 | `NOT_STARTED` |
| 系统设置 | 设置 | `SettingsPage` | 规划 `/settings`，未注册正式组件 | 本机路径、工具、主题和运行参数 | Desktop Settings / Native Bridge 待收敛 | 未开始 | `NOT_STARTED` |
| 功能开关 | 功能开关配置 | `FeatureFlagsPage` | 规划 `/feature-flags`，内部入口未实现 | Feature 状态查看和配置 | Feature Registry / Gate | 未开始 | `NOT_STARTED` |
| SNMP Center | SNMP 中心 | `SnmpCenterPage` 及 SNMP 子页 | 无 Electron 正式入口 | 旧 SNMP 中心能力 | 保留历史代码 | 当前不迁移；如重启需独立立项 | `BLOCKED` |
| 无线勘测 | 无线勘测 | `WifiSurveyPage` | 无 Electron 正式入口 | 旧勘测能力 | 保留历史代码 | 当前不迁移；如重启需独立立项，与无线扫描不同 | `BLOCKED` |

## 验收矩阵

| 模块 | UI 对等 | 功能对等 | 导入/导出 | 实时任务、停止与恢复 | 自动测试证据 | 人工验收 | 真实设备验收 | 当前缺口 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 设备管理 | 模块侧纵向闭环已实现，待统一任务窗口与人工对照 | 真实 CRUD/分组/已保存及未保存表单连接测试/采集/终端链路；表单秘密仅经一次性回环通道 | CSV 重复策略与确认；诊断 ZIP；CSV/模板/SecureCRT/OmniPeek 实际 Artifact；Electron 授权路径打开/定位 | 后端 Task 持久化、页面当前会话轮询/取消；统一任务窗口重启恢复待共享分支 | `tests/test_device_management_web_api.py`、`tests/test_device_import_export.py`、`tests/test_desktop_action_service.py`、`DeviceManagementView.test.ts` | `NOT_STARTED` | SSH/Telnet/SNMP、采集、光模块、诊断下载及三类终端软件均待现场/本机验证 | `BLOCKED_ON_TASK_WINDOW`；人工同数据对照与现场结果 |
| AC 管理 | 部分 | 部分/Fake | 部分 | 部分 | 现有 AC 定向测试 | `NOT_STARTED` | `NOT_STARTED` | 规划、光衰独立页、真实写操作和现场验收 |
| 轨道交通 | 部分 | 只读/部分/Fake 混合 | 部分 | 部分 | 现有 Rail/Online MR/Mesh 定向测试 | `NOT_STARTED` | 列车下电期间冻结 | 不得以聚合看板代替 Qt 业务页 |
| 配置采集中心 | 部分 | 部分真实 | 已有 | 已有部分 | 现有 Config 定向测试 | `NOT_STARTED` | 待真实设备 | Qt 全操作、错误和恢复对照 |
| 文件管理 | 部分 | 部分真实 | 受控下载已有 | 部分 | 现有 File 定向测试 | `NOT_STARTED` | 待 SFTP 设备 | 双窗格、传输队列和异常恢复 |
| 网络工具 | 部分 | 部分真实 | 部分 | 部分 | 现有 Network/Traffic 定向测试 | `NOT_STARTED` | Agent/无线硬件待验收 | 逐工具纵向闭环与 Qt 对照 |
| 任务中心 | Web 原生页面 | 部分 | 不适用 | 真实 Task 状态机 | Job Center 定向测试 | `NOT_STARTED` | 随业务任务验收 | 不作为业务模块完成的替代证据 |
| Agent 管理 | 部分 | 部分/Fake | Agent 包已有 | 部分 | Agent Controller/Fake 测试 | `NOT_STARTED` | `NOT_STARTED` | 真实 Agent、多 Controller 和现场失败恢复 |
| 命令说明、日志中心、系统设置、功能开关 | 否 | 否 | 否 | 否 | 无对等证据 | `NOT_STARTED` | 不适用 | 尚未迁移 |
| SNMP Center、无线勘测 | 不迁移 | 不迁移 | 不迁移 | 不迁移 | 不纳入 | 不纳入 | 不纳入 | `BLOCKED` |

## 当前推进规则

1. 一次只把一个 Qt 模块做成完整纵向切片，不横向增加只读页面。
2. 自动测试先定向；进入集成和合并前再运行全量 Python、Vue、Electron、Ruff、构建和文档检查。
3. 当前设备管理只能标记 `PARTIAL / BLOCKED_ON_TASK_WINDOW`。未保存表单连接测试已完成模块侧真实 Job 链路；统一任务窗口依赖合入并完成人工对照、但现场设备未通过时，才升级为 `REAL_DEVICE_PENDING`；全部通过后才能升级为 `COMPLETE`。
4. 浏览器开发入口不得产生独立导航、业务分支、发布包或验收矩阵；Native 功能只在 Electron 中开放。
