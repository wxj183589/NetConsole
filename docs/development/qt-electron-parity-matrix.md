# Qt → Electron 功能对等矩阵

## 目的与事实来源

本文按当前 Qt 源码、Vue 路由、FastAPI Router、Application Service 和测试记录判断迁移状态，不以“页面已经存在”作为完成依据。当前系统设置审计基线为 `main@ee88fd01`。

正式产品入口固定为：

```text
Electron Desktop → Vue → FastAPI → Application Service → Domain / Infrastructure
```

- Electron Desktop 是永久桌面产品和 Qt 业务迁移目标。
- Qt 已退出正式发布与回退产品范围；模块达到 `COMPLETE` 前保留对应源码作为迁移事实依据，达到真实验收门后再删除。
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
| 设备管理 | 设备管理 | `DeviceManagementPage`：`src/netconsole/ui/pages/device_management_page.py`；相关 Dialog/Widget 见专项文档 | `/network/devices` / `DeviceManagementView.vue` | 列表、筛选、分页、当前页选择、CRUD、分组、连接测试、采集、详情/历史、终端、CSV/SecureCRT/OmniPeek | `DeviceManagementWebService`；`device_management_router.py` | 真实数据库、Task、Export Process、受控 Artifact、Desktop Action 与统一任务窗口已接入；人工桌面与真实设备仍待验收 | `IMPLEMENTED_UNVERIFIED` |
| AC 管理 | AC 管理及其子页 | `AcManagementPage`、`TracksideApPlanPage`、`TracksideApServicePage` | `/ac-management/*` / `views/ac-management/` | FIT-AP、光衰、扩展、Mesh、规划和受控 AC 操作 | AC Query/Application Service；AC Router | 查询、部分受控动作和 Fake 能力并存，独立页面仍缺失 | `PARTIAL` |
| 轨道交通 | 轨道交通及其子页 | `RailTransitPage`、`CarNetworkDiagnosticPage`、`OnlineMrCollectionPage`、`MeshLogAnalysisPage` 等 | `/rail-transit/*` / `views/rail-transit/` | 基础资料、在线列车、车地通信、车内检测、Online MR、Mesh 分析和报告 | Rail/Online MR/Mesh Application Service；相关 Router | 轨交 Job handler、统一任务窗口、连续采集、点表、会话备注和解析等真实纵向链路已接入；Qt 剩余按钮、Electron 人工对照和真实设备验收仍未完成，详见[轨交逐操作矩阵](parity/rail-transit.md) | `PARTIAL / IMPLEMENTED_UNVERIFIED` |
| 配置采集中心 | 配置采集中心 | `ConfigCollectionCenterPage`、`ConfigLifecycleWorker/Service`、`ConfigDiffViewer`；详见 [配置采集对等矩阵](parity/config-collection.md) | `/config-center` / `ConfigCollectionView.vue` | running/saved/diff 真实采集、`save force`、批量、历史/内容/删除、同/跨设备双栏比较、差异导航、导出/Artifact、取消/失败/恢复 | `ConfigCollectionApplicationService`；Config Router；config domain handlers | 真实纵向链、跨设备左右篮、共享任务窗口和 mount 自动化已接入；Electron 人工与真实 H3C 设备待验收 | `IMPLEMENTED_UNVERIFIED` |
| 文件管理 | 文件管理 | `FileManagementPage`：`src/netconsole/ui/pages/file_management_page.py`；详见 `development/parity/file-management.md` | `/file-manager` / `FileManagementView.vue` | 本地与设备双栏、筛选、连接、导航、传输队列、恢复、MESH 导入和桌面动作 | `FileManagementApplicationService`；File Router | 双栏、持久队列、受控目录和固定 WinSCP Bridge 已实现；Electron 人工、真实 SFTP/MR 待验收 | `IMPLEMENTED_UNVERIFIED` |
| 网络工具 | 网络工具 | `NetworkToolsPage`、`NetworkToolboxPage`、`IperfBandwidthPage`、`WirelessScanPage` | `/network-tools/{traffic,toolbox,wireless-scan}` / `views/network-tools/` | IPv4/IPv6/VLSM/子网/汇总/反掩码；单次/持续/批量/网段/TCP Ping；fping/iPerf；停止、结果、日志和导出 | Network/Traffic Application Service；Network/Traffic Router；共享 Task/Export/Artifact | 核心真实闭环已接入；IPOP 已接系统设置和语义 Native Bridge，真实 Agent/无线硬件与人工并排验收未完成 | `PARTIAL` |
| 无线扫描 | 网络工具 → 无线扫描 | `WirelessScanPage` | `/network-tools/wireless-scan` / `WirelessScanView.vue` | 网卡与扫描源、过滤、启停、自动刷新、项目、历史、Raw、详情和 CSV/XLSX Artifact | `NetworkToolsApplicationService`；Wireless Scan Job/Export；共享 tasks store | 正式路由和真实 Windows 扫描链已接入，不再以 Fake 作为完成证据；待真实无线网卡、WLAN API/netsh 降级与 Electron 人工验收 | `REAL_DEVICE_PENDING` |
| 任务中心 | Qt 中分散任务进度 | 多个进度 Dialog/Worker | `/tasks` / `JobCenterView.vue` | 列表、详情、日志、取消、恢复 | `TaskApplicationService`、`JobCenterQueryService`；Job Router | 通用任务中心真实可用，但需随业务模块逐项验收 | `PARTIAL` |
| Agent 管理 | 无完整 Qt 一级入口 | Online MR Agent 相关 Dialog | `/agents` / `AgentListView.vue` | Profile、健康、工具、任务、包和远程执行入口 | Agent Controller Service；Agent Router | 真实 Controller 路径与 Fake 验收并存，真实 Agent 环境未通过 | `PARTIAL` |
| 命令说明 | 命令说明 | `CommandReferencePage` | `/command-reference` / `CommandReferenceView.vue` | 实时搜索、模块/设备/厂商/协议/类别/风险筛选、Qt 事实详情、复制、刷新、Markdown 导出 | `CommandReferenceApplicationService`；`command_reference_router.py`；真实 Export Process 与公共 `WebArtifactStore` 已接通 | 正式 Feature/导航、共享 TaskWindow 模块筛选、真实取消、Artifact 和共享动态 locale 已接入；Electron 人工验收待完成 | `IMPLEMENTED_UNVERIFIED` |
| 应用日志与安全维护（日志中心） | 日志；设置 → 磁盘清理/更新日志/开源许可/关于 | `AppLogPage`、`DiskCleanupDialog`、`ChangelogDialog`、`OpenSourceNoticeDialog`、`AboutDialog` | `/logs` / `SystemMaintenanceView.vue` | 日志搜索、级别、分页、刷新、复制、清空和导出；白名单扫描/清理；更新日志；依赖扫描、复制、外链和 TXT/XLSX 导出；关于信息 | `SystemMaintenanceApplicationService`；System Maintenance Router；现有 Job/Export Process | 真实查询、清空、1～365 天白名单扫描/选择/确认清理、部分进度、取消/恢复和语义化本机请求已接入；CSV/TXT/XLSX 使用公共 Artifact 契约和安全显示名 | `IMPLEMENTED_UNVERIFIED` |
| 系统设置 | 设置 | `SettingsPage` | `/settings` / `SystemSettingsView.vue`，仅 Electron Desktop 正式可达 | 当前已接线的主题、语言、主题色；iperf/fping/IPOP；三类终端路径、会话根、端口/编码；保存/重载/默认恢复；局点与维护入口 | `SettingsApplicationService` / Settings Router / 严格 Native Bridge | 设置文件读写、冲突/损坏/失败回滚、外观预览与离页恢复已闭环；全局 i18n 和桌面人工仍未完成 | `PARTIAL` |
| 功能开关 | 功能开关配置 | `FeatureFlagsPage` | 集成在 `/settings`；仅源码开发态显示 | 四个布尔状态完整读写、影响预览、确认、恢复 | 中央 Feature Registry / Gate / customer profile | 自动化闭环；打包态强制隐藏并拒绝 API | `IMPLEMENTED_UNVERIFIED` |
| SNMP Center | SNMP 中心 | 旧 Qt 能力已批准删除 | 无 Electron 正式入口 | 无 | 活动代码、资源和依赖已删除 | 不迁移、不重建；设备 SNMP v1/v2c 单独保留 | `REMOVED` |
| 无线勘测 | 无线勘测 | 旧 Qt 能力已批准删除 | 无 Electron 正式入口 | 无 | 活动代码已删除 | 不迁移、不重建；网络工具无线扫描单独保留 | `REMOVED` |

