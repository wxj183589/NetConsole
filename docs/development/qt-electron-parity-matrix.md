# Qt → Electron 功能对等矩阵

## 目的与事实来源

本文按当前 Qt 源码、Vue 路由、FastAPI Router、Application Service 和测试记录判断迁移状态，不以“页面已经存在”作为完成依据。审计基线为 `main@901e2529`，各模块实现按顺序收敛到累计分支 `codex/electron-parity-integration`。

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
| 设备管理 | 设备管理 | `DeviceManagementPage`：`src/netconsole/ui/pages/device_management_page.py`；相关 Dialog/Widget 见专项文档 | `/network/devices` / `DeviceManagementView.vue` | 列表、筛选、分页、当前页选择、CRUD、分组、连接测试、采集、详情/历史、终端、CSV/SecureCRT/OmniPeek | `DeviceManagementWebService`；`device_management_router.py` | 真实数据库、Task、Export Process 和 Desktop Action 已接入；旧表单测试回环 token/端口已删除，当前等待共享 Runtime 非序列化 bootstrap；设备页只消费公共 tasks store/任务窗口；诊断公共 Artifact DTO 和 Electron endpoint allowlist 待共享分支接线 | `PARTIAL / BLOCKED_ON_JOB_RUNTIME / BLOCKED_ON_TASK_WINDOW` |
| AC 管理 | AC 管理及其子页 | `AcManagementPage`、`TracksideApPlanPage`、`TracksideApServicePage` | `/ac-management/*` / `views/ac-management/` | FIT-AP、光衰、扩展、Mesh、规划和受控 AC 操作 | AC Query/Application Service；AC Router | 查询、部分受控动作和 Fake 能力并存，独立页面仍缺失 | `PARTIAL` |
| 轨道交通 | 轨道交通及其子页 | `RailTransitPage`、`CarNetworkDiagnosticPage`、`OnlineMrCollectionPage`、`MeshLogAnalysisPage` 等 | `/rail-transit/*` / `views/rail-transit/` | 基础资料、在线列车、车地通信、车内检测、Online MR、Mesh 分析和报告 | Rail/Online MR/Mesh Application Service；相关 Router | 轨交 Job handler、统一任务窗口、连续采集、点表、会话备注和解析等真实纵向链路已接入；Qt 剩余按钮、Electron 人工对照和真实设备验收仍未完成，详见[轨交逐操作矩阵](parity/rail-transit.md) | `PARTIAL / IMPLEMENTED_UNVERIFIED` |
| 配置采集中心 | 配置采集中心 | `ConfigCollectionCenterPage`、`ConfigLifecycleWorker/Service`、`ConfigDiffViewer`；详见 [配置采集对等矩阵](parity/config-collection.md) | `/config-center` / `ConfigCollectionView.vue` | running/saved/diff 真实采集、`save force`、批量、历史/内容/删除、同/跨设备双栏比较、差异导航、导出/Artifact、取消/失败/恢复 | `ConfigCollectionApplicationService`；Config Router；config domain handlers | 真实纵向链、跨设备左右篮、共享任务窗口和 mount 自动化已接入；Electron 人工与真实 H3C 设备待验收 | `IMPLEMENTED_UNVERIFIED` |
| 文件管理 | 文件管理 | `FileManagementPage`：`src/netconsole/ui/pages/file_management_page.py`；详见 `development/parity/file-management.md` | `/file-manager` / `FileManagementView.vue` | 本地与设备双栏、筛选、连接、导航、传输队列、恢复、MESH 导入和桌面动作 | `FileManagementApplicationService`；File Router | 双栏与持久队列自动契约已实现；真实 SFTP/MR 待验收，原目录和 WinSCP 等待共享 Bridge | `PARTIAL` |
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
| 设备管理 | Qt 操作区、表格、表单、详情、分组、导入导出、终端和紧凑任务摘要已形成 Electron 实现 | 真实 CRUD/分组、已保存设备与未保存表单连接测试、采集、诊断、终端受控启动 | CSV 重复策略与确认；诊断 ZIP；CSV/模板/SecureCRT/OmniPeek 实际 Artifact；公共 capability DTO | 公共 Task 持久化与轮询；统一任务窗口负责停止、日志、Artifact、重试和恢复；页面不再私建任务系统 | `tests/test_device_management_web_api.py`、`tests/test_device_import_export.py`、`tests/test_local_process_adapter.py`、`tests/test_job_center_web_api.py`、`DeviceManagementView.mount.test.ts` | CRUD、导入导出、任务窗口及 SecureCRT/Xshell/PuTTY 为 `MANUAL_DESKTOP_PENDING` | SSH/Telnet/SNMP、采集、光模块和诊断待真实设备 | `IMPLEMENTED_UNVERIFIED`；人工软件流程通过后再按剩余项升级为 `REAL_DEVICE_PENDING` |
| AC 管理 | FIT-AP 主页面已接打开 AC Web、AC 信息、普通资源、AP 详情深度、光衰更新、批量删除、元数据导入/保存和 Radio/LLDP/光衰历史；受控页已接 Qt 两项 AC 写操作 | HTTPS 外部打开、四类采集、批量删除、CSV/XLSX 元数据导入、详情保存、历史分页与两项固定写操作均为真实闭环，无 AC Fake 执行 | 部分 | AC owner 已接统一任务窗口的模块筛选、停止、日志、Artifact 与重启恢复；业务页只保留摘要 | AC parser/repository/job/API/Vue/Electron 定向测试 | `NOT_STARTED` | `REAL_DEVICE_PENDING` | `PARTIAL / IMPLEMENTED_UNVERIFIED`；AP/光衰/OmniPeek 导出、扩展/规划完整编辑导入导出、其余 Qt 子页和现场验收仍待完成 |
| 轨道交通 | 独立业务入口已拆分，仍有少量 Qt 交互缺口 | 多个真实 Application Service/Task/Export 闭环；共享 handler 已注册 | 基础资料/MESH/Online MR/点表/在线列车导入导出已接入；轨旁业务报告仍缺公共 Artifact source | `rail` 模块已接统一任务窗口；取消、日志、恢复、Artifact 保存和 LOCAL 强停复用唯一 Task Center | Rail 后端 `85 passed`、Vue `134 passed`、Electron `68 passed`，详见[轨交逐操作矩阵](parity/rail-transit.md) | `MANUAL_DESKTOP_PENDING` | `REAL_DEVICE_PENDING`，但功能缺口未清零 | 会话目录、iPerf 重试、轨旁详情/全量更新、MESH 参数与破坏性动作、人工和现场验收；不得以聚合看板替代 Qt 业务页 |
| 配置采集中心 | 独立左右选择篮、双栏与操作入口已实现 | 真实采集/保存/历史/原子隔离删除/同跨设备历史比较 | Export Process + Artifact 已实现 | Task 持久化、统一任务窗口、检查点取消/失败/恢复已实现 | Config Service/API/Qt diff/Vue mount/typecheck/build 定向验证 | 主工作树 Electron 点击待验收 | H3C SSH/Telnet 与现场权限待验收 | 保持 `IMPLEMENTED_UNVERIFIED`；人工与真实设备验收前不得标 `COMPLETE` |
| 文件管理 | 双栏已实现，待人工对照 | 本地真实；SFTP 自动契约已实现 | 设备文件以 `fd1_*` 受控交付；非 Artifact | 串行队列、取消、重试、DPAPI 恢复和 `.part` 清理已实现 | File Service/Transfer、API 模型、Vue API/状态模型定向测试 | `NOT_STARTED` | `REAL_DEVICE_PENDING` | 原目录/WinSCP 为 `BLOCKED_ON_TASK_WINDOW`；详见专项矩阵 |
| 网络工具 | 部分 | 部分真实 | 部分 | 部分 | 现有 Network/Traffic 定向测试 | `NOT_STARTED` | Agent/无线硬件待验收 | 逐工具纵向闭环与 Qt 对照 |
| 任务中心 | Web 原生页面 | 部分 | 不适用 | 真实 Task 状态机 | Job Center 定向测试 | `NOT_STARTED` | 随业务任务验收 | 不作为业务模块完成的替代证据 |
| Agent 管理 | 部分 | 部分/Fake | Agent 包已有 | 部分 | Agent Controller/Fake 测试 | `NOT_STARTED` | `NOT_STARTED` | 真实 Agent、多 Controller 和现场失败恢复 |
| 命令说明、日志中心、系统设置、功能开关 | 否 | 否 | 否 | 否 | 无对等证据 | `NOT_STARTED` | 不适用 | 尚未迁移 |
| SNMP Center、无线勘测 | 不迁移 | 不迁移 | 不迁移 | 不迁移 | 不纳入 | 不纳入 | 不纳入 | `BLOCKED` |

## 当前推进规则

1. 一次只把一个 Qt 模块做成完整纵向切片，不横向增加只读页面。
2. 自动测试先定向；进入集成和合并前再运行全量 Python、Vue、Electron、Ruff、构建和文档检查。
3. 当前设备管理标记为 `IMPLEMENTED_UNVERIFIED`。共享 Runtime bootstrap、统一任务窗口和诊断 Artifact allowlist 已接通；本机 CRUD、导入导出、任务窗口和终端人工流程通过，且剩余项仅为真实网络设备时，才升级为 `REAL_DEVICE_PENDING`；全部现场项通过后才能升级为 `COMPLETE`。
4. 浏览器开发入口不得产生独立导航、业务分支、发布包或验收矩阵；Native 功能只在 Electron 中开放。
