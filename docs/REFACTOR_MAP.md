# NetConsole 重构地图

## 当前基线

正式产品已经收口为 Electron Main/Preload + Vue + FastAPI/Python Core。Qt 源码、入口、依赖和发布链已删除；Browser 仅用于本机开发诊断。历史迁移状态不再作为当前任务清单，模块事实见[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)。

## 活动技术债务

| 领域 | 当前永久入口 | 当前状态 | 下一步 |
| --- | --- | --- | --- |
| Job Center | `TaskApplicationService/TaskRuntime/LocalProcessAdapter` | 协议统一；部分领域仍委托 `legacy_tasks.py` | 按生产调用逐项迁出，保留取消/错误/事件契约 |
| 设备管理 | Device Service -> Router -> Vue | `IMPLEMENTED_UNVERIFIED` | Electron 人工与真实设备 CRUD/连接/导入导出验收 |
| AC/FIT-AP | AC Application/Query Service -> Router -> Vue | `PARTIAL / REAL_DEVICE_PENDING` | 补齐隐藏缺口并做真实 H3C AC 验收 |
| 轨道交通 | Rail/Online MR/MESH Service -> Router -> Vue | `PARTIAL` | 按独立业务闭环验收采集、停止、恢复、Artifact 和报告 |
| 配置采集 | Config Application Service -> Router -> Vue | `IMPLEMENTED_UNVERIFIED` | 真实采集、保存、双栏比较和 Artifact 人工验收 |
| 文件管理 | File Application Service -> Router -> Vue/Bridge | `IMPLEMENTED_UNVERIFIED` | 真实 SFTP、队列恢复和本机动作验收 |
| 网络工具 | Network/Traffic Service -> Router/WS -> Vue | `PARTIAL` | 本地/Agent fping、iPerf、无线扫描实机验收 |
| 命令平台 | Operation -> Resolver -> Versioned Profile -> Adapter | 首个设备 inventory Profile 已接入 | AC/MR/配置/文件命令按证据逐域接入 |
| Electron 发布 | Electron Builder + 冻结 Backend + 本地工具/合规门 | 基础链已建立 | 完成 E2 依赖/SBOM/许可证与最终制品 smoke |

## 已完成回收

- `src/netconsole/ui/`、`apps/desktop/`、Qt probe、旧 WebShell 和兼容启动入口。
- Qt/PySide/QFluentWidgets 依赖、许可证和发布内容。
- SNMP Center、通用 MIB/OID 平台和无线勘测；用户历史数据不做破坏性清理。
- 七处仅用于 Qt offscreen 的测试环境设置和仓库内遗留 Qt 字节码缓存。
- 旧 Qt/Web 迁移文档已降为兼容指针，原文由 Git 历史保留。

## 集成门

开发阶段运行定向测试；最终组合运行 Python/Vue/Electron/Agent 全量测试、Ruff、文档链接、架构 Guard 和真实制品 smoke。自动化通过不替代桌面人工和真实设备验收。当前 E10 结果及未解决项见[架构一致性报告](archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md)。