## 验收矩阵

| 模块 | UI 对等 | 功能对等 | 导入/导出 | 实时任务、停止与恢复 | 自动测试证据 | 人工验收 | 真实设备验收 | 当前缺口 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 设备管理 | Qt 操作区、表格、表单、详情、分组、导入导出、终端和紧凑任务摘要已形成 Electron 实现 | 真实 CRUD/分组、已保存设备与未保存表单连接测试、采集、诊断、终端受控启动 | CSV 重复策略与确认；诊断 ZIP；CSV/模板/SecureCRT/OmniPeek 实际 Artifact；公共 capability DTO | 公共 Task 持久化与轮询；统一任务窗口负责停止、日志、Artifact、重试和恢复；页面不再私建任务系统 | `tests/test_device_management_web_api.py`、`tests/test_device_import_export.py`、`tests/test_local_process_adapter.py`、`tests/test_job_center_web_api.py`、`DeviceManagementView.mount.test.ts` | CRUD、导入导出、任务窗口及 SecureCRT/Xshell/PuTTY 为 `MANUAL_DESKTOP_PENDING` | SSH/Telnet/SNMP、采集、光模块和诊断待真实设备 | `IMPLEMENTED_UNVERIFIED`；人工软件流程通过后再按剩余项升级为 `REAL_DEVICE_PENDING` |
| AC 管理 | FIT-AP 主页面已接打开 AC Web、AC 信息、普通资源、AP 详情深度、光衰更新、批量删除、元数据导入/保存和 Radio/LLDP/光衰历史；受控页已接 Qt 两项 AC 写操作 | HTTPS 外部打开、四类采集、批量删除、CSV/XLSX 元数据导入、详情保存、历史分页与两项固定写操作均为真实闭环，无 AC Fake 执行 | 部分 | AC owner 已接统一任务窗口的模块筛选、停止、日志、Artifact 与重启恢复；业务页只保留摘要 | AC parser/repository/job/API/Vue/Electron 定向测试 | `NOT_STARTED` | `REAL_DEVICE_PENDING` | `PARTIAL / IMPLEMENTED_UNVERIFIED`；AP/光衰/OmniPeek 导出、扩展/规划完整编辑导入导出、其余 Qt 子页和现场验收仍待完成 |
| 轨道交通 | 独立业务入口已拆分，仍有少量 Qt 交互缺口 | 多个真实 Application Service/Task/Export 闭环；共享 handler 已注册 | 基础资料/MESH/Online MR/点表/在线列车导入导出已接入；轨旁业务报告仍缺公共 Artifact source | `rail` 模块已接统一任务窗口；取消、日志、恢复、Artifact 保存和 LOCAL 强停复用唯一 Task Center | Rail 后端 `85 passed`、Vue `134 passed`、Electron `68 passed`，详见[轨交逐操作矩阵](parity/rail-transit.md) | `MANUAL_DESKTOP_PENDING` | `REAL_DEVICE_PENDING`，但功能缺口未清零 | 会话目录、iPerf 重试、轨旁详情/全量更新、MESH 参数与破坏性动作、人工和现场验收；不得以聚合看板替代 Qt 业务页 |
| 配置采集中心 | 独立左右选择篮、双栏与操作入口已实现 | 真实采集/保存/历史/原子隔离删除/同跨设备历史比较 | Export Process + Artifact 已实现 | Task 持久化、统一任务窗口、检查点取消/失败/恢复已实现 | Config Service/API/Qt diff/Vue mount/typecheck/build 定向验证 | 主工作树 Electron 点击待验收 | H3C SSH/Telnet 与现场权限待验收 | 保持 `IMPLEMENTED_UNVERIFIED`；人工与真实设备验收前不得标 `COMPLETE` |
| 文件管理 | 双栏已实现，待人工对照 | 本地真实；SFTP 自动契约与固定桌面动作已实现 | 设备文件以 `fd1_*` 受控交付；非 Artifact | 串行队列、取消、重试、DPAPI 恢复和 `.part` 清理已实现 | File Service/Transfer、Desktop Action/API、Vue、Electron IPC 定向测试 | `MANUAL_DESKTOP_PENDING` | `REAL_DEVICE_PENDING` | known_hosts、真实 SFTP/MR、大文件异常恢复和 WinSCP 点击待验收；详见专项矩阵 |
| 网络工具 | 核心页面齐全 | Network/Traffic/Wireless 真实 Service | CSV/XLSX Artifact 已有 | 共享 Task 状态、停止、恢复和 Traffic WebSocket；历史 `controller` owner 仅按明确 Traffic task type 接入统一窗口 | Network/Traffic API、Service、Job、Artifact 与 Vue 定向测试 | `NOT_STARTED` | Agent/iPerf/无线硬件待验收 | IPOP 设置与语义 Bridge 已接；人工和真实硬件未验收，未达到 `REPLACE_READY` |
| 任务中心 | Web 原生页面 | 部分 | 不适用 | 真实 Task 状态机 | Job Center 定向测试 | `NOT_STARTED` | 随业务任务验收 | 不作为业务模块完成的替代证据 |
| Agent 管理 | 部分 | 部分/Fake | Agent 包已有 | 部分 | Agent Controller/Fake 测试 | `NOT_STARTED` | `NOT_STARTED` | 真实 Agent、多 Controller 和现场失败恢复 |
| 系统设置、功能开关 | 设置表单与内部开关页已实现；不迁移 Qt 明示未实现控件 | 真实 `settings.json`、中央 Feature profile 与严格 DTO；外观有预览/确认/失败及离页恢复 | 不适用 | 不适用 | SettingsStore/API、Vue mount、Electron IPC 定向测试 | `MANUAL_DESKTOP_PENDING` | 外部工具为 `REAL_DEVICE_PENDING` | `PARTIAL`；全局业务模块语言消费为 `BLOCKED_ON_GLOBAL_I18N` |
| 命令说明 | 页面和正式导航已实现 | 250ms 实时搜索、竞态保护、筛选、Qt 事实详情、复制与刷新已实现 | Markdown ExportJob 与公共 Artifact 已实现；公开名不含 UUID/内部路径 | 严格命名 localStorage 恢复当前任务 ID；模块串行轮询 `/exports/{task_id}`，取消后继续收敛到服务端终态，临时失败按固定延迟重试，仅终态、404 或卸载时释放；Electron PlatformAdapter、TaskWindow validator、模块筛选和真实 owner 取消已接通 | `tests/test_command_reference_web_api.py`、`tests/test_command_reference.py`、真实挂载 `CommandReferenceView.test.ts`、公共 Job Center Artifact 测试 | `MANUAL_DESKTOP_PENDING` | 不适用 | `IMPLEMENTED_UNVERIFIED`；共享动态 locale 已接，仍需 Electron 人工搜索、复制、导出、取消和 Artifact 保存验收 |
| 应用日志与安全维护 | 是（待人工对照） | 真实服务 | 公共 Export Process + Artifact 已实现 CSV/TXT/XLSX | 真实任务、唯一取消终态、部分进度与重启恢复 | `test_system_maintenance_web.py`、`test_app_auto_cleanup.py`、`SystemMaintenanceView.test.ts`、API 测试、typecheck/build | `MANUAL_DESKTOP_PENDING` | 不适用 | 自动化完成；仍需 Electron 人工复制、扫描选择、确认/取消、Artifact 保存、错误和重启恢复验收 |
| SNMP Center、无线勘测 | 已删除 | 已删除 | 已删除 | 已删除 | 不纳入 | 不纳入 | 不纳入 | `REMOVED` |

