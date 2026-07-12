# NetConsole 文档索引

本文档集以当前生产代码、测试和构建脚本为事实来源。代码行为变化后，应在同一改动中更新对应 Markdown；若文档与代码冲突，以代码和测试为准并修正文档。

## 核心文档

| 文档 | 用途 | 主要维护对象 | 事实来源 | 必须更新时机 |
| --- | --- | --- | --- | --- |
| [项目总览](../README.md) | 产品定位、模块、架构摘要、运行入口 | 全体开发/维护人员 | `main.py`、`netconsole/app.py`、Feature Registry | 一级模块、启动方式、版本或总体架构变化 |
| [架构](ARCHITECTURE.md) | 分层、启动、后台任务、导出、数据流和线程边界 | 架构与跨域开发 | `netconsole/core`、`services`、`repositories`、`ui` | 新增跨层依赖、后台执行模型或核心服务 |
| [Web 演进架构](WEB_ARCHITECTURE.md) | Desktop/Server/Agent 模式、API、Web Shell、冻结和迁移边界 | Web 演进与桌面宿主开发 | `backend/api`、`desktop`、Task Runtime、RuntimeMode | Web 接入、运行模式、任务 Adapter 或迁移阶段变化 |
| [开发规则](DEVELOPMENT_RULES.md) | 编码、分层、任务、导出、Feature、测试规则 | 所有代码贡献者 | `AGENTS.md`、架构代码、测试 | 开发约束或工程基线变化 |
| [项目级 Codex Skills](CODEX_SKILLS.md) | Skill 清单、路由、组合和维护 | Codex/Skill 维护者 | `.agents/skills`、`AGENTS.md` | Skill 新增、升级、改名或边界变化 |
| [Job Center](JOB_CENTER.md) | 普通后台任务协议、生命周期、取消和迁移规则 | 后台任务开发 | `job_models.py`、`job_runner.py`、`job_registry.py`、`background_*` | Job 协议、事件、handler 或 manager 变化 |
| [导出进程规范](export_process_policy.md) | Export Process、临时文件、取消和 writer 约束 | 报告/导出开发 | `services/export`、`export_worker.py`、export UI helper | 导出类型、协议或文件提交策略变化 |
| [重构地图](REFACTOR_MAP.md) | 当前接管状态、遗留入口和下一步 | 架构维护者 | Registry、domain handlers、生产调用点 | 任务迁移、兼容层或 legacy 收口 |
| [数据与路径](DATA_LAYOUT.md) | 全局/局点/会话/运行时目录和清理边界 | Repository/存储开发 | `core/paths.py`、cleanup、disk manager | 路径、数据库或清理策略变化 |
| [功能模块](FEATURE_MODULES.md) | 一级模块、子功能和 Feature key | UI/版本配置开发 | `core/feature_registry.py`、主窗口注册 | 页面、Tab、动作或 Feature key 变化 |
| [表格与 UI 规范](ui_table_guidelines.md) | 表格、列宽、滚动、主题和 1080p | Qt UI 开发 | UI helpers/widgets、相关测试 | 公共控件、页面布局或主题规则变化 |
| [构建与发布](BUILD_AND_RELEASE.md) | 构建入口、版本、外部工具和验证 | 发布维护者 | `project/build_release.py`、构建脚本、`core/version.py` | 依赖、打包、版本或发布目录变化 |
| [独立 Agent](AGENT.md) | Windows Go Agent 的边界、能力和集成状态 | 现场采集/远程执行开发 | `agent/`、Agent API/测试 | Agent 能力、协议、命令或发布方式变化 |
| [变更记录](CHANGELOG.md) | 用户可见与架构变更摘要 | 发布/模块维护者 | Git 提交、发行版本 | 每次发布及重要未发布变更 |

## 业务专题

| 文档 | 用途 | 主要维护对象 | 事实来源 | 必须更新时机 |
| --- | --- | --- | --- | --- |
| [Online MR 实时采集](ONLINE_MR_COLLECTION.md) | 多 MR、命令、fping/iPerf、会话、停止与恢复 | 轨道交通采集开发 | `online_mr_*`、`vehicle_mr_online.py`、UI/测试 | 命令、状态、周期、目录或交互变化 |
| [MR/Mesh 日志分析](mr_mesh_log_analysis_rules.md) | 导入、解析、阈值、切换/乒乓、报表 | Mesh 分析开发 | `mesh_*`、规则 JSON、页面/测试 | parser、阈值、图表或报告变化 |
| [SNMP Center](SNMP_CENTER.md) | MIB/OID、查询、批量采集、Trap 和拓扑 | SNMP/MIB 开发 | SNMP models/services/repositories/UI/测试 | 操作、参数、MIB、缓存或 Tab 变化 |
| [AP Identity 总览](AP_IDENTITY.md) | Canonical 模型、resolver、只读接入边界 | AP Identity/接入域开发 | `ap_identity*`、domain handlers、测试 | 模型、优先级、接入点或接管结论变化 |
| [AP Identity 展示评估](AP_IDENTITY_DISPLAY_ASSESSMENT.md) | 允许字段、风险、flag 和不可用状态 | 诊断展示评估 | diagnostics ViewModel、评估测试 | ViewModel、flag、脱敏或展示准入变化 |
| [AP Identity Job 宿主评估](AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md) | 结果流、宿主缺口和阶段 8.3 决策 | Job/诊断宿主评估 | UI 调用链、结果生命周期、测试 | 新增统一详情/历史宿主或结果保留层 |
| [命令参考规范](软件使用命令说明.md) | 命令资源字段、风险和消费者 | 命令/parser 开发 | `resources/command_reference.json`、解析器 | 命令、参数、风险或消费者变化 |

## 规则与兼容资料

- `01`～`08` 编号文档保留中英文项目约束和历史兼容要求；新增实现优先遵守本索引中的核心文档。
- 同一主题只维护一个主文档：数据路径用 `DATA_LAYOUT.md`，导出用 `export_process_policy.md`，Mesh 用 `mr_mesh_log_analysis_rules.md`，变更记录用 `CHANGELOG.md`。
- 评估类文档不等于上线授权；尤其 AP Identity 阶段推进不得解释为生产接管许可。

## 文档维护检查

提交前确认：相对链接可解析、无开发机绝对路径、Feature key 与注册表一致、任务数量/状态来自当前代码、命令与文件名大小写准确、Markdown 为 UTF-8、文档改动未夹带生产代码或配置变化。
