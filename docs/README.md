# NetConsole 文档索引

本文档集以当前生产代码、测试和构建脚本为事实来源。代码行为变化后，应在同一改动中更新对应 Markdown；若文档与代码冲突，以代码和测试为准并修正文档。

## 本次专题

- [UI 导入导出文件选择审计（2026-07-30 整改证据）](development/import-export-dialog-audit.md)
- [轨旁 AP 逐站规划](AP_MANAGEMENT_VLAN_GROUPS.md)
- [轨旁 AP 主数据与关联模型](rail-transit/TRACKSIDE_AP_DOMAIN_MODEL.md)
- [轨旁 AP 业务只读快照](TRACKSIDE_AP_BUSINESS_SNAPSHOT.md)
- [轨旁 AP 业务 WPS 云文档同步](WPS_TRACKSIDE_AP_SYNC.md)
- [车内通信检测：点表与固定拓扑](rail-transit/train-communication/README.md)
- [检测点表模型](rail-transit/train-communication/POINT_TABLE.md)
- [检测任务流程](rail-transit/train-communication/CHECK_WORKFLOW.md)
- [配置采集与快照对比](CONFIG_COLLECTION.md)
- [CBTC 旧 Wireshark DLL 逆向状态](reverse-engineering/CBTC_WIRESHARK_DLL.md)
- [MESH 身份、存储协调与 RSSI 调查记录](mesh_analysis_identity_rssi_investigation.md)
- [动态图共享时间轴与稳定性规则](../apps/web/src/components/charts/README.md)

## 核心文档