## 系统设置 Qt 事实矩阵

只统计 `SettingsPage` 当前实际接线的控件；Qt 中明确标注“未实现”且禁用的 Mica、紧凑表格、全局并发/超时、日志保留、原始回显、默认下载/备份/报告目录和 MIB 目录不作为本轮迁移完成项。

| Qt 可达操作 | Electron 归属与实现 | 当前结论 |
| --- | --- | --- |
| 主题、主题色 | 设置页即时预览；保存失败、取消、重载和确认离页均恢复已保存外观 | 自动化通过；`MANUAL_DESKTOP_PENDING` |
| 语言 | 共享响应式 runtime 已供 Shell 与设置页消费，保存后重启恢复 | 其他业务模块尚未消费，`BLOCKED_ON_GLOBAL_I18N` |
| iperf、fping、IPOP 路径 | `selectSettingsTool(tool_id)` 原生选择；main、保存 API 和真实执行点按受控 EXE 名称复验 | 恶意路径负例通过；`REAL_DEVICE_PENDING` |
| 终端类型与路径 | SecureCRT/Xshell/PuTTY 三个独立持久键；切换类型读取对应值 | 挂载交互和后端持久化测试通过；`MANUAL_DESKTOP_PENDING` |
| SecureCRT 会话根、SSH/Telnet 端口、CRT 编码 | 严格 DTO 写入既有 `settings.json`，目录仅经语义 Bridge 选择 | 自动化通过；`MANUAL_DESKTOP_PENDING` |
| 保存、重载、恢复表单默认值 | 版本 CAS、原子替换、损坏拒写、失败回滚；默认值只改表单，保存后才落盘 | 自动化通过 |
| 打开配置目录 | `executeSettingsAction(open_settings_config)`，后端只打开 `PathResolver` 受控目录 | `MANUAL_DESKTOP_PENDING` |
| IPOP 测试启动 | `executeSettingsAction(launch_ipop)`，后端重新校验已保存 `IPOP.EXE` | `REAL_DEVICE_PENDING` |
| 当前局点名称、路径 | Settings DTO 读取当前 `site_name` 与 `PathResolver.site_dir` | 自动化数据链已接；桌面显示待人工 |
| 新建局点、切换局点 | 归 Shell 局点入口，不在 Settings Application Service 复制局点业务 | Shell 集成仍需统一验收，系统设置保持 `PARTIAL` |
| 打开当前局点目录 | `executeSettingsAction(open_current_site)`，后端只解析当前局点受控目录 | `MANUAL_DESKTOP_PENDING` |
| 磁盘清理 | 归日志维护页面/服务，不在设置页复制清理逻辑 | 未与设置入口统一集成，系统设置保持 `PARTIAL` |
| 更新日志、开源许可 | 归 Shell 关于入口 | 未与设置入口统一集成，系统设置保持 `PARTIAL` |
| 功能开关查看、修改、预览、恢复 | 设置页内部区块复用中央 Registry/Gate/customer profile；写入、预览、恢复均确认 | 源码开发态自动化通过；打包态隐藏并拒绝 API |

系统设置整体不能标记为 `IMPLEMENTED_UNVERIFIED` 或 `COMPLETE`：全局语言、Shell/日志维护归属集成与真实桌面动作仍未清零。SNMP Center 与无线勘测已删除，不得借系统设置或历史 profile 恢复。

## 当前推进规则

1. 一次只把一个 Qt 模块做成完整纵向切片，不横向增加只读页面。
2. 自动测试先定向；进入集成和合并前再运行全量 Python、Vue、Electron、Ruff、构建和文档检查。
3. 当前设备管理标记为 `IMPLEMENTED_UNVERIFIED`。共享 Runtime bootstrap、统一任务窗口和诊断 Artifact allowlist 已接通；本机 CRUD、导入导出、任务窗口和终端人工流程通过，且剩余项仅为真实网络设备时，才升级为 `REAL_DEVICE_PENDING`；全部现场项通过后才能升级为 `COMPLETE`。
4. 浏览器开发入口不得产生独立导航、业务分支、发布包或验收矩阵；Native 功能只在 Electron 中开放。

### 应用日志与安全维护共享契约

本模块不复制 `WebArtifactStore`、Artifact manifest 或任务状态。`system_logs_current`、`system_logs_all`、`system_open_source_txt`、`system_open_source_xlsx` 均由公共 Store 固定解析到 `paths.site_files_dir(site_id) / "system_maintenance" / "outputs"`；公开任务结果使用 manifest `display_name`，不公开 UUID 物理名或服务端路径。TXT 使用真实 `.txt` 后缀、`text/plain; charset=utf-8` 和可读下载名，不再用 `.md` 伪装。当前自动化门已通过，状态保持 `IMPLEMENTED_UNVERIFIED / MANUAL_DESKTOP_PENDING`，不能据此隐藏 Qt 对照入口。