| 文档 | 用途 | 主要维护对象 | 事实来源 | 必须更新时机 |
| --- | --- | --- | --- | --- |
| [项目总览](../README.md) | 产品定位、模块、架构摘要、运行入口 | 全体开发/维护人员 | Electron Main、`main.py`、Electron Runtime、Feature Registry | 一级模块、启动方式、版本或总体架构变化 |
| [用户文件导入导出契约](IMPORT_EXPORT_INTERACTION.md) | 用户文件选择、固定导出动作、任务绑定、Artifact 最终落盘和受管下载例外 | Web/Electron/Export 开发 | `exportActionRegistry`、`useUserSelectedExport`、Electron BackendDownloadManager | 新增或修改任一导入、导出、下载、模板或 Artifact 保存入口 |
| [永久架构与后续演进](ARCHITECTURE_NEXT.md) | Electron-only 永久层、不可回退边界与后续演进顺序 | 架构负责人 | 当前代码、最终迁移矩阵与目录规范 | 永久技术边界或演进顺序变化 |
| [架构一致性审计](ARCHITECTURE_COMPLIANCE.md) | Electron-only 最终分层、Qt 历史迁移映射、自动 Guard、例外和发布阻塞规则 | 架构、迁移与发布负责人 | Git 历史、实际依赖、迁移矩阵、Guard 和非 Qt 测试 | 分层规则、Qt 删除范围、Guard 或最终发布门变化 |
| [Electron Desktop](ELECTRON_DESKTOP.md) | Electron main/preload、Python 生命周期、临时令牌、开发/生产资源与 Qt 历史边界 | Desktop/Core/Web 开发 | `apps/desktop_electron`、`apps/web/src/platform`、`backend/electron_runtime.py` | Electron 生命周期、安全桥接、启动或发布状态变化 |
| [架构](ARCHITECTURE.md) | Electron-only 分层、启动、后台任务、导出、数据和安全边界 | 架构与跨域开发 | `apps/desktop_electron`、`apps/web`、`src/netconsole/backend`、Services/Repositories | 新增跨层依赖、运行形态或核心服务 |
| [最终迁移矩阵](architecture/MIGRATION_MATRIX.md) | 已删除 Qt 路径分类、永久去向、自动证据与当前验收状态 | 架构、迁移与验收负责人 | Git 删除历史、Feature/Navigation Registry、生产代码和测试 | 历史映射、模块状态或验收结论变化 |
| [E10 架构一致性报告](archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md) | Qt 遗留回收证据、扫描分类、未解决项与发布门 | 架构与发布负责人 | 当前工作树、Guard、定向测试和最终制品 | E10 结果、风险或发布门变化 |
| [Electron/Vue/FastAPI 架构](WEB_ARCHITECTURE.md) | 唯一 Renderer、API、Browser 诊断和 Desktop Bridge 边界 | Web 与桌面宿主开发 | `src/netconsole/backend/api`、`apps/desktop_electron`、`apps/web` | Web 接入、运行模式或 Bridge 变化 |
| [Web 迁移计划（历史兼容）](WEB_MIGRATION_PLAN.md) | 已结束双轨迁移的兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [Web 迁移矩阵（历史兼容）](WEB_MIGRATION_MATRIX.md) | 已结束双轨矩阵的兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [Desktop WebHost](WEB_HOST.md) | Electron Web Runtime、开发诊断入口及历史 Qt WebHost 边界 | Desktop/Core/Web 开发 | Electron Runtime、`src/netconsole/launcher`、Git 历史迁移证据 | WebHost 生命周期、认证、诊断入口或打包变化 |
| [Qt/Electron 对等矩阵（历史兼容）](development/qt-electron-parity-matrix.md) | 旧详细矩阵兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [轨道交通逐操作矩阵（历史兼容）](development/parity/rail-transit.md) | 已冻结的逐操作迁移规格兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [设备管理对等规格（历史兼容）](development/parity/device-management.md) | 已冻结的逐字段/逐操作规格兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [设备管理与设备详情](../apps/web/src/views/devices/README.md) | 设备列表、快速详情抽屉、完整详情页、数据来源、Command Profile 与验收边界 | Device/Application/API/Vue 开发 | Device Detail Application/Query Service、DTO/API、版本化 Profile 和 Vue | 设备字段、能力、刷新任务、页签或验收状态变化 |
| [文件管理对等规格（历史兼容）](development/parity/file-management.md) | 已冻结的双栏/SFTP/下载队列规格兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [设备文件下载](device-files/README.md) | Electron 设备文件只读浏览、SFTP、主机密钥、下载任务，以及同模块下的配置采集中心和设备诊断下载入口 | File Service/Task Center/Web | 当前代码、历史取证和定向测试 | SFTP、主机密钥、下载或安全边界变化 |
| [配置采集与快照对比](CONFIG_COLLECTION.md) | 配置采集、快照选择、双栏 Diff、裁剪、导出和恢复 | Config Service/Task Center/Web | 配置 handler、API、Vue 与定向测试 | 快照、对比、裁剪、导出或恢复语义变化 |
| [Desktop Native Bridge 契约](DESKTOP_NATIVE_BRIDGE.md) | Electron 本机选择器、受控目录/Artifact、终端与通知的严格白名单 | Electron 桌面外壳与本机动作开发 | RuntimeMode、Desktop session、Feature Gate、PathResolver | 新增或修改任一本机 Bridge 动作前 |
| [工具集](EXTERNAL_TOOL_COLLECTION.md) | 本机第三方 EXE 注册、分类、图标、状态、仅 ID 启动和独立 userData 存储 | Electron/Vue 桌面工具开发 | ExternalToolStore、ExternalToolService、专用 IPC 与工具集页面 | 工具模型、持久化、选择器、启动或安全边界变化 |
| [外部终端白名单](external-terminal/README.md) | SecureCRT、Xshell、PuTTY 的受控可执行文件名、选择器和启动复验边界 | Desktop/Device/Application 开发 | Shared Bridge、Electron Main、Python Settings Tool Validation | 终端类型、文件名或启动边界变化 |
| [表单与路径字段](ui/FORM_AND_PATH_FIELDS.md) | 路径输入、按钮组、字段反馈和窄窗口布局规范 | Vue Renderer 开发 | `NcExecutablePathField` 与系统设置页面 | 新增或修改路径选择字段时 |
| [开发规则](DEVELOPMENT_RULES.md) | 编码、分层、任务、导出、Feature、测试规则 | 所有代码贡献者 | `AGENTS.md`、架构代码、测试 | 开发约束或工程基线变化 |
| [下一阶段开发指南](DEVELOPMENT_GUIDE.md) | 永久功能调用链、前端/API/Electron 硬边界和迁移检查 | Web/Core/Desktop 开发 | 下一代架构、开发规则、目录规范 | 新功能链路或跨层约束变化 |
| [API / Application 边界审计](API_APPLICATION_BOUNDARY_AUDIT.md) | 18 个 FastAPI Router 的分层证据、判级和治理顺序 | Web/API/Core 开发 | Router、组合根、Application/Query Service | Router 依赖、用例编排或存储错误边界变化 |
| [项目级 Codex Skills](CODEX_SKILLS.md) | Skill 清单、路由、组合和维护 | Codex/Skill 维护者 | `.agents/skills`、`AGENTS.md` | Skill 新增、升级、改名或边界变化 |
| [Job Center](JOB_CENTER.md) | 普通后台任务协议、生命周期、取消和迁移规则 | 后台任务开发 | `job_models.py`、`job_runner.py`、`job_registry.py`、`background_*` | Job 协议、事件、handler 或 manager 变化 |
| [数据库与升级](04-database.md) | SQLite 分类、迁移边界、统一升级编排与 Adapter 接入状态 | Repository/数据库开发 | `core/database.py`、`services/database_upgrade/`、各数据库 Adapter | schema、备份、切换、回滚或恢复规则变化 |
| [导出进程规范](export_process_policy.md) | Export Process、临时文件、取消和 writer 约束 | 报告/导出开发 | `services/export`、`export_worker.py`、export UI helper | 导出类型、协议或文件提交策略变化 |
| [重构地图](REFACTOR_MAP.md) | 当前接管状态、遗留入口和下一步 | 架构维护者 | Registry、domain handlers、生产调用点 | 任务迁移、兼容层或 legacy 收口 |
| [CBTC 旧 Wireshark DLL 逆向状态](reverse-engineering/CBTC_WIRESHARK_DLL.md) | RE 证据清单、结论等级、复现要求和当前缺口 | 协议分析与维护人员 | 仓库样本、脚本、CSV、测试包和 Git 历史 | 新增样本、探针、算法证据或结论等级变化 |
| [数据与路径](DATA_LAYOUT.md) | 全局/局点/会话/运行时目录和清理边界 | Repository/存储开发 | `core/paths.py`、cleanup、disk manager | 路径、数据库或清理策略变化 |
| [局点与数据存储](storage/README.md) | 局点 Registry、数据根迁移、备份恢复和 `.ncsite` 包 | Storage/Core/Desktop 开发 | `services/site_storage.py`、Electron bootstrap、`/api/v1` | 局点、数据根、迁移或包格式变化 |
| [仓库目录规范](development/repository-layout.md) | 根目录白名单、应用边界、运行数据和新增文件检查 | 所有开发/维护人员 | `AGENTS.md`、实际目录和构建脚本 | 顶层布局、目录职责或迁移映射变化 |
| [测试基线](TEST_BASELINE.md) | 定向测试、测试数据隔离和合并前全量门槛 | 所有开发/维护人员 | pytest、Vitest、Ruff、构建与文档检查 | 测试隔离、执行顺序或最终门槛变化 |
| [Web 双轨迁移第一批更新记录](development/web-migration-wave-1.md) | 当前并行任务、提交、验证、延期项和合并门槛 | Web 迁移指挥与集成 | 独立工作树提交、测试和集成分支 | 第一批任务状态、测试或范围变化 |
| [Electron 对等迁移第二波归档](development/electron-parity-wave2.md) | 第二波集成、验证、发布边界和任务/worktree 回收记录 | Electron 迁移指挥与集成 | `main` 提交、自动测试与资源清理结果 | 第二波范围、验收或归档状态变化 |
| [Electron-only 后续开发交接档案](archive/migrations/electron-only/HANDOFF-2026-07-18.md) | Electron-only E1～E6A、命令平台、开发接口和 E2 发布合规的决策、证据与后续门禁 | Electron-only 迁移指挥与后续集成 | 当前 Git 历史、专项归档、生产代码和测试 | 阶段状态、最终提交、发布门或固定产品边界变化 |
| [局点生命周期与运行日志整改交接](archive/migrations/electron-only/E11-site-lifecycle-runtime-log-2026-07-21.md) | Legacy/Demo 局点审计回收、软件运行日志三天保留、真实清理证据和后续验收顺序 | 存储与系统维护负责人 | 当前代码、定向测试、正式运行日志清理前后快照 | 局点回收执行状态、日志清理边界或真实验收结论变化 |
| [Codex 会话收尾交接档案](archive/migrations/electron-only/HANDOFF-2026-07-21.md) | 2026-07-21 会话结束时的 `main` 快照、近期提交、MESH/Online MR 状态、未提交工作区和后续恢复顺序 | 后续 Codex/开发接手人 | 当前 Git 历史、最后任务验证、工作区状态和专题文档 | 会话收尾、后续接手或当前工作区状态变化 |
| [Electron-only E1 阶段归档](archive/migrations/electron-only/E1-2026-07-18.md) | Qt 启动入口、旧 WebShell、无调用测试和兼容导入回收记录 | Electron-only 迁移指挥与后续开发 | `refactor/electron-only` 提交、定向测试和当前阻塞 | E1 收口、E2 构建链或 Qt 依赖边界变化 |
| [Electron-only E2 依赖与发布合规归档](archive/migrations/electron-only/E2-dependencies-release-compliance-2026-07-18.md) | Python/Node 依赖分层、锁定环境、SBOM、许可证和 Qt 发布 Guard 的整改记录 | Electron-only 发布、依赖与合规维护 | 依赖清单、约束文件、Notice/SBOM、打包脚本和定向测试 | 运行依赖、第三方组件、许可证事实或发布门变化 |
| [Electron-only E4 数据目录迁移归档](archive/migrations/electron-only/E4-2026-07-18.md) | 用户应用数据根、历史数据迁移、冲突和测试残留清理记录 | Electron-only 迁移指挥与存储维护 | `PathResolver`、Electron Main、迁移 manifest、定向测试 | 数据根、迁移规则、清理白名单或回退状态变化 |
| [Electron-only E5 启动性能归档](archive/migrations/electron-only/E5-2026-07-18.md) | Electron/Python/Vue 单调时间线、首屏关键路径和实测对比 | Electron-only 迁移与性能维护 | Electron Main、Backend lifespan、延迟依赖和真实 smoke 日志 | 启动阶段、依赖加载时机或性能基线变化 |
| [Electron-only E6 数据库调优归档](archive/migrations/electron-only/E6-2026-07-18.md) | SQLite 查询计划、历史索引、旧库兼容和回滚证据 | Repository/数据库与 Electron-only 迁移维护 | `Database` schema、Repository SQL、真实库 Backup 副本和测试 | 主库 schema、索引、迁移或性能证据变化 |
| [Electron-only E10B 架构 Guard 与整改归档](archive/migrations/electron-only/2026-07-18-E10B-architecture-guards-and-remediation.md) | 九个架构门、精确分类、限时例外、整改与回滚证据 | 架构、迁移与发布负责人 | `scripts/architecture`、`config/architecture`、迁移矩阵与定向测试 | Guard、分类、例外或发布阻塞状态变化 |
| [历史残留审计（2026-07-25）](archive/migrations/HISTORICAL_RESIDUE_AUDIT_2026-07-25.md) | stash、WIP、snapshot refs 的去重、主线替代关系和弃用结论 | 架构、迁移与安全维护人员 | Git refs、稳定 patch-id、当前代码路径和凭据状态 | 历史引用、凭据轮换或引用清理状态变化 |
| [配置采集对等矩阵（历史兼容）](development/parity/config-collection.md) | 已冻结的采集、保存、比较和导出规格兼容指针 | 历史维护 | Git 历史与最终迁移矩阵 | 不再作为当前状态源 |
| [Traffic Web 应用边界](development/api-boundary-wave-1/traffic-web-boundary.md) | Traffic 执行端、查询分页、取消/重试和 Router 展示映射边界 | Traffic Web/API 开发 | `TrafficWebApplicationService`、Traffic Router、组合根 | Traffic Web 用例或 REST/WebSocket 契约变化 |
| [功能模块](FEATURE_MODULES.md) | 一级模块、子功能和 Feature key | UI/版本配置开发 | `core/feature_registry.py`、主窗口注册 | 页面、Tab、动作或 Feature key 变化 |
| [表格与 UI 规范](ui_table_guidelines.md) | Vue/Element Plus 表格、列宽、滚动、密度和状态 | Vue UI 开发 | `NcTable`、Element Plus、相关测试 | 公共组件、页面布局或表格规则变化 |
| [NetConsole UI 设计系统](UI_DESIGN_SYSTEM.md) | Vue 3 + Element Plus + ECharts + Design Token 的主题、组件和可视化规范 | Web/UI 开发 | `apps/web/src/theme`、`apps/web/src/styles`、Electron 主题 IPC | Token、主题、组件、窗口背景或图表规范变化 |
| [表格与字段展示标准](ui/TABLE_AND_FIELD_STANDARDS.md) | `NcDataTable`、自动列宽、对齐、缺失值、偏好和增量 Guard | Web/UI 开发 | `apps/web/src/components/table`、`scripts/ui`、表格清单 | 公共表格契约、列定义或迁移状态变化 |
| [表格迁移清单](ui/TABLE_INVENTORY.md) | 所有 Vue 表格的组件、对齐、列宽和整改状态 | Web/UI 开发与验收 | `scripts/ui/export_table_inventory.py` 扫描结果 | 任一表格新增、删除或迁移 |
| [全局确认对话框](ui/CONFIRMATION_DIALOGS.md) | 统一确认类型、风险文案、键盘和安全边界 | Web/UI 开发 | `apps/web/src/components/feedback` | 新增确认动作、风险等级或弹窗行为变化 |
| [构建与发布](BUILD_AND_RELEASE.md) | 构建入口、版本、外部工具和验证 | 发布维护者 | `scripts/build/build_release.py`、构建脚本、`src/netconsole/core/version.py` | 依赖、打包、版本或发布目录变化 |
| [完整版与客户版打包](FULL_AND_CUSTOMER_PACKAGING.md) | Full/Customer 模板、客户交付三态、会话预览、依赖检查和构建门禁 | 发布维护者、功能交付配置人员 | Feature Registry、Settings Application Service、版本准备脚本 | 模板语义、依赖关系、预览或 Profile 门禁变化 |
| [正式包功能矩阵](PACKAGED_FEATURE_MATRIX.md) | 正式生产 Feature、页面/API、自动证据与干净安装人工状态 | 发布维护者、验收人员 | Registry、生产基线、打包 smoke、Windows/跨电脑验收记录 | 正式包功能、Feature 状态或人工验收结果变化 |
| [独立 Agent](AGENT.md) | Windows Go Agent 的边界、能力和集成状态 | 现场采集/远程执行开发 | `apps/agent/`、Agent API/测试 | Agent 能力、协议、命令或发布方式变化 |
| [Agent Controller](AGENT_CONTROLLER.md) | 多 Agent 配置、健康检查、认证、REST/WebSocket 与 Web 管理边界 | Agent 控制面开发 | `services/agent`、`repositories/agent_repository.py`、Agent Router | Controller 模型、探测协议、凭据或调度变化 |
| [Agent 流量测试协议](AGENT_TRAFFIC_API.md) | fping/iPerf 强类型执行、任务事件游标、结果与能力契约 | Agent/流量测试开发 | `apps/agent/internal/{core,fping,iperf,api}`、`AgentHttpClient` | Agent 流量参数、事件、结果或能力变化 |
| [统一流量测试架构](TRAFFIC_TEST_ARCHITECTURE.md) | 本地/Agent 执行、Task 映射、Traffic 事件、数据与恢复边界 | 流量测试与阶段 4C 开发 | `services/traffic`、`TrafficRunRepository`、Traffic handlers | 执行端、状态、事件、存储、恢复或 Web 接入变化 |
| [AC 管理](AC_MANAGEMENT.md) | Electron AC/FIT-AP 查询、受控更新/写操作、光衰、配置和验收边界 | AC/FIT-AP 开发 | AC Application Service/Repository/API/Vue/Task | AC 命令、查询字段、光衰、配置、写操作或验收状态变化 |
| [轨道交通无线业务模型](RAIL_TRANSIT_WIRELESS.md) | 轨旁 AP、AC Mesh-Link、Online MR 与离线分析的业务边界和匹配规则 | 轨道交通无线与 AC Mesh-Link 开发 | `src/netconsole/services/vehicle_mr_online.py`、Mesh-Link Query API/Vue | Mesh-Link 字段、匹配、时效性或采集/分析边界变化 |
| [轨旁 AP 逐站规划](AP_MANAGEMENT_VLAN_GROUPS.md) | 逐站规划、设备管理站点来源、上线统计、历史 VLAN 数据边界和 PVID 核验 | 轨旁 AP/Core/API/Vue 开发 | 基础资料 Application Service、Repository、API 与 Vue | 逐站字段、统计、站点来源、历史数据边界或 PVID 语义变化 |
| [轨旁 AP 主数据与关联模型](rail-transit/TRACKSIDE_AP_DOMAIN_MODEL.md) | 稳定 ID、子页作用域草稿、事务顺序、业务投影、LLDP 精确关联与迁移 | 基础资料、轨旁 AP 和 AP Identity 跨域开发 | Base Data Application/Repository、Trackside Business、AP Identity、Vue | 主数据所有权、关系字段、保存边界、迁移或匹配规则变化 |
| [轨旁 AP 业务只读快照](TRACKSIDE_AP_BUSINESS_SNAPSHOT.md) | 多来源 revision、页面 expected revision、导出冻结 staging、Worker 与 Artifact 一致性 | 轨旁 AP 查询/导出、AP Identity、Job/Artifact | Snapshot/Query/Export Service、API/Vue 与定向测试 | 来源、revision、筛选/选择、staging、错误码或导出元数据变化 |
| [轨道交通地面无人值守](GROUND_UNATTENDED.md) / [风险审计](GROUND_UNATTENDED_RISK_AUDIT.md) | 独立运行窗口、正线分类、全车长 Ping、历史 Syslog、READY ZIP 查询、归档和恢复 | 地面无人值守开发、风险与验收 | `src/netconsole/services/ground_unattended/`、独立 API/Vue | 配置、分类、Ping、Syslog、调度、归档、风险或人工验收状态变化 |
| [轨道交通无线综合看板](RAIL_TRANSIT_WIRELESS_DASHBOARD.md) | 基础设施、列车、任务、Agent 与 Mesh 分析只读聚合 | 轨道交通综合监控开发 | `src/netconsole/services/rail_transit/wireless_dashboard_query_service.py`、对应 API/Vue | 聚合来源、告警映射、刷新或只读边界变化 |
| [车内通信检测](TRAIN_COMMUNICATION_MONITORING.md) | TC1/TC2 固定六节点拓扑、VRRP 虚拟 IP 静态配置、跨端状态和车内通信检测 Task | 轨道交通车内通信开发 | `src/netconsole/services/rail_transit/train_communication_query_service.py`、对应 API/Vue | 节点关联、状态、检测任务或刷新边界变化 |
| [轨道交通基础资料](RAIL_TRANSIT_BASE_DATA.md) | 子页独立快照/草稿/保存、revision 事务、线路参数、设备 station 来源预览、站点模板、站点/区间、轨旁 AP、逐站规划与上线统计、列车/MR 及受控导入 | 轨道交通基础资料开发 | `src/netconsole/application/rail_transit/base_data_application_service.py`、Repository、API/Vue | 字段、校验、编辑会话、来源预览、模板、规划页签或写入边界变化 |
| [变更记录](CHANGELOG.md) | 用户可见与架构变更摘要 | 发布/模块维护者 | Git 提交、发行版本 | 每次发布及重要未发布变更 |

## 业务专题

| 文档 | 用途 | 主要维护对象 | 事实来源 | 必须更新时机 |
| --- | --- | --- | --- | --- |
| [设备厂商导入与采集能力](DEVICE_VENDOR_IMPORT_AND_COLLECTION.md) | 原始厂商、规范化 key、驱动解析、SKIPPED 任务状态和新增驱动接入边界 | 设备管理与采集维护 | `src/netconsole/models/device.py`、`src/netconsole/services/device_collection_support.py` | 厂商导入、驱动注册或跳过状态变化 |
| [Online MR 实时采集](ONLINE_MR_COLLECTION.md) | 多 MR、命令、fping/iPerf、会话、只读查询、最终化与恢复 | 轨道交通采集开发 | `online_mr_*`、`vehicle_mr_online.py`、UI/测试 | 命令、状态、查询、周期、目录、最终化或交互变化 |
| [Online MR Agent 远程执行器](ONLINE_MR_AGENT_EXECUTOR.md) | 单 Agent start/status/normal stop、包导入、截止时间与恢复安全边界 | Online MR Agent 执行开发 | `agent_executor.py`、Agent Client/Controller、Mapping/测试 | Agent 开关、路由、状态、恢复、身份或包收敛变化 |
| [Online MR Agent Fake 验收](ONLINE_MR_AGENT_FAKE_ACCEPTANCE.md) | Web Agent 控制与回环 Fake Agent 的全链路验收、冻结项和复现步骤 | Online MR Web/Agent 联调 | Agent Web Router/Service、Fake Agent、正式 Client/Importer 测试 | Web Agent 契约、Fake 状态机或验收边界变化 |
| [Web 本地 Online MR 受控启停](ONLINE_MR_WEB_CONTROL.md) | Desktop WebHost 的 LOCAL 启停、安全开关、请求白名单和幂等 | Online MR Web 控制开发 | `web_control_service.py`、控制 Router/Vue、ApplicationService | Web 控制路由、安全条件、DTO 或状态变化 |
| [MR/Mesh 日志分析](mr_mesh_log_analysis_rules.md) | 导入、解析、阈值、切换/乒乓、报表 | Mesh 分析开发 | `mesh_*`、规则 JSON、页面/测试 | parser、阈值、图表或报告变化 |
| [AP Identity 总览](AP_IDENTITY.md) | 局点统一索引、AC/Base 优先级、H3C 反查、只读查询与写事件刷新 | AP Identity/接入域开发 | `ap_identity*`、MESH/Vehicle/Wireless/搜索消费者、测试 | schema、来源、优先级、刷新边界或接管入口变化 |
| [AP Identity 消费者审计](AP_IDENTITY_CONSUMER_AUDIT.md) | 各业务 MAC 输入、Resolver、私有 Alias、直查表、revision 与 remap 状态 | AP Identity 消费者收口 | MESH、Ground、Vehicle、Wireless、AC Mesh-Link、轨旁业务 | 新增消费者、批量接口、旁路白名单或整改状态变化 |
| [AP Identity 展示评估](AP_IDENTITY_DISPLAY_ASSESSMENT.md) | 允许字段、风险、flag 和不可用状态 | 诊断展示评估 | diagnostics ViewModel、评估测试 | ViewModel、flag、脱敏或展示准入变化 |
| [AP Identity Job 宿主评估（冻结历史）](AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md) | 旧 Qt 宿主评估与否决边界，只作历史证据 | 历史维护 | Git 历史、当前全局任务中心与诊断模型 | 不再作为新增 Qt 宿主授权 |
| [设备版本兼容性基线](DEVICE_COMPATIBILITY.md) | 代码内置兼容基线、确定性解析、开发期脱敏候选扫描和 Dashboard 适配范围来源 | 设备兼容/命令/parser 开发 | `resources/device_compatibility_profiles.json`、`src/netconsole/services/device_compatibility/`、定向测试 | 新增型号、平台大版本、Release、命令 Profile 或 parser Profile 映射 |
| [命令参考规范](COMMAND_REFERENCE.md) | 命令资源字段、风险和消费者 | 命令/parser 开发 | `resources/command_reference.json`、解析器 | 命令、参数、风险或消费者变化 |
| [ZTE 轨旁交换机 Adapter](ZTE_TRACKSIDE_SWITCH_ADAPTER.md) | ZXR10 5960X-ES 第一阶段范围、采样 Artifact 与阶段二实机清单 | ZTE 轨旁交换机适配 | Adapter、Parser、采样 Job、轨旁 AP API/Vue | ZTE 命令、能力状态、Artifact 或验证等级变化 |

## 规则与兼容资料

- `01`～`08` 编号文档保留中英文项目约束和历史兼容要求；新增实现优先遵守本索引中的核心文档。
- 同一主题只维护一个主文档：数据路径用 `DATA_LAYOUT.md`，导出用 `export_process_policy.md`，Mesh 用 `mr_mesh_log_analysis_rules.md`，变更记录用 `CHANGELOG.md`。
- 评估类文档本身不等于上线授权；AP Identity 当前生产接管范围以 [AP Identity 总览](AP_IDENTITY.md) 列出的代码入口和测试为准。

## 文档维护检查

提交前确认：相对链接可解析、无开发机绝对路径、Feature key 与注册表一致、任务数量/状态来自当前代码、命令与文件名大小写准确、Markdown 为 UTF-8、文档改动未夹带生产代码或配置变化。
